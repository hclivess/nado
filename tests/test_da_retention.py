"""The DA store must be a ROLLING WINDOW, not an append-only archive.

MEASURED 2026-08-06 on the alphanet-15 node: exec_da held 41 GB in 109 objects (1,916 files) — every settle
proof published during the 2026-08-04/05 transport work, ~390 MB each (a ~120 MiB proof erasure-coded
k=4/n=8). That was 99.8% of the node's 41 GB footprint; the blocks themselves were 75 MB. A snapshot node
had quietly become an archival one, and the disk was at 87%.

THE CAUSE was not a missing design — DaStore's own module docstring says "Storage is a rolling window: once
a commitment's effect is settled + snapshotted, prune() drops it". prune() was written for exactly this and,
until this change, was called from ONE place in the entire tree: tests/test_da_store.py. Production never
called it.

NOTHING NEEDS THE OLD OBJECTS: protocol.SETTLE_PROOF_DEPTH_GATED means a settle proof is verified near the
TIP and deeper blocks accept without re-fetching it, so an object is only reachable for a short window after
publication. A COUNT is the right bound rather than an age — it caps disk at retain x blob size regardless
of settle cadence, and it degrades safely, keeping exactly the newest objects (the only fetchable ones).

Run: python3 tests/test_da_retention.py
"""
import os
import shutil
import sys
import tempfile
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops.da_store import DaStore

fails = 0


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


def _tmp():
    return tempfile.mkdtemp(prefix="da_retain_")


def _objs(root):
    return [n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))]


def t_put_enforces_the_window():
    root = _tmp()
    try:
        s = DaStore(root, retain=3)
        for i in range(8):
            s.put(b"blob-%04d" % i + b"x" * 300, 2, 4)
            time.sleep(0.01)                      # distinct mtimes so "newest" is well defined
        assert len(_objs(root)) == 3, f"expected 3 objects retained, found {len(_objs(root))}"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def t_the_newest_object_survives_its_own_put():
    """The sweep runs AFTER the write, so a freshly published object must never be its own victim —
    otherwise a publisher would delete the very blob a peer is about to fetch."""
    root = _tmp()
    try:
        s = DaStore(root, retain=2)
        last = None
        for i in range(6):
            last = s.put(b"payload-%04d" % i + b"y" * 300, 2, 4)
            time.sleep(0.01)
            assert s.have(last["commitment"]), "the object just published was swept away"
        assert s.get(last["commitment"]) is not None, "the newest object must still be readable"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def t_retain_none_is_unbounded():
    """Tests and any caller managing its own window must be unaffected."""
    root = _tmp()
    try:
        s = DaStore(root)
        for i in range(5):
            s.put(b"z-%04d" % i + b"z" * 100, 2, 4)
        assert len(_objs(root)) == 5, "retain=None must not drop anything"
        assert s.sweep() == 0, "sweep() with no window must be a no-op"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def t_sweep_is_idempotent_and_safe_on_a_missing_root():
    root = _tmp()
    try:
        s = DaStore(root, retain=1)
        for i in range(4):
            s.put(b"w-%04d" % i + b"w" * 100, 2, 4)
            time.sleep(0.01)
        assert s.sweep() == 0, "a second sweep at the window size must drop nothing"
        shutil.rmtree(root, ignore_errors=True)
        assert s.sweep() == 0, "sweep must not raise when the root has vanished"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def t_exec_node_constructs_a_bounded_store():
    """The whole failure was that production never bounded it — pin that both construction sites do."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "execnode", "execnode.py")).read()
    assert src.count("DaStore(DA_DIR, retain=DA_RETAIN)") == 2, \
        "both DaStore constructions in the exec node must pass a retention bound"
    assert "DaStore(DA_DIR)" not in src.replace("DaStore(DA_DIR, retain=DA_RETAIN)", ""), \
        "an unbounded DaStore construction is still present"
    assert "NADO_DA_RETAIN" in src, "the window must be operator-overridable"


for nm, fn in [("put() enforces the window", t_put_enforces_the_window),
               ("the newest object survives its own put", t_the_newest_object_survives_its_own_put),
               ("retain=None stays unbounded", t_retain_none_is_unbounded),
               ("sweep is idempotent and crash-safe", t_sweep_is_idempotent_and_safe_on_a_missing_root),
               ("the exec node constructs a bounded store", t_exec_node_constructs_a_bounded_store)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
