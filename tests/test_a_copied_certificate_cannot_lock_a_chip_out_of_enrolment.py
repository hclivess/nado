"""A copied endorsement certificate cannot lock a chip's owner out of enrolment (gen 28's
TPM_RETRY_OWNER_HEIGHT, inlined in G9: the rule holds from block 1).

A certificate is public and tpm_enrol is free, so before this rule a stranger could open an enrolment with a copied
certificate, never commit, and have the chip's retry count raised: a cooldown doubling to ~5.5 days per round against
the real owner. And a challenger posting its blob in the record's last blocks charged the client a failure it had no
time to avoid (review 2026-10-11).

  * the count row is (chip, opener) from block 1 — the chip alone only at height 0 (admission on a genesis tip);
  * apply charges a failed record's OWN opener, and revert restores exactly that row;
  * validation holds back only the opener that failed: a stranger's failures leave the owner free at expiry, while the
    failing opener still waits its own spacing;
  * only a wrong commitment is the client's failure: an all-answered record never committed is ambiguous (a
    challenger can seal a secret no chip opens, or post in the last block) and charges nobody — judged at height 0 or
    with no height it still counts, as it did (the `< 1` / None the inlined gate kept).
The gen-28 halves (apply and validation below the gate) are retired in G9: generation 28's rules.

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
GATE = 60_000                                          # a height of the story (the gates are inlined; nothing to set)
BASE = P.TPM_RETRY_COOLDOWN_BASE


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
# the v2 pool apply snapshots and validation checks (every enrolment is v2 from block 1; the synthetic chain has no blocks)
T.tpm_pool_v2 = lambda h: {f"pool{i:02d}" + "q" * 44: 5 for i in range(12)}

# --- the row a failure is charged to -------------------------------------------------------------------------------
r = failed_rec("aa" * 32, GATE + 10, "stranger")
check("at height 0 (admission on a genesis tip) the count row is the chip alone", E.retry_key(r, 0) == "aa" * 32)
check("from block 1 it is (chip, opener)", E.retry_key(r, 1) == "aa" * 32 + ":stranger"
      and E.retry_key(r, GATE) == "aa" * 32 + ":stranger")

# --- only a wrong commitment is the client's failure -------------------------------------------------------------
h0 = GATE + 100
late = failed_rec("ab" * 32, h0, "o", last_blob=E.expiry(failed_rec("ab" * 32, h0, "o")) - 10)
early = failed_rec("ab" * 32, h0, "o", last_blob=h0 + 3)
wrong = dict(early, state=E.STATE_FAILED)
check("an all-answered, never-committed record charges nobody from block 1 (late or early challenge)",
      not E.client_failed(late, GATE) and not E.client_failed(early, GATE) and not E.client_failed(early, 1))
check("a wrong commitment still does", E.client_failed(wrong, GATE))
check("judged at height 0 or with no height the all-answered record still counts (the kept `< 1` / None)",
      E.client_failed(late, 0) and E.client_failed(early))
check("retry_ready_at follows: no spacing after an unanswered commit", E.retry_ready_at(early, 3, GATE) == E.expiry(early))
check("and the doubling after a wrong commitment", E.retry_ready_at(wrong, 3, GATE) == E.expiry(wrong) + BASE * 8)

# --- apply / revert charge the failed record's own opener ---------------------------------------------------------
attest_native.verify_ek = lambda chain, t, height=None, roots=None: {"ok": True, "identity": CUR["ek"],
                                                                     "ek_identity": CUR["ek"],
                                                                     "root_sha256": sorted(P.DEVICE_ATTEST_EK_ROOTS)[0]}
EK1 = "e1" * 32
CUR["ek"] = EK1
old = dict(failed_rec(EK1, GATE + 10, "stranger"), state=E.STATE_FAILED)
put_open(EK1, old)
kv_ops.tpm_retry_set(EK1, 4)                                          # a chip-wide count row stays untouched
h = E.expiry(old) + 1
tx = {"recipient": "tpm_enrol", "sender": "owner", "data": {"ek": ["00"], "pub": pub("y").hex()}}
A.apply_tpm_enrol_tx(tx, h)
check("apply charges the stranger's own row", kv_ops.tpm_retry_get(EK1 + ":stranger") == 1)
check("and never the chip's", kv_ops.tpm_retry_get(EK1) == 4 and kv_ops.tpm_retry_get(EK1 + ":owner") == 0)
A.apply_tpm_enrol_tx(tx, h, revert=True)
check("revert restores exactly the row apply charged", kv_ops.tpm_retry_get(EK1 + ":stranger") == 0
      and kv_ops.tpm_retry_get(EK1) == 4, (kv_ops.tpm_retry_get(EK1 + ":stranger"), kv_ops.tpm_retry_get(EK1)))

# (apply below the gate charging the chip-wide row is retired in G9: generation 28's rules)

# --- validation: the owner is free at expiry; the failing opener waits its own spacing --------------------------------
T._anchor_time = lambda tx, h: 1_800_000_000


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
bad = dict(failed_rec(EK2, GATE + 10, stranger["address"]), state=E.STATE_FAILED)
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
# (below the gate the owner was held to the chip-wide spacing — the hole this closed; retired in G9: generation 28's rules)

print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILURES")
sys.exit(1 if FAILED else 0)
