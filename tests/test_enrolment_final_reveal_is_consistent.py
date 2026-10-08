"""The final reveal of an enrolment gets the same verdict in validation and in apply (protocol.TPM_ENROL_V3_HEIGHT).

  * before the gate a last reveal whose joined secrets miss the client's commitment raises (the old rule, kept for replay);
  * from the gate it is accepted and the RECORD fails: state "failed", and faults() names nobody;
  * a matching commitment still proves, in both regimes;
  * two reveals in ONE block each validate against the parent record (neither is the last there), then apply in
    sequence: from the gate the block applies and the record fails; before the gate apply raised where validation
    passed — the inconsistency the gate removes.

Real credential blobs (tpm_aik.make_credential on a throwaway RSA key), a real throwaway state DB.
Run: python3 tests/test_enrolment_final_reveal_is_consistent.py
"""
import hashlib
import os
import struct
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-final-reveal-")    # never the live database (assign, not setdefault)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers", "private"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

import protocol as P                                                   # noqa: E402
import ops.account_ops as A                                            # noqa: E402
from ops import tpm_enrol as E, kv_ops                                 # noqa: E402
from ops.tpm_aik import credential_commitment, make_credential         # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa              # noqa: E402
from cryptography.hazmat.primitives import serialization               # noqa: E402

FAILED = []
GATE = 50_000
P.TPM_ENROL_V3_HEIGHT = GATE


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


def raises(fn):
    try:
        fn()
    except AssertionError:
        return True
    return False


def aik_pub_area():
    b = struct.pack(">HHI", 0x0001, 0x000B, 0x00050472) + b"\x00\x00" + struct.pack(">H", 0x0010)
    b += struct.pack(">HH", 0x0014, 0x000B) + struct.pack(">H", 2048) + struct.pack(">I", 0)
    return b + b"\x00\x00"


EK = rsa.generate_private_key(public_exponent=65537, key_size=2048)
EK_SPKI = EK.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
EK_ID = hashlib.sha256(EK_SPKI).hexdigest()
PUB = aik_pub_area()
NAME = E.aik_name_hex(PUB)
CH = ["chal-a" + "q" * 44, "chal-b" + "q" * 44]
SECRETS = {c: os.urandom(32) for c in CH}
SEEDS = {c: os.urandom(32) for c in CH}
BLOBS = {c: make_credential(EK_SPKI, bytes.fromhex(NAME), SECRETS[c], seed=SEEDS[c]) for c in CH}
GOOD = credential_commitment(b"".join(SECRETS[c] for c in sorted(CH)))
BAD = credential_commitment(b"not the secrets")


def committed(h0, commitment):
    """A v2 record (two challengers, both challenged) with the client's commitment at h0 + 3."""
    rec = E.new_record(EK_ID, EK_SPKI, NAME, PUB, "owner", h0, list(CH), pool=[[c, 1] for c in CH], k=2)
    for i, c in enumerate(CH):
        rec = E.apply_challenge(rec, c, BLOBS[c][0], BLOBS[c][1], h0 + 1 + i)
    return E.apply_commit(rec, "owner", commitment, h0 + 3)


def reveal_all(rec, h, fail):
    for i, c in enumerate(CH):
        rec = E.apply_reveal(rec, c, SECRETS[c], SEEDS[c], h + i, fail_on_mismatch=fail)
    return rec


# --- the pure transition ---------------------------------------------------------------------------------------------
pre = GATE - 100
check("before the gate a mismatching last reveal raises",
      raises(lambda: reveal_all(committed(pre, BAD), pre + 4, pre + 4 >= GATE)))
post = GATE + 100
r = reveal_all(committed(post, BAD), post + 4, post + 4 >= GATE)
check("from the gate a mismatching last reveal fails the record", r["state"] == E.STATE_FAILED, r["state"])
check("a failed record faults nobody", E.faults(r, CH) == [], E.faults(r, CH))
check("a failed record is not a proof", raises(lambda: E.proven_key(r)))
for h0 in (pre, post):
    ok = reveal_all(committed(h0, GOOD), h0 + 4, h0 + 4 >= GATE)
    check(f"a matching commitment still proves ({'from' if h0 >= GATE else 'before'} the gate)",
          ok["state"] == E.STATE_PROVEN, ok["state"])


# --- two reveals in one block: validation reads the parent, apply runs in sequence -----------------------------------
kv_ops.init_env()


def same_block(h0, commitment):
    rec = committed(h0, commitment)
    eid = hashlib.sha256(b"rec%d" % h0).hexdigest()[:32]      # one row per case
    kv_ops.tpm_enrol_set(eid, rec)
    hb = h0 + 4
    fail = hb >= GATE
    parent = kv_ops.tpm_enrol_get(eid)
    validated = all(not raises(lambda c=c: E.apply_reveal(parent, c, SECRETS[c], SEEDS[c], hb, fail_on_mismatch=fail))
                    for c in CH)
    txs = [{"recipient": "tpm_reveal", "sender": c,
            "data": {"id": eid, "secret": SECRETS[c].hex(), "seed": SEEDS[c].hex()}} for c in CH]

    def apply():
        for tx in txs:
            A.apply_tpm_enrol_tx(tx, hb)
    applied = not raises(apply)
    return validated, applied, kv_ops.tpm_enrol_get(eid)


v, a, rec = same_block(GATE + 1000, BAD)
check("from the gate: both reveals validate against the parent and the block applies", v and a, (v, a))
check("from the gate: the record ends failed", rec["state"] == E.STATE_FAILED, rec["state"])
v, a, rec = same_block(GATE + 2000, GOOD)
check("from the gate: a matching pair in one block proves", v and a and rec["state"] == E.STATE_PROVEN, (v, a, rec["state"]))
v, a, _ = same_block(GATE - 1000, BAD)
check("before the gate: validation passed both and apply raised (the old, inconsistent rule is replayed as it was)",
      v and not a, (v, a))

print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILURES")
sys.exit(1 if FAILED else 0)
