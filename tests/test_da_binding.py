"""DA-BINDING: a settle-with-proof's calls_commitment is bound to the ORDERED on-chain `blob` calldata, so a
prover cannot settle a fabricated call sequence. The bridge is calls_commit.block_calls — the SAME function L1
(verifier) and the exec node (prover) use to derive the calls list from a block — plus da_calls_commitment,
what L1 independently computes for a settled span. This test pins: determinism, that the prover's per-call
calls_commitment over block_calls equals L1's da_calls_commitment, and that ANY substitution (call added,
dropped, reordered, or a field changed) breaks the commitment.

Run: python3 tests/test_da_binding.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import calls_commit as CC

fails = 0
def check(name, fn):
    global fails
    try:
        assert fn(), "assertion false"
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def _blob(sender, cid, method, args, ns=None, value=0):
    d = {"op": "call", "contract": cid, "method": method, "args": args, "value": value}
    if ns:
        d["ns"] = ns
    return {"recipient": "blob", "sender": sender, "data": d}

def _block(n, ts, txs):
    return {"block_number": n, "block_timestamp": ts, "block_transactions": txs}

A, B = "ndoAAAA" + "A" * 41, "ndoBBBB" + "B" * 41

BLK1 = _block(100, 1700, [
    _blob(A, "cid_dice", "bet", [3, 50]),
    {"recipient": "bond", "sender": B, "data": {}},          # non-blob -> ignored
    _blob(B, "cid_dice", "settle", [3]),
    _blob(A, "cid_other", "run", [7], ns="rollup2"),         # different ns -> not in default
    {"recipient": "blob", "sender": A, "data": {"op": "deploy", "code": {}}},  # deploy -> excluded
])
BLK2 = _block(101, 1706, [_blob(A, "cid_dice", "bet", [1, 20])])

# 1) block_calls extracts exactly the default-ns op=='call' blobs, in order, with the block's context
def t_extract():
    cs = CC.block_calls(BLK1, "default")
    return (len(cs) == 2
            and cs[0] == {"cid": "cid_dice", "method": "bet", "caller": A, "args": [3, 50], "value": 0,
                          "cursor": 100, "timestamp": 1700}
            and cs[1]["method"] == "settle" and cs[1]["caller"] == B
            and CC.block_calls(BLK1, "rollup2")[0]["cid"] == "cid_other")
check("block_calls: only default-ns op=='call' blobs, ordered, with block context", t_extract)

# 2) determinism
check("da_calls_commitment is deterministic", lambda:
      CC.da_calls_commitment([BLK1, BLK2]) == CC.da_calls_commitment([BLK1, BLK2]))

# 3) the PROVER's calls_commitment over block_calls == L1's da_calls_commitment (prover and verifier agree)
def t_prover_matches():
    calls = CC.block_calls(BLK1, "default") + CC.block_calls(BLK2, "default")
    return CC.calls_commitment(calls) == CC.da_calls_commitment([BLK1, BLK2])
check("prover calls_commitment(block_calls) == L1 da_calls_commitment", t_prover_matches)

# 4) BINDING: every kind of tamper changes the commitment
base = CC.da_calls_commitment([BLK1, BLK2])
def tamper(mut):
    import copy
    b1, b2 = copy.deepcopy(BLK1), copy.deepcopy(BLK2)
    mut(b1, b2)
    return CC.da_calls_commitment([b1, b2]) != base

check("tamper: change an arg  -> commitment differs", lambda: tamper(
    lambda b1, b2: b1["block_transactions"][0]["data"].__setitem__("args", [4, 50])))
check("tamper: change method   -> differs", lambda: tamper(
    lambda b1, b2: b1["block_transactions"][0]["data"].__setitem__("method", "cashout")))
check("tamper: change caller/sender -> differs", lambda: tamper(
    lambda b1, b2: b1["block_transactions"][0].__setitem__("sender", B)))
check("tamper: inject an extra call -> differs", lambda: tamper(
    lambda b1, b2: b2["block_transactions"].append(_blob(A, "cid_dice", "bet", [9, 9]))))
check("tamper: drop a call -> differs", lambda: tamper(
    lambda b1, b2: b1["block_transactions"].pop(0)))
check("tamper: reorder calls -> differs", lambda: tamper(
    lambda b1, b2: b1["block_transactions"].insert(0, b1["block_transactions"].pop(2))))
check("tamper: change the block's cursor/timestamp context -> differs", lambda: tamper(
    lambda b1, b2: b1.__setitem__("block_number", 999)))

# 5) verify_calls_bound_to_da — the L1 gate: accept a proof whose segment commitment matches the on-chain
#    blocks it settles, reject a mismatch, a missing commitment, an unavailable block, or a gap in coverage.
_BLOCKS = {100: BLK1, 101: BLK2}
def _get_block(h):
    return _BLOCKS.get(h)

def _proof_over(prev, end):
    """one segment covering (prev, end], carrying the HONEST commitment over those blocks."""
    blks = [_BLOCKS[h] for h in range(prev + 1, end + 1)]
    return {"segments": [{"cursor": end, "calls_commitment": CC.da_calls_commitment(blks, "default")}]}

check("gate: honest proof over (99,101] is bound",
      lambda: CC.verify_calls_bound_to_da(_proof_over(99, 101), "default", 99, 101, _get_block)[0])
check("gate: multi-segment span (per block) is bound", lambda: CC.verify_calls_bound_to_da(
      {"segments": [{"cursor": 100, "calls_commitment": CC.da_calls_commitment([BLK1], "default")},
                    {"cursor": 101, "calls_commitment": CC.da_calls_commitment([BLK2], "default")}]},
      "default", 99, 101, _get_block)[0])
check("gate: FABRICATED commitment rejected", lambda: not CC.verify_calls_bound_to_da(
      {"segments": [{"cursor": 101, "calls_commitment": 12345}]}, "default", 99, 101, _get_block)[0])
check("gate: missing calls_commitment rejected", lambda: not CC.verify_calls_bound_to_da(
      {"segments": [{"cursor": 101}]}, "default", 99, 101, _get_block)[0])
check("gate: unavailable block rejected", lambda: not CC.verify_calls_bound_to_da(
      _proof_over(99, 101), "default", 99, 105, lambda h: None)[0])
check("gate: segments not covering the span rejected", lambda: not CC.verify_calls_bound_to_da(
      {"segments": [{"cursor": 100, "calls_commitment": CC.da_calls_commitment([BLK1], "default")}]},
      "default", 99, 101, _get_block)[0])

print("\n" + ("ALL PASSED" if not fails else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
