"""
Registration-rate PoSW difficulty v2 (ops/reg_difficulty.py) — the CONSENSUS multiplier scales the required
PoSW work with recent registration volume, counted from the CHAIN'S BLOCKS over complete epochs strictly
before the anchor (2026-07-17 split postmortem: the v1 live-index read + still-filling anchor epoch made
honest nodes disagree and wedged the clean ones at #2944). This test stubs the per-epoch chain counts and
checks the window math, the race fix (anchor-epoch counts are excluded), the grandfather proof scan, and
the mint-side boundary behavior.

Run: python3 tests/test_reg_difficulty.py
"""
import os, sys, tempfile, logging, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_regdiff_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.getLogger().addHandler(logging.NullHandler())

from protocol import POSW_T, POSW_S, POSW_K, POSW_DIFF_FLOOR, POSW_DIFF_WINDOW, POSW_DIFF_MAX_MULT
from fork import height as fork_height
REG_DIFF_V2_HEIGHT = fork_height("reg_difficulty_v2")
from ops import posw
from ops import reg_difficulty as rd

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

E = 500                                            # an anchor epoch
COUNTS = {}                                        # stubbed per-epoch chain register counts
rd.chain_register_count = lambda epoch: COUNTS.get(epoch, 0)

def t1_normal_load_is_1x():
    """Prove no recent registrations gives a 1x multiplier and the base POSW_T step count."""
    COUNTS.clear()
    assert rd.difficulty_multiplier(E) == 1, "no recent registrations -> 1x"
    assert rd.required_posw_t(E) == POSW_T, "1x -> base PoSW steps"

def t2_flood_ramps_difficulty():
    """Prove a flood at 5x the floor baseline in the pre-anchor window ramps the work to 5x."""
    COUNTS.clear()
    COUNTS[E - 1] = 5 * POSW_DIFF_FLOOR            # recent window = epochs [E-20, E-1]
    m = rd.difficulty_multiplier(E)
    assert m == 5, f"5x the baseline should give 5x work, got {m}"
    assert rd.required_posw_t(E) == POSW_T * 5, "required steps scale with the multiplier"

def t3_capped_at_max():
    """Prove a huge registration burst is capped at POSW_DIFF_MAX_MULT so honest users aren't priced out."""
    COUNTS.clear()
    COUNTS[E - 1] = 500 * POSW_DIFF_FLOOR
    assert rd.difficulty_multiplier(E) == POSW_DIFF_MAX_MULT, "multiplier is capped"
    assert rd.required_posw_t(E) == POSW_T * POSW_DIFF_MAX_MULT

def t4_anchor_epoch_excluded():
    """THE RACE FIX: registrations landing in the anchor's OWN (still-filling) epoch must not move the
    requirement — otherwise a register landing between prove-time and land-time invalidates honest proofs."""
    COUNTS.clear()
    COUNTS[E] = 500 * POSW_DIFF_FLOOR              # flood in the anchor epoch itself
    assert rd.difficulty_multiplier(E) == 1, "anchor-epoch counts are outside the window"

def t5_window_bounds():
    """Prove the recent window is exactly [E-POSW_DIFF_WINDOW, E-1]: an epoch just outside contributes 0."""
    COUNTS.clear()
    COUNTS[E - POSW_DIFF_WINDOW] = 5 * POSW_DIFF_FLOOR       # oldest epoch INSIDE the window
    assert rd.difficulty_multiplier(E) == 5, "oldest in-window epoch counts"
    COUNTS.clear()
    COUNTS[E - POSW_DIFF_WINDOW - 1] = 5 * POSW_DIFF_FLOOR   # one epoch too old
    assert rd.difficulty_multiplier(E) == 1, "out-of-window epoch must not count"

def t6_grandfather_proof_scan():
    """proof_multiplier finds the exact multiplier a proof satisfies (verify is exact-T) and 0 for garbage.
    Runs with a shrunken POSW_T so the sequential prove stays test-fast."""
    orig_t = rd.POSW_T
    rd.POSW_T = 4 * POSW_S                          # 4 segments at 1x — small but structurally real
    try:
        ch = posw.challenge_bytes("ndotest", "ab" * 32)
        proof = posw.prove(ch, T=2 * rd.POSW_T, S=POSW_S, k=POSW_K)      # honest 2x proof
        assert rd.proof_multiplier(ch, proof) == 2, "2x proof scans to multiplier 2"
        assert rd.proof_multiplier(posw.challenge_bytes("ndoother", "ab" * 32), proof) == 0, \
            "wrong-challenge proof scans to 0"
    finally:
        rd.POSW_T = orig_t

def t7_mint_boundary():
    """mint_multiplier: mirrors the chain-observed multiplier inside the grandfather window (what v1 peers
    provably accept), switches to the strict v2 value past REG_DIFF_V2_HEIGHT."""
    orig_obs, orig_dm = rd._observed_multiplier, rd.difficulty_multiplier
    rd._observed_multiplier = lambda tip, scan_limit=2000: 2
    rd.difficulty_multiplier = lambda e: 3
    try:
        assert rd.mint_multiplier(100, REG_DIFF_V2_HEIGHT) == 2, "inside window -> mirror the chain"
        assert rd.mint_multiplier(100, REG_DIFF_V2_HEIGHT + 1) == 3, "past boundary -> strict v2"
        rd._observed_multiplier = lambda tip, scan_limit=2000: None
        assert rd.mint_multiplier(100, REG_DIFF_V2_HEIGHT) == 3, "no observable register -> v2 fallback"
    finally:
        rd._observed_multiplier, rd.difficulty_multiplier = orig_obs, orig_dm

for t in (t1_normal_load_is_1x, t2_flood_ramps_difficulty, t3_capped_at_max, t4_anchor_epoch_excluded,
          t5_window_bounds, t6_grandfather_proof_scan, t7_mint_boundary):
    check(t.__name__, t)

print("ALL PASS" if fails == 0 else f"{fails} FAILURES"); sys.exit(1 if fails else 0)
