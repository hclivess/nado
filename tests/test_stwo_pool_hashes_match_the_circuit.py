"""The Stwo pool hashes exactly as the Stwo circuit does (execnode/shielded_stwo.py vs the prototype's Rust reference).

A pool that hashes one bit differently from its circuit holds notes nobody can ever spend. Pins, against vectors the
prototype's reference functions printed (scratchpad stwo0/stwo_zk/examples/vectors.rs, Stwo rev 826591c6): owner,
commitment, nullifier and node digests, and the depth-48 root of three leaves; plus the pool's own invariants — the
incremental root equals a full recomputation, a path folds back to the root, a nullifier spends once, and roots
outside the anchor window are refused.

Run: python3 tests/test_stwo_pool_hashes_match_the_circuit.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-stwo-pool-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import struct
from execnode import shielded_stwo as SP

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


V = {"owner": "b7506b49b8cd0172cc8657df013494afac2b4ebf2a2f08469442a1f920ff19f2",
     "cm": "dc4a5784b71a6998e0ce4cb6ed9d86582ec979e58d5e41f62fb5be876bb72711",
     "nf": "5e6e79f1279d3ca360d7f3fef3181f7016009a567cb093d67da06eb64401b537",
     "node": "effce06f06de4abc429700cd2899a7ba0fb92e22d1caf023d4cdb11dc704bc67",
     "root3_d48": "92116da0139687877f793cd32b16f8429613fd64a819ea2c01d1f31cc4b15340",
     "leaf0": "d22f7c6cba250f02f68887546517395a39bd8560df8a5ea401260e3843b049d1",
     "leaf1": "ee8047490f6204ca70f3ed422c4b8aa6970257a8a9ba81e922bbd8727af0e6cc"}
nsk = struct.pack("<8I", 1, 2, 3, 4, 5, 6, 7, 0xDEADBEEF).hex()
o = SP.owner_of(nsk)
check("owner = H(21, nsk) matches the circuit", o == V["owner"], o)
cm = SP.commit(1000, o, 0x1111)
check("cm = H(22, v, owner, rho) matches the circuit", cm == V["cm"], cm)
check("nf = H(23, nsk, rho) matches the circuit", SP.nullifier(nsk, 0x1111) == V["nf"])
check("node = H(left, right) matches the circuit", SP.node(o, cm) == V["node"])
leaves = [SP.commit(5, o, 1), SP.commit(6, o, 2), cm]
check("leaf commitments match", leaves[:2] == [V["leaf0"], V["leaf1"]])
check("the depth-48 root of three leaves matches the circuit's", SP.tree_root(leaves) == V["root3_d48"], SP.tree_root(leaves))

pool = SP.StwoShieldedPool()
check("an empty pool has the empty depth-48 root", pool.root() == SP.EMPTY_ROOT)
for x in leaves:
    pool.append(x)
check("the incremental root equals the full recomputation", pool.root() == V["root3_d48"])
sibs, dirs = SP.tree_path(leaves, 2)
cur = leaves[2]
for s, d in zip(sibs, dirs):
    cur = SP.node(s, cur) if d else SP.node(cur, s)
check("a path folds back to the root", cur == pool.root())
pool.spend(V["nf"])
try:
    pool.spend(V["nf"]); twice = True
except ValueError:
    twice = False
check("a nullifier spends once", not twice and pool.has_nullifier(V["nf"]))
old = pool.root()
for i in range(SP.ANCHOR_WINDOW):
    pool.append(SP.commit(i, o, 100 + i))
check("a root older than the anchor window is refused", not pool.knows_root(old) and pool.knows_root(pool.root()))
again = SP.StwoShieldedPool.from_dict(pool.to_dict())
check("a pool round-trips through its snapshot", again.root() == pool.root() and again.nullifiers == pool.nullifiers)
print("ALL PASS — the Stwo pool hashes as the circuit does" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
