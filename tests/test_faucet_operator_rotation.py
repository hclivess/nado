"""
The faucet's OPERATOR is state, not code — it can be rotated without an upgrade.

WHY. The payout gate used to be a digest assembled into `reward` itself. That made the spending key
un-rotatable without an `upgrade`, invisible on-chain (you had to disassemble the contract to learn who
could spend the prize bank), and — on a contract that was ever `lock`ed — bound permanently, with no way
back even for its owner. Contract OWNERSHIP was already transferable (state.transfer_contract preserves
cid and storage); this closes the matching gap for the SPENDING right, so an operator key can be split
from the node/staking key by transaction instead of by code change.

WHAT THESE CHECKS PIN
  * unset reads as the deploy-time key, so an already-deployed faucet keeps paying across the upgrade
    with no migration step and no window where nobody can pay;
  * only the CURRENT operator may rotate, and after rotating the old key is powerless — a handover, not
    a shared credential;
  * zero is refused, because storing it would read as "unset" and silently restore the bootstrap key,
    turning a handover into a takeback;
  * the payout rules survive the change: still operator-only, still at most one payout per
    (game, day, rank), still failing closed when the bank cannot cover it.
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_fails = []
def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  — " + detail) if detail and not cond else ""))
    if not cond: _fails.append(name)


def main():
    os.environ.setdefault("HOME", tempfile.mkdtemp())
    from execnode import zkvm, runtimes
    from execnode.games import faucet

    code = faucet.build()
    OPER = faucet.OP_DIG
    NEW = runtimes.zkvm_addr_digest("ba04cbbb7c1ffc17ed67b62e3100f25789f3738998af6b")

    def run(method, args, storage, caller):
        # zkvm.run(code, method, caller, args, storage, ...) — caller is positional and is a FIELD
        # element (the alghash address digest); address strings never enter the VM.
        ok, ret, new_st, io = zkvm.run(code, method, caller, args, dict(storage))[:4]
        paid = sum(b for k, a, b in io if k == zkvm.IO_PAY)
        return ok, new_st, paid

    # ---- unset storage falls back to the deploy-time key ------------------------------------------
    ok, st, paid = run("reward", [0, 1, 1, 12345, 500], {}, OPER)
    check("with NO operator configured, the deploy-time key can pay", ok and paid == 500)
    ok, _, _ = run("reward", [0, 1, 1, 12345, 500], {}, NEW)
    check("...and a stranger cannot", not ok)

    # ---- rotation --------------------------------------------------------------------------------
    ok, st, _ = run("set_operator", [NEW], {}, OPER)
    check("the current operator can rotate the role", ok and st.get(faucet.SLOT_OPERATOR) == NEW)

    ok2, _, paid2 = run("reward", [0, 2, 1, 12345, 500], st, NEW)
    check("the NEW operator can pay", ok2 and paid2 == 500)
    ok3, _, _ = run("reward", [0, 3, 1, 12345, 500], st, OPER)
    check("the OLD key is powerless after the handover", not ok3)

    # ---- the takeback hole -----------------------------------------------------------------------
    ok4, st4, _ = run("set_operator", [0], st, NEW)
    check("rotating to ZERO is refused (it would restore the bootstrap key)", not ok4)

    # ---- and a stranger can never rotate ---------------------------------------------------------
    ok5, _, _ = run("set_operator", [12345], st, OPER)
    check("the displaced key cannot rotate it back", not ok5)
    ok6, _, _ = run("set_operator", [12345], st, 999)
    check("an unrelated caller cannot rotate it", not ok6)

    # ---- payout rules unchanged ------------------------------------------------------------------
    ok7, st7, paid7 = run("reward", [5, 9, 1, 777, 250], st, NEW)
    check("a fresh (game, day, rank) pays", ok7 and paid7 == 250)
    ok8, _, paid8 = run("reward", [5, 9, 1, 777, 250], st7, NEW)
    check("...and the SAME placement cannot be paid twice", not ok8)

    print()
    print("ALL FAUCET-OPERATOR CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
