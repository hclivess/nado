import os

import msgpack
from sqlite_ops import DbHandler
from data_ops import check_traversal, get_home


def get_account(address, create_on_error=True):
    """return all account information if account exists else create it"""
    check_traversal(address)
    account_path = f"{get_home()}/accounts/{address}/balance.dat"

    if os.path.exists(account_path):
        with open(account_path, "rb") as account_file:
            account = msgpack.unpack(account_file)
        return account
    elif create_on_error:
        return create_account(address)
    else:
        return None


def reflect_transaction(transaction, revert=False):
    sender = transaction["sender"]
    recipient = transaction["recipient"]
    amount = transaction["amount"]

    is_burn = False
    if recipient == "burn":
        is_burn = True

    if revert:
        change_balance(address=sender, amount=amount, is_burn=is_burn)
        change_balance(address=recipient, amount=-amount)

    else:
        change_balance(address=sender, amount=-amount, is_burn=is_burn)
        change_balance(address=recipient, amount=amount)


def change_balance(address: str, amount: int, is_burn=False):
    check_traversal(address)
    while True:
        try:
            account_message = get_account(address)
            account_message["account_balance"] += amount
            assert (account_message["account_balance"] >= 0), "Cannot change balance into negative"

            if is_burn:
                account_message["account_burned"] -= amount
                assert (account_message["account_burned"] >= 0), "Cannot change burn into negative"

            with open(f"{get_home()}/accounts/{address}/balance.dat", "wb") as account_file:
                msgpack.pack(account_message, account_file)
        except Exception as e:
            raise ValueError(f"Failed setting balance for {address}: {e}")
        break
    return True


def increase_produced_count(address, amount, revert=False):
    check_traversal(address)

    account_path = f"{get_home()}/accounts/{address}/balance.dat"
    account = get_account(address)
    produced = account["account_produced"]
    if revert:
        account.update(account_produced=produced - amount)
    else:
        account.update(account_produced=produced + amount)

    with open(account_path, "wb") as outfile:
        msgpack.pack(account, outfile)

    return produced

def create_account(address, balance=0, burned=0, produced=0):
    """create account if it does not exist"""
    check_traversal(address)

    account_path = f"{get_home()}/accounts/{address}/balance.dat"
    if not os.path.exists(account_path):
        os.makedirs(f"{get_home()}/accounts/{address}")

        account = {
            "account_balance": balance,
            "account_burned": burned,
            "account_address": address,
            "account_produced": produced,
        }

        with open(account_path, "wb") as outfile:
            msgpack.pack(account, outfile)
        return account
    else:
        return get_account(address)


def get_account_value(address, key):
    check_traversal(address)

    account = get_account(address)
    value = account[key]
    return value
