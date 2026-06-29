import time

from .data_ops import get_home
from .sqlite_ops import DbHandler
from protocol import B_MIN


def get_account(address, create_on_error=True):
    """return all account information if account exists else create it"""
    acc_handler = DbHandler(db_file=f"{get_home()}/index/index.db")
    fetched = acc_handler.db_fetch("SELECT * FROM acc_index WHERE address = ?", (address,))
    acc_handler.close()

    if fetched:
        account = {"address": fetched[0][0],
                   "balance": fetched[0][1],
                   "produced": fetched[0][2],
                   # bonded column may be absent on a legacy row read mid-migration; default 0
                   "bonded": fetched[0][3] if len(fetched[0]) > 3 else 0}
        return account
    elif create_on_error:
        return create_account(address)
    else:
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

    # --- ordinary transfer ---
    amount_sender = amount + fee
    change_balance(address=sender, amount=-amount_sender, logger=logger, revert=revert)
    change_balance(address=recipient, amount=amount, logger=logger, revert=revert)


def change_balance(address: str, amount: int, logger, revert=False):
    # Compute the signed delta ONCE (the old code re-flipped the sign inside a retry loop,
    # which could silently mint on a retried revert). Apply as a SINGLE guarded in-place
    # UPDATE instead of SELECT-then-UPDATE across two connections: this removes the read leg
    # (the ~296x balance-write amplification), removes the read-modify-write race, and the
    # WHERE-clause floor enforces the non-negative invariant atomically. rowcount != 1 means
    # the floor blocked the write -> fail closed (raise), without a loop that could wedge the
    # single block-processing thread.
    delta = -amount if revert else amount
    acc_handler = DbHandler(db_file=f"{get_home()}/index/index.db")
    acc_handler.db_execute(
        "INSERT OR IGNORE INTO acc_index (address, balance, produced, bonded) VALUES (?,0,0,0)", (address,))
    rows = acc_handler.db_change(
        "UPDATE acc_index SET balance = balance + ? WHERE address = ? AND balance + ? >= 0",
        (delta, address, delta))
    acc_handler.close()
    if rows != 1:
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
    acc_handler = DbHandler(db_file=f"{get_home()}/index/index.db")

    # use truthiness, not `> 0`: on a rollback get_totals(revert=True) returns NEGATIVE
    # deltas, and the old `> 0` guards skipped them entirely, so totals only ever grew
    # (every reorg permanently inflated the reported supply).
    if produced:
        acc_handler.db_execute("UPDATE totals_index SET produced = produced + ?", (produced,))
    if fees:  # fees counted from block 1 (the >111111 compat gate is gone — fresh chain)
        acc_handler.db_execute("UPDATE totals_index SET fees = fees + ?", (fees,))
    acc_handler.close()


def fetch_totals():
    acc_handler = DbHandler(db_file=f"{get_home()}/index/index.db")
    totals = acc_handler.db_fetch("SELECT * FROM totals_index")
    result = {
        "produced": totals[0][0],
        "fees": totals[0][1],
    }
    return result

def increase_produced_count(address, amount, logger, revert=False):
    # single guarded in-place UPDATE (no SELECT-then-UPDATE, no retry spin). The floor keeps
    # the produced counter non-negative so a mismatched rollback fails closed rather than
    # silently going negative and skewing the penalty metric.
    delta = -amount if revert else amount
    acc_handler = DbHandler(db_file=f"{get_home()}/index/index.db")
    acc_handler.db_execute(
        "INSERT OR IGNORE INTO acc_index (address, balance, produced, bonded) VALUES (?,0,0,0)", (address,))
    rows = acc_handler.db_change(
        "UPDATE acc_index SET produced = produced + ? WHERE address = ? AND produced + ? >= 0",
        (delta, address, delta))
    acc_handler.close()
    if rows != 1:
        logger.error(f"Refusing to drive produced count negative for {address} "
                     f"(amount={amount}, revert={revert})")
        raise AssertionError(f"Produced-count underflow for {address}")
    return True


def create_account(address, balance=0, produced=0, bonded=0):
    acc_handler = DbHandler(db_file=f"{get_home()}/index/index.db")
    # name columns explicitly: the schema is (address, balance, produced, bonded)
    acc_handler.db_execute(
        "INSERT OR IGNORE INTO acc_index (address, balance, produced, bonded) VALUES (?,?,?,?)",
        (address, balance, produced, bonded,))
    acc_handler.close()

    account = {"address": address,
               "balance": balance,
               "produced": produced,
               "bonded": bonded,
               }

    return account


def change_bonded(address: str, amount: int, logger, revert=False):
    """Move stake into (amount>0) or out of (amount<0) the `bonded` column via a single
    guarded UPDATE, mirroring change_balance. The WHERE floor keeps bonded non-negative so a
    bad unbond fails closed instead of going negative. Bonded is NOT spendable balance."""
    delta = -amount if revert else amount
    acc_handler = DbHandler(db_file=f"{get_home()}/index/index.db")
    acc_handler.db_execute(
        "INSERT OR IGNORE INTO acc_index (address, balance, produced, bonded) VALUES (?,0,0,0)", (address,))
    rows = acc_handler.db_change(
        "UPDATE acc_index SET bonded = bonded + ? WHERE address = ? AND bonded + ? >= 0",
        (delta, address, delta))
    acc_handler.close()
    if rows != 1:
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
    which run before incorporate_block). Deterministic: the same committed acc_index yields the
    same dict on every node. fidelity is None in v1 (no on-chain fidelity column yet), which
    disables the selection_shares ramp so each identity gets full split-neutral capped weight."""
    acc_handler = DbHandler(db_file=f"{get_home()}/index/index.db")
    rows = acc_handler.db_fetch("SELECT address, bonded FROM acc_index WHERE bonded >= ?", (B_MIN,))
    acc_handler.close()
    return {row[0]: {"bonded": row[1], "fidelity": None} for row in rows}
