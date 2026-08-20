"""Thundering-herd lock on latest_settled (2026-08-20): after every write txn a dozen Tornado
workers missed the generation key at once and each re-ran the unjustified-top-cursor walk
concurrently — ~80% of busy samples in py-spy, starving the core thread to 37s/block applies.
The herd must resolve to exactly ONE compute per generation."""
import os, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("NADO_HOME", "/tmp/nado-settle-lock-test-home")
os.makedirs(os.environ["NADO_HOME"], exist_ok=True)
from ops import settlement_ops as so


def t1_herd_resolves_to_one_compute():
    calls = [0]
    def slow(ns="default"):
        calls[0] += 1
        time.sleep(0.2)
        return (-1, None)
    orig = (so._latest_settled_uncached, so.kv_ops.env_path,
            so.kv_ops.write_generation, so.kv_ops.in_write_txn)
    so._latest_settled_uncached = slow
    so.kv_ops.env_path = lambda *a, **k: "/tmp/x"
    so.kv_ops.write_generation = lambda *a, **k: 7
    so.kv_ops.in_write_txn = lambda *a, **k: False
    so._latest_settled_cache[0] = None
    try:
        res = []
        ts = [threading.Thread(target=lambda: res.append(so.latest_settled("default")))
              for _ in range(12)]
        t0 = time.time()
        [t.start() for t in ts]; [t.join() for t in ts]
        el = time.time() - t0
        assert calls[0] == 1, f"herd must resolve to ONE compute, got {calls[0]}"
        assert len(res) == 12 and all(r == (-1, None) for r in res)
        assert el < 1.0, f"12 threads should cost ~one compute, took {el:.2f}s"
    finally:
        (so._latest_settled_uncached, so.kv_ops.env_path,
         so.kv_ops.write_generation, so.kv_ops.in_write_txn) = orig
        so._latest_settled_cache[0] = None


def t2_write_txn_still_bypasses():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "ops", "settlement_ops.py")).read()
    i = src.index("def latest_settled")
    seg = src[i:i + 2600]
    assert seg.index("in_write_txn()") < seg.index("_latest_settled_lock"), \
        "the in-write-txn bypass must come BEFORE the lock (core thread must never block mid-txn)"
    assert seg.count("entry[0] == key") >= 2, \
        "the cache must be re-checked after acquiring the lock (double-checked pattern)"


if __name__ == "__main__":
    fails = 0
    for name in ("t1_herd_resolves_to_one_compute", "t2_write_txn_still_bypasses"):
        try:
            globals()[name]()
            print(f"PASS  {name}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL  {name}: {e}")
    print("ALL PASS" if not fails else f"{fails} FAILURE(S)")
    raise SystemExit(1 if fails else 0)
