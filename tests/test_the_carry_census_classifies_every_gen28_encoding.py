"""The G5 carry census classifies every gen-28 encoding in contract storage the way the carry must treat it.

tools/carry_census.py decides, per slot, what the gen-29 carry re-encodes (doc/stwo/g5-carry.md): a value that is a
registry digest is remapped; a key that is (F*2^32 + digest) mod P is re-keyed; a key that is a VM-hash output is
re-derived through the contract's index; plain keys (small, or F*2^32 + id with a field tag up to 2^20) carry
unchanged. A wrong class is a lost or a corrupted slot at genesis, so each class is pinned with built values:
  1. a value equal to a registry digest is "digest"; a large non-digest value (an amount: 1 NADO = 10^10) is "big";
  2. F*2^32 + id is "plain", including a LARGE field tag (tictactoe stores under F = 1050 — the census's first cut-off
     of 1024 misread those two slots as hash keys, 2026-10-25);
  3. (F*2^32 + digest) mod P is "F|digest", for F = 0 and the autogame's OWNRUN = 51;
  4. a key that is a digest itself is "digest"; an alghash-sized key matching nothing is "hash";
  5. the tool refuses the live exec_state.json path.
Run: python3 tests/test_the_carry_census_classifies_every_gen28_encoding.py
"""
import _harness
HOME = _harness.isolate("nado-test-carry-census-")
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(_harness.ROOT, "tools"))
import carry_census as CC

T = _harness.Report()
P = CC.P
d1, d2 = 0x9E3779B97F4A7C15 % P, 0xC2B2AE3D27D4EB4F % P            # two digest-sized registry keys
digests = {d1, d2}
slots = {
    str((5 << 32) + 7): str(d1),                  # owner digest stored as a value
    str((3 << 32) + 1): str(133560266192),        # an amount (13.36 NADO)
    str((1050 << 32) + 20728): "43873",           # tictactoe's large field tag
    str(((51 << 32) + d2) % P): "9",              # autogame OWNRUN slot over a digest
    str(((0 << 32) + d1) % P): "1",               # F = 0 composite over a digest (== the digest itself)
    str(0xB5AD4ECEDA1CE2A9): "2",                 # a hash key (alghash-sized, matches nothing)
    "3": "0",
}
cl = CC.classify(slots, digests)
T.check("1. a value that is a registry digest is a digest", cl[(5 << 32) + 7] == ("plain", "digest"), cl[(5 << 32) + 7])
T.check("1. a large non-digest value (an amount) is big", cl[(3 << 32) + 1] == ("plain", "big"), cl[(3 << 32) + 1])
T.check("2. F*2^32 + id with a large field tag (1050) is plain", cl[(1050 << 32) + 20728][0] == "plain")
T.check("2. a small key is plain", cl[3] == ("plain", "small"))
T.check("3. (OWNRUN*2^32 + digest) mod P is F|digest", cl[((51 << 32) + d2) % P][0] == "F|digest")
T.check("4. a key equal to a digest is a digest", cl[d1][0] == "digest")
T.check("4. an alghash-sized key matching nothing is a hash key", cl[0xB5AD4ECEDA1CE2A9][0] == "hash")
r = subprocess.run([sys.executable, os.path.join(_harness.ROOT, "tools", "carry_census.py"),
                    "/srv/nado-home/nado/exec_state.json"], capture_output=True, text=True, timeout=120)
T.check("5. the tool refuses the live exec_state.json", r.returncode != 0 and "refusing the LIVE" in (r.stderr + r.stdout),
        (r.returncode, r.stderr[-200:]))
T.done("ALL PASS — the carry census classifies every gen-28 encoding")
