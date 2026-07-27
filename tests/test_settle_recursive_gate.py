"""
REGRESSION (consensus divergence, deep-audit finding 2026-07-27): the fold-acceptance branch had NO activation
gate, so a node on the fold-aware code would HONOUR a `recursive` field (skipping the per-segment exec check and
requiring recursive_verify to pass) while an unupgraded peer IGNORED the field and verified the K-way. An
attacker could staple a BOGUS `recursive` blob onto an otherwise-valid settle tx: the new node REJECTS it, the
old node ACCEPTS it -> fleet fork.

Fix: honour `recursive` ONLY when protocol.SETTLE_PROOF_RECURSIVE is on (flipped at a reroll, so the whole fleet
agrees). This test asserts:
  * flag OFF  -> a bogus `recursive` is IGNORED; the proof still verifies the K-way (identical to an old node).
  * flag ON   -> the bogus `recursive` is REJECTED (uniform, post-reroll all nodes on the fold-aware verifier).

Run: python3 tests/test_settle_recursive_gate.py
"""
import os, sys, copy, tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_recgate_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
from genesis import create_indexers
create_indexers()

import protocol
from execnode import zkvmasm
from execnode.stark import settlement_sparse as SS, storage_tree as ST

fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1

D, NQ = 16, 2
CID = "c" * 32
ALICE = "ndoAAAA" + "A" * 41
COUNTER = {"bump": zkvmasm.assemble("movi r1 0\n sload r2 r1\n movi r3 1\n add r2 r3\n sstore r1 r2\n ret r2")}
REC = ST.digest_hex(ST.SparseStore(D, {}).root())
CALLS = [{"cid": CID, "method": "bump", "caller": ALICE, "args": []}]


def _pre():
    return {CID: {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}}


# an honest single-segment proof (no `recursive` key), fast
_PROOF = SS.prove_settlement_sparse(_pre(), CALLS, cursor=100, rec_hex=REC, num_queries=NQ, depth=D)
assert "recursive" not in _PROOF

_saved = protocol.SETTLE_PROOF_RECURSIVE
try:
    # honest proof verifies regardless of the flag (no `recursive` key -> always the K-path)
    protocol.SETTLE_PROOF_RECURSIVE = False
    ok, _, _, _ = SS.verify_settlement_sparse(_PROOF, num_queries=NQ, depth=D)
    check("honest proof verifies (flag OFF)", ok)
    protocol.SETTLE_PROOF_RECURSIVE = True
    ok, _, _, _ = SS.verify_settlement_sparse(_PROOF, num_queries=NQ, depth=D)
    check("honest proof verifies (flag ON)", ok)

    # staple a BOGUS `recursive` blob (the attack payload) onto the otherwise-valid proof
    bogus = copy.deepcopy(_PROOF)
    bogus["recursive"] = {"fold": {}, "comp": {}, "comp_public": {}, "fold_public": {}, "row_mode": True}
    bogus["comp_points_per_proof"] = None

    # flag OFF: the field is IGNORED -> K-path -> ACCEPTED, exactly as an unupgraded node would (NO fork)
    protocol.SETTLE_PROOF_RECURSIVE = False
    ok_off, why_off, _, _ = SS.verify_settlement_sparse(bogus, num_queries=NQ, depth=D)
    check(f"flag OFF: bogus `recursive` IGNORED, proof accepted the K-way ({why_off})", ok_off)

    # flag ON: the field is HONOURED -> fold path -> recursive_verify rejects the bogus bundle (uniform reject)
    protocol.SETTLE_PROOF_RECURSIVE = True
    ok_on, why_on, _, _ = SS.verify_settlement_sparse(bogus, num_queries=NQ, depth=D)
    check(f"flag ON: bogus `recursive` HONOURED and REJECTED ({why_on})", not ok_on)
finally:
    protocol.SETTLE_PROOF_RECURSIVE = _saved

print("\nALL PASS — the fold-acceptance gate prevents the version-skew fork" if fails == 0 else f"\n{fails} FAILURES")
sys.exit(1 if fails else 0)
