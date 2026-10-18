"""An account's transaction history says where a FULL page stopped (transaction_ops.get_transactions_of_account:
`more` + `last_block`), and a short page says nothing — the only way a caller can page, because a transaction carries
no block number of its own. The wallet's deposit restore pages on it (interface.js stwoOwnTransactions); before this,
an account with more than ~1000 indexed transactions never had its later fresh-owner deposits found on a new device.

Run: python3 tests/test_account_history_says_where_a_full_page_stopped.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-acct-page-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import transaction_ops as T

import _harness
_report = _harness.Report()
check = _report.check


# 5 transactions over blocks 3, 3, 4, 9, 9 (index entries are block-ordered)
index = [(3, "a"), (3, "b"), (4, "c"), (9, "d"), (9, "e")]
blocks = {b: {"block_transactions": [{"txid": t} for bb, t in index if bb == b]} for b in {3, 4, 9}}
T.kv_ops.tx_of_account = lambda acct, mb, limit: [e for e in index if e[0] >= mb][:limit]
T.get_block_number = lambda number: blocks.get(number)

full = T.get_transactions_of_account("x", 0, limit=4)
check("a full page lists its transactions", [t["txid"] for t in full["transactions"]] == ["a", "b", "c", "d"], full)
check("and says there is more, stopping in block 9", full.get("more") is True and full.get("last_block") == 9, full)
nxt = T.get_transactions_of_account("x", full["last_block"], limit=4)
check("the next page from that block holds the rest (the seam repeats, callers dedupe)",
      [t["txid"] for t in nxt["transactions"]] == ["d", "e"] and "more" not in nxt, nxt)
short = T.get_transactions_of_account("x", 0, limit=1000)
check("a short page carries no cursor (the reply shape is unchanged for every other caller)",
      set(short) == {"transactions"} and len(short["transactions"]) == 5, short)
print("ALL PASS — account history says where a full page stopped" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
