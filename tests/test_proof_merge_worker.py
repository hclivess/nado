#!/usr/bin/env python3
"""A proof-bearing settle from a peer's mempool must never be verified INLINE in the peer loop.

2026-08-29: a restarted node spent 20+ minutes inside verify_settlement_sparse on the peer-loop thread;
status_pool stayed empty behind it, the node saw no peer ahead, stayed in produce mode and sat 70 blocks
behind a mesh it believed it led. Now: proof settles go to a single worker thread (same merge_transaction,
same admission rules), one verification per txid.   Run: python3 tests/test_proof_merge_worker.py"""
import sys, os, time, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from memserver import MemServer   # noqa: E402

passed = failed = 0
def ok(c, m):
    global passed, failed
    if c: passed += 1; print(f"  ok   {m}")
    else: failed += 1; print(f"  FAIL {m}")

ok(MemServer._is_proof_settle({"recipient": "settle", "data": {"proof": "…"}}), "a settle carrying a proof is a proof settle")
ok(MemServer._is_proof_settle({"recipient": "settle", "data": {"proof_da": "abcd"}}), "…so is one carrying a DA commitment")
ok(not MemServer._is_proof_settle({"recipient": "settle", "data": {"ns": "default"}}), "a bare quorum settle is not")
ok(not MemServer._is_proof_settle({"recipient": "transfer", "data": {"proof": "x"}}), "a non-settle with a 'proof' field is not")

ms = object.__new__(MemServer)                       # no constructor: no DB, no loops
merged, lock = [], threading.Lock()
class _Log:
    def error(self, m): print("   log:", m)
ms.logger = _Log()
ms._pool_txid_set = lambda: set()
def slow_merge(tx, user_origin):
    time.sleep(0.2)                                  # stands in for a minutes-long verification
    with lock: merged.append(tx["txid"])
    return {"result": True}
ms.merge_transaction = slow_merge
t0 = time.time()
ms._queue_proof_merge({"txid": "A", "recipient": "settle", "data": {"proof": 1}}, False)
ms._queue_proof_merge({"txid": "A", "recipient": "settle", "data": {"proof": 1}}, False)   # duplicate while in flight
ms._queue_proof_merge({"txid": "B", "recipient": "settle", "data": {"proof": 1}}, False)
ok(time.time() - t0 < 0.1, "queueing returns immediately — the caller's thread is not blocked by the verification")
deadline = time.time() + 3
while time.time() < deadline and len(merged) < 2: time.sleep(0.05)
ok(merged == ["A", "B"], f"the worker verified each proof once, in order ({merged})")
ok(not ms._proof_inflight, "nothing left in flight")
print(f"\n[proof-worker] {passed} passed, {failed} failed"); sys.exit(1 if failed else 0)
