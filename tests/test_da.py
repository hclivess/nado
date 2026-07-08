"""
Data availability: Reed-Solomon erasure coding (any k-of-n shards reconstruct) + a hash-based Merkle
commitment + availability sampling. See ops/da.py and doc/rolling-mode-and-da.md §4.2.

Run: python3 tests/test_da.py
"""
import os, sys, itertools, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import da

random.seed(1)
fails = 0
def check(name, cond):
    global fails
    if cond: print(f"PASS  {name}")
    else: fails += 1; print(f"FAIL  {name}")


def t1_any_k_of_n_reconstruct():
    """Any k of the n shards reconstruct the original blob (exhaustive over C(8,4)=70 subsets)."""
    data = bytes(random.randrange(256) for _ in range(1000))
    k, n = 4, 8
    m = da.encode(data, k, n)
    for combo in itertools.combinations(range(n), k):
        assert da.reconstruct(m, {i: m["shards"][i] for i in combo}) == data, f"combo {combo}"

def t2_more_than_k_also_works():
    """Supplying MORE than k shards still reconstructs (uses the first k)."""
    data = bytes(range(200))
    m = da.encode(data, 3, 7)
    assert da.reconstruct(m, {i: m["shards"][i] for i in range(6)}) == data

def t3_fewer_than_k_fails():
    """Fewer than k shards cannot reconstruct — raises, never returns wrong data silently."""
    m = da.encode(b"hello world " * 20, 4, 8)
    try:
        da.reconstruct(m, {0: m["shards"][0], 1: m["shards"][1]}); ok = False
    except Exception:
        ok = True
    assert ok

def t4_sampling_verifies_and_rejects():
    """A committed shard verifies against the commitment; a tampered shard or wrong index is rejected."""
    m = da.encode(b"availability", 3, 9)
    sp = da.sample_proof(m, 5)
    assert da.verify_sample(m["commitment"], 5, sp["shard"], sp["proof"]), "valid sample verifies"
    assert not da.verify_sample(m["commitment"], 5, sp["shard"] + b"x", sp["proof"]), "tampered shard rejected"
    assert not da.verify_sample(m["commitment"], 4, sp["shard"], sp["proof"]), "index-swapped proof rejected"

def t5_determinism():
    """Same data → same commitment and same shards (integer-only, no floats)."""
    d = bytes(range(50))
    a = da.encode(d, 5, 10); b = da.encode(d, 5, 10)
    assert a["commitment"] == b["commitment"] and a["shards"] == b["shards"]

def t6_edge_lengths():
    """Empty, 1-byte, exact-multiple, and large blobs all round-trip through any k shards."""
    for d in [b"", b"x", bytes(range(28)), bytes(random.randrange(256) for _ in range(5000))]:
        m = da.encode(d, 3, 6)
        assert da.reconstruct(m, {i: m["shards"][i] for i in (0, 2, 5)}) == d, f"len={len(d)}"


for name, fn in sorted(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, (fn() or True))

print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
