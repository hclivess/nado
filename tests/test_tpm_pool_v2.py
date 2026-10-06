"""TPM challenger pool v2: online stake, k = 5, misses excluded (protocol.TPM_POOL_V2_HEIGHT, operator-approved
2026-10-06).

An enrolment opened at h >= the gate is a v2 record:
  POOL      bonded >= B_MIN at the enrol block AND an FFG duty landed in >= TPM_POOL_PRESENCE_MIN DISTINCT epochs of the
            proven window AND not excluded; weight bonded // B_MIN;
  SNAPSHOT  the record stores "pool" and "k" (5) and the delayed draw reads them, never a recomputation;
  PENALTY   a drawn challenger that failed a v2 record (open at expiry without its challenge, or in commit at expiry
            without its reveal) sits out v2 pools for TPM_MISS_EXCLUDE_BLOCKS from that record's expiry — and a record
            whose CLIENT abandoned it, or committed too late to leave a reveal window, faults nobody;
  DUTIES    GET /tpm_duty?address= tells a wallet challenger what it owes, with the node loop's own bounds.
Older records keep exactly the gen-28 draw (replay must not move).

Synthetic chain (the pool reads committed blocks only) over a real throwaway state DB.
Run: python3 tests/test_tpm_pool_v2.py
"""
import ast
import asyncio
import logging
import os
import struct
import sys
import tempfile
import types

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-tpmpool2-")        # never the live database (assign, not setdefault)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers", "private"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

import protocol as P                                                   # noqa: E402
import ops.block_ops as B                                              # noqa: E402
import ops.transaction_ops as T                                        # noqa: E402
import ops.account_ops as A                                            # noqa: E402
from ops import tpm_enrol as E, kv_ops, attest_native                  # noqa: E402

FAILED = []
L = P.EPOCH_LENGTH
BM = P.B_MIN
X = P.TPM_MISS_EXCLUDE_BLOCKS


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


def refused(fn, needle=""):
    try:
        fn()
    except AssertionError as e:
        return needle in str(e)
    return False


# --- the synthetic chain --------------------------------------------------------------------------------------------
GATE = 7200
H = GATE + 2 * L + 13                                  # a v2 enrol
HI_E = (H // L)                                        # the enrol block's epoch: the window is the 100 epochs before it
TOP = H + 3 * X                                        # far enough for every exclusion window below


def addr(tag, i=0):
    s = f"{tag}{i:03d}"
    return s + "q" * (50 - len(s))


VALS = [addr("val", i) for i in range(12)]             # always present, weights 1..12
EDGE, BURST, POOR, EXACT, LATE = addr("edge"), addr("burst"), addr("poor"), addr("exact"), addr("late")
PRESENCE = {a: (lambda e: True, 1) for a in VALS}
PRESENCE[EDGE] = (lambda e: HI_E - 50 <= e < HI_E, 1)          # exactly the threshold
PRESENCE[BURST] = (lambda e: HI_E - 49 <= e < HI_E, 40)        # one short, however many txs it lands
PRESENCE[POOR] = (lambda e: True, 1)
PRESENCE[EXACT] = (lambda e: True, 1)
PRESENCE[LATE] = (lambda e: e >= HI_E, 1)                      # starts after the enrol (bonds and joins later)
HOLES = set()


def block(n):
    n = int(n)
    if n < 1 or n > TOP or n in HOLES:
        return None
    txs = []
    if n % L == 5:
        for a, (pred, cnt) in PRESENCE.items():
            if pred(n // L):
                txs += [{"recipient": "duty", "sender": a}] * cnt
    if n % L == 7:
        txs += [{"recipient": "tpm_ready", "sender": a} for a in VALS[:6]]
    return {"block_transactions": txs}


def reset_caches():
    T._tpm_presence_cache[0] = None
    T._tpm_proven_cache[0] = None
    T._tpm_producer_cache[0] = None


T.get_block_number = block
B.epoch_beacon = lambda e: "%064x" % ((e * 2654435761 + 7) % (1 << 256))
kv_ops.init_env()
for i, a in enumerate(VALS):
    kv_ops.account_set(a, "bonded", (i + 1) * BM + BM // 2)
kv_ops.account_set(EDGE, "bonded", 2 * BM)
kv_ops.account_set(BURST, "bonded", 50 * BM)
kv_ops.account_set(POOR, "bonded", BM - 1)
kv_ops.account_set(EXACT, "bonded", BM)

LIVE_GATE = P.TPM_POOL_V2_HEIGHT
P.TPM_POOL_V2_HEIGHT = GATE

# === 1. POOL ELIGIBILITY ============================================================================================
reset_caches()
pres = T._duty_presence(H)
check("presence counts DISTINCT epochs, not transactions", pres[BURST] == 49 and pres[EDGE] == 50 and pres[VALS[0]] == 100,
      (pres.get(BURST), pres.get(EDGE), pres.get(VALS[0])))
pool = T.tpm_pool_v2(H)
check("exactly TPM_POOL_PRESENCE_MIN distinct epochs is enough", EDGE in pool, sorted(pool))
check("one epoch short is not, however many duty txs it landed (a burst cannot buy presence)", BURST not in pool)
check("the bond floor: B_MIN - 1 is out, exactly B_MIN is in with weight 1", POOR not in pool and pool.get(EXACT) == 1)
check("weight is bonded // B_MIN", all(pool[a] == i + 1 for i, a in enumerate(VALS)) and pool[EDGE] == 2, pool)
check("an account with no presence before the enrol epoch is not in the pool", LATE not in pool)
check("the pool is exactly the online stake", set(pool) == set(VALS) | {EDGE, EXACT}, sorted(pool))
check("the old pool weights duty counts (the burst would dominate it) — the v2 pool does not",
      T._recent_producers(H).get(BURST, 0) > T._recent_producers(H).get(VALS[0], 0) and BURST not in pool)
lo, hi = T.proven_window(H)
check("the presence window is the proven window: the 100 epochs before the enrol block's epoch",
      (hi - lo) // L == P.DEVICE_ATTEST_EK_PROVEN_WINDOW // L and hi == HI_E * L, (lo, hi))
_reads = [0]
T.get_block_number = lambda n: (_reads.__setitem__(0, _reads[0] + 1), block(n))[1]
T._duty_presence(H)
T.get_block_number = block
check("the presence scan is cached per window (no rescan per validation)", _reads[0] == 0, _reads[0])
reset_caches()
HOLES.add(lo + 17)
try:
    T._duty_presence(H)
    check("a missing block in the window DEFERS (WindowUnavailable), never guesses", False, "no exception")
except T.WindowUnavailable as e:
    check("a missing block in the window DEFERS (WindowUnavailable), never guesses", (e.lo, e.hi) == (lo, hi))
HOLES.clear()
reset_caches()

# === 2. THE APPLY PATH: snapshot, k, rollback ========================================================================
EK = "ab" * 32
EK_SPKI = b"\x30" * 12
attest_native.verify_ek = lambda chain, now, roots=None, height=None: {
    "ok": True, "identity": EK, "ek_identity": EK, "root_sha256": sorted(P.DEVICE_ATTEST_EK_ROOTS)[0]}
attest_native.ek_public_der = lambda der: EK_SPKI
A._tpm_anchor_time = lambda h: 0
OWNER = addr("owner")


def aik_pub_area(policy: bytes = b""):
    b = struct.pack(">HHI", 0x0001, 0x000B, 0x00050472) + struct.pack(">H", len(policy)) + policy
    b += struct.pack(">H", 0x0010) + struct.pack(">HH", 0x0014, 0x000B) + struct.pack(">H", 2048) + struct.pack(">I", 0)
    return b + b"\x00\x00"


def enrol_tx(pub):
    return {"recipient": "tpm_enrol", "sender": OWNER, "data": {"ek": ["30"], "pub": pub.hex()}}


def apply(tx, h, revert=False):
    with kv_ops.write_txn():
        A.apply_tpm_enrol_tx(tx, h, revert=revert)


def eid_of(pub):
    return E.enrol_id(P.CHAIN_ID, EK, E.aik_name_hex(pub))


def raw_row(eid):
    return kv_ops._unpack(kv_ops._read(lambda txn: txn.get(kv_ops._tpm_enrol_key(eid), db=kv_ops._dbs()["devbind"])))


def wipe():
    with kv_ops.write_txn():
        for e, _r in kv_ops.tpm_enrols_all():
            kv_ops.tpm_enrol_del(e)
        kv_ops.tpm_enrol_open_set(EK, None)


PUB = aik_pub_area(b"v2")
EID = eid_of(PUB)
apply(enrol_tx(PUB), H)
rec = kv_ops.tpm_enrol_get(EID)
check("a v2 enrolment stores its pool snapshot, sorted [address, weight] pairs",
      rec.get("pool") == [[a, w] for a, w in sorted(pool.items())], rec.get("pool"))
check("a v2 enrolment stores k = 5", rec.get("k") == 5 == P.DEVICE_ATTEST_EK_CHALLENGERS_V2 and E.record_k(rec) == 5)
check("a v2 record is the 16-field row (the legacy 13 + pool, k, missed)", len(raw_row(EID)) == 16 and rec["missed"] == [])
check("...and is still told apart from a 2-3 field device binding", kv_ops._is_enrol_record(raw_row(EID)))
opens = E.draw_opens(H)
drawn = T.tpm_drawn_challengers(rec, opens)
check("a v2 draw seats k = 5 distinct challengers", len(drawn) == 5 and len(set(drawn)) == 5, drawn)
check("the v2 draw is the exact draw over the STORED pool with the draw epoch's beacon",
      drawn == E.challenger_set_exact(E.draw_key(EK), E.pool_weights(rec), B.epoch_beacon(E.draw_epoch(H)), 5))
# frozen: stake moves after the enrol, a newcomer piles in — the draw does not move, and nothing recomputes the pool
kv_ops.account_set(VALS[0], "bonded", 900 * BM)
kv_ops.account_set(LATE, "bonded", 900 * BM)
_real_pool = T.tpm_pool_v2
T.tpm_pool_v2 = lambda h: (_ for _ in ()).throw(RuntimeError("the draw recomputed the pool"))
try:
    again = T.tpm_drawn_challengers(rec, opens + 40)
    check("bonding after the enrol does not change the draw (the snapshot is read, never recomputed)", again == drawn,
          (again, drawn))
finally:
    T.tpm_pool_v2 = _real_pool
reset_caches()
check("...while a pool recomputed later WOULD have moved (the snapshot is what holds it)",
      T.tpm_pool_v2(H + 2 * L).get(VALS[0]) == 900)
kv_ops.account_set(VALS[0], "bonded", BM + BM // 2)
kv_ops.account_set(LATE, "bonded", 0)
reset_caches()

# rollback of the enrol, and of the materialising challenge, restores exactly
apply(enrol_tx(PUB), H, revert=True)
check("rolling back a v2 enrol removes the record", kv_ops.tpm_enrol_get(EID) is None)
apply(enrol_tx(PUB), H)
undrawn = kv_ops.tpm_enrol_get(EID)
ch = {"recipient": "tpm_challenge", "sender": drawn[0], "data": {"id": EID, "blob": "11" * 40, "enc": "22" * 40}}
apply(ch, opens)
mat = kv_ops.tpm_enrol_get(EID)
check("the first challenge materialises all five", mat["challengers"] == sorted(drawn) and len(mat["blobs"]) == 1)
apply(ch, opens, revert=True)
check("rolling back the materialising challenge restores the v2 record exactly (pool, k, missed included)",
      kv_ops.tpm_enrol_get(EID) == undrawn and len(raw_row(EID)) == 16)
wipe()

# === 3. EXCLUSION: exactly the right parties, in each failure shape ==================================================
EXP = H + E.enrol_window(H)


def drawn_for(policy, h=H):
    pub = aik_pub_area(policy)
    r = E.new_record(EK, EK_SPKI, E.aik_name_hex(pub), pub, OWNER, h, [], pool=sorted(pool.items()), k=5)
    return sorted(T.tpm_drawn_challengers(r, E.draw_opens(h)))


def put_v2(policy, state, blobs=(), reveals=(), materialise=True, h=H, hc=None):
    pub = aik_pub_area(policy)
    r = E.new_record(EK, EK_SPKI, E.aik_name_hex(pub), pub, OWNER, h, [], pool=sorted(pool.items()), k=5)
    d = T.tpm_drawn_challengers(r, E.draw_opens(h))
    if materialise:
        r["challengers"] = sorted(d)
    r["blobs"] = sorted([a, "11", "22", E.draw_opens(h) + 1] for a in blobs)
    r["reveals"] = sorted([a, "33", "44", E.draw_opens(h) + 5] for a in reveals)
    r["state"] = state
    if state == "commit":
        r["commit"], r["hc"] = "00" * 32, (E.draw_opens(h) + 3 if hc is None else hc)
    with kv_ops.write_txn():
        kv_ops.tpm_enrol_set(eid_of(pub), r)
    return eid_of(pub), r, sorted(d)


_, r_a, d_a = put_v2(b"never", "open", materialise=False)
check("open at expiry, never materialised: EVERY drawn challenger (recomputed from the snapshot) is at fault",
      T.tpm_record_faults(r_a) == d_a and len(d_a) == 5, (T.tpm_record_faults(r_a), d_a))
check("...and they are out of a v2 pool built at the expiry", not (set(d_a) & set(T.tpm_pool_v2(EXP))))
check("...but not while the record is still live (expiry - 1)", set(d_a) <= set(T.tpm_pool_v2(EXP - 1)))
check("...still out at expiry + TPM_MISS_EXCLUDE_BLOCKS - 1", set(d_a) <= T._tpm_excluded(EXP + X - 1))
check("...and back at expiry + TPM_MISS_EXCLUDE_BLOCKS (one day, then the seat returns)",
      not T._tpm_excluded(EXP + X) and set(d_a) <= set(T.tpm_pool_v2(EXP + X)))
wipe()

answered = drawn_for(b"partial")[:2]
_, r_b, d_b = put_v2(b"partial", "open", blobs=answered)
check("open at expiry with two challenges: exactly the three that never challenged are at fault",
      T._tpm_excluded(EXP) == set(d_b) - set(answered), (sorted(T._tpm_excluded(EXP)), d_b, answered))
wipe()

d_c = drawn_for(b"commit")
_, r_c, d_c = put_v2(b"commit", "commit", blobs=d_c, reveals=d_c[:3])
check("commit at expiry: exactly the challengers holding a challenge but no reveal are at fault",
      T._tpm_excluded(EXP) == set(d_c[3:]), (sorted(T._tpm_excluded(EXP)), d_c))
wipe()
G = P.TPM_REVEAL_GRACE
put_v2(b"commit", "commit", blobs=d_c, reveals=[], hc=EXP - G)
check("a commit landing within TPM_REVEAL_GRACE of expiry faults NOBODY (the client chose to leave no time)",
      T._tpm_excluded(EXP) == set())
put_v2(b"commit", "commit", blobs=d_c, reveals=[], hc=EXP - G - 1)
check("...one block earlier the challengers had their window, and the silent ones are at fault",
      T._tpm_excluded(EXP) == set(d_c))
wipe()

_, r_d, d_d = put_v2(b"abandon", "open", blobs=drawn_for(b"abandon"))
check("every challenger answered and the CLIENT never committed: nobody is at fault", T._tpm_excluded(EXP) == set())
wipe()

put_v2(b"proven", "proven", blobs=drawn_for(b"proven"), reveals=drawn_for(b"proven"))
check("a proven record faults nobody", T._tpm_excluded(EXP) == set())
wipe()

legacy_pub = aik_pub_area(b"legacy")
legacy = E.new_record(EK, EK_SPKI, E.aik_name_hex(legacy_pub), legacy_pub, OWNER, GATE - 500, [])
with kv_ops.write_txn():
    kv_ops.tpm_enrol_set(eid_of(legacy_pub), legacy)
check("a legacy record that expired open faults nobody (old records keep their behaviour)",
      T._tpm_excluded(GATE - 500 + E.enrol_window(GATE - 500)) == set())
wipe()

# a short pool (stake moved inside the enrol block between validation and apply) could never be drawn: nobody at fault
short = E.new_record(EK, EK_SPKI, E.aik_name_hex(PUB), PUB, OWNER, H, [], pool=[[VALS[0], 1], [VALS[1], 1]], k=5)
check("a snapshot that cannot seat k faults nobody (no set was ever anyone's duty)", T.tpm_record_faults(short) == [])

# === 3b. THE RETRY CARRIES THE MISS (a superseding enrol under the same id would otherwise erase it) =================
apply(enrol_tx(PUB), H)
first = kv_ops.tpm_enrol_get(EID)
d_first = sorted(T.tpm_drawn_challengers(first, opens))
RETRY = EXP + 3
apply(enrol_tx(PUB), RETRY)                       # the chip retries with the same key: same id, the row is superseded
second = kv_ops.tpm_enrol_get(EID)
check("the retry supersedes the expired record in place (same id, a new v2 record)", second["h"] == RETRY)
check("...and carries the misses of the record it replaced", second["missed"] == [[EXP, a] for a in d_first],
      second["missed"])
check("...so the failed challengers stay out of the pool after the retry", set(d_first) <= T._tpm_excluded(RETRY + 50))
check("...and were already left out of the retry's own snapshot", not (set(d_first) & {p[0] for p in second["pool"]}))
stripped = dict(second, missed=[])
with kv_ops.write_txn():
    kv_ops.tpm_enrol_set(EID, stripped)
check("WITHOUT the carry the retry would have erased the miss (why it exists)", not (set(d_first) & T._tpm_excluded(RETRY + 50)))
with kv_ops.write_txn():
    kv_ops.tpm_enrol_set(EID, second)
apply(enrol_tx(PUB), RETRY, revert=True)
check("rolling back the superseding enrol restores the expired record exactly", kv_ops.tpm_enrol_get(EID) == first)
check("the exclusion seen in validation (parent state) equals the one apply saw (carried)",
      T._tpm_excluded(RETRY) == set(d_first))
wipe()

# === 4. VALIDATION: k = 5 must be seatable; below the gate the old rule holds =======================================
from signatures import generate_keydict, sign, unhex                       # noqa: E402
T._anchor_time = lambda tx, h: 1_790_000_000
opener = generate_keydict()


def signed(kd, recipient, data, h):
    tx = {"sender": kd["address"], "recipient": recipient, "amount": 0, "fee": 0, "timestamp": 1, "data": data,
          "nonce": f"n{h}{recipient}", "public_key": kd["public_key"], "max_block": h, "chain_id": P.CHAIN_ID}
    tx["txid"] = T.create_txid(tx)
    tx["signature"] = sign(private_key=kd["private_key"], message=unhex(tx["txid"]))
    return tx


def verdict(h, policy=b"val"):
    try:
        T.validate_transaction(signed(opener, "tpm_enrol", {"ek": ["30" * 40], "pub": aik_pub_area(policy).hex()}, h),
                               logging.getLogger("t"), block_height=h)
        return "accepted"
    except Exception as e:
        return f"{type(e).__name__}: {e}"


v = verdict(H)
check("a v2 enrol against a pool that seats five validates", v == "accepted", v)
saved = {a: (kv_ops.get_account(a) or {}).get("bonded", 0) for a in VALS + [EDGE, EXACT]}
for a in VALS[4:] + [EDGE, EXACT]:
    kv_ops.account_set(a, "bonded", 0)                # four eligible left
reset_caches()
v = verdict(H)
check("a v2 enrol against four eligible challengers is REFUSED (k = 5)", "not enough independent challengers" in v, v)
check("...the same chain would still have seated the old k = 3", E.pool_can_seat(T._tpm_pool(H), 3))
P.TPM_POOL_V2_HEIGHT = 1 << 62
v_old = verdict(H)
P.TPM_POOL_V2_HEIGHT = GATE
check("below the gate the old rule decides (the same tx is accepted): replay keeps its verdict", v_old == "accepted", v_old)
for a, b in saved.items():
    kv_ops.account_set(a, "bonded", b)
reset_caches()

# === 5. BELOW THE GATE: byte-identical legacy records, the old draw ==================================================
P.TPM_POOL_V2_HEIGHT = 1 << 62
LPUB = aik_pub_area(b"old")
LEID = eid_of(LPUB)
apply(enrol_tx(LPUB), H)
old = kv_ops.tpm_enrol_get(LEID)
check("below the gate the record is the legacy 13-field row, byte for byte",
      len(raw_row(LEID)) == 13 and "k" not in old and "pool" not in old
      and kv_ops._read(lambda txn: txn.get(kv_ops._tpm_enrol_key(LEID), db=kv_ops._dbs()["devbind"]))
      == kv_ops._pack([old[f] for f in kv_ops._TPM_ENROL_FIELDS]))
od = T.tpm_drawn_challengers(old, opens)
check("below the gate the draw is the old one: _tpm_pool at the enrol block, k = 3",
      od == E.challenger_set_exact(E.draw_key(EK), T._tpm_pool(H), B.epoch_beacon(E.draw_epoch(H)), 3) and len(od) == 3)
check("a legacy record needs 3 challengers", E.record_k(old) == 3)
P.TPM_POOL_V2_HEIGHT = GATE
wipe()

# === 6. REGISTER: the record's own k ================================================================================
def register_reason(n):
    r = E.new_record(EK, EK_SPKI, E.aik_name_hex(PUB), PUB, OWNER, H, [addr("c", i) for i in range(n)],
                     pool=sorted(pool.items()), k=5)
    r["state"] = "proven"
    with kv_ops.write_txn():
        kv_ops.tpm_enrol_set(EID, r)
    tx = {"sender": OWNER, "max_block": H + 900,
          "device": {"id": EID, "ek": EK, "certinfo": "00" * 16, "sig": "00" * 16}}
    try:
        T.verify_register_device_ek(tx, "00" * 32)
        return "accepted"
    except Exception as e:
        return str(e)


check("a proven v2 record with five challengers passes the count check (fails later, on the dummy certify)",
      "wrong number of challengers" not in register_reason(5), register_reason(5))
check("a v2 record proved against three is refused", "wrong number of challengers" in register_reason(3))
wipe()

# === 7. THE DUTY INDEX AND /tpm_duty =================================================================================
apply(enrol_tx(PUB), H)
rec = kv_ops.tpm_enrol_get(EID)
drawn = sorted(T.tpm_drawn_challengers(rec, opens))
outsider = next(a for a in VALS if a not in drawn)
tip = opens + 4
idx = T.tpm_pending_duties(tip, kv_ops.tpm_enrols_live(tip=tip))
want_lo = tip + P.TX_INCLUSION_DELAY
want_hi = min(EXP - 1, tip + P.TX_LANDING_WINDOW - P.RESERVED_TX_MARGIN)
check("every drawn challenger owes a challenge on an open record, nobody else", set(idx) == set(drawn), sorted(idx))
d0 = idx[drawn[0]][0]
check("a duty is {id, action, ekpub, name, min_block, max_block, expires_at}",
      set(d0) == {"id", "action", "ekpub", "name", "min_block", "max_block", "expires_at"} and d0["action"] == "challenge"
      and d0["id"] == EID and d0["ekpub"] == rec["ekpub"] and d0["name"] == rec["name"] and d0["expires_at"] == EXP)
check("min_block / max_block are the node loop's (tip + TX_INCLUSION_DELAY; min(expiry - 1, tip + window - margin))",
      (d0["min_block"], d0["max_block"]) == (want_lo, want_hi) == T.tpm_duty_bounds(rec, tip), (d0, want_lo, want_hi))
check("no duty exists before the draw epoch (nobody is drawn yet)",
      T.tpm_pending_duties(opens - 1, kv_ops.tpm_enrols_live(tip=opens - 1)) == {})
late_tip = EXP - P.TX_INCLUSION_DELAY
check("a duty whose window cannot fit before expiry is omitted",
      T.tpm_pending_duties(late_tip, kv_ops.tpm_enrols_live(tip=late_tip)) == {})
for i, a in enumerate(drawn):
    apply({"recipient": "tpm_challenge", "sender": a, "data": {"id": EID, "blob": "11" * 40, "enc": "22" * 40}}, opens + i)
apply({"recipient": "tpm_commit", "sender": OWNER, "data": {"id": EID, "commit": "00" * 32}}, opens + 10)
with kv_ops.write_txn():                              # two reveals landed (the record keeps commit until all five)
    r = kv_ops.tpm_enrol_get(EID)
    r["reveals"] = sorted([a, "33", "44", opens + 11] for a in drawn[:2])
    kv_ops.tpm_enrol_set(EID, r)
idx = T.tpm_pending_duties(opens + 12, kv_ops.tpm_enrols_live(tip=opens + 12))
check("in commit, exactly the challengers without a reveal owe a reveal",
      set(idx) == set(drawn[2:]) and all(ds[0]["action"] == "reveal" for ds in idx.values()), idx)
_pub = {b[0]: b[1] for b in (kv_ops.tpm_enrol_get(EID).get("blobs") or [])}
check("a reveal duty carries the address's OWN published challenge (a second device reveals only if its secret matches)",
      all(ds[0].get("blob") == _pub.get(a) for a, ds in idx.items()), {a: ds[0].get("blob", "")[:12] for a, ds in idx.items()})


def load_handler():
    """The REAL /tpm_duty handler from nado.py (importing nado would start a node), run against a fake memserver."""
    src = open(os.path.join(ROOT, "nado.py")).read()
    tree = ast.parse(src)
    keep = [n for n in tree.body if (isinstance(n, ast.AsyncFunctionDef) and n.name == "tpm_duty")
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_tpm_duty_cache" for t in n.targets))]
    ns = {"memserver": types.SimpleNamespace(latest_block={"block_number": opens + 12}),
          "_resp": lambda out, status=200: (status, out), "_rate_limited": lambda req, n: False,
          "_RL": lambda: (429, {})}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "nado.py", "exec"), ns)   # noqa: S102 - our own source
    return ns


ns = load_handler()
req = lambda a: types.SimpleNamespace(query={"address": a})   # noqa: E731
st, body = asyncio.run(ns["tpm_duty"](req(drawn[3])))
check("GET /tpm_duty answers {tip, duties} for a drawn address",
      st == 200 and body["tip"] == opens + 12 and [d["action"] for d in body["duties"]] == ["reveal"], (st, body))
st, body = asyncio.run(ns["tpm_duty"](req(outsider)))
check("...an empty list for an address that owes nothing", st == 200 and body["duties"] == [], body)
st, body = asyncio.run(ns["tpm_duty"](req("bad/address")))
check("...and a 400 for a malformed address", st == 400)
nsrc = open(os.path.join(ROOT, "nado.py")).read()
check("the route is registered", 'web.get("/tpm_duty", tpm_duty)' in nsrc)
check("/tpm_enrolment states k and v2 for every record", 'out["k"], out["v2"] = _record_k(rec), _is_v2(rec)' in nsrc)
wipe()

# === 8. THE NODE'S OWN CHALLENGER LOOP answers a v2 record (k from the record) ======================================
from loops.core_loop import CoreClient as Core                            # noqa: E402
from ops.key_ops import generate_keys                                     # noqa: E402
apply(enrol_tx(PUB), H)
rec = kv_ops.tpm_enrol_get(EID)
drawn = sorted(T.tpm_drawn_challengers(rec, opens))
kd = generate_keys()
import ops.tpm_aik as _aik                                                # noqa: E402
_aik.make_credential = lambda ekpub, name, secret, seed=None: (b"\x11" * 40, b"\x22" * 40)   # the test EK is not RSA


class Mem:
    def __init__(self, tip, me):
        self.keydict, self.address = kd, me
        self.latest_block = {"block_number": tip}
        self.transaction_pool, self.submitted = [], []

    def merge_transaction(self, tx, user_origin=False):
        self.submitted.append(tx)
        self.transaction_pool.append(tx)
        return {"result": True}


def core_at(tip, me):
    core = types.SimpleNamespace(memserver=Mem(tip, me), logger=logging.getLogger("tpmpool2"))
    for m in ("maybe_tpm_challenge", "maybe_tpm_prune_secrets", "_tpm_tx_pending",
              "_tpm_secrets_path", "_tpm_secrets_load", "_tpm_secrets_save"):
        setattr(core, m, getattr(Core, m).__get__(core))
    return core


c = core_at(opens, drawn[4])
c.maybe_tpm_challenge()
sent = c.memserver.submitted
check("a node drawn as the FIFTH challenger of a v2 record answers it",
      [t["recipient"] for t in sent] == ["tpm_challenge"], sent)
lo_b, hi_b = T.tpm_duty_bounds(rec, opens)
check("...with the bounds /tpm_duty serves", bool(sent) and sent[0]["max_block"] == hi_b
      and sent[0].get("min_block") == lo_b, sent and (sent[0].get("min_block"), sent[0]["max_block"], lo_b, hi_b))
c = core_at(opens, next(a for a in VALS if a not in drawn))
c.maybe_tpm_challenge()
check("a pool member that was not drawn stays out", c.memserver.submitted == [])
view = T.tpm_challengers_view(rec, opens - 1)
check("the client view waits on five placeholders for a v2 record", len(view["challengers"]) == 5 and view["draw_pending"])
wipe()

# === 9. THE GATE ====================================================================================================
P.TPM_POOL_V2_HEIGHT = LIVE_GATE
src = open(os.path.join(ROOT, "protocol.py")).read()
check("the gate is keyed on the live generation, live from block 1 at the reroll",
      "TPM_POOL_V2_HEIGHT = 100000 if CHAIN_GENERATION == 28 else 1" in src and P.CHAIN_GENERATION == 28)
check("the v2 constants: k = 5, presence 50 epochs, one day out, one epoch of reveal grace",
      (P.DEVICE_ATTEST_EK_CHALLENGERS_V2, P.TPM_POOL_PRESENCE_MIN, P.TPM_MISS_EXCLUDE_BLOCKS, P.TPM_REVEAL_GRACE)
      == (5, 50, 14400, 60))

print("\nALL OK" if not FAILED else f"\n{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
