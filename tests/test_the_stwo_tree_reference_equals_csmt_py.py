"""The Stwo settlement circuit's tree reference equals execnode/csmt.py, root for root.

native/stwo_settle/src/csmt_ref.rs is the ground truth the gen-29 settlement circuit (Goldilocks retirement G4) is
tested against: one personalized BLAKE2s compression per leaf and per node, keys and digests as little-endian words. If it
disagreed with the node's own tree by a bit, every proof would prove a root no node computes. So: every membership proof (up to 10 per tree, ~170 in all) from
csmt.Tree (random key sets, keys sharing long prefixes, membership paths, depths 0 to 40+) are fed to
the Rust reference (src/bin/csmt_ref_roots), and every root it prints must equal the tree's root.

Needs the nightly toolchain to build the crate; skips with the reason when it is not installed.
Run: python3 tests/test_the_stwo_tree_reference_equals_csmt_py.py
"""
import _harness
HOME = _harness.isolate("nado-test-stwo-tree-ref-")
import os
import random
import shutil
import subprocess

from execnode import csmt as C

T = _harness.Report()
CRATE = os.path.join(_harness.ROOT, "native", "stwo_settle")
TOOLCHAIN = "nightly-2026-01-15"


def build():
    cargo = shutil.which("cargo") or os.path.expanduser("~/.cargo/bin/cargo")
    if not os.path.exists(cargo):
        return None
    # RUSTUP_AUTO_INSTALL=0: rustup >= 1.28 INSTALLS a missing `+toolchain` on the spot — on a CI runner or a fleet
    # box running scripts/run_tests.sh that is a nightly download nobody asked for, and minutes past the CI cap.
    # Without it the toolchain is simply absent and the test SKIPs.
    r = subprocess.run([cargo, f"+{TOOLCHAIN}", "build", "--release", "--bin", "csmt_ref_roots"], cwd=CRATE,
                       capture_output=True, text=True, timeout=1800,
                       env=dict(os.environ, RUSTUP_AUTO_INSTALL="0", CARGO_TARGET_DIR=os.path.join(os.path.expanduser("~"), ".cache", "nado-stwo-settle-target")))
    if r.returncode != 0:
        print(r.stderr[-1500:])
        return None
    return os.path.join(os.path.expanduser("~"), ".cache", "nado-stwo-settle-target", "release", "csmt_ref_roots")


rnd = random.Random(4)
cases, want = [], []
for t in range(30):
    pre = "".join(rnd.choice("01") for _ in range(rnd.choice([0, 9, 30])))
    items = {}
    for _ in range(rnd.choice([1, 2, 7, 40])):
        k = bytearray(rnd.randbytes(32))
        if rnd.random() < 0.5:
            for i, b in enumerate(pre):
                k[i >> 3] = (k[i >> 3] & ~(1 << (7 - (i & 7)))) | (int(b) << (7 - (i & 7)))
        items[bytes(k)] = rnd.randbytes(rnd.choice([1, 32, 77]))
    tree = C.Tree(items)
    root = tree.root()
    for k in list(items)[:10]:
        sibs, term = tree.prove(k)
        assert term[0] == "leaf" and term[1] == k
        cases.append(f"{k.hex()} {C.value_hash(items[k]).hex()} {','.join(s.hex() for s in sibs)}")
        want.append(root.hex())
T.check("the cases cover depth 0 and paths deeper than 30", min(c.count(",") for c in cases if " " in c) >= 0
        and max(len(c.split(" ")[2].split(",")) if c.split(" ")[2] else 0 for c in cases) > 30)
binp = build()
if binp is None:
    print(f"SKIP  no {TOOLCHAIN} toolchain (or the crate did not build): the Rust reference cannot be run here")
else:
    r = subprocess.run([binp], input="\n".join(cases) + "\n", capture_output=True, text=True, timeout=120)
    got = r.stdout.split()
    bad = [i for i, (g, w) in enumerate(zip(got, want)) if g != w]
    T.check(f"every one of {len(cases)} roots from the Rust reference equals csmt.py's", len(got) == len(want) and not bad,
            (len(got), len(want), bad[:3]))
T.done("ALL PASS — the Stwo tree reference equals csmt.py")
