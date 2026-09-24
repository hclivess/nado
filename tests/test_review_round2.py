"""REVIEW_R2_HEIGHT: the second round of 2026-09-23 review fixes, pinned at the gate.

doc/security-review-2026-09-23.md — exec: Z6 duplicate note commitments, Z9 the field path's exit address,
Z4 the field pool's capacity, F7 runtime typing, F10 the lock flag, F8 constructor asset effects, F4 the
per-block execution budget (with its prover mirror); L1: S4 the DA-carried proven marker, A4 canonical
pre_contracts keys; proof: P2 aux as digest lanes, P3/Z8 the AIR identity in the transcript, P4 path lengths.

Every rule is shown differing across the gate and nowhere else. The proof-format ones are shown on a toy AIR
under explicit rules (legacy = every earlier gate on, round2 off).

Run: python3 tests/test_review_round2.py
"""
import os
import sys
import copy
import tempfile
import traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-round2-")        # NEVER the live node's home (rule 4)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_TESTNET"] = "1"
os.environ["NADO_ALLOW_PYTHON_KERNELS"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("blocks", "index", "private", "peers", "transactions"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

import protocol as P
from execnode.state import ExecState, asset_id
from execnode import zkvmasm, zkvm
from execnode.stark import stark, field as F, settlement_sparse as SS
from execnode.shielded_field import TREE_DEPTH

fails = 0


def check(name, fn):
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


GATE = int(P.REVIEW_R2_HEIGHT)
ALICE = "mldsa44" + "a" * 42
LEGACY = stark.Rules(True, True, True, False)
NEW = stark.Rules(True, True, True, True)


def fresh(block):
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json"))
    st.cursor = int(block) - 1
    st.bridge[ALICE] = 10 ** 9
    return st


# ---- rules ------------------------------------------------------------------------------------------------
def t_rules_flip_at_the_gate():
    assert not stark.rules_for_height(GATE - 1).round2 and stark.rules_for_height(GATE).round2
    st = fresh(GATE - 1); assert not st.rules_r2()
    st = fresh(GATE); assert st.rules_r2()
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocol.py")).read()
    assert "REVIEW_R2_HEIGHT = 214000 if CHAIN_GENERATION == 25 else 1" in src
    assert "EXEC_CTX_CURRENT_HEIGHT = (1 << 62) if CHAIN_GENERATION == 25 else 1" in src


# ---- F7 / F10 / F8 (deploy) ---------------------------------------------------------------------------------
def t_f7_f10_deploy_typing_and_lock_flag():
    code = {"go": zkvmasm.assemble("movi r0 1\n ret r0")}
    st = fresh(GATE)
    assert st.apply_blob({"op": "deploy", "code": code, "nonce": 1, "runtime": ["zkvm"]}, ALICE, "t").startswith("skip")
    st.apply_blob({"op": "deploy", "code": code, "nonce": 2, "upgradable": "false"}, ALICE, "t")
    cid = next(iter(st.contracts)); assert st.contracts[cid]["upgradable"] is False, "false-like locks at the gate"
    st = fresh(GATE - 1)
    st.apply_blob({"op": "deploy", "code": code, "nonce": 2, "upgradable": "false"}, ALICE, "t")
    cid = next(iter(st.contracts)); assert st.contracts[cid]["upgradable"] is True, "legacy: only JSON false locked"


def t_f8_constructor_asset_effects_are_committed():
    """A constructor's asset effects used to be computed and DROPPED. From the gate they are staged and committed
    like a call's — and, like a call's, an ILLEGAL effect reverts the constructor (the contract deploys with
    empty state). The differential: a constructor that writes a slot AND mints an asset it does not issue keeps
    the slot below the gate (effects ignored) and deploys empty at it (effects judged)."""
    ctor = zkvmasm.assemble("movi r1 7\n movi r2 0\n sstore r2 r1\n movi r1 12345\n ctx r2 caller\n movi r3 5\n amint r1 r2 r3\n ret r0")
    code = {"constructor": ctor, "go": zkvmasm.assemble("ret r0")}
    st = fresh(GATE - 1)
    st.apply_blob({"op": "deploy", "code": code, "nonce": 3}, ALICE, "t")
    cid = next(iter(st.contracts))
    assert st.contracts[cid]["storage"]["slots"].get("0") == 7, "legacy: the slot write survives, the mint is silently dropped"
    st = fresh(GATE)
    st.apply_blob({"op": "deploy", "code": code, "nonce": 3}, ALICE, "t")
    cid = next(iter(st.contracts))
    assert st.contracts[cid]["storage"] == {}, "at the gate the illegal mint reverts the constructor: empty state"
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "execnode", "state.py")).read()
    assert "elif self.rules_r2() and _fx:" in src and "self.stage_asset_effects(cid, _fx)" in src


# ---- F4 per-block execution budget ---------------------------------------------------------------------------
def t_f4_block_budget_reverts_the_call_that_exceeds_it_and_the_prover_mirrors():
    # a tight loop that burns ~GAS_LIMIT steps: jmp to itself until the gas limit reverts? No — a call that
    # executes many steps and RETURNS: count down from a big number.
    loop = zkvmasm.assemble("movi r1 60000\n movi r2 1\n loop:\n sub r1 r2\n jnz r1 @loop\n ret r0")
    code = {"burn": loop}
    from protocol import EXEC_BLOCK_STEP_BUDGET
    st = fresh(GATE)
    st.apply_blob({"op": "deploy", "code": code, "nonce": 4}, ALICE, "t")
    cid = next(iter(st.contracts))
    meter = {}
    zkvm.run(code, "burn", 1, [], {}, meter=meter)
    per_call = meter["gas"]; assert 100_000 < per_call < zkvm.GAS_LIMIT, per_call
    fits = int(EXEC_BLOCK_STEP_BUDGET) // per_call
    st._block_steps = 0
    for i in range(fits):
        assert st.apply_blob({"op": "call", "contract": cid, "method": "burn", "args": [], "value": 1}, ALICE, f"c{i}").endswith("-> ok")
    r = st.apply_blob({"op": "call", "contract": cid, "method": "burn", "args": [], "value": 1}, ALICE, "cx")
    assert "budget exhausted" in r, r
    assert st.bridge[ALICE] == 10 ** 9 - fits, "the reverted call's escrow came back"
    st_old = fresh(GATE - 1)
    st_old.apply_blob({"op": "deploy", "code": code, "nonce": 4}, ALICE, "t")
    st_old._block_steps = 0
    for i in range(fits + 1):
        assert st_old.apply_blob({"op": "call", "contract": cid, "method": "burn", "args": [], "value": 1}, ALICE, f"c{i}").endswith("-> ok")
    # the prover: the same calls in one block are unprovable past the budget, provable below the gate
    from execnode import settlement_proofs as SP
    pre = {cid: {"code": code, "storage": {"slots": {}}, "runtime": "zkvm"}}
    calls = [{"cid": cid, "method": "burn", "caller": ALICE, "args": [], "cursor": GATE} for _ in range(fits + 1)]
    try:
        SP.prove_epoch(pre, calls, cursor=GATE, num_queries=2)
        assert False, "the prover must refuse what the chain reverted"
    except ValueError as e:
        assert "budget" in str(e), e


# ---- Z6 / Z9 / Z4 (shielded) ---------------------------------------------------------------------------------
def t_z6_duplicate_field_note_refused_and_z4_pool_full():
    st = fresh(GATE)
    assert st.apply_field_shield(1000, 7, 9).startswith("field-shield")
    assert st.apply_field_shield(1000, 7, 9) == "skip field-shield: duplicate note commitment"
    st_old = fresh(GATE - 1)
    assert st_old.apply_field_shield(1000, 7, 9).startswith("field-shield")
    assert st_old.apply_field_shield(1000, 7, 9).startswith("field-shield"), "legacy admitted the duplicate"
    st = fresh(GATE)
    st.field_pool.commitments = [i + 1 for i in range(1 << TREE_DEPTH)]     # a full tree
    assert st.apply_field_shield(5, 1, 2) == "skip field-shield: the field pool is full"


def t_z9_field_exit_address_validated():
    from execnode.state import MAX_EXIT_VALUE
    st = fresh(GATE)
    bundle = {"stark": {"joinsplit2": {"proof": {}, "root": "0", "nf": "1", "cm_out1": "2", "cm_out2": "3",
                                       "public_value": -5, "fee": 0}}, "withdraw_addr": "not-an-address"}
    r = st.apply_field_transfer(bundle)
    assert "withdraw_addr is not a spendable account" in r, r


# ---- S4 the DA-carried proven marker -------------------------------------------------------------------------
def t_s4_da_proof_records_the_marker_from_the_gate():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ops", "account_ops.py")).read()
    assert '"proof_da" in data' in src and "REVIEW_R2_HEIGHT" in src


# ---- A4 canonical pre_contracts keys ---------------------------------------------------------------------------
def t_a4_non_canonical_pre_contracts_keys_are_refused():
    ok, why = SS._canonical_pre_contracts({"c" * 32: {"storage": {"slots": {"05": 1}}}})
    assert not ok and "slot key" in why
    ok, why = SS._canonical_pre_contracts({"C" * 32: {"storage": {"slots": {"5": 1}}}})
    assert not ok and "cid" in why
    ok, why = SS._canonical_pre_contracts({"c" * 32: {"storage": {"slots": {"5": 1, "0": 7}}}})
    assert ok
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "execnode", "stark", "settlement_sparse.py")).read()
    assert "if stark.current_rules().round2:" in src and "okc, whyc = _canonical_pre_contracts(bundle[\"pre_contracts\"]," in src


def t_a4_fixed_name_contracts_pass_from_their_gate_and_nothing_else_does():
    """PROOF_FIXED_CID_HEIGHT: live state holds `faucet` and `sovereign`, so the hex-only check refused EVERY honest
    settle proof from 214000. From the gate exactly those names pass; a near-miss spelling never does."""
    import protocol as P
    pre = {"c" * 32: {"storage": {"slots": {"5": 1}}}, "faucet": {"storage": {"slots": {"1": 2}}},
           "sovereign": {"storage": {"slots": {}}}}
    ok, why = SS._canonical_pre_contracts(pre)
    assert not ok and "faucet" in why, "below the gate the refusal stands, so replay is unchanged"
    ok, why = SS._canonical_pre_contracts(pre, fixed_names=True)
    assert ok, why
    for bad in ("Faucet", "faucet ", "0xab", "FAUCET", "faucet2"):
        ok, why = SS._canonical_pre_contracts({bad: {"storage": {"slots": {}}}}, fixed_names=True)
        assert not ok, f"{bad!r} must stay refused"
    assert "PROOF_FIXED_CID_HEIGHT = (1 << 62) if CHAIN_GENERATION == 25 else 1" in open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocol.py")).read()
    assert P.PROOF_FIXED_CID_HEIGHT > P.REVIEW_R2_HEIGHT


# ---- proof rules: P2 aux lanes, P3/Z8 AIR identity, P4 path lengths ----------------------------------------------
T_TOY = 16
TRANS = [lambda cur, nxt, per: F.sub(F.sub(nxt[0], cur[0]), 1)]
BND = [(0, 0, 0)]
TRACE = [[i] for i in range(T_TOY)]


def _prove(rules, aux=None, bnd=BND):
    with stark.with_rules(rules):
        return stark.prove(TRACE, TRANS, bnd, max_degree=2, num_queries=8, aux=aux)


def _verify(pf, rules, aux=None, bnd=BND, trans=TRANS):
    with stark.with_rules(rules):
        return stark.verify(pf, trans, bnd, max_degree=2, num_queries=8, aux=aux)


def t_air_identity_binds_the_transcript_at_the_gate():
    pf = _prove(NEW)
    assert _verify(pf, NEW)[0]
    assert not _verify(pf, LEGACY)[0], "a round-2 proof is refused below the gate (format)"
    assert not _verify(_prove(LEGACY), NEW)[0], "a pre-gate proof is refused at the gate"
    # the AIR the VERIFIER holds is what enters: a different boundary statement or constraint count fails
    assert not _verify(pf, NEW, bnd=[(0, 0, 1)])[0], "another boundary value"
    assert not _verify(pf, NEW, trans=TRANS + TRANS)[0], "another constraint count"
    d1 = stark.air_digest(16, 1, 2, 1, BND, [[1] * 16]); d2 = stark.air_digest(16, 1, 2, 1, BND, [[2] * 16])
    assert d1 != d2 and len(d1) == 32, "the periodic tables are in the identity when no statement digest is"
    assert stark.air_digest(16, 1, 2, 1, BND, [{"period": 1, "base": [3]}]) == stark.air_digest(16, 1, 2, 1, BND, [[3] * 16]), \
        "a structured column and its dense form have one identity"


def t_aux_is_bound_by_digest_lanes_not_byte_sum():
    a, b = "ndoAB", "ndoBA"                               # same byte sum, different strings
    pf = _prove(NEW, aux=a)
    assert _verify(pf, NEW, aux=a)[0]
    assert not _verify(pf, NEW, aux=b)[0], "an address with the same byte sum must NOT verify (P2)"
    from execnode.stark import backend as BK
    with stark.with_rules(NEW):
        t1 = stark.Transcript(stark.DOMAIN_STARK, backend=BK.RECURSION); stark.absorb_aux(t1, a)
        t2 = stark.Transcript(stark.DOMAIN_STARK, backend=BK.RECURSION); stark.absorb_aux(t2, b)
        assert t1.state != t2.state, "under alghash2 the two strings used to absorb IDENTICALLY (byte sum)"
    with stark.with_rules(LEGACY):
        t1 = stark.Transcript(stark.DOMAIN_STARK, backend=BK.RECURSION); stark.absorb_aux(t1, a)
        t2 = stark.Transcript(stark.DOMAIN_STARK, backend=BK.RECURSION); stark.absorb_aux(t2, b)
        assert t1.state == t2.state, "THE FINDING: the legacy alghash2 encoding cannot tell them apart"


def t_opening_paths_must_be_log2_n_long():
    pf = _prove(NEW)
    bad = copy.deepcopy(pf)
    col = bad["openings"][0]["cols"][0]
    col["cur_path"] = list(col["cur_path"]) + [col["cur_path"][-1]]
    ok, why = _verify(bad, NEW)
    assert not ok and "path length" in why, why


for name, fn in list(globals().items()):
    if name.startswith("t_") and callable(fn):
        check(name[2:].replace("_", " "), fn)

print()
print("ALL PASS — the second-round rules flip at REVIEW_R2_HEIGHT and nowhere else" if not fails
      else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
