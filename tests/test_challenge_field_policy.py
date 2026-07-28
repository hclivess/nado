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


# THE HOLE IS NOW CLOSED AT THE ROOT. The attack needed a backend that selects a WEAKER challenge field;
# the recursion port removed the last one, so every backend is GF(p^2) and there is nothing to downgrade to.
# That is a stronger statement than the guard, and it is the one to assert first.
for _bk_ in (BK.DEFAULT, BK.ALGHASH2, BK.RECURSION):
    check(stark.ext_challenges_active(_bk_),
          f"backend {_bk_.name!r} selects GF(p^2) — no weaker field exists to downgrade into")

gap = soundness.aux_bits(17, ext=True) - soundness.aux_bits(17, ext=False)
check(gap > 50, f"the downgrade is worth {gap:.0f} bits of LogUp soundness — not a rounding difference")


class _Stub(dict):
    """Minimal proof shell: the guard must fire on the DECLARED backend, before any geometry or STARK work,
    so it is reachable without building a real proof."""


def _verify(decl_backend, caller_backend=None):
    p = _Stub({"T": 1024, "W": VC.W_TOTAL, "backend": decl_backend})
    return VC.verify_epoch_calls(p, [], [], num_queries=4, backend=caller_backend)


# THE GUARD REMAINS, as defence in depth: if a base-field backend is ever reintroduced, a PROOF must still
# not be able to select it. There is no such backend to test against today, so drive the policy directly by
# making ext_challenges_active report False the way a base-field backend would.
_real = stark.ext_challenges_active
try:
    stark.ext_challenges_active = lambda b=None: False
    ok, why = _verify("recursion")
    check(not ok, "with a base-field backend present, a proof DECLARING it is still refused")
    check("not the prover" in (why or "").lower() or "base-field backend" in (why or "").lower(),
          f"...and the refusal names the reason ({why!r})")
    ok_o1, why_o1 = VC.verify_epoch_o1(_Stub({"T": 1024, "W": VC.W_TOTAL, "backend": "recursion"}),
                                       [], num_queries=4)
    check(not ok_o1, "verify_epoch_o1 refuses it too (it had the same hole)")
finally:
    stark.ext_challenges_active = _real

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

# ---------------------------------------------------------------- the policy's LEGITIMATE callers comply
# The guard refuses a PROOF-supplied backend, so every internal caller that knows which backend it asked for
# must say so explicitly. sparse settlement PROVES its segments with RECURSION (row-committed, foldable) and
# used to verify them with no backend at all — i.e. resolving the very field-selecting string the guard
# rejects. That combination made honest settlement proofs fail with a message about prover choice, and no
# test caught it: the suite never exercised the recursion-backed verify path with the guard active.
import inspect
from execnode.stark import settlement_sparse as SS

# prove_bound_epoch takes the backend as a PARAMETER (default blake2b; only prove_settlement_sparse asks for
# RECURSION), so a bundle legitimately carries any of them and the verify side must resolve it from the proof
# — pinning one forces the wrong HASH and desyncs the transcript ("insufficient proof-of-work"). That is only
# safe while no backend selects a weaker field, which is what the first block above asserts. These two facts
# are load-bearing together: if a base-field backend returns, the guard starts refusing proof-declared
# backends and these call sites have to pass the one they expect.
for fn_name in ("verify_bound_epoch", "verify_bound_epoch_replay"):
    src = inspect.getsource(getattr(SS, fn_name))
    if "verify_epoch_calls(" in src:
        check("backend=" not in src.split("verify_epoch_calls(")[1].split(")")[0],
              f"settlement_sparse.{fn_name} resolves the backend from the proof (bundles are not all "
              f"RECURSION-proven, so pinning one would desync the transcript)")

print()
if fails:
    print(f"{len(fails)} CHECK(S) FAILED:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("ALL CHALLENGE-FIELD POLICY CHECKS PASSED")
