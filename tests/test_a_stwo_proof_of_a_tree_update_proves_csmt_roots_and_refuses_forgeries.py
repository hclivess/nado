"""A Stwo proof of a compressed-tree update proves csmt.py's roots, and its verifier refuses forged statements.

native/stwo_settle (Goldilocks retirement G4, prototype v0) proves ONE key update of the gen-29 exec tree: the old
leaf to the old root and the new leaf to the new root over the same siblings, on upstream's BLAKE2s AIR plus our path
component. Driven with REAL updates from execnode/csmt.Tree — depth 0 (a one-key tree), a shallow and a deep path in a
large tree, and a key sharing a long prefix (a deep path) — each case checks:
  1. the roots the proof states equal csmt.py's root before and after the update;
  2. the honest proof verifies;
  3. six forged statements against an honest proof are refused (new root, old root, key, new value hash, old value
     hash, swapped roots).
Also prints the prove/verify time and proof size per depth.

Needs the nightly toolchain to build the crate; skips with the reason when it is not installed.
Run: python3 tests/test_a_stwo_proof_of_a_tree_update_proves_csmt_roots_and_refuses_forgeries.py
"""
import _harness
HOME = _harness.isolate("nado-test-stwo-tree-update-")
import os
import random
import shutil
import subprocess

from execnode import csmt as C

T = _harness.Report()
CRATE = os.path.join(_harness.ROOT, "native", "stwo_settle")
TARGET = os.path.join(os.path.expanduser("~"), ".cache", "nado-stwo-settle-target")


def build():
    cargo = shutil.which("cargo") or os.path.expanduser("~/.cargo/bin/cargo")
    if not os.path.exists(cargo):
        return None
    r = subprocess.run([cargo, "+nightly-2026-01-15", "build", "--release", "--bin", "settle_update"], cwd=CRATE,
                       capture_output=True, text=True, timeout=1800, env=dict(os.environ, CARGO_TARGET_DIR=TARGET))
    if r.returncode != 0:
        print(r.stderr[-1500:])
        return None
    return os.path.join(TARGET, "release", "settle_update")


rnd = random.Random(11)


def case(items, key, new_value):
    t = C.Tree(items)
    sibs, term = t.prove(key)
    old = t.root()
    t.set(key, new_value)
    line = f"{key.hex()} {C.value_hash(items[key]).hex()} {C.value_hash(new_value).hex()} {','.join(s.hex() for s in sibs)}"
    return line, old.hex(), t.root().hex(), len(sibs)


cases = []
one = {rnd.randbytes(32): b"v"}
cases.append(("one-key tree", *case(one, next(iter(one)), b"w")))
big = {rnd.randbytes(32): rnd.randbytes(32) for _ in range(300)}
k = next(iter(big))
cases.append(("300-key tree", *case(big, k, b"changed")))
pre = bytearray(rnd.randbytes(32))
deep = dict(big)
for i in range(3):                                  # three keys sharing a 30-bit prefix: a long path
    kk = bytearray(rnd.randbytes(32))
    kk[:3] = pre[:3]
    kk[3] = (pre[3] & 0xC0) | (kk[3] & 0x3F)
    deep[bytes(kk)] = rnd.randbytes(8)
deep_key = max((x for x in deep if x[:3] == bytes(pre[:3])), key=lambda x: len(C.Tree(deep).prove(x)[0]))
cases.append(("deep path (shared prefix)", *case(deep, deep_key, b"deep change")))

binp = build()
if binp is None:
    print("SKIP  no nightly-2026-01-15 toolchain (or the crate did not build): the Stwo prover cannot be run here")
else:
    for name, line, want_old, want_new, depth in cases:
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
        T.check(f"1. {name} (depth {depth}): the proof's roots are csmt.py's before and after the update",
                roots == [want_old, want_new], (roots, want_old[:16], want_new[:16], r.stderr[-300:]))
        T.check(f"2. {name}: the honest proof verifies", out.get("HONEST") == ["ok"], out.get("HONEST"))
        T.check(f"3. {name}: all six forged statements are refused",
                len(forged) == 6 and set(forged.values()) == {"refused"}, forged)
        print(f"      {name}: depth {depth}, {' '.join(out.get('TIME', []))}")
T.done("ALL PASS — a Stwo proof of a tree update proves csmt.py's roots and refuses forgeries")
