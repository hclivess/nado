# tests/test_prune_expired_pool.py — the MEMPOOL OWNER prunes expired txs on the peer loop's clock (every mode),
# and peer-facing reads never see a tx that can no longer land.
# 2026-09-04: a relay stuck in emergency sync held a 10 MiB settle tx 1,500 blocks past its max_block because
# eviction ran only on the produce path; a first fix hooked the core-loop pass, which never ends while behind
# (emergency_mode loops internally). Pruning belongs to the pool owner, driven by a thread that always ticks.
import os, sys, tempfile, threading, re
sys.path.insert(0, "/root/nado")
os.environ.setdefault("NADO_HOME", tempfile.mkdtemp(prefix="nado-prune-test-"))

F = []
def ck(n, c): print(("  ok  " if c else " FAIL ") + n); (F.append(n) if not c else None)

from memserver import MemServer
from protocol import TX_LANDING_WINDOW

class _Log:
    def __init__(self): self.lines = []
    def warning(self, m): self.lines.append(m)
    info = error = debug = warning

class _MS:
    _tx_can_land = MemServer._tx_can_land; live_pool = MemServer.live_pool; prune_expired_pool = MemServer.prune_expired_pool
    def __init__(self, pool, height):
        self.transaction_pool = pool; self.latest_block = {"block_number": height}
        self.mempool_lock = threading.RLock(); self.logger = _Log()

H = 35978
live = {"txid": "live", "max_block": H + 50, "data": "x"}
expired = {"txid": "expired", "max_block": 34483, "data": "y" * 1000}
edge = {"txid": "edge", "max_block": H, "data": "z"}                       # max_block == tip: can no longer land
far = {"txid": "far", "max_block": H + TX_LANDING_WINDOW + 1, "data": "w"}   # beyond the landing window
pool = [live, expired, edge, far]
ms = _MS(pool, H)
ck("live_pool hides the three dead txs before any prune", [t["txid"] for t in ms.live_pool()] == ["live"])
ck("live_pool does not mutate the pool", ms.transaction_pool is pool and len(pool) == 4)
n = ms.prune_expired_pool()
ck("three of four dropped", n == 3)
ck("only the live tx remains", [t["txid"] for t in ms.transaction_pool] == ["live"])
ck("pool object replaced when something went", ms.transaction_pool is not pool)
ck("prune logged at warning", any("Pruned 3" in l for l in ms.logger.lines))
same = ms.transaction_pool
ck("nothing to drop → 0", ms.prune_expired_pool() == 0)
ck("pool object untouched when nothing went", ms.transaction_pool is same)
ms2 = _MS([expired], H); ms2.latest_block = None
ck("no tip yet → 0, no crash", ms2.prune_expired_pool() == 0)
ck("no tip yet → live_pool serves everything (admission decides)", len(ms2.live_pool()) == 1)

# WIRING: the peer loop ticks the prune every pass; the three peer-facing pool reads go through live_pool.
src = open("/root/nado/loops/peer_loop.py").read()
ck("peer loop prunes before reconciling", src.index("prune_expired_pool()") < src.index("merge_remote_transactions(user_origin=False"))
api = open("/root/nado/nado.py").read()
ck("/transactions_by_id serves live_pool", 'memserver.live_pool() if t.get("txid") in wanted' in api)
ck("/transaction_ids lists live_pool", 't.get("txid") for t in memserver.live_pool()' in api)
ck("/transaction_pool dumps live_pool", 'lambda: memserver.live_pool()' in api)
ck("save_pool persists live_pool", "txs = self.live_pool()" in open("/root/nado/memserver.py").read())
ck("core loop no longer carries its own prune", "prune_expired_pool" not in open("/root/nado/loops/core_loop.py").read())
print("FAILED:", F) if F else print("ALL OK"); sys.exit(1 if F else 0)
