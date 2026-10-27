"""The deleted shielded pools still commit, byte for byte, what they committed on every generation-29 state (G9 slice 5).

The Goldilocks field pool, the wide pool and the shielded-contract state were deleted: on generation 29 no entry point
could add a note to any of them, so they were empty at every height. The empty field pool still projected two T_DIGEST
records into EVERY gen-29 exec root (the wide pool and app state projected nothing while empty), so those two are kept as
constants (exec_root_b2.RETIRED_FIELD_ROOT / RETIRED_FIELD_NFSET). The LEGACY BLAKE2b pool is not retired: its
`shielded_transfer` op still appends zero-value notes, so its two digests stay computed from the pool. Pins:
  1. an empty exec state projects the four pool records with the exact values every gen-29 node committed;
  2. its root is protocol.EXEC_GENESIS_ROOT_B2 (the gen-29 exec genesis root), at cursor -1, 0 and a live height;
  3. the field records are the constants, not a computation that could drift: blake2b_hash(["field_nfset"]) is the
     empty spent set's digest, and nothing in execnode/ imports a deleted pool module;
  4. the retired tags 11/12 stay reserved and the snapshot no longer writes the deleted pools.
A reroll may drop the two constants only together with a CHAIN_GENERATION bump.

Run: python3 tests/test_the_retired_pools_commit_their_empty_digests.py
"""
import _harness
HOME = _harness.isolate("nado-test-retired-pools-")
import os, re

import protocol as P
from hashing import blake2b_hash
from execnode import exec_root_b2 as B2
from execnode.state import ExecState

T = _harness.Report()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WANT = {   # the values the four records carried on every gen-29 state (measured on 2cb36e73, 2026-10-28)
    "shield_root": "3494ed478a1577a5dad291006765ffcbf43096c44f1cec9121c302cf6b767f92",
    "shield_nfset": "a96aa2bd2e3510ee04e8cd838054a36328c80584160b3170b6fc242077f56d14",
    "field_root": "12068980620996700996",
    "field_nfset": "caeaaec45c69de5493ca19f3967f5706552b5840fa46f33a33681f97d0f72b37",
}

st = ExecState(os.path.join(HOME, "s.json"))
proj = B2.records_projection(st)
for name, v in WANT.items():
    T.check(f"1. the empty state commits T_DIGEST {name} = {v[:16]}…", proj.get(B2.record_key(B2.T_DIGEST, name, v)) == B2.ONE)
T.check("...and nothing else: the wide pool and app state projected nothing while empty (4 records on 2cb36e73 too)",
        len(proj) == 4, len(proj))
roots = set()
for c in (-1, 0, 10576):
    s = ExecState(os.path.join(HOME, f"c{c}.json"))
    s.cursor = c
    roots.add(s.state_root())
T.check("2. the empty exec root is EXEC_GENESIS_ROOT_B2 at cursor -1, 0 and 10576", roots == {P.EXEC_GENESIS_ROOT_B2}, roots)
T.check("3. the field records are pinned constants",
        (B2.RETIRED_FIELD_ROOT, B2.RETIRED_FIELD_NFSET) == (WANT["field_root"], WANT["field_nfset"])
        and blake2b_hash(["field_nfset"]) == WANT["field_nfset"])
dead = re.compile(r"\b(shielded_field|shielded_wide|shielded_state|joinsplit\w*|appnote_circuit|znote)\b")
hits = []
for d, _dirs, files in os.walk(os.path.join(ROOT, "execnode")):
    for f in files:
        if f.endswith(".py"):
            src = open(os.path.join(d, f)).read()
            hits += [f"{f}: {ln.strip()}" for ln in src.splitlines() if "import" in ln and dead.search(ln)]
T.check("...and nothing in execnode/ imports a deleted pool module", not hits, hits)
T.check("4. tags 11/12 stay reserved", (B2.T_APP_ROOT, B2.T_APP_NULL) == (11, 12))
snap = st._snapshot()
T.check("...and the snapshot writes no deleted pool (the legacy pool stays: it is live)",
        not any(k in snap for k in ("field_pool", "wide_pool", "app_state")) and "shielded" in snap)
T.done()
