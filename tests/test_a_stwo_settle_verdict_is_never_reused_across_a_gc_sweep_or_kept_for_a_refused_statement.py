"""A STWO SETTLE VERDICT IS NEVER REUSED ACROSS A GC SWEEP, AND A REFUSED STATEMENT IS NEVER KEPT AS ONE
(ops/transaction_ops.stwo_verify_key / _stwo_settle_check / _stwo_verdict; zk audit 2026-11-02).

A pooled settle is re-validated on every block-candidate build, so its verdict is memoised. The memo key must bind every
committed-state read the verdict makes that a LATER block can change. The cursor's block hash fixes the span and its chain
inputs, but not the idle-GC watermarks: ops/settle_chain.l1_weights_at refuses a span whose epoch weights would have to be
rebuilt from recert rows the row sweep has pruned, and both watermarks rise with the tip. Unbound, a verdict cached before
a sweep answered after it, so the node that held the memo accepted where a node judging fresh refused.

And a native verifier that refuses this node's OWN statement (stwo_settle RC_BAD_ARGS: the statement is built from this
node's replay, and the honest prover proved that same text with the same parser) has said nothing about the proof. It
used to surface as settle_b2's "malformed bundle" and be memoised as a refusal for good.

  1. the key changes with gc_rows_below and with gc_accts_below, and with nothing else held fixed;
  2. through _stwo_settle_check: a second validation at the same watermarks reuses the verdict (one replay); after a row
     sweep, and again after an account sweep, the verdict is computed afresh;
  3. a native refusal of the node's own statement reaches L1 as ProofUnavailable (defer), is not memoised, and the same
     settle is judged on its merits once the library answers.

Run: python3 tests/test_a_stwo_settle_verdict_is_never_reused_across_a_gc_sweep_or_kept_for_a_refused_statement.py
"""
import os
import _harness
HOME = _harness.isolate("nado-test-stwo-verdict-key-")
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(os.path.join(HOME, "nado", d), exist_ok=True)
import json
import protocol

from genesis import create_indexers
create_indexers()

from execnode import settle_b2
from execnode.native_guard import NativeStatementRefused
from ops import kv_ops, settle_chain, settlement_ops, transaction_ops as TXO
from ops.transaction_ops import ProofUnavailable, stwo_verify_key

T = _harness.Report()

# ---- 1 ------------------------------------------------------------------------------------------------------------------
base = ("c", 60, "aa" * 32, 120, "bb" * 32, "cc" * 32)
k0 = stwo_verify_key(*base, 0, 0)
T.check("1. the key binds the row-sweep watermark", stwo_verify_key(*base, 5, 0) != k0)
T.check("1. the key binds the account-sweep watermark", stwo_verify_key(*base, 0, 5) != k0)
T.check("1. and is stable when nothing changes", stwo_verify_key(*base, 0, 0) == k0)

# ---- 2: the real _stwo_settle_check, its chain context stubbed ---------------------------------------------------------
protocol.STWO_SETTLE_HEIGHT = 1                       # the gate open (the shipped value is dormant on generation 29)
settlement_ops.latest_settled = lambda ns: (60, "aa" * 32)
settle_chain.carry_refusal = lambda sc: None
calls = []
_real_verdict = TXO._stwo_verdict


def counted(*a):
    calls.append(a)
    return True, "ok"


TXO._stwo_verdict = counted
TXO._STWO_VERIFY_MEMO.clear()
data = {"stwo": "commitment-1"}


def check():
    TXO._stwo_settle_check(data, protocol.DEFAULT_NS, 120, "bb" * 32, 200, deep=False)


check()
check()
T.check("2. a second validation at the same watermarks reuses the verdict (one replay)", len(calls) == 1, len(calls))
kv_ops.meta_set_int("gc_rows_below", 7)
check()
T.check("2. after a row sweep the verdict is computed afresh", len(calls) == 2, len(calls))
kv_ops.meta_set_int("gc_accts_below", 3)
check()
T.check("2. after an account sweep the verdict is computed afresh", len(calls) == 3, len(calls))
check()
T.check("2. and is reused again while the watermarks hold", len(calls) == 3, len(calls))

# ---- 3: a refused statement, through the real _stwo_verdict -------------------------------------------------------------
TXO._stwo_verdict = _real_verdict
TXO._STWO_VERIFY_MEMO.clear()
TXO._fetch_da_proof = lambda c: json.dumps({"v": 1}).encode()
settle_chain.l1_chain = lambda sc: None
settle_chain.l1_span_blocks = lambda sc, cursor: []
answer = {"raise": True}


def fake_verify_span(sc, sroot, blocks, chain, bundle):
    if answer["raise"]:
        raise NativeStatementRefused("the library refused this node's own statement")
    return False, "the VM proof: REFUSED Sum", None


settle_b2.verify_span = fake_verify_span
data = {"stwo": "commitment-2"}
try:
    check()
    got = "accepted"
except ProofUnavailable as e:
    got = "deferred"
except AssertionError as e:
    got = f"refused: {e}"
T.check("3. a refused statement defers the settle (ProofUnavailable), never refuses it", got == "deferred", got)
T.check("3. and nothing is memoised for it", not TXO._STWO_VERIFY_MEMO, TXO._STWO_VERIFY_MEMO)
answer["raise"] = False
try:
    check()
    got = "accepted"
except ProofUnavailable:
    got = "deferred"
except AssertionError as e:
    got = f"refused: {e}"
T.check("3. once the library answers, the same settle is judged on its merits", got.startswith("refused:") and
        "REFUSED Sum" in got, got)
T.done("ALL PASS — a Stwo settle verdict binds the GC watermarks, and a refused statement is never a verdict")
