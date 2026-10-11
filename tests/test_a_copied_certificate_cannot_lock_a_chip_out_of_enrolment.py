"""A copied endorsement certificate cannot lock a chip's owner out of enrolment (protocol.TPM_RETRY_OWNER_HEIGHT).

A certificate is public and tpm_enrol is free, so before this gate a stranger could open an enrolment with a copied
certificate, never commit, and have the chip's retry count raised: a cooldown doubling to ~5.5 days per round against
the real owner. And a challenger posting its blob in the record's last blocks charged the client a failure it had no
time to avoid (review 2026-10-11).

  * the count row is the chip below the gate and (chip, opener) from it;
  * apply charges a failed record's OWN opener from the gate, and revert restores exactly that row;
  * validation holds back only the opener that failed: a stranger's failures leave the owner free at expiry, while the
    failing opener still waits its own spacing;
  * an all-answered record whose last challenge left the client fewer than TPM_REVEAL_GRACE blocks is not the client's
    failure from the gate, and still was below it (history replays unchanged).

Real apply path (account_ops.apply_tpm_enrol_tx) and validate_transaction over a throwaway state DB; the endorsement-
chain kernel is stubbed, as in test_enrolment_retry_spacing.
Run: python3 tests/test_a_copied_certificate_cannot_lock_a_chip_out_of_enrolment.py
"""
import logging
import os
import struct
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-retry-owner-")      # never the live database (assign)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers", "private"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

import protocol as P                                                   # noqa: E402
import ops.account_ops as A                                            # noqa: E402
import ops.transaction_ops as T                                        # noqa: E402
from ops import tpm_enrol as E, kv_ops, attest_native                  # noqa: E402
from signatures import generate_keydict, sign, unhex                   # noqa: E402

FAILED = []
V3, GATE = 50_000, 60_000
P.TPM_ENROL_V3_HEIGHT = V3
P.TPM_RETRY_OWNER_HEIGHT = GATE
P.TPM_POOL_V2_HEIGHT = 1 << 62
BASE, GRACE = P.TPM_RETRY_COOLDOWN_BASE, P.TPM_REVEAL_GRACE


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


CH = ["chal-a" + "q" * 44, "chal-b" + "q" * 44]
EK_SPKI = b"\x30\x82spki-for-the-test"
CUR = {"ek": None}


def pub(tag):
    return b"\x00\x01pub-" + tag.encode()


def failed_rec(ek, h, owner, last_blob=None, tag="x"):
    """A v2 record every challenger answered and its client never committed; the last blob at `last_blob`."""
    rec = E.new_record(ek, EK_SPKI, E.aik_name_hex(pub(tag)), pub(tag), owner, h, list(CH),
                       pool=[[c, 1] for c in CH], k=2)
    lb = h + 2 if last_blob is None else last_blob
    rec["blobs"] = sorted([[CH[0], "11", "22", h + 1], [CH[1], "11", "22", lb]])
    return rec


def eid_of(ek, tag):
    return E.enrol_id(P.CHAIN_ID, ek, E.aik_name_hex(pub(tag)))


def put_open(ek, rec, tag="x"):
    kv_ops.tpm_enrol_set(eid_of(ek, tag), rec)
    kv_ops.tpm_enrol_open_set(ek, eid_of(ek, tag))


kv_ops.init_env()
attest_native.ek_public_der = lambda der: EK_SPKI
A._tpm_anchor_time = lambda h: 1_800_000_000

# --- the row a failure is charged to -------------------------------------------------------------------------------
r = failed_rec("aa" * 32, GATE + 10, "stranger")
check("below the gate the count row is the chip alone", E.retry_key(r, GATE - 1) == "aa" * 32)
check("from the gate it is (chip, opener)", E.retry_key(r, GATE) == "aa" * 32 + ":stranger")

# --- the late-challenge grace ---------------------------------------------------------------------------------------
h0 = GATE + 100
late = failed_rec("ab" * 32, h0, "o", last_blob=E.expiry(failed_rec("ab" * 32, h0, "o")) - 10)
early = failed_rec("ab" * 32, h0, "o", last_blob=E.expiry(late) - GRACE - 1)
check("a last challenge inside the grace is not the client's failure from the gate", not E.client_failed(late, GATE))
check("one that left the client the grace still is", E.client_failed(early, GATE))
check("below the gate the late one still counted (history replays unchanged)",
      E.client_failed(late, GATE - 1) and E.client_failed(late))
check("retry_ready_at follows: no spacing after a late challenge", E.retry_ready_at(late, 3, GATE) == E.expiry(late))

# --- apply / revert charge the failed record's own opener ---------------------------------------------------------
attest_native.verify_ek = lambda chain, t, height=None, roots=None: {"ok": True, "identity": CUR["ek"],
                                                                     "ek_identity": CUR["ek"],
                                                                     "root_sha256": sorted(P.DEVICE_ATTEST_EK_ROOTS)[0]}
EK1 = "e1" * 32
CUR["ek"] = EK1
old = failed_rec(EK1, GATE + 10, "stranger")
put_open(EK1, old)
kv_ops.tpm_retry_set(EK1, 4)                                          # a pre-gate chip-wide count stays untouched
h = E.expiry(old) + 1
tx = {"recipient": "tpm_enrol", "sender": "owner", "data": {"ek": ["00"], "pub": pub("y").hex()}}
A.apply_tpm_enrol_tx(tx, h)
check("apply charges the stranger's own row", kv_ops.tpm_retry_get(EK1 + ":stranger") == 1)
check("and never the chip's", kv_ops.tpm_retry_get(EK1) == 4 and kv_ops.tpm_retry_get(EK1 + ":owner") == 0)
A.apply_tpm_enrol_tx(tx, h, revert=True)
check("revert restores exactly the row apply charged", kv_ops.tpm_retry_get(EK1 + ":stranger") == 0
      and kv_ops.tpm_retry_get(EK1) == 4, (kv_ops.tpm_retry_get(EK1 + ":stranger"), kv_ops.tpm_retry_get(EK1)))

EK0 = "e0" * 32                                                       # below the gate: the chip-wide row, as before
CUR["ek"] = EK0
old0 = failed_rec(EK0, V3 + 10, "stranger")
put_open(EK0, old0)
A.apply_tpm_enrol_tx(tx, E.expiry(old0) + 1)
check("below the gate apply still charges the chip", kv_ops.tpm_retry_get(EK0) == 1
      and kv_ops.tpm_retry_get(EK0 + ":stranger") == 0)
A.apply_tpm_enrol_tx(tx, E.expiry(old0) + 1, revert=True)
check("and its revert restores the chip row", kv_ops.tpm_retry_get(EK0) == 0)

# --- validation: the owner is free at expiry; the failing opener waits its own spacing --------------------------------
T._anchor_time = lambda tx, h: 1_800_000_000
T._tpm_pool = lambda h: {f"pool{i:02d}" + "q" * 44: 5 for i in range(12)}


def aik_area(policy):
    b = struct.pack(">HHI", 0x0001, 0x000B, 0x00050472) + struct.pack(">H", len(policy)) + policy
    b += struct.pack(">H", 0x0010) + struct.pack(">HH", 0x0014, 0x000B) + struct.pack(">H", 2048) + struct.pack(">I", 0)
    return b + b"\x00\x00"


def verdict(kd, h, nonce):
    t = {"sender": kd["address"], "recipient": "tpm_enrol", "amount": 0, "fee": 0, "timestamp": 1,
         "data": {"ek": ["30" * 40], "pub": aik_area(nonce.encode()).hex()}, "nonce": nonce,
         "public_key": kd["public_key"], "max_block": h, "chain_id": P.CHAIN_ID}
    t["txid"] = T.create_txid(t)
    t["signature"] = sign(private_key=kd["private_key"], message=unhex(t["txid"]))
    try:
        T.validate_transaction(t, logging.getLogger("t"), block_height=h)
        return "accepted"
    except Exception as e:                                             # noqa: BLE001
        return f"{type(e).__name__}: {e}"


victim, stranger = generate_keydict(), generate_keydict()
EK2 = "e2" * 32
CUR["ek"] = EK2
bad = failed_rec(EK2, GATE + 10, stranger["address"])
put_open(EK2, bad)
kv_ops.tpm_retry_set(EK2 + ":" + stranger["address"], 8)              # the stranger has failed this chip many times
end = E.expiry(bad)
v = verdict(victim, end, "v1")
check("the chip's owner enrols at the stranger's record's expiry, with no spacing", v == "accepted", v)
ready = E.retry_ready_at(bad, 8, end)
v = verdict(stranger, end, "s1")
check("the stranger waits its own spacing", f"can enrol again from block {ready}" in v and ready > end, v)
v = verdict(stranger, ready, "s2")
check("and is accepted at it", v == "accepted", v)
P.TPM_RETRY_OWNER_HEIGHT = 1 << 62                                     # below the gate: the chip-wide rule, as before
kv_ops.tpm_retry_set(EK2, 8)
v = verdict(victim, end, "v2")
check("below the gate the owner was held to the chip-wide spacing (the hole this closes)", "can enrol again" in v, v)
P.TPM_RETRY_OWNER_HEIGHT = GATE

print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILURES")
sys.exit(1 if FAILED else 0)
