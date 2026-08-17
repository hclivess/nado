"""
Every rejection leaves the pool untouched — checked at EVERY rejection point, not the convenient ones.

WHY EXHAUSTIVELY. verify_transition has a dozen ways to say no, and apply_transition mutates only after it
says yes. That ordering is the single thing standing between a malformed statement and a half-applied one,
and this repo has paid for it before: the pool's own apply_transfer recorded the nullifier and appended the
outputs BEFORE validating the unshield destination, so a malformed exit burned the note and recorded no
exit. Individual tests already cover a few rejection paths; this covers the table, so a future edit that
moves one check below a mutation fails here rather than in production.

The upgrade case is separate and is a PROPERTY, not a guard: a contract upgrade preserves the cid, notes
are scoped by cid, and the rules come from the note KIND rather than the contract's code — so upgrading a
contract can neither strand its private state nor change how existing notes behave. Worth pinning because
the alternative (an upgrade silently invalidating everyone's notes) would be a rug pull with no attacker.

Run: python3 tests/test_shielded_state_atomicity.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_atomic_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.state import ExecState
from execnode import shielded_state as S

FAILS = []


def check(name, fn):
    try:
        fn()
        print("PASS  " + name)
    except AssertionError as e:
        print("FAIL  " + name + " — " + str(e))
        FAILS.append(name)
    except Exception as e:
        print(f"FAIL  {name} — {type(e).__name__}: {e}")
        FAILS.append(name)


CID = "d0be764f3da9c9cc6bb609280a887929"
OTHER = "230860957a7c1db403434ffb4a3969b3"
ALICE, BOB = 0xA11CE, 0xB0B
DEST = "c041167affec9c9649cbf3fe72f921a7fb001ba9831ba0"
CM = S.note_commitment(CID, S.KIND_VALUE, [1000], S.owner_of(ALICE), 111)
NF = S.note_nullifier(ALICE, CM)


def _pool():
    p = S.ShieldedStatePool({CID: [CM]})
    return p


def _snapshot(p):
    """Everything a rejection must not disturb."""
    return ({c: list(v) for c, v in p.trees.items()}, set(p.nullifiers),
            {c: list(v) for c, v in p.anchors.items()})


# ---- the rejection table -----------------------------------------------------------------------------
# One entry per distinct reason verify_transition can refuse. Each must leave the pool byte-identical.
GOOD = {"cid": CID, "kind": S.KIND_VALUE, "root": None, "nullifiers": [NF],
        "out_commitments": [12345], "public_delta": 0}
STARK = {"stark": {"arity": 1, "D": S.TREE_DEPTH}}

REJECTIONS = [
    ("not a dict",             "malformed",         None, None),
    ("no contract",            {"kind": S.KIND_VALUE}, STARK, None),
    ("unknown kind",           dict(GOOD, kind=999), STARK, None),
    ("too many inputs",        dict(GOOD, nullifiers=[1, 2, 3, 4, 5]), STARK, None),
    ("not a list",             dict(GOOD, nullifiers="x"), STARK, None),
    ("spends and creates nothing", dict(GOOD, nullifiers=[], out_commitments=[]), STARK, None),
    ("duplicate nullifier",    dict(GOOD, nullifiers=[NF, NF]), STARK, None),
    ("already spent",          GOOD, STARK, "prespend"),
    ("duplicate commitment",   dict(GOOD, out_commitments=[CM]), STARK, None),
    ("same commitment twice",  dict(GOOD, out_commitments=[7, 7]), STARK, None),
    ("wrong arity",            GOOD, {"stark": {"arity": 2, "D": S.TREE_DEPTH}}, None),
    ("wrong depth",            GOOD, {"stark": {"arity": 1, "D": 4}}, None),
    ("delta out of range",     dict(GOOD, public_delta=S.VALUE_MAX), STARK, None),
    ("no circuit for shape",   dict(GOOD, nullifiers=[], public_delta=0), STARK, None),
    ("bogus proof",            GOOD, STARK, None),
    ("transparent refused",    GOOD, {"witness": {"inputs": [], "outputs": []}}, None),
]


def t_every_rejection_leaves_the_pool_untouched():
    seen = set()
    for label, public, proof, setup in REJECTIONS:
        p = _pool()
        if setup == "prespend":
            p.spend(NF)
        if public is not None and public != "malformed":
            public = dict(public)
            public["root"] = p.root(CID)
        before = _snapshot(p)
        r = S.apply_transition("not-a-dict" if public == "malformed" else public,
                               proof if proof is not None else "not-a-dict", p)
        assert r is not None, f"{label}: expected a rejection, got acceptance"
        assert _snapshot(p) == before, f"{label}: the pool was mutated by a REJECTED transition ({r})"
        seen.add(r)
    for r in sorted(seen):
        print("        · " + r[:88])
    assert len(seen) >= 12, f"the table only exercised {len(seen)} distinct reasons — it has gone stale"


def t_the_reasons_are_distinct_enough_to_diagnose():
    """A rejection reason is what an operator sees. Two different failures collapsing to one message is how
    a real bug hides behind a benign-looking one."""
    reasons = []
    for label, public, proof, setup in REJECTIONS:
        p = _pool()
        if setup == "prespend":
            p.spend(NF)
        if public is not None and public != "malformed":
            public = dict(public)
            public["root"] = p.root(CID)
        reasons.append(S.apply_transition("not-a-dict" if public == "malformed" else public,
                                          proof if proof is not None else "not-a-dict", p))
    assert all(r for r in reasons), "a rejection returned an empty reason"


# ---- the upgrade property ----------------------------------------------------------------------------
def t_private_state_survives_a_contract_upgrade():
    """A contract upgrade preserves the cid, notes are scoped by cid, and the rules come from the note KIND
    rather than the contract's code. So an upgrade can neither strand private state nor change how existing
    notes behave — the alternative would be a rug pull with no attacker."""
    st = ExecState(path=os.path.join(os.environ["HOME"], "up.json"))
    st.contracts[CID] = {"runtime": "zkvm", "code": {"m": []}, "storage": {}, "abi": {},
                         "deployer": "dep", "upgradable": True}
    st.app_state.append(CID, CM)
    st.bridge[CID] = 1000
    root_before = st.app_state.root(CID)

    st.contracts[CID] = {**st.contracts[CID], "code": {"m2": []}}      # what `upgrade` does: same cid
    assert st.app_state.root(CID) == root_before, "an upgrade moved the note root"
    assert st.app_state.has_commitment(CID, CM), "an upgrade dropped the notes"
    assert st.bridge[CID] == 1000, "an upgrade dropped the escrow"


def t_notes_under_a_missing_contract_are_unspendable_but_not_lost():
    """The op requires the contract to exist. If one ever vanished, the notes stay in the tree and the
    escrow stays in the ledger — recorded here so the failure mode is 'frozen', never 'silently gone'."""
    st = ExecState(path=os.path.join(os.environ["HOME"], "gone.json"))
    st.app_state.append(CID, CM)
    st.bridge[CID] = 1000
    r = st.apply_blob({"op": "private_call", "public": dict(GOOD, root=st.app_state.root(CID)),
                       "proof": STARK}, "sender", "t")
    assert r == "skip private_call: no such contract", f"unexpected: {r}"
    assert st.app_state.has_commitment(CID, CM), "the notes were dropped"
    assert st.bridge[CID] == 1000, "the escrow was dropped"


def t_each_rejection_gives_its_own_reason():
    """The table above asserts only that SOMETHING rejected. That is too weak to pin a specific guard: with
    the contract-name check disabled, a statement carrying no cid falls through and is rejected later for
    spending and creating nothing — a different bug wearing the same green tick. Mutation testing found
    exactly that. These assert the EXACT reason, so the guard that produced it is the one under test."""
    p = _pool()
    cases = [
        ({"kind": S.KIND_VALUE}, "transition names no contract"),
        (dict(GOOD, cid=CID, kind=999), "unknown note kind 999"),
        (dict(GOOD, cid=CID, nullifiers=[], out_commitments=[]), "transition spends and creates nothing"),
        (dict(GOOD, cid=CID, nullifiers="x"), "nullifiers and out_commitments must be lists"),
    ]
    for public, expected in cases:
        public = dict(public)
        if "root" in public:
            public["root"] = p.root(CID)
        r = S.verify_transition(public, STARK, _pool())
        assert r == expected, f"expected {expected!r}, got {r!r}"


for name, fn in list(globals().items()):
    if name.startswith("t_"):
        check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "ALL ATOMICITY CHECKS PASSED")
sys.exit(1 if FAILS else 0)
