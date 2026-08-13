"""
Fidelity may not be FARMED by recerting fast (protocol.FIDELITY_MIN_GAP_EPOCHS).

THE BUG: FIDELITY_GAIN is awarded per continuous RECERT, and the only spacing rule anywhere was
validate_transaction's "one register per epoch" — an epoch being 60 blocks x 6 s = 6 minutes. So the ramp
that protocol.py described as "consecutive recerts (~days)" could be run to FIDELITY_CAP = 30 in 30
epochs = 3 HOURS, lifting open weight from OPEN_BASE_FLOOR (2) to 10. That is a 5x multiplier on BOTH
open-lane producer selection and the presence dividend, bought with ~1 s of sequential PoSW per recert on
a transaction that is fee-exempt. Found from a user report: "my fidelity increased to 4 today instead
of 2".

THE FIX: a continuous recert earns the ramp only if it is >= FIDELITY_MIN_GAP_EPOCHS from the previous
one. A closer recert still RENEWS THE LEASE — presence and eligibility are untouched, nobody is dropped
for renewing early — it just earns no fidelity.

WHAT THESE CHECKS PIN, and why each one matters:

  * farming is dead: 30 back-to-back epoch recerts no longer reach the cap;
  * the honest cadences still ramp: the browser renews at 192 epochs and the node at 230, both >= the gap;
  * PRESENCE IS NOT PUNISHED: a too-early recert still renews the lease, it only forgoes the ramp;
  * a lapse still resets to GAIN, unchanged;
  * THE TWO IMPLEMENTATIONS AGREE. The rule lives in account_ops.apply_register (live) and in
    dividend_ops.fidelity_at_epoch (the replay a dividend fraud proof checks against). If they ever
    diverge, a fraud proof recomputes a different weight than was actually applied and FALSE-SLASHES an
    honest settler — so the last check replays real histories through both and demands equality.
  * the ACTIVATION GATE holds: recerts before it keep the old ramp, so historical reconstructions stay
    byte-identical and already-paid dividends remain provable.
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
        from ops import kv_ops, account_ops, dividend_ops
        from protocol import (FIDELITY_CAP, FIDELITY_GAIN, FIDELITY_MIN_GAP_EPOCHS,
                              FIDELITY_MIN_GAP_ACTIVATION_EPOCH, POSW_LEASE_EPOCHS)
        kv_ops.init_env()

        A0 = FIDELITY_MIN_GAP_ACTIVATION_EPOCH

        class _Log:
            def info(self, *a):
                pass

        def run(addr, epochs):
            """Apply a recert at each epoch through the LIVE path; return final stored fidelity.
            apply_register takes the EPOCH (transaction_ops passes block_height // EPOCH_LENGTH)."""
            for e in epochs:
                account_ops.apply_register(addr, e, _Log())
            acc = kv_ops.get_account(addr) or {}
            return int(acc.get("fidelity", 0))

        # ---- farming is dead ------------------------------------------------------------------------
        spam = [A0 + i for i in range(30)]                     # 30 consecutive epochs = 3 hours
        fid_spam = run("spammer", spam)
        check("30 back-to-back epoch recerts no longer reach the cap", fid_spam < FIDELITY_CAP)
        check("a spammed run earns only the first recert's GAIN", fid_spam == FIDELITY_GAIN)

        # ---- the honest cadences still ramp ---------------------------------------------------------
        browser = [A0 + 192 * i for i in range(6)]             # wallet renews at 80% of the lease
        check("browser cadence (192 epochs) still ramps", run("browser", browser) == 6 * FIDELITY_GAIN)
        node = [A0 + 230 * i for i in range(6)]                # node renews at lease - 10
        check("node cadence (230 epochs) still ramps", run("node", node) == 6 * FIDELITY_GAIN)
        check("the gap is below both honest triggers", FIDELITY_MIN_GAP_EPOCHS <= 192)

        # ---- presence is NOT punished for renewing early --------------------------------------------
        early = [A0, A0 + 10]
        run("early", early)
        acc = kv_ops.get_account("early") or {}
        check("an early recert still renews the lease (registered stays 1)", int(acc.get("registered", 0)) == 1)
        check("...and is still in the open registry", "early" in account_ops.get_open_registry(A0 + 10))
        check("...but earned no extra fidelity", int(acc.get("fidelity", 0)) == FIDELITY_GAIN)

        # ---- a lapse still resets to GAIN -----------------------------------------------------------
        lapsed = [A0, A0 + 192, A0 + 192 + POSW_LEASE_EPOCHS + 1]
        check("a lapse still resets to GAIN", run("lapsed", lapsed) == FIDELITY_GAIN)

        # ---- the activation gate preserves history --------------------------------------------------
        pre = [A0 - 40 + i for i in range(10)]                 # tight recerts BEFORE activation
        check("pre-activation tight recerts keep the OLD ramp", run("historic", pre) == 10 * FIDELITY_GAIN)

        # ---- THE TWO IMPLEMENTATIONS MUST AGREE (else a fraud proof false-slashes) -------------------
        mismatch = None
        for addr, epochs in (("spammer", spam), ("browser", browser), ("node", node),
                             ("lapsed", lapsed), ("historic", pre), ("early", early)):
            live = int((kv_ops.get_account(addr) or {}).get("fidelity", 0))
            replay = dividend_ops.fidelity_at_epoch(addr, max(epochs))
            if live != replay:
                mismatch = (addr, live, replay)
                break
        check(f"live ramp == dividend replay for every history{'' if not mismatch else f' [{mismatch}]'}",
              mismatch is None)

    print()
    print("ALL FIDELITY MIN-GAP CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
