# tests/pets_balance_sim.py — Monte-Carlo tuner that FROZE the NADO Pets v2 battle constants.
# Run `python3 tests/pets_balance_sim.py` to reproduce the balance report; the defaults below are the
# shipped values (must match tests/pets_ref.py / the bytecode / static/pets-genes.js).
# Goal: every stat's MARGINAL win-rate value (+D points) is ~equal, so power = Σstats is a true score.
# Uses python random for speed; the frozen constants then go into pets_ref.py / bytecode / pets-genes.js
# where the rolls come from HASH(q+off) exactly as before.
import random, statistics, sys

CAP_BATTLE = 12

# tunable constants (integers only — the VM has no floats)
P = dict(
    SPAD=60,     # speed softening: P(A owns turn) = (spdA+SPAD)/(spdA+spdB+2*SPAD)
    KHIT=15,     # contested hit: P(hit) = (KHIT+acc)/(KHIT+acc+dodge) — smooth, never saturates
    IMUL=2,      # accuracy weight: acc = int*IMUL
    LDIV=1,      # crit chance % = luck // LDIV
    CMUL=100,    # crit bonus % of damage (100 = crits DOUBLE)
    WNUM=90,     # mitigation: dmg * WNUM // (WNUM + wis)
    CDIV=2,      # intimidation: flat -cha//CDIV, floor 1
    RDIV=4,      # regen per turn = loy // RDIV, capped at max HP
    VMUL=3,      # HP = 20 + vit*VMUL + app//ADIV
    ADIV=1,      # appetite -> HP divisor
    BDMG=50,     # flat damage base: dmg = (BDMG+str+app//AATK)*(60..120)%//100+1
    AATK=4,      # appetite bite: app//AATK joins the damage base
)

def fight(sa, sb, rng, p=P):
    """One battle: sa/sb are 10-stat lists. Returns True if A wins (tie -> defender B... A is challenger).
       Mirrors the intended bytecode exactly (ints, floor div)."""
    hpA = 20 + sa[2] * p["VMUL"] + sa[9] // p["ADIV"]
    hpB = 20 + sb[2] * p["VMUL"] + sb[9] // p["ADIV"]
    h0, h1 = hpA, hpB
    spdA, spdB = sa[8], sb[8]
    span = spdA + spdB + 2 * p["SPAD"]
    for t in range(CAP_BATTLE):
        alive = 1 if (h0 > 0 and h1 > 0) else 0
        cur = 0 if rng.randrange(span) < spdA + p["SPAD"] else 1   # who owns this turn
        A, B = (sa, sb) if cur == 0 else (sb, sa)
        # contested hit roll: roll*(K+acc+dodge) < 100*(K+acc)   (acc = attacker INT, dodge = defender AGI)
        hit = 1 if rng.randrange(100) * (p["KHIT"] + A[3] * p["IMUL"] + B[1]) < 100 * (p["KHIT"] + A[3] * p["IMUL"]) else 0
        dmg = (p["BDMG"] + A[0] + A[9] // p["AATK"]) * (60 + rng.randrange(61)) // 100 + 1
        if rng.randrange(100) < A[7] // p["LDIV"]: dmg += dmg * p["CMUL"] // 100   # crit (luck)
        dmg = dmg * p["WNUM"] // (p["WNUM"] + B[4])                          # mitigation (wis)
        dmg = max(1, dmg - B[5] // p["CDIV"])                                # intimidation (cha)
        dmg *= hit * alive
        if cur == 0: h1 -= dmg
        else: h0 -= dmg
        # regen (loyalty), both sides, alive-gated, capped at max HP
        h0 = min(hpA, h0 + alive * (sa[6] // p["RDIV"]))
        h1 = min(hpB, h1 + alive * (sb[6] // p["RDIV"]))
    # winner = higher REMAINING FRACTION of HP (cross-multiplied, integer): HP is survival, not score
    return h0 * hpB > h1 * hpA

def rand_stats(rng, lo=10, hi=80):
    return [rng.randrange(lo, hi) for _ in range(10)]

NAMES = ["Str", "Agi", "Vit", "Int", "Wis", "Cha", "Loy", "Lck", "Spd", "App"]

def marginal(trials=4000, delta=12, seed=1):
    """For each stat: winrate of (base + delta in that stat) vs the identical base twin."""
    rng = random.Random(seed)
    out = []
    for i in range(10):
        w = 0
        for _ in range(trials):
            base = rand_stats(rng)
            boosted = list(base); boosted[i] += delta
            # play both seats to cancel the defender-tie edge
            if fight(boosted, base, rng): w += 1
            if not fight(base, boosted, rng): w += 1
        out.append(100.0 * w / (2 * trials))
    return out

def fairness(trials=4000, seed=2):
    """Random EQUAL-POWER pairs (different distributions): how far from 50/50? Also seat bias."""
    rng = random.Random(seed)
    w = 0
    for _ in range(trials):
        a, b = rand_stats(rng), rand_stats(rng)
        diff = sum(a) - sum(b)                      # zero out the power difference by moving spare points
        for _ in range(abs(diff)):
            tgt = b if diff > 0 else a
            js = [j for j in range(10) if tgt[j] < 95]
            tgt[random.Random(rng.random()).choice(js)] += 1
        if fight(a, b, rng): w += 1
        if not fight(b, a, rng): w += 1
    return 100.0 * w / (2 * trials)

def power_curve(trials=3000, seed=3):
    """Winrate as a function of power advantage."""
    rng = random.Random(seed)
    buckets = {}
    for _ in range(trials):
        a, b = rand_stats(rng, 10, 85), rand_stats(rng, 10, 85)
        d = sum(a) - sum(b)
        k = max(-4, min(4, d // 40))
        r = 1 if fight(a, b, rng) else 0
        s = buckets.setdefault(k, [0, 0]); s[0] += r; s[1] += 1
    return {k * 40: round(100 * v[0] / v[1], 1) for k, v in sorted(buckets.items())}

if __name__ == "__main__":
    for k, v in [kv.split("=") for kv in sys.argv[1:]]: P[k] = int(v)
    m = marginal()
    print("marginal winrate for +12 in one stat (want all ~equal, >50):")
    for n, v in zip(NAMES, m): print(f"  {n}: {v:.1f}%")
    print(f"  spread: {max(m) - min(m):.1f} pp   mean {statistics.mean(m):.1f}")
    print(f"equal-power fairness (want ~50): {fairness():.1f}%")
    print("power-difference curve:", power_curve())
