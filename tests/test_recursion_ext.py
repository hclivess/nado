"""RECURSION OVER GF(p^2) PROOFS — the end-to-end gate for the extension port.

The recursion path was pinned to base-field arithmetic long after FRI, the DEEP point and the constraint
alphas had been lifted, which left anything destined to be FOLDED carrying the OLD ~47-bit commit bound.
That is why SETTLE_PROOF_RECURSIVE is gated off: accepting folded settlement proofs while the main path
claims 109-112 bits would make the fold the weakest link in consensus.

This exercises the whole stack on an EXTENSION inner proof: the one-permutation ext Merkle leaf
(alghash2.rleaf_ext), fri_verify's ext carries and per-layer leaf frames, air_ir lowering extension-valued
constraints as output PAIRS, and rowcomp_verify's extension composition check.

The RECURSION backend now draws from GF(p^2) like every other — the exclusion in
stark.ext_challenges_active is gone, which is what actually took folded proofs from ~47 bits to 109. These
checks are the gate that made that flip safe to throw.
"""
import sys, os, random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.stark import (fri, field as F, backend as BK, stark, extf as ext2, air_ir,
                            fri_verify as FV, logup_bind as LB, alghash2 as a2)

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


# ---------------------------------------------------------------- the leaf that unblocked it all
# node(leaf(a0), leaf(a1)) costs THREE in-circuit permutation blocks and needs the second block's digest
# constrained equal to a witness sibling — a linkage the path machinery has no way to express. Packing both
# limbs into the single existing frame makes an extension leaf cost exactly what a base leaf costs.
from execnode.stark.recursion import _blocks_for

_blk, _, _, digest = _blocks_for((7, 11), 0, [])
check(tuple(digest) == tuple(a2.rleaf_ext(7, 11)),
      "the in-circuit ext leaf block reproduces the native rleaf_ext digest bit-for-bit")
check(len(_blk) == len(_blocks_for(7, 0, [])[0]),
      "an ext leaf costs the SAME number of permutation blocks as a base leaf (one, not three)")
check(a2.rleaf_ext(7, 0) != a2.rleaf(7),
      "an ext leaf with a zero hi limb is still a DISTINCT frame from a base leaf")

# ---------------------------------------------------------------- the IR lowers extension constraints
# Widths DERIVED, not written down. These were the literals 12 and 9 — correct at degree 2 and silently
# out of range at degree 3, where the aux block is D*NUM_AUX_BASE wide. A test that hardcodes the field is
# asserting the OLD field the moment the field moves, which is exactly when it should be catching things.
D = ext2.DEGREE
W_EXT = LB.W_MAIN + LB.NUM_AUX_EXT
W_BASE = LB.W_MAIN + LB.NUM_AUX_BASE
prog_ext = air_ir.build_program(LB._transitions(True), W_EXT, 0, 2, ext_chal=True)
prog_base = air_ir.build_program(LB._transitions(False), W_BASE, 0, 2)
check(len(prog_ext["ext_pairs"]) == 3,
      f"each extension-valued constraint lowers to a GROUP of {D} SSA outputs")
check(prog_ext["C"] == 2 * D and prog_base["C"] == 2,
      f"each logical challenge occupies {D} CHAL leaves under ext")
check(air_ir.program_degree(prog_ext) == air_ir.program_degree(prog_base),
      "lowering to limbs does NOT raise the program degree (max_degree and blowup are unaffected)")

# The lowered program must agree with the constraint closures it was traced from, or the in-circuit
# composition proves a different statement than the native one.
random.seed(3)
A = [(i, i * 2, i * 3) for i in range(8)]
rows, T = LB._trace(A, list(reversed(A)))
chals = [tuple(random.randrange(F.P) for _ in range(D)) for _ in range(2)]
aux = LB._build_aux_ext(rows, chals)
full = [list(rows[i]) + [aux[k][i] for k in range(LB.NUM_AUX_EXT)] for i in range(T)]
flat_ch = [limb for ch in chals for limb in ch]
cons = LB._transitions(True)
agree = True
for i in range(T - 1):
    direct = []
    for con in cons:
        v = con(full[i], full[i + 1], [], chals)
        # Every limb, not just two. This read v[0], v[1] — correct at degree 2 and a SILENT truncation at
        # any higher degree: the comparison would then pass while the third limb of every constraint went
        # unchecked, which is precisely the failure this check exists to catch.
        direct += [x % F.P for x in v]
    if [x % F.P for x in air_ir.eval_program_point(prog_ext, full[i], full[i + 1], [], flat_ch)] != direct:
        agree = False
        break
check(agree, "the lowered SSA == the constraint closures on every row of a real extension trace")
check(all(v == 0 for v in air_ir.eval_program_point(prog_ext, full[0], full[1], [], flat_ch)),
      "an honest extension trace satisfies the lowered constraints (all outputs zero)")

# ---------------------------------------------------------------- a GF(p^2) FRI proof folds in-circuit
N, DEG, NQ = 32, 4, 3
random.seed(5)
coef = [random.randrange(F.P) for _ in range(DEG)] + [0] * (N - DEG)
off = F.GENERATOR
ev = [F.poly_eval(coef, x) for x in F.domain(N, off)]
p = fri.prove(ev, off, blowup=N // DEG, num_queries=NQ, backend=BK.RECURSION)
check(bool(p.get("ext")), "the inner FRI proof really is extension-valued (else this proves nothing)")

rp, pub = FV.prove_fold([p], num_queries_inner=NQ, num_queries_outer=8)
ok, why = FV.verify_fold(rp, pub, expect_inner=NQ, expect_outer=8)
check(ok, f"a GF(p^2) FRI proof folds in-circuit and the fold VERIFIES ({why})")

# The layout is derived from the INNER proofs' public parts, never from the fold prover — otherwise a prover
# could present extension work and have it checked under the cheaper base-field AIR.
check(pub["publics"][0].get("ext") is True,
      "ext/ext0 travel in the PUBLIC statement, so the verifier derives the layout itself")

# Mixing fields in one batch cannot work — one AIR holds one column layout — and must be refused loudly
# rather than silently checked under whichever layout came first.
import copy
mixed = copy.deepcopy(pub)
mixed["publics"].append(copy.deepcopy(mixed["publics"][0]))
mixed["publics"][1]["ext"] = False
ok_mixed, why_mixed = FV.verify_fold(rp, mixed, expect_inner=NQ, expect_outer=8)
check(not ok_mixed, f"a batch mixing base-field and GF(p^2) proofs is REFUSED ({why_mixed})")

# ---------------------------------------------------------------- the activation, and what it does NOT do
# This assertion was inverted until the port landed: the recursion backend was excluded precisely because its
# in-circuit verifiers could not check extension proofs. Keeping the check (rather than deleting it) is what
# makes a silent revert to the ~47-bit path fail loudly.
check(stark.ext_challenges_active(BK.RECURSION),
      "the RECURSION backend draws from GF(p^2) — folded proofs are no longer the weak link at ~47 bits")
check(stark.ext_challenges_active(BK.DEFAULT) == stark.ext_challenges_active(BK.RECURSION),
      "every backend agrees on the challenge field (no backend-shaped hole to downgrade through)")
import protocol as _P
check(_P.SETTLE_PROOF_RECURSIVE in (True, False),
      f"SETTLE_PROOF_RECURSIVE is an explicit protocol decision (currently {_P.SETTLE_PROOF_RECURSIVE}) — "
      "the recursion port makes it SAFE to enable, it does not enable it")

print()
if fails:
    print(f"{len(fails)} CHECK(S) FAILED:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("ALL GF(p^2) RECURSION CHECKS PASSED")
