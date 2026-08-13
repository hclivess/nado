"""
The auto-register lease guard must actually fire (core_loop.maybe_auto_register).

THE BUG: the guard read `acc.get("reg_epoch", -1)`, but `reg_epoch` is NOT a stored account field — it is
an enrichment the HTTP handler adds (`nado.py`: `data["reg_epoch"] = kv_ops.recert_latest(addr)`). The raw
document this loop reads has no such key, so the value was ALWAYS -1, `reg_ep >= 0` was always False, and
the guard never fired. Every auto-registering node re-registered EVERY EPOCH instead of once per
~240-epoch lease.

Measured consequences on betanet-2 before the fix (chain 1.6 days old):

  * the three auto-registering nodes reached fidelity 366-379 — ~one recert per epoch since genesis —
    while every browser miner sat at 1. Open weight 10 vs 2: 5x the producer selection AND 5x the
    presence-dividend share. That is the reward gap users reported.
  * ~240 s/day of PoSW burned per node instead of ~1 s, and ~240 register txs/day of chain spam each;
  * the registration-difficulty baseline was inflated by that volume, which is part of why the anti-flood
    multiplier sat at 1x.

WHAT THIS PINS: the field the guard reads must be one that EXISTS in the raw account document, and the
lease arithmetic must skip a renewal while the lease is still valid and allow one when it is not. The
first check is the regression itself — it fails on the old code and passes on the new.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fails = []


def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        _fails.append(name)


def main():
    with tempfile.TemporaryDirectory() as d:
        os.environ["HOME"] = d
        os.makedirs(os.path.join(d, "nado"), exist_ok=True)
        from ops import kv_ops, account_ops
        from protocol import POSW_LEASE_EPOCHS
        kv_ops.init_env()

        class _Log:
            def info(self, *a):
                pass

        ADDR = "a" * 46
        account_ops.apply_register(ADDR, 100, _Log())          # recert at epoch 100

        # ---- the regression: reg_epoch is NOT in the stored document ---------------------------------
        raw = kv_ops.get_account(ADDR) or {}
        check("account doc really has no 'reg_epoch' key (the old guard's input)",
              "reg_epoch" not in raw)
        check("...so the old expression silently yields -1", int(raw.get("reg_epoch", -1)) == -1)

        # ---- the source the fix uses DOES have it ----------------------------------------------------
        latest = kv_ops.recert_latest(ADDR)
        check("recert_latest returns the real recert epoch", latest == 100)

        # ---- the guard arithmetic, exercised directly -------------------------------------------------
        def guard_skips(now_epoch, reg_ep):
            """Mirror of the loop's condition: True = skip the renewal (still well inside the lease)."""
            return reg_ep >= 0 and now_epoch < reg_ep + POSW_LEASE_EPOCHS - 10

        check("OLD input (-1) never skips -> re-registers every epoch",
              not guard_skips(101, int(raw.get("reg_epoch", -1))))
        check("NEW input skips one epoch later (lease valid)", guard_skips(101, latest))
        check("NEW input still skips just inside the lease tail",
              guard_skips(100 + POSW_LEASE_EPOCHS - 11, latest))
        check("NEW input RENEWS in the tail (lease nearly spent)",
              not guard_skips(100 + POSW_LEASE_EPOCHS - 10, latest))
        check("NEW input renews after a full lapse",
              not guard_skips(100 + POSW_LEASE_EPOCHS + 5, latest))

        # ---- a never-registered address must always be allowed to register ---------------------------
        check("an unregistered address never skips", not guard_skips(1, kv_ops.recert_latest("z" * 46)))

        # ---- and the loop must read that source, not the phantom field -------------------------------
        import inspect
        from loops import core_loop
        src = inspect.getsource(core_loop.Loop.maybe_auto_register) \
            if hasattr(core_loop, "Loop") and hasattr(getattr(core_loop, "Loop"), "maybe_auto_register") \
            else inspect.getsource(core_loop)
        # Strip comments before asserting: the fix deliberately DESCRIBES the old expression in a comment,
        # so a naive substring search matches the explanation and reports the bug as still present.
        code = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
        check("the loop reads recert_latest for the lease guard", "recert_latest" in code)
        check("the loop no longer reads the phantom reg_epoch field",
              'acc.get("reg_epoch"' not in code)

    print()
    print("ALL AUTO-REGISTER GUARD CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
