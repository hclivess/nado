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

Run: python3 tests/test_proof_bind_gate.py        (~1 min: one toy STARK in Python + two small real epochs)
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
from execnode.stark import stark, fri, field as F, settlement_sparse as SS, storage_tree as ST, vm_circuit
from execnode.stark import extf as ext2
from execnode import zkvmasm

fails = 0


def check(name, fn):
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


GATE = int(P.PROOF_BIND_HEIGHT)
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


def t_gate_carries_the_reroll_branch():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocol.py")).read()
    assert "PROOF_BIND_HEIGHT = 208000 if CHAIN_GENERATION == 25 else 1" in src


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
    pf = stark.prove(HONEST_TRACE, TRANS, BND, max_degree=2, num_queries=8)
    assert pf["fri"]["N"] == pf["N"] and pf["fri"]["offset"] == stark.OFF, "an honest prover already satisfies P0"
    for rules in (LEGACY, STRICT):
        with stark.with_rules(rules):
            ok, why = stark.verify(pf, TRANS, BND, max_degree=2, num_queries=8)
            assert ok, f"honest proof under {rules}: {why}"


def t_naive_violation_is_refused_under_both_rules():
    """The system was never broken for a LAZY forger: a violated constraint makes the composition high-degree
    and the real FRI refuses it. The finding is that a careful forger sidesteps FRI by redeclaring its domain."""
    pf = stark.prove(BAD_TRACE, TRANS, BND, max_degree=2, num_queries=8)
    for rules in (LEGACY, STRICT):
        with stark.with_rules(rules):
            ok, why = stark.verify(pf, TRANS, BND, max_degree=2, num_queries=8)
            assert not ok, f"a violated constraint must not verify under {rules}"


_FORGED = _forge(BAD_TRACE)


def t_forgery_is_ACCEPTED_below_the_gate():
    """THE FINDING, REPRODUCED. This is what every node accepted before PROOF_BIND_HEIGHT, and why the gate
    exists. If this ever starts failing, the legacy rules changed — which is a consensus change of its own."""
    assert _FORGED["fri"]["N"] == 2 * _FORGED["N"], "the forgery declares a doubled FRI domain"
    with stark.with_rules(LEGACY):
        ok, why = stark.verify(_FORGED, TRANS, BND, max_degree=2, num_queries=8)
        assert ok, f"under the legacy rules the forged proof of a VIOLATED trace verified: {why}"


def t_forgery_is_refused_at_the_gate_naming_the_domain():
    with stark.with_rules(STRICT):
        ok, why = stark.verify(_FORGED, TRANS, BND, max_degree=2, num_queries=8)
        assert not ok and "FRI domain" in why, why
    # the default context is strict too: a caller that never set the rules gets the pin
    ok, why = stark.verify(_FORGED, TRANS, BND, max_degree=2, num_queries=8)
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


D8, NQ = 8, 2
CID = "c" * 32
ALICE = "ndoAAAA" + "A" * 41
COUNTER = {"bump": zkvmasm.assemble("movi r1 0\n sload r2 r1\n movi r3 1\n add r2 r3\n sstore r1 r2\n ret r2")}
REC = ST.digest_hex(ST.SparseStore(D8, {}).root())
CALLS = [{"cid": CID, "method": "bump", "caller": ALICE, "args": [], "cursor": h} for h in (1, 2) for _ in range(2)]


def _pre():
    return {CID: {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}}


def _prove(rules):
    with stark.with_rules(rules):
        return SS.prove_settlement_sparse(_pre(), CALLS, cursor=2, rec_hex=REC, num_queries=NQ, depth=D8)


def _verify(proof, rules):
    with stark.with_rules(rules):
        return SS.verify_settlement_sparse(proof, num_queries=NQ, depth=D8)


_NEW = _prove(STRICT)
_OLD = _prove(LEGACY)


def t_epoch_format_flips_at_the_gate():
    ok, why, _, _ = _verify(_NEW, STRICT); assert ok, f"new-format proof at the gate: {why}"
    ok, why, _, _ = _verify(_OLD, LEGACY); assert ok, f"old-format proof below the gate: {why}"
    ok, why, _, _ = _verify(_OLD, STRICT); assert not ok, "an old-format proof must be refused AT the gate"
    ok, why, _, _ = _verify(_NEW, LEGACY); assert not ok, "a new-format proof must be refused BELOW the gate"
    assert _NEW["kv_pre"] == _OLD["kv_pre"] and _NEW["kv_post"] == _OLD["kv_post"], \
        "the settled root — the only thing consensus sees — is identical either side of the gate"


def t_statement_tamper_is_refused_at_the_gate():
    """Present the proven epoch with a different io log: the rebuilt statement digest differs, so the replayed
    challenges differ and nothing lines up. (The legacy verifier also refuses THIS crude edit through the
    spot-checks; the review's attack is the linear-system rewrite that the crude edit stands in for.)"""
    bad = copy.deepcopy(_NEW)
    seg = bad["segments"][0]
    for i, e in enumerate(seg["io"]):
        if int(e[0]) == 1:                           # IO_SSTORE: bump the stored value
            seg["io"][i] = [e[0], e[1], (int(e[2]) + 1) % F.P]; break
    assert seg["io"] != _NEW["segments"][0]["io"]
    ok, why, _, _ = _verify(bad, STRICT)
    assert not ok, "a proof presented with a statement it was not bound to must fail"


def t_statement_digest_is_what_both_sides_build():
    """Prover and verifier digest the BUILT tables, so they agree by construction; the digest moves with the io."""
    seg = _NEW["segments"][0]
    from execnode import settlement_proofs as SP
    pub_calls, epoch_io = SP._epoch_pub_statement(seg)
    from execnode.stark import backend as _bk
    ok, why, per, bl = vm_circuit.epoch_statement(seg["proof"], pub_calls, epoch_io,
                                                  ext=stark.ext_challenges_active(_bk.RECURSION))
    assert ok, why
    d1 = vm_circuit.statement_digest(seg["proof"]["T"], per, bl)
    io2 = list(epoch_io); io2[0] = (io2[0][0], io2[0][1], (int(io2[0][2]) + 1) % F.P)
    ok, why, per2, bl2 = vm_circuit.epoch_statement(seg["proof"], pub_calls, io2,
                                                    ext=stark.ext_challenges_active(_bk.RECURSION))
    assert ok, why
    assert vm_circuit.statement_digest(seg["proof"]["T"], per2, bl2) != d1
    assert len(d1) == 32


# ---- 4. the child verifier judges by the rules it is handed, not by its own defaults -----------------------------
def t_child_verifier_carries_the_rules():
    """The out-of-process verifier has no context of its own; the rules ride in the request. The child pins
    PROTOCOL query strength, so this NQ=2 bundle is refused for strength either way — what this checks is that
    a request carrying `rules` round-trips to a VERDICT (a malformed request crashes the child to None), and
    the source checks pin that the child enters exactly the rules it was handed."""
    from ops.proof_child import verify_sparse_out_of_process
    res = verify_sparse_out_of_process(_NEW, D8, rules=STRICT)
    assert res is not None and res[0] is False and "query" in str(res[1]).lower(), res
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "ops", "proof_child.py")).read()
    assert '"rules": _r' in src and "_stk.with_rules(" in src and 'req.get("rules")' in src


def t_settle_branch_and_exec_apply_set_the_rules():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tx = open(os.path.join(root, "ops", "transaction_ops.py")).read()
    ex = open(os.path.join(root, "execnode", "execnode.py")).read()
    assert "_stk.rules_at(block_height)" in tx, "L1 judges a settle proof under the rules of ITS block"
    assert '_stk.rules_at(block["block_number"])' in ex, "the exec layer applies a block under ITS rules"
    assert "SS.stark.rules_at(_land_h)" in ex, "the settler proves in the format its landing block will judge"


for name, fn in list(globals().items()):
    if name.startswith("t_") and callable(fn):
        check(name[2:].replace("_", " "), fn)

print()
print("ALL PASS — the FRI domain is pinned and the statement is bound, from PROOF_BIND_HEIGHT" if not fails
      else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
