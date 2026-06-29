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
from ops.sqlite_ops import DbHandler
from genesis import make_genesis, create_indexers
from ops.log_ops import get_logger

GENESIS_ADDRESS = "ndo18c3afa286439e7ebcb284710dbd4ae42bdaf21b80137b"
GENESIS_CHILD_HASH = "3abbfe409d446d997fbf65767c97e3f59ecb943d61a000240432e1627187966b"
GENESIS_BALANCE = 1000000000000000000
GENESIS_TIMESTAMP = 1669852800
GENESIS_IP = "78.102.98.72"
FEE_HEIGHT = 111111  # at/above this height the fee is debited from the sender


def accumulate_chain(logger, log_every=50000):
    """Walk the chain from genesis via child_hash links and accumulate full state
    in memory. Returns (accounts, tx_rows, block_rows, totals, tip_block).

    accounts: {address: [balance_delta, produced_delta, burned_delta]}
    totals:   [produced, fees, burned]
    Mirrors reflect_transaction()/index_totals()."""
    accounts = {}
    tx_rows = []
    block_rows = []
    totals = [0, 0, 0]  # produced, fees, burned

    def adj(addr, balance=0, produced=0, burned=0):
        a = accounts.get(addr)
        if a is None:
            a = accounts[addr] = [0, 0, 0]
        a[0] += balance
        a[1] += produced
        a[2] += burned

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
            amount_sender = amount + fee if height > FEE_HEIGHT else amount
            is_burn = tx["recipient"] == "burn"
            adj(tx["sender"], balance=-amount_sender, burned=amount_sender if is_burn else 0)
            adj(tx["recipient"], balance=amount)
            tx_rows.append((tx["txid"], height, tx["sender"], tx["recipient"]))

        reward = block["block_reward"]
        adj(block["block_creator"], balance=reward, produced=reward)
        block_rows.append((block["block_hash"], height))

        if reward > 0:
            totals[0] += reward
        if height > FEE_HEIGHT:
            totals[1] += sum(tx["fee"] for tx in block["block_transactions"])
        totals[2] += sum(tx["amount"] for tx in block["block_transactions"] if tx["recipient"] == "burn")

        count += 1
        if count % log_every == 0:
            logger.info(f"Reindex accumulated {count} blocks (height {height})")

    logger.info(f"Reindex accumulated {count} blocks, {len(accounts)} accounts, {len(tx_rows)} txs")
    return accounts, tx_rows, block_rows, totals, tip


def write_state(accounts, tx_rows, block_rows, totals, logger):
    """Bulk-write the accumulated state. accounts deltas are merged onto whatever
    rows already exist (the genesis account)."""
    home = get_home()

    # --- accounts + totals: one transaction ---
    acc = DbHandler(db_file=f"{home}/index/accounts.db")
    try:
        existing = acc.db_fetch("SELECT address, balance, produced, burned FROM acc_index")
        merged = {row[0]: [row[1], row[2], row[3]] for row in existing}
        for addr, (db, dp, dbn) in accounts.items():
            m = merged.get(addr)
            if m is None:
                m = merged[addr] = [0, 0, 0]
            m[0] += db
            m[1] += dp
            m[2] += dbn
        acc.db_execute("DELETE FROM acc_index")
        acc.db_executemany(
            "INSERT INTO acc_index (address, balance, produced, burned) VALUES (?,?,?,?)",
            [(a, v[0], v[1], v[2]) for a, v in merged.items()])
        acc.db_execute("UPDATE totals_index SET produced=?, fees=?, burned=?", (totals[0], totals[1], totals[2]))
    finally:
        acc.close()

    # --- blocks ---
    blk = DbHandler(db_file=f"{home}/index/blocks.db")
    try:
        blk.db_executemany("INSERT OR IGNORE INTO block_index (block_hash, block_number) VALUES (?,?)", block_rows)
    finally:
        blk.close()

    # --- tx index: drop indexes, bulk insert (deduped by txid), rebuild indexes ---
    seen = set()
    deduped = []
    for row in tx_rows:
        if row[0] not in seen:
            seen.add(row[0])
            deduped.append(row)

    tx = DbHandler(db_file=f"{home}/index/transactions.db")
    try:
        tx.db_execute("CREATE TABLE IF NOT EXISTS tx_index(txid TEXT, block_number INTEGER, sender TEXT, recipient TEXT)")
        for idx in ("idx_txid", "idx_sender", "idx_recipient"):
            tx.db_execute(f"DROP INDEX IF EXISTS {idx}")
        tx.db_executemany("INSERT OR IGNORE INTO tx_index VALUES (?,?,?,?)", deduped)
        tx.db_execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_txid ON tx_index(txid)")
        tx.db_execute("CREATE INDEX IF NOT EXISTS idx_sender ON tx_index(sender, block_number)")
        tx.db_execute("CREATE INDEX IF NOT EXISTS idx_recipient ON tx_index(recipient, block_number)")
    finally:
        tx.close()

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
