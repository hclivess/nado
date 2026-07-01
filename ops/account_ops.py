from ops import kv_ops
from ops.address_ops import make_address
from protocol import B_MIN, EPOCH_LENGTH, PRESENCE_WINDOW, FIDELITY_GAIN, FIDELITY_DECAY, SLASH_BOND_PENALTY, BOND_UNLOCK_DELAY

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
    # Fee is ALWAYS debited from the sender (the >111111 compat gate is gone — fresh chain).
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
        apply_register(address=sender, logger=logger, revert=revert)
        return
    if recipient == "heartbeat":
        apply_heartbeat(address=sender, epoch=block_height // EPOCH_LENGTH, logger=logger, revert=revert)
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

    # --- ordinary transfer ---
    amount_sender = amount + fee
    change_balance(address=sender, amount=-amount_sender, logger=logger, revert=revert)
    change_balance(address=recipient, amount=amount, logger=logger, revert=revert)


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
    {address: {"bonded": int, "fidelity": None}} for every account with bonded >= B_MIN.

    Together with the epoch beacon this is the SOLE input to mining_ops.select_producer, so it
    must be read against PARENT state (it is, on both the production and verification paths,
    which run before incorporate_block). Deterministic: the same committed accounts sub-DB yields
    the same dict on every node (LMDB iterates by sorted address). fidelity is None in v1 (no
    on-chain fidelity ramp on the bonded lane yet), which disables the selection_shares ramp so each
    identity gets full split-neutral capped weight."""
    return {addr: {"bonded": doc["bonded"], "fidelity": None}
            for addr, doc in kv_ops.iter_accounts() if doc.get("bonded", 0) >= B_MIN}


def get_open_registry(current_epoch: int):
    """OPEN-lane producer registry (S4 two-lane): {address: {"fidelity": int}} for every account
    that has REGISTERED (one-time PoW) and posted a heartbeat within the last PRESENCE_WINDOW
    epochs. Together with mining_ops.lane_of + the beacon this is the input to the open-lane draw.

    Membership is DERIVED from the heartbeats sub-DB (revert-safe: incorporate inserts, rollback
    deletes), so an abandoned registration drops out automatically without any decay bookkeeping.
    Deterministic — the same committed state yields the same dict on every node — and MUST be read
    against PARENT state on the production/verification paths (as-of-parent guard, task #17)."""
    present = kv_ops.heartbeat_addresses_after(current_epoch - PRESENCE_WINDOW)
    registry = {}
    for address in present:
        account = kv_ops.get_account(address)
        if account and account.get("registered", 0) == 1:
            registry[address] = {"fidelity": account.get("fidelity", 0)}
    return registry


def apply_register(address: str, logger, revert=False):
    """Set (apply) / clear (revert) an address's OPEN-lane registered flag. The one-time light
    registration PoW is enforced in transaction validation; here we only flip the flag. Revert-
    symmetric (register -> 1, revert -> 0)."""
    kv_ops.account_set(address, "registered", 0 if revert else 1)
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


def apply_heartbeat(address: str, epoch: int, logger, revert=False):
    """Record (apply) / remove (revert) a per-epoch presence heartbeat: write the heartbeats sub-DB
    and bump the fidelity counter. One heartbeat per (address, epoch) is enforced at tx validation,
    and the DUPSORT heartbeats sub-DB auto-dedups identical (epoch,address) dups. Fully revert-
    symmetric: incorporate inserts the exact dup + bumps fidelity, rollback deletes that exact dup +
    decrements (the GC of pre-presence-window epochs is intentionally NOT reverted — those rows are
    outside any rollback/read window)."""
    if not revert:
        kv_ops.heartbeat_put(epoch, address)
        # FIDELITY with ABSENCE DECAY (continuous-presence, anti-Sybil): decay for the gap since the
        # account's last heartbeat, CAPPED at its current fidelity so the result never floors (=> the
        # net change is exactly invertible), then +GAIN for this epoch's presence.
        acc = kv_ops.get_account(address)
        cur_fid = int(acc.get("fidelity", 0)) if acc else 0
        prev = int(acc.get("last_hb_epoch", 0)) if acc else 0    # 0 = never / genesis => no gap
        gap = max(0, epoch - prev - 1) if prev > 0 else 0
        decay = min(cur_fid, FIDELITY_DECAY * gap)
        net = FIDELITY_GAIN - decay                              # cur_fid + net >= GAIN >= 0 (never floors)
        if not kv_ops.account_adjust(address, "fidelity", net, floor_zero=True):
            logger.error(f"Fidelity adjust underflow for {address} (net={net})")
            raise AssertionError(f"Fidelity underflow for {address}")
        kv_ops.account_set(address, "last_hb_epoch", epoch)
        kv_ops.hb_revert_put(epoch, address, prev, net)          # exact inverse for rollback
        # ANTI-BLOAT GC: drop presence + revert rows older than the presence window. get_open_registry
        # only reads epoch > current - PRESENCE_WINDOW and rollbacks are bounded (max_rollbacks <
        # EPOCH_LENGTH << PRESENCE_WINDOW epochs), so these rows are never read or reverted again.
        kv_ops.heartbeat_gc(epoch - PRESENCE_WINDOW)
        kv_ops.hb_revert_gc(epoch - PRESENCE_WINDOW)
    else:
        kv_ops.heartbeat_del(epoch, address)
        rec = kv_ops.hb_revert_pop(epoch, address)
        if rec is not None:
            prev, net = rec
            if not kv_ops.account_adjust(address, "fidelity", -net, floor_zero=True):
                logger.error(f"Fidelity revert underflow for {address} (net={net})")
                raise AssertionError(f"Fidelity revert underflow for {address}")
            kv_ops.account_set(address, "last_hb_epoch", prev)   # restore exactly (byte-identical)
        else:
            # No revert record (a pre-decay heartbeat) -> legacy exact -GAIN inverse.
            change_fidelity(address=address, amount=FIDELITY_GAIN, logger=logger, revert=True)
    return True
