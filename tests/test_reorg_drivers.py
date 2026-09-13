"""THREE MEASURED REORG DRIVERS, ONE CHECK EACH.

2026-09-13, from /root/nado/fork_diffs.jsonl (356 splits in three days) and the two stragglers:

  * 115 of 141 different-tx-set splits were a `tpm_ready` WE held and the peer did not — our own
    announcement, born in the same pass that built the block. A transaction that entered the pool through
    this node waits one slot before it is eligible for this node's own block (_held_back).
  * 185.238.249.208 carried ITSELF in its peer list with no config ip, answered its own fork question,
    and sat BEHIND on an orphaned branch. A signed probe answer from our own key is not an answer
    (probe_block_hash_signed self_address).
  * 89.143.197.26/.28 refused the canonical 69056 as "already-mined" for months: tx-index rows left by an
    orphaned branch. A row naming a block that is not on our chain is residue and is dropped
    (_purge_index_residue).

Run: python3 tests/test_reorg_drivers.py
"""
import os, sys, tempfile, json, io

os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="nado_rd_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import loops.core_loop as CL                  # noqa: E402
from loops.core_loop import CoreClient        # noqa: E402
import ops.peer_ops as PO                     # noqa: E402
import ops.block_ops as BO                    # noqa: E402

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


class _Quiet:
    def __getattr__(self, _):
        return lambda *a, **k: None


class Stub:
    def __init__(self, tip):
        self.memserver = type("M", (), {})()
        self.memserver.latest_block = {"block_number": tip}
        self.memserver.own_born = {}
        self.logger = _Quiet()
        self._held_back = CoreClient._held_back.__get__(self)
        self._purge_index_residue = CoreClient._purge_index_residue.__get__(self)


# ---------------------------------------------------------------- 1. born here, this slot -> wait
s = Stub(tip=100)
s.memserver.own_born = {"fresh": 100, "old": 98}
check(s._held_back({"txid": "fresh"}, 101), "a tx born through us at the current tip is held out of our block for this slot")
check(not s._held_back({"txid": "old"}, 101), "one born two tips ago is eligible")
check(not s._held_back({"txid": "gossip"}, 101), "a tx that arrived by gossip is never held — peers already have it")
s.memserver.latest_block = {"block_number": 101}
check(not s._held_back({"txid": "fresh"}, 102), "...and the fresh one is eligible from the very next tip")

# ---------------------------------------------------------------- 2. our own signed answer is not an answer
class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False
import urllib.request as _ur
saved_open = _ur.urlopen
def fake_open(url, timeout=0):
    return _Resp(json.dumps({"block_hash": "a" * 64, "address": "ME", "public_key": "pk", "signature": "sig", "as_of": 500}).encode())
_ur.urlopen = fake_open          # the probe's local alias resolves urlopen through this module at call time
try:
    r_self = PO.probe_block_hash_signed("1.2.3.4", 500, tip_hint=500, self_address="ME")
    check(r_self is None, "a claim signed by OUR OWN address is discarded, whatever IP served it")
    r_other = PO.probe_block_hash_signed("1.2.3.4", 500, tip_hint=500, self_address="SOMEONE_ELSE")
    check(isinstance(r_other, tuple) and r_other[0] == "a" * 64, "another node's claim still counts")
    r_none = PO.probe_block_hash_signed("1.2.3.4", 500, tip_hint=500)
    check(isinstance(r_none, tuple), "with no self_address the probe behaves exactly as before")
finally:
    _ur.urlopen = saved_open

# ---------------------------------------------------------------- 3. orphaned index rows are residue
rows = {
    "t_canon":   {"block_number": 90, "sender": "s", "recipient": "r"},   # in our block 90 -> keep
    "t_orphan":  {"block_number": 95, "sender": "s", "recipient": "r"},   # our block 95 does not carry it -> drop
    "t_future":  {"block_number": 120, "sender": "s", "recipient": "r"},  # above our tip -> drop
}
chain = {90: {"block_transactions": [{"txid": "t_canon"}]}, 95: {"block_transactions": [{"txid": "other"}]}}
deleted = []
class FakeKV:
    @staticmethod
    def tx_get(txid): return rows.get(txid)
    @staticmethod
    def tx_index_del(txid, block_number, sender, recipient): deleted.append((txid, block_number)); rows.pop(txid, None)
saved_kv, saved_gbn = CL.kv_ops, BO.get_block_number
CL.kv_ops = FakeKV
BO.get_block_number = lambda n: chain.get(n)
try:
    s = Stub(tip=100)
    dropped = s._purge_index_residue(["t_canon", "t_orphan", "t_future", "t_missing"])
    check(sorted(dropped) == ["t_future", "t_orphan"], f"rows naming a block not on our chain are dropped ({dropped})")
    check("t_canon" in rows, "a row whose block really carries the tx is kept — that IS a replay")
    check(sorted(x[0] for x in deleted) == ["t_future", "t_orphan"], "...and only those rows were deleted")
finally:
    CL.kv_ops, BO.get_block_number = saved_kv, saved_gbn

# ---------------------------------------------------------------- 4. blind index -> build nothing, judge nothing
import threading
from protocol import TX_AT_MOST_ONCE_STRICT_HEIGHT
s = Stub(tip=100)
s._tx_index_incomplete = CoreClient._tx_index_incomplete.__get__(s)
check(not s._tx_index_incomplete(), "no rebuild running and no marker -> the index is complete")
ev = threading.Event()
s._tx_reindex_thread = threading.Thread(target=ev.wait, daemon=True); s._tx_reindex_thread.start()
check(s._tx_index_incomplete(), "a running rebuild thread -> incomplete (build nothing, judge nothing)")
ev.set(); s._tx_reindex_thread.join(2)
from config import get_home                       # the node reads get_home()/index/, not $HOME/index/
marker = os.path.join(get_home(), "index"); os.makedirs(marker, exist_ok=True)
open(os.path.join(marker, "tx_reindex.json"), "w").write('{"next": 5}')
check(s._tx_index_incomplete(), "a resumable rebuild marker on disk -> incomplete, even with no thread")
os.remove(os.path.join(marker, "tx_reindex.json"))
check(not s._tx_index_incomplete(), "...and complete again once the marker is gone")

# ---------------------------------------------------------------- 5. the chain's own replays stand below the gate
G = TX_AT_MOST_ONCE_STRICT_HEIGHT
check(CoreClient._replay_tolerated(G - 1), f"a replay in block {G - 1} (below the strict height) is tolerated")
check(not CoreClient._replay_tolerated(G), f"...and at {G} the rule is strict")
check(CoreClient._replay_tolerated(69056) and CoreClient._replay_tolerated(78078),
      "the measured replay blocks 69056 and 78078 are below the gate on this chain")

print(("\nFAILED: " + "; ".join(fails)) if fails else "\nall checks passed")
sys.exit(1 if fails else 0)
