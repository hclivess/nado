from ops import kv_ops
from protocol import B_MIN, EPOCH_LENGTH, PRESENCE_WINDOW, FIDELITY_GAIN

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
        # release `amount` of stake back to spendable balance; fee is burned
        change_bonded(address=sender, amount=-amount, logger=logger, revert=revert)
        change_balance(address=sender, amount=amount - fee, logger=logger, revert=revert)
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


def apply_heartbeat(address: str, epoch: int, logger, revert=False):
    """Record (apply) / remove (revert) a per-epoch presence heartbeat: write the heartbeats sub-DB
    and bump the fidelity counter. One heartbeat per (address, epoch) is enforced at tx validation,
    and the DUPSORT heartbeats sub-DB auto-dedups identical (epoch,address) dups. Fully revert-
    symmetric: incorporate inserts the exact dup + bumps fidelity, rollback deletes that exact dup +
    decrements (the GC of pre-presence-window epochs is intentionally NOT reverted — those rows are
    outside any rollback/read window)."""
    if not revert:
        kv_ops.heartbeat_put(epoch, address)
        # ANTI-BLOAT GC: drop heartbeats older than the presence window. get_open_registry only reads
        # epoch > current - PRESENCE_WINDOW, and rollbacks are bounded (max_rollbacks < EPOCH_LENGTH
        # << PRESENCE_WINDOW epochs), so these dups are never read or reverted again — bounds the
        # sub-DB so a slow distributed spammer cannot grow it without limit.
        kv_ops.heartbeat_gc(epoch - PRESENCE_WINDOW)
    else:
        kv_ops.heartbeat_del(epoch, address)
    change_fidelity(address=address, amount=FIDELITY_GAIN, logger=logger, revert=revert)
    return True
