"""AUX (LogUp) CHALLENGES OVER GF(p^D).

β and γ were the last base-field draw in the proof system, and therefore the term that actually bound it. A
LogUp/permutation argument is sound because γ − rlc(tuple) is non-zero for all but a (lookups + rows)/|F|
fraction of γ; at NADO's 2^17 rows a base-field γ puts that near 44 bits, well under FRI's commit phase
(112) and the constraint alphas (126). Every aux_spec circuit inherited it — vm_circuit, logup_bind, and the
settlement path that proves through them.

Lifting the challenge alone is not enough and is worse than useless: everything derived from it is then
extension-valued, so the aux COLUMNS and their constraints have to move too. Each logical aux column is
carried as a TUPLE of extf.DEGREE base columns. These checks pin the parts of that which are silently
breakable — a wrong layout mostly still produces a proof, it just proves less than it claims.

Every number here is derived from extf.DEGREE rather than written down, because a test that hardcodes the
degree stops testing the moment the field moves and instead asserts the OLD field — which is exactly when
you need it most. (At the GF(p^2) -> GF(p^3) migration this file's literal 2s would have failed against
correct code and passed against a half-migrated layout.)
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.stark import stark, soundness, backend as BK

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


# ---------------------------------------------------------------- which layout is active
from execnode.stark import extf as ext2
D = ext2.DEGREE
check(stark.ext_challenges_active(BK.DEFAULT),
      f"the default backend draws aux/alpha challenges from GF(p^{D})")
# The RECURSION backend used to be pinned to the base field because the in-circuit verifier could not do
# extension arithmetic. It can now, and the pin was itself the bug: a prover that chose backend="recursion"
# chose a 64-bit security level. There is ONE authority on the question and every backend follows it.
check(stark.ext_challenges_active(BK.RECURSION) == stark.ext_challenges_active(BK.DEFAULT),
      "the RECURSION backend draws from the SAME field — a backend cannot pick its own security level")
check(stark.ext_challenges_active(None) == stark.ext_challenges_active(BK.DEFAULT),
      "None resolves to the default backend, so prover and verifier agree when it is omitted")

# combine-follows-the-challenge-field, aux-geometry-widening, both-accumulator-limbs-pinned and the
# multiset-equality round trips retired in G9: logup, logup_bind and vm_circuit (the only aux_spec circuits) were
# deleted with the Goldilocks settle proof. The single-authority flag above and the calculator below remain live:
# stark.py, recursive_verify and stark_native still read ext_challenges_active.

# ---------------------------------------------------------------- the calculator reports what the code does
check(soundness.aux_bits(17, ext=True) > soundness.aux_bits(17, ext=False),
      "aux_bits: the ext bound is strictly stronger than the base one")
check(soundness.aux_bits(17, ext=False) < 50,
      f"aux_bits: the OLD base-field bound really was ~44 bits ({soundness.aux_bits(17, ext=False):.1f})")
check(soundness.aux_bits(17, ext=True) > 100,
      f"aux_bits: the lifted bound clears 100 ({soundness.aux_bits(17, ext=True):.1f})")
# Bus-count-independent: lifting to GF(p^D) buys exactly (D-1)*E_BASE bits over the base field, whatever
# the row count and bus count subtract from both sides.
check(abs((soundness.aux_bits(17, ext=True) - soundness.aux_bits(17, ext=False))
          - (D - 1) * soundness.E_BASE) < 1e-9,
      f"aux_bits FOLLOWS the degree: the ext lift is worth exactly (D-1)*E_BASE = "
      f"{(D - 1) * soundness.E_BASE} bits")
check(soundness.E_FIELD() == D * soundness.E_BASE,
      "the calculator's field size is read from extf, not hardcoded to GF(p^2)")
check(soundness.aux_bits(17) == soundness.aux_bits(17, ext=stark.ext_challenges_active()),
      "aux_bits READS the live flag rather than assuming it")

a = soundness.achieved(1, 18, 128, 320, 18, log_degree=17)
check(a["total"] <= a["aux"],
      "the reported PROVABLE bound accounts for the LogUp term (it is no longer omitted)")

print()
if fails:
    print(f"{len(fails)} CHECK(S) FAILED:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("ALL AUX-EXT CHALLENGE CHECKS PASSED")
