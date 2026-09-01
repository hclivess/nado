"""The 2026-08-25 dividend rules (protocol.py), unconditional since the betanet-5 (gen 23) reroll: the
convex 1..25 dividend weight curve, the halving lapse, and the 40% bonded levy. Also pins that NO
activation gate exists for them any more — they rode gen 22 behind a generation-keyed gate that the reroll
retired; a bare height sneaking back in would outlive its chain."""
import os, sys, re, tempfile, traceback
os.environ.setdefault("HOME", tempfile.mkdtemp())
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import protocol as P

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def t_no_gate_survives():
    src = open(os.path.join(ROOT, "protocol.py")).read()
    for name in ("DIVIDEND_RULES_HEIGHT", "DIVIDEND_RULES_EPOCH", "_GEN22_RULES_ACTIVATION", "bonded_dividend_bps", "BONDED_DIVIDEND_BPS_V2"):
        assert not re.search(r"^\s*(def\s+)?%s\b" % name, src, re.M), f"{name} is back — the gen-22 gate was retired at gen 23"
    assert P.CHAIN_GENERATION >= 23


def t_bonded_levy():
    assert P.BONDED_DIVIDEND_BPS == 4000
    for R in (1, 7, 10**9, 10**9 + 3):
        pc, dv, tr = P.split_bonded_block_reward(R)
        assert pc + dv + tr == R, "the split must sum exactly (apply == rollback integers)"
        assert dv == R * 4000 // P.BPS_DENOM and tr == R * P.TREASURY_BPS // P.BPS_DENOM
    assert P.split_bonded_block_reward(10**9) == (5 * 10**8, 4 * 10**8, 10**8)     # 50 / 40 / 10


def t_dividend_curve():
    got = [P.dividend_weight(f, 0) for f in (0, 1, 5, 10, 15, 20, 25, 30, 99, None, -3)]
    assert got == [0, 0, 1, 3, 7, 11, 17, 25, 25, 0, 0], got     # gen 24: probation below fidelity 2 -> absent (0)
    assert all(P.dividend_weight(f, 0) <= P.dividend_weight(f + 1, 0) for f in range(0, 35)), "monotonic"
    assert P.dividend_weight(P.FIDELITY_CAP, 0) == P.DIVIDEND_WEIGHT_MAX == 25
    from ops.mining_ops import open_shares
    assert open_shares(0) == 2 and open_shares(30) == 10, "selection weight keeps its liveness floor"


def t_fidelity_step():
    G, MIN = P.FIDELITY_GAIN, P.FIDELITY_MIN_GAP_EPOCHS
    assert P.fidelity_step(7, True, MIN) == 7 + G and P.fidelity_step(7, True, MIN + 5) == 7 + G
    assert P.fidelity_step(7, True, MIN - 1) == 7 and P.fidelity_step(7, True, 1) == 7     # anti-farm spacing
    assert P.fidelity_step(20, False, 999) == 10                                            # lapse halves
    assert P.fidelity_step(3, False, 999) == max(G, 1)
    assert P.fidelity_step(0, False, 999) == G and P.fidelity_step(1, False, 999) == G     # never below GAIN


def t_live_apply_and_replay_share_the_step():
    """apply_register and fidelity_at_epoch must both call protocol.fidelity_step — not mirror it."""
    a = open(os.path.join(ROOT, "ops", "account_ops.py")).read()
    d = open(os.path.join(ROOT, "ops", "dividend_ops.py")).read()
    assert "fidelity_step(" in a.split("def apply_register")[1].split("\ndef ")[0]
    assert "fidelity_step(" in d.split("def fidelity_at_epoch")[1].split("\ndef ")[0]
    assert "dividend_weight(" in d.split("def weights_at_epoch")[1]


if __name__ == "__main__":
    check("no activation gate survives the reroll", t_no_gate_survives)
    check("bonded levy 40%; splits sum exactly", t_bonded_levy)
    check("dividend curve: convex 1..25, selection weight untouched", t_dividend_curve)
    check("fidelity step: spacing kept, lapse halves", t_fidelity_step)
    check("live apply and fraud-proof replay share protocol.fidelity_step", t_live_apply_and_replay_share_the_step)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
