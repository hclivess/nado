"""
Shielded pool — UNBACKED-MINT fence (doc/privacy.md, execnode/state.py).

Coins may only ENTER the shielded pool via an L1 `shield` tx, whose escrowed amount drives
apply_shield / apply_field_shield. A transfer BLOB is user-supplied and escrow-free, so a positive
`public_value` there would mint notes backed by nothing: the join-split circuit faithfully proves
`v_in + public_value == v_out + fee`, but `public_value` is a PUBLIC INPUT the prover chooses, not a
fact about escrow. Without the fence, one MIN_TX_FEE blob mints an arbitrary note and unshields it
straight back out against SHIELD_ESCROW — draining every other depositor (L1's `escrow.balance >=
amount` floor bounds the loss to the escrow, but that IS everyone's deposits).

These tests assert the fence on BOTH blob paths, and that the LEGITIMATE escrow-driven deposit
(apply_shield, whose public_value comes from the authoritative on-chain amount) still works.

Run: python3 tests/test_unbacked_mint.py
"""
import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_mint_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode.shielded import note_commitment, owner_id
from signatures import generate_keydict

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

EVE = generate_keydict()
MINT = 5_000_000_000_000                      # 500 NADO conjured from nothing
PATH = os.path.join(os.environ["HOME"], "exec_mint.json")


def _fresh():
    """A pristine ExecState — no shield deposit has ever been applied, so escrow backing is zero."""
    return ExecState(path=os.path.join(tempfile.mkdtemp(prefix="nado_mint_st_"), "s.json"))


def _mint_blob(value):
    """A transparent-path transfer blob with NO inputs and public_value > 0 — the mint attempt."""
    owner, rho = owner_id(EVE["public_key"]), "r0"
    return {"op": "shielded_transfer",
            "public": {"root": None, "nullifiers": [], "out_commitments": [note_commitment(value, owner, rho)],
                       "public_value": value, "fee": 0},
            "proof": {"inputs": [], "outputs": [{"value": value, "owner": owner, "rho": rho}]}}


def t1():
    """A transparent transfer blob with public_value > 0 is rejected and does NOT touch the pool."""
    st = _fresh()
    res = st.apply_blob(_mint_blob(MINT), "ndoEve", "tx0")
    assert "public_value > 0" in res, f"mint was not rejected: {res!r}"
    assert st.shielded.size() == 0, f"rejected mint still appended a commitment (size {st.shielded.size()})"
    assert not st.unshield_withdrawals, "rejected mint recorded an unshield exit"


def t2():
    """The rejection happens BEFORE apply_transfer, so a rejected blob can never half-mutate the pool."""
    st = _fresh()
    before = (st.shielded.size(), len(st.shielded.nullifiers), dict(st.unshield_withdrawals), st.uw_nonce)
    st.apply_blob(_mint_blob(1), "ndoEve", "tx1")
    st.apply_blob(_mint_blob(MINT), "ndoEve", "tx2")
    after = (st.shielded.size(), len(st.shielded.nullifiers), dict(st.unshield_withdrawals), st.uw_nonce)
    assert before == after, f"pool state moved on a rejected mint: {before} -> {after}"


def t3():
    """The field (STARK) path bounds public_value to <= 0 too.

    This MUST use a GENUINELY VALID proof. A malformed bundle is rejected by verify_transfer long before
    the public_value bound is reached, so it would pass with or without the fence and prove nothing. Here
    the circuit is fully satisfied — v_in(1000) + public_value(MINT) == v_out(1000+MINT) + fee(0) — and the
    ONLY thing standing between the prover and MINT coins from nothing is the bound. Slow: real proving."""
    from execnode.stark import alghash
    from execnode import shielded_field as SF
    nsk, rho, VIN = 0x1111, 0x2222, 1000
    st = _fresh()
    st.field_pool.append(alghash.commit(VIN, alghash.owner_of(nsk), rho))     # one honestly-deposited note
    pos = st.field_pool.position(alghash.commit(VIN, alghash.owner_of(nsk), rho))
    bundle, public = SF.prove_transfer(st.field_pool, nsk, VIN, rho, pos,
                                       VIN + MINT, alghash.owner_of(0x3333), 0x4444,
                                       public_value=MINT, fee=0)
    # Sanity: the proof itself is sound — the circuit is happy to prove this statement.
    ok, why = __import__("execnode.shielded", fromlist=["x"]).verify_transfer(
        public, bundle, st.field_pool.knows_root)
    assert ok, f"test is not exercising the fence — the proof itself failed to verify: {why}"
    before = len(st.field_pool.commitments)
    res = st.apply_field_transfer(bundle)
    assert "out of range" in res, f"a VALID proof with public_value > 0 was accepted: {res!r}"
    assert len(st.field_pool.commitments) == before, "rejected field mint appended a commitment"
    assert not st.unshield_withdrawals, "rejected field mint recorded an unshield exit"


def t4():
    """REGRESSION GUARD: the legitimate escrow-driven deposit still works — apply_shield carries a
    positive public_value derived from the AUTHORITATIVE on-chain amount, and must NOT be fenced."""
    st = _fresh()
    owner, rho = owner_id(EVE["public_key"]), "rdep"
    res = st.apply_shield(1234, [note_commitment(1234, owner, rho)], [{"value": 1234, "owner": owner, "rho": rho}])
    assert not res.startswith("skip"), f"legitimate L1 shield deposit was wrongly rejected: {res!r}"
    assert st.shielded.size() == 1, f"legitimate deposit did not append its note (size {st.shielded.size()})"


def t5():
    """REGRESSION GUARD: the field-native escrow deposit path is likewise unaffected."""
    st = _fresh()
    res = st.apply_field_shield(4321, 0x1111, 0x2222)
    assert not res.startswith("skip"), f"legitimate field-shield deposit was wrongly rejected: {res!r}"
    assert len(st.field_pool.commitments) == 1, "legitimate field deposit did not append its note"


for name, fn in [("transparent mint (public_value > 0) rejected", t1),
                 ("rejected mint leaves pool state untouched", t2),
                 ("field-path mint (public_value > 0) rejected", t3),
                 ("legitimate L1 shield deposit still works", t4),
                 ("legitimate field-shield deposit still works", t5)]:
    check(name, fn)

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
