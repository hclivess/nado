"""EPOCHW ROOT WINDOW + ACCUMULATOR (gen 24+, protocol.EPOCHW_ROOT_WINDOWED).

Until gen 24 every `epochw:<E>` row (~18 KB, one per epoch, forever) is hashed into every block's state root —
the last root family whose per-block cost grew with chain age. From gen 24 those rows are windowed like the
other epoch families, and a 32-byte `epochwacc:<E>` = blake2b(acc[E-1] || epochw[E]) row written at the
same boundary keeps the whole history root-bound. Pins: gen-23 behaviour untouched (rule off), the chain
is written/reverted symmetrically, the root walk equals the slow path with the rule on, rows below the
floor leave the root, the newest accumulator stays, and the accumulator equals a recomputation over the rows
(so a rewritten old epoch is detectable). Also pins kv_ops.bonded_map == the json-decoding scan."""
import hashlib
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def _fresh():
    d = tempfile.mkdtemp(prefix="nado-epochw-")
    os.environ["HOME"] = d
    from ops import kv_ops
    kv_ops.close_all()
    kv_ops.init_env()
    return kv_ops


def t1_rule_off_is_byte_identical():
    import protocol
    from ops import snapshot_ops as so
    check("gen 23: EPOCHW_ROOT_WINDOWED is False", protocol.EPOCHW_ROOT_WINDOWED is False or protocol.CHAIN_GENERATION >= 24)
    if not protocol.EPOCHW_ROOT_WINDOWED:
        check("gen 23: window prefixes unchanged", so.ROOT_WINDOWED_META_PREFIXES == (b"att:", b"divnull:", b"settle:"))
        kv = _fresh()
        kv.epoch_weights_commit(5, {"a": 1})
        check("gen 23: no accumulator row written", kv.epoch_weights_acc(5) is None)
        kv.close_all()


def t2_accumulator_chain_and_window():
    import protocol
    from ops import snapshot_ops as so
    kv = _fresh()
    orig_flag, orig_pfx = protocol.EPOCHW_ROOT_WINDOWED, so.ROOT_WINDOWED_META_PREFIXES
    protocol.EPOCHW_ROOT_WINDOWED = True
    so.ROOT_WINDOWED_META_PREFIXES = (b"att:", b"divnull:", b"settle:", b"epochw:", b"epochwacc:")
    try:
        W = so.ROOT_RETENTION_EPOCHS
        top = W + 10
        acc = b""
        for e in range(top + 1):
            kv.epoch_weights_commit(e, {"addr%d" % e: e + 1})
            blob = kv._read(lambda txn: txn.get(b"epochw:%d" % e, db=kv._dbs()["meta"]))
            acc = hashlib.blake2b(acc + blob, digest_size=32).digest()
            if e in (0, 1, top):
                check(f"acc[{e}] chained from acc[{e-1}] and the blob", kv.epoch_weights_acc(e) == acc)
        slow = so._root_triples(so.read_state())
        fast = so.read_root_state()
        check("rule on: root walk == slow path", slow == fast)
        check("rule on: roots equal", so.merkle_root(slow) == so.l1_state_root())
        keys = {k for n, k, v in fast if n == "meta"}
        floor = top - W
        check("epochw below the floor leaves the root", b"epochw:%d" % (floor - 1) not in keys and b"epochw:0" not in keys)
        check("epochw at/after the floor stays", b"epochw:%d" % floor in keys and b"epochw:%d" % top in keys)
        check("accumulator windowed the same way", b"epochwacc:%d" % (floor - 1) not in keys and b"epochwacc:%d" % top in keys)
        check("rows below the floor still in the DB (readers untouched)", kv.epoch_weights_get(0) == {"addr0": 1})
        # revert symmetry: reverting the top epoch deletes both rows and restores the previous root
        r_before = so.l1_state_root()
        kv.epoch_weights_commit(top + 1, {"x": 1}); r_mid = so.l1_state_root()
        kv.epoch_weights_commit(top + 1, revert=True)
        check("revert deletes epochw + acc", kv.epoch_weights_get(top + 1) is None and kv.epoch_weights_acc(top + 1) is None)
        check("revert restores the root exactly", so.l1_state_root() == r_before and r_mid != r_before)
        # tamper detection: rewriting an old (out-of-window) epoch's weights no longer moves the root,
        # but the committed accumulator no longer matches a recomputation over the rows.
        def recompute(upto):
            a = b""
            for e in range(upto + 1):
                a = hashlib.blake2b(a + kv._read(lambda txn, e=e: txn.get(b"epochw:%d" % e, db=kv._dbs()["meta"])), digest_size=32).digest()
            return a
        check("accumulator == recomputation over the rows", recompute(top) == kv.epoch_weights_acc(top))
        kv._write(lambda txn: txn.put(b"epochw:0", b'{"addr0":999}', db=kv._dbs()["meta"]))
        check("tampered out-of-window epoch is detectable", recompute(top) != kv.epoch_weights_acc(top))
    finally:
        protocol.EPOCHW_ROOT_WINDOWED, so.ROOT_WINDOWED_META_PREFIXES = orig_flag, orig_pfx
        kv.close_all()


def t3_bonded_map_matches_scan():
    kv = _fresh()
    from protocol import B_MIN
    big = 10 ** 30
    kv.account_set("a" * 46, "bonded", B_MIN)
    kv.account_set("b" * 46, "bonded", B_MIN - 1)
    kv.account_set("c" * 46, "balance", 5)                  # bonded absent -> defaults 0
    kv.account_set("d" * 46, "bonded", big)
    kv.account_set_field("e" * 46, "public_key", '"bonded":123')   # a string that LOOKS like the field, after the real one
    kv.account_set("e" * 46, "bonded", B_MIN + 7)
    kv._write(lambda txn: txn.put(b"f" * 46, b'{"balance":1}', db=kv._dbs()["accounts"]))   # legacy doc, no bonded field
    fast = kv.bonded_map(B_MIN)
    slow = {a: doc.get("bonded", 0) for a, doc in kv.iter_accounts() if doc.get("bonded", 0) >= B_MIN}
    check("bonded_map == json scan (threshold, absent, huge int, decoy string, legacy doc)", fast == slow, f"{fast} vs {slow}")
    check("huge int exact", fast.get("d" * 46) == big)
    kv.close_all()


if __name__ == "__main__":
    for name in ("t1_rule_off_is_byte_identical", "t2_accumulator_chain_and_window", "t3_bonded_map_matches_scan"):
        try:
            globals()[name]()
        except Exception:
            import traceback; traceback.print_exc(); _fails.append(name)
    print("ALL PASS" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    raise SystemExit(1 if _fails else 0)
