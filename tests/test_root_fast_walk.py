"""THE ROOT-ONLY STATE WALK MUST BE BYTE-IDENTICAL TO THE FULL WALK IT REPLACES (2026-09-01).

l1_state_root() used to materialise the ENTIRE snapshot state — 317k rows / 35 MB at block 82.9k, more
than half of it block_by_num/block_by_hash and windowed-out attestations/commits/reveals — sort it, and
then throw 92% of it away in _root_triples. At a 6-second block time that walk was ~0.7 s of GIL per
block on the core thread (py-spy: 21% of ALL process CPU), and the node ran chronically behind while
serving 500+ wallets. snapshot_ops._walk_root_rows applies the same exclusions and retention window to
KEYS before any value is copied, seeks straight to the floor in the epoch-prefixed families, and yields
in canonical order. This file pins that it is the same function: same row set, same order, same root —
across the cases where the two could plausibly disagree (the decimal epochw keys, the window edge, an
unparseable epoch, a default account doc, excluded keys/prefixes/DBs, DUPSORT values, a changed value
under the plain-row digest cache). Any drift here is a consensus fork, not a performance regression.
"""
import os
import re
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("" if cond else f": {detail}")))
    if not cond:
        _fails.append(name)


def _fresh_home():
    d = tempfile.mkdtemp(prefix="nado-rootwalk-")
    os.environ["HOME"] = d
    from ops import kv_ops
    kv_ops.close_all()
    kv_ops.init_env()
    return d


def _fixture_rows(kv_ops, so, EPOCH_LENGTH):
    ref_epoch = so.ROOT_RETENTION_EPOCHS + 25
    floor = ref_epoch - so.ROOT_RETENTION_EPOCHS
    rows = []
    rows.append(("accounts", b"aa" * 23, kv_ops._pack(kv_ops._normalize({"balance": 5, "registered": 1}))))
    rows.append(("accounts", b"bb" * 23, kv_ops._pack(kv_ops._normalize({}))))       # absent-equivalent
    rows.append(("totals", b"supply", b"123"))
    # decimal epochw keys: lexicographic order (b"epochw:9" > b"epochw:85") must NOT pick the reference
    for e in (9, ref_epoch, 70):
        rows.append(("meta", b"epochw:%d" % e, b"w" * 50))
    for k in so.ROOT_EXCLUDED_META_KEYS:
        rows.append(("meta", k, b"1"))
    for pfx in so.ROOT_EXCLUDED_META_PREFIXES:
        rows.append(("meta", pfx + b"x", b"1"))
    for e in (floor - 1, floor, floor + 1, ref_epoch):
        rows.append(("meta", b"att:addr:%d" % e, b"1"))
        rows.append(("meta", b"divnull:addr:%d" % e, b"1"))
        rows.append(("meta", b"settle:ns:addr:%d" % (e * EPOCH_LENGTH), b"1"))
        rows.append(("commits", b"addr|%d" % e, b"c"))
        for db in ("reveals", "attestations", "recert_by_epoch"):
            rows.append((db, kv_ops.be8(e), b"v%d" % e))
            rows.append((db, kv_ops.be8(e), b"u%d" % e))                             # DUPSORT second value
        rows.append(("settlements", b"ns\x00" + kv_ops.be8(e * EPOCH_LENGTH), b"s"))
    rows.append(("meta", b"att:unparseable", b"1"))                                  # epoch None -> kept
    rows.append(("meta", b"zzz_plain", b"p"))
    rows.append(("recerts", b"addr", kv_ops.be8(3)))
    rows.append(("bond_since", b"addr", kv_ops.be8(1)))
    rows.append(("block_by_num", kv_ops.be8(1), b"body"))                            # ROOT_EXCLUDED_DBS
    rows.append(("treasury_proposals", b"p", b"x"))
    return rows, floor


def t1_fast_walk_equals_slow_path():
    _fresh_home()
    from ops import kv_ops
    from ops import snapshot_ops as so
    from protocol import EPOCH_LENGTH
    rows, floor = _fixture_rows(kv_ops, so, EPOCH_LENGTH)
    kv_ops.restore_snapshot_state(rows)
    slow = so._root_triples(so.read_state())
    fast = so.read_root_state()
    check("row set + order identical to _root_triples(read_state())", slow == fast,
          f"slow={len(slow)} fast={len(fast)} only_slow={list(set(slow) - set(fast))[:3]} "
          f"only_fast={list(set(fast) - set(slow))[:3]}")
    check("walk order is the canonical (db, key, value) sort",
          fast == sorted(fast, key=lambda t: (t[0], t[1], t[2])))
    r_slow = so.merkle_root(slow)
    check("root from the walk == root from the slow path", so._root_from_walk() == r_slow)
    check("l1_state_root == slow root", so.l1_state_root() == r_slow)
    keys = {(t[0], t[1]) for t in fast}
    names = {t[0] for t in fast}
    check("excluded DBs never walked", not ({"block_by_num", "block_by_hash", "treasury_proposals"} & names))
    check("window edge: floor-1 dropped, floor kept (meta att)",
          ("meta", b"att:addr:%d" % (floor - 1)) not in keys and ("meta", b"att:addr:%d" % floor) in keys)
    check("window edge: epoch-prefixed seek (reveals)",
          ("reveals", kv_ops.be8(floor - 1)) not in keys and ("reveals", kv_ops.be8(floor)) in keys)
    check("both DUPSORT values of a kept key survive",
          sum(1 for t in fast if t[0] == "reveals" and t[1] == kv_ops.be8(floor)) == 2)
    check("commits windowed by the epoch at the END of the key",
          ("commits", b"addr|%d" % (floor - 1)) not in keys and ("commits", b"addr|%d" % floor) in keys)
    check("default account doc dropped, real one kept",
          ("accounts", b"bb" * 23) not in keys and ("accounts", b"aa" * 23) in keys)
    check("unparseable windowed key kept", ("meta", b"att:unparseable") in keys)
    check("excluded meta keys/prefixes dropped",
          not any(k in so.ROOT_EXCLUDED_META_KEYS or k.startswith(so.ROOT_EXCLUDED_META_PREFIXES)
                  for n, k in keys if n == "meta"))
    check("every epochw row kept (not windowed)", sum(1 for n, k in keys if k.startswith(b"epochw:")) == 3)

    # A CHANGED plain-row value must invalidate its cached digest (memcmp against the buffer, not a key hit).
    r0 = so.l1_state_root()
    kv_ops.account_set("aa" * 23, "balance", 6)
    r1 = so.l1_state_root()
    check("changed account value changes the root", r1 != r0)
    check("...and still matches the slow path", r1 == so.merkle_root(so._root_triples(so.read_state())))
    rows2 = [(n, k, (b"W" * 50 if (n, k) == ("meta", b"epochw:70") else v)) for n, k, v in rows]
    kv_ops.restore_snapshot_state(rows2)
    r2 = so.l1_state_root()
    check("changed epochw value changes the root", r2 not in (r0, r1))
    check("...and still matches the slow path", r2 == so.merkle_root(so._root_triples(so.read_state())))
    # Reference epoch below the retention window: no window at all, both paths identical
    rows3 = [(n, k, v) for n, k, v in rows if not k.startswith(b"epochw:")] + [("meta", b"epochw:5", b"w")]
    kv_ops.restore_snapshot_state(rows3)
    check("no-window regime identical", so.read_root_state() == so._root_triples(so.read_state()))
    check("state_fingerprint root == l1_state_root", so.state_fingerprint()[0] == so.l1_state_root())
    kv_ops.close_all()


def t2_epoch_prefixed_writers_use_be8():
    """The floor SEEK in reveals/attestations/recert_by_epoch is exact only if every key is be8(epoch):
    a shorter key would be kept by the slow path (epoch None) yet could sort below the seek point."""
    src = open(os.path.join(ROOT, "ops", "kv_ops.py")).read()
    from ops import snapshot_ops as so
    bad = []
    for line in src.splitlines():
        for db in so._EPOCH_PREFIXED_DBS:
            if f'_dbs()["{db}"]' in line and ".put(" in line and "be8(" not in line:
                bad.append(line.strip())
    check("every put into an epoch-prefixed DB keys by be8(epoch)", not bad, str(bad))


def t3_herd_locks():
    """One compute per generation for the three generation-keyed derived reads, with the in-write-txn
    bypass ahead of the lock (the latest_settled pattern)."""
    src = open(os.path.join(ROOT, "ops", "account_ops.py")).read()
    for fn, lock in (("def get_open_registry", "_open_reg_lock"), ("def get_bonded_registry", "_bonded_reg_lock")):
        seg = src[src.index(fn):src.index(fn) + 3000]
        check(f"{fn}: in_write_txn bypass before the lock", seg.index("in_write_txn()") < seg.index(lock))
        check(f"{fn}: double-checked", seg.count("entry[0] != key") >= 2)
    ssrc = open(os.path.join(ROOT, "ops", "snapshot_ops.py")).read()
    seg = ssrc[ssrc.index("def l1_state_root"):ssrc.index("def l1_state_root") + 3000]
    check("l1_state_root: in_write_txn bypass before the lock", seg.index("in_write_txn()") < seg.index("_root_lock"))
    check("l1_state_root: double-checked", seg.count("entry[0] == key") >= 2)

    from ops import account_ops as ao
    calls = [0]
    def slow_members(floor):
        calls[0] += 1
        time.sleep(0.2)
        return set()
    orig = (ao.kv_ops.recert_addresses_after, ao.kv_ops.env_path, ao.kv_ops.write_generation, ao.kv_ops.in_write_txn)
    ao.kv_ops.recert_addresses_after = slow_members
    ao.kv_ops.env_path = lambda *a, **k: "/tmp/x"
    ao.kv_ops.write_generation = lambda *a, **k: 7
    ao.kv_ops.in_write_txn = lambda *a, **k: False
    ao._open_reg_cache[0] = None
    try:
        res = []
        ts = [threading.Thread(target=lambda: res.append(ao.get_open_registry(100))) for _ in range(12)]
        t0 = time.time()
        [t.start() for t in ts]
        [t.join() for t in ts]
        el = time.time() - t0
        check("open registry herd resolves to ONE compute", calls[0] == 1, f"got {calls[0]}")
        check("all 12 callers got the result", len(res) == 12 and all(r == {} for r in res))
        check("12 threads cost ~one compute", el < 1.0, f"{el:.2f}s")
    finally:
        (ao.kv_ops.recert_addresses_after, ao.kv_ops.env_path, ao.kv_ops.write_generation, ao.kv_ops.in_write_txn) = orig
        ao._open_reg_cache[0] = None


if __name__ == "__main__":
    for name in ("t1_fast_walk_equals_slow_path", "t2_epoch_prefixed_writers_use_be8", "t3_herd_locks"):
        try:
            globals()[name]()
        except Exception as e:  # noqa
            import traceback; traceback.print_exc()
            _fails.append(name)
    print("ALL PASS" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    raise SystemExit(1 if _fails else 0)
