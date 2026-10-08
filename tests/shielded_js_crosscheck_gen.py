#!/usr/bin/env python3
"""Emit reference vectors (JSON on stdout) for tests/shielded_js_crosscheck.mjs, computed by execnode/shielded.py —
the consensus reference the exec node enforces — at the moment the check runs.

Why generated and not pinned: the cross-check once carried hard-coded hashes, and the debrand cutover (6531186b)
renamed DOMAIN_SHIELD "nado.shield" -> "shield-v1" in BOTH the module and its JS port without touching them. JS and
Python stayed byte-identical, yet the check failed 6 of 9 for months, so a real drift would have been hidden behind a
check that was always red. Vectors drawn from the live module cannot go stale that way.
"""
import os
import sys
import tempfile

# BEFORE any execnode import: never the live database, never the live exec state (CLAUDE.md rule 4 — assign, not
# setdefault, and the exec paths are CWD-relative so HOME alone does not cover them).
_tmp = tempfile.mkdtemp(prefix="nado-shielded-xcheck-")
os.environ["HOME"] = _tmp
os.environ["NADO_EXEC_STATE"] = os.path.join(_tmp, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_tmp, "exec_da")
import atexit
import shutil
atexit.register(shutil.rmtree, _tmp, ignore_errors=True)

import json
import random
import contextlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
with contextlib.redirect_stdout(sys.stderr):        # import-time banners (native ML-DSA self-test) are not vectors
    from execnode import shielded as S

rng = random.Random(20261008)
hx = lambda n=32: "%0*x" % (n * 2, rng.getrandbits(n * 8))

V = {"domain": S.DOMAIN_SHIELD, "depth": S.SHIELD_DEPTH, "empty": S.EMPTY_ROOT,
     "owners": [], "notes": [], "sighashes": [], "trees": []}

for pk in ["abcd1234"] + [hx(64) for _ in range(4)]:
    V["owners"].append({"pk": pk, "owner": S.owner_id(pk)})

# values exercise str(int(value)): small, zero, beyond 2^53 (the JS port must stay exact), passed as decimal strings
for value in [0, 1, 100, 10**10, 2**53 + 1, 2**63 - 1, 123456789012345678901234567890]:
    pk, rho = hx(), hx()
    owner = S.owner_id(pk)
    V["notes"].append({"value": str(value), "pk": pk, "owner": owner, "rho": rho,
                       "cm": S.note_commitment(value, owner, rho), "nf": S.note_nullifier(pk, rho)})

for pub in [
    {"nullifiers": ["nfB", "nfA"], "out_commitments": ["cm2", "cm1"], "public_value": -40, "fee": 10},
    {"nullifiers": [hx(), hx()], "out_commitments": [hx()], "public_value": 0, "fee": 0},
    {"nullifiers": [hx()], "out_commitments": [], "public_value": -(10**12), "fee": 3, "withdraw_addr": hx(23)},
    {"nullifiers": [], "out_commitments": [hx(), hx(), hx()], "public_value": 2**60},
    {},
]:
    V["sighashes"].append({"pub": {k: (str(v) if isinstance(v, int) else v) for k, v in pub.items()},
                           "sighash": S.transfer_sighash(pub)})

# trees of every awkward size (empty-padding on the right at several levels); a path + its negative per tree
for n in [1, 2, 3, 4, 5, 7, 8, 9, 16, 17]:
    owner = S.owner_id("abcd1234")
    leaves = [S.note_commitment(10 * (i + 1), owner, "r%d" % i) for i in range(n)]
    root = S.merkle_root(leaves)
    pos = rng.randrange(n)
    path = S.merkle_path(leaves, pos)
    assert S.verify_path(leaves[pos], pos, path, root)
    V["trees"].append({"leaves": leaves, "root": root, "pos": pos, "path": path})

print(json.dumps(V))
