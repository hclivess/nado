# tests/pets_ref.py — the SINGLE Python reference for every chance formula in the NADO Pets contract.
# tests/test_pets_contract.py proves the bytecode equals these functions; tests/pets_js_crosscheck_gen.py
# proves static/pets-genes.js (what the browser shows) equals them too. Change a formula in one place only.
import json, hashlib

DIE_PCT = 10   # battle loser's death chance, % (small — most losers survive and are CLAIMED by the winner)

def vm_hash(v):
    return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")

def ref_gene(bh, b, pid):       return vm_hash(bh[b] + bh[b + 1] + pid)
def ref_species(gene):          r = gene % 100; return 1 + (r >= 70) + (r >= 95)
def ref_stat(gene, sp, i):      return vm_hash(gene + 1000 + i) % 60 + 1 + (sp - 1) * 15
def ref_power(gene, sp):        return sum(ref_stat(gene, sp, i) for i in range(10))
def ref_train_roll(bh, th, pid, i): return vm_hash(bh[th] + bh[th + 1] + pid * 16 + i) % 100

def ref_train_ok(roll, cur, sp):
    K = 10 + 30 * sp               # the rarity-scaled limit function: rarer species train easier
    return roll * (K + cur) < 100 * K

def ref_battle(bh, wh, bid, pwa, pwb):
    q = bh[wh] + bh[wh + 1] + bid * 8
    sa, sb = pwa * (75 + vm_hash(q + 1) % 100), pwb * (75 + vm_hash(q + 2) % 100)
    return (sa > sb), (vm_hash(q + 3) % 100 < DIE_PCT)     # (A wins?, loser dies?) — legacy power model

# ---- turn-based battle (2026-07): a probabilistic HP duel, NOT a raw power compare ------------------
# Combat stats derive from the 10 EFFECTIVE stats (base gene stats + trained bonuses):
#   HP  = vitality(#2)*3 + 20      ATK = strength(#0)      DODGE = min(agility(#1), 60)   SPD = speed(#8)
# Initiative: the faster pet swings on even turns (A first if spdA>=spdB, else B). Each turn ONE fighter
# attacks: a hit lands iff hitRoll(0..99) >= the defender's DODGE; damage = ATK*(60+dmgRoll%61)//100 + 1
# (0.6x–1.2x ATK, min 1). Once either faints (HP<=0) all further damage is gated off (the fight is over).
# After CAP_BATTLE turns the higher remaining HP wins (tie -> the defender, pet B). Then the loser's 20%
# death roll. Every roll is HASH(q + offset) over the SAME beacon mix q the old model used, so it stays
# objective, on-chain-recomputable, and differentially verifiable. Returns a full turn log for the UI.
CAP_BATTLE = 20   # MUST equal CAP_BATTLE in tests/test_pets_contract.py (bytecode) and static/pets-genes.js

def _combat(eff):
    return eff[2] * 3 + 20, eff[0], min(eff[1], 60), eff[8]   # HP, ATK, DODGE, SPD

def ref_battle_turns(bh, wh, bid, effA, effB):
    q = bh[wh] + bh[wh + 1] + bid * 8
    h0, a0, d0, s0 = _combat(effA)
    h1, a1, d1, s1 = _combat(effB)
    sf = 0 if s0 >= s1 else 1            # initiative flag: 0 => A swings on even turns
    log = []
    for t in range(CAP_BATTLE):
        cur = sf if t % 2 == 0 else 1 - sf          # who attacks this turn (0=A, 1=B)
        atk = a0 if cur == 0 else a1
        dodge = d1 if cur == 0 else d0              # the DEFENDER's dodge (defender = 1-cur)
        hit_roll = vm_hash(q + t) % 100
        dmg_roll = vm_hash(q + t + 4096) % 61
        alive = 1 if (h0 > 0 and h1 > 0) else 0
        hit = 1 if hit_roll >= dodge else 0
        dmg = hit * alive * (atk * (60 + dmg_roll) // 100 + 1)
        if cur == 0:
            h1 -= dmg
        else:
            h0 -= dmg
        log.append({"t": t, "atk": cur, "hit": hit and alive, "dmg": dmg, "h0": h0, "h1": h1})
    a_wins = h0 > h1
    dies = vm_hash(q + 999999) % 100 < DIE_PCT
    return a_wins, dies, h0, h1, log
