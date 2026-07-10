"""OPT-IN M-of-N MULTISIG accounts (consensus).

A multisig account is an ordinary "ndo…" address derived from a DESCRIPTOR instead of a keypair:

    descriptor      = {"threshold": M, "members": [sorted unique member addresses]}
    virtual pubkey  = blake2b_hash(["nado-msig-v1", M, members])         (domain-tagged, 64 hex)
    multisig address= make_address(virtual pubkey)                       (normal checksummed address)

Receiving needs nothing special — anyone can send to the derived address, and the account doc is
created on first credit like any other. SPENDING is where multisig differs from a keyed account:

  * the tx body carries "multisig": descriptor (inside the SIGNED body, committed by the txid), and
    NO top-level public_key (there is none — the descriptor hash plays that role, so PUBKEY-ONCE
    never stores anything for a multisig account and every spend re-carries its full descriptor);
  * the "signature" field is a LIST of {"public_key", "signature"} entries — each a normal ML-DSA-44
    signature over unhex(txid) by a DISTINCT descriptor member (bound member->key by make_address,
    exactly like proof_sender). At least `threshold` valid entries are required, and every entry
    must be valid (garbage/non-member/duplicate entries hard-fail rather than merely not counting,
    so acceptance is deterministic and verification work is bounded by len(members)).

Because each entry signs the txid — which commits the descriptor, recipient, amount and nonce —
co-signers can sign INDEPENDENTLY in any order (collect signatures offline, submit once M are in),
and no signature can be replayed onto a different spend. Multisig accounts are PAYMENT accounts
only: validate_transaction rejects reserved recipients (no bonding/mining/voting/HTLC duties), which
keeps every validator-identity assumption (one key == one identity) intact.

Nothing about a multisig address is marked on-chain in advance: the address IS the policy (the
checksum'd hash of it), the way a P2SH hash commits a script. Colliding a real keypair into a
descriptor address (or vice versa) requires a preimage on the domain-tagged blake2b — infeasible.

Browser/CLI reproducibility: every step is canonical-JSON + blake2b (see hashing.canonical_bytes),
so a phone derives the identical address and txid.
"""

from Curve25519 import verify, unhex
from hashing import blake2b_hash
from ops.address_ops import make_address, validate_address
from protocol import MULTISIG_MAX_MEMBERS


def multisig_virtual_pubkey(threshold: int, members: list) -> str:
    """The descriptor's domain-tagged hash — the string that stands in for a public key in address
    derivation. 64 hex chars (make_address uses the first 42). CONSENSUS-CRITICAL and mirrored by
    the browser wallet: ["nado-msig-v1", M, members] through canonical_bytes -> blake2b."""
    return blake2b_hash(["nado-msig-v1", int(threshold), list(members)])


def multisig_address(threshold: int, members: list) -> str:
    """Derive the multisig account address from its policy. Deterministic: same (threshold, sorted
    members) on any client -> same address. Different threshold OR member set -> unrelated address."""
    return make_address(multisig_virtual_pubkey(threshold, members))


def validate_descriptor(descriptor) -> tuple:
    """Shape-check a multisig descriptor and return (threshold, members). Raises AssertionError on
    any violation. Canonical form is enforced (exactly the two keys, members sorted + unique, every
    member a real non-reserved address) so ONE policy has ONE encoding -> ONE address; an equivalent-
    but-reordered descriptor is rejected rather than silently deriving a second address."""
    assert isinstance(descriptor, dict), "multisig descriptor must be an object"
    assert set(descriptor.keys()) == {"threshold", "members"}, \
        "multisig descriptor must have exactly {threshold, members}"
    threshold = descriptor["threshold"]
    members = descriptor["members"]
    assert isinstance(threshold, int) and not isinstance(threshold, bool), "multisig threshold must be an int"
    assert isinstance(members, list), "multisig members must be a list"
    assert 2 <= len(members) <= MULTISIG_MAX_MEMBERS, \
        f"multisig needs 2..{MULTISIG_MAX_MEMBERS} members"
    assert 1 <= threshold <= len(members), "multisig threshold must be 1..len(members)"
    assert all(isinstance(m, str) for m in members), "multisig members must be address strings"
    assert members == sorted(members), "multisig members must be sorted (canonical form)"
    assert len(set(members)) == len(members), "multisig members must be unique"
    for member in members:
        assert validate_address(member, allow_reserved=False), f"invalid multisig member address {member}"
    return threshold, members


def verify_multisig_origin(transaction) -> bool:
    """The multisig counterpart of validate_origin: prove the spend was authorized by the account's
    policy. Checks (raising on the first failure): descriptor is canonical, the SENDER is exactly
    the descriptor's derived address (the binding that makes the descriptor unforgeable — a wrong
    descriptor derives a different sender), and the signature list holds >= threshold entries, each
    by a DISTINCT member whose pubkey derives its member address (proof_sender logic) and whose
    ML-DSA signature over the txid verifies. Every entry must be valid — one bad entry rejects the
    tx (deterministic accept/reject; no 'count the good ones' ambiguity), and len(entries) is capped
    at len(members) so an attacker can't stuff entries to inflate verification cost."""
    threshold, members = validate_descriptor(transaction["multisig"])
    assert transaction["sender"] == multisig_address(threshold, members), \
        "sender is not the address derived from the multisig descriptor"

    entries = transaction.get("signature")
    assert isinstance(entries, list) and entries, "multisig tx needs a list of signature entries"
    assert len(entries) <= len(members), "more signature entries than members"

    message = unhex(transaction["txid"])
    signed_by = set()
    for entry in entries:
        assert isinstance(entry, dict), "each multisig signature entry must be an object"
        public_key = entry.get("public_key")
        signature = entry.get("signature")
        assert isinstance(public_key, str) and isinstance(signature, str), \
            "multisig signature entry needs public_key + signature hex"
        member = make_address(public_key)
        assert member in members, "signature by a non-member key"
        assert member not in signed_by, "duplicate signature by the same member"
        assert verify(signed=signature, public_key=public_key, message=message), \
            f"invalid multisig signature from {member}"
        signed_by.add(member)

    assert len(signed_by) >= threshold, \
        f"multisig needs {threshold} member signatures, got {len(signed_by)}"
    return True


# --- CLIENT-SIDE helpers (non-consensus): build a proposal, collect signatures, hand off ----------
# The co-signing flow is offline-first: one member drafts (the txid commits everything, including the
# descriptor), the proposal JSON is passed around by any channel, each member appends a signature
# entry, and whoever holds the M-th signature submits. Lazy imports avoid transaction_ops <-> here
# cycles (transaction_ops also imports this module lazily, from inside validate_origin).

def draft_multisig_spend(threshold, members, recipient, amount, fee, max_block, data=""):
    """Build an UNSIGNED multisig spend proposal: canonical descriptor + body + txid, with an empty
    signature list for members to fill. Raises if the descriptor is malformed. NOTE the landing
    window: max_block must be < 360 blocks ahead when the last signature lands and the tx is
    submitted (mempool hygiene drops anything staler), so collect signatures promptly or re-draft."""
    from hashing import create_nonce
    from config import get_timestamp_seconds
    from protocol import CHAIN_ID
    from ops.transaction_ops import create_txid
    members = sorted(members)
    threshold, members = validate_descriptor({"threshold": int(threshold), "members": members})
    body = {
        "sender": multisig_address(threshold, members),
        "recipient": recipient,
        "amount": int(amount),
        "timestamp": get_timestamp_seconds(),
        "data": data,
        "nonce": create_nonce(),
        "max_block": int(max_block),
        "chain_id": CHAIN_ID,
        "multisig": {"threshold": threshold, "members": members},
        "fee": int(fee),
    }
    body["txid"] = create_txid(body)
    body["signature"] = []
    return body


def add_member_signature(transaction, private_key):
    """Append one member's signature entry to a proposal (verifying the txid first, so a member can
    never be tricked into signing a body that doesn't match the id they're shown). Idempotent per
    member; raises if the key isn't a descriptor member. Returns (transaction, signatures_present)."""
    from Curve25519 import sign, from_private_key
    from ops.transaction_ops import create_txid
    threshold, members = validate_descriptor(transaction["multisig"])
    body = {k: v for k, v in transaction.items() if k not in ("signature", "txid")}
    assert create_txid(body) == transaction["txid"], "proposal txid does not match its contents"
    keydict = from_private_key(private_key)
    assert keydict["address"] in members, "this key is not a member of the multisig"
    entries = transaction.setdefault("signature", [])
    if not any(make_address(e.get("public_key", "")) == keydict["address"] for e in entries):
        entries.append({
            "public_key": keydict["public_key"],
            "signature": sign(private_key=private_key, message=unhex(transaction["txid"])),
        })
    return transaction, len(entries)
