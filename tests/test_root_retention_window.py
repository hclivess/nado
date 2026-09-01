"""ROOT RETENTION WINDOW (2026-08-20): the state root commits only the last ROOT_RETENTION_EPOCHS
epochs of the epoch-growing row families — a pure function of the triples (reference = max
committed epochw row), rollback-symmetric by construction, NOTHING deleted. Pins: key parsers on
the real formats, byte-identical output below the threshold, correct exclusion above it, never
excluding epochw/divinflow/accounts/unparseable keys, and the inverse property."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("NADO_HOME", "/tmp/nado-rootwindow-test-home")
from ops import snapshot_ops as so
from protocol import EPOCH_LENGTH

W = so.ROOT_RETENTION_EPOCHS
ADDR = "078d0ff642dfaac2d15b28dc83cff1082581616fe004e3"


def _be8(n): return n.to_bytes(8, "big")


def _state(max_epoch, extra=()):
    """synthetic consensus state with every windowed family populated for epochs 0..max_epoch,
    plus epochw/divinflow per epoch and a few permanent rows."""
    t = []
    for e in range(max_epoch + 1):
        t.append(("meta", f"epochw:{e}".encode(), b"{}"))
        t.append(("meta", f"divinflow:{e}".encode(), b"1"))
        t.append(("commits", f"{ADDR}|{e}".encode(), b"c"))
        t.append(("reveals", _be8(e), b"r"))
        t.append(("attestations", _be8(e), f"{ADDR}|x".encode()))
        t.append(("recert_by_epoch", _be8(e), ADDR.encode()))
        t.append(("settlements", b"default\x00" + _be8(e * EPOCH_LENGTH), f"{ADDR}|root".encode()))
        t.append(("meta", f"att:{ADDR}:{e}".encode(), b"1"))
        t.append(("meta", f"divnull:{ADDR}:{e}".encode(), b"1"))
        t.append(("meta", f"settle:default:{ADDR}:{e * EPOCH_LENGTH}".encode(), b"1"))
    t.append(("accounts", ADDR.encode(), b'{"balance":1}'))
    t.append(("totals", b"totals", b"{}"))
    t.extend(extra)
    return sorted(t, key=lambda x: (x[0], x[1], x[2]))


def t1_parsers_on_real_formats():
    assert so._row_epoch("commits", f"{ADDR}|17".encode()) == 17
    assert so._row_epoch("reveals", _be8(9)) == 9
    assert so._row_epoch("attestations", _be8(16)) == 16
    assert so._row_epoch("recert_by_epoch", _be8(10)) == 10
    assert so._row_epoch("settlements", b"default\x00" + _be8(900)) == 900 // EPOCH_LENGTH
    assert so._row_epoch("meta", f"att:{ADDR}:12".encode()) == 12
    assert so._row_epoch("meta", f"divnull:{ADDR}:20".encode()) == 20
    assert so._row_epoch("meta", f"settle:default:{ADDR}:300".encode()) == 300 // EPOCH_LENGTH
    # epochw parses to its epoch, but it is WINDOWED only from gen 24 (protocol.EPOCHW_ROOT_WINDOWED): on
    # gen 23 the prefix is absent from ROOT_WINDOWED_META_PREFIXES, so the root never consults the parser.
    from protocol import EPOCHW_ROOT_WINDOWED
    assert so._row_epoch("meta", b"epochw:5") == 5
    assert (b"epochw:" in so.ROOT_WINDOWED_META_PREFIXES) == EPOCHW_ROOT_WINDOWED, "epochw window follows the gen-24 rule"
    assert so._row_epoch("accounts", ADDR.encode()) is None
    assert so._row_epoch("commits", b"garbage-no-separator") is None, "unparseable -> None -> kept"


def t2_identical_below_threshold():
    s = _state(W - 1)
    out = so._root_triples(s)
    base = [t for t in s if t[0] not in so.ROOT_EXCLUDED_DBS]
    assert out == base, "until the reference epoch reaches the window, the root must be UNCHANGED"


def t3_window_excludes_only_old_windowed_rows():
    ref = W + 25
    s = _state(ref, extra=[("commits", b"garbage-no-separator", b"?")])
    out = so._root_triples(s)
    floor = ref - W
    for name, key, _ in out:
        e = so._row_epoch(name, key)
        windowed = name in so.ROOT_WINDOWED_DBS or (name == "meta" and key.startswith(so.ROOT_WINDOWED_META_PREFIXES))
        if windowed and e is not None:
            assert e >= floor, f"{name} {key!r} epoch {e} < floor {floor} must be excluded"
    kept = {(n, k) for n, k, _ in out}
    assert ("meta", f"epochw:0".encode()) in kept and ("meta", b"divinflow:0") in kept, \
        "epochw/divinflow are permanent root members"
    assert ("accounts", ADDR.encode()) in kept and ("totals", b"totals") in kept
    assert ("commits", b"garbage-no-separator") in kept, "unparseable keys are never excluded"
    assert ("commits", f"{ADDR}|{floor - 1}".encode()) not in kept
    assert ("commits", f"{ADDR}|{floor}".encode()) in kept, "floor itself is retained (>=)"
    assert ("settlements", b"default\x00" + _be8((floor - 1) * EPOCH_LENGTH)) not in kept
    assert ("meta", f"att:{ADDR}:{floor - 1}".encode()) not in kept


def t4_rollback_symmetry():
    """Reverting the newest boundary block deletes epochw:<ref>; the window must slide back by exactly
    one epoch and re-admit the edge rows — the same function on the reduced state, no journal."""
    ref = W + 10
    full = _state(ref)
    reduced = [t for t in full if t != ("meta", f"epochw:{ref}".encode(), b"{}")]
    out_full = {(n, k) for n, k, _ in so._root_triples(full)}
    out_red = {(n, k) for n, k, _ in so._root_triples(reduced)}
    edge = ("commits", f"{ADDR}|{ref - W - 1}".encode())   # just below the full window's floor
    assert edge not in out_full and edge in out_red, "rolling back one boundary re-admits the edge epoch"
    assert so.merkle_root(so._root_triples(full)) != so.merkle_root(so._root_triples(reduced))


def t5_root_changes_exactly_when_window_engages():
    a = so.merkle_root(so._root_triples(_state(W - 1)))
    b = so.merkle_root(so._root_triples(_state(W)))     # ref == W -> floor 0 -> still nothing excluded
    c = so.merkle_root(so._root_triples(_state(W + 1))) # floor 1 -> epoch-0 windowed rows leave
    assert a != b != c
    out_w = {(n, k) for n, k, _ in so._root_triples(_state(W))}
    assert ("commits", f"{ADDR}|0".encode()) in out_w, "at ref == W the floor is 0: nothing excluded yet"
    out_w1 = {(n, k) for n, k, _ in so._root_triples(_state(W + 1))}
    assert ("commits", f"{ADDR}|0".encode()) not in out_w1, "first exclusion at ref == W + 1"


if __name__ == "__main__":
    fails = 0
    for name in sorted(k for k in globals() if k.startswith("t") and k[1].isdigit()):
        try:
            globals()[name]()
            print(f"PASS  {name}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL  {name}: {e}")
    print("ALL PASS" if not fails else f"{fails} FAILURE(S)")
    raise SystemExit(1 if fails else 0)
