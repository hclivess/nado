"""The wallet's Stwo note algebra (static/stark/stwo_js.js) is the node's (execnode/shielded_stwo.py), byte for byte.

A wallet that hashes a note differently from the exec layer builds commitments nobody can find, paths to roots the pool
never had, and nullifiers that do not match the proof — every one of them a lost or unspendable note, and nothing fails
until a user's spend does. Pins, on vectors evaluated by BOTH implementations:
  1. BLAKE2s-256 (the JS port of RFC 7693) == hashlib.blake2s on the RFC's "abc" vector and on lengths around the
     64-byte block edges;
  2. owner, cm (u64 extremes included), nf, node, the empty root, the depth-48 root of 0..13 leaves, and the
     (siblings, dirs) path of several positions — whose recomputation reaches the same root;
  3. aux_of(dest) — the destination binding — for "", a real address and non-ASCII bytes;
  4. the JS refuses what the Python refuses: a value above 2^64 - 1, a digest that is not 32 bytes.

Run: python3 tests/test_stwo_wallet_note_algebra_matches_the_node.py
"""
import os, sys, tempfile, json, subprocess, hashlib, struct
_T = tempfile.mkdtemp(prefix="nado-test-stwo-wallet-algebra-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, _T, ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from execnode import shielded_stwo as SP

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


if not shutil.which("node"):
    print("SKIP  no node"); sys.exit(0)

w = lambda *x: struct.pack("<8I", *x).hex()
NSKS = [w(0x12345678, 0x9ABCDEF0, 0x0F0F0F0F, 0xDEADBEEF, 0x0BADF00D, 0x77777777, 0x2468ACE0, 0x13579BDF),
        "00" * 32, "ff" * 32, hashlib.blake2b(b"nsk", digest_size=32).hexdigest()]
VALS = [(1, 0), (5000, 0x5EED5EED5EED), ((1 << 64) - 1, (1 << 64) - 1), (0x0123456789ABCDEF & ((1 << 61) - 1), 7)]
LEAVES = [SP.commit(i * 3 + 1, SP.owner_of(NSKS[0]), i) for i in range(13)]
BLAKE_INPUTS = [b"", b"abc", b"\x00", bytes(range(63)), bytes(range(64)), bytes(range(65)), bytes(range(128)),
                bytes(range(129)), bytes(200)]
DESTS = ["", "nado1example-not-an-address", "ünïcödé ✓", "a" * 300]

case = {"nsks": NSKS, "vals": [[str(v), str(r)] for v, r in VALS], "leaves": LEAVES,
        "blake": [b.hex() for b in BLAKE_INPUTS], "dests": DESTS}
probe = r"""
import * as S from %s;
const c = JSON.parse(process.argv[1]);
const out = {blake: c.blake.map((h) => S.toHex(S.blake2s(S.fromHex(h))))};
out.owner = c.nsks.map((k) => S.ownerOf(k));
out.cm = []; out.nf = [];
for (const k of c.nsks) for (const [v, r] of c.vals) { out.cm.push(S.commit(BigInt(v), S.ownerOf(k), BigInt(r))); out.nf.push(S.nullifier(k, BigInt(r))); }
out.node = [S.node(c.leaves[0], c.leaves[1]), S.node(S.EMPTY_LEAF, c.leaves[2])];
out.empty = S.emptyRoot();
out.roots = []; for (let n = 0; n <= c.leaves.length; n++) out.roots.push(S.treeRoot(c.leaves.slice(0, n)));
out.paths = [0, 1, 6, 10, 12].map((p) => S.treePath(c.leaves, p));
out.aux = c.dests.map((d) => S.auxOf(d));
const refuses = (f) => { try { f(); return false; } catch (e) { return true; } };
out.refuse = [refuses(() => S.commit(1n << 64n, S.ownerOf(c.nsks[0]), 0n)), refuses(() => S.commit(-1n, S.ownerOf(c.nsks[0]), 0n)),
              refuses(() => S.ownerOf("00".repeat(31))), refuses(() => S.node("zz".repeat(32), c.leaves[0]))];
console.log(JSON.stringify(out));
""" % json.dumps("file://" + os.path.join(ROOT, "static", "stark", "stwo_js.js"))
r = subprocess.run(["node", "--input-type=module", "-e", probe, json.dumps(case)], capture_output=True, text=True,
                   timeout=300)
if r.returncode != 0:
    print("FAIL  the JS module runs in Node", r.stderr[-1500:]); sys.exit(1)
js = json.loads(r.stdout)

check("1. BLAKE2s-256('abc') is RFC 7693 Appendix B's vector",
      js["blake"][1] == "508c5e8c327c14e2e1a72ba34eeb452f37458b209ed63a294d999b4c86675982", js["blake"][1])
check("...and the JS BLAKE2s == hashlib.blake2s around every block edge",
      js["blake"] == [hashlib.blake2s(b).hexdigest() for b in BLAKE_INPUTS])
check("2. owner = H(21, nsk) matches the node for every spend key", js["owner"] == [SP.owner_of(k) for k in NSKS])
check("...cm matches (u64 extremes included)",
      js["cm"] == [SP.commit(v, SP.owner_of(k), r) for k in NSKS for v, r in VALS])
check("...nf matches", js["nf"] == [SP.nullifier(k, r) for k in NSKS for _v, r in VALS])
check("...node matches", js["node"] == [SP.node(LEAVES[0], LEAVES[1]), SP.node(SP.EMPTY_LEAF, LEAVES[2])])
check("...the empty depth-48 root matches", js["empty"] == SP.EMPTY_ROOT)
check("...the depth-48 root of 0..13 leaves matches at every size",
      js["roots"] == [SP.tree_root(LEAVES[:n]) for n in range(len(LEAVES) + 1)])
ok_paths = True
for p, got in zip([0, 1, 6, 10, 12], js["paths"]):
    sibs, dirs = SP.tree_path(LEAVES, p)
    cur = LEAVES[p]
    for s, d in zip(sibs, dirs):
        cur = SP.node(s, cur) if d else SP.node(cur, s)
    ok_paths &= got["sibs"] == sibs and got["dirs"] == dirs and got["root"] == cur == SP.tree_root(LEAVES)
check("...every path (siblings, dirs) matches and recomputes to the pool's root", ok_paths)
check("3. aux_of(dest) == BLAKE2s-256(b'NADO/stwo-js/aux/v1\\0' || dest UTF-8)",
      js["aux"] == [hashlib.blake2s(b"NADO/stwo-js/aux/v1\x00" + d.encode()).hexdigest() for d in DESTS])
check("4. the JS refuses a value above 2^64 - 1 or below 0, and a digest that is not 32 bytes", all(js["refuse"]),
      js["refuse"])

print("ALL PASS — the wallet's Stwo note algebra is the node's" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
