"""
Fast full reindex: rebuild accounts.db, blocks.db and the consolidated tx index
from the local block files.

The slow part of the old per-block reindex was never the work itself -- it was one
SQLite connect + WAL checkpoint/fsync per block and per balance change. This version
walks the chain once, accumulates ALL state in memory, and writes it in a handful of
bulk transactions (and builds the tx indexes after the bulk insert, not during it).

It reproduces byte-identical state to the live incorporate_block path -- the balance,
burn, reward and totals rules below mirror reflect_transaction()/index_totals() exactly
(see test: reindex_fast == per-block reference). Supersedes the buggy
reindex_batch_raw_experimental.py (which indexed only the first tx of every block).

Run directly to wipe index/ and rebuild from blocks/ ; import accumulate_chain/
write_state to reuse the fast path elsewhere (e.g. rebuilding the tx index after a
state-snapshot import, which intentionally omits it).
"""
import os
import shutil

from ops.data_ops import sort_list_dict, get_home, make_folder
from ops.block_ops import (get_block, get_block_ends_info,
                           set_latest_block_info, update_child_in_latest_block)
from ops import kv_ops
from genesis import make_genesis, create_indexers
from ops.log_ops import get_logger
from protocol import split_block_reward, TREASURY_ADDRESS, TREASURY_GENESIS

GENESIS_ADDRESS = TREASURY_ADDRESS   # genesis address == treasury (canonical checksum)
# TODO(relaunch): GENESIS_CHILD_HASH is the hash of block 1 under the NEW canonical hashing;
# regenerate it once the relaunched genesis + block 1 exist (the old value is stale).
GENESIS_CHILD_HASH = "3abbfe409d446d997fbf65767c97e3f59ecb943d61a000240432e1627187966b"
GENESIS_BALANCE = TREASURY_GENESIS   # bootstrap allocation minted to the genesis/treasury
GENESIS_TIMESTAMP = 1669852800
GENESIS_IP = "78.102.98.72"


def accumulate_chain(logger, log_every=50000):
    """Walk the chain from genesis via child_hash links and accumulate full state
    in memory. Returns (accounts, tx_rows, block_rows, totals, tip_block).

    accounts: {address: [balance_delta, produced_delta, burned_delta]}
    totals:   [produced, fees, burned]
    Mirrors reflect_transaction()/index_totals()."""
    accounts = {}
    tx_rows = []
    block_rows = []
    totals = [0, 0]  # produced, fees

    def adj(addr, balance=0, produced=0, bonded=0):
        a = accounts.get(addr)
        if a is None:
            a = accounts[addr] = [0, 0, 0]
        a[0] += balance
        a[1] += produced
        a[2] += bonded

    block = get_block_ends_info(logger=logger)["latest_block"]  # genesis
    tip = block
    count = 0
    while block:
        child_hash = block.get("child_hash")
        if not child_hash:
            break
        child = get_block(block=child_hash)
        if not child:
            logger.warning(f"Reindex stopped: missing block {child_hash}")
            break
        block = tip = child

        height = block["block_number"]
        if height <= 0:
            continue

        for tx in sort_list_dict(block["block_transactions"]):
            amount = tx["amount"]
            fee = tx["fee"]
            recipient = tx["recipient"]
            # mirror reflect_transaction: bond/unbond move coins between balance and bonded;
            # everything else is an ordinary transfer (fee always debited). No burn.
            if recipient == "bond":
                adj(tx["sender"], balance=-(amount + fee), bonded=amount)
            elif recipient == "unbond":
                adj(tx["sender"], balance=amount - fee, bonded=-amount)
            else:
                adj(tx["sender"], balance=-(amount + fee))
                adj(recipient, balance=amount)
            tx_rows.append((tx["txid"], height, tx["sender"], recipient))

        # 90/10 split mirrors incorporate_block: producer gets the floor + produced credit,
        # treasury the exact remainder; totals.produced tracks the FULL emission.
        reward = block["block_reward"]
        producer_cut, treasury_cut = split_block_reward(reward)
        adj(block["block_creator"], balance=producer_cut, produced=producer_cut)
        if treasury_cut:
            adj(TREASURY_ADDRESS, balance=treasury_cut)
        block_rows.append((block["block_hash"], height))

        if reward:
            totals[0] += reward
        totals[1] += sum(tx["fee"] for tx in block["block_transactions"])  # fees counted always

        count += 1
        if count % log_every == 0:
            logger.info(f"Reindex accumulated {count} blocks (height {height})")

    logger.info(f"Reindex accumulated {count} blocks, {len(accounts)} accounts, {len(tx_rows)} txs")
    return accounts, tx_rows, block_rows, totals, tip


def write_state(accounts, tx_rows, block_rows, totals, logger):
    """Bulk-write the accumulated state into the KV index. accounts deltas are merged onto whatever
    docs already exist (the genesis accounts); registered/fidelity and the heartbeats sub-DB are
    left intact (this fast path mirrors reflect_transaction for transfers/bond/unbond, which is what
    accumulate_chain replays — it does not replay register/heartbeat)."""
    kv_ops.init_env(get_home())

    # --- accounts + totals: one write txn (merge balance/produced/bonded deltas onto existing) ---
    with kv_ops.write_txn():
        merged = {addr: dict(doc) for addr, doc in kv_ops.iter_accounts()}
        for addr, (d_balance, d_produced, d_bonded) in accounts.items():
            m = merged.get(addr)
            if m is None:
                m = merged[addr] = {"balance": 0, "produced": 0, "bonded": 0}
            m["balance"] = m.get("balance", 0) + d_balance
            m["produced"] = m.get("produced", 0) + d_produced
            m["bonded"] = m.get("bonded", 0) + d_bonded
        for addr, doc in merged.items():
            kv_ops.put_account(addr, doc)
        kv_ops.totals_set(totals[0], totals[1])

    # --- blocks ---
    with kv_ops.write_txn():
        for block_hash, height in block_rows:
            kv_ops.block_index_put(block_number=height, block_hash=block_hash)

    # --- tx index: rebuild from scratch (deduped by txid) ---
    seen = set()
    deduped = []
    for row in tx_rows:
        if row[0] not in seen:
            seen.add(row[0])
            deduped.append(row)

    with kv_ops.write_txn():
        kv_ops.drop_tx_index()
        for txid, height, sender, recipient in deduped:
            kv_ops.tx_index_put(txid=txid, block_number=height, sender=sender, recipient=recipient)

    logger.info(f"Reindex wrote {len(accounts)} account deltas, {len(deduped)} tx rows, {len(block_rows)} blocks")


def rebuild_from_blocks(logger):
    """full wipe + genesis + fast reindex from the local block files"""
    home = get_home()
    if os.path.exists(f"{home}/index"):
        shutil.rmtree(f"{home}/index")
    make_folder(f"{home}/index")
    make_folder(f"{home}/index/producer_sets")
    create_indexers()

    make_genesis(address=GENESIS_ADDRESS, balance=GENESIS_BALANCE, ip=GENESIS_IP,
                 port=9173, timestamp=GENESIS_TIMESTAMP, logger=logger)
    ends = get_block_ends_info(logger=logger)
    update_child_in_latest_block(child_hash=GENESIS_CHILD_HASH, logger=logger, parent=ends["latest_block"])

    accounts, tx_rows, block_rows, totals, tip = accumulate_chain(logger)
    write_state(accounts, tx_rows, block_rows, totals, logger)
    set_latest_block_info(latest_block=tip, logger=logger)
    logger.info(f"Reindex complete at tip height {tip['block_number']}")


if __name__ == "__main__":
    logger = get_logger(file="reindex.log", logger_name="reindex_logger")
    rebuild_from_blocks(logger)
