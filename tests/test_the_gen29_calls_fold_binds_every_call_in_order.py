"""The generation-29 calls fold binds every call, in order, with BLAKE2s.

calls_commit.fold_leaves_b2 is the gen-29 calldata binding (Goldilocks retirement G4,
doc/stwo/g4-settlement-statement.md 2.3): the leaves L1 persists per block, folded with BLAKE2s so the Stwo settlement
circuit proves it with the same Blake component as the tree and the VM. Frozen at the reroll, so pinned now:
  1. the fold equals an independent recomputation from hashlib (person NADOcll1, 32 zero bytes to start, each leaf as
     32 bytes big-endian);
  2. it is incremental: folding a span in two pieces equals folding it at once (a segment boundary changes nothing);
  3. changing, dropping, injecting or reordering a leaf changes the commitment; so does the leaf of a changed call
     (an arg, the method, the caller, the cursor) through the real call_leaf;
  4. malformed input (a leaf of 2^256 or more, a negative leaf, a node that is not 32 bytes) is refused.

Run: python3 tests/test_the_gen29_calls_fold_binds_every_call_in_order.py
"""
import _harness
HOME = _harness.isolate("nado-test-calls-fold-b2-")
import hashlib
import random

from execnode import calls_commit as CC

T = _harness.Report()
rnd = random.Random(29)
leaves = [rnd.getrandbits(256) for _ in range(40)]


def ref(ls):
    n = bytes(32)
    for x in ls:
        n = hashlib.blake2s(n + x.to_bytes(32, "big"), digest_size=32, person=b"NADOcll1").digest()
    return n


c = CC.fold_leaves_b2(CC.chain_start_b2(), leaves)
T.check("1. the fold equals the hashlib recomputation", c == ref(leaves))
T.check("2. folding in two pieces equals folding at once",
        CC.fold_leaves_b2(CC.fold_leaves_b2(CC.chain_start_b2(), leaves[:17]), leaves[17:]) == c)
moved = {
    "a changed leaf": leaves[:5] + [leaves[5] ^ 1] + leaves[6:],
    "a dropped leaf": leaves[:5] + leaves[6:],
    "an injected leaf": leaves[:5] + [12345] + leaves[5:],
    "two leaves swapped": leaves[:5] + [leaves[6], leaves[5]] + leaves[7:],
}
for name, ls in moved.items():
    T.check(f"3. {name} changes the commitment", CC.fold_leaves_b2(CC.chain_start_b2(), ls) != c)
call = {"cid": "c" * 32, "method": "move", "caller": "ndo" + "a" * 45, "args": [1, 2, "x"], "value": 0, "cursor": 500}
base = CC.call_leaf(call)
for field, val in (("args", [1, 3, "x"]), ("method", "join"), ("caller", "ndo" + "b" * 45), ("cursor", 501)):
    other = CC.call_leaf(dict(call, **{field: val}))
    T.check(f"3. a changed call ({field}) changes its leaf and so the commitment",
            other != base and CC.fold_leaves_b2(CC.chain_start_b2(), [base]) != CC.fold_leaves_b2(CC.chain_start_b2(), [other]))
for name, fn in (("a leaf of 2^256", lambda: CC.fold_leaves_b2(bytes(32), [1 << 256])),
                 ("a negative leaf", lambda: CC.fold_leaves_b2(bytes(32), [-1])),
                 ("a 31-byte node", lambda: CC.fold_leaves_b2(bytes(31), [1]))):
    try:
        fn(); ok = False
    except ValueError:
        ok = True
    T.check(f"4. refused: {name}", ok)
T.done("ALL PASS — the gen-29 calls fold binds every call, in order")
