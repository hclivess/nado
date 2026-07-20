# tests/pets_ref.py — the Python reference for every chance formula in the NADO Pets contract.
#
# It DELEGATES to execnode/games/pets.py, which declares itself "the single source of truth" and is the
# module the deployed bytecode is assembled from. This file used to carry its own copy of all eight
# formulas, hashing with blake2b-256 — a leftover from before the zkVM port, when that WAS the contract's
# hash. The zkVM hashes with alghash over a ~62-bit field, so the reference had been computing genes 256
# bits wide against a chain producing 59-bit ones, and every downstream value (tier, species, stats,
# power, training, battles) differed. tests/pets_js_crosscheck.mjs was failing 854 of 1320 checks, which
# read as "the browser drifted from the chain" — the exact opposite was true: static/pets-genes.js matches
# the chain and this file did not. Verified against a live pet, whose on-chain gene is a field element.
#
# So the formulas now live in ONE place. What remains here are the ADAPTERS the older harnesses want: they
# pass a {index: hash} map plus an index where the contract module takes two hashes, and two legacy names
# (ref_species / ref_battle) predate the current ones.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.games.pets import (                    # noqa: F401 — re-exported for the harnesses
    DIE_PCT, CAP_BATTLE, TIER_CUM, TIER_BASE, TIER_COUNT, STAT_TIER_BONUS,
    roll32, ref_tier, ref_si, ref_stat, ref_power, ref_train_ok,
)
from execnode.games.pets import (
    ref_gene as _ref_gene,
    ref_train_roll as _ref_train_roll,
    ref_battle_turns as _ref_battle_turns,
)
from execnode.stark import alghash
from execnode.stark import field as F


def vm_hash(v):
    """The contract's hash: alghash over the zkVM field, NOT blake2b. Anything derived from a gene has to
    go through this or it lands in a different number space entirely."""
    return alghash.hashn([v % F.P])


def ref_gene(bh, b, pid):
    """gene from a {index: blockhash} map at index b — the shape the harnesses build."""
    return _ref_gene(bh[b], bh[b + 1], pid)


def ref_train_roll(bh, th, pid, i):
    return _ref_train_roll(bh[th], bh[th + 1], pid, i)


def ref_battle_turns(bh, wh, bid, eff_a, eff_b):
    return _ref_battle_turns(bh[wh], bh[wh + 1], bid, eff_a, eff_b)


def ref_species(gene):
    """legacy name: returns the TIER (sp) — callers use it as sp."""
    return ref_tier(gene)


def ref_battle(bh, wh, bid, pwa, pwb):
    """The pre-2026-07-11 power-only battle. Kept because older vectors still reference it; the live
    contract settles with ref_battle_turns, where every stat fights."""
    q = (bh[wh] % F.P + bh[wh + 1] % F.P + bid * 8) % F.P
    sa = pwa * (75 + roll32((q + 1) % F.P) % 100)
    sb = pwb * (75 + roll32((q + 2) % F.P) % 100)
    return (sa > sb), (roll32((q + 3) % F.P) % 100 < DIE_PCT)
