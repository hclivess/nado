# tests/pets_ref.py — the SINGLE Python reference for every chance formula in the NADO Pets contract.
# tests/test_pets_contract.py proves the bytecode equals these functions; tests/pets_js_crosscheck_gen.py
# proves static/pets-genes.js (what the browser shows) equals them too. Change a formula in one place only.
import json, hashlib

DIE_PCT = 10   # battle loser's death chance, % (small — most losers survive and are CLAIMED by the winner)

def vm_hash(v):
    return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")

def ref_gene(bh, b, pid):       return vm_hash(bh[b] + bh[b + 1] + pid)

# ── rarity: SIX tiers on a geometric ~4.5x decay (Common..Omega). The tier roll is a fresh 100000-wide gene
# slice, independent of the species pick, so odds are decoupled from how many animals live in each tier.
# TIER_CUM = cumulative thresholds; sp = 1 + how many you clear. Odds: 78 / 17 / 3.9 / 0.85 / 0.21 / 0.04 %.
TIER_CUM   = [78000, 95000, 98900, 99750, 99960]          # mod 100000
TIER_BASE  = {1: 1, 2: 205, 3: 570, 4: 839, 5: 964, 6: 1001}  # first si of each tier's roster band
TIER_COUNT = {1: 204, 2: 365, 3: 269, 4: 125, 5: 37, 6: 7}    # animals in each tier (sum = 1007)
STAT_TIER_BONUS = 6                                         # +6/stat per tier (Elo-validated ~76% adjacent)

def ref_tier(gene):
    rt = vm_hash(gene + 555) % 100000
    return 1 + sum(1 for t in TIER_CUM if rt >= t)
def ref_species(gene):          return ref_tier(gene)   # legacy name: returns the TIER (sp) — callers use it as sp
def ref_si(gene, sp):           return TIER_BASE[sp] + vm_hash(gene + 777) % TIER_COUNT[sp]
def ref_stat(gene, sp, i):      return vm_hash(gene + 1000 + i) % 60 + 1 + (sp - 1) * STAT_TIER_BONUS
def ref_power(gene, sp):        return sum(ref_stat(gene, sp, i) for i in range(10))
def ref_train_roll(bh, th, pid, i): return vm_hash(bh[th] + bh[th + 1] + pid * 16 + i) % 100

def ref_train_ok(roll, cur, sp):
    K = 10 + 30 * sp               # the rarity-scaled limit function: rarer species train easier
    return roll * (K + cur) < 100 * K

def ref_battle(bh, wh, bid, pwa, pwb):
    q = bh[wh] + bh[wh + 1] + bid * 8
    sa, sb = pwa * (75 + vm_hash(q + 1) % 100), pwb * (75 + vm_hash(q + 2) % 100)
    return (sa > sb), (vm_hash(q + 3) % 100 < DIE_PCT)     # (A wins?, loser dies?) — legacy power model

# ---- turn-based battle v2 (2026-07-11): EVERY stat fights, and power = Σstats is a TRUE score --------
# Constants frozen by Monte-Carlo balancing (scratch balance_sim.py): across stat ranges 5-60 / 20-78 /
# 30-95 the marginal win-rate of +12 in ANY single stat sits in a ≤4.7pp band (~53-58%), equal-power pets
# split 50.3/49.7, and win-rate rises monotonically with the power difference. Per-stat combat roles:
#   #0 Strength  -> damage        dmg = (50 + str + app//4) * (60 + dmgRoll%61) // 100 + 1
#   #1 Agility   -> dodge         contested hit: hitRoll * (15 + 2*int_att + agi_def) < 100*(15 + 2*int_att)
#   #2 Vitality  -> HP            maxHP = 20 + vit*3 + app
#   #3 Intellig. -> accuracy      (the 2*int term above — offsets dodge, never saturates)
#   #4 Wisdom    -> mitigation    dmg = dmg * 90 // (90 + wis_def)
#   #5 Charisma  -> intimidation  dmg = max(1, dmg - cha_def//2)
#   #6 Loyalty   -> regen         each turn both heal loy//4, capped at their max HP (alive-gated)
#   #7 Luck      -> crit          critRoll%100 < luck  =>  damage DOUBLES (before mitigation)
#   #8 Speed     -> turn share    P(A owns a turn) = (spdA+60)/(spdA+spdB+120)
#   #9 Appetite  -> bulk + bite   +1 HP each and app//4 joins the damage base (it eats real NADO for this)
# Winner = higher remaining FRACTION of HP (integer cross-multiply h0*maxB > h1*maxA; tie -> defender),
# so HP is survival, not raw score. KO gates everything off as before; the loser's death roll is unchanged.
# Rolls per turn: owner HASH(q+t+8192), hit HASH(q+t), dmg HASH(q+t+4096), crit HASH(q+t+12288).
CAP_BATTLE = 12   # MUST equal CAP_BATTLE in tests/test_pets_contract.py (bytecode) and static/pets-genes.js
                  # (12 turns keeps the unrolled deploy blob under the 64 KiB per-tx DA cap)

def ref_battle_turns(bh, wh, bid, effA, effB):
    q = bh[wh] + bh[wh + 1] + bid * 8
    hA = 20 + effA[2] * 3 + effA[9]
    hB = 20 + effB[2] * 3 + effB[9]
    h0, h1 = hA, hB
    span = effA[8] + effB[8] + 120
    log = []
    for t in range(CAP_BATTLE):
        alive = 1 if (h0 > 0 and h1 > 0) else 0
        cur = 0 if vm_hash(q + t + 8192) % span < effA[8] + 60 else 1     # speed: who owns this turn
        A, B = (effA, effB) if cur == 0 else (effB, effA)
        acc = 15 + 2 * A[3]
        hit = 1 if vm_hash(q + t) % 100 * (acc + B[1]) < 100 * acc else 0
        dmg = (50 + A[0] + A[9] // 4) * (60 + vm_hash(q + t + 4096) % 61) // 100 + 1
        crit = 1 if vm_hash(q + t + 12288) % 100 < A[7] else 0
        dmg = dmg + crit * dmg
        dmg = dmg * 90 // (90 + B[4])
        dmg = max(1, dmg - B[5] // 2)
        dmg = dmg * hit * alive
        if cur == 0:
            h1 -= dmg
        else:
            h0 -= dmg
        h0 = min(hA, h0 + alive * (effA[6] // 4))
        h1 = min(hB, h1 + alive * (effB[6] // 4))
        log.append({"t": t, "atk": cur, "hit": hit and alive, "crit": crit and hit and alive,
                    "dmg": dmg, "h0": h0, "h1": h1})
    a_wins = h0 * hB > h1 * hA           # remaining FRACTION decides (tie -> defender)
    dies = vm_hash(q + 999999) % 100 < DIE_PCT
    return a_wins, dies, h0, h1, log
