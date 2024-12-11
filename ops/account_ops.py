import time
from contextlib import contextmanager
from .data_ops import get_home
from .sqlite_ops import DbHandler


# Connection pooling helper
@contextmanager
def get_db_connection():
    """Context manager for database connections to ensure proper handling"""
    db_handler = DbHandler(db_file=f"{get_home()}/index/accounts.db")
    try:
        yield db_handler
    finally:
        db_handler.close()


def get_account(address, create_on_error=True):
    """Return all account information if account exists else create it"""
    with get_db_connection() as acc_handler:
        fetched = acc_handler.db_fetch(
            "SELECT address, balance, produced, burned FROM acc_index WHERE address = ?",
            (address,)
        )

        if fetched:
            return {
                "address": fetched[0][0],
                "balance": fetched[0][1],
                "produced": fetched[0][2],
                "burned": fetched[0][3]
            }
        elif create_on_error:
            return create_account(address)
        return None


def reflect_transaction(transaction, logger, block_height, revert=False):
    """Process a transaction by updating sender and recipient balances"""
    sender = transaction["sender"]
    recipient = transaction["recipient"]

    amount_sender = (transaction["amount"] + transaction["fee"]) if block_height > 111111 else transaction["amount"]
    amount_recipient = transaction["amount"]

    is_burn = recipient == "burn"

    with get_db_connection() as acc_handler:
        try:
            # Begin transaction for atomicity
            acc_handler.db_execute("BEGIN TRANSACTION")

            # Update sender
            change_balance(acc_handler, sender, -amount_sender if not revert else amount_sender,
                           is_burn, logger)

            # Update recipient
            change_balance(acc_handler, recipient, amount_recipient if not revert else -amount_recipient,
                           False, logger)

            acc_handler.db_execute("COMMIT")
            return True

        except Exception as e:
            acc_handler.db_execute("ROLLBACK")
            logger.error(f"Transaction failed: {e}")
            return False


def change_balance(acc_handler, address, amount, is_burn, logger):
    """Update balance in a single atomic operation"""
    try:
        # Update balance and burned in a single query
        result = acc_handler.db_execute("""
            UPDATE acc_index 
            SET balance = balance + ?,
                burned = CASE WHEN ? THEN burned - ? ELSE burned END
            WHERE address = ?
            RETURNING balance, burned
        """, (amount, is_burn, amount, address))

        new_balance, new_burned = result[0]

        if new_balance < 0:
            raise ValueError(f"Negative balance: {new_balance}")
        if new_burned < 0:
            raise ValueError(f"Negative burned amount: {new_burned}")

    except Exception as e:
        logger.error(f"Balance update failed for {address}: {e}")
        raise


def get_totals(block, revert=False):
    """Calculate block totals with optimized calculations"""
    fees = sum(tx["fee"] for tx in block["block_transactions"])
    burned = sum(tx["amount"] for tx in block["block_transactions"] if tx["recipient"] == "burn")
    produced = block["block_reward"]

    if revert:
        return {
            "produced": -produced,
            "fees": -fees,
            "burned": -burned
        }
    return {
        "produced": produced,
        "fees": fees,
        "burned": burned
    }


def index_totals(produced, fees, burned, block_height):
    """Update totals with a single atomic operation"""
    with get_db_connection() as acc_handler:
        acc_handler.db_execute("""
            UPDATE totals_index 
            SET produced = produced + ?,
                fees = CASE WHEN ? > 111111 AND ? > 0 THEN fees + ? ELSE fees END,
                burned = burned + ?
        """, (produced, block_height, fees, fees, burned))


def fetch_totals():
    """Fetch totals with optimized query"""
    with get_db_connection() as acc_handler:
        totals = acc_handler.db_fetch("SELECT produced, fees, burned FROM totals_index")
        return {
            "produced": totals[0][0],
            "fees": totals[0][1],
            "burned": totals[0][2],
        }


def increase_produced_count(address, amount, logger, revert=False):
    """Update produced count atomically"""
    with get_db_connection() as acc_handler:
        try:
            acc_handler.db_execute("BEGIN TRANSACTION")

            result = acc_handler.db_execute("""
                UPDATE acc_index 
                SET produced = produced + ? 
                WHERE address = ?
                RETURNING produced
            """, (-amount if revert else amount, address))

            produced_updated = result[0][0]
            acc_handler.db_execute("COMMIT")
            return produced_updated

        except Exception as e:
            acc_handler.db_execute("ROLLBACK")
            logger.error(f"Failed to update produced count: {e}")
            raise


def create_account(address, balance=0, burned=0, produced=0):
    """Create new account with optimized insertion"""
    with get_db_connection() as acc_handler:
        acc_handler.db_execute(
            "INSERT INTO acc_index (address, balance, burned, produced) VALUES (?,?,?,?)",
            (address, balance, burned, produced)
        )

        return {
            "address": address,
            "balance": balance,
            "produced": produced,
            "burned": burned,
        }


def get_account_value(address, key):
    """Optimized single value fetch"""
    with get_db_connection() as acc_handler:
        result = acc_handler.db_fetch(f"SELECT {key} FROM acc_index WHERE address = ?", (address,))
        return result[0][0] if result else None