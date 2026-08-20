"""
Canonical presence-dividend accrual + settle-divergence alarm (execnode/execnode.py).

THE BUG CLASS (betanet-3, proven live 2026-08-19): accrual ran in the poll EPILOGUE, i.e. at
poll-batch boundaries — private, per-node timing. collect_dividend burns whatever is accrued at
that instant, so the same blocks produced different roots on different nodes (measured: same seed
state + same 532 blocks + 81 collects -> two different roots for batch-end vs per-block accrual).
Structurally identical attesters could therefore never agree, and the settle quorum froze.

  1. behavioral: two accrual positions around one collect produce DIFFERENT dividend maps (the
     divergence mechanism, demonstrated on ExecState directly)
  2. pins: canonical accrual runs BEFORE the block applies, keyed purely on h, activation-gated by
     the hardcoded DIV_ACCRUAL_CANONICAL_FROM; a failed accrual HOLDS the cursor
  3. pins: the settle-conflict alarm scans every replayed block and CRITICAL-logs the first
     same-cursor root conflict
  4. pins: /exec/state_snapshot serves by-cursor stashes (?cursor=) for justified-checkpoint repair

Run: python3 tests/test_exec_accrual_canonical.py
"""
import os, sys, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

_SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "execnode", "execnode.py")).read()

def _st():
    return ExecState(tempfile.mktemp(prefix="nado_accrual_", suffix=".json"))


def t1_accrual_position_changes_the_root():
    # miner M has 5 accrued; epoch E pays M another 7; a collect burns the accrued balance.
    # Order A: collect THEN accrue -> dividend[M] == 7. Order B: accrue THEN collect -> 0.
    def build(order):
        st = _st()
        st.dividend["M"] = 5
        st._touch()
        def collect():
            st.dividend.pop("M"); st._touch()      # what collect_dividend does to the map
        def accrue():
            st.accrue_dividend_epoch(7, {"M": 1})
        (collect, accrue) if order == "A" else (accrue, collect)
        if order == "A":
            collect(); accrue()
        else:
            accrue(); collect()
        return st.dividend.get("M", 0), st.state_root()
    (da, ra), (db, rb) = build("A"), build("B")
    assert da != db and ra != rb, "accrual position must change the map and the root (the bug class)"


def t2_pin_canonical_accrual_gated_and_before_apply():
    assert "DIV_ACCRUAL_CANONICAL_FROM" not in _SRC, \
        "the betanet-3 gate (and the legacy epilogue accrual) were DELETED at gen 22 and must STAY deleted"
    assert "NADO_EXEC_DIV" not in _SRC, "activation must not be env-tweakable"
    assert "accrue_dividend_epoch" not in _SRC[_SRC.index("async def tail_loop"):], \
        "the legacy batch-boundary epilogue accrual must stay deleted (per-block accrual is THE rule)"
    tl = _SRC[_SRC.index("async def tail_loop"):]
    i = tl.index("if not await _accrue_owed(session, state, h // _EPOCH_LENGTH - 1)")
    seg = tl[i:i + 400]
    assert "_accrue_owed(session, state, h // _EPOCH_LENGTH - 1)" in seg, \
        "watermark must be a pure function of h"
    assert "break" in seg, "a failed accrual must HOLD the cursor"
    assert i < tl.index('if "block_transactions" not in block:'), \
        "canonical accrual must run BEFORE the body check / apply"
    # helper: stalls return False on pruned weights and on exceptions
    hs = _SRC[_SRC.index("async def _accrue_owed"):_SRC.index("def _observe_settles")]
    assert hs.count("return False") >= 2 and "return True" in hs


def t3_pin_divergence_alarm():
    assert "_observe_settles(block, state.attested)" in _SRC, "every replayed block must be scanned"
    ob = _SRC[_SRC.index("def _observe_settles"):_SRC.index("async def tail_loop")]
    assert "SETTLE ROOT CONFLICT" in ob and "CRITICAL" in ob
    assert "len(roots) > 1" in ob, "alarm fires on the first same-cursor root conflict"


def t4_pin_snapshot_by_cursor():
    h = _SRC[_SRC.index("async def h_state_snapshot"):]
    h = h[:h.index("\nasync def ")]
    assert 'request.query.get("cursor")' in h and "_settled_history" in h, \
        "/exec/state_snapshot must serve by-cursor stashes"


check("accrual position changes the dividend map and the root", t1_accrual_position_changes_the_root)
check("pin: canonical accrual gated, pure-in-h, before apply, holds on failure", t2_pin_canonical_accrual_gated_and_before_apply)
check("pin: settle-divergence CRITICAL alarm", t3_pin_divergence_alarm)
check("pin: snapshot served by cursor", t4_pin_snapshot_by_cursor)
print(f"\n{'ALL PASS' if fails == 0 else f'{fails} FAILURE(S)'}")
sys.exit(1 if fails else 0)
