"""THE AUTHORIZATION COMMITMENT IS WIRED INTO CONSENSUS, AND THE AGGREGATE ENVELOPE ACTUALLY VERIFIES.

mldsa_block_auth used to be a module nothing called. Two separate things had to become true for it to be
real, and each fails silently in its own way:

  1. construct_block must COMMIT (auth_root, auth_count) inside the hash preimage, and verify_block must
     RECOMPUTE both from the block's own transactions. A commitment the verifier accepts instead of
     deriving is worthless — a prover would simply commit to a root covering fewer checks than the block
     demands, and "these zero authorizations are valid" is a proof of nothing.

  2. The aggregate envelope must verify against the statement the VERIFIER built, and the verifier must
     not secretly re-prove anything to do it. The first version of verify_block_authorizations called
     _items() to recover each sub-circuit's boundaries, which re-PROVES every sub-circuit — the answer
     comes out right and the whole point is lost.

This exercises a REAL ML-DSA-44 keypair and a REAL folded bundle. It is slow on purpose: a mock would pass
against code that proves nothing.
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.stark import mldsa_block_auth as AUTH, mldsa_sig_proof as SP, mldsa_verify as MV

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


# ---------------------------------------------------------------- the commitment is in the block hash
from ops import block_ops

txs = [{"txid": "aa" * 32, "sender": "nado1sender0000000000000000000000000", "recipient": "x",
        "amount": 1, "fee": 1, "signature": "00" * 8},
       {"txid": "bb" * 32, "sender": "nado1other00000000000000000000000000", "recipient": "y",
        "amount": 2, "fee": 1, "signature": "11" * 8}]

blk = block_ops.construct_block(block_timestamp=1, block_number=7, parent_hash="00" * 32,
                                creator="nado1creator000000000000000000000000", transaction_pool=list(txs),
                                block_reward=0, state_root="ab" * 32, exec_root="cd" * 32, exec_cursor=0)
check("auth_root" in blk and "auth_count" in blk, "construct_block stamps the authorization commitment")
r, c = AUTH.auth_commitments(blk)
check(blk["auth_root"] == r and blk["auth_count"] == c,
      "the stamped commitment equals the independent recomputation")
check(c == 2, f"auth_count counts both signing transactions (got {c})")

# the commitment is INSIDE the hash: change one txid and the block hash must move
blk2 = block_ops.construct_block(block_timestamp=1, block_number=7, parent_hash="00" * 32,
                                 creator="nado1creator000000000000000000000000",
                                 transaction_pool=[dict(txs[0], txid="cc" * 32), txs[1]],
                                 block_reward=0, state_root="ab" * 32, exec_root="cd" * 32, exec_cursor=0)
check(blk2["auth_root"] != blk["auth_root"], "a changed txid changes the committed root")
check(blk2["block_hash"] != blk["block_hash"], "and therefore changes block identity")

# a LIED commitment is caught by recomputation — this is the check verify_block performs
lied = dict(blk, auth_count=1)
_r, _c = AUTH.auth_commitments(lied)
check(_c != lied["auth_count"], "a block understating auth_count is caught by recomputation")

# ---------------------------------------------------------------- no state read in the leaf
# PUBKEY-ONCE lets a tx omit public_key. If the leaf depended on the resolved key the block hash would
# depend on state, which is the one thing the state_root gate already covers and must not be duplicated.
nokey = [{k: v for k, v in t.items() if k != "public_key"} for t in txs]
withkey = [dict(t, public_key="ff" * 64) for t in txs]
check(AUTH.auth_commitments({"block_number": 7, "block_transactions": nokey}) ==
      AUTH.auth_commitments({"block_number": 7, "block_transactions": withkey}),
      "the commitment does NOT depend on whether a tx carries its public key")

# ---------------------------------------------------------------- multisig counts its real checks
ms = [dict(txs[0], multisig={"m": 2}, signature=["00" * 8, "11" * 8, "22" * 8])]
ents = AUTH.auth_entries({"block_number": 7, "block_transactions": ms})
check(ents[0]["kind"] == AUTH.KIND_MULTISIG_MLDSA44 and ents[0]["sig_count"] == 3,
      "a multisig entry declares its kind and its REAL signature count")
check(AUTH.sig_checks({"block_number": 7, "block_transactions": ms}) == 3,
      "sig_checks counts signature verifications, not entries")

# ---------------------------------------------------------------- a REAL aggregate envelope verifies
from signatures import generate_keydict, sign, unhex

keys = generate_keydict()
pk_hex, sk_hex = keys["public_key"], keys["private_key"]
txid = "3f" * 32
sig_hex = sign(private_key=sk_hex, message=unhex(txid))
check(MV.verify(bytes.fromhex(pk_hex), unhex(txid), bytes.fromhex(sig_hex)),
      "the reference ML-DSA verifier accepts the signature we are about to prove")

PARTS = ("norm_z", "usehint")          # a real subset; the full 103-permutation bundle is a farm job
out = SP.prove_signature(bytes.fromhex(pk_hex), unhex(txid), bytes.fromhex(sig_hex), parts=PARTS)
check(out is not None, "prove_signature produced a folded bundle")
if out:
    bundle, publics, airs = out
    ok, why = SP.verify_signature(bundle, publics, airs)
    check(ok, f"the bundle verifies directly ({why})")

    # the SAME bundle through the block-level entry point, with the statement built by the verifier
    entry_block = {"block_number": 7, "parent_hash": "00" * 32,
                   "block_transactions": [{"txid": txid, "sender": "nado1s", "signature": sig_hex}]}
    root, count = AUTH.auth_commitments(entry_block)
    stmt = {"auth_version": AUTH.AUTH_VERSION, "auth_root": root, "auth_count": count,
            "height": 7, "parent": "00" * 32,
            "entries": AUTH.auth_entries(entry_block), "pubkeys": [pk_hex], "witnesses": [sig_hex]}
    env = {"bundles": [{"bundle": bundle, "publics": publics, "parts": list(PARTS)}]}
    check(SP.verify_block_authorizations(SP.BLOCK_AUTH_CIRCUIT_V1, env, stmt),
          "verify_block_authorizations accepts the envelope against the VERIFIER's statement")

    # a bundle that covers FEWER parts than it claims, or none at all, must not pass
    check(not SP.verify_block_authorizations(
        SP.BLOCK_AUTH_CIRCUIT_V1, {"bundles": [{"bundle": bundle, "publics": publics, "parts": []}]}, stmt),
        "an envelope declaring NO parts is rejected (a bundle covering nothing proves nothing)")
    check(not SP.verify_block_authorizations(SP.BLOCK_AUTH_CIRCUIT_V1, {"bundles": []}, stmt),
          "an envelope with fewer bundles than authorizations is rejected")
    check(not SP.verify_block_authorizations("some-other-circuit", env, stmt),
          "an unknown circuit id is rejected")

    # replay onto a DIFFERENT signature must fail: the statement is rebuilt from (pk, txid, sig)
    other = sign(private_key=sk_hex, message=unhex("7c" * 32))
    stmt2 = dict(stmt, witnesses=[other])
    check(not SP.verify_block_authorizations(SP.BLOCK_AUTH_CIRCUIT_V1, env, stmt2),
          "the bundle cannot be replayed onto a different signature")

print()
if fails:
    print(f"{len(fails)} CHECK(S) FAILED:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("ALL BLOCK-AUTH WIRING CHECKS PASSED")
