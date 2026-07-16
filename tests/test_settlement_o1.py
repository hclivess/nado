"""
AUTHORITATIVE RECURSIVE SETTLEMENT (execnode/settlement_proofs.prove/verify_settlement_o1) — the money-path
K→1: a real multi-segment zkVM epoch (the W=106 two-phase execution AIR, ROW-COMMITTED) is settled by ONE
recursion bundle. verify_settlement_o1 runs the segment statements + io replay + state-root chain natively
(no cryptography) and, in place of K per-segment stark.verify calls, verifies the fold + row-mode composition
recursion proofs against a statement it builds itself (per-segment periodic tables from the public calls/io,
FS-derived query positions, in-circuit-validated layer-0 seam). Cross-checked against the legacy per-segment
path (same post root); a tampered io log, a tampered layer-0, and a default-policy (protocol-strength) verify
of this reduced-strength test bundle are all rejected.
By DEFAULT this validates the ROW-COMMITTED W=106 segment path (prove_settlement(row_commit=True) +
verify_settlement) — fast (~10 s, native NTT), the sound path the recursion wrapper builds on. The full
recursion BUNDLE at W=106 is memory/throughput-gated in pure Python (see the NADO_HEAVY note below) and runs
only under NADO_HEAVY=1; its MECHANISM is validated in the normal suite by tests/test_recursive_row.py
(two-phase row-mode K→1) and tests/test_rowcomp_verify.py (W=10 row absorption).
(Run: python3 tests/test_settlement_o1.py  — fast segment path; NADO_HEAVY=1 python3 … — full recursion.)
"""
import os, sys, copy, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode import settlement_proofs as SP, zkvmasm

# HEAVY (opt-in). Building the W=106 execution-AIR recursion bundle (fold + row-mode composition over a real
# multi-segment epoch) COMPLETES + VERIFIES end-to-end with the native prover (native NTT to NMAX=2^22, native
# rleaf/rnode Merkle, fast division-free Goldilocks reduction) — ~15 GB and a handful of minutes on this box.
# (It used to OOM at ~40 GB in pure Python; the native prover fixed that, and completing it surfaced + let us
# fix the composition-gadget degree overflow — see doc/zk-recursion.md and air_ir.gadget_max_degree.)
#
# It is still opt-in via NADO_HEAVY=1 because it's minutes, not CI-fast. By default this file runs the fast
# row-committed SEGMENT path (~10 s) and reports SKIP for the full bundle; the recursion MECHANISM is also
# covered small-scale by tests/test_recursive_row.py (two-phase row-mode K→1) and tests/test_rowcomp_verify.py.
HEAVY = os.environ.get("NADO_HEAVY") == "1"

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

NQ, NQO = 2, 2
COUNTER = {"bump": zkvmasm.assemble("""
    movi r1 0
    sload r2 r1
    movi r3 1
    add r2 r3
    sstore r1 r2
    ret r2
""")}
ALICE = "ndoAAAA" + "A" * 41
CID = "c" * 32


def _pre():
    return {CID: {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}}


CALLS = [{"cid": CID, "method": "bump", "caller": ALICE, "args": []} for _ in range(6)]


def t_row_committed_segments():
    """The SOUND path the recursion wrapper builds on: a real W=106 exec-AIR epoch proven ROW-COMMITTED
    (stark.prove(row_commit=True), one recursion-Merkle tree per phase) proves + verifies, and the state-root
    chain reaches the same post root. Fast (native NTT at N<=NMAX); no recursion bundle."""
    from execnode.stark import backend as _B
    b = SP.prove_settlement(_pre(), CALLS, cursor=200, num_queries=NQ, max_rows=300,
                            backend=_B.RECURSION, row_commit=True)
    ok, why, post = SP.verify_settlement(b, num_queries=NQ)
    assert ok, f"row-committed W=106 segments must prove+verify: {why}"
    assert post == b["post_root"], "state-root chain must reach post_root"


_BUNDLE = None
if HEAVY:
    # segments (row-committed exec proofs) + the recursion bundle, at MINIMAL scale (few calls, one comp point
    # per proof). Still ~25 GB / many minutes at W=106 — hence the NADO_HEAVY gate.
    _BUNDLE = SP.prove_settlement_o1(_pre(), CALLS, cursor=200, num_queries=NQ, max_rows=300,
                                     outer_queries=NQO, comp_points_per_proof=1)


def t_o1_settles():
    assert _BUNDLE["num_segments"] >= 2, f"expected a multi-segment epoch, got {_BUNDLE['num_segments']}"
    ok, why, post = SP.verify_settlement_o1(_BUNDLE, num_queries=NQ, outer_queries=NQO)
    assert ok, f"authoritative recursive settlement must verify: {why}"
    assert post == _BUNDLE["post_root"]


def t_matches_legacy_path():
    """The same bundle also passes the legacy per-segment path (row-mode proofs verify natively too) and
    reaches the same post root — the recursion bundle replaces it, it doesn't diverge from it."""
    ok, why, post = SP.verify_settlement(_BUNDLE, num_queries=NQ)
    assert ok, f"legacy per-segment verification must agree: {why}"
    assert post == _BUNDLE["post_root"]


def t_tampered_io_rejected():
    bad = copy.deepcopy(_BUNDLE)
    for e in bad["segments"][0]["io"]:
        if e[0] == 2:                                    # IO_SSTORE: claim a different stored value
            e[2] = 99
    ok, _, _ = SP.verify_settlement_o1(bad, num_queries=NQ, outer_queries=NQO)
    assert not ok, "a tampered io log must be rejected"


def t_tampered_layer0_rejected():
    bad = copy.deepcopy(_BUNDLE)
    q = bad["segments"][0]["proof"]["fri"]["queries"][0]
    q["steps"][0]["lo"] = (int(q["steps"][0]["lo"]) + 1) % (2**61)
    ok, _, _ = SP.verify_settlement_o1(bad, num_queries=NQ, outer_queries=NQO)
    assert not ok, "a tampered layer-0 seam value must be rejected by the in-circuit membership"


def t_default_policy_demands_protocol_strength():
    """verify_settlement_o1 with no explicit policy pins the PROTOCOL query counts — this reduced-strength
    test bundle must be rejected, not trusted at its declared counts."""
    ok, _, _ = SP.verify_settlement_o1(_BUNDLE)
    assert not ok, "default policy must demand protocol query strength"


if __name__ == "__main__":
    check("row-committed W=106 segments prove + verify (sound path)", t_row_committed_segments)
    if not HEAVY:
        print("SKIP  full recursion bundle: it COMPLETES + VERIFIES with the native prover (~15 GB, minutes) "
              "but is opt-in for speed. Set NADO_HEAVY=1 to run the real W=106 O(1) settlement end-to-end.")
        print("      Its MECHANISM is also validated by test_recursive_row.py (two-phase row-mode K→1) and "
              "test_rowcomp_verify.py (W=10 row absorption).")
        print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
        sys.exit(1 if fails else 0)
    check("multi-segment epoch settles via ONE recursion bundle (no per-segment stark.verify)", t_o1_settles)
    check("agrees with the legacy per-segment path (same post root)", t_matches_legacy_path)
    check("tampered io log rejected", t_tampered_io_rejected)
    check("tampered layer-0 seam rejected", t_tampered_layer0_rejected)
    check("default policy demands protocol query strength", t_default_policy_demands_protocol_strength)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
