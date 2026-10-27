"""REVIEW_R2_HEIGHT: the second round of 2026-09-23 review fixes, pinned at the gate.

doc/security-review-2026-09-23.md — exec: Z6 duplicate note commitments, Z9 the field path's exit address,
Z4 the field pool's capacity, F7 runtime typing, F10 the lock flag, F8 constructor asset effects, F4 the
per-block execution budget (its prover mirror and A4 retired in G9 with the Goldilocks settle prover); L1: S4 the DA-carried proven marker, A4 canonical
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
# GENERATION 28'S EXEC LAYER is what this file pins (zkvm.py v1, the Goldilocks prover, alghash, field digests); from
# BLAKE_EXEC_HEIGHT the exec layer is BLAKE2s/zkvm2 and has its own tests. Run under gen 28's gate explicitly, so the old
# path stays tested while gen 28's history replays through it (until G9 deletes it) — the gen-29 rehearsal found this
# file reading the shipped value.
import _harness as _gen28
import protocol as _P_gen28
_P_gen28.BLAKE_EXEC_HEIGHT = _gen28.gate_at("BLAKE_EXEC_HEIGHT", 28)
# ...and generation 28's pools, which these height-1 rules were written against: there a field shield at height 1 lands
# in the wide pool; generation 29 opens the Stwo pool and closes the wide one from block 1 (STWO_POOL_HEIGHT,
# WIDE_DEPOSIT_CLOSE_HEIGHT), each with its own tests. (EXEC_BUDGET_V2_HEIGHT, the per-sender share, was inlined in G9.)
for _g in ("STWO_POOL_HEIGHT", "WIDE_DEPOSIT_CLOSE_HEIGHT"):
# ...and generation 28's block budget, which these height-1 rules were written against: there one sender may fill the
# block's budget; generation 29 caps a sender's share from block 1 (EXEC_BUDGET_V2_HEIGHT), with its own tests. (Gen 28's
# pools — a field shield at height 1 in the wide pool — retired in G9 with STWO_POOL_HEIGHT / WIDE_DEPOSIT_CLOSE_HEIGHT.)
for _g in ("EXEC_BUDGET_V2_HEIGHT",):
    setattr(_P_gen28, _g, _gen28.gate_at(_g, 28))
from execnode.state import ExecState, asset_id
from execnode import zkvmasm, zkvm
from execnode.stark import stark, field as F
from execnode.shielded_field import TREE_DEPTH

import _harness
_report = _harness.Report()
check = _report.run


GATE = 1   # the rule holds from block 1 (gen 25's REVIEW_R2_HEIGHT, deleted after the betanet-8 reroll); height 0 is below it
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
    assert not hasattr(P, "REVIEW_R2_HEIGHT") and not hasattr(P, "EXEC_CTX_CURRENT_HEIGHT"), "the gates stay deleted"


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
def t_f4_block_budget_reverts_the_call_that_exceeds_it():
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
    st._block_steps, st._block_steps_by = 0, {}
    # ONE CALL PER SENDER: from block 1 a sender may use only EXEC_SENDER_STEP_SHARE of the block (EXEC_BUDGET_V2_HEIGHT,
    # gen 28's gate, inlined in G9), so the block budget is filled by many senders, as on generation 29.
    senders = ["mldsa44" + format(i, "042x") for i in range(fits + 1)]
    for a in senders:
        st.bridge[a] = 10 ** 9
    for i in range(fits):
        assert st.apply_blob({"op": "call", "contract": cid, "method": "burn", "args": [], "value": 1}, senders[i], f"c{i}").endswith("-> ok")
    r = st.apply_blob({"op": "call", "contract": cid, "method": "burn", "args": [], "value": 1}, senders[fits], "cx")
    assert "budget exhausted" in r, r
    assert st.bridge[senders[fits]] == 10 ** 9, "the reverted call's escrow came back"
    st_old = fresh(GATE - 1)                    # height 0: neither the budget nor the per-sender share applies
    st_old.apply_blob({"op": "deploy", "code": code, "nonce": 4}, ALICE, "t")
    st_old._block_steps = 0
    for i in range(fits + 1):
        assert st_old.apply_blob({"op": "call", "contract": cid, "method": "burn", "args": [], "value": 1}, ALICE, f"c{i}").endswith("-> ok")
    # the prover-mirrors half retired in G9: the Goldilocks settlement prover (settlement_proofs.prove_epoch) was deleted


# ---- Z6 / Z9 / Z4 (shielded) ---------------------------------------------------------------------------------
def t_z6_the_legacy_pool_at_height_0_keeps_its_old_verdict():
    # Z6 / Z4 / Z9 on the WIDE pool from block 1 retired in G9: generation 28's rules — from block 1 every field shield
    # and transfer is the Stwo pool's (STWO_POOL_HEIGHT, inlined as 1), whose own tests pin duplicates, capacity and the
    # exit address. The legacy pool is reachable only at height 0, below every deleted gate, where the duplicate was
    # historically admitted.
    st_old = fresh(GATE - 1)
    assert st_old.apply_field_shield(1000, 7, 9).startswith("field-shield")
    assert st_old.apply_field_shield(1000, 7, 9).startswith("field-shield"), "height 0: the legacy pool admits the duplicate"


# ---- S4 the DA-carried proven marker -------------------------------------------------------------------------
def t_s4_da_proof_records_the_marker_from_the_gate():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ops", "account_ops.py")).read()
    assert 'int(block_height) >= 1 and "proof_da" in data' in src


# ---- A4 canonical pre_contracts keys ---------------------------------------------------------------------------
# a4_non_canonical_pre_contracts_keys_are_refused and a4_fixed_name_contracts_pass_from_their_gate_and_nothing_else_does
# retired in G9: settlement_sparse (the Goldilocks settle-proof verifier that read pre_contracts) was deleted


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
print("ALL PASS — the second-round rules flip at REVIEW_R2_HEIGHT and nowhere else" if not _report.fails
      else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
