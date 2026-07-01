"""
Rebuild ONLY the transaction index (tx / tx_by_sender / tx_by_recipient) from the local block files,
resolving alias recipients to their owner address — so send-to-alias payments appear in the recipient's
history. Balances/accounts are NEVER touched (this is a derived index), so it cannot corrupt state; the
worst case of an interrupted run is a partial index that a re-run completes.

Run with the NODE STOPPED (LMDB is single-writer):  HOME=<datadir> python scripts/reindex_tx.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from genesis import create_indexers
from ops import kv_ops, alias_ops
from ops.block_ops import get_block, get_block_ends_info
from ops.log_ops import get_logger


def main():
    logger = get_logger(logger_name="reindex_tx")
    create_indexers()
    tip = get_block_ends_info(logger=logger)["latest_block"]["block_number"]
    kv_ops.drop_tx_index()                      # clear the old (alias-string-misfiled) index
    n_tx, n_alias = 0, 0
    for h in range(0, tip + 1):
        bh = kv_ops.hash_by_number(h)
        if not bh:
            continue
        block = get_block(bh)
        if not block:
            continue
        for tx in block.get("block_transactions", []):
            resolved = alias_ops.resolve_alias(tx["recipient"]) or tx["recipient"]
            if resolved != tx["recipient"]:
                n_alias += 1
            kv_ops.tx_index_put(txid=tx["txid"], block_number=h,
                                sender=tx["sender"], recipient=resolved)
            n_tx += 1
    print(f"reindexed {n_tx} transactions across blocks 0..{tip} "
          f"({n_alias} send-to-alias resolved to their owner)")


if __name__ == "__main__":
    main()
