"""
Shielded-contract transition circuit (execnode/stark/appnote_circuit.py) — trace and AIR.

WHY THIS FILE IS SHAPED LIKE THIS. The expensive failure mode for a hand-written AIR is not a wrong answer,
it is a trace that violates its own constraints: proving then dies deep inside FRI with "final layer not
low-degree", which says nothing about which constraint or which row. So the first and largest check here
evaluates EVERY constraint at EVERY row of an honest trace directly — no proving, no FRI, and a failure
names the constraint index and the offending rows. It runs in under a second, where a prove is ~13.

The second group is the other half of the same coin: an AIR that a tampered trace ALSO satisfies proves
nothing. Each tamper check breaks one specific thing and asserts some constraint notices.

Run: python3 tests/test_appnote_circuit.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.stark import appnote_circuit as AC, alghash, field as F
from execnode import shielded_state as S

FAILS = []


class Skipped(Exception):
    """A skip must NOT report as a pass. FAST=1 used to print '(skipped)' and then 'PASS', so the single
    most valuable check in this file — the real prove/verify round trip — announced success while doing
    nothing. That is the same false-assurance shape this branch found in a test defending dead code, and it
    is worse here because it hid a skip rather than a triviality."""


def check(name, fn):
    try:
        fn()
        print("PASS  " + name)
    except Skipped as e:
        print(f"SKIP  {name} — {e}")
    except AssertionError as e:
        print("FAIL  " + name + " — " + str(e))
        FAILS.append(name)
    except Exception as e:
        print(f"FAIL  {name} — {type(e).__name__}: {e}")
        FAILS.append(name)


NSK, CID_EL, KIND = 0xABCDEF, 12345, S.KIND_VALUE
FIN, FOUT, RHO_IN, RHO_OUT = [1000], [700], 7, 11
OWNER_OUT = alghash.owner_of(999)


def _witness(D=4):
    return dict(nsk=NSK, cid_el=CID_EL, kind=KIND, fields_in=FIN, rho_in=RHO_IN,
                siblings=[i + 1 for i in range(D)], dirs=[i % 2 for i in range(D)],
                fields_out=FOUT, owner_out=OWNER_OUT, rho_out=RHO_OUT)


def _build(D=4):
    w = _witness(D)
    tr, T, Dd, root, nf, cm_out = AC.build_trace(**w)
    per = AC.periodic(T, len(FIN), D, CID_EL, KIND)
    return w, tr, T, per, root, nf, cm_out


def _violations(tr, T, per, cons=None):
    """{constraint index: [rows]} — the diagnostic an FRI failure cannot give you."""
    cons = cons or AC.transitions()
    bad = {}
    for r in range(T - 1):
        cur, nxt, prow = tr[r], tr[r + 1], [c[r] for c in per]
        for i, c in enumerate(cons):
            if c(cur, nxt, prow) != 0:
                bad.setdefault(i, []).append(r)
    return bad


# ---- the trace reproduces the statement --------------------------------------------------------------
def t_trace_reproduces_the_reference():
    w, tr, T, per, root, nf, cm_out = _build()
    g = AC.geometry(1, 4)
    owner, cm_in, ref_nf, ref_root, ref_cm_out = AC.transition(**w)
    assert tr[g["own_end"]][AC.OWN] == owner, "OWNER capture wrong"
    assert tr[g["com_end"]][AC.CARRY] == cm_in, "cm_in capture wrong"
    assert tr[g["nul_end"]][AC.NFREG] == ref_nf, "nullifier capture wrong"
    assert tr[g["out_end"]][AC.ROOTREG] == ref_root, "root capture wrong"
    assert tr[g["out_end"]][AC.S0] == ref_cm_out, "cm_out wrong"


def t_the_circuit_and_the_state_machine_hash_alike():
    """The AIR must absorb exactly what the state machine commits, or a proof would attest to a note the
    pool does not hold. One cid folded through the state machine, one commitment computed both ways."""
    cid = "d0be764f3da9c9cc6bb609280a887929"
    owner = S.owner_of(NSK)
    a = S.note_commitment(cid, S.KIND_VALUE, [1000], owner, 7)
    b = AC.note_cm(S.cid_element(cid), S.KIND_VALUE, [1000], owner, 7)
    assert a == b, "state machine and circuit disagree about the commitment"
    assert S.note_nullifier(NSK, a) == AC.note_nf(NSK, a), "they disagree about the nullifier"
    assert (S.DOM_APPCM, S.DOM_APPNF) == (AC.DOM_APPCM, AC.DOM_APPNF), "domain tags diverged"


def t_domain_tags_are_disjoint_from_the_pool():
    pool = {alghash.DOM_OWNER, alghash.DOM_CM, alghash.DOM_NF, alghash.DOM_NODE}
    assert AC.DOM_APPCM not in pool and AC.DOM_APPNF not in pool, "an app tag collides with a pool tag"


def t_geometry_is_parametric():
    for D in (1, 4, 12, 20):
        g = AC.geometry(1, D)
        assert g["out_start"] == g["nul_end"] + D * AC.RPL, f"membership region wrong at D={D}"
        assert AC.trace_len(1, D) >= g["total"] + 1, f"trace too short at D={D}"
    a1, a3 = AC.geometry(1, 4), AC.geometry(3, 4)
    assert a3["com_end"] - a3["own_end"] == a1["com_end"] - a1["own_end"] + 2 * AC.R, \
        "COMMIT does not grow one round-block per extra field"


# ---- the honest trace satisfies its own AIR ----------------------------------------------------------
def t_every_constraint_holds_at_every_row():
    for D in (1, 4, 12):
        w, tr, T, per, root, nf, cm_out = _build(D)
        bad = _violations(tr, T, per)
        assert not bad, f"D={D}: " + "; ".join(f"constraint #{i} on rows {r[:4]}" for i, r in bad.items())


# ---- and a tampered one does not --------------------------------------------------------------------
def _expect_violation(mutate, what):
    w, tr, T, per, root, nf, cm_out = _build()
    mutate(tr, per, AC.geometry(1, 4))
    assert _violations(tr, T, per), f"{what} was not caught by any constraint"


def t_tampering_with_the_spent_amount_is_caught():
    _expect_violation(lambda tr, per, g: [row.__setitem__(AC.VIN, row[AC.VIN] + 1) for row in tr],
                      "changing the input amount")


def t_breaking_conservation_is_caught():
    """CONS is pinned to -public_delta by a boundary; here we prove the TRANSITION notices too."""
    def m(tr, per, g):
        for row in tr:
            row[AC.VOUT] = F.add(row[AC.VOUT], 1)      # v_out changed, CONS left alone
    _expect_violation(m, "breaking value conservation")


def t_a_secret_register_that_changes_mid_trace_is_caught():
    def m(tr, per, g):
        for row in tr[g["com_end"]:]:
            row[AC.NSK] = F.add(row[AC.NSK], 1)        # a different nsk for the nullifier than the commitment
    _expect_violation(m, "swapping nsk mid-trace")


def t_relabelling_the_contract_is_caught():
    """The point of putting cid in a PERIODIC column: a prover who proves against contract A cannot present
    the proof as contract B, because the verifier rebuilds PUBMSG from the public statement."""
    w, tr, T, per, root, nf, cm_out = _build()
    other = AC.periodic(T, 1, 4, CID_EL + 1, KIND)     # the verifier's columns for a DIFFERENT contract
    assert _violations(tr, T, other), "a trace verified against another contract's periodic columns"


def t_relabelling_the_kind_is_caught():
    w, tr, T, per, root, nf, cm_out = _build()
    other = AC.periodic(T, 1, 4, CID_EL, KIND + 1)
    assert _violations(tr, T, other), "a trace verified against another note kind's periodic columns"


def t_a_forged_merkle_sibling_is_caught():
    def m(tr, per, g):
        for row in tr[g["merk"]:g["out_start"]]:
            row[AC.SIB] = F.add(row[AC.SIB], 1)
    _expect_violation(m, "forging a membership sibling")


def t_a_non_boolean_direction_is_caught():
    def m(tr, per, g):
        for row in tr[g["merk"]:g["out_start"]]:
            row[AC.DIR] = 7                            # not 0/1 -> the child interpolation is not a swap
    _expect_violation(m, "a non-boolean path direction")


def t_a_non_bit_range_column_is_caught():
    def m(tr, per, g):
        tr[g["out_end"] + 2][AC.RB0] = 5               # the soundness hinge of the decomposition
    _expect_violation(m, "a non-boolean range bit")


# ---- the real thing: a proof, and everything a verifier must refuse ---------------------------------
# ~25 s (prove ~18, verify ~7). Everything above is a fast structural check; this is the one that proves
# the structure actually composes into a sound proof. Set FAST=1 to skip it while iterating.
def t_prove_and_verify_round_trip():
    if os.environ.get("FAST"):
        raise Skipped("FAST=1; run without it to prove and verify for real")
    D = 12
    w = _witness(D)
    delta = FOUT[0] - FIN[0]                      # fields_in + delta = fields_out
    proof, root, nf, cm_out = AC.prove(**w, public_delta=delta)
    ok, why = AC.verify(proof, CID_EL, KIND, root, nf, cm_out, delta, lambda r: True)
    assert ok, f"an honest proof was rejected: {why}"

    def refused(what, **over):
        args = dict(cid_el=CID_EL, kind=KIND, root=root, nf=nf, cm_out=cm_out,
                    public_delta=delta, root_is_known=lambda r: True)
        args.update(over)
        ok2, _ = AC.verify(proof, args["cid_el"], args["kind"], args["root"], args["nf"],
                           args["cm_out"], args["public_delta"], args["root_is_known"])
        assert not ok2, f"verifier accepted {what}"

    refused("a proof re-presented as another contract", cid_el=CID_EL + 1)
    refused("a proof re-presented as another note kind", kind=KIND + 1)
    refused("a different public delta", public_delta=delta + 1)
    refused("a substituted nullifier", nf=nf + 1)
    refused("a substituted output commitment", cm_out=cm_out + 1)
    refused("a root the pool never held", root_is_known=lambda r: False)

    padded = dict(proof)
    padded["T"] = proof["T"] * 2
    ok3, why3 = AC.verify(padded, CID_EL, KIND, root, nf, cm_out, delta, lambda r: True)
    assert not ok3 and "geometry" in why3, "a re-padded trace was not caught by the geometry pin"


for name, fn in list(globals().items()):
    if name.startswith("t_"):
        check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "ALL CIRCUIT CHECKS PASSED")
sys.exit(1 if FAILS else 0)
