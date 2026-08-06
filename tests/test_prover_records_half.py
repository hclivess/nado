"""The prover must ATTACH a records half, and must attach nothing when the span did not move one.

THE PRODUCER WAS THE MISSING PIECE. records_transition.py has existed for weeks, ops/transaction_ops.py
verifies proof["records"], and three test files cover it — but NOTHING under execnode/ ever SET it. The
production prover only ever PINNED a records root, which is why the exec node skipped every span whose
records moved before it ever proved anything. Flipping SETTLE_PROOF_RECORDS_VALUE_CALLS without this would
have changed what L1 derives, spent a genesis, and unblocked nothing.

WHAT THE VERIFIER REQUIRES (ops/transaction_ops.py, the `_records_bound` branch), and therefore what these
checks pin:
  * proof["records"]     — the transition, whose updates must EQUAL net_records_updates(pre_get, effects)
                           where the effects come from L1's OWN committed summaries, never from the proof;
  * proof["rec_post"]    — the claimed post records root, composed with kv_post into the settle's state_root;
  * proof["records_pre"] — the PRE projection, which pinned_pre_get hashes against the tip's records root so
                           every value the binding arithmetic reads is authenticated.

THE EMPTY-EFFECT TRAP is the one that bites: L1 REQUIRES rec_post == rec_hex when the span committed no
effects, so attaching an empty transition would try to move the half on nobody's authority. The prover must
attach NOTHING in that case and leave the frozen path byte-identical.

Run: python3 tests/test_prover_records_half.py
"""
import ast
import importlib
import os
import re
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SRC = open(os.path.join(ROOT, "execnode", "execnode.py")).read()
TREE = ast.parse(SRC)

fails = 0


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


def _fn(name):
    for n in ast.walk(TREE):
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name:
            return n
    raise AssertionError(f"{name} not found")


def t_builder_exists_and_is_awaited():
    f = _fn("_build_records_half")
    assert isinstance(f, ast.AsyncFunctionDef), "it performs L1 fetches, so it must be async"
    assert "await _build_records_half(" in SRC, "the settle path must AWAIT it, not schedule it"


def t_all_three_verifier_fields_are_attached():
    assert 'proof["records"], proof["rec_post"], proof["records_pre"]' in SRC, \
        "all three fields the verifier reads must be set together — two of three binds nothing"


def t_attach_is_conditional_the_empty_case_stays_frozen():
    """L1 requires rec_post == rec_hex for a span with no effects. Attaching an empty transition would move
    the half on nobody's authority, so the frozen path must stay byte-identical."""
    assert "if _records_half is not None:" in SRC, "the attach must be conditional"
    body = SRC[SRC.index("async def _build_records_half"):SRC.index("async def _build_settlement_proof")]
    assert "if not effects:" in body, "an empty effect set must return None, not an empty transition"
    assert "if not net:" in body, "effects that net to nothing must also return None"


def t_pre_root_is_the_tip_root_not_the_post_root():
    """pre_full = rnode(kv_pre, rec_hex) must equal L1's JUSTIFIED root, which was composed with the records
    half AT sc. Writing digest_hex(rec_root) was only safe while the skip forced the two to be equal."""
    assert "rec_hex = SST.digest_hex(rec_pre_root)" in SRC, \
        "rec_hex must be the PRE records root once the two can differ"
    # LINE-ANCHORED, not a substring: `_rec_hex = SST.digest_hex(rec_root)` is a DIFFERENT local used only
    # in the self-check failure message, and a naive `in SRC` matched inside it. Fourth checker today that
    # was wrong before the code was.
    import re as _re
    bad = [l for l in SRC.splitlines() if _re.match(r"\s*rec_hex\s*=\s*SST\.digest_hex\(rec_root\)", l)]
    assert not bad, f"the old POST-root assignment would break pre_full the moment records move: {bad}"


def t_derivation_is_checked_against_our_own_apply():
    """If the derived effects do not land on the records root we captured at `cur`, our derivation
    disagrees with our own apply — refuse locally rather than make every peer pay to verify a proof that
    can only fail to bind."""
    assert "records-derivation-mismatch" in SRC, \
        "a derivation that disagrees with our apply must be caught before posting"


def t_accrual_inputs_come_from_l1_not_the_proof():
    """records_bind's header: the exec node reads these over an UNAUTHENTICATED HTTP hop, so a verifier
    trusting the proof's copy would be trusting the prover's HTTP client. The prover must read them from L1
    and fail closed when they are unavailable."""
    body = SRC[SRC.index("async def _build_records_half"):SRC.index("async def _build_settlement_proof")]
    assert "/get_dividend_inflow?epoch=" in body and "/get_open_weights?epoch=" in body, \
        "accrual inputs must be fetched from L1"
    assert 'ow.get("error")' in body, "a refused weights_at_epoch (pruned recerts) must fail closed"


def t_no_post_state_is_materialised():
    """The KV half never materialises a post-state either — it derives the post from the pre by executing.
    Using a live post-state here would reintroduce the PRE MISMATCH trap records_root_from_snapshot
    documents, because `st` keeps mutating throughout the prove."""
    body = SRC[SRC.index("async def _build_records_half"):SRC.index("async def _build_settlement_proof")]
    assert "prove_records_transition" not in body, \
        "the pre/post-state wrapper takes a POST state; build from the store + derived updates instead"
    assert "SX.prove_transition(store" in body, "prove from the PRE store plus the derived updates"


def t_projection_is_computed_once():
    """Computing records_projection inside pre_get rebuilt the whole ~118k-entry map on EVERY record
    lookup — quadratic, in the prove's critical path."""
    body = SRC[SRC.index("async def _build_records_half"):SRC.index("async def _build_settlement_proof")]
    assert body.count("_ER.records_projection(pre_view)") == 1, \
        f"records_projection must be computed once, found {body.count('_ER.records_projection(pre_view)')}"


def t_the_prover_derives_THE_SAME_WAY_L1_DOES():
    """THE MISMATCH THAT WOULD HAVE MADE THE REROLL DELIVER NOTHING, caught by exercising the live path.

    L1 builds `records_out` by concatenating the per-block `rec` lists its exec summaries stored, and those
    come from records_bind.block_records_effects. The prover was using records_bind.span_effects — and the
    two DO NOT derive the same thing. Measured on a single value call with the flag on:

        block_records_effects -> [(T_BRIDGE_BAL, sender, -1000), (T_BRIDGE_BAL, cid, +1000)]
        span_effects          -> []

    span_effects walks RESERVED RECIPIENTS (bridge deposit, faucet, treasury) and accruals; a contract call
    is a `blob`, which it contributes nothing for. So a prover using it would omit every value-call escrow,
    and bind_and_verify_records — which requires tr["updates"] to EQUAL the derived set — would refuse the
    proof every time. The reroll would have shipped and unblocked nothing.

    The prover must walk the span's BLOCKS and call block_records_effects on each, appending the dividend
    accrual on a boundary block exactly where core_loop appends it."""
    body = SRC[SRC.index("async def _build_records_half"):SRC.index("async def _build_settlement_proof")]
    assert "RB.block_records_effects(" in body, \
        "the prover must derive per block via block_records_effects — the same function L1 uses"
    assert "RB.span_effects(" not in body, \
        "span_effects does NOT derive value-call escrows; using it silently omits them"
    assert "RB.dividend_accrual_effects(" in body, "the boundary accrual must be appended per block"
    assert "if not _derivable:" in body, \
        "a non-derivable block must end the span, matching L1's rd!=1 refusal"


def t_every_symbol_the_builder_calls_actually_EXISTS():
    """THE CHECK THAT WAS MISSING, and it cost a live failure.

    _build_records_half calls RB.epoch_accrual_due, which lived only on the reroll BRANCH — main's
    records_bind.py never had it. Every attempt therefore died on
    `AttributeError: module 'execnode.stark.records_bind' has no attribute 'epoch_accrual_due'`,
    caught by the builder's own except and reported as "records half FAILED … — quorum". It failed CLOSED,
    so nothing was ever at risk, but the feature was DEAD on main while being reported as live.

    Every other check in this file is textual — it reads the source as a string and never imports anything,
    so a name that does not resolve is invisible to all of them. RESOLVE THE NAMES."""
    import importlib
    RB = importlib.import_module("execnode.stark.records_bind")
    body = SRC[SRC.index("async def _build_records_half"):SRC.index("async def _build_settlement_proof")]
    called = sorted(set(re.findall(r"\bRB\.([A-Za-z_][A-Za-z0-9_]*)", body)))
    assert called, "expected the builder to call into records_bind"
    missing = [n for n in called if not hasattr(RB, n)]
    assert not missing, f"_build_records_half calls records_bind.{missing} which do not exist"
    for mod_alias, mod_name in (("SX", "execnode.stark.state_transition"),
                                ("_SST", "execnode.stark.storage_tree"),
                                ("_ER", "execnode.exec_root")):
        m = importlib.import_module(mod_name)
        names = sorted(set(re.findall(r"\b" + mod_alias + r"\.([A-Za-z_][A-Za-z0-9_]*)", body)))
        gone = [n for n in names if not hasattr(m, n)]
        assert not gone, f"_build_records_half calls {mod_name}.{gone} which do not exist"


def t_epoch_skip_is_GONE_now_that_the_derivation_ships():
    """It was the single largest refusal class — 55 of 146 over one measured day — and it existed only
    because the presence-dividend accrual was INVISIBLE (no transaction behind it), not because it was
    unprovable. With the accrual derived at incorporate time, reproduced per block by the prover, and L1's
    epoch assert made conditional on the records binding, refusing every boundary span on sight would throw
    away exactly what the reroll bought.

    This check INVERTED at the alphanet-16 cutover. It previously pinned the skip in place, deliberately,
    so it could not be dropped before the derivation shipped — dropping it early produces proofs L1 refuses,
    because L1 would mark a boundary block derivable with the accrual MISSING."""
    assert "crosses a dividend epoch boundary" not in SRC, \
        "the blanket epoch-boundary skip must be gone now that the accrual is derived"
    assert "epoch_accrual_due" in open(os.path.join(ROOT, "loops", "core_loop.py")).read(), \
        "L1 must derive the accrual at incorporate time, or the prover's version cannot bind"
    tx = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
    assert "if not _records_bound:" in tx, \
        "L1's epoch assert must be conditional on the records binding"


for nm, fn in [("the builder exists and is awaited", t_builder_exists_and_is_awaited),
               ("all three verifier fields are attached together", t_all_three_verifier_fields_are_attached),
               ("attach is conditional; the empty case stays frozen", t_attach_is_conditional_the_empty_case_stays_frozen),
               ("rec_hex is the PRE root, not the post root", t_pre_root_is_the_tip_root_not_the_post_root),
               ("the derivation is checked against our own apply", t_derivation_is_checked_against_our_own_apply),
               ("accrual inputs come from L1, not the proof", t_accrual_inputs_come_from_l1_not_the_proof),
               ("no post-state is materialised", t_no_post_state_is_materialised),
               ("the projection is computed once", t_projection_is_computed_once),
               ("the prover derives the same way L1 does", t_the_prover_derives_THE_SAME_WAY_L1_DOES),
               ("every symbol the builder calls actually exists", t_every_symbol_the_builder_calls_actually_EXISTS),
               ("the epoch skip is gone now that the derivation ships", t_epoch_skip_is_GONE_now_that_the_derivation_ships)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
