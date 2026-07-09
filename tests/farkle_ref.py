#!/usr/bin/env python3
"""farkle_ref.py — reference Farkle ("Ten Thousand") engine.

Python twin of /root/nado/static/farkle-engine.js. Identical rules/results.
Drives on-chain contract differential testing.

SCORING RULES:
  single 1 = 100; single 5 = 50.
  three of a kind: three 1s = 1000; three of face F (2..6) = F*100.
  four of a kind  = 2x the three-of-a-kind value.
  five of a kind  = 4x the three-of-a-kind value.
  six of a kind   = 8x the three-of-a-kind value.
  straight 1-2-3-4-5-6 (all six dice) = 1500.
  2,3,4,6 alone score nothing.
"""

import hashlib
import random


# ---------------------------------------------------------------------------
# dieFromHash(seed_hex, index) -> die in 1..6, deterministic & portable.
#
# SCHEME (must match farkle-engine.js byte-for-byte):
#   msg  = ascii( seed_hex + ":" + decimal(index) )
#   dig  = SHA-256(msg)                       # 32 bytes
#   u32  = big-endian uint32 of dig[0..4)     # dig[0]<<24|dig[1]<<16|dig[2]<<8|dig[3]
#   die  = (u32 mod 6) + 1
# ---------------------------------------------------------------------------
def die_from_hash(seed_hex, index):
    msg = (seed_hex + ":" + str(index)).encode("ascii")
    dig = hashlib.sha256(msg).digest()
    u32 = (dig[0] << 24) | (dig[1] << 16) | (dig[2] << 8) | dig[3]
    return (u32 % 6) + 1


def _three_value(face):
    return 1000 if face == 1 else face * 100


# ---------------------------------------------------------------------------
# score_roll(dice) -> dict(score, scoring_dice, all_score)
# ---------------------------------------------------------------------------
def score_roll(dice):
    counts = [0] * 7  # index 1..6
    for d in dice:
        counts[d] += 1

    # Straight 1-2-3-4-5-6 (needs all six).
    if len(dice) == 6 and all(counts[f] == 1 for f in range(1, 7)):
        return {"score": 1500, "scoring_dice": [1, 2, 3, 4, 5, 6], "all_score": True}

    score = 0
    scoring_dice = []
    for f in range(1, 7):
        c = counts[f]
        if c == 0:
            continue
        if c >= 3:
            base = _three_value(f)
            mult = {3: 1, 4: 2, 5: 4, 6: 8}[c]
            score += base * mult
            scoring_dice.extend([f] * c)
        else:
            if f == 1:
                score += c * 100
                scoring_dice.extend([1] * c)
            elif f == 5:
                score += c * 50
                scoring_dice.extend([5] * c)

    all_score = score > 0 and len(scoring_dice) == len(dice)
    return {"score": score, "scoring_dice": scoring_dice, "all_score": all_score}


# ---------------------------------------------------------------------------
# auto_play_turn(rng, threshold) -> banked score (0 on bust).
# rng() returns a uniform die 1..6.
# ---------------------------------------------------------------------------
def auto_play_turn(rng, threshold):
    turn_total = 0
    dice_left = 6
    while True:
        roll = [rng() for _ in range(dice_left)]
        r = score_roll(roll)
        if r["score"] == 0:
            return 0  # BUST
        turn_total += r["score"]
        if turn_total >= threshold:
            return turn_total  # BANK
        remaining = dice_left - len(r["scoring_dice"])
        dice_left = 6 if remaining == 0 else remaining  # hot dice -> fresh 6


# ---------------------------------------------------------------------------
# Monte-Carlo payout math.
# ---------------------------------------------------------------------------
def montecarlo(thresholds, turns_per_threshold, rng, house_target=0.975):
    rows = []
    for T in thresholds:
        busts = 0
        total = 0
        scores = [0] * turns_per_threshold
        for i in range(turns_per_threshold):
            s = auto_play_turn(rng, T)
            if s == 0:
                busts += 1
            total += s
            scores[i] = s
        n = turns_per_threshold
        mean_score = total / n
        bust_prob = busts / n
        scores.sort()
        p999 = scores[min(n - 1, int(0.999 * (n - 1)))]
        suggested_k = round(mean_score / house_target)
        house_edge = 1 - mean_score / suggested_k
        rows.append({
            "T": T, "bust_prob": bust_prob, "mean_score": mean_score,
            "suggested_k": suggested_k, "house_edge": house_edge, "p999": p999,
        })
    return rows


# ---------------------------------------------------------------------------
# Self-test + CLI: `python3 farkle_ref.py`
# ---------------------------------------------------------------------------
def _assert_eq(a, b, msg):
    if a != b:
        raise AssertionError(f"ASSERT FAIL {msg}: {a!r} != {b!r}")


def self_test():
    _assert_eq(score_roll([1, 1, 1, 5, 5, 2])["score"], 1100, "[1,1,1,5,5,2]")
    _assert_eq(score_roll([1, 2, 3, 4, 5, 6])["score"], 1500, "straight")
    _assert_eq(score_roll([2, 2, 2, 3, 4, 6])["score"], 200, "[2,2,2,3,4,6]")
    _assert_eq(score_roll([5])["score"], 50, "[5]")
    _assert_eq(score_roll([2, 3, 4, 6])["score"], 0, "bust")
    _assert_eq(score_roll([1, 1, 1, 1, 1, 1])["score"], 8000, "six 1s")
    _assert_eq(score_roll([6, 6, 6, 6])["score"], 1200, "four 6s")
    _assert_eq(score_roll([5, 5, 5, 5])["score"], 1000, "four 5s")
    _assert_eq(score_roll([2, 2, 2, 2, 2])["score"], 800, "five 2s")
    _assert_eq(score_roll([1, 5])["score"], 150, "[1,5]")
    _assert_eq(score_roll([1, 2, 3, 4, 5, 6])["all_score"], True, "straight allScore")
    _assert_eq(score_roll([1, 1, 1, 5, 5, 2])["all_score"], False, "not hot")
    _assert_eq(score_roll([1, 1, 1, 5, 5, 5])["all_score"], True, "hot dice")
    _assert_eq(die_from_hash("deadbeef", 0), die_from_hash("deadbeef", 0), "die determinism")
    print("scoreRoll/dieFromHash self-test: PASS")


def die_samples(seed_hex, n):
    return [die_from_hash(seed_hex, i) for i in range(n)]


def format_table(rows, house_target):
    print("")
    print(f"Monte-Carlo payout table (house target payout = {house_target} S)")
    print("T      bustProb   E[score]  suggestedK  houseEdge   maxScore(99.9pct)")
    for r in rows:
        print(
            f"{r['T']:>5}  "
            f"{r['bust_prob']:>8.4f}  "
            f"{r['mean_score']:>8.2f}  "
            f"{r['suggested_k']:>10}  "
            f"{r['house_edge'] * 100:>8.2f}%  "
            f"{r['p999']:>10}"
        )


def main():
    self_test()
    print("dieFromHash('nado-farkle', 0..9):", ",".join(str(x) for x in die_samples("nado-farkle", 10)))
    thresholds = [300, 400, 500, 600, 750, 1000, 1250, 1500, 2000, 3000]
    TURNS = 300000
    rng = lambda: random.randint(1, 6)
    rows = montecarlo(thresholds, TURNS, rng)
    format_table(rows, 0.975)
    print("")
    print("PASS")


if __name__ == "__main__":
    main()
