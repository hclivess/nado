"""
The join-split proof path is not natively provable — a REGRESSION GUARD, not a feature test.

FOUND 2026-08-16 while measuring proving cost for shielded contracts. `stark.prove`'s native arena covers
only the `alghash2` and `recursion` backends; anything else reaches `require_native_prover`, which refuses
outside a build or a conformance test (the Rust-only policy, after a Python settle prove starved L1 into a
re-anchor on 2026-08-04). All three join-split modules call `stark.prove` with NO backend argument, so they
take `backend.DEFAULT` — `blake2b` — and therefore cannot prove on a node at all.

That makes the shielded pool's Phase-2 delegated prover (`/exec/prove_transfer`) inoperable in production,
and it predates the shielded-contracts work. This file pins the facts so the gap cannot be closed by
accident and then silently reopened: if someone gives the join-split path an arena-covered backend, the
first check here fails and should be deleted along with this docstring.

Run: python3 tests/test_joinsplit_backend_gap.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.stark import backend as BK

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else " — " + detail))
    if not cond:
        FAILS.append(name)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "execnode", "stark", "stark.py"), encoding="utf8").read()

# What the arena actually covers, read from the source rather than assumed.
m = re.search(r'_arena_covers\s*=\s*getattr\(_b,\s*"name",\s*""\)\s*in\s*\(([^)]*)\)', SRC)
covered = set(re.findall(r'"([a-z0-9]+)"', m.group(1))) if m else set()
check("the native arena's covered backends are readable from stark.py", bool(covered), "regex did not match")
check("the arena does NOT cover the default backend",
      BK.DEFAULT.name not in covered,
      f"DEFAULT={BK.DEFAULT.name} is in {covered} — the gap is closed, delete this file")

for mod in ("joinsplit", "joinsplit_circuit", "joinsplit2"):
    path = os.path.join(ROOT, "execnode", "stark", mod + ".py")
    src = open(path, encoding="utf8").read()
    calls = re.findall(r"stark\.prove\(([^\n]*)", src)
    check(f"{mod}.py calls stark.prove", bool(calls), "no prove call found")
    check(f"{mod}.py still passes NO backend (would refuse on a node)",
          all("backend" not in c for c in calls),
          "a backend argument appeared — if it is arena-covered the gap is fixed, update this file")

# And the constraint this imposes on the new work: the shielded-contract circuit must not inherit it.
CIRCUIT = os.path.join(ROOT, "execnode", "stark", "appnote_circuit.py")
if os.path.exists(CIRCUIT):
    src = open(CIRCUIT, encoding="utf8").read()
    check("the shielded-contract circuit selects an arena-covered backend",
          any(f'"{b}"' in src or f"'{b}'" in src for b in covered),
          "it would inherit blake2b and be born unprovable on a node")
else:
    print("SKIP  the shielded-contract circuit does not exist yet")

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "ALL BACKEND-GAP CHECKS PASSED")
sys.exit(1 if FAILS else 0)
