"""SAVINGS-LANE CAP PER ATTESTED DEVICE (protocol.BOND_DEVICE_CAP_HEIGHT / BOND_DEVICE_CAP; mining_ops.bonded_producer_registry;
doc/device-attestation.md §"Savings-lane cap"). Pins:
  1. below the gate the producer registry is the raw registry (historical blocks replay unchanged);
  2. from the gate only ATTESTED identities (in the open registry) are drawn, each capped at BOND_DEVICE_CAP;
  3. unattested stake never wins a bonded slot, not even through the un-ramped liveness fallback;
  4. liveness: no attested bonded identity at all -> the whole registry, uncapped;
  5. fork-choice weight (total_bonded_shares / block_fork_weight) is untouched by the cap;
  6. the display mirror, the status fields, the wallet line and the 16-language strings are wired.
Run: python3 tests/test_bond_device_cap.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-bondcap-")
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def main():
    import protocol as P
    from ops import mining_ops as M
    N = P.DENOMINATION
    a, b, c = "a" * 46, "b" * 46, "c" * 46
    reg = {a: {"bonded": 2000 * N, "fidelity": None, "bond_since": None},
           b: {"bonded": 50 * N, "fidelity": None, "bond_since": None},
           c: {"bonded": 5000 * N, "fidelity": None, "bond_since": None}}
    open_reg = {a: {"fidelity": 3}, b: {"fidelity": 1}}
    gate = P.BOND_DEVICE_CAP_HEIGHT
    check("cap is 1,000 NADO", P.BOND_DEVICE_CAP == 1000 * N)
    check("the gate is a height at/after the permanent-binding gate", gate >= P.DEVICE_BIND_PERMANENT_HEIGHT)
    # 1. below the gate
    check("below the gate: the raw registry, same object", M.bonded_producer_registry(reg, open_reg, gate - 1) is reg)
    # 2. from the gate (before the curve: the cliff)
    pr = M.bonded_producer_registry(reg, open_reg, gate)
    check("from the gate: only attested identities", set(pr) == {a, b}, set(pr))
    check("stake above the cap counts as the cap (pre-curve blocks replay the cliff)", pr[a]["bonded"] == P.BOND_DEVICE_CAP)
    check("stake below the cap counts in full", pr[b]["bonded"] == 50 * N)
    # 2b. THE CURVE (BOND_WEIGHT_CURVE_HEIGHT): knee = max(1,000, 5 % of the others), tail saturating at 1.5 x knee
    cg = P.BOND_WEIGHT_CURVE_HEIGHT
    check("curve gate is at/after the cap gate", cg >= gate)
    check("bond_weight: identity up to the knee", M.bond_weight(700 * N, 1000 * N) == 700 * N)
    check("bond_weight: continuous at the knee", M.bond_weight(1000 * N, 1000 * N) == 1000 * N)
    check("bond_weight: 2,000 on a 1,000 knee counts 1,250 (K(1.5-0.5K/s))", M.bond_weight(2000 * N, 1000 * N) == 1250 * N)
    check("bond_weight: saturates below 1.5 x knee", M.bond_weight(10**9 * N, 1000 * N) < 1500 * N and M.bond_weight(10**9 * N, 1000 * N) > 1499 * N)
    check("bond_knee: floored at 1,000 NADO for a small lane", M.bond_knee(2000 * N, 50 * N) == 1000 * N)
    check("bond_knee: 5 % of the OTHERS' stake once that exceeds the floor; own stake never lifts it", M.bond_knee(50_000 * N, 40_000 * N) == 2000 * N and M.bond_knee(50_000 * N, 4_000 * N) == 1000 * N)
    prc = M.bonded_producer_registry(reg, open_reg, cg)
    check("curve draw: a's 2,000 on a 1,000 knee (others: 50) counts 1,250", prc[a]["bonded"] == 1250 * N, prc.get(a))
    check("curve draw: b unchanged below the knee", prc[b]["bonded"] == 50 * N)
    big = {a: {"bonded": 50_000 * N, "fidelity": None, "bond_since": None}, b: {"bonded": 40_000 * N, "fidelity": None, "bond_since": None}, c: {"bonded": 5000 * N, "fidelity": None, "bond_since": None}}
    prb = M.bonded_producer_registry(big, {a: {}, b: {}, c: {}}, cg)
    check("curve draw in a big lane: knees come from the others, whale bounded to < 1.5 x its knee", prb[a]["bonded"] == M.bond_weight(50_000 * N, M.bond_knee(50_000 * N, 45_000 * N)) and prb[a]["bonded"] < 3375 * N)
    check("the input registry is never mutated", reg[a]["bonded"] == 2000 * N and c in reg)
    # 3. the draw never picks unattested stake, at bonded slots, with and without the ramp
    beacon = "ab" * 32
    wins = {}
    for slot in range(gate, gate + 600):
        if M.lane_of(slot, beacon) != "bonded":
            continue
        w = M.select_producer_two_lane(open_reg, reg, beacon, slot)
        wins[w] = wins.get(w, 0) + 1
    check("bonded slots from the gate: winners are attested only", set(wins) <= {a, b} and wins, wins)
    check("... the capped whale does not dominate: b wins a fair share (50 vs 1000 shares)", wins.get(b, 0) > 0, wins)
    fresh = {k: {**v, "bond_since": 10 ** 9} for k, v in reg.items()}       # everyone still ramping -> fallback path
    wins2 = set()
    for slot in range(gate, gate + 600):
        if M.lane_of(slot, beacon) == "bonded":
            wins2.add(M.select_producer_two_lane(open_reg, fresh, beacon, slot))
    check("the un-ramped liveness fallback stays inside the attested set", wins2 <= {a, b} and wins2, wins2)
    before = set()
    for slot in range(gate - 600, gate):
        if M.lane_of(slot, beacon) == "bonded":
            before.add(M.select_producer_two_lane(open_reg, reg, beacon, slot))
    check("below the gate the unattested whale still wins (historical replay)", c in before, before)
    # 4. liveness
    check("no attested bonded identity -> whole registry, uncapped", M.bonded_producer_registry(reg, {}, gate) is reg)
    w0 = M.select_producer_two_lane({}, reg, beacon, next(s for s in range(gate, gate + 600) if M.lane_of(s, beacon) == "bonded"))
    check("... and a bonded slot still produces", w0 in reg, w0)
    # 5. fork weight untouched
    check("total_bonded_shares ignores the cap and attestation", M.total_bonded_shares(reg) == 200 + 5 + 500)
    check("block_fork_weight ignores the cap and attestation", M.block_fork_weight(reg, gate) == 706)
    # 6. wiring
    mo = open(os.path.join(ROOT, "ops", "mining_ops.py")).read()
    seg = mo[mo.index("def select_producer_two_lane"):]
    check("the draw runs over bonded_producer_registry, fallback included",
          "draw_registry = bonded_producer_registry(bonded_registry, open_registry, slot)" in seg
          and "_weighted_draw(draw_registry, bonded_weight, beacon, slot)" in seg
          and "_weighted_draw(draw_registry, _bonded_shares, beacon, slot)" in seg
          and "_weighted_draw(bonded_registry, bonded_weight" not in seg)
    bo = open(os.path.join(ROOT, "ops", "block_ops.py")).read()
    check("the display mirrors the draw", "bonded_reg = bonded_producer_registry(get_bonded_registry(), open_reg, epoch * EPOCH_LENGTH)" in bo)
    check("mining_status carries the cap + curve fields", all(k in bo for k in ('"bond_cap_active"', '"bonded_producing"', '"my_bonded_raw"', '"bond_device_cap"', '"my_bonded_effective"', '"bond_knee"')))
    js = open(os.path.join(ROOT, "static", "interface.js")).read()
    check("the wallet says whether the stake counts", 'i18("bond.needsAttest"' in js and 'i18("bond.capped"' in js and 'id="bondCapLine"' in open(os.path.join(ROOT, "static", "interface.html")).read())
    i18n = open(os.path.join(ROOT, "static", "i18n.js")).read()
    for k in ("bond.needsAttest", "bond.capped", "bond.counting"):
        n = i18n.count('"' + k + '":')
        check(f"i18n: {k} in every language", n >= 16 and n % 16 == 0, n)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback; traceback.print_exc(); _fails.append("exception")
    print("ALL PASS" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    raise SystemExit(1 if _fails else 0)
