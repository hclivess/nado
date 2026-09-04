# tests/test_prune_expired_pool.py — the core loop prunes expired txs EVERY pass, in EVERY mode.
# 2026-09-04: a relay stuck in emergency sync held a 10 MiB settle tx 1,500 blocks past its max_block because
# eviction only ran on the produce path; peers re-pulled it ~1/s and 67 % of the GIL went to serialising it.
import os, sys, tempfile, threading
sys.path.insert(0, "/root/nado")
os.environ.setdefault("NADO_HOME", tempfile.mkdtemp(prefix="nado-prune-test-"))
os.environ.setdefault("HOME", os.environ["NADO_HOME"])

F = []
def ck(n, c): print(("  ok  " if c else " FAIL ") + n); (F.append(n) if not c else None)

from loops.core_loop import CoreClient
from protocol import TX_LANDING_WINDOW

class _Log:
    def __init__(self): self.lines = []
    def info(self, m): self.lines.append(m)
    warning = error = debug = info

class _MS:
    def __init__(self, pool, height):
        self.transaction_pool = pool; self.latest_block = {"block_number": height}; self.mempool_lock = threading.Lock()

class _Loop:
    prune_expired_pool = CoreClient.prune_expired_pool
    def __init__(self, ms): self.memserver = ms; self.logger = _Log()

H = 35978
live = {"txid": "live", "max_block": H + 50, "data": "x"}
expired = {"txid": "expired", "max_block": 34483, "data": "y" * 1000}
edge = {"txid": "edge", "max_block": H, "data": "z"}                       # max_block == tip: can no longer land
far = {"txid": "far", "max_block": H + TX_LANDING_WINDOW + 1, "data": "w"}   # beyond the landing window
pool = [live, expired, edge, far]
loop = _Loop(_MS(pool, H))
n = loop.prune_expired_pool()
ck("three of four dropped", n == 3)
ck("only the live tx remains", [t["txid"] for t in loop.memserver.transaction_pool] == ["live"])
ck("pool object replaced when something went", loop.memserver.transaction_pool is not pool)
ck("prune logged", any("Pruned 3" in l for l in loop.logger.lines))
same = loop.memserver.transaction_pool
ck("nothing to drop → 0", loop.prune_expired_pool() == 0)
ck("pool object untouched when nothing went", loop.memserver.transaction_pool is same)
loop2 = _Loop(_MS([expired], None)); loop2.memserver.latest_block = None
ck("no tip yet → 0, no crash", loop2.prune_expired_pool() == 0)
print("FAILED:", F) if F else print("ALL OK"); sys.exit(1 if F else 0)
