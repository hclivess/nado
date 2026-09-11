"""ops/tpm_enrol — THE ORDERING IS THE PROOF, so the ordering is what this test attacks.

ops/tpm_aik checks the arithmetic of one challenge. The arithmetic is happily satisfied by a fabrication: a
client with no chip at all picks a secret and a seed, computes the blob itself, and every equation holds.
What makes the enrolment mean something is that each message landed in a block strictly after the one it
answers. Every case below is a real way to try to collapse that, and each must be refused.

Run: python3 tests/test_tpm_enrol.py
"""
import hashlib
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="nado-enrol-"))
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def refuses(name, fn):
    try:
        fn()
        check(f"refuses {name}", False, "it was accepted")
    except (AssertionError, ValueError):     # a rule violation and a malformed input are both refusals
        check(f"refuses {name}", True)


def aik_pub_area(exponent=0):
    """A minimal restricted RSA-2048 signing key's TPMT_PUBLIC — what validate_aik_pub_area demands."""
    import struct
    b = struct.pack(">HHI", 0x0001, 0x000B, 0x00050472) + b"\x00\x00" + struct.pack(">H", 0x0010)
    b += struct.pack(">HH", 0x0014, 0x000B) + struct.pack(">H", 2048) + struct.pack(">I", exponent)
    return b + b"\x00\x00"


def main():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    from ops import tpm_enrol as E
    from ops.tpm_aik import credential_commitment, make_credential

    ek = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ek_spki = ek.public_key().public_bytes(serialization.Encoding.DER,
                                           serialization.PublicFormat.SubjectPublicKeyInfo)
    ek_id = hashlib.sha256(ek_spki).hexdigest()
    pub = aik_pub_area()
    name_hex = E.aik_name_hex(pub)
    eid = E.enrol_id("nado-25", ek_id, name_hex)

    check("the enrolment id is derived, not chosen", eid == E.enrol_id("nado-25", ek_id, name_hex)
          and len(eid) == 32)
    check("a different chain generation is a different enrolment", E.enrol_id("nado-26", ek_id, name_hex) != eid)
    check("the public area must be a restricted signing key", "restricted" in E.validate_publication(ek_id, pub))
    refuses("an unrestricted signing key", lambda: E.validate_publication(ek_id, aik_pub_area_unrestricted()))

    # --- the challenger draw ------------------------------------------------------------------------------
    # WEIGHTS ARE PLAIN INTEGERS. They were registry entries until the draw moved to recent block
    # producers; the signature changed and the body did not, and every enrolment then died with
    # "'int' object is not subscriptable" in production. The shape is pinned here now.
    reg = {f"addr{i:02d}": (i + 1) for i in range(12)}
    picked = E.challenger_set(eid, reg, "beacon-a", 3)
    check("the draw yields exactly k challengers", len(picked) == 3, picked)
    check("the challengers are distinct", len(set(picked)) == 3, picked)
    check("the draw is deterministic", E.challenger_set(eid, reg, "beacon-a", 3) == picked)
    check("a different beacon draws a different set — the client cannot wait for a set it likes",
          E.challenger_set(eid, reg, "beacon-b", 3) != picked
          or E.challenger_set(eid, reg, "beacon-c", 3) != picked)
    check("a different enrolment draws independently",
          E.challenger_set("f" * 32, reg, "beacon-a", 3) != picked
          or E.challenger_set("e" * 32, reg, "beacon-a", 3) != picked)
    check("an empty registry draws nobody, rather than a weaker set",
          E.challenger_set(eid, {}, "beacon-a", 3) == [])
    check("a set too small to seat k returns what it has, so the caller can refuse",
          len(E.challenger_set(eid, {"solo": 10}, "beacon-a", 3)) == 1)
    check("a zero weight is never seated", "nobody" not in
          E.challenger_set(eid, dict(reg, nobody=0), "beacon-a", 3))
    # THE BUG THAT REACHED PRODUCTION: a wrong-shaped weight must be a clean rejection, because
    # validate_transaction promises AssertionError and an escaping TypeError in block verification is
    # the difference between a rejected block and a fork.
    refuses("a registry entry where an integer belongs",
            lambda: E.challenger_set(eid, {"a": {"bonded": 5}}, "beacon-a", 3))
    refuses("a string weight", lambda: E.challenger_set(eid, {"a": "5"}, "beacon-a", 3))

    # --- the honest flow ----------------------------------------------------------------------------------
    secrets = {c: os.urandom(32) for c in picked}
    seeds = {c: os.urandom(32) for c in picked}
    blobs = {c: make_credential(ek_spki, bytes.fromhex(name_hex), secrets[c], seed=seeds[c])
             for c in picked}

    def fresh():
        return E.new_record(ek_id, ek_spki, name_hex, pub, "owner1", 100, picked)

    rec = fresh()
    for i, c in enumerate(picked):
        rec = E.apply_challenge(rec, c, blobs[c][0], blobs[c][1], 101 + i)
    commitment = credential_commitment(b"".join(secrets[c] for c in sorted(picked)))
    rec = E.apply_commit(rec, "owner1", commitment, 110)
    for i, c in enumerate(picked):
        rec = E.apply_reveal(rec, c, secrets[c], seeds[c], 111 + i)
    check("an honest enrolment reaches proven", rec["state"] == E.STATE_PROVEN, rec["state"])
    check("the proven key names the chip and the attestation key",
          E.proven_key(rec) == f"{ek_id}:{name_hex}")

    # --- the orderings that must not be collapsible -------------------------------------------------------
    r = fresh()
    refuses("a challenge in the enrolment's own block", lambda: E.apply_challenge(r, picked[0], blobs[picked[0]][0], blobs[picked[0]][1], 100))
    refuses("a challenge from someone who was not drawn",
            lambda: E.apply_challenge(r, "outsider", blobs[picked[0]][0], blobs[picked[0]][1], 101))
    r1 = E.apply_challenge(r, picked[0], blobs[picked[0]][0], blobs[picked[0]][1], 101)
    refuses("a second challenge from the same challenger",
            lambda: E.apply_challenge(r1, picked[0], blobs[picked[0]][0], blobs[picked[0]][1], 102))
    refuses("a commitment before every challenger has been heard",
            lambda: E.apply_commit(r1, "owner1", commitment, 105))

    r2 = r1
    for i, c in enumerate(picked[1:]):
        r2 = E.apply_challenge(r2, c, blobs[c][0], blobs[c][1], 102 + i)
    refuses("a commitment in the last challenge's own block",
            lambda: E.apply_commit(r2, "owner1", commitment, 103))
    refuses("a commitment from anyone but the identity that opened the enrolment",
            lambda: E.apply_commit(r2, "someone-else", commitment, 110))
    r3 = E.apply_commit(r2, "owner1", commitment, 110)
    refuses("a challenge after the commitment", lambda: E.apply_challenge(r3, picked[0], b"x", b"y", 111))

    # THE ATTACK THE WHOLE DESIGN EXISTS TO STOP: reveal in the commitment's own block, so a client that reads
    # the block can pick its commitment after seeing the secret.
    c0 = picked[0]
    refuses("a reveal in the commitment's own block",
            lambda: E.apply_reveal(r3, c0, secrets[c0], seeds[c0], 110))
    refuses("a challenger revealing a secret it did not seal",
            lambda: E.apply_reveal(r3, c0, os.urandom(32), seeds[c0], 111))
    refuses("a challenger revealing a different seed",
            lambda: E.apply_reveal(r3, c0, secrets[c0], os.urandom(32), 111))
    refuses("a reveal from a challenger with nothing sealed",
            lambda: E.apply_reveal(r3, "outsider", secrets[c0], seeds[c0], 111))
    r4 = E.apply_reveal(r3, c0, secrets[c0], seeds[c0], 111)
    refuses("a second reveal from the same challenger",
            lambda: E.apply_reveal(r4, c0, secrets[c0], seeds[c0], 112))
    check("one reveal short is not proven", r4["state"] == E.STATE_COMMITTED)
    try:
        E.proven_key(r4)
        check("an unproven enrolment yields no key", False, "it yielded one")
    except AssertionError:
        check("an unproven enrolment yields no key", True)

    # A CLIENT THAT OPENED ONLY SOME OF THE CHALLENGES MUST FAIL, or k-of-k collapses to 1-of-k. It commits to
    # what it really recovered plus a guess for the rest; every blob check passes and only the final
    # commitment catches it.
    bad = credential_commitment(b"".join((secrets[c] if c == c0 else os.urandom(32))
                                         for c in sorted(picked)))
    rb = fresh()
    for i, c in enumerate(picked):
        rb = E.apply_challenge(rb, c, blobs[c][0], blobs[c][1], 101 + i)
    rb = E.apply_commit(rb, "owner1", bad, 110)
    for c in picked[:-1]:
        rb = E.apply_reveal(rb, c, secrets[c], seeds[c], 111)
    last = picked[-1]
    refuses("a client that only opened some of its challenges",
            lambda: E.apply_reveal(rb, last, secrets[last], seeds[last], 112))

    # AND A CHIP-FREE FABRICATION MUST BE UNREACHABLE THROUGH THIS INTERFACE. The client can compute a
    # perfectly valid blob for its own secret — the state machine refuses it because the client is not one of
    # the drawn challengers, which is the entire difference between a proof and a self-assertion.
    mine_s, mine_r = os.urandom(32), os.urandom(32)
    mine_blob, mine_enc = make_credential(ek_spki, bytes.fromhex(name_hex), mine_s, seed=mine_r)
    refuses("a client sealing its own challenge",
            lambda: E.apply_challenge(fresh(), "owner1", mine_blob, mine_enc, 101))

    print("\n" + ("ALL OK" if not _fails else f"{len(_fails)} FAILURES"))
    return 1 if _fails else 0


def aik_pub_area_unrestricted():
    import struct
    b = struct.pack(">HHI", 0x0001, 0x000B, 0x00050472 & ~0x00010000) + b"\x00\x00" + struct.pack(">H", 0x0010)
    b += struct.pack(">HH", 0x0014, 0x000B) + struct.pack(">H", 2048) + struct.pack(">I", 0)
    return b + b"\x00\x00"


if __name__ == "__main__":
    sys.exit(main())
