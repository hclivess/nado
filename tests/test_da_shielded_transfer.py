"""
DA-backed shielded transfer (end-to-end): a shielded-transfer STARK proof is too big for an L1 blob, so
only the transfer STATEMENT + the proof's DA `commitment` ride on-chain and the ~MB proof rides the DA layer.
This proves the soundness+determinism the fix is for: a proof published to DA and resolved by commitment on a
DIFFERENT node applies to the IDENTICAL committed root as the node that produced it — so the shielded pool
is now reconstructible by every exec node from the L1-ordered stream, not just the operator that held the POST.

Run: python3 tests/test_da_shielded_transfer.py   (slow — generates a real STARK proof)
"""
import os, sys, json, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode.stark import alghash
from execnode import shielded_field as SF
from ops.da_store import DaStore, reconstruct_from

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def _state_with_note(nsk, value, rho):
    """Fresh exec state whose field pool holds one spendable note commit(value, owner_of(nsk), rho)."""
    st = ExecState(path=tempfile.mktemp(prefix="nado_das_", suffix=".json"))
    st.apply_field_shield(value, alghash.owner_of(nsk), rho)
    return st


def t1_da_carried_transfer_matches_inline():
    """A proof carried through DA (erasure-coded, reconstructed by commitment on a second node) applies to
    the same state_root as applying it inline — DA transport is transparent and deterministic."""
    nsk, value, rho = 0x1111, 1000, 0x2222
    a = _state_with_note(nsk, value, rho)          # node that proves
    b = _state_with_note(nsk, value, rho)          # node that only ever sees the L1 blob + DA
    assert a.state_root() == b.state_root(), "same shield -> identical starting root"

    cm = alghash.commit(value, alghash.owner_of(nsk), rho)
    pos = a.field_pool.position(cm)
    bundle, _public = SF.prove_transfer(a.field_pool, nsk, value, rho, pos,
                                        950, alghash.owner_of(0x3333), 0x4444, public_value=0, fee=50)
    bundle_json = json.dumps(bundle)               # what the delegated prover produces; too big for a blob

    # publish the PROOF to DA; the on-chain blob would carry only proof_da = this commitment
    da = DaStore(tempfile.mkdtemp(prefix="nado_das_store_"))
    meta = da.put(bundle_json.encode(), 4, 8)

    # node B resolves the proof from DA by commitment, TRUSTLESSLY (k+1 verified shards), never having seen it
    pairs = [(i, *da.shard(meta["commitment"], i)) for i in range(meta["k"] + 1)]
    fetched = reconstruct_from(meta, pairs).decode()
    assert fetched == bundle_json, "DA reconstructs the exact proof bytes"

    ra = a.apply_blob({"op": "field_transfer", "bundle_json": bundle_json}, "s", "txA")   # inline
    rb = b.apply_blob({"op": "field_transfer", "bundle_json": fetched}, "s", "txB")       # via DA
    assert "skip" not in ra.lower(), f"inline apply failed: {ra}"
    assert "skip" not in rb.lower(), f"DA apply failed: {rb}"
    assert a.state_root() == b.state_root(), "DA-carried transfer == inline: identical committed root"


def t2_unavailable_is_detectable_not_silent():
    """A proof nobody published can't be reconstructed — get() returns None (a detectable availability
    failure that stalls the block in order), rather than silently applying a wrong/empty transfer."""
    da = DaStore(tempfile.mkdtemp(prefix="nado_das_none_"))
    assert da.get("de" * 32) is None, "unknown commitment -> not reconstructible (no silent corruption)"


for name, fn in sorted(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
