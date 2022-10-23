import json
import os

def get_account(address, create_on_error=True):
    """return all account information if account exists else create it"""
    account_path = f"accounts/{address}/balance.dat"
    if os.path.exists(account_path):
        with open(account_path, "r") as account_file:
            account = json.load(account_file)
        return account
    elif create_on_error:
        return create_account(address)
    else:
        return None

def create_account(address, balance=0, burned=0):
    """create account if it does not exist"""
    account_path = f"accounts/{address}/balance.dat"
    if not os.path.exists(account_path):
        os.makedirs(f"accounts/{address}")

        account = {
            "account_balance": balance,
            "account_burned": burned,
            "account_address": address,
        }

        with open(account_path, "w") as outfile:
            json.dump(account, outfile)
        return account
    else:
        return get_account(address)

def get_burn_bonus(address):
    account = get_account(address)
    burned = account["account_burned"]
    return burned
