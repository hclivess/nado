import argparse
import asyncio
import json
import random

from Curve25519 import from_private_key
from compounder import compound_send_transaction
from config import get_timestamp_seconds, create_config, config_found, get_port
from ops.account_ops import get_account_value
from ops.data_ops import allow_async
from ops.data_ops import get_home, make_folder
from ops.key_ops import load_keys, keyfile_found, save_keys, generate_keys
from ops.log_ops import get_logger
from ops.peer_ops import get_public_ip
from ops.peer_ops import load_ips
from ops.transaction_ops import create_transaction, draft_transaction, to_raw_amount, get_recommneded_fee, to_readable_amount, \
    get_target_block, get_base_fee

LOCAL = True

def send_transaction(transaction, ips, logger):
    print(json.dumps(transaction, indent=4))
    input("Press any key to continue")

    fails = []
    results = asyncio.run(compound_send_transaction(ips=ips,
                                                    port=9173,
                                                    fail_storage=fails,
                                                    logger=logger,
                                                    transaction=transaction,
                                                    semaphore=asyncio.Semaphore(50)))

    print(f"Submitted to {len(results)} nodes successfully")


if __name__ == "__main__":
    allow_async()
    logger = get_logger(file=f"linewallet.log")

    parser = argparse.ArgumentParser()
    parser.add_argument("--sk", help="[private key] Use private key, ignore default key location", default=False)
    parser.add_argument("--amount", help="[number] Amount to send", default=False)
    parser.add_argument("--recipient", help="[NADO address] Recipient address", default=False)
    parser.add_argument("--fee", help="[number] Fee to spend", default=False)
    parser.add_argument("--target", help="[number] Target block number", default=False)
    args = parser.parse_args()
    if args.sk:
        key_dictionary = from_private_key(args.sk)

        print(key_dictionary)
        print(f"Loaded {key_dictionary['address']} wallet")

    else:
        make_folder(f"{get_home()}/private", strict=False)
        if not config_found():
            ip = asyncio.run(get_public_ip(logger=logger))
            create_config(ip=ip)
        if not keyfile_found():
            save_keys(generate_keys())
        key_dictionary = load_keys()

    private_key = key_dictionary["private_key"]
    public_key = key_dictionary["public_key"]
    address = key_dictionary["address"]
    if LOCAL:
        ips = ["127.0.0.1"]
    else:
        ips = asyncio.run(load_ips(fail_storage=[], logger=logger, port=9173))
    target = random.choice(ips)
    port = get_port()
    balance = get_account_value(address, key="balance")
    balance_readable = to_readable_amount(balance)

    print(f"Sending from {address}")
    print(f"Balance: {balance_readable}")
    # print(f"Mining Penalty: {penalty}")

    if args.recipient:
        recipient = args.recipient
    else:
        recipient = input("Recipient: ")

    if args.amount:
        amount = args.amount
    else:
        amount = input("Amount: ")

    recommended_block = asyncio.run(get_target_block(target=target,
                                                     port=port,
                                                     logger=logger))

    print(f"Recommended target block: {recommended_block}")

    if args.target:
        target_block = args.target
    else:
        target_block = input(f"Target block: ")
    if not target_block:
        target_block = recommended_block

    data=""

    draft = draft_transaction(sender=address,
                                     recipient=recipient,
                                     amount=to_raw_amount(amount),
                                     data=data,
                                     public_key=public_key,
                                     timestamp=get_timestamp_seconds(),
                                     target_block=int(target_block))

    recommended_fee = asyncio.run(get_recommneded_fee(target=target,
                                                      port=port,
                                                      base_fee=get_base_fee(transaction=draft),
                                                      logger=logger))
    print(f"Recommended fee: {recommended_fee}")

    transaction = create_transaction(draft=draft,
                                     private_key=private_key,
                                     fee=recommended_fee)

    if args.fee:
        fee = args.fee
    else:
        fee = input(f"Fee: ")
    if not fee:
        fee = 0

    send_transaction(transaction, ips=ips, logger=logger)
