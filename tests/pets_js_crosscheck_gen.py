#!/usr/bin/env python3
# tests/pets_js_crosscheck_gen.py — emit reference vectors (JSON on stdout) for pets_js_crosscheck.mjs,
# using the SAME reference functions the contract is differentially tested against.
import sys, json, random
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))
from tests.pets_ref import (vm_hash, ref_gene, ref_species, ref_si, ref_stat, ref_power,
                            ref_train_roll, ref_train_ok, ref_battle, ref_battle_turns,
                            ref_battle_seed, ref_battle_turns_cr)
from execnode.stark import field as F

rng = random.Random(20260710)
hx = lambda v: format(v, "064x")
hatches, trainings, battles, cr_battles = [], [], [], []
for k in range(120):
    pid = rng.randrange(1, 10**9)
    h0, h1 = rng.getrandbits(256), rng.getrandbits(256)
    bh = {0: h0, 1: h1}
    g = ref_gene(bh, 0, pid); sp = ref_species(g)
    hatches.append({"pid": pid, "bh0": hx(h0), "bh1": hx(h1), "gene": str(g), "sp": sp, "si": ref_si(g, sp),
                    "stats": [ref_stat(g, sp, i) for i in range(10)], "pw": ref_power(g, sp)})
    i, cur, spp = rng.randrange(10), rng.randrange(1, 400), rng.randrange(1, 7)   # tiers 1..6
    roll = ref_train_roll(bh, 0, pid, i)
    trainings.append({"pid": pid, "i": i, "bh0": hx(h0), "bh1": hx(h1), "roll": roll,
                      "cur": cur, "sp": spp, "ok": ref_train_ok(roll, cur, spp)})
    bid = rng.randrange(1, 10**9)
    effA = [rng.randrange(1, 120) for _ in range(10)]
    effB = [rng.randrange(1, 120) for _ in range(10)]
    a_wins, dies, bh0, bh1, _log = ref_battle_turns(bh, 0, bid, effA, effB)
    battles.append({"bid": bid, "bh0": hx(h0), "bh1": hx(h1), "effA": effA, "effB": effB,
                    "aWins": a_wins, "dies": dies, "hp0": bh0, "hp1": bh1})
    # commit-reveal battles (wm == 1): seed = HASH(s1 + s2 + bid) from field-sized secrets. Every 4th one uses
    # trained-up stats so a raw hit passes HP_OFF and the contract's one-hit cap is exercised too.
    s1, s2 = rng.randrange(F.P), rng.randrange(F.P)
    hi = k % 4 == 0
    effA = [rng.randrange(1, 120) + (400 if hi else 0) for _ in range(10)]
    effB = [rng.randrange(1, 120) for _ in range(10)]
    a_wins, dies, hp0, hp1, _log = ref_battle_turns_cr(s1, s2, bid, effA, effB)
    cr_battles.append({"bid": bid, "s1": str(s1), "s2": str(s2), "seed": str(ref_battle_seed(s1, s2, bid)),
                       "effA": effA, "effB": effB, "aWins": a_wins, "dies": dies, "hp0": hp0, "hp1": hp1})
print(json.dumps({"hatches": hatches, "trainings": trainings, "battles": battles, "crBattles": cr_battles}))
