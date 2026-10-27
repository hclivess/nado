"""PROOF_BIND_HEIGHT: the FRI domain is the STARK's, and the epoch statement is in the transcript.

Security review 2026-09-23, findings P0 and A1 (doc/security-review-2026-09-23.md §5, §6). Both are verifier
PINS — an honest prover already satisfies them — so both are validation-rule changes gated on the block being
judged (protocol.PROOF_BIND_HEIGHT, execnode/stark/stark.rules_at). This test pins the rule at the boundary and
nowhere else, and it BUILDS the P0 forgery rather than trusting the reviewer's trace of it:

  P0  stark.verify never compared proof["fri"]["N"] / ["offset"] with its own N / OFF. The spot-checks bind
      layer-0 values at idx mod (N/2) with the STARK's N, so a FRI declared over 2N need only agree with the
      composition on N of its 2N points — and N points ALWAYS interpolate to a degree < N polynomial, which is
      exactly what a blowup-2 FRI over 2N accepts. Any trace, constraints violated or not, then "verifies".
      Below the gate this file shows that forgery ACCEPTED; at the gate it is refused, naming the domain.
  A1  the exec epoch's public statement (io log, args, programs, per-row context — the periodic tables the
      verifier rebuilds) entered no transcript, so the query points were fixed before the statement was chosen.
      From the gate a digest of the rebuilt statement is absorbed before the trace roots; that changes the proof
      FORMAT, so an old-format proof is refused at the gate and a new-format one below it — prover and verifier
      flip on the same block, and the memo/child verifier carry the rules explicitly.

Run: python3 tests/test_proof_bind_gate.py        (one toy STARK in Python; the real-epoch half retired in G9 with the exec AIR)
"""
import os
import sys
import copy
import tempfile
import traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-proofbind-")      # NEVER the live node's home (rule 4)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_ALLOW_PYTHON_KERNELS"] = "1"                        # the toy AIR proves on the blake2b path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol as P
from execnode.stark import stark, fri, field as F
from execnode.stark import extf as ext2

import _harness
_report = _harness.Report()
check = _report.run


GATE = 1   # the rule holds from block 1 (gen 25's PROOF_BIND_HEIGHT, deleted after the betanet-8 reroll); height 0 is below it
LEGACY, STRICT = stark.RULES_LEGACY, stark.RULES_STRICT


# ---- 1. the rules are a pure function of the block height ------------------------------------------------------
def t_rules_pure_in_height():
    # Only THIS gate's two fields are asserted: later gates (PROOF_BLOCK_SELECTOR_HEIGHT, A2) add fields of
    # their own that flip at their own heights, and test_proof_block_selector pins those.
    pins = lambda r: (r.pin_fri_domain, r.bind_statement)
    assert pins(stark.rules_for_height(GATE - 1)) == (False, False), "one block below the gate: the old rules"
    assert pins(stark.rules_for_height(GATE)) == (True, True), "at the gate: both pins"
    assert pins(stark.rules_for_height(GATE + 100000)) == (True, True)
    assert pins(stark.rules_for_height(0)) == (False, False) or GATE <= 0
    assert stark.rules_for_height(None) == STRICT, "no height known = strict, never permissive"
    assert stark.current_rules() == STRICT, "nothing set = strict (a forgotten site refuses loudly)"
    with stark.rules_at(GATE - 1):
        assert pins(stark.current_rules()) == (False, False)
        with stark.rules_at(GATE):
            assert pins(stark.current_rules()) == (True, True)
        assert pins(stark.current_rules()) == (False, False), "contexts nest and restore"
    assert stark.current_rules() == STRICT


def t_gate_stays_deleted():
    assert not hasattr(P, "PROOF_BIND_HEIGHT")


# ---- 2. P0: build the forgery, watch the old rule accept it, watch the gate refuse it ----------------------------
T_TOY = 16
TRANS = [lambda cur, nxt, per: F.sub(F.sub(nxt[0], cur[0]), 1)]      # a counter: next = cur + 1
BND = [(0, 0, 0)]
HONEST_TRACE = [[i] for i in range(T_TOY)]
BAD_TRACE = [[i if i < 10 else i + 5] for i in range(T_TOY)]           # jumps by 6 at row 10: constraint violated


def _lagrange_eval(xs, ys, z):
    """f(z) for the unique degree < len(xs) polynomial through (xs, ys): base-field points, GF(p^3) values (the
    composition is extension-valued because the alphas are). O(n^2) per point; n = 64 here."""
    acc = ext2.ZERO
    for i, (xi, yi) in enumerate(zip(xs, ys)):
        num, den = 1, 1
        for j, xj in enumerate(xs):
            if j != i:
                num = F.mul(num, F.sub(z, xj)); den = F.mul(den, F.sub(xi, xj))
        acc = ext2.add(acc, ext2.scalar_mul(ext2.canon(yi), F.mul(num, F.inv(den))))
    return acc


def _forge(trace):
    """stark.prove with fri.prove swapped for the review's construction: the composition cp on the N-coset
    becomes a 2N vector v with v[j] = cp[j mod N/2] for j < N (every value the spot-checks can ask for) and a
    second half chosen so v is a genuine degree < N polynomial on the 2N coset — i.e. the interpolant through
    the first N points, evaluated on the rest. fri.prove then proves it HONESTLY: real folds, real grind, real
    openings, and layer 0 at any queried idx is cp at idx mod N/2, which is what stark.verify compares."""
    real = fri.prove

    def forged(evals, offset, blowup=4, num_queries=fri.NUM_QUERIES, transcript=None, backend=None, ext=None):
        N = len(evals); half = N // 2
        pts = F.domain(2 * N, offset)
        xs, ys = pts[:N], [ext2.canon(evals[j % half]) for j in range(N)]
        v = list(ys) + [_lagrange_eval(xs, ys, z) for z in pts[N:]]
        return real(v, offset, blowup, num_queries, transcript=transcript, backend=backend, ext=ext)

    fri.prove = forged
    try:
        return stark.prove(trace, TRANS, BND, max_degree=2, num_queries=8)
    finally:
        fri.prove = real


def t_honest_toy_proof_verifies_under_both_rules():
    # proven and verified under the SAME rules: later gates (A2, round2) make the transcript rule-dependent
    for rules in (LEGACY, STRICT):
        with stark.with_rules(rules):
            pf = stark.prove(HONEST_TRACE, TRANS, BND, max_degree=2, num_queries=8)
            assert pf["fri"]["N"] == pf["N"] and pf["fri"]["offset"] == stark.OFF, "an honest prover already satisfies P0"
            ok, why = stark.verify(pf, TRANS, BND, max_degree=2, num_queries=8)
            assert ok, f"honest proof under {rules}: {why}"


def t_naive_violation_is_refused_under_both_rules():
    """The system was never broken for a LAZY forger: a violated constraint makes the composition high-degree
    and the real FRI refuses it. The finding is that a careful forger sidesteps FRI by redeclaring its domain."""
    for rules in (LEGACY, STRICT):
        with stark.with_rules(rules):
            pf = stark.prove(BAD_TRACE, TRANS, BND, max_degree=2, num_queries=8)
            ok, why = stark.verify(pf, TRANS, BND, max_degree=2, num_queries=8)
            assert not ok, f"a violated constraint must not verify under {rules}"


with stark.with_rules(LEGACY):
    _FORGED = _forge(BAD_TRACE)                      # the forgery as a pre-gate prover would have built it


def t_forgery_is_ACCEPTED_below_the_gate():
    """THE FINDING, REPRODUCED. This is what every node accepted before PROOF_BIND_HEIGHT, and why the gate
    exists. If this ever starts failing, the legacy rules changed — which is a consensus change of its own."""
    assert _FORGED["fri"]["N"] == 2 * _FORGED["N"], "the forgery declares a doubled FRI domain"
    with stark.with_rules(LEGACY):
        ok, why = stark.verify(_FORGED, TRANS, BND, max_degree=2, num_queries=8)
        assert ok, f"under the legacy rules the forged proof of a VIOLATED trace verified: {why}"


def t_forgery_is_refused_at_the_gate_naming_the_domain():
    with stark.with_rules(STRICT):
        forged = _forge(BAD_TRACE)                   # built with every later prologue, so ONLY the pin refuses it
        ok, why = stark.verify(forged, TRANS, BND, max_degree=2, num_queries=8)
        assert not ok and "FRI domain" in why, why
    # the default context is strict too: a caller that never set the rules gets the pin
    ok, why = stark.verify(forged, TRANS, BND, max_degree=2, num_queries=8)
    assert not ok and "FRI domain" in why, why


def t_fri_verify_pins_its_own_domain():
    """The pin lives at both ends: a caller that reaches fri.verify directly with its protocol domain."""
    pf = _FORGED["fri"]
    ok, why = fri.verify(pf, expected_N=_FORGED["N"], expected_blowup=2, num_queries=8)
    assert not ok and "domain size" in why, why
    ok, why = fri.verify(pf, expected_offset=stark.OFF + 1, expected_blowup=2, num_queries=8)
    assert not ok and "domain offset" in why, why


# ---- 3. A1: the statement is in the transcript, and the format flips at the gate --------------------------------
def t_toy_statement_binds_the_transcript():
    s1, s2 = bytes(range(32)), bytes(range(1, 33))
    pf = stark.prove(HONEST_TRACE, TRANS, BND, max_degree=2, num_queries=8, statement=s1)
    assert stark.verify(pf, TRANS, BND, max_degree=2, num_queries=8, statement=s1)[0]
    assert not stark.verify(pf, TRANS, BND, max_degree=2, num_queries=8, statement=s2)[0], "another statement"
    assert not stark.verify(pf, TRANS, BND, max_degree=2, num_queries=8)[0], "no statement at all"
    # the lanes are exact: a digest is absorbed as 8 u32s, never as a string the alghash2 backend would byte-sum
    assert stark.statement_lanes(s1) != stark.statement_lanes(s2)
    assert stark.statement_lanes(bytes(32)) == (0,) * 8


# epoch format flips at the gate / statement tamper / statement digest is what both sides build retired in G9: the
# exec AIR (vm_circuit) and the Goldilocks settlement prover/verifier (settlement_sparse, settlement_proofs) were deleted
# child verifier carries the rules retired in G9: ops/proof_child.py (the out-of-process settle-proof verifier) was deleted


def t_settle_branch_and_exec_apply_set_the_rules():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tx = open(os.path.join(root, "ops", "transaction_ops.py")).read()
    ex = open(os.path.join(root, "execnode", "execnode.py")).read()
    # (the L1 settle-proof branch and the settler's landing-height format retired in G9: L1 refuses every settle
    # proof on gen 29, and the Goldilocks settle prover was deleted)
    assert "settle_verify_key" not in tx, "L1 no longer verifies a Goldilocks settle proof, under any rules"
    assert '_stk.rules_at(block["block_number"])' in ex, "the exec layer applies a block under ITS rules"


for name, fn in list(globals().items()):
    if name.startswith("t_") and callable(fn):
        check(name[2:].replace("_", " "), fn)

print()
print("ALL PASS — the FRI domain is pinned and the statement is bound, from PROOF_BIND_HEIGHT" if not _report.fails
      else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
