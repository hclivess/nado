from ops import kv_ops
from ops.address_ops import make_address
from protocol import B_MIN, EPOCH_LENGTH, FIDELITY_GAIN, SLASH_BOND_PENALTY, BOND_UNLOCK_DELAY, BRIDGE_ESCROW, DIVIDEND_POOL, POSW_LEASE_EPOCHS, HTLC_ESCROW, SHIELD_ESCROW

# Account state lives in the schemaless `accounts` sub-DB as a msgpack document keyed by address
# (see ops/kv_ops.py). Missing fields default to 0 on read, so adding a field (as we did with
# registered/fidelity) needs NO migration. All key-encoding + (de)serialization is in kv_ops; this
# module keeps the SAME public signatures the old SQLite version exposed, so core_loop / handlers
# are untouched.


def get_account(address, create_on_error=True):
    """Return all account information if the account exists, else (create_on_error) a zero doc.

    Reading no longer PERSISTS an empty row: auto-creating zero rows on a read made the persisted
    account set depend on read traffic (non-deterministic across nodes). Write paths
    (change_balance/change_bonded/...) create the doc as needed, so a zero doc reads identically to
    an absent one (every field defaults to 0)."""
    account = kv_ops.get_account(address)
    if account is not None:
        return account
    if create_on_error:
        return {"address": address, "balance": 0, "produced": 0,
                "bonded": 0, "registered": 0, "fidelity": 0}
    return None


def reflect_transaction(transaction, logger, block_height=None, revert=False):
    # Fee is ALWAYS debited from the sender.
    # The fee is destroyed (credited to no one); it is counted into totals.fees and subtracted
    # from supply, and it drives the elastic block reward via the header cumulative_fees counter.
    sender = transaction["sender"]
    recipient = transaction["recipient"]
    amount = transaction["amount"]
    fee = transaction["fee"]

    # --- mining stake transactions (S4): move coins between spendable balance and `bonded` ---
    if recipient == "bond":
        # lock `amount` of spendable balance into bonded stake; fee is burned (destroyed)
        change_balance(address=sender, amount=-(amount + fee), logger=logger, revert=revert)
        change_bonded(address=sender, amount=amount, logger=logger, revert=revert)
        # stake-weighted bond age for the producer-selection ramp (anti-sudden-whale); revert-exact by txid
        apply_bond_since(sender, amount, block_height, transaction["txid"], revert=revert)
        return
    if recipient == "unbond":
        # UNBOND DELAY: unbond is now a REQUEST, not an instant release. The `amount` STAYS in `bonded`
        # (still slashable AND still selection-weighted) and a release_block = block_height +
        # BOND_UNLOCK_DELAY is recorded; only a matured `withdraw` moves it to spendable balance. This
        # stops a caught equivocator from yanking stake out in the same block to dodge the slash.
        # Fee-exempt (validation enforces fee==0); one pending unbond per address.
        if revert:
            kv_ops.unbond_del(sender)
        else:
            kv_ops.unbond_put(sender, amount, block_height + BOND_UNLOCK_DELAY)
        return
    if recipient == "withdraw":
        # claim a MATURED unbond: move `amount` from bonded -> spendable balance. The tx data carries
        # {amount, release_block} (self-describing), so revert exactly restores the pending entry.
        data = transaction.get("data") or {}
        amt = int(data["amount"])
        change_bonded(address=sender, amount=-amt, logger=logger, revert=revert)
        change_balance(address=sender, amount=amt, logger=logger, revert=revert)
        if revert:
            kv_ops.unbond_put(sender, amt, int(data["release_block"]))
        else:
            kv_ops.unbond_del(sender)
        return

    # --- OPEN-lane mining transactions (S4 two-lane): fee-EXEMPT, no coin movement ---
    # These let a zero-coin identity mine: `register` (one-time, PoW-gated in validation) flips the
    # registered flag; `heartbeat` (one per epoch) records presence + bumps fidelity. Neither moves
    # balance or charges a fee (a 0-balance address could not pay one) — validation enforces fee==0.
    if recipient == "register":
        apply_register(address=sender, epoch=(block_height // EPOCH_LENGTH), logger=logger, revert=revert)
        return

    # --- SLASHING (#15 step 5C): a fee-exempt tx carrying a proven equivocation proof in `data`.
    # validate_transaction already verified the proof + that the offender holds enough bond + is not
    # already slashed at this height, so reflect just extracts (offender, height) and burns the bond.
    if recipient == "slash":
        proof = transaction.get("data") or {}
        offender = make_address(proof["public_key"])
        apply_slash(address=offender, height=proof["block_number"], logger=logger, revert=revert)
        return

    # --- FFG attestation (#6): record/revert a bonded validator's checkpoint attestation. Validation
    # already enforced bonded + one-per-(validator,epoch) + correct checkpoint hash. Revert-symmetric.
    if recipient == "attest":
        data = transaction.get("data") or {}
        epoch, target_hash = data["target_epoch"], data["target_hash"]
        if revert:
            kv_ops.attestation_del(epoch, sender, target_hash)
        else:
            kv_ops.attestation_put(epoch, sender, target_hash)
        return

    # --- COMMIT-REVEAL RANDAO (#7): record/revert a bonded validator's commit or reveal. Validation
    # enforced bonded + windows + commitment-opening + one-per-(sender,epoch). Revert-symmetric.
    if recipient == "commit":
        data = transaction.get("data") or {}
        if revert:
            kv_ops.commit_del(sender, data["target_epoch"])
        else:
            kv_ops.commit_put(sender, data["target_epoch"], data["commitment"])
        return
    if recipient == "reveal":
        data = transaction.get("data") or {}
        if revert:
            kv_ops.reveal_del(data["target_epoch"], data["secret"])
        else:
            kv_ops.reveal_put(data["target_epoch"], data["secret"])
        return

    # --- ALIAS op (register / transfer / unregister): change the registry, destroy the fee, no transfer ---
    if recipient == "alias":
        from ops import alias_ops
        alias_ops.apply_alias(transaction, sender=sender, logger=logger, revert=revert)
        change_balance(address=sender, amount=-fee, logger=logger, revert=revert)
        return

    # --- DATA-AVAILABILITY blob (execution-layer Phase 1): L1 orders + stores the opaque payload and
    # BURNS the DA fee; it never decodes the payload and changes no other state. Revert just un-burns. ---
    if recipient == "blob":
        change_balance(address=sender, amount=-fee, logger=logger, revert=revert)
        return

    # --- EXECUTION-LAYER SETTLEMENT (Phase 2): record/revert a bonded validator's settlement attestation
    # of (exec_cursor, state_root). Fee-exempt; the SETTLED root is a derived quorum read, so nothing else
    # to persist here. Revert-symmetric via settlement_del. ---
    if recipient == "settle":
        data = transaction.get("data") or {}
        cursor, root = data["exec_cursor"], data["state_root"]
        if revert:
            kv_ops.settlement_del(cursor, sender, root)
        else:
            kv_ops.settlement_put(cursor, sender, root)
        return

    # --- BRIDGE DEPOSIT (Phase 2): move amount+fee from sender, LOCK `amount` in the escrow, burn the fee.
    # The execution node reads this deposit from the ordered stream and credits the sender exec-side. ---
    if recipient == "bridge":
        change_balance(address=sender, amount=-(amount + fee), logger=logger, revert=revert)
        change_balance(address=BRIDGE_ESCROW, amount=amount, logger=logger, revert=revert)
        return

    # --- BRIDGE EXIT (Phase 2): release `amount` from escrow to the proven addr and burn the nullifier.
    # Validation already verified the Merkle proof against the settled root + escrow funding. Fee-exempt. ---
    if recipient == "bridge_withdraw":
        data = transaction.get("data") or {}
        addr, amt, nonce = data["addr"], int(data["amount"]), data["nonce"]
        change_balance(address=BRIDGE_ESCROW, amount=-amt, logger=logger, revert=revert)
        change_balance(address=addr, amount=amt, logger=logger, revert=revert)
        if revert:
            kv_ops.bridge_nullifier_del(addr, nonce)
        else:
            kv_ops.bridge_nullifier_put(addr, nonce)
        return

    # --- SHIELD DEPOSIT (doc/privacy.md): lock `amount` in the shielded-pool escrow, burn the fee. The output
    # note commitments ride in tx.data (opaque to L1); the exec node reads this deposit and adds them. ---
    if recipient == "shield":
        change_balance(address=sender, amount=-(amount + fee), logger=logger, revert=revert)
        change_balance(address=SHIELD_ESCROW, amount=amount, logger=logger, revert=revert)
        return

    # --- UNSHIELD EXIT (doc/privacy.md): release `amount` from the shielded escrow to the proven addr and burn
    # the nullifier. Validation already verified the Merkle proof against the settled exec root + escrow. ---
    if recipient == "unshield":
        data = transaction.get("data") or {}
        addr, amt, nonce = data["addr"], int(data["amount"]), data["nonce"]
        change_balance(address=SHIELD_ESCROW, amount=-amt, logger=logger, revert=revert)
        change_balance(address=addr, amount=amt, logger=logger, revert=revert)
        if revert:
            kv_ops.shield_nullifier_del(addr, nonce)
        else:
            kv_ops.shield_nullifier_put(addr, nonce)
        return

    # --- HTLC LOCK (cross-chain atomic swap): move amount+fee from sender, LOCK `amount` in HTLC_ESCROW,
    # burn the fee, and record the swap keyed by THIS tx's txid. Validation checked hashlock/expiry/funds. ---
    if recipient == "htlc_lock":
        data = transaction.get("data") or {}
        change_balance(address=sender, amount=-(amount + fee), logger=logger, revert=revert)
        change_balance(address=HTLC_ESCROW, amount=amount, logger=logger, revert=revert)
        if revert:
            kv_ops.htlc_del(transaction["txid"])
        else:
            kv_ops.htlc_put(transaction["txid"], {
                "sender": sender, "claimant": data["claimant"], "amount": int(amount),
                "hashlock": data["hashlock"], "expiry": int(data["expiry"]), "status": "open"})
        return

    # --- HTLC CLAIM (fee-exempt): the claimant revealed the preimage (validation verified sha256==hashlock,
    # status open, not expired, sender==claimant). Release escrow -> claimant and record the preimage
    # (publishing it is what lets the counterparty claim the mirrored lock on the other chain). ---
    if recipient == "htlc_claim":
        data = transaction.get("data") or {}
        doc = kv_ops.htlc_get(data["htlc_id"])
        amt = int(doc["amount"])
        change_balance(address=HTLC_ESCROW, amount=-amt, logger=logger, revert=revert)
        change_balance(address=doc["claimant"], amount=amt, logger=logger, revert=revert)
        if revert:
            doc["status"] = "open"; doc.pop("preimage", None)
        else:
            doc["status"] = "claimed"; doc["preimage"] = data["preimage"]
        kv_ops.htlc_put(data["htlc_id"], doc)
        return

    # --- HTLC REFUND (fee-exempt): after `expiry`, the original sender reclaims an UNCLAIMED lock.
    # Validation verified status open, height >= expiry, and sender == the lock's sender. ---
    if recipient == "htlc_refund":
        data = transaction.get("data") or {}
        doc = kv_ops.htlc_get(data["htlc_id"])
        amt = int(doc["amount"])
        change_balance(address=HTLC_ESCROW, amount=-amt, logger=logger, revert=revert)
        change_balance(address=doc["sender"], amount=amt, logger=logger, revert=revert)
        doc["status"] = "open" if revert else "refunded"
        kv_ops.htlc_put(data["htlc_id"], doc)
        return

    # --- DIVIDEND COLLECTION (doc/presence-dividend.md): release `amount` from the DIVIDEND_POOL to the proven
    # claimant and burn the nullifier. Validation already verified the Merkle proof against the settled root
    # + pool funding. Fee-exempt. ---
    if recipient == "dividend_withdraw":
        data = transaction.get("data") or {}
        addr, amt, nonce = data["addr"], int(data["amount"]), data["nonce"]
        change_balance(address=DIVIDEND_POOL, amount=-amt, logger=logger, revert=revert)
        change_balance(address=addr, amount=amt, logger=logger, revert=revert)
        if revert:
            kv_ops.dividend_nullifier_del(addr, nonce)
        else:
            kv_ops.dividend_nullifier_put(addr, nonce)
        return

    # --- TREASURY GOVERNANCE (doc/treasury.md §3.3): record/revert a bonded validator's APPROVAL vote for a
    # treasury_spend proposal. The quorum is a derived read (treasury_justified), so nothing else to persist.
    # Revert-symmetric via treasury_vote_del. ---
    if recipient == "treasury_vote":
        change_balance(address=sender, amount=-fee, logger=logger, revert=revert)   # burn the anti-spam vote fee
        data = transaction.get("data") or {}
        pid = data["pid"]
        if revert:
            kv_ops.treasury_vote_del(pid, sender)
        else:
            # SNAPSHOT the voter's activated weight NOW (at vote time) so a later top-up can't inflate this
            # approval. Activated = bond aged past TREASURY_VOTE_ACTIVATION_EPOCHS at this block's epoch.
            from ops.settlement_ops import _vote_activated
            from ops.mining_ops import selection_shares, epoch_of
            acc = get_account(sender, create_on_error=False)
            info = {"bonded": int(acc.get("bonded", 0)) if acc else 0, "bond_since": kv_ops.bond_since_get(sender)}
            vote_epoch = epoch_of(block_height) if block_height is not None else 0
            w = selection_shares(info["bonded"]) if _vote_activated(info, vote_epoch) else 0
            kv_ops.treasury_vote_put(pid, sender, w)
            if data.get("spend"):
                kv_ops.treasury_proposal_put(pid, data["spend"])   # non-consensus display index (idempotent)
        return

    # --- TREASURY PAYOUT: move `amount` from the treasury to the proposal's recipient and burn the one-shot
    # nullifier. Validation already checked the 2/3 bonded quorum + the per-proposal cap + funding. ---
    if recipient == "treasury_execute":
        from protocol import TREASURY_ADDRESS
        data = transaction.get("data") or {}
        spend, pid = data["spend"], data["pid"]
        amt, rcpt = int(spend["amount"]), spend["recipient"]
        change_balance(address=sender, amount=-fee, logger=logger, revert=revert)   # burn the executor's fee
        change_balance(address=TREASURY_ADDRESS, amount=-amt, logger=logger, revert=revert)
        change_balance(address=rcpt, amount=amt, logger=logger, revert=revert)
        if revert:
            kv_ops.treasury_executed_del(pid)
        else:
            kv_ops.treasury_executed_put(pid)
        return

    # --- ordinary transfer (recipient may be a registered ALIAS -> credit its CURRENT owner) ---
    from ops import alias_ops
    resolved = alias_ops.resolve_alias(recipient) or recipient
    amount_sender = amount + fee
    change_balance(address=sender, amount=-amount_sender, logger=logger, revert=revert)
    change_balance(address=resolved, amount=amount, logger=logger, revert=revert)


def change_balance(address: str, amount: int, logger, revert=False):
    # Compute the signed delta ONCE (revert flips the sign), then a single read-modify-write of the
    # account doc inside the active write txn (so two debits in one block compose correctly). The
    # floor_zero guard enforces the non-negative invariant: if it would go negative the write is
    # refused and we fail closed (raise) rather than silently mint or wedge the core thread.
    delta = -amount if revert else amount
    if not kv_ops.account_adjust(address, "balance", delta, floor_zero=True):
        logger.error(f"Refusing to drive {address} balance negative (amount={amount}, revert={revert})")
        raise AssertionError(f"Balance underflow for {address}")
    return True


def get_totals(block, revert=False):
    fees = 0
    produced = block["block_reward"]

    for transaction in block["block_transactions"]:
        fees += transaction["fee"]

    if not revert:
        result = {"produced": produced, "fees": fees}
    else:
        result = {"produced": -produced, "fees": -fees}
    return result


def index_totals(produced, fees, block_height):
    # signed add (on rollback get_totals(revert=True) returns NEGATIVE deltas, which must be applied
    # so totals shrink on a reorg — the old `> 0` guard wrongly skipped them and only ever grew).
    kv_ops.totals_add(produced, fees)


def fetch_totals():
    return kv_ops.totals_get()


def get_finalized_height() -> int:
    """Highest block height consensus has FINALIZED. rollback_one_block refuses to revert any block
    at/below this floor (FinalityViolation). Monotonic, persisted in the KV meta sub-DB; defaults to
    0 (genesis is trivially final). Advanced by incorporate_block as max(prev, tip - FINALITY_DEPTH)
    (#17 security step 1)."""
    return kv_ops.meta_get_int("finalized_height", 0)


def set_finalized_height(height: int):
    """Persist the finalized-height floor. Callers MUST keep it monotonic (only ever increase it)."""
    kv_ops.meta_set_int("finalized_height", int(height))


def increase_produced_count(address, amount, logger, revert=False):
    # single read-modify-write of the produced counter; floor keeps it non-negative so a mismatched
    # rollback fails closed instead of going negative and skewing the penalty metric.
    delta = -amount if revert else amount
    if not kv_ops.account_adjust(address, "produced", delta, floor_zero=True):
        logger.error(f"Refusing to drive produced count negative for {address} "
                     f"(amount={amount}, revert={revert})")
        raise AssertionError(f"Produced-count underflow for {address}")
    return True


def create_account(address, balance=0, produced=0, bonded=0, registered=0, fidelity=0):
    # INSERT-OR-IGNORE: seed the doc only if the address has no row yet (idempotent), but always
    # return the requested values (matches the old behavior).
    kv_ops.create_account_if_absent(address, balance=balance, produced=produced, bonded=bonded,
                                    registered=registered, fidelity=fidelity)
    return {"address": address,
            "balance": balance,
            "produced": produced,
            "bonded": bonded,
            "registered": registered,
            "fidelity": fidelity,
            }


def change_bonded(address: str, amount: int, logger, revert=False):
    """Move stake into (amount>0) or out of (amount<0) the `bonded` field, mirroring change_balance.
    The floor keeps bonded non-negative so a bad unbond fails closed. Bonded is NOT spendable
    balance."""
    delta = -amount if revert else amount
    if not kv_ops.account_adjust(address, "bonded", delta, floor_zero=True):
        logger.error(f"Refusing to drive bonded negative for {address} (amount={amount}, revert={revert})")
        raise AssertionError(f"Bonded underflow for {address}")
    return True


def get_account_value(address, key):
    account = get_account(address)
    value = account[key]
    return value


def get_bonded_registry():
    """Producer registry from committed account state (S4.3):
    {address: {"bonded": int, "fidelity": None, "bond_since": int}} for every account with bonded >= B_MIN.

    Together with the epoch beacon this is the SOLE input to mining_ops.select_producer, so it
    must be read against PARENT state (it is, on both the production and verification paths,
    which run before incorporate_block). Deterministic: the same committed accounts sub-DB yields
    the same dict on every node (LMDB iterates by sorted address). `fidelity` stays None (the
    selection_shares fidelity ramp is off on the bonded lane). `bond_since` is the stake-weighted bond age
    epoch (0 = unset = fully aged): it drives the PRODUCER-selection ramp ONLY (mining_ops.bond_ramp_weight),
    NOT total_bonded_shares — so fork-choice weight + the FFG/settlement quorum stay ramp-free."""
    accts = [(addr, doc) for addr, doc in kv_ops.iter_accounts() if doc.get("bonded", 0) >= B_MIN]
    since = kv_ops.bond_since_many([a for a, _ in accts])
    return {addr: {"bonded": doc["bonded"], "fidelity": None, "bond_since": since.get(addr)}
            for addr, doc in accts}


def apply_bond_since(address, delta, block_height, txid, revert=False):
    """Maintain the STAKE-WEIGHTED bond age used by the producer-selection ramp. Called from the `bond`
    reflect AFTER change_bonded has applied `delta` (>0). new_since = weighted average of the existing
    stake's age and the freshly-added stake's age (this epoch), so a top-up re-ramps the new portion (closes
    the "age a cheap address then dump" loophole) while auto-bond's tiny top-ups barely move it. A first bond
    from zero starts the age at this epoch. Revert-exact: the prior value (or 'was unset') is stored by txid
    and restored on rollback."""
    epoch = block_height // EPOCH_LENGTH
    if revert:
        prev = kv_ops.bond_since_revert_pop(txid)          # None => there was no bond_since before this tx
        if prev is None:
            kv_ops.bond_since_del(address)
        else:
            kv_ops.bond_since_put(address, prev)
        return
    prev_raw = kv_ops.bond_since_get_raw(address)          # None if unset
    kv_ops.bond_since_revert_put(txid, prev_raw)
    new_bonded = int(kv_ops.get_account(address).get("bonded", 0))   # AFTER change_bonded
    old_bonded = new_bonded - int(delta)
    if old_bonded <= 0:
        # A genuine first bond ages from now. Never record exactly 0 (that's the genesis/unset sentinel meaning
        # "fully aged" for the treasury-vote activation gate) — an epoch-0 bonder must still age normally.
        new_since = max(1, epoch)
    else:
        # TOP-UP of an existing stake — blend ages, stake-weighted. A genesis/pre-existing stake has an unset
        # age (None) which means FULLY AGED, so treat its age as epoch 0 here (do NOT mistake it for a first
        # bond, or an aged validator that auto-bonds would reset its whole stake to now and could stall).
        prev_age = 0 if prev_raw is None else int(prev_raw)
        new_since = (old_bonded * prev_age + int(delta) * epoch) // new_bonded
    kv_ops.bond_since_put(address, new_since)


def get_open_registry(current_epoch: int):
    """OPEN-lane producer registry (S4 two-lane): {address: {"fidelity": int}} for every account with a
    VALID LEASE — a PoSW recert within the last POSW_LEASE_EPOCHS. Presence IS the lease: there is no
    separate heartbeat mechanism (doc/presence-dividend.md §2.4) — the recert is the single presence +
    anti-Sybil signal. Membership is DERIVED from the revert-safe recert_by_epoch index (incorporate
    inserts, rollback deletes), so a lapsed identity drops out automatically. Deterministic, and read
    against PARENT state on the production/verification paths (as-of-parent guard, task #17)."""
    registry = {}
    for address in kv_ops.recert_addresses_after(current_epoch - POSW_LEASE_EPOCHS):
        account = kv_ops.get_account(address)
        if account and account.get("registered", 0) == 1:
            registry[address] = {"fidelity": account.get("fidelity", 0)}
    return registry


def apply_register(address: str, epoch: int, logger, revert=False):
    """Renewable presence LEASE + continuity FIDELITY. A valid register/recert (its PoSW checked in tx
    validation) records a recert at `epoch`, marks the address registered, and updates fidelity: +GAIN if
    this recert is CONTINUOUS with the previous one (gap <= POSW_LEASE_EPOCHS), else it RESETS to GAIN (a
    lapse loses the streak). fidelity ramps over ~FIDELITY_CAP recerts (≈ days). Revert-symmetric: the
    exact fidelity net is stored (hb_revert store reused) and restored, the recert rows removed, and
    `registered` cleared only if no recert remains."""
    if revert:
        rec = kv_ops.hb_revert_pop(epoch, address)
        if rec is not None:
            _prev, net = rec
            if not kv_ops.account_adjust(address, "fidelity", -net, floor_zero=True):
                raise AssertionError(f"Fidelity revert underflow for {address}")
        kv_ops.recert_del(address, epoch)
        if kv_ops.recert_latest(address) < 0:
            kv_ops.account_set(address, "registered", 0)
    else:
        prev = kv_ops.recert_latest(address)                    # previous recert epoch (before this one)
        acc = kv_ops.get_account(address)
        cur_fid = int(acc.get("fidelity", 0)) if acc else 0
        continuous = prev >= 0 and (epoch - prev) <= POSW_LEASE_EPOCHS
        decay = 0 if continuous else cur_fid                    # a lapse (or first recert) resets to GAIN
        net = FIDELITY_GAIN - decay                             # cur_fid+net = cur_fid+GAIN (cont) or GAIN
        kv_ops.recert_put(address, epoch)
        kv_ops.account_set(address, "registered", 1)
        if not kv_ops.account_adjust(address, "fidelity", net, floor_zero=True):
            raise AssertionError(f"Fidelity underflow for {address}")
        kv_ops.hb_revert_put(epoch, address, prev, net)         # exact inverse for rollback
    return True


def change_fidelity(address: str, amount: int, logger, revert=False):
    """Additive OPEN-lane diligence counter (revert = sign-flip, EXACT). Stored RAW/uncapped;
    mining_ops.open_shares clamps to FIDELITY_CAP on READ, so the stored value stays a clean
    reversible counter (no lossy clamp at write time). Floor keeps it non-negative -> a bad revert
    fails closed instead of going negative."""
    delta = -amount if revert else amount
    if not kv_ops.account_adjust(address, "fidelity", delta, floor_zero=True):
        logger.error(f"Refusing to drive fidelity negative for {address} (amount={amount}, revert={revert})")
        raise AssertionError(f"Fidelity underflow for {address}")
    return True


def apply_slash(address, height, logger, revert=False):
    """SLASHING core (#15 step 5C / #6): burn SLASH_BOND_PENALTY of `address`'s bonded stake for a
    proven offence at `height`, and record (address, height) so the same offence can't be slashed
    twice. Revert-symmetric: validate_transaction guarantees the offender held >= SLASH_BOND_PENALTY
    bonded BEFORE applying, so the dock never floors; rollback restores the bond (change_bonded with
    revert) and clears the slash record. The bonded coins are DESTROYED (the deterrent is the loss)."""
    change_bonded(address=address, amount=-SLASH_BOND_PENALTY, logger=logger, revert=revert)
    if revert:
        kv_ops.slash_clear(address, height)
    else:
        kv_ops.slash_record(address, height)
