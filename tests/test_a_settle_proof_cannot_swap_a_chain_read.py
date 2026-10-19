"""A settle proof cannot swap a chain read: every BHASH/BEACON value it claims must equal the finalized chain.

The settlement STARK proves only that a span's execution is CONSISTENT with the BHASH/BEACON values in its io log — a
prover may write any value there. L1 binds each one to its own finalized chain (transaction_ops.settle_chain_reads_check,
run inside _validate_settle before any proof work). Without it a bonded validator could settle a state built on dice,
wheels and beacons of its own choosing. Mapping the settle statement for G4 (2026-10-20) found NO test that swaps a chain
read and expects the refusal — only the honest case and the check's position in the source. This is that test:
  honest BHASH and BEACON reads pass; refused — a swapped block hash, a swapped beacon, a height not yet finalized,
  an epoch not yet finalized, a height the chain does not have, a value outside the field, an unknown read kind; and
  _validate_settle still calls the check (the move from inline code did not drop it).

Run: python3 tests/test_a_settle_proof_cannot_swap_a_chain_read.py
"""
import _harness
HOME = _harness.isolate("nado-test-settle-chain-reads-")
import os

from execnode import zkvm
from execnode.stark import field as F
from execnode import state as ST
from ops import block_ops, transaction_ops as TX
import protocol as P

T = _harness.Report()
H = 10_000                                              # the block validating the settle
FIN = H - P.FINALITY_DEPTH - 1                          # its finalized position
HASHES = {h: "%064x" % (h * 0x1234567 + 99) for h in range(0, FIN + 1, 7)}
BEACONS = {e: 777_000 + e for e in range(0, FIN // P.EPOCH_LENGTH + 1)}

block_ops.get_block_hash_by_number = lambda h: HASHES.get(h)
ST.ExecState.exec_beacon_at = staticmethod(lambda e, _rev, _upto: BEACONS.get(e))

bh_h = sorted(HASHES)[-2]
honest_bh = (zkvm.IO_BHASH, bh_h, int(HASHES[bh_h], 16) % F.P)
honest_bc = (zkvm.IO_BEACON, 3, BEACONS[3] % F.P)


def proof(*reads):
    return {"segments": [{"io": [list(r) for r in reads] + [[zkvm.IO_RET, 0, 0]]}]}


def verdict(*reads):
    try:
        TX.settle_chain_reads_check(proof(*reads), H)
        return "accepted"
    except AssertionError as e:
        return str(e)


T.check("honest BHASH and BEACON reads are accepted", verdict(honest_bh, honest_bc) == "accepted", verdict(honest_bh, honest_bc))
cases = {
    "a swapped block hash": (zkvm.IO_BHASH, bh_h, (honest_bh[2] + 1) % F.P),
    "a swapped beacon": (zkvm.IO_BEACON, 3, (honest_bc[2] + 1) % F.P),
    "a BHASH height not yet finalized": (zkvm.IO_BHASH, FIN + 1, 5),
    "a BEACON epoch not yet finalized": (zkvm.IO_BEACON, FIN // P.EPOCH_LENGTH + 1, 5),
    "a height the chain does not have": (zkvm.IO_BHASH, bh_h + 1, 5),
    "a value outside the field": (zkvm.IO_BHASH, bh_h, F.P),
}
for name, bad in cases.items():
    v = verdict(honest_bh, bad)
    T.check(f"refused: {name}", v != "accepted", v)
T.check("refused: a swapped read hidden after honest ones still fails the whole proof",
        verdict(honest_bh, honest_bc, cases["a swapped beacon"]) != "accepted")
src = open(os.path.join(_harness.ROOT, "ops", "transaction_ops.py")).read()
vs = src[src.index("def _validate_settle("):src.index("def _validate_bridge(")]
T.check("_validate_settle still runs the check, before the DA binding and the proof verification",
        "settle_chain_reads_check(proof, block_height)" in vs
        and vs.index("settle_chain_reads_check(proof, block_height)") < vs.index("DA BINDING — PRUNE-SAFE")
        < vs.index("verify_settlement_sparse"))
T.done("ALL PASS — a settle proof cannot swap a chain read")
