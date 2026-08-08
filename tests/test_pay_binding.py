"""Binding a contract PAYOUT from the proof's own io log, instead of refusing the whole span.

WHY IT EXISTS. A `PAY` opcode moves bridge balances, and a payout is an EXECUTION outcome — it never appears
in the calldata. `block_records_effects` runs at incorporate time on a node that does not execute contracts,
so it is structurally blind to it, and the settle verifier has always refused any span whose io contained a
PAY:

    assert int(_e[0]) != _zkvm.IO_PAY, "settle-with-proof io contains a PAY (moves RECORDS, ...)"

That refusal is correct for a records-FROZEN proof, which pins one records root across the span. It is
unnecessary for a records-BOUND proof, where records are allowed to move and every effect is checked
against this node's own derivation.

WHAT MAKES THE DERIVATION SOUND — the three things these checks pin:

  1. The io log is not the prover's word: the STARK commits to it, and settlement_proofs._run_call raises on
     revert/bad payout under the SAME rules the live path applies. A valid proof therefore already
     establishes the payout was affordable and applied.
  2. The payee resolves through a registry rebuilt from the segment's OWN committed calls. The prover starts
     from an empty registry and accumulates only within the span, so this resolves exactly what the prover
     could — never more (no trusting a supplied address) and never less (it cannot refuse an honest proof).
  3. Every payout produces the exact pair execnode/state.py writes: bridge[cid] -= amt, bridge[to] += amt.

Anything it cannot fully account for must FAIL CLOSED and keep riding the bonded quorum — a partially
derived effect set would let a prover settle a root that silently omits the rest, which is the precise
failure block_records_inert exists to prevent.

Run: python3 tests/test_pay_binding.py
"""
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import protocol                                                        # noqa: E402
from execnode import runtimes as RT, zkvm as Z                         # noqa: E402
from execnode import exec_root as ER                                   # noqa: E402
from execnode.stark import records_bind as RB                          # noqa: E402

fails = 0

CID = "c0ffee00000000000000000000000000000000000000ab"
PAYER = "1111111111111111111111111111111111111111111111"
PAYEE = "2222222222222222222222222222222222222222222222"
OTHER = "3333333333333333333333333333333333333333333333"


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


def seg(calls, io):
    return {"calls": calls, "io": [list(e) for e in io]}


def call(cid=CID, caller=PAYER, args=(PAYEE,)):
    return {"cid": cid, "method": "m", "caller": caller, "args": list(args)}


def dg(addr):
    """The digest the zkVM sees for an address — the SAME function the runtime registers."""
    return RT.zkvm_addr_digest(addr)


# ---- the happy path -------------------------------------------------------------------------------------

def t_a_payout_derives_the_pair_state_writes():
    fx = RB.pay_effects_from_segment(seg([call()], [(Z.IO_PAY, dg(PAYEE), 700), (Z.IO_RET, 0, 0)]))
    assert (ER.T_BRIDGE_BAL, (CID,), -700) in fx, f"the contract must be debited: {fx}"
    assert (ER.T_BRIDGE_BAL, (PAYEE,), 700) in fx, f"the payee must be credited: {fx}"
    assert len(fx) == 2, f"exactly one pair per payout: {fx}"


def t_the_payee_is_resolved_not_trusted():
    """The io log carries a DIGEST, never an address. A digest the span's calls never registered must not
    resolve — the prover could not resolve it either, so refusing costs nothing and trusting would."""
    try:
        RB.pay_effects_from_segment(seg([call(args=())],                       # OTHER never registered
                                        [(Z.IO_PAY, dg(OTHER), 5), (Z.IO_RET, 0, 0)]))
    except RB.Unbindable:
        return
    raise AssertionError("an unregistered payee digest must not resolve")


def t_the_caller_is_registered_too():
    """zkvm_statement registers the caller as well as string args, so a contract may pay its caller."""
    fx = RB.pay_effects_from_segment(seg([call(args=())],
                                         [(Z.IO_PAY, dg(PAYER), 42), (Z.IO_RET, 0, 0)]))
    assert (ER.T_BRIDGE_BAL, (PAYER,), 42) in fx, f"the caller must resolve: {fx}"


def t_several_calls_attribute_to_their_own_contract():
    """Attribution comes from the io log's own structure: one RET-terminated chunk per call, in order."""
    c1, c2 = call(cid="aaa"), call(cid="bbb")
    fx = RB.pay_effects_from_segment(seg([c1, c2], [
        (Z.IO_PAY, dg(PAYEE), 10), (Z.IO_RET, 0, 0),
        (Z.IO_PAY, dg(PAYEE), 25), (Z.IO_RET, 0, 0)]))
    assert (ER.T_BRIDGE_BAL, ("aaa",), -10) in fx, f"first payout belongs to aaa: {fx}"
    assert (ER.T_BRIDGE_BAL, ("bbb",), -25) in fx, f"second payout belongs to bbb: {fx}"


def t_a_span_with_no_payout_derives_nothing():
    assert RB.pay_effects_from_segment(seg([call()], [(Z.IO_RET, 0, 0)])) == []


# ---- fail closed ----------------------------------------------------------------------------------------

def t_a_ret_split_that_does_not_match_the_calls_is_refused():
    """If the chunk count and the call count disagree, attribution is a guess — and a guess here debits the
    wrong contract."""
    try:
        RB.pay_effects_from_segment(seg([call(), call()],                      # two calls, ONE log
                                        [(Z.IO_PAY, dg(PAYEE), 1), (Z.IO_RET, 0, 0)]))
    except RB.Unbindable:
        return
    raise AssertionError("a mismatched RET split must be refused")


def t_a_trailing_unterminated_log_is_refused():
    try:
        RB.pay_effects_from_segment(seg([call()], [(Z.IO_PAY, dg(PAYEE), 1)]))  # no RET
    except RB.Unbindable:
        return
    raise AssertionError("an unterminated io log must be refused")


def t_an_asset_payout_refuses_the_span():
    """The asset ledger is not part of the records projection this module derives. Half-deriving it would
    let a prover settle a root that silently omits the rest — the same fail-closed rule
    block_records_effects already applies."""
    try:
        RB.pay_effects_from_segment(seg([call()], [
            (Z.IO_ASEL, 7, 0), (Z.IO_PAY, dg(PAYEE), 3), (Z.IO_RET, 0, 0)]))
    except RB.Unbindable:
        return
    raise AssertionError("an asset-denominated payout must refuse the span")


def t_a_segment_call_without_a_cid_is_refused():
    try:
        RB.pay_effects_from_segment(seg([{"method": "m", "caller": PAYER, "args": [PAYEE]}],
                                        [(Z.IO_PAY, dg(PAYEE), 1), (Z.IO_RET, 0, 0)]))
    except RB.Unbindable:
        return
    raise AssertionError("no cid means nothing to debit — refuse")


# ---- the consensus switch -------------------------------------------------------------------------------

def t_there_is_no_switch_to_forget():
    """It ships unconditional. A dormant flag is a second code path nobody exercises, and this one was
    introduced at the only moment enabling it is free: every settle-prove on alphanet-16 has run with
    calls=0, so no span on chain contains a payout for a mixed fleet to disagree about."""
    src = open(os.path.join(ROOT, "protocol.py")).read()
    assert "SETTLE_PROOF_RECORDS_PAY = False" not in src, "no off-by-default switch"
    assert "SETTLE_PROOF_RECORDS_PAY = True" not in src, "and no switch at all"
    rb = open(os.path.join(ROOT, "execnode/stark/records_bind.py")).read()
    assert "_PAY_BINDING" not in rb, "the flag reader must be gone too"


def t_the_registry_is_shared_across_a_proofs_segments():
    """Span-wide accumulation, matching the prover's single dry-run. It cannot admit a payout the prover
    rejected: prove_epoch resets its registry per segment, so a payee resolvable only via an earlier
    segment makes split_io return None and the whole prove fail — there is no such proof to verify."""
    a = seg([call(args=(PAYEE,))], [(Z.IO_RET, 0, 0)])              # registers PAYEE, pays nothing
    b = seg([call(args=())], [(Z.IO_PAY, dg(PAYEE), 9), (Z.IO_RET, 0, 0)])   # pays it in a LATER segment
    fx = RB.pay_effects_from_proof({"segments": [a, b]})
    assert (ER.T_BRIDGE_BAL, (PAYEE,), 9) in fx, f"the shared registry must resolve it: {fx}"


def t_the_prover_derives_the_same_shape():
    """The prover's half must produce the same (tag, parts, delta) triples, or the records half it proves
    is missing exactly what the verifier derives and can never bind."""
    from execnode import settlement_proofs as SP
    assert callable(SP.span_payout_effects), "the prover needs its own derivation"
    src = open(os.path.join(ROOT, "execnode/settlement_proofs.py")).read()
    seg_src = src[src.index("def span_payout_effects"):src.index("def prove_epoch")]
    assert "_run_call" in seg_src, "it must drive the SAME runner, not a reimplementation"
    assert "T_BRIDGE_BAL" in seg_src, "and emit the same records positions"
    ex = open(os.path.join(ROOT, "execnode/execnode.py")).read()
    assert "SP.span_payout_effects(" in ex, "the records half must actually include them"


def t_a_frozen_records_proof_still_refuses_a_pay():
    """The refusal is still right where records are PINNED across the span: a payout inside one would make
    the proof assert something false."""
    src = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
    # There are TWO `if not _records_bound:` blocks (the epoch-boundary assert comes first), so anchor on
    # the one that actually guards the PAY scan rather than on whichever appears earliest.
    i = src.rindex("if not _records_bound:", 0, src.index("IO_PAY"))
    seg_src = src[i:i + 600]
    assert "IO_PAY" in seg_src, "the frozen path must still scan for a PAY"
    assert "assert int(_e[0]) != _zkvm.IO_PAY" in seg_src, "and still refuse it"


def t_the_derivation_runs_only_after_the_calldata_binding():
    """The registry is rebuilt from the segment's calls, so those calls must first have been bound to this
    node's committed summaries — otherwise the io log's provenance means nothing."""
    src = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
    i_bind = src.index("Settle proof not bound to the on-chain calldata")
    # Match the CALL, not the name: the comment above the frozen-path guard mentions the function too, and
    # anchoring on the bare name silently compared against a comment.
    i_pay = src.index("_RBP.pay_effects_from_proof(proof)")
    assert i_bind < i_pay, "payout derivation must come AFTER the calldata binding"


for nm, fn in [("a payout derives the pair state writes", t_a_payout_derives_the_pair_state_writes),
               ("the payee is resolved, not trusted", t_the_payee_is_resolved_not_trusted),
               ("the caller is registered too", t_the_caller_is_registered_too),
               ("several calls attribute to their own contract", t_several_calls_attribute_to_their_own_contract),
               ("a span with no payout derives nothing", t_a_span_with_no_payout_derives_nothing),
               ("a mismatched RET split is refused", t_a_ret_split_that_does_not_match_the_calls_is_refused),
               ("an unterminated log is refused", t_a_trailing_unterminated_log_is_refused),
               ("an asset payout refuses the span", t_an_asset_payout_refuses_the_span),
               ("a call without a cid is refused", t_a_segment_call_without_a_cid_is_refused),
               ("there is no switch to forget", t_there_is_no_switch_to_forget),
               ("registry shared across a proof's segments", t_the_registry_is_shared_across_a_proofs_segments),
               ("the prover derives the same shape", t_the_prover_derives_the_same_shape),
               ("a frozen records proof still refuses a PAY", t_a_frozen_records_proof_still_refuses_a_pay),
               ("derivation runs after the calldata binding", t_the_derivation_runs_only_after_the_calldata_binding)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
