"""
Identity CREATION must cost more than identity RENEWAL (protocol.POSW_ENTRY_MULT).

WHY THIS EXISTS. Every present identity earns `OPEN_BASE_FLOOR = 2` open-lane weight, flat, and that
weight pays both producer selection and the presence dividend. Against the honest weight measured on
betanet-2 (266 across 117 miners), ~133 identities take HALF of both — for about two core-minutes of PoSW
per day. The only thing that stood in the way was `ops.ratelimit.allow_registration`, a 64-per-IP cap
called from exactly one place: nado.py's HTTP submission handler. It is admission policy on one door, not
a rule of the chain — submit to a different node, or gossip straight to peers, and it never applies.

IT CANNOT BE MADE CONSENSUS. A transaction carries no IP (sender/pubkey/posw/signature), and transactions
arrive by GOSSIP, so the address a node sees is the relaying peer rather than the originator. Nodes would
disagree about the same block — the non-determinism class that split betanet-6. A self-declared IP would
be forgeable and free to vary.

So the cost moves to something consensus CAN check: the sender's own recert history. A register from an
address with no valid lease as of the anchor epoch pays POSW_ENTRY_MULT× the base sequential work; an
established identity renewing pays the base. Creation dear, presence cheap — and the open lane stays
capital-free, which is the point of the lane.

WHAT THESE CHECKS PIN:

  * a first registration is dear, a renewal is not, and a re-entry after a LAPSE is dear again;
  * the entry cost COMPOSES with the rate multiplier (a burst of new identities pays both);
  * the ACTIVATION GATE holds — before it, nothing changes, so in-flight proofs stay valid and historical
    blocks re-validate byte-identically;
  * DETERMINISM, which is the whole reason this is expressible in consensus at all: the answer depends
    only on the SENDER'S OWN recerts as of the anchor epoch. Another actor registering cannot change it,
    and it cannot drift between prove-time and land-time.
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
        from ops import reg_difficulty as RD
        from protocol import (POSW_T, POSW_ENTRY_MULT, POSW_ENTRY_ACTIVATION_EPOCH,
                              POSW_LEASE_EPOCHS)
        kv_ops.init_env()

        class _Log:
            def info(self, *a):
                pass

        A0 = POSW_ENTRY_ACTIVATION_EPOCH
        NEW, OLD, LAPSED = "n" * 46, "o" * 46, "l" * 46

        # OLD is an established identity: recert just before the anchor we will test at.
        account_ops.apply_register(OLD, A0 + 10, _Log())
        # LAPSED registered long ago and let the lease expire.
        account_ops.apply_register(LAPSED, A0 - POSW_LEASE_EPOCHS - 50, _Log())

        anchor = A0 + 20

        # ---- creation vs renewal ---------------------------------------------------------------------
        check("a never-registered address is an ENTRY", RD.is_entry_registration(NEW, anchor))
        check("an established identity is NOT an entry", not RD.is_entry_registration(OLD, anchor))
        check("a LAPSED identity is an entry again", RD.is_entry_registration(LAPSED, anchor))

        base_rate = RD.difficulty_multiplier(anchor)
        t_new = RD.required_posw_t(anchor, NEW)
        t_old = RD.required_posw_t(anchor, OLD)
        check(f"first registration costs {POSW_ENTRY_MULT}x the renewal", t_new == t_old * POSW_ENTRY_MULT)
        check("a renewal costs exactly the rate requirement", t_old == POSW_T * base_rate)
        check("the entry cost COMPOSES with the rate multiplier",
              t_new == POSW_T * base_rate * POSW_ENTRY_MULT)

        # ---- the activation gate ---------------------------------------------------------------------
        pre = A0 - 5
        check("before activation an entry pays the plain rate requirement",
              RD.required_posw_t(pre, NEW) == POSW_T * RD.difficulty_multiplier(pre))
        check("...and entry_multiplier is 1 there", RD.entry_multiplier(NEW, pre) == 1)

        # ---- a caller with no sender still gets the display value ------------------------------------
        check("required_posw_t() without a sender = rate only (display path)",
              RD.required_posw_t(anchor) == POSW_T * base_rate)

        # ---- DETERMINISM: only the sender's OWN history matters --------------------------------------
        before = RD.required_posw_t(anchor, NEW)
        for i in range(5):                                   # other identities registering must not move it
            account_ops.apply_register(f"x{i}" + "y" * 44, A0 + 11 + i, _Log())
        check("another actor registering cannot change this sender's requirement",
              RD.required_posw_t(anchor, NEW) == before)

        # a recert LATER than the anchor must not retroactively change the anchored answer
        account_ops.apply_register(NEW, anchor + 5, _Log())
        check("a recert AFTER the anchor does not change the anchored requirement",
              RD.required_posw_t(anchor, NEW) == before)
        check("...but it is a renewal at a LATER anchor", not RD.is_entry_registration(NEW, anchor + 10))

    print()
    print("ALL POSW ENTRY-COST CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
