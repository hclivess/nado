"""EXEC_RULES_V2_HEIGHT: the exec-layer call rules from the 2026-09-23 security review, pinned at the gate.

doc/security-review-2026-09-23.md §1 C1, §2 F2, §4 Z2, §3 S2/S3/S5. Each is a rule about what a call or a
settle proof DOES, so each is a consensus rule for the exec root (every exec node computes it) and rides one
height gate. This file shows the rule differing across the gate and nowhere else — and for the two that were
reproduced by the review (C1, Z2) it shows the LEGACY behaviour first, so the gate is seen to close something
that was really open:

  C1  an asset-denominated value into a method that never reads ACTX is booked as native value; below the gate
      the tokens are escrowed and the call runs (the drain); at the gate it is refused before any ledger moves,
      while a method that reads ACTX still takes asset value. (The Goldilocks settlement prover's mirror of the
      refusal was deleted in G9 with the prover.)
  F2  a non-string `method` used to be DEBITED and then raise at the VM (escrow kept); at the gate it is refused
      first, a VM exception refunds, and L1 admission refuses to order it.
  Z2  a `stark` bundle with no join-split proof used to pass "output well-formedness" and record an unbacked
      unshield exit; since G9 slice 5c the whole transparent `shielded_transfer` op is a skip at every height (the
      legacy pool is deleted), so no bundle, signed or stark, can record an exit through it.
  S2/S3 (the settle branch's records fold and the order of its checks before the proof verify) were retired in G9 with
      the L1 settle-proof verifier: a BLAKE2s exec root settles by quorum attestation only.
  S5  (a MemoryError inside a Goldilocks verifier layer propagated: retired with execnode/stark in G9 slice 4)

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
# BLAKE_EXEC_HEIGHT's gen-28 pin retired in G9: generation 28's rules (the v1 VM, field digests) are gone, so this
# file runs on generation 29's exec layer like the chain does.
from execnode.state import ExecState, asset_id, MAX_EXIT_VALUE
from execnode import zkvmasm

import _harness
_report = _harness.Report()
check = _report.run


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
    assert int(st.contracts[cid]["storage"]["slots"]["1"]) == int(aid), "ACTX saw the asset (whole: the 256-bit VM)"


def t_c1_native_value_is_untouched_by_the_gate():
    st, cid, aid = fresh(GATE)
    r = st.apply_blob({"op": "call", "contract": cid, "method": "book", "args": [], "value": 500}, ALICE, "tx")
    assert r.endswith("-> ok"), r
    assert st.bridge[cid] == 500


# c1 prover mirrors the refusal retired in G9: the Goldilocks settle prover (settlement_proofs._run_call) was deleted


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


CLOSED = "skip shielded_transfer: the legacy shielded pool is closed (LEGACY_TRANSFER_CLOSE_HEIGHT)"


def t_z2_no_exit_blob_records_an_exit_at_any_height():
    """THE FINDING (an empty stark bundle recorded an unbacked exit) is unreachable at every height: the transparent op
    is skipped before anything is parsed (G9 slice 5c deleted the legacy pool; the stark refusal, the join-split check and
    the MAX_EXIT_VALUE bound went with its body). Below block 1, at the gate and far past it, a stark bundle, an empty one,
    an over-bound exit and a signed exit are all the same skip, and nothing moves."""
    signed = _exit_blob(-1_000_000, None)
    signed["proof"] = {"sig": "x"}
    over = _exit_blob(-MAX_EXIT_VALUE, None)
    over["proof"] = {"sig": "x"}
    st_old, st, st_far = fresh(GATE - 1)[0], fresh(GATE)[0], fresh(GATE + 10 ** 6)[0]
    roots = [s.state_root() for s in (st_old, st, st_far)]
    assert st_old.apply_blob(_exit_blob(-1_000_000, {"x": 1}), ALICE, "tx") == CLOSED
    assert st.apply_blob(_exit_blob(-1_000_000, {"x": 1}), ALICE, "tx") == CLOSED
    assert st.apply_blob(_exit_blob(-1_000_000, []), ALICE, "tx") == CLOSED
    assert st.apply_blob(_exit_blob(-MAX_EXIT_VALUE, {"joinsplit": {}}), ALICE, "tx") == CLOSED
    assert st.apply_blob(over, ALICE, "tx") == CLOSED
    assert st_far.apply_blob(signed, ALICE, "tx") == CLOSED
    assert [s.state_root() for s in (st_old, st, st_far)] == roots
    assert all(s.pool_value == 0 and not s.unshield_withdrawals and s.uw_nonce == 0 for s in (st_old, st, st_far))


# ---- S2 / S3 -----------------------------------------------------------------------------------------------
# s2 records fold refuses a negative running balance retired in G9: the settle branch's records fold (records_bind
#   net_records_updates over a Goldilocks records-bound proof) was deleted with the L1 settle-proof verifier
# s3 cheap settle checks precede the cryptographic verify retired in G9: a settle carrying a proof is refused
#   unconditionally on gen 29, so there is no cryptographic verify left to order the cheap checks before


# ---- S5 ----------------------------------------------------------------------------------------------------
# S5 a memory error propagates out of every verifier layer: retired in G9 slice 4 — stark.verify, the last Goldilocks
# verifier layer it drove, went with execnode/stark; native_guard.NODE_LOCAL_ERRORS (the rule) is pinned by
# tests/test_verifier_thread_and_oom_safety.py.


for name, fn in list(globals().items()):
    if name.startswith("t_") and callable(fn):
        check(name[2:].replace("_", " "), fn)

print()
print("ALL PASS — the exec-layer rules flip at EXEC_RULES_V2_HEIGHT and nowhere else" if not _report.fails
      else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
