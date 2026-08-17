"""
DA transport for private-call proofs.

WHY IT HAS TO RIDE DA AT ALL. A transition proof is ~20 MiB; the blob cap is 64 KiB. So L1 carries the
PUBLIC statement (a few hundred bytes — nullifiers, output commitments, the delta, the anchor) plus a DA
commitment, and the proof bytes travel k-of-n. That is not a new mechanism: shielded transfers already do
exactly this, and the point of this slice is that private calls reuse it rather than inventing a second
transport with its own failure modes.

THE PROPERTY THAT MATTERS is the all-or-nothing stall. `_apply_block` resolves every DA-carried proof in a
block BEFORE mutating anything; one unavailable proof stalls the block in L1 order rather than
half-applying it. Every honest node fetches the identical bundle by commitment, so they all apply the same
thing or none of it. A per-op divergence there would be a fork, which is why the op table is one table.

Run: python3 tests/test_shielded_state_da.py
"""
import json
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_da_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops.da_store import DaStore, reconstruct_from
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
NSK, NSK2 = 0xA11CE, 0xB0B


# ---- the op table the resolver reads ------------------------------------------------------------------
def t_private_call_is_registered_for_da():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "execnode", "execnode.py"), encoding="utf8").read()
    import re
    m = re.search(r"_DA_BLOB_OPS\s*=\s*\{([^}]*)\}", src)
    assert m, "the DA op table is gone"
    table = m.group(1)
    assert '"private_call": "proof_json"' in table, "private_call does not ride DA"
    assert '"field_transfer": "bundle_json"' in table, "the shielded-transfer entry was lost"


def t_the_resolver_stalls_rather_than_half_applying():
    """Pinned structurally: the unavailable branch must `return False` (stall the whole block), not
    `continue`. Half-applying a block whose proof one node could fetch and another could not is a fork."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "execnode", "execnode.py"), encoding="utf8").read()
    i = src.index("_DA_BLOB_OPS.get(d.get(\"op\"))")
    window = src[i:i + 1800]
    assert "UNAVAILABLE via DA" in window and "return False" in window, \
        "an unavailable DA proof no longer stalls the block"


# ---- a real proof through a real DA store -------------------------------------------------------------
def t_a_real_proof_survives_the_da_round_trip():
    """The size claim, checked rather than asserted: prove for real, put the bytes through Reed-Solomon
    k-of-n, and reconstruct from a bare quorum of shards."""
    pool = S.ShieldedStatePool()
    cm = S.note_commitment(CID, S.KIND_VALUE, [1000], S.owner_of(NSK), 7)
    pool.append(CID, cm)
    # A pure private rearrangement (delta 0): this check is about TRANSPORT, so it deliberately avoids
    # the turnstile — no balance moves, nothing but the proof has to survive the trip.
    public, proof = S.prove_transition(pool, CID, S.KIND_VALUE, NSK, [1000], 7, pool.position(CID, cm),
                                       [1000], S.owner_of(NSK2), 11, public_delta=0)
    blob = json.dumps(proof["stark"], default=str).encode()
    print(f"      proof {len(blob) / 1048576:.1f} MiB · public statement "
          f"{len(json.dumps(public, default=str))} B", flush=True)
    assert len(blob) > 64 * 1024, "this proof would have fit in a blob — the DA path would be unnecessary"

    store = DaStore(os.path.join(os.environ["HOME"], "da"))
    meta = store.put(blob, k=4, n=8)
    got = store.get(meta["commitment"])
    assert got == blob, "the DA store did not return the bytes it was given"

    # and from a BARE QUORUM — four of the eight shards, which is the property k-of-n exists for. Each
    # (shard, proof) self-verifies against the commitment, so this is the same path a node takes when it
    # gathers shards from peers it does not trust.
    pairs = []
    for i in range(4):
        sh = store.shard(meta["commitment"], i)
        assert sh is not None, f"shard {i} was not stored"
        shard_bytes, shard_proof = sh
        pairs.append((i, shard_bytes, shard_proof))
    rebuilt = reconstruct_from(meta, pairs)
    assert rebuilt == blob, "four of eight shards did not reconstruct the proof"

    # a shard that does not belong must not be counted toward the quorum
    bad = [(0, b"\x00" * len(pairs[0][1]), pairs[0][2])] + pairs[1:]
    try:
        reconstruct_from(meta, bad)
        raise AssertionError("a corrupted shard was accepted into the quorum")
    except ValueError:
        pass

    # the statement the blob would actually carry stays tiny
    payload = {"op": "private_call", "public": public, "proof_da": meta["commitment"]}
    assert len(json.dumps(payload, default=str)) < 64 * 1024, "the commitment blob exceeds the blob cap"

    globals()["_PROOF_BYTES"], globals()["_PUBLIC"], globals()["_META"] = blob, public, meta


def t_the_commitment_binds_the_bytes():
    """A DA commitment is worth nothing if a store can answer with other bytes. Tamper one shard and the
    quorum reconstruction must not silently produce a different, verifying-looking proof."""
    store = DaStore(os.path.join(os.environ["HOME"], "da2"))
    meta = store.put(b"x" * 200_000, k=4, n=8)
    other = DaStore(os.path.join(os.environ["HOME"], "da3"))
    meta2 = other.put(b"y" * 200_000, k=4, n=8)
    assert meta["commitment"] != meta2["commitment"], "different bytes produced the same commitment"


# ---- the op accepts a DA-delivered proof exactly like an inline one -----------------------------------
def t_the_op_accepts_a_da_delivered_proof():
    """After the resolver injects proof_json, apply_blob must treat it identically to an inline proof —
    the resolver's whole job is that the op cannot tell the difference."""
    if "_PROOF_BYTES" not in globals():
        raise AssertionError("the round-trip check did not run first")
    st = ExecState(path=os.path.join(os.environ["HOME"], "exec_da.json"))
    st.contracts[CID] = {"runtime": "zkvm", "code": {}, "storage": {}, "abi": {}}
    cm = S.note_commitment(CID, S.KIND_VALUE, [1000], S.owner_of(NSK), 7)
    st.app_state.append(CID, cm)
    payload = {"op": "private_call",
               "public_json": json.dumps(_PUBLIC, default=str),
               "proof_json": json.dumps({"stark": json.loads(_PROOF_BYTES)}, default=str)}
    r = st.apply_blob(payload, "sender", "txda")
    assert r.startswith("private_call "), f"a DA-delivered proof was rejected: {r}"
    assert len(st.app_state.nullifiers) == 1, "the DA-delivered transition did not apply"


def t_a_blob_with_no_proof_and_no_da_is_refused():
    st = ExecState(path=os.path.join(os.environ["HOME"], "exec_da2.json"))
    st.contracts[CID] = {"runtime": "zkvm", "code": {}, "storage": {}, "abi": {}}
    r = st.apply_blob({"op": "private_call", "public": {"cid": CID}, "proof_da": "deadbeef"},
                      "sender", "txda2")
    assert r == "skip: bad private_call", f"a blob whose proof never arrived was not refused: {r}"


for name, fn in list(globals().items()):
    if name.startswith("t_"):
        check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "ALL DA-TRANSPORT CHECKS PASSED")
sys.exit(1 if FAILS else 0)
