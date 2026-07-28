"""THE PROVER DOES NOT PICK ITS OWN SECURITY LEVEL.

The backend string a proof carries selects the HASH — and, since the GF(p^2) migration, also the CHALLENGE
FIELD: stark.ext_challenges_active is False for "recursion", because the fold's in-circuit verifier cannot
do extension arithmetic. That coupling opened a hole an adversarial audit found and reproduced end to end:

    prove_epoch_calls(calls, backend=RECURSION)   ->  proof["backend"] = "recursion", W = W_TOTAL (base)
    verify_epoch_calls(proof, ...)                ->  (True, "ok")

Every consensus caller passes backend=None — settlement_sparse.verify_bound_epoch and
verify_bound_epoch_replay, vm_circuit.verify_call — and that is the path block apply reaches through
ops/transaction_ops.py -> verify_settlement_sparse. So a settler could stamp backend="recursion", build the
whole proof base-field, and have the proof that drives the SETTLED STATE ROOT checked at ~45-bit LogUp,
~47-bit FRI and ~56-bit alphas instead of 109/112/126. Nothing detects it: the proof is entirely
self-consistent, it is simply weaker.

The fix is policy, not arithmetic: a proof-supplied backend may never select the base-field layout. A caller
that legitimately wants it — the fold — passes backend=RECURSION explicitly, and that still works.
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.stark import vm_circuit as VC, stark, backend as BK, soundness

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


# The coupling that makes this exploitable is real and intended — pin it so the test explains itself.
check(not stark.ext_challenges_active(BK.RECURSION),
      "the recursion backend really does select the base field (that is why it is exploitable)")
check(stark.ext_challenges_active(BK.DEFAULT),
      "the default backend selects GF(p^2)")

gap = soundness.aux_bits(17, ext=True) - soundness.aux_bits(17, ext=False)
check(gap > 50, f"the downgrade is worth {gap:.0f} bits of LogUp soundness — not a rounding difference")


class _Stub(dict):
    """Minimal proof shell: the guard must fire on the DECLARED backend, before any geometry or STARK work,
    so it is reachable without building a real proof."""


def _verify(decl_backend, caller_backend=None):
    p = _Stub({"T": 1024, "W": VC.W_TOTAL, "backend": decl_backend})
    return VC.verify_epoch_calls(p, [], [], num_queries=4, backend=caller_backend)


ok, why = _verify("recursion")
check(not ok, "a proof DECLARING the recursion backend is refused by verify_epoch_calls")
check("not the prover" in (why or "").lower() or "base-field backend" in (why or "").lower(),
      f"...and the refusal names the reason ({why!r})")

ok_o1, why_o1 = VC.verify_epoch_o1(_Stub({"T": 1024, "W": VC.W_TOTAL, "backend": "recursion"}),
                                   [], num_queries=4)
check(not ok_o1, "verify_epoch_o1 refuses it too (it had the same hole)")

# The legitimate user of the base-field layout is the FOLD, which passes the backend EXPLICITLY. That must
# still be allowed, or SETTLE_PROOF_RECURSIVE can never be turned on.
ok_expl, why_expl = _verify("recursion", caller_backend=BK.RECURSION)
check("not the prover" not in (why_expl or "").lower(),
      f"an EXPLICIT backend=RECURSION from the caller is still permitted (got {why_expl!r})")

# A proof that declares nothing, or declares an ext backend, is unaffected by the policy.
for decl in (None, "blake2b", "alghash2"):
    p = _Stub({"T": 1024, "W": VC.W_TOTAL_EXT})
    if decl:
        p["backend"] = decl
    _ok, _why = VC.verify_epoch_calls(p, [], [], num_queries=4)
    check("not the prover" not in (_why or "").lower(),
          f"a proof declaring {decl!r} is not blocked by the challenge-field policy")

print()
if fails:
    print(f"{len(fails)} CHECK(S) FAILED:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("ALL CHALLENGE-FIELD POLICY CHECKS PASSED")
