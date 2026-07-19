"""
Prune-safe settle-with-proof binding (execnode/stark/calls_commit.py, ops/kv_ops.exec_summary_*).

The old DA binding re-read every block BODY in the settled span. Bodies are node-local prunable AND are
wiped wholesale by a snapshot re-anchor, so the same settle tx validated differently across the fleet ->
consensus fork. The binding now reads per-block EXEC SUMMARIES derived at incorporate time and stored in the
KV store, which pruning never touches.

Two properties are load-bearing and both are asserted here:
  1. EQUIVALENCE — folding the persisted leaves gives EXACTLY the commitment the body-based
     da_calls_commitment gives. If this ever drifts, the binding silently accepts fabricated calls.
  2. FAIL-CLOSED — a missing summary, a records-moving block, a tampered commitment, an over-long span or
     an uncovered span are all REFUSED. A missing summary must never read as "this block had no calls".

Run: python3 tests/test_exec_summary_binding.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import calls_commit as CC, field as F, alghash

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def call_tx(sender="ndoA", cid="c1", method="m", args=(1, 2), value=0, ns=None):
    """A `blob` tx carrying an op=='call' payload, in the shape apply_blob / block_calls read."""
    d = {"op": "call", "contract": cid, "method": method, "args": list(args), "value": value}
    if ns is not None:
        d["ns"] = ns
    return {"recipient": "blob", "sender": sender, "data": d}


def block(txs, number=10, ts=1234):
    return {"block_number": number, "block_timestamp": ts, "block_transactions": list(txs)}


# ---------------------------------------------------------------- 1. equivalence

def t_fold_matches_body_commitment():
    """THE load-bearing invariant: folding persisted leaves == the body-derived da_calls_commitment."""
    blk = block([call_tx(cid="a", method="foo"), call_tx(sender="ndoB", cid="b", method="bar", args=(7,))])
    _inert, calls_by_ns = CC.block_summary(blk)
    from_summary = CC.fold_leaves(alghash.IV, calls_by_ns.get("default", []))
    from_body = CC.da_calls_commitment([blk], "default")
    assert from_summary == from_body, f"summary fold {from_summary} != body fold {from_body}"


def t_fold_matches_across_multiple_blocks():
    """The chain composes across blocks exactly as the body-based fold does (order-sensitive)."""
    b1 = block([call_tx(cid="a", method="one")], number=10)
    b2 = block([call_tx(cid="b", method="two")], number=11)
    node = alghash.IV
    for b in (b1, b2):
        node = CC.fold_leaves(node, CC.block_summary(b)[1].get("default", []))
    assert node == CC.da_calls_commitment([b1, b2], "default"), "multi-block chain must match the body fold"


def t_namespaces_are_separated():
    """A call in namespace 'x' must not enter the default namespace's chain."""
    blk = block([call_tx(cid="a", method="d"), call_tx(cid="b", method="x", ns="x")])
    _i, by_ns = CC.block_summary(blk)
    assert CC.fold_leaves(alghash.IV, by_ns.get("default", [])) == CC.da_calls_commitment([blk], "default")
    assert CC.fold_leaves(alghash.IV, by_ns.get("x", [])) == CC.da_calls_commitment([blk], "x")
    assert by_ns.get("default") != by_ns.get("x"), "namespaces must not share a leaf list"


# ---------------------------------------------------------------- 2. records-inertness allowlist

def t_safe_ops_are_inert():
    """A block of value-0 calls and pure-KV ops moves no RECORDS."""
    for op in ("deploy", "lock", "upgrade", "transfer_contract"):
        assert CC.block_records_inert(block([{"recipient": "blob", "sender": "a", "data": {"op": op}}])), \
            f"op {op} should be records-inert"
    assert CC.block_records_inert(block([call_tx(value=0)])), "value-0 call should be inert"
    assert CC.block_records_inert(block([{"recipient": "ndoSomeone", "sender": "a", "amount": 5}])), \
        "an ordinary transfer touches no exec state"


def t_value_call_is_not_inert():
    """A value>0 call escrows sender->cid across two bridge-balance RECORD positions before the VM runs."""
    assert not CC.block_records_inert(block([call_tx(value=1)])), "value>0 call moves RECORDS"


def t_records_moving_blob_ops_are_not_inert():
    for op in ("emit", "bridge_withdraw", "collect_dividend", "field_transfer", "shielded_transfer"):
        assert not CC.block_records_inert(block([{"recipient": "blob", "sender": "a", "data": {"op": op}}])), \
            f"blob op {op} moves RECORDS"


def t_records_moving_recipients_are_not_inert():
    for r in ("bridge", "bridge_withdraw", "dividend", "dividend_withdraw",
              "shield", "unshield", "xmsg", "faucet", "treasury_execute"):
        assert not CC.block_records_inert(block([{"recipient": r, "sender": "a"}])), \
            f"L1 recipient {r} moves RECORDS"


def t_unknown_op_defaults_to_not_inert():
    """THE allowlist property: an op nobody has vetted is non-inert, so a future record-moving op fails
    CLOSED (proof refused, quorum fallback) instead of silently settling a records-frozen root."""
    assert not CC.block_records_inert(block([{"recipient": "blob", "sender": "a", "data": {"op": "brand_new"}}]))
    assert not CC.block_records_inert(block([{"recipient": "blob", "sender": "a", "data": "not-a-dict"}])), \
        "an undecodable blob cannot be established safe"


# ---------------------------------------------------------------- 3. the gate, fail-closed

def _store(blocks, lo):
    """{height: summary} for `blocks` starting at height lo+1 — what kv_ops.exec_summary_get would return."""
    out = {}
    for i, b in enumerate(blocks):
        inert, by_ns = CC.block_summary(b)
        out[lo + 1 + i] = {"inert": 1 if inert else 0, "calls": by_ns}
    return out


def _proof(store, lo, hi, ns="default"):
    """A single-segment proof whose calls_commitment is the honest fold over (lo, hi]."""
    node = alghash.IV
    for h in range(lo + 1, hi + 1):
        node = CC.fold_leaves(node, (store[h].get("calls") or {}).get(ns, []))
    return {"segments": [{"cursor": hi, "calls_commitment": node}]}


def t_honest_proof_binds():
    blocks = [block([call_tx(method=f"m{i}")], number=100 + i) for i in range(3)]
    store = _store(blocks, 100)
    ok, why = CC.verify_calls_bound_to_summaries(_proof(store, 100, 103), "default", 100, 103,
                                                 store.get, 240)
    assert ok, f"an honest, fully-summarised span must bind: {why}"


def t_missing_summary_is_refused():
    """A gap must REFUSE, never read as 'no calls' — else a node lacking the summary binds the span to an
    empty call list and accepts a fabricated one."""
    blocks = [block([call_tx(method=f"m{i}")], number=100 + i) for i in range(3)]
    store = _store(blocks, 100)
    proof = _proof(store, 100, 103)
    del store[102]
    ok, why = CC.verify_calls_bound_to_summaries(proof, "default", 100, 103, store.get, 240)
    assert not ok and "no exec summary" in why, f"missing summary must be refused, got ({ok}, {why})"


def t_records_moving_block_is_refused():
    blocks = [block([call_tx()], number=100), block([call_tx(value=5)], number=101)]
    store = _store(blocks, 100)
    ok, why = CC.verify_calls_bound_to_summaries(_proof(store, 100, 102), "default", 100, 102,
                                                 store.get, 240)
    assert not ok and "RECORDS" in why, f"a records-moving block must be refused, got ({ok}, {why})"


def t_fabricated_calls_refused():
    blocks = [block([call_tx(method="real")], number=100)]
    store = _store(blocks, 100)
    proof = _proof(store, 100, 101)
    proof["segments"][0]["calls_commitment"] = (int(proof["segments"][0]["calls_commitment"]) + 1) % F.P
    ok, why = CC.verify_calls_bound_to_summaries(proof, "default", 100, 101, store.get, 240)
    assert not ok and "fabricated" in why, f"a tampered commitment must be refused, got ({ok}, {why})"


def t_span_cap_and_coverage():
    blocks = [block([call_tx()], number=100 + i) for i in range(3)]
    store = _store(blocks, 100)
    ok, why = CC.verify_calls_bound_to_summaries(_proof(store, 100, 103), "default", 100, 103, store.get, 2)
    assert not ok and "exceeds" in why, "an over-long span must be refused"
    short = {"segments": [{"cursor": 102, "calls_commitment": _proof(store, 100, 102)["segments"][0]["calls_commitment"]}]}
    ok, why = CC.verify_calls_bound_to_summaries(short, "default", 100, 103, store.get, 240)
    assert not ok and "do not cover" in why, f"a partial span must be refused, got ({ok}, {why})"
    ok, why = CC.verify_calls_bound_to_summaries(_proof(store, 100, 101), "default", 100, 100, store.get, 240)
    assert not ok and "empty" in why, "an empty span must be refused"


def t_no_segments_refused():
    ok, why = CC.verify_calls_bound_to_summaries({"segments": []}, "default", 100, 101, lambda h: None, 240)
    assert not ok, "a proof with no segments must be refused"


for name, fn in [
    ("summary fold == body-derived commitment (THE invariant)", t_fold_matches_body_commitment),
    ("chain composes across blocks identically", t_fold_matches_across_multiple_blocks),
    ("namespaces keep separate chains", t_namespaces_are_separated),
    ("value-0 calls + pure-KV ops are records-inert", t_safe_ops_are_inert),
    ("value>0 call is NOT inert", t_value_call_is_not_inert),
    ("records-moving blob ops are NOT inert", t_records_moving_blob_ops_are_not_inert),
    ("records-moving L1 recipients are NOT inert", t_records_moving_recipients_are_not_inert),
    ("unknown op fails CLOSED (allowlist)", t_unknown_op_defaults_to_not_inert),
    ("honest fully-summarised span binds", t_honest_proof_binds),
    ("missing summary is refused, not treated as empty", t_missing_summary_is_refused),
    ("records-moving block in span is refused", t_records_moving_block_is_refused),
    ("fabricated calls_commitment is refused", t_fabricated_calls_refused),
    ("span cap / partial / empty span refused", t_span_cap_and_coverage),
    ("proof with no segments refused", t_no_segments_refused),
]:
    check(name, fn)

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
