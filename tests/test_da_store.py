"""
DA store: publish -> spread shards -> reconstruct k-of-n trustlessly, tamper-rejection, pruning.
Run: python3 tests/test_da_store.py
"""
import os, sys, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import da
from ops.da_store import DaStore, reconstruct_from

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

DATA = bytes(range(256)) * 40 + b"shielded-proof-blob"   # ~10 KB stand-in for a proof payload
K, N = 4, 8

def _store():
    return DaStore(tempfile.mkdtemp(prefix="nado_dastore_"))

def t1_put_get_roundtrip():
    """A publisher that holds all n shards reconstructs the exact bytes."""
    s = _store(); meta = s.put(DATA, K, N)
    assert meta["k"] == K and meta["n"] == N and len(meta["commitment"]) > 0
    assert s.get(meta["commitment"]) == DATA, "roundtrip"
    assert s.have(meta["commitment"]) == list(range(N)), "publisher holds every shard"

def t2_reconstruct_from_exactly_k():
    """Any k of the n (shard, proof) pairs reconstruct — the redundancy tolerates n-k missing nodes."""
    s = _store(); meta = s.put(DATA, K, N)
    pairs = []
    for i in [1, 3, 5, 7]:                       # an arbitrary k-subset, as if fetched from 4 DA nodes
        sh, pr = s.shard(meta["commitment"], i)
        pairs.append((i, sh, pr))
    assert reconstruct_from(meta, pairs) == DATA, "k-of-n reconstruct"

def t3_spread_then_reconstruct():
    """Publisher hands single (shard,proof) pairs to fresh DA nodes; a consumer pulls k of them back."""
    pub = _store(); meta = pub.put(DATA, K, N)
    nodes = [_store() for _ in range(N)]
    for i in range(N):                            # spread: node i holds only shard i
        sh, pr = pub.shard(meta["commitment"], i)
        assert nodes[i].accept(meta, i, sh, pr), "verified shard accepted"
    # consumer collects k shards from k distinct nodes (say the last k), each self-verifying
    pairs = []
    for i in range(N - K, N):
        r = nodes[i].shard(meta["commitment"], i)
        assert r is not None, "node serves the shard it accepted"
        pairs.append((i, r[0], r[1]))
    assert reconstruct_from(meta, pairs) == DATA

def t4_reject_tampered_shard():
    """A corrupt (shard,proof) fails verify_sample -> accept() refuses it and reconstruct_from ignores it."""
    s = _store(); meta = s.put(DATA, K, N)
    sh, pr = s.shard(meta["commitment"], 2)
    bad = bytearray(sh); bad[0] ^= 0xFF
    node = _store()
    assert node.accept(meta, 2, bytes(bad), pr) is False, "poisoned shard rejected on accept"
    assert node.have(meta["commitment"]) == [], "nothing stored for a rejected shard"
    # a bad shard mixed into a fetch set is dropped; k good ones still reconstruct
    good = [(i, *s.shard(meta["commitment"], i)) for i in [0, 1, 4, 6]]
    salted = good + [(2, bytes(bad), pr)]
    assert reconstruct_from(meta, salted) == DATA, "salted set still decodes from the good k"

def t5_too_few_shards():
    """< k shards cannot reconstruct — get() returns None, reconstruct_from raises."""
    pub = _store(); meta = pub.put(DATA, K, N)
    node = _store()
    for i in range(K - 1):                         # only k-1 shards
        sh, pr = pub.shard(meta["commitment"], i)
        node.accept(meta, i, sh, pr)
    assert node.get(meta["commitment"]) is None, "k-1 shards -> cannot reconstruct"
    try:
        reconstruct_from(meta, [(0, *pub.shard(meta["commitment"], 0))])
        assert False, "should have raised"
    except ValueError:
        pass

def t6_prune():
    """Rolling-window: prune() drops a settled commitment; get() then returns None."""
    s = _store(); meta = s.put(DATA, K, N)
    assert s.get(meta["commitment"]) == DATA
    s.prune(meta["commitment"])
    assert s.meta(meta["commitment"]) is None and s.get(meta["commitment"]) is None

def t7_path_traversal_guard():
    """A commitment can't escape the store root."""
    s = _store()
    for bad in ["../evil", "a/b", "..", "."]:
        try:
            s.meta(bad); assert False, f"expected reject for {bad!r}"
        except ValueError:
            pass


for name, fn in sorted(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
