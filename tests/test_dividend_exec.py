"""
Presence dividend — execution-node accrual + collect (doc/presence-dividend.md, Phase 2/3):
  accrue_dividend distributes the DIVIDEND_POOL growth among CURRENTLY-PRESENT miners only, fidelity-weighted,
  carrying the sub-unit remainder; collect_dividend burns a balance into a provable withdrawal leaf that
  verifies against the state_root (what L1's dividend_withdraw checks against the settled root).

Run: python3 tests/test_dividend_exec.py
"""
import os, sys, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from hashing import dividend_leaf, verify_merkle_proof

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def fresh():
    return ExecState(tempfile.mktemp(prefix="nado_divexec_", suffix=".json"))

def t1_weighted_present_only_with_carry():
    st = fresh()
    # pool 0 -> 1000, present {A:10, B:5} -> A 666, B 333, carry 1 (1000 - 999)
    st.accrue_dividend(1000, {"A": 10, "B": 5})
    assert st.dividend["A"] == 666 and st.dividend["B"] == 333, "fidelity-weighted split"
    assert st.div_carry == 1, "sub-unit remainder carried"
    assert "C" not in st.dividend, "an absent miner accrues nothing"
    # pool 1000 -> 1300 (delta 300) + carry 1 = 301, present {A:10} only -> A += 301
    st.accrue_dividend(1300, {"A": 10})
    assert st.dividend["A"] == 967, "A accrues the next round"
    assert st.dividend["B"] == 333, "B, absent this round, is unchanged"

def t2_no_growth_no_accrual():
    st = fresh()
    st.accrue_dividend(500, {"A": 1})
    before = dict(st.dividend)
    assert st.accrue_dividend(500, {"A": 1}) == 0, "no pool growth -> nothing distributed"
    assert st.dividend == before

def t3_collect_burns_and_proves():
    st = fresh()
    st.accrue_dividend(1000, {"A": 10})            # A gets all 1000
    assert st.dividend["A"] == 1000
    res = st.apply_blob({"op": "collect_dividend"}, "A", "txid1")
    assert "collect_dividend" in res and st.dividend.get("A", 0) == 0, "collect burns the balance"
    w = st.dividend_withdrawals["1"]
    assert w["addr"] == "A" and w["amount"] == 1000, "records the provable withdrawal"
    p = st.dividend_withdrawal_proof("1")
    assert verify_merkle_proof(dividend_leaf("A", 1000, "1"), p["proof"], st.state_root()), \
        "the collection proves against the state_root (== what L1 checks vs the settled root)"

def t4_collect_nothing_is_noop():
    st = fresh()
    res = st.apply_blob({"op": "collect_dividend"}, "Z", "txid2")
    assert "no accrued" in res and not st.dividend_withdrawals, "collecting with 0 accrued is a no-op"

def t5_persist_roundtrip():
    path = tempfile.mktemp(prefix="nado_divexec_", suffix=".json")
    st = ExecState(path); st.accrue_dividend(700, {"A": 3, "B": 4}); st.save()
    st2 = ExecState(path)                          # reload
    assert st2.dividend == st.dividend and st2.dividend_pool_seen == 700 and st2.div_carry == st.div_carry, \
        "dividend state survives a save/load"

def t6_drawdown_does_not_strand():
    # Regression: after the pool is drawn down by a claim, fresh inflow BELOW the old high-water mark must
    # still be distributed. The old max()-watermark pinned `seen` at the peak, so post-claim inflow yielded
    # delta<=0 and was distributed to NOBODY until cumulative inflow re-crossed the peak (stranding).
    st = fresh()
    st.accrue_dividend(1000, {"A": 1})                       # pool 0->1000: A gets 1000, seen=1000
    assert st.dividend["A"] == 1000
    # a claim of 400 debits the L1 DIVIDEND_POOL: balance is now 600, below the old seen=1000.
    assert st.accrue_dividend(600, {"A": 1}) == 0, "the drawdown itself distributes nothing"
    assert st.dividend_pool_seen == 600, "watermark follows the pool DOWN (the bug pinned it at 1000)"
    # fresh inflow of 200 -> balance 800, STILL below the old 1000 mark: the new 200 must be distributed.
    assert st.accrue_dividend(800, {"B": 1}) == 200, "inflow below the old high-water mark is NOT stranded"
    assert st.dividend["B"] == 200 and st.dividend_pool_seen == 800

for name, fn in sorted(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
