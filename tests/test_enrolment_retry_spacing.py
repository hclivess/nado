"""A chip whose last enrolment its own client did not complete waits a growing spacing before enrolling again
(protocol.TPM_ENROL_V3_HEIGHT, TPM_RETRY_COOLDOWN_BASE, TPM_RETRY_COOLDOWN_MAX_EXP).

  * client_failed: a failed record, or a v2 record still open with every challenge posted and no commit — never one
    held up by a missing challenge, never a legacy or proven one;
  * retry_ready_at = expiry + BASE * 2^min(n, MAX) when client-failed, else expiry (the cap holds);
  * the count lives in the devbind row "tpmretry:<ek>", which devbind_rows never reads as a binding;
  * apply raises the count when a new enrolment replaces a client-failed one, and revert restores its exact prior value
    (also for a re-open under the same id); a record held up by a missing challenge leaves it unchanged.

Real apply path (account_ops.apply_tpm_enrol_tx) over a throwaway state DB; the endorsement-chain kernel is stubbed.
Run: python3 tests/test_enrolment_retry_spacing.py
"""
import hashlib
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-retry-spacing-")    # never the live database (assign, not setdefault)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers", "private"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

import protocol as P                                                   # noqa: E402
import ops.account_ops as A                                            # noqa: E402
from ops import tpm_enrol as E, kv_ops, attest_native                  # noqa: E402

FAILED = []
GATE = 50_000
P.TPM_ENROL_V3_HEIGHT = GATE
P.TPM_POOL_V2_HEIGHT = 1 << 62            # the legacy enrol path: no pool snapshot to build
BASE, MAXE = P.TPM_RETRY_COOLDOWN_BASE, P.TPM_RETRY_COOLDOWN_MAX_EXP


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


CH = ["chal-a" + "q" * 44, "chal-b" + "q" * 44]
EK_SPKI = b"\x30\x82spki-for-the-test"


def pub(tag):
    return b"\x00\x01pub-" + tag.encode()


def v2(ek, h, blobs=2, state=None, commit=False, tag="a"):
    rec = E.new_record(ek, EK_SPKI, E.aik_name_hex(pub(tag)), pub(tag), "owner", h, list(CH),
                       pool=[[c, 1] for c in CH], k=2)
    rec["blobs"] = sorted([[c, "11", "22", h + 1 + i] for i, c in enumerate(CH[:blobs])])
    if commit:
        rec["state"], rec["commit"], rec["hc"] = E.STATE_COMMITTED, "00" * 32, h + 5
    if state:
        rec["state"] = state
    return rec


# --- the pure functions ----------------------------------------------------------------------------------------------
EK0 = "e0" * 32
r_full = v2(EK0, 1000)
r_short = v2(EK0, 1000, blobs=1)
r_failed = v2(EK0, 1000, commit=True, state=E.STATE_FAILED)
r_commit = v2(EK0, 1000, commit=True)
r_proven = v2(EK0, 1000, commit=True, state=E.STATE_PROVEN)
r_legacy = E.new_record(EK0, EK_SPKI, E.aik_name_hex(pub("l")), pub("l"), "owner", 1000, list(CH))
r_legacy["blobs"] = sorted([[c, "11", "22", 1001] for c in CH])
check("a failed record is client-failed", E.client_failed(r_failed))
check("a v2 record open with every challenge posted and no commit is client-failed", E.client_failed(r_full))
check("a record held up by a missing challenge is not", not E.client_failed(r_short))
check("a committed record waiting on reveals is not", not E.client_failed(r_commit))
check("a proven record is not", not E.client_failed(r_proven))
check("a legacy record is not", not E.client_failed(r_legacy))
check("no record is not", not E.client_failed(None) and not E.client_failed({}))
end = E.expiry(r_full)
check("not client-failed: ready at expiry", E.retry_ready_at(r_short, 5) == end)
check("client-failed: expiry + BASE * 2^n", all(E.retry_ready_at(r_full, n) == end + BASE * (1 << n) for n in range(MAXE + 1)))
check("the exponent is capped", E.retry_ready_at(r_full, MAXE + 7) == end + BASE * (1 << MAXE))


# --- the count through apply / revert --------------------------------------------------------------------------------
kv_ops.init_env()
CUR = {"ek": None}
attest_native.verify_ek = lambda chain, t, height=None: {"ok": True, "identity": CUR["ek"]}
attest_native.ek_public_der = lambda der: EK_SPKI
A._tpm_anchor_time = lambda h: 1_800_000_000


def enrol_tx(tag):
    return {"recipient": "tpm_enrol", "sender": "owner", "data": {"ek": ["00"], "pub": pub(tag).hex()}}


def eid_of(ek, tag):
    return E.enrol_id(P.CHAIN_ID, ek, E.aik_name_hex(pub(tag)))


def case(ek, old, new_tag, start=0):
    """Put `old` on chain as the chip's open enrolment and the count at `start`; apply then revert a tpm_enrol of
    `new_tag` past the old one's retry point. Returns (count after apply, count after revert, marker after revert)."""
    CUR["ek"] = ek
    old_id = eid_of(ek, old["_tag"])
    rec = {k: v for k, v in old.items() if k != "_tag"}
    kv_ops.tpm_enrol_set(old_id, rec)
    kv_ops.tpm_enrol_open_set(ek, old_id)
    kv_ops.tpm_retry_set(ek, start)
    h = E.retry_ready_at(rec, start) + 3
    A.apply_tpm_enrol_tx(enrol_tx(new_tag), h)
    after = kv_ops.tpm_retry_get(ek)
    A.apply_tpm_enrol_tx(enrol_tx(new_tag), h, revert=True)
    return after, kv_ops.tpm_retry_get(ek), kv_ops.tpm_enrol_open_for_ek(ek), old_id


EK1 = "e1" * 32
a, r, m, oid = case(EK1, dict(v2(EK1, GATE + 10, tag="x"), _tag="x"), "y")
check("replacing a client-failed enrolment counts one", a == 1, a)
check("revert restores the count to its exact prior value (0: the row is gone)", r == 0, r)
check("revert restores the marker", m == oid, (m, oid))

EK2 = "e2" * 32
a, r, _m, _o = case(EK2, dict(v2(EK2, GATE + 10, commit=True, state=E.STATE_FAILED, tag="x"), _tag="x"), "y", start=3)
check("a failed record counts from a prior count", a == 4, a)
check("revert restores the prior count exactly (3)", r == 3, r)

EK3 = "e3" * 32
a, r, _m, _o = case(EK3, dict(v2(EK3, GATE + 10, blobs=1, tag="x"), _tag="x"), "y", start=2)
check("a record held up by a missing challenge does not count", a == 2 and r == 2, (a, r))

EK4 = "e4" * 32
a, r, m, oid = case(EK4, dict(v2(EK4, GATE + 10, tag="same"), _tag="same"), "same", start=1)
check("a re-open under the same id counts from the superseded record", a == 2, a)
check("and its revert restores the count and the record", r == 1 and m == oid
      and E.client_failed(kv_ops.tpm_enrol_get(oid)), (r, m))

EK5 = "e5" * 32
old5 = v2(EK5, 1000, tag="x")                         # opened and replaced before the gate
CUR["ek"] = EK5
kv_ops.tpm_enrol_set(eid_of(EK5, "x"), old5)
kv_ops.tpm_enrol_open_set(EK5, eid_of(EK5, "x"))
A.apply_tpm_enrol_tx(enrol_tx("y"), E.expiry(old5) + 1)
check("before the gate nothing is counted", kv_ops.tpm_retry_get(EK5) == 0)

# --- validation: a signed tpm_enrol through validate_transaction -----------------------------------------------------
import logging as _lg                                                  # noqa: E402
import struct                                                          # noqa: E402
import ops.transaction_ops as T                                        # noqa: E402
from signatures import generate_keydict, sign, unhex                   # noqa: E402

T._anchor_time = lambda tx, h: 1_800_000_000
T._tpm_pool = lambda h: {f"pool{i:02d}" + "q" * 44: 5 for i in range(12)}
_ROOT = sorted(P.DEVICE_ATTEST_EK_ROOTS)[0]
attest_native.verify_ek = lambda chain, t, roots=None, height=None: {"ok": True, "root_sha256": _ROOT,
                                                                     "identity": CUR["ek"], "ek_identity": CUR["ek"]}


def aik_area(policy):
    b = struct.pack(">HHI", 0x0001, 0x000B, 0x00050472) + struct.pack(">H", len(policy)) + policy
    b += struct.pack(">H", 0x0010) + struct.pack(">HH", 0x0014, 0x000B) + struct.pack(">H", 2048) + struct.pack(">I", 0)
    return b + b"\x00\x00"


opener = generate_keydict()


def verdict(h):
    tx = {"sender": opener["address"], "recipient": "tpm_enrol", "amount": 0, "fee": 0, "timestamp": 1,
          "data": {"ek": ["30" * 40], "pub": aik_area(b"retry").hex()}, "nonce": f"n{h}",
          "public_key": opener["public_key"], "max_block": h, "chain_id": P.CHAIN_ID}
    tx["txid"] = T.create_txid(tx)
    tx["signature"] = sign(private_key=opener["private_key"], message=unhex(tx["txid"]))
    try:
        T.validate_transaction(tx, _lg.getLogger("t"), block_height=h)
        return "accepted"
    except Exception as e:
        return f"{type(e).__name__}: {e}"


EK6 = "e6" * 32
CUR["ek"] = EK6
old6 = v2(EK6, GATE + 10, tag="x")                    # client-failed: every challenge posted, no commit
kv_ops.tpm_enrol_set(eid_of(EK6, "x"), old6)
kv_ops.tpm_enrol_open_set(EK6, eid_of(EK6, "x"))
kv_ops.tpm_retry_set(EK6, 2)
ready = E.retry_ready_at(old6, 2)
check("retry_ready_at with a count of 2 is expiry + 4 * BASE", ready == E.expiry(old6) + 4 * BASE)
v = verdict(ready - 1)
check("validation refuses a re-enrol one block before retry_ready_at", "can enrol again from block %d" % ready in v, v)
v = verdict(ready)
check("validation accepts it at retry_ready_at", v == "accepted", v)
view = T.tpm_retry_view(old6, ready - 10)
check("/tpm_enrolment serves the block validation accepts (tpm_retry_view)",
      view == {"client_failed": True, "retry_ready_at": ready}, view)
P.TPM_ENROL_V3_HEIGHT = 1 << 62
check("before the gate it serves the plain expiry", T.tpm_retry_view(old6, ready - 10)["retry_ready_at"] == E.expiry(old6))
v = verdict(E.expiry(old6))
check("before the gate validation applies no spacing (expiry is enough)", v == "accepted", v)
P.TPM_ENROL_V3_HEIGHT = GATE

kv_ops.tpm_retry_set(EK1, 2)
check("the count row is never read as a device binding",
      kv_ops.tpm_retry_get(EK1) == 2 and not any("tpmretry" in str(row[0]) or EK1 in str(row[0])
                                                 for row in kv_ops.devbind_rows()))

print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILURES")
sys.exit(1 if FAILED else 0)
