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

from execnode.stark import (stark, extf as ext2, logup, logup_bind as LB, vm_circuit as VC,
                            soundness, backend as BK, field as F)

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


# ---------------------------------------------------------------- which layout is active
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

# ---------------------------------------------------------------- combine follows the challenge field
base = logup.combine([1, 2, 3], 5)
lifted = logup.combine([1, 2, 3], ext2.lift(5))
check(lifted == ext2.lift(base),
      "combine over a LIFTED base gamma equals the base result (the ext path is a faithful extension)")
check(isinstance(logup.combine([1, 2, 3], (5, 7)), tuple),
      "combine with a true ext gamma returns an ext element")

# ---------------------------------------------------------------- geometry doubles, degree does not
check(LB._aux_spec(ext=True)["num_aux"] == D * LB._aux_spec(ext=False)["num_aux"],
      f"logup_bind: each logical aux column becomes {D} base columns under ext")
check(VC._aux_spec([], ext=True)["num_aux"] == D * VC._aux_spec([], ext=False)["num_aux"],
      "vm_circuit: same widening")
check(VC.W_TOTAL_EXT == VC.W_MAIN + D * VC.NUM_AUX,
      f"vm_circuit: the ext trace width is main + {D}*aux")
check(len(VC.transitions(ext=True)) == len(VC.transitions(ext=False)),
      "the constraint COUNT is unchanged — this is a field change, not a circuit redesign")

# ---------------------------------------------------------------- BOTH accumulator limbs are pinned
# The whole statement is "the buses balance", expressed as Z = 0 at both ends. Under ext, Z is a GF(p^2)
# value: pinning only the lo limb would let a prover park an unbalanced bus in the hi limb and still satisfy
# the boundary. That is a total loss of the argument, and it produces perfectly valid-looking proofs.
lb_bnd = LB._boundaries(64, ext=True)
acc_limbs = [LB._aux(LB._LOG_ACC, i) for i in range(D)]
for row in (0, 63):
    check(all(any(b == (row, c, 0) for b in lb_bnd) for c in acc_limbs),
          f"logup_bind: ALL {D} limbs of the accumulator are pinned at row {row}")

vc_bnd = VC._boundaries(64, ext=True)
for row in (0, 63):
    check(all(any(b == (row, c, 0) for b in vc_bnd) for c in VC._aux_limbs(VC.Z)),
          f"vm_circuit: ALL {D} limbs of Z are pinned at row {row}")

# The base layout must be untouched — the recursion backend still relies on it.
lb_base = LB._boundaries(64, ext=False)
check(lb_base == [(0, LB.ACC, 0), (63, LB.ACC, 0)],
      "the base layout's boundaries are unchanged (RECURSION still proves through them)")

# ---------------------------------------------------------------- the argument still works, both layouts
A = [(1, 2, 3), (4, 5, 6), (7, 8, 9), (4, 5, 6)]
for name, bk in (("ext (default)", None), ("base (recursion)", BK.RECURSION)):
    proof = LB.prove_multiset_eq(A, list(reversed(A)), num_queries=8, backend=bk)
    ok, why = LB.verify_multiset_eq(proof, expect_n=len(A), num_queries=8, backend=bk)
    check(ok, f"{name}: a true multiset equality verifies ({why})")

    bad = LB.prove_multiset_eq(A, [(9, 9, 9), (4, 5, 6), (7, 8, 9), (4, 5, 6)], num_queries=8, backend=bk)
    ok2, _ = LB.verify_multiset_eq(bad, expect_n=len(A), num_queries=8, backend=bk)
    check(not ok2, f"{name}: an UNEQUAL multiset is rejected (the argument still binds)")

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
