#!/usr/bin/env python3
# tests/pets_js_crosscheck_gen.py — emit reference vectors (JSON on stdout) for pets_js_crosscheck.mjs,
# using the SAME reference functions the contract is differentially tested against.
import sys, json, random
sys.path.insert(0, "/root/nado")
from tests.pets_ref import (vm_hash, ref_gene, ref_species, ref_stat, ref_power,
                            ref_train_roll, ref_train_ok, ref_battle)

rng = random.Random(20260710)
hx = lambda v: format(v, "064x")
hatches, trainings, battles = [], [], []
for k in range(120):
    pid = rng.randrange(1, 10**9)
    h0, h1 = rng.getrandbits(256), rng.getrandbits(256)
    bh = {0: h0, 1: h1}
    g = ref_gene(bh, 0, pid); sp = ref_species(g)
    hatches.append({"pid": pid, "bh0": hx(h0), "bh1": hx(h1), "gene": str(g), "sp": sp,
                    "stats": [ref_stat(g, sp, i) for i in range(10)], "pw": ref_power(g, sp)})
    i, cur, spp = rng.randrange(10), rng.randrange(1, 400), rng.randrange(1, 4)
    roll = ref_train_roll(bh, 0, pid, i)
    trainings.append({"pid": pid, "i": i, "bh0": hx(h0), "bh1": hx(h1), "roll": roll,
                      "cur": cur, "sp": spp, "ok": ref_train_ok(roll, cur, spp)})
    bid, pwa, pwb = rng.randrange(1, 10**9), rng.randrange(200, 900), rng.randrange(200, 900)
    a_wins, dies = ref_battle(bh, 0, bid, pwa, pwb)
    q = h0 + h1 + bid * 8
    sa, sb = pwa * (75 + vm_hash(q + 1) % 100), pwb * (75 + vm_hash(q + 2) % 100)
    battles.append({"bid": bid, "bh0": hx(h0), "bh1": hx(h1), "pwA": pwa, "pwB": pwb,
                    "aWins": a_wins, "dies": dies, "scoreA": sa, "scoreB": sb})
print(json.dumps({"hatches": hatches, "trainings": trainings, "battles": battles}))
