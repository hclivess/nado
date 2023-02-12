import time

from .data_ops import get_home
from .sqlite_ops import DbHandler


def get_account(address, create_on_error=True):
    """return all account information if account exists else create it"""
    acc_handler = DbHandler(db_file=f"{get_home()}/index/accounts.db")
    fetched = acc_handler.db_fetch("SELECT * FROM acc_index WHERE address = ?", (address,))
    acc_handler.close()

    if fetched:
        account = {"address": fetched[0][0],
                   "balance": fetched[0][1],
                   "produced": fetched[0][2],
                   "burned": fetched[0][3]}
        return account
    elif create_on_error:
        return create_account(address)
    else:
        return None


def reflect_transaction(transaction, logger, block_height, revert=False):
    sender = transaction["sender"]
    recipient = transaction["recipient"]

    amount_sender = transaction["amount"]+transaction["fee"]
    amount_recipient = transaction["amount"]

    is_burn = False
    if recipient == "burn":
        is_burn = True

    change_balance(address=sender, amount=-amount_sender, is_burn=is_burn, logger=logger, revert=revert)
    change_balance(address=recipient, amount=amount_recipient, is_burn=False, logger=logger, revert=revert)


def change_balance(address: str, amount: int, logger, is_burn=False, revert=False):
    while True:
        try:
            if revert:
                amount = -amount

            acc = get_account(address)
            new_balance = acc["balance"] + amount
            assert (new_balance >= 0), f"Cannot change balance into negative: {new_balance}"

            if is_burn:
                new_burned = acc["burned"] - amount
                assert (new_burned >= 0), f"Cannot change burn into negative: {new_burned}"
            else:
                new_burned = acc["burned"]

            acc_handler = DbHandler(db_file=f"{get_home()}/index/accounts.db")
            acc_handler.db_execute("UPDATE acc_index SET balance = ?, burned = ? WHERE address = ?", (new_balance,
                                                                                                      new_burned,
                                                                                                      address,))
            acc_handler.close()
            return True

        except Exception as e:
            logger.error(f"Failed setting balance for {address}: {e}, is_burn: {is_burn}, revert: {revert}")
            time.sleep(1)


def get_totals(block, revert=False):
    fees = 0
    burned = 0
    produced = block["block_reward"]

    for transaction in block["block_transactions"]:
        if transaction["recipient"] == "burn":
            burned += transaction["amount"]
        fees += transaction["fee"]

    if not revert:
        result =  {"produced": produced,
                "fees": fees,
                "burned": burned
                }
    else:
        result = {"produced": -produced,
                "fees": -fees,
                "burned": -burned
                }
    return result
def index_totals(produced, fees, burned):
    acc_handler = DbHandler(db_file=f"{get_home()}/index/accounts.db")

    if produced > 0:
        acc_handler.db_execute("UPDATE totals_index SET produced = produced + ?", (produced,))
    if fees > 0:
        acc_handler.db_execute("UPDATE totals_index SET fees = fees + ?", (fees,))
    if burned > 0:
        acc_handler.db_execute("UPDATE totals_index SET burned = burned + ?", (burned,))
    acc_handler.close()

def increase_produced_count(address, amount, logger, revert=False):
    while True:
        try:
            account = get_account(address)
            produced = account["produced"]
            if revert:
                produced_updated = produced - amount
                account.update(produced=produced_updated)
            else:
                produced_updated = produced + amount
                account.update(produced=produced_updated)

            acc_handler = DbHandler(db_file=f"{get_home()}/index/accounts.db")
            acc_handler.db_execute("UPDATE acc_index SET produced = ? WHERE address = ?", (produced_updated, address,))
            acc_handler.close()

            return produced_updated

        except Exception as e:
            logger.error(f"Failed to validate spending during block production: {e}")


def create_account(address, balance=0, burned=0, produced=0):
    acc_handler = DbHandler(db_file=f"{get_home()}/index/accounts.db")
    acc_handler.db_execute("INSERT INTO acc_index VALUES (?,?,?,?)", (address, balance, burned, produced,))
    acc_handler.close()

    account = {"address": address,
               "balance": balance,
               "produced": produced,
               "burned": burned,
               }

    return account


def get_account_value(address, key):
    account = get_account(address)
    value = account[key]
    return value
