"""THE CHALLENGER DUTY (loops/core_loop.maybe_tpm_challenge) — the loop without which the whole
vendor-endorsed path is dead.

Consensus accepts a COMPLETED enrolment, but an enrolment only completes if the drawn challengers answer
it. Nothing else in the system answers; every bonded node runs this, which is what makes the challenger
set something the network supplies rather than a service someone operates. So the properties pinned here
are the ones that decide whether a real machine ever gets attested:

  - a drawn challenger seals a credential the prover's chip can actually open;
  - it persists (secret, seed) BEFORE broadcasting, so a restart between the two does not strand the
    enrolment — update waves restart the whole fleet routinely;
  - it NEVER reveals before the prover's commitment is on chain, which is the entire security argument;
  - a node that was not drawn stays out of it.

Run: python3 tests/test_tpm_challenger_loop.py
"""
import hashlib
import json
import logging
import os
import struct
import sys
import tempfile
import types

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_tpmchal_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers", "private"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

logger = logging.getLogger("tpmchal"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers                                   # noqa: E402
create_indexers()

import protocol as P                                                  # noqa: E402
from ops import kv_ops, tpm_aik, tpm_enrol as E                       # noqa: E402
from ops.key_ops import generate_keys                                 # noqa: E402
import loops.core_loop as core_loop                                   # noqa: E402
from loops.core_loop import CoreClient as Core                        # noqa: E402

_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


class FakeMem:
    def __init__(self, kd, tip):
        self.keydict = kd
        self.address = kd["address"]
        self.latest_block = {"block_number": tip}
        self.transaction_pool = []
        self.submitted = []

    def merge_transaction(self, tx, user_origin=False):
        self.submitted.append(tx)
        self.transaction_pool.append(tx)
        return {"result": True}


def software_chip():
    """A stand-in prover: an RSA endorsement key and a valid restricted-signing public area. The chip's
    ROLE here is only to be sealed to — whether real silicon opens the credential is tests/test_swtpm's
    question, and it answers yes."""
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.primitives import hashes, serialization
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    spki = key.public_key().public_bytes(serialization.Encoding.DER,
                                         serialization.PublicFormat.SubjectPublicKeyInfo)
    decrypt = lambda ct: key.decrypt(ct, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                                      algorithm=hashes.SHA256(), label=b"IDENTITY\x00"))
    pub = (struct.pack(">HHI", 0x0001, 0x000B, 0x00050472) + b"\x00\x00" + struct.pack(">H", 0x0010)
           + struct.pack(">HH", 0x0014, 0x000B) + struct.pack(">H", 2048) + struct.pack(">I", 0)
           + b"\x00\x00")
    return spki, decrypt, pub


def main():
    P.DEVICE_ATTEST_EK_HEIGHT = P.DEVICE_ATTEST_EK_HEIGHT or 1
    gate = P.DEVICE_ATTEST_EK_HEIGHT
    tip = gate + 500
    kd = generate_keys()
    me = kd["address"]
    mem = FakeMem(kd, tip)
    core = types.SimpleNamespace(memserver=mem, logger=logger)
    for m in ("maybe_tpm_challenge", "maybe_tpm_prune_secrets", "_tpm_tx_pending",
              "_tpm_secrets_path", "_tpm_secrets_load", "_tpm_secrets_save"):
        setattr(core, m, getattr(Core, m).__get__(core))

    # every bonded identity is drawable; this node is bonded and the other two challengers are not us
    core_loop.get_bonded_registry = lambda: {me: {"bonded": 10 ** 12},
                                             "other1": {"bonded": 10 ** 12},
                                             "other2": {"bonded": 10 ** 12}}

    ek_spki, decrypt, aik_pub = software_chip()
    ek_id = hashlib.sha256(ek_spki).hexdigest()
    name_hex = E.aik_name_hex(aik_pub)
    eid = E.enrol_id(P.CHAIN_ID, ek_id, name_hex)
    others = ["other1", "other2"]
    rec = E.new_record(ek_id, ek_spki, name_hex, aik_pub, "prover", tip - 10, sorted([me] + others))
    kv_ops.tpm_enrol_set(eid, rec)

    # --- the challenge -----------------------------------------------------------------------------
    core.maybe_tpm_challenge()
    check("a drawn challenger sends a challenge", len(mem.submitted) == 1
          and mem.submitted[0]["recipient"] == "tpm_challenge", [t["recipient"] for t in mem.submitted])
    ch = mem.submitted[0]
    check("the challenge lands strictly after the enrolment", int(ch["min_block"]) > int(rec["h"]))
    check("the challenge is fee-exempt and zero-amount", ch["fee"] == 0 and ch["amount"] == 0)

    # THE SECRET IS ON DISK BEFORE THE BROADCAST. A challenger that publishes a blob and then loses its
    # secret can never reveal, and the prover's chip has to start over with a new attestation key.
    with open(f"{os.environ['HOME']}/nado/private/tpm_challenges.json") as f:
        store = json.load(f)
    check("the secret was persisted before broadcasting", eid in store and len(store[eid]["secret"]) == 64)

    # AND THE PROVER'S CHIP CAN OPEN IT. This is the point of the whole message.
    blob = bytes.fromhex(ch["data"]["blob"])
    enc = bytes.fromhex(ch["data"]["enc"])
    opened = tpm_aik.activate_credential(decrypt, blob, enc, bytes.fromhex(name_hex))
    check("the chip opens what this node sealed", opened == bytes.fromhex(store[eid]["secret"]))

    # --- it does not mint duplicates, and does not reveal early ------------------------------------
    core.maybe_tpm_challenge()
    check("no duplicate while ours is in flight", len(mem.submitted) == 1, len(mem.submitted))

    mem.transaction_pool.clear()
    rec = E.apply_challenge(rec, me, blob, enc, tip - 5)
    kv_ops.tpm_enrol_set(eid, rec)
    core.maybe_tpm_challenge()
    check("no second challenge once ours is on chain", len(mem.submitted) == 1, len(mem.submitted))

    # THE ATTACK THE WHOLE DESIGN EXISTS TO STOP: revealing while the prover has not committed lets a
    # prover with no chip read the secret off the chain and commit to it afterwards.
    secrets_all = {me: bytes.fromhex(store[eid]["secret"])}
    for c in others:
        s_c, r_c = os.urandom(32), os.urandom(32)
        secrets_all[c] = s_c
        b_c, e_c = tpm_aik.make_credential(ek_spki, bytes.fromhex(name_hex), s_c, seed=r_c)
        rec = E.apply_challenge(rec, c, b_c, e_c, tip - 4)
    kv_ops.tpm_enrol_set(eid, rec)
    core.maybe_tpm_challenge()
    check("NEVER reveals before the prover has committed", len(mem.submitted) == 1,
          [t["recipient"] for t in mem.submitted])

    # --- the reveal, once the commitment is on chain -------------------------------------------------
    joined = b"".join(secrets_all[c] for c in sorted(secrets_all))
    rec = E.apply_commit(rec, "prover", tpm_aik.credential_commitment(joined), tip - 3)
    kv_ops.tpm_enrol_set(eid, rec)
    core.maybe_tpm_challenge()
    check("reveals once the commitment is on chain", len(mem.submitted) == 2
          and mem.submitted[1]["recipient"] == "tpm_reveal", [t["recipient"] for t in mem.submitted])
    rv = mem.submitted[1]["data"]
    check("it reveals the SAME secret it sealed", rv["secret"] == store[eid]["secret"]
          and rv["seed"] == store[eid]["seed"])
    check("the revealed pair reproduces the published blob",
          tpm_aik.make_credential(ek_spki, bytes.fromhex(name_hex),
                                  bytes.fromhex(rv["secret"]), seed=bytes.fromhex(rv["seed"]))[0] == blob)

    # A RESTART BETWEEN CHALLENGE AND REVEAL MUST NOT STRAND IT — the secret came off disk, so a fresh
    # process with an empty memory still reveals correctly.
    mem2 = FakeMem(kd, tip)
    core2 = types.SimpleNamespace(memserver=mem2, logger=logger)
    for m in ("maybe_tpm_challenge", "maybe_tpm_prune_secrets", "_tpm_tx_pending",
              "_tpm_secrets_path", "_tpm_secrets_load", "_tpm_secrets_save"):
        setattr(core2, m, getattr(Core, m).__get__(core2))
    core2.maybe_tpm_challenge()
    check("a restarted node still reveals what it sealed",
          len(mem2.submitted) == 1 and mem2.submitted[0]["data"]["secret"] == store[eid]["secret"])

    # --- a node that was not drawn stays out ---------------------------------------------------------
    kd2 = generate_keys()
    mem3 = FakeMem(kd2, tip)
    core3 = types.SimpleNamespace(memserver=mem3, logger=logger)
    for m in ("maybe_tpm_challenge", "maybe_tpm_prune_secrets", "_tpm_tx_pending",
              "_tpm_secrets_path", "_tpm_secrets_load", "_tpm_secrets_save"):
        setattr(core3, m, getattr(Core, m).__get__(core3))
    core_loop.get_bonded_registry = lambda: {kd2["address"]: {"bonded": 10 ** 12}}
    core3.maybe_tpm_challenge()
    check("a node that was not drawn sends nothing", mem3.submitted == [])

    # AN UNBONDED NODE THAT WAS DRAWN MUST STILL ANSWER. The draw moved to recent block producers, and a
    # producer need not be bonded; a leftover bonded-registry gate here meant the first real enrolment on
    # the chain sat with zero challenges for 107 blocks while three drawn producers ignored it.
    core_loop.get_bonded_registry = lambda: {}
    mem.submitted.clear()
    mem.transaction_pool.clear()
    # ISOLATE IT: the loop sends ONE message per pass over all live enrolments, so an earlier record
    # still awaiting our reveal would answer first and this case would test the wrong thing.
    kv_ops.tpm_enrol_del(eid)
    rec_open = E.new_record(ek_id, ek_spki, name_hex, aik_pub, "prover", tip - 10, sorted([me] + others))
    kv_ops.tpm_enrol_set("b" * 32, rec_open)
    core.maybe_tpm_challenge()
    check("a DRAWN but unbonded node still answers", len(mem.submitted) == 1
          and mem.submitted[0]["recipient"] == "tpm_challenge",
          [t["recipient"] for t in mem.submitted])
    kv_ops.tpm_enrol_del("b" * 32)
    kv_ops.tpm_enrol_set(eid, rec)
    mem.submitted.clear()
    mem.transaction_pool.clear()

    # --- proven enrolments stop costing anything, and their secrets are forgotten --------------------
    core_loop.get_bonded_registry = lambda: {me: {"bonded": 10 ** 12}}
    rec2 = dict(rec); rec2["state"] = "proven"
    kv_ops.tpm_enrol_set(eid, rec2)
    core.maybe_tpm_challenge()
    check("a proven enrolment is not answered again", mem.submitted == [])
    with open(f"{os.environ['HOME']}/nado/private/tpm_challenges.json") as f:
        check("its secret is pruned", json.load(f) == {})

    print("\n" + ("ALL OK" if not _fails else f"{len(_fails)} FAILURES"))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
