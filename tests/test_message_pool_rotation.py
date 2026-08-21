"""Byte-budget rotation of the off-chain message pool (replaces the 7-day TTL as the primary bound).

Run: python3 tests/test_message_pool_rotation.py
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops.message_pool import MessagePool, MSG_TTL_SECONDS, MSG_POOL_MAX_BYTES, _rough_size
from tests.test_message_pool import make_env, YES   # reuses the cheap-PoW envelope factory

fails = 0
def check(cond, msg):
    global fails
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond: fails += 1

now = 1_700_000_000
one = _rough_size(make_env(ct="c0", ts=now))
budget = one * 3 + 10                              # room for exactly three envelopes

# --- rotation: the 4th insert evicts the 1st, the 5th evicts the 2nd; newest always survives ---
p = MessagePool(max_pool_bytes=budget)
ids = [p.add_message(make_env(ct=f"c{i}", ts=now + i), now + i, YES, YES)[2] for i in range(5)]
check(len(p.messages) == 3, f"byte budget not enforced: {len(p.messages)} msgs")
check(p.total_bytes <= budget, f"total_bytes {p.total_bytes} over budget {budget}")
check(p.total_bytes == sum(r['size'] for r in p.messages.values()), "total_bytes meter drifted")
check(p.get_message(ids[0]) is None and p.get_message(ids[1]) is None, "oldest two should be rotated out")
check(all(p.get_message(i) is not None for i in ids[2:]), "newest three must survive")
check(p.stats()["bytes"] == p.total_bytes and p.stats()["max_bytes"] == budget, "stats lacks byte meter")

# --- drop() frees budget: after an ack-drop a new insert no longer evicts ---
freed = p.messages[ids[2]]["size"]; before = p.total_bytes
p.drop(ids[2])
check(p.total_bytes == before - freed, f"drop did not release bytes: {p.total_bytes}")
p.add_message(make_env(ct="c9", ts=now + 9), now + 9, YES, YES)
check(len(p.messages) == 3 and p.get_message(ids[3]) is not None, "drop-freed space should absorb insert")

# --- gc() keeps the meter honest; TTL is a backstop far longer than 7 days ---
check(MSG_TTL_SECONDS >= 30 * 24 * 3600, "TTL backstop should be much longer than the old 7 days")
check(p.gc(now + MSG_TTL_SECONDS + 100) == 3 and p.total_bytes == 0, "gc must zero the meter")

# --- default budget is the requested 5 MiB ---
check(MSG_POOL_MAX_BYTES == 5 * 1024 * 1024, f"default budget {MSG_POOL_MAX_BYTES}")

# --- persistence: legacy file without 'size' is re-measured; shrunk budget rotates on load ---
q = MessagePool(max_pool_bytes=budget)
qids = [q.add_message(make_env(ct=f"d{i}", ts=now + i), now + i, YES, YES)[2] for i in range(3)]
qtotal = q.total_bytes
for r in q.messages.values():
    del r["size"]                                   # simulate a pre-rotation pool file
q._dirty = True
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "pool.bin")
    q.save(path)
    r1 = MessagePool(max_pool_bytes=budget); r1.load(path, now + 3)
    check(len(r1.messages) == 3 and r1.total_bytes == qtotal, "legacy load must re-measure sizes")
    check(list(r1.messages) == qids, "load must restore seq order")
    r2 = MessagePool(max_pool_bytes=one + 1); r2.load(path, now + 3)
    check(len(r2.messages) == 1 and qids[2] in r2.messages and r2._dirty,
          "shrunk budget must rotate oldest on load and mark dirty")

print("\nALL ROTATION CHECKS PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
