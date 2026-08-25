"""The generation-keyed rule gate (protocol.py, 2026-08-25): the dividend curve, the softened lapse and the
40% bonded levy activate at DIVIDEND_RULES_HEIGHT on chain generation 22 and are unconditional afterwards.

THE SHAPE IS THE TEST. Earlier gates said "remove at the next reroll" in a comment and depended on someone
remembering. This one is keyed on CHAIN_GENERATION so the reroll commit retires it by itself; the source
assertion below is what stops a future edit from turning it back into a bare height."""
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


def t_gate_is_keyed_on_generation():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocol.py")).read()
    m = re.search(r"^DIVIDEND_RULES_HEIGHT\s*=\s*(.+)$", src, re.M)
    assert m, "DIVIDEND_RULES_HEIGHT must be defined at module level"
    assert "CHAIN_GENERATION ==" in m.group(1) and "else 0" in m.group(1), \
        f"the gate must read '<height> if CHAIN_GENERATION == <gen> else 0', got: {m.group(1)}"
    assert P.DIVIDEND_RULES_EPOCH == P.DIVIDEND_RULES_HEIGHT // P.EPOCH_LENGTH
    if P.CHAIN_GENERATION != 22:
        assert P.DIVIDEND_RULES_HEIGHT == 0, "on any later generation the rules are active from block 0"


def t_bonded_levy():
    H = P.DIVIDEND_RULES_HEIGHT
    assert P.bonded_dividend_bps(max(0, H - 1)) == (P.BONDED_DIVIDEND_BPS if H > 0 else P.BONDED_DIVIDEND_BPS_V2)
    assert P.bonded_dividend_bps(H) == P.BONDED_DIVIDEND_BPS_V2 == 4000
    for h in (0, max(0, H - 1), H, H + 12345):
        for R in (1, 7, 10**9, 10**9 + 3):
            pc, dv, tr = P.split_bonded_block_reward(R, h)
            assert pc + dv + tr == R, "the split must sum exactly (apply == rollback integers)"
            assert dv == R * P.bonded_dividend_bps(h) // P.BPS_DENOM and tr == R * P.TREASURY_BPS // P.BPS_DENOM
    pc, dv, tr = P.split_bonded_block_reward(10**9, H)
    assert (pc, dv, tr) == (5 * 10**8, 4 * 10**8, 10**8), (pc, dv, tr)     # 50 / 40 / 10


def t_dividend_curve():
    E = P.DIVIDEND_RULES_EPOCH
    from ops.mining_ops import open_shares
    if E > 0:
        for f in range(0, 40):
            assert P.dividend_weight(f, E - 1) == open_shares(f), "pre-activation weight == selection weight"
    got = [P.dividend_weight(f, E) for f in (0, 1, 5, 10, 15, 20, 25, 30, 99, None, -3)]
    assert got == [1, 1, 1, 3, 7, 11, 17, 25, 25, 1, 1], got
    assert all(P.dividend_weight(f, E) <= P.dividend_weight(f + 1, E) for f in range(0, 35)), "monotonic"
    assert P.dividend_weight(P.FIDELITY_CAP, E) == P.DIVIDEND_WEIGHT_MAX == 25


def t_fidelity_step():
    E, G, MIN = P.DIVIDEND_RULES_EPOCH, P.FIDELITY_GAIN, P.FIDELITY_MIN_GAP_EPOCHS
    # continuous, well spaced -> +GAIN (both eras)
    assert P.fidelity_step(7, True, MIN, E) == 7 + G and P.fidelity_step(7, True, MIN + 5, max(0, E - 1)) == 7 + G
    # continuous, too close -> unchanged (anti-farm spacing, both eras)
    assert P.fidelity_step(7, True, MIN - 1, E) == 7 and P.fidelity_step(7, True, 1, max(0, E - 1)) == 7
    # lapse / first recert: reset to GAIN before, halve (never below GAIN) from the activation epoch
    if E > 0:
        assert P.fidelity_step(20, False, 999, E - 1) == G
    assert P.fidelity_step(20, False, 999, E) == 10
    assert P.fidelity_step(3, False, 999, E) == max(G, 1)
    assert P.fidelity_step(0, False, 999, E) == G and P.fidelity_step(1, False, 999, E) == G


def t_live_apply_and_replay_share_the_step():
    """apply_register and fidelity_at_epoch must both call protocol.fidelity_step — not mirror it."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    a = open(os.path.join(root, "ops", "account_ops.py")).read()
    d = open(os.path.join(root, "ops", "dividend_ops.py")).read()
    assert "fidelity_step(" in a.split("def apply_register")[1].split("\ndef ")[0]
    assert "fidelity_step(" in d.split("def fidelity_at_epoch")[1].split("\ndef ")[0]
    assert "dividend_weight(" in d.split("def weights_at_epoch")[1]


if __name__ == "__main__":
    check("gate is keyed on CHAIN_GENERATION (self-retiring at the next reroll)", t_gate_is_keyed_on_generation)
    check("bonded levy 20% -> 40% at the gate; splits sum exactly", t_bonded_levy)
    check("dividend curve: selection weight before, convex 1..25 from the gate", t_dividend_curve)
    check("fidelity step: spacing kept, lapse halves from the gate", t_fidelity_step)
    check("live apply and fraud-proof replay share protocol.fidelity_step", t_live_apply_and_replay_share_the_step)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
