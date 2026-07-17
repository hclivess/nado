"""
Presence dividend — execution-node accrual + collect (doc/presence-dividend.md, Phase 2/3):
  accrue_dividend_epoch distributes one epoch's DIVIDEND_POOL INFLOW (a deterministic L1 fact, not a live
  pool read) among that epoch's present miners only, fidelity-weighted, carrying the sub-unit remainder;
  collect_dividend burns a balance into a provable withdrawal leaf that verifies against the state_root
  (what L1's dividend_withdraw checks against the settled root).

Run: python3 tests/test_dividend_exec.py
"""
import os, sys, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from hashing import dividend_leaf, verify_merkle_proof

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def fresh():
    """Return a blank ExecState backed by a throwaway temp file."""
    return ExecState(tempfile.mktemp(prefix="nado_divexec_", suffix=".json"))

def t1_weighted_present_only_with_carry():
    """Prove accrue_dividend_epoch splits an epoch's inflow fidelity-weighted among ONLY the present miners, carrying the sub-unit remainder."""
    st = fresh()
    # epoch inflow 1000, present {A:10, B:5} -> A 666, B 333, carry 1 (1000 - 999)
    assert st.accrue_dividend_epoch(1000, {"A": 10, "B": 5}) == 999
    assert st.dividend["A"] == 666 and st.dividend["B"] == 333, "fidelity-weighted split"
    assert st.div_carry == 1, "sub-unit remainder carried"
    assert "C" not in st.dividend, "an absent miner accrues nothing"
    # next epoch: inflow 300 + carry 1 = 301, present {A:10} only -> A += 301
    assert st.accrue_dividend_epoch(300, {"A": 10}) == 301
    assert st.dividend["A"] == 967, "A accrues the next epoch (inflow + carry)"
    assert st.dividend["B"] == 333, "B, absent this epoch, is unchanged"

def t2_no_inflow_no_accrual():
    """Prove a zero-inflow epoch distributes nothing and leaves accrued dividends untouched."""
    st = fresh()
    st.accrue_dividend_epoch(500, {"A": 1})
    before = dict(st.dividend)
    assert st.accrue_dividend_epoch(0, {"A": 1}) == 0, "no inflow -> nothing distributed"
    assert st.dividend == before

def t3_collect_burns_and_proves():
    """Prove collect_dividend burns the accrued balance into a withdrawal leaf that Merkle-proves against the state_root."""
    st = fresh()
    st.accrue_dividend_epoch(1000, {"A": 10})      # A gets all 1000
    assert st.dividend["A"] == 1000
    res = st.apply_blob({"op": "collect_dividend"}, "A", "txid1")
    assert "collect_dividend" in res and st.dividend.get("A", 0) == 0, "collect burns the balance"
    w = st.dividend_withdrawals["1"]
    assert w["addr"] == "A" and w["amount"] == 1000, "records the provable withdrawal"
    p = st.dividend_withdrawal_proof("1")
    from execnode import exec_root as ER
    assert ER.verify_dividend(st.state_root(), "A", 1000, "1", p["proof"]), \
        "the collection proves against the state_root (== what L1 checks vs the settled root)"

def t4_collect_nothing_is_noop():
    """Prove collecting with zero accrued is a no-op that records no withdrawal."""
    st = fresh()
    res = st.apply_blob({"op": "collect_dividend"}, "Z", "txid2")
    assert "no accrued" in res and not st.dividend_withdrawals, "collecting with 0 accrued is a no-op"

def t5_persist_roundtrip():
    """Prove dividend balances, the epoch watermark, and the carry survive an ExecState save/load."""
    path = tempfile.mktemp(prefix="nado_divexec_", suffix=".json")
    st = ExecState(path); st.accrue_dividend_epoch(700, {"A": 3, "B": 4}); st.last_div_epoch = 7; st.save()
    st2 = ExecState(path)                          # reload
    assert st2.dividend == st.dividend and st2.last_div_epoch == 7 and st2.div_carry == st.div_carry, \
        "dividend state survives a save/load"

def t6_empty_present_set_carries_forward():
    """Prove an epoch with inflow but NO present miners loses nothing: the whole pot carries to the next epoch."""
    st = fresh()
    assert st.accrue_dividend_epoch(1000, {}) == 0, "no present set -> nothing distributed"
    assert st.div_carry == 1000, "the whole inflow carries forward (no raw lost)"
    assert st.accrue_dividend_epoch(0, {"A": 1}) == 1000, "the carried pot pays the next present set"
    assert st.dividend["A"] == 1000 and st.div_carry == 0

def t7_deterministic_across_dict_order():
    """Prove the split is a PURE FUNCTION of (inflow, weights): insertion order of the weight map cannot change it."""
    a, b = fresh(), fresh()
    a.accrue_dividend_epoch(1001, {"A": 3, "B": 2, "C": 5})
    b.accrue_dividend_epoch(1001, {"C": 5, "B": 2, "A": 3})
    assert a.dividend == b.dividend and a.div_carry == b.div_carry, \
        "identical (inflow, weights) -> identical dividend map on every node"

for name, fn in sorted(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
