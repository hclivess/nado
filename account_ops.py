import os

import msgpack
from sqlite_ops import DbHandler
from data_ops import check_traversal, get_home


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


def reflect_transaction(transaction, logger, revert=False):
    sender = transaction["sender"]
    recipient = transaction["recipient"]
    amount = transaction["amount"]

    is_burn = False
    if recipient == "burn":
        is_burn = True

    if revert:
        change_balance(address=sender, amount=amount, is_burn=is_burn, logger=logger)
        change_balance(address=recipient, amount=-amount, logger=logger)

    else:
        change_balance(address=sender, amount=-amount, is_burn=is_burn, logger=logger)
        change_balance(address=recipient, amount=amount, logger=logger)


def change_balance(address: str, amount: int, logger, is_burn=False):
    while True:
        try:
            acc = get_account(address)
            acc["balance"] += amount
            assert (acc["balance"] >= 0), "Cannot change balance into negative"

            if is_burn:
                acc["burned"] -= amount
                assert (acc["burned"] >= 0), "Cannot change burn into negative"

            acc_handler = DbHandler(db_file=f"{get_home()}/index/accounts.db")
            acc_handler.db_execute("UPDATE acc_index SET balance = ?, burned = ? WHERE address = ?", (acc["balance"],
                                                                                                      acc["burned"],
                                                                                                      address,))
            acc_handler.close()
            return True

        except Exception as e:
            logger.error(f"Failed setting balance for {address}: {e}")

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
