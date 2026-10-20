"""A Stwo proof of compressed-tree writes proves csmt.py's roots, and its verifier refuses forged statements.

native/stwo_settle (Goldilocks retirement G4) proves a SEQUENTIAL BATCH of writes to the gen-29 exec tree — value
updates, inserts and deletes, including the two that change the tree's shape (an insert splitting a neighbour's leaf,
a delete collapsing one upward) — on upstream's BLAKE2s AIR plus our path component (native/stwo_settle/src/blake/
path.rs has the soundness argument). Every write comes from a REAL execnode/csmt.Tree, classified the way the tree
itself sees it, and the expected roots are the tree's own. Cases: one update; one batch on a 300-key tree with a
shared-prefix cluster that holds all five op kinds (updates, inserts into an EMPTY child and splitting a leaf, deletes
leaving an EMPTY and collapsing a long chain); and the edges: the empty tree gaining a first and a second key and
losing both again (every op at depth 0). Each case checks:
  1. the roots the proof states equal csmt.py's root before the first write and after the last;
  2. the honest proof verifies;
  3. every forged statement against the honest proof is refused: each field (new root, old root, key, new and old value
     hash, swapped roots) of the first and the last write; for a split, the neighbour key and the split depth; for a
     batch, a consistent chain through a wrong intermediate root, a value moved between writes, a dropped write and
     two writes reordered.
  4. a DISHONEST PROVER is refused: a witness that breaks exactly one shape rule while every hash chain stays consistent
     (native/stwo_settle settle::Tamper, and two crafted from the tree): the new tree's top sibling differs from the
     old one's, a split's EMPTY sibling is not empty, a split's sibling is not the neighbour's leaf, an EMPTY start is
     not zero, a delete opens a LEAF sibling as an internal node, a collapse stops beside an EMPTY. Each would prove a
     root that is not the canonical tree's.
Also prints the prove/verify time and proof size.

Needs the nightly toolchain to build the crate; skips with the reason when it is not installed.
Run: python3 tests/test_a_stwo_proof_of_a_tree_update_proves_csmt_roots_and_refuses_forgeries.py
"""
import os
_REAL_HOME = os.path.expanduser("~")      # BEFORE isolate: the toolchain lives under the real HOME
import _harness
HOME = _harness.isolate("nado-test-stwo-tree-update-")
import random
import subprocess

from execnode import csmt as C
from tests._stwo_settle_build import NIGHTLY, build

T = _harness.Report()


def pfx(key, d):
    return int.from_bytes(key, "big") >> (256 - d) if d else 0


def under(t, d, p):
    return [x for x in t._sorted if pfx(x, d) == p]


def opening(t, key, d):
    """the two children of the internal sibling at depth d (sibs[d-1])"""
    sp = pfx(key, d) ^ 1
    ks = under(t, d, sp)
    l = t._node(d + 1, sp << 1, [x for x in ks if not C.bit(x, d)])
    r = t._node(d + 1, (sp << 1) | 1, [x for x in ks if C.bit(x, d)])
    return l, r


def first_diff(a, b):
    return next(i for i in range(256) if C.bit(a, i) != C.bit(b, i))


def write(t, key, nv):
    """the settle_update line for setting key to nv (None: delete) on tree t, classified as csmt sees it; applies it"""
    vh = lambda v: C.value_hash(v).hex()
    sibs, term = t.prove(key)
    d = len(sibs)
    sl = lambda ss: ",".join(s.hex() for s in ss) or "-"
    if nv is not None and key in t._kv:
        op, line = "U", f"U {key.hex()} {vh(t._kv[key])} {vh(nv)} {sl(sibs)} -"
    elif nv is not None and term[0] == "empty":
        extra = "-"
        if d:
            l, r = opening(t, key, d)
            assert C.node_hash(l, r) == sibs[d - 1]
            extra = f"{l.hex()},{r.hex()}"
        op, line = "IE", f"IE {key.hex()} - {vh(nv)} {sl(sibs)} {extra}"
    elif nv is not None:
        k2, v2 = term[1], term[2]
        op, line = "IS", f"IS {key.hex()} - {vh(nv)} {sl(sibs)} {k2.hex()},{vh(v2)},{first_diff(key, k2) + 1}"
    else:
        assert term[0] == "leaf" and term[1] == key
        sk = under(t, d, pfx(key, d) ^ 1) if d else []
        if len(sk) == 1:
            k2 = sk[0]
            da = d - 1
            while da > 0 and sibs[da - 1] == C.EMPTY:
                da -= 1
            op, line = "DC", f"DC {key.hex()} {vh(t._kv[key])} - {sl(sibs[:da])} {k2.hex()},{vh(t._kv[k2])},{d}"
        else:
            extra = "-"
            if d:
                l, r = opening(t, key, d)
                assert C.node_hash(l, r) == sibs[d - 1]
                extra = f"{l.hex()},{r.hex()}"
            op, line = "DE", f"DE {key.hex()} {vh(t._kv[key])} - {sl(sibs)} {extra}"
    if nv is None:
        t.delete(key)
    else:
        t.set(key, nv)
    return op, line


def case(items, steps):
    t = C.Tree(dict(items))
    old = t.root().hex()
    ops, lines = [], []
    for key, nv in steps:
        op, line = write(t, key, nv)
        ops.append(op)
        lines.append(line)
    return "\n".join(lines), old, t.root().hex(), ops


rnd = random.Random(11)
cases = []
big = {rnd.randbytes(32): rnd.randbytes(32) for _ in range(300)}
k0 = next(iter(big))
cases.append(("one update", *case(big, [(k0, b"changed")])))

pre = rnd.randbytes(4)
cluster = []
for i in range(4):                                  # four keys sharing a 26-bit prefix: a chain of EMPTY siblings
    kk = bytearray(rnd.randbytes(32))
    kk[:3] = pre[:3]
    kk[3] = (pre[3] & 0xC0) | (kk[3] & 0x3F)
    cluster.append(bytes(kk))
deep = dict(big)
deep.update({x: rnd.randbytes(8) for x in cluster})
ks = list(big)
into_chain = bytearray(cluster[0])
into_chain[1] ^= 0x10                               # leaves the cluster's prefix at bit 11: lands in an EMPTY child
mixed = [
    (ks[5], b"a"),                                  # update
    (rnd.randbytes(32), b"new leaf"),               # insert: a random key ends at a leaf -> split
    (bytes(into_chain), b"into an empty child"),    # insert into an EMPTY child of the cluster's chain
    (cluster[1], None),                             # deletes inside the cluster
    (cluster[2], None),
    (cluster[3], None),                             # ... the last leaves cluster[0] alone: a long collapse
    (ks[17], None),                                 # delete a random key
    (ks[5], b"a again"),
    (cluster[0], b"g"),
]
cases.append(("every op kind in one batch", *case(deep, mixed)))

a, b = rnd.randbytes(32), rnd.randbytes(32)
cases.append(("the empty tree and back (depth 0)", *case({}, [(a, b"first"), (b, b"second"), (a, None), (b, None)])))

for name, _line, _o, _n, ops in cases:
    print(f"      {name}: ops {' '.join(ops)}")
T.check("the batches hold all five op kinds", set(cases[1][4]) | set(cases[2][4]) == {"U", "IE", "IS", "DE", "DC"},
        (cases[1][4], cases[2][4]))
T.check("the edge case starts and ends at the empty tree", cases[2][2] == C.EMPTY.hex() == cases[2][3])

binp, build_log = build(_REAL_HOME, "settle_update")
T.check("the crate builds when its toolchain is present", binp is not None or not build_log, build_log)
if binp is None:
    print(f"SKIP  no {NIGHTLY} toolchain: the Stwo prover cannot be run here")
else:
    for name, line, want_old, want_new, ops in cases:
        r = subprocess.run([binp], input=line + "\n", capture_output=True, text=True, timeout=1800)
        out = {}
        forged = {}
        for l in r.stdout.splitlines():
            p = l.split()
            if p and p[0] == "FORGE":
                forged[p[1]] = p[2]
            elif p:
                out[p[0]] = p[1:]
        roots = out.get("ROOTS", ["", ""])
        T.check(f"1. {name}: the proof's roots are csmt.py's before and after",
                roots == [want_old, want_new], (roots, want_old[:16], want_new[:16], r.stderr[-400:]))
        T.check(f"2. {name}: the honest proof verifies", out.get("HONEST") == ["ok"], out.get("HONEST"))
        want = 12 + (2 if {"IS", "DC"} & set(ops) else 0) + (4 if len(ops) >= 2 else 0)
        T.check(f"3. {name}: all {want} forged statements are refused",
                len(forged) == want and set(forged.values()) == {"refused"}, forged)
        print(f"      {name}: {' '.join(out.get('TIME', []))}")

    # 4. dishonest provers, each breaking one rule; "refused" = the prover's own check or the verifier said no
    def dishonest(lines, tamper=None):
        env = dict(os.environ, SETTLE_TAMPER=tamper) if tamper else None
        r = subprocess.run([binp], input=lines + "\n", capture_output=True, text=True, timeout=1800, env=env)
        got = [l.split(None, 1)[1] for l in r.stdout.splitlines() if l.startswith("HONEST ")]
        return got[0] if got else "no output: " + r.stderr[-200:]

    # each tamper on ONE write, so no root chain exists to catch it: only the circuit (the prover's own consistency
    # check, the LogUp sum, or the STARK) may refuse — a refusal by Chain or Shape would prove nothing about the rule
    in_circuit = lambda v: v.startswith("prover_refused") or v == "Sum" or v.startswith("Stark")
    by_op = {}
    for line in cases[1][1].splitlines():
        p = line.split()
        if p[0] in ("IS", "DC") and "esib" not in by_op:
            da = 0 if p[4] == "-" else len(p[4].split(","))
            if int(p[5].split(",")[2]) - 1 > da:
                by_op["esib"] = line                # a split with EMPTY siblings between its two depths
        by_op.setdefault(p[0], line)
    for tamper, op, what in [("shared_sibling", "U", "the new tree's top sibling differs from the old tree's"),
                             ("empty_sibling", "esib", "a split's EMPTY sibling is not empty"),
                             ("split_link", "IS", "a split's sibling is not the neighbour's leaf"),
                             ("empty_start", "IE", "an EMPTY start is not 32 zero bytes")]:
        T.check(f"4. (control) the honest {op} write verifies on its own", dishonest(by_op[op]) == "ok")
        verdict = dishonest(by_op[op], tamper)
        T.check(f"4. a dishonest prover is refused IN-CIRCUIT: {what}", in_circuit(verdict), verdict)
    pair = dict(big)
    pair.update({cluster[0]: b"x", cluster[1]: b"y"})
    t = C.Tree(pair)
    sibs, term = t.prove(cluster[1])
    d = len(sibs)
    da = d - 1
    while da > 0 and sibs[da - 1] == C.EMPTY:
        da -= 1
    assert da + 1 < d and sibs[da] == C.EMPTY, (da, d)
    vh = lambda v: C.value_hash(v).hex()
    sl = lambda ss: ",".join(x.hex() for x in ss) or "-"
    honest = f"DC {cluster[1].hex()} {vh(b'y')} - {sl(sibs[:da])} {cluster[0].hex()},{vh(b'x')},{d}"
    early = f"DC {cluster[1].hex()} {vh(b'y')} - {sl(sibs[:da + 1])} {cluster[0].hex()},{vh(b'x')},{d}"
    as_empty = f"DE {cluster[1].hex()} {vh(b'y')} - {sl(sibs)} {'11' * 32},{'22' * 32}"
    T.check("4. (control) the honest collapse of the same delete verifies", dishonest(honest) == "ok", dishonest(honest))
    v = dishonest(early)
    T.check(f"4. a dishonest prover is refused IN-CIRCUIT: a collapse that stops beside an EMPTY (depth {da + 1}, not {da})",
            in_circuit(v), v)
    v = dishonest(as_empty)
    T.check("4. a dishonest prover is refused IN-CIRCUIT: a delete opens a LEAF sibling as an internal node",
            in_circuit(v), v)
T.done("ALL PASS — a Stwo proof of tree writes proves csmt.py's roots and refuses forgeries")
