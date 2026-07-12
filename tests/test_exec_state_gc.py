"""
Exec-layer state-root growth bounds (execnode/state.py):
  1. drop_claimed: a finalized L1 claim GCs the matching withdrawal/dividend/unshield record —
     the leaf leaves state_root; unclaimed records stay provable
  2. drop_consumed_outbox: a finalized xmsg delivery GCs the SOURCE outbox message; seqs stay
     monotonic afterwards (no reuse)
  3. field-nullifier DIGEST leaf: root is bounded in nullifier-set size but still binds it
  4. a legacy (list) outbox snapshot is REFUSED loudly (no legacy shapes on alphanet)

Run: python3 tests/test_exec_state_gc.py
"""
import os, sys, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState, _outbox_leaf
from hashing import verify_merkle_proof

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def _st():
    return ExecState(tempfile.mktemp(prefix="nado_execgc_", suffix=".json"))


def t1_drop_claimed():
    st = _st()
    st.withdrawals["1"] = {"addr": "ndoA", "amount": 5}
    st.withdrawals["2"] = {"addr": "ndoB", "amount": 7}
    st.dividend_withdrawals["3"] = {"addr": "ndoC", "amount": 9}
    st.unshield_withdrawals["4"] = {"addr": "ndoD", "amount": 11}
    st._touch()
    r0 = st.state_root()
    st.drop_claimed("bridge_withdraw", 1)
    st.drop_claimed("dividend_withdraw", "3")
    st.drop_claimed("unshield", 4)
    assert "1" not in st.withdrawals and "3" not in st.dividend_withdrawals and "4" not in st.unshield_withdrawals
    assert st.state_root() != r0, "claimed leaves must leave the root"
    p = st.withdrawal_proof("2")
    assert p and verify_merkle_proof(
        __import__("hashing").withdrawal_leaf("ndoB", 7, "2"), p["proof"], st.state_root()), \
        "UNclaimed exits must stay provable"
    st.drop_claimed("bridge_withdraw", 999)        # unknown nonce -> no-op, no error
    st.drop_claimed("nonsense", 1)                 # unknown kind -> no-op


def t2_drop_consumed_outbox_and_monotonic_seq():
    st = _st()
    st.apply_blob({"op": "emit", "to_ns": "b", "data": "m0"}, sender="ndoA", txid="t0")
    st.apply_blob({"op": "emit", "to_ns": "b", "data": "m1"}, sender="ndoA", txid="t1")
    r0 = st.state_root()
    st.drop_consumed_outbox(0)
    assert "0" not in st.outbox and "1" in st.outbox, "only the consumed message goes"
    assert st.state_root() != r0, "consumed outbox leaf must leave the root"
    st.apply_blob({"op": "emit", "to_ns": "b", "data": "m2"}, sender="ndoA", txid="t2")
    assert "2" in st.outbox and st.outbox["2"]["seq"] == 2, "seq counter is monotonic after GC (no reuse)"
    p = st.outbox_proof(1)
    assert p and verify_merkle_proof(_outbox_leaf(p["message"]), p["proof"], st.state_root()), \
        "surviving outbox messages stay provable"
    assert st.outbox_proof(0) is None, "consumed message is gone"
    st.drop_consumed_outbox("bogus")               # malformed seq -> no-op


def t3_field_nfset_digest_bounded():
    st = _st()
    r_empty = st.state_root()
    st.field_pool.nullifiers.update(range(1, 500))
    st._touch()
    r_full = st.state_root()
    assert r_full != r_empty, "the digest still BINDS the nullifier set"
    # the leaf list stays the same LENGTH regardless of set size (one digest leaf, not one per nf)
    n_leaves_full = len(st._compute_leaves())
    st.field_pool.nullifiers.update(range(500, 1000))
    st._touch()
    assert len(st._compute_leaves()) == n_leaves_full, "leaf count must not grow with the nullifier set"
    assert st.state_root() != r_full, "...but the digest changes with the set"


def t4_legacy_outbox_shape_refused():
    st = _st()
    try:
        st._restore({"contracts": {}, "cursor": 5,
                     "outbox": [{"seq": 0, "from": "ndoA", "to_ns": "b", "data": "x"}]})
        raise SystemExit("legacy list outbox must be refused")
    except ValueError as e:
        assert "legacy outbox" in str(e)
    # and the seq counter is floored past any present seqs (never reused after GC)
    st2 = _st()
    st2._restore({"contracts": {}, "cursor": 5, "outbox_seq": 0,
                  "outbox": {"7": {"seq": 7, "from": "ndoA", "to_ns": "b", "data": "x"}}})
    assert st2.outbox_seq == 8, "counter must be floored above the highest present seq"


for name, fn in sorted((n, f) for n, f in list(globals().items())
                       if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)

print(f"\n{'ALL EXEC-GC CHECKS PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
