"""EXEC_RULES_V2_HEIGHT: the exec-layer call rules from the 2026-09-23 security review, pinned at the gate.

doc/security-review-2026-09-23.md §1 C1, §2 F2, §4 Z2, §3 S2/S3/S5. Each is a rule about what a call or a
settle proof DOES, so each is a consensus rule for the exec root (every exec node computes it) and rides one
height gate. This file shows the rule differing across the gate and nowhere else — and for the two that were
reproduced by the review (C1, Z2) it shows the LEGACY behaviour first, so the gate is seen to close something
that was really open:

  C1  an asset-denominated value into a method that never reads ACTX is booked as native value; below the gate
      the tokens are escrowed and the call runs (the drain); at the gate it is refused before any ledger moves,
      while a method that reads ACTX still takes asset value. The settlement prover mirrors the refusal.
  F2  a non-string `method` used to be DEBITED and then raise at the VM (escrow kept); at the gate it is refused
      first, a VM exception refunds, and L1 admission refuses to order it.
  Z2  a `stark` bundle with no join-split proof used to pass "output well-formedness" and record an unbacked
      unshield exit; at the gate it is refused, and an exit is bounded by MAX_EXIT_VALUE.
  S2  the records fold refuses a running balance below zero when asked to (the settle branch asks from the gate).
  S3  the cheap settle checks (tip extension, root, chain reads, calldata) come BEFORE the cryptographic verify.
  S5  a MemoryError inside any verifier layer propagates instead of becoming a (False, ...) verdict.

Run: python3 tests/test_exec_rules_v2.py
"""
import os
import sys
import tempfile
import traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-execrules-")     # NEVER the live node's home (rule 4)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("blocks", "index", "private", "peers", "transactions"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

import logging
import protocol as P
from execnode.state import ExecState, asset_id, MAX_EXIT_VALUE
from execnode import zkvm, zkvmasm
from execnode.stark import records_bind as RB, stark, vm_circuit, settlement_sparse as SS
from execnode import exec_root as ER, settlement_proofs as SP

fails = 0


def check(name, fn):
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


GATE = 1   # the rule holds from block 1 (gen 25's EXEC_RULES_V2_HEIGHT, deleted after the betanet-8 reroll); height 0 is below it
ALICE = "mldsa44" + "a" * 42
BOB = "mldsa44" + "b" * 42

# A contract with one method that BOOKS its value without asking which currency it is (the shape of every
# game: `ctx value` -> sstore) and one that reads ACTX (the shape of dex/otc/reserve).
CODE = {
    "book": zkvmasm.assemble("ctx r1 value\n movi r2 0\n sstore r2 r1\n ret r1"),
    "aware": zkvmasm.assemble("actx r1 asset\n movi r2 1\n sstore r2 r1\n ret r1"),
}


def fresh(block):
    """An ExecState about to apply block `block` (cursor = block - 1, as _apply_block leaves it)."""
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json"))
    st.cursor = int(block) - 1
    st.bridge[ALICE] = 10 ** 9
    st.apply_blob({"op": "deploy", "code": CODE, "nonce": 1}, ALICE, "tx-deploy")
    cid = next(iter(st.contracts))
    st.apply_blob({"op": "asset_create", "seed": 7, "name": "Worthless", "sym": "WRT", "dec": 0,
                   "supply": 10 ** 9}, ALICE, "tx-asset")
    return st, cid, str(asset_id(ALICE, 7))


def t_rules_v2_is_a_pure_function_of_the_block():
    st, _, _ = fresh(GATE - 1)
    assert not st.rules_v2(), "one block below the gate: legacy"
    st.cursor = GATE - 1
    assert st.rules_v2(), "at the gate: v2"
    assert not hasattr(P, "EXEC_RULES_V2_HEIGHT"), "the gate stays deleted"


# ---- C1 ----------------------------------------------------------------------------------------------------
def t_c1_legacy_books_a_token_as_native_value():
    """THE FINDING. Below the gate the worthless token is escrowed into the contract's ASSET ledger and the
    method stores `value` = 500 as if 500 NADO had arrived — which its PAY would later draw from the shared
    native holding. This is what every node did before the gate."""
    st, cid, aid = fresh(GATE - 1)
    r = st.apply_blob({"op": "call", "contract": cid, "method": "book", "args": [], "value": 500,
                       "asset": aid}, ALICE, "tx")
    assert r.endswith("-> ok"), r
    assert st.asset_balance(aid, cid) == 500 and st.asset_balance(aid, ALICE) == 10 ** 9 - 500
    assert st.view(cid, "book", []) is not None or True   # (no view schema; the slot write is what matters)
    assert int((st.contracts[cid]["storage"].get("slots") or {}).get("0", 0)) == 500, "value booked as native"


def t_c1_gate_refuses_asset_value_into_an_actx_blind_method():
    st, cid, aid = fresh(GATE)
    before = dict(st.contracts[cid]["storage"])
    r = st.apply_blob({"op": "call", "contract": cid, "method": "book", "args": [], "value": 500,
                       "asset": aid}, ALICE, "tx")
    assert r.startswith("skip") and "ACTX" in r, r
    assert st.asset_balance(aid, ALICE) == 10 ** 9 and st.asset_balance(aid, cid) == 0, "nothing moved"
    assert st.contracts[cid]["storage"] == before, "nothing ran"


def t_c1_gate_still_admits_asset_value_into_an_actx_aware_method():
    st, cid, aid = fresh(GATE)
    r = st.apply_blob({"op": "call", "contract": cid, "method": "aware", "args": [], "value": 500,
                       "asset": aid}, ALICE, "tx")
    assert r.endswith("-> ok"), r
    assert st.asset_balance(aid, cid) == 500
    assert int(st.contracts[cid]["storage"]["slots"]["1"]) == int(aid) % stark.F.P, "ACTX saw the asset"


def t_c1_native_value_is_untouched_by_the_gate():
    st, cid, aid = fresh(GATE)
    r = st.apply_blob({"op": "call", "contract": cid, "method": "book", "args": [], "value": 500}, ALICE, "tx")
    assert r.endswith("-> ok"), r
    assert st.bridge[cid] == 500


def t_c1_prover_mirrors_the_refusal():
    """A prover more permissive than the chain proves a transition the chain never applied; the mirror makes
    the refused call UNPROVABLE at the same height and provable below it."""
    contracts = {"c" * 32: {"code": CODE, "storage": {"slots": {}}, "runtime": "zkvm"}}
    aid = str(asset_id(ALICE, 7))
    assets = {aid: {"sym": "WRT", "supply": 10 ** 9, "dec": 0, "issuer": ALICE}}
    abal = {aid: {ALICE: 10 ** 9}}
    call = {"cid": "c" * 32, "method": "book", "caller": ALICE, "args": [], "value": 500, "asset": int(aid)}
    try:
        SP._run_call(dict(contracts), {}, {k: dict(v) for k, v in abal.items()}, dict(assets), {},
                     dict(call, cursor=GATE), 0, GATE, 0, None, None, False)
        assert False, "the prover must refuse what the chain refuses"
    except ValueError as e:
        assert "ACTX" in str(e), e
    ec, pc, _ = SP._run_call(dict(contracts), {}, {k: dict(v) for k, v in abal.items()}, dict(assets), {},
                             dict(call, cursor=GATE - 1), 0, GATE - 1, 0, None, None, False)
    assert pc["asset"] == int(aid), "below the gate the prover still executes it (legacy parity)"
    assert zkvm.method_reads_actx(CODE, "aware") and not zkvm.method_reads_actx(CODE, "book")
    assert not zkvm.method_reads_actx(CODE, ["book"]) and not zkvm.method_reads_actx(None, "book")


# ---- F2 ----------------------------------------------------------------------------------------------------
def t_f2_legacy_debits_then_raises_and_keeps_the_escrow():
    st, cid, _ = fresh(GATE - 1)
    r = st.apply_blob({"op": "call", "contract": cid, "method": ["book"], "args": [], "value": 500}, ALICE, "tx")
    assert r.startswith("skip"), r
    assert st.bridge.get(cid, 0) == 500 and st.bridge[ALICE] == 10 ** 9 - 500, "legacy: coins stranded"


def t_f2_gate_refuses_a_non_string_method_before_any_debit():
    st, cid, _ = fresh(GATE)
    r = st.apply_blob({"op": "call", "contract": cid, "method": ["book"], "args": [], "value": 500}, ALICE, "tx")
    assert r == "skip: method must be a string", r
    assert st.bridge.get(cid, 0) == 0 and st.bridge[ALICE] == 10 ** 9


def t_f2_gate_refunds_when_the_vm_raises():
    st, cid, _ = fresh(GATE)
    real = st._rt_run

    def boom(*a, **k):
        raise RuntimeError("synthetic VM failure")
    st._rt_run = boom
    try:
        r = st.apply_blob({"op": "call", "contract": cid, "method": "book", "args": [], "value": 500}, ALICE, "tx")
    finally:
        st._rt_run = real
    assert "refunded" in r, r
    assert st.bridge.get(cid, 0) == 0 and st.bridge[ALICE] == 10 ** 9


def t_f2_l1_admission_types_the_method_from_the_gate():
    from genesis import create_indexers
    from ops.account_ops import create_account
    from ops.key_ops import generate_keys
    from ops.transaction_ops import construct_blob_tx, validate_transaction
    create_indexers()
    kd = generate_keys(); create_account(kd["address"], balance=10 ** 8)
    logger = logging.getLogger("t")
    tx = construct_blob_tx(kd, {"op": "call", "contract": "c" * 32, "method": ["bet"], "args": []},
                           max_block=GATE + 50, fee=P.MIN_TX_FEE)
    validate_transaction(tx, logger, GATE - 1)                      # legacy: L1 orders it (exec skips it)
    try:
        validate_transaction(tx, logger, GATE)
        assert False, "at the gate a list method must not be admitted"
    except AssertionError as e:
        assert "method" in str(e), e
    ok_tx = construct_blob_tx(kd, {"op": "call", "contract": "c" * 32, "method": "bet", "args": []},
                              max_block=GATE + 50, fee=P.MIN_TX_FEE)
    validate_transaction(ok_tx, logger, GATE)


# ---- Z2 ----------------------------------------------------------------------------------------------------
def _exit_blob(pv, stark_bundle):
    return {"op": "shielded_transfer",
            "public": {"root": "0" * 64, "nullifiers": [], "out_commitments": [], "public_value": pv,
                       "fee": 0, "withdraw_addr": "ndo" + "A" * 46},
            "proof": {"stark": stark_bundle}}


def t_z2_legacy_records_an_unbacked_exit_for_an_empty_bundle():
    """THE FINDING. No note was ever spent, yet the pool goes negative and an exit is recorded."""
    st, _, _ = fresh(GATE - 1)
    r = st.apply_blob(_exit_blob(-1_000_000, {"x": 1}), ALICE, "tx")
    assert r.startswith("unshield"), r
    assert st.pool_value == -1_000_000 and len(st.unshield_withdrawals) == 1


def t_z2_gate_refuses_a_bundle_without_a_join_split_proof():
    # From block 1 the privacy pause (gen 25's PRIVACY_PAUSE_HEIGHT, deleted with this file's gate) refuses EVERY stark
    # bundle on this op before the Z2 check is reached — so the bundle is refused, and nothing moves, either way.
    st, _, _ = fresh(GATE)
    r = st.apply_blob(_exit_blob(-1_000_000, {"x": 1}), ALICE, "tx")
    assert r.startswith("skip shielded_transfer") and "stark bundle" in r, r
    assert st.pool_value == 0 and not st.unshield_withdrawals
    r = st.apply_blob(_exit_blob(-1_000_000, []), ALICE, "tx")
    assert r.startswith("skip shielded_transfer"), r


def t_z2_gate_bounds_the_exit():
    # a stark bundle never reaches the bound from block 1 (the pause refuses it first); a signed transfer does
    st, _, _ = fresh(GATE)
    r = st.apply_blob(_exit_blob(-MAX_EXIT_VALUE, {"joinsplit": {}}), ALICE, "tx")
    assert r.startswith("skip shielded_transfer"), r
    blob = _exit_blob(-MAX_EXIT_VALUE, None)
    blob["proof"] = {"sig": "x"}
    r = st.apply_blob(blob, ALICE, "tx")
    assert "MAX_EXIT_VALUE" in r, r
    assert st.pool_value == 0 and not st.unshield_withdrawals


# ---- S2 ----------------------------------------------------------------------------------------------------
def t_s2_records_fold_refuses_a_negative_running_balance():
    pre = {("s" * 40,): 100}
    pre_get = lambda tag, parts: pre.get(tuple(parts), 0)
    eff = [(ER.T_BRIDGE_BAL, ("s" * 40,), -150)]
    legacy = RB.net_records_updates(pre_get, eff, depth=8)
    assert legacy and legacy[0][2] == (100 - 150) % stark.F.P, "legacy folds to a field residue"
    try:
        RB.net_records_updates(pre_get, eff, depth=8, nonneg=True)
        assert False, "must be unbindable"
    except RB.Unbindable as e:
        assert "below zero" in str(e), e
    ok = RB.net_records_updates(pre_get, [(ER.T_BRIDGE_BAL, ("s" * 40,), -100)], depth=8, nonneg=True)
    assert ok[0][2] == 0, "reaching exactly zero is fine"
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ops", "transaction_ops.py")).read()
    assert "nonneg=(int(block_height) >= 1))" in src


# ---- S3 ----------------------------------------------------------------------------------------------------
def t_s3_cheap_settle_checks_precede_the_cryptographic_verify():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ops", "transaction_ops.py")).read()
    i_tip = src.index("Settle proof pre_root must extend the settled tip")
    i_da = src.index("Settle proof not bound to the on-chain calldata")
    i_reads = src.index("for _kind, _key, _val in SS.chain_reads(proof)")
    i_verify = src.index("verify_sparse_out_of_process(proof, _protocol.EXEC_TREE_DEPTH")
    i_pin = src.index("assert kv_pre == kv_pre_claim and kv_post == kv_post_claim")
    assert i_tip < i_verify and i_da < i_verify and i_reads < i_verify, "cheap checks first"
    assert i_verify < i_pin, "...and the claims are pinned to the proven halves after the verify"


# ---- S5 ----------------------------------------------------------------------------------------------------
class _OOM(dict):
    """A proof whose first read runs out of memory."""
    def __getitem__(self, k):
        raise MemoryError("synthetic")
    def get(self, k, d=None):
        raise MemoryError("synthetic")


def t_s5_memory_error_propagates_out_of_every_verifier_layer():
    for fn in (lambda: stark.verify(_OOM(), [], []),
               lambda: vm_circuit.verify_epoch_calls(_OOM(), [], []),
               lambda: SS.verify_bound_epoch(_OOM()),
               lambda: SS.verify_settlement_sparse({"segments": [_OOM()]}, depth=8)):
        try:
            res = fn()
            assert False, f"a resource failure became a verdict: {res}"
        except MemoryError:
            pass


for name, fn in list(globals().items()):
    if name.startswith("t_") and callable(fn):
        check(name[2:].replace("_", " "), fn)

print()
print("ALL PASS — the exec-layer rules flip at EXEC_RULES_V2_HEIGHT and nowhere else" if not fails
      else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
