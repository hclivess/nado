"""NEGATIVE TESTS MUST BE ABLE TO REACH THEIR ASSERT.

This exists because the same defect occurred SIX times while migrating the challenge field to GF(p^3).

A tamper test perturbs one value and asserts the verifier rejects it. The idiom everyone reaches for is:

    proof["layer0"][0] = (int(proof["layer0"][0]) + 1) % F.P

That is correct only while the value is a base-field scalar. Once the challenge field is an extension, a
layer-0 seam is a TUPLE of limbs, `int(tuple)` raises TypeError, and the perturbation never happens — so the
verifier is never asked to reject anything and the assert on the next line is never reached. The test then
reports a failure whose message ("int() argument must be ... not 'tuple'") looks like a harness problem, and
the property it claimed to cover is silently uncovered.

That is the dangerous half. A tamper test that raises is merely noisy; a tamper test that raises AFTER the
suite has been taught to tolerate it, or one whose failure is read as cosmetic, is a hole with a green label
on it. One of these cost a 6.5-hour gate run, and the sixth was caught only by reading the file before
spending another four hours on it.

The fix in every case is the same three lines:

    def _bump(v):
        if isinstance(v, tuple):
            return ((int(v[0]) + 1) % F.P,) + tuple(v[1:])
        return (int(v) + 1) % F.P

So this test is a lint, not a proof: it refuses the raw `int(<seam>)` shape anywhere in tests/. It cannot tell
a correct tamper from an incorrect one in general — it just makes the specific mistake that actually happened,
six times, impossible to reintroduce without deleting this file.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# `int(` applied directly to something that indexes a seam/proof structure. Deliberately narrow: it targets the
# shape that recurred, not every use of int() in the suite.
BAD = re.compile(r"int\(\s*[A-Za-z_][A-Za-z0-9_]*\s*\[[^)]*\]\s*\)")

# Names that mark a value as living in the challenge field — a seam, a layer-0 element, a fold public part.
FIELDY = ("layer0", "seam", "fri_public", "public_part", "alphas", "challenge", "betas", "gammas")

offenders = []
for fn in sorted(os.listdir(HERE)):
    if not (fn.startswith("test_") and fn.endswith(".py")):
        continue
    if fn == os.path.basename(__file__):
        continue
    path = os.path.join(HERE, fn)
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            stripped = line.strip()
            if stripped.startswith("#") or not BAD.search(line):
                continue
            if not any(k in line for k in FIELDY):
                continue
            # a _bump-style helper guarded by isinstance is exactly the correct form
            if "isinstance" in line:
                continue
            offenders.append(f"{fn}:{lineno}: {stripped}")

print(f"scanned {len([f for f in os.listdir(HERE) if f.startswith('test_') and f.endswith('.py')])} test files")
if offenders:
    print(f"FAIL  {len(offenders)} raw int(<seam>) tamper site(s) — these cannot reach their assert at D>1:")
    for o in offenders:
        print("  - " + o)
    print("\n  fix: bump the first limb via a _bump() helper that checks isinstance(v, tuple).")
    sys.exit(1)
print("PASS  no tamper site applies int() directly to a challenge-field value")
print("ALL TAMPER-HELPER CHECKS PASSED")
