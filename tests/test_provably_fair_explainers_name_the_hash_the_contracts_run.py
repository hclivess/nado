"""THE PROVABLY-FAIR EXPLAINERS NAME THE HASH THE CONTRACTS RUN.

A fairness explainer is a promise a player can check by hand, so it must describe what the contract computes. Generation
29's contracts run on the 256-bit zkvm2: their HASH is zkvm2.hash_words (BLAKE2s), sums wrap at 2^256, and a roll reads
the LO32 window. Until 2026-10-28 farkle.html still told players a die was
`LO32(alghash((blockhash(H) + blockhash(H+1) + seat·1000 + nonce·10 + k) mod P)) mod 6 + 1` — the gen-28 field VM's hash
and modulus, neither of which exists on the chain any more (G9 deleted them).

  1. no player-facing text (static/*.html outside <script>/<style>, and every string of static/i18n/*.json and
     static/i18n_games/*.json) names alghash, Goldilocks or "mod P" — with no exception (the autogame Daily Gauntlet's road, the
     last gen-28 alghash, moved to the VM hash on 2026-10-28);
  2. farkle's explainer states the gen-29 formula, and that formula, computed as written, is the contract reference's
     die (execnode/games/farkle.roll_dice) on random block hashes.

Run: python3 tests/test_provably_fair_explainers_name_the_hash_the_contracts_run.py
"""
import _harness
HOME = _harness.isolate("nado-test-fair-explainers-")

import glob
import json
import os
import random
import re

from execnode import zkvm2
from execnode.games import farkle

T = _harness.Report()
STATIC = os.path.join(_harness.ROOT, "static")
RETIRED = re.compile(r"(?i)alghash|goldilocks|\bmod P\b")
EXEMPT = set()     # none: the Daily Gauntlet's road left gen-28 alghash on 2026-10-28


def page_text(path):
    s = open(path, encoding="utf-8", errors="replace").read()
    return re.sub(r"(?is)<(script|style)\b.*?</\1>", "", s)


def strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)
    elif isinstance(o, str):
        yield o


# ---- 1: no player-facing text names the retired hash ------------------------------------------------------------------
hits = []
for f in sorted(glob.glob(os.path.join(STATIC, "*.html"))):
    if os.path.basename(f) not in EXEMPT:
        hits += [f"{os.path.basename(f)}: {m.group(0)}" for m in RETIRED.finditer(page_text(f))]
for f in sorted(glob.glob(os.path.join(STATIC, "i18n", "*.json")) + glob.glob(os.path.join(STATIC, "i18n_games", "*.json"))):
    if os.path.basename(f) not in EXEMPT:
        hits += [f"{os.path.basename(f)}: {s[:80]}" for s in strings(json.load(open(f, encoding="utf-8"))) if RETIRED.search(s)]
T.check("1. no fairness text a player reads names alghash, Goldilocks or mod P", not hits, hits[:5])

# ---- 2: farkle's formula is the contract's die ----------------------------------------------------------------------
FORMULA = "LO32(BLAKE2s((blockhash(H) + blockhash(H+1) + seat·1000 + nonce·10 + k) mod 2^256)) mod 6 + 1"
T.check("2a. farkle's explainer states the gen-29 die formula", FORMULA in page_text(os.path.join(STATIC, "farkle.html")))


def die_as_explained(bh0, bh1, seat, nonce, k):
    return (zkvm2.hash_words([(bh0 + bh1 + seat * 1000 + nonce * 10 + k) % (1 << 256)]) & 0xFFFFFFFF) % 6 + 1


rnd = random.Random(29)
bad = []
for _ in range(300):
    bh0, bh1 = rnd.getrandbits(256), rnd.getrandbits(256)
    seat, nonce = rnd.randrange(1 << 32), rnd.randrange(64)
    want = farkle.roll_dice(bh0, bh1, seat, nonce, 6)
    got = [die_as_explained(bh0, bh1, seat, nonce, k) for k in range(6)]
    if got != want:
        bad.append((hex(bh0)[:12], seat, nonce, got, want))
T.check("2b. the formula, computed as written, is farkle.roll_dice's die on 300 random rolls", not bad, bad[:2])

T.done("ALL PASS — the provably-fair explainers name the hash the contracts run")
