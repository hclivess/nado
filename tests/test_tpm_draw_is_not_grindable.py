"""The TPM enrolment's challengers cannot be aimed by the client that opens it (ops/tpm_enrol "COMMIT, THEN DRAW").

THE HOLE (audit 2026-09-27, CRIT). The k challengers were drawn at the tpm_enrol from epoch_beacon(epoch of the
enrol), keyed on the enrolment id — and the id hashes the attestation key's public area, whose authPolicy bytes the
client writes freely. That beacon is fixed before the epoch starts, so a client computes the draw offline and tries
public areas until every seat lands on pool members it runs; with every seat colluding the chip proof is forged. This
file reproduced that grind on betanet-8 (below block 28500); betanet-9 draws every enrolment commit-then-draw from
block 1, so the gate (TPM_DRAW_UNGRINDABLE_HEIGHT) and the enrol-time draw are deleted, and the reproduction and the
legacy-record checks went with them. Pinned here (COMMIT, THEN DRAW):

  - the draw ignores every field the client writes: two attestation keys of one chip, two owners, two enrolment ids,
    any block of the same epoch — one draw;
  - its dice are the beacon of a LATER epoch, whose anchor block is strictly after the enrol (unknown at commit), and
    the enrol's own epoch beacon — the one the client could see — has no influence at all;
  - the pool is frozen at the enrol block, so joining it after the dice are known changes nothing;
  - exact sampling seats k whenever the pool has k weighted members (checked at the enrol, never short later);
  - a retry after expiry is drawn from fresh dice (AN EXPIRED ATTEMPT MUST BE RETRYABLE);
  - the apply path writes an undrawn record, refuses a challenge before the draw epoch and a commit to nothing,
    materialises the set on the first challenge, rolls back byte-exactly, and an honest enrolment still completes;
  - the challenger loop answers a delayed enrolment it was drawn for, and only once the draw exists;
  - /tpm_enrolment never serves an empty set to the shipped helper.

Run: python3 tests/test_tpm_draw_is_not_grindable.py          (system python3: needs `cryptography`)
"""
import hashlib
import logging
import os
import struct
import sys
import tempfile
import types

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-tpmdraw-")        # never touch the live database (assign, not setdefault)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers", "private"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

import protocol as P                                                   # noqa: E402
import ops.block_ops as B                                              # noqa: E402
import ops.transaction_ops as T                                        # noqa: E402
from ops import tpm_enrol as E, tpm_aik                                # noqa: E402

FAILED = []
K = P.DEVICE_ATTEST_EK_CHALLENGERS
L = P.EPOCH_LENGTH


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


def refused(fn):
    """True when fn raises AssertionError — a clean rejection, never another exception type."""
    try:
        fn()
    except AssertionError:
        return True
    return False


# --- a synthetic chain --------------------------------------------------------------------------------------------
BEACONS = {}                                        # epoch -> beacon; a test can overwrite one to see what it moves


def beacon(epoch):
    return BEACONS.get(epoch, "%064x" % ((epoch * 2654435761 + 7) % (1 << 256)))


B.epoch_beacon = beacon

from signatures import generate_keydict, sign, unhex                     # noqa: E402
KEYS = {}
for _ in range(10):
    _kd = generate_keydict()
    KEYS[_kd["address"]] = _kd
HONEST = list(KEYS)[:7]                               # seven honest challengers
EVIL = list(KEYS)[7:]                                 # three the attacker runs (bonded, announced, landing duties)
BLOCKS = {}


def build(until, members, late=()):
    """Every member announces and lands a duty every 5th block; `late` = (height, address) joins after the fact."""
    for h in range(1, until + 1):
        txs = []
        if h % 5 == 0:
            for a in members:
                txs += [{"recipient": "tpm_ready", "sender": a}, {"recipient": "duty", "sender": a}]
        for lh, a in late:
            if h >= lh and h % 5 == 0:
                txs += [{"recipient": "tpm_ready", "sender": a}] + [{"recipient": "duty", "sender": a}] * 50
        BLOCKS[h] = {"block_transactions": txs}
    T.get_block_number = lambda n: BLOCKS.get(int(n))
    T._tpm_proven_cache[0] = None
    T._tpm_producer_cache[0] = None


def aik_pub_area(policy: bytes = b""):
    """A restricted RSA-2048 signing key's TPMT_PUBLIC — authPolicy is the client's free choice of bytes."""
    b = struct.pack(">HHI", 0x0001, 0x000B, 0x00050472) + struct.pack(">H", len(policy)) + policy
    b += struct.pack(">H", 0x0010) + struct.pack(">HH", 0x0014, 0x000B) + struct.pack(">H", 2048) + struct.pack(">I", 0)
    return b + b"\x00\x00"


def software_ek():
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.primitives import hashes, serialization
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    spki = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    decrypt = lambda ct: key.decrypt(ct, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(),
                                                      label=b"IDENTITY\x00"))
    return spki, decrypt


BASE = 3000                                          # a real height with a full synthetic history below it
build(BASE + 1200, HONEST + EVIL)
ek_spki, decrypt = software_ek()
EK_ID = hashlib.sha256(ek_spki).hexdigest()

# === 2. NO CLIENT-CHOSEN FIELD REACHES THE DRAW =======================================================================
H1 = BASE + 7 * L + 13                               # an enrol, epoch E1
E1 = H1 // L
check("the enrol-time draw and its gate are deleted: every enrolment is drawn commit-then-draw",
      not hasattr(E, "draw_is_delayed") and not hasattr(E, "challenger_set") and not hasattr(T, "_tpm_challengers")
      and not hasattr(P, "TPM_DRAW_UNGRINDABLE_HEIGHT"))
check("an enrol at block 1 is drawn two epochs on, like any other", E.draw_opens(1) == 2 * L)
check("its dice are anchored strictly after every block of its epoch",
      all((E.draw_epoch(h) - 1) * L > h for h in range(E1 * L, E1 * L + L)))
opens = E.draw_opens(H1)


def rec_for(pub, owner="o" * 46, h=H1):
    return E.new_record(EK_ID, ek_spki, E.aik_name_hex(pub), pub, owner, h, [])


draws = set()
for n in range(300):
    pub = aik_pub_area(n.to_bytes(4, "big"))
    owner = f"{n:046x}"
    h = E1 * L + (n % L)                             # any block of the same epoch
    draws.add(tuple(T.tpm_drawn_challengers(rec_for(pub, owner, h), opens)))
check("300 public areas, owners and blocks of one epoch give ONE draw", len(draws) == 1, len(draws))
check("two attestation keys of the same chip get the same challengers",
      T.tpm_drawn_challengers(rec_for(aik_pub_area(b"a")), opens)
      == T.tpm_drawn_challengers(rec_for(aik_pub_area(b"b")), opens))
the_draw = list(next(iter(draws)))
check("a full set of distinct challengers is drawn", len(set(the_draw)) == K, the_draw)

# the beacon the client could SEE (its own epoch's) moves nothing; the draw epoch's beacon is what decides
before = T.tpm_drawn_challengers(rec_for(aik_pub_area()), opens)
BEACONS[E1] = "ab" * 32
BEACONS[E1 + 1] = "cd" * 32
check("the enrol epoch's (known) beacon has no influence on the draw",
      T.tpm_drawn_challengers(rec_for(aik_pub_area()), opens) == before)
moved = set()
for i in range(40):
    BEACONS[E.draw_epoch(H1)] = "%064x" % (i * 7919 + 1)
    moved.add(tuple(T.tpm_drawn_challengers(rec_for(aik_pub_area()), opens)))
BEACONS.clear()
check("the draw is decided by the beacon of the draw epoch", len(moved) > 5, len(moved))

# before the draw epoch there is nothing to aim at, and nothing can be answered
check("no set exists before the draw epoch", T.tpm_drawn_challengers(rec_for(aik_pub_area()), opens - 1) is None)
check("a challenge before the draw epoch is refused",
      refused(lambda: T.tpm_materialise_draw(rec_for(aik_pub_area()), opens - 1)))

# the pool is frozen at the enrol: an attacker who sees the dice and then piles into the pool changes nothing
LATE = "ee" * 23
build(BASE + 1200, HONEST + EVIL, late=((H1 + 1, LATE),))
check("joining the pool after the enrol does not move the draw",
      T.tpm_drawn_challengers(rec_for(aik_pub_area()), opens) == before)
build(BASE + 1200, HONEST + EVIL)

# === 3. LIVENESS: a pool that can seat k always does; a retry gets fresh dice =====================================
check("exact sampling seats k from a heavily concentrated pool",
      all(len(E.challenger_set_exact(f"ek:{i}", {"a": 10 ** 6, "b": 1, "c": 1}, "%064x" % i, 3)) == 3 for i in range(200)))
check("exact sampling never seats one challenger twice",
      all(len(set(E.challenger_set_exact(f"ek:{i}", {"a": 5, "b": 1, "c": 1, "d": 9}, "%064x" % i, 3))) == 3
          for i in range(200)))
check("a pool of fewer than k weighted members is refused at the enrol",
      not E.pool_can_seat({"a": 5, "b": 0, "c": 1}, 3) and E.pool_can_seat({"a": 5, "b": 1, "c": 1}, 3))
check("a shape error in the weights is a rejection, not a TypeError",
      refused(lambda: E.challenger_set_exact("ek:x", {"a": 1.5, "b": 1, "c": 1}, "00" * 32, 3)))
check("a delayed record keeps the full working window after its draw opens",
      H1 + E.enrol_window(H1) == opens + P.DEVICE_ATTEST_EK_ENROL_SHORT)
check("a record opened at block 1 keeps the full working window too",
      1 + E.enrol_window(1) == E.draw_opens(1) + P.DEVICE_ATTEST_EK_ENROL_SHORT)
check("a retry after expiry is drawn from a later draw epoch (fresh dice)",
      all(E.draw_epoch(h + E.enrol_window(h)) > E.draw_epoch(h) for h in list(range(1, 1 + 3 * L)) + list(range(BASE, BASE + 3 * L))))
_reads = [0]
_get = T.get_block_number
T.get_block_number = lambda n: (_reads.__setitem__(0, _reads[0] + 1), _get(n))[1]
T._proven_challengers(H1)
T._proven_challengers(H1 + 3 * L)                     # the tip's window moved on while the enrolment waits
_reads[0] = 0
T._proven_challengers(H1)
T._proven_challengers(H1 + 3 * L)
T.get_block_number = _get
check("the pool of a waiting enrolment and the tip's pool are both cached (no rescan per block)", _reads[0] == 0, _reads[0])
check("the determinism of the draw: the same inputs give the same set twice",
      T.tpm_drawn_challengers(rec_for(aik_pub_area()), opens) == T.tpm_drawn_challengers(rec_for(aik_pub_area()), opens + 50))


# === 4. THE APPLY PATH, AGAINST A REAL STATE DB =====================================================================
def consensus_path():
    from ops import kv_ops, attest_native
    from ops.account_ops import apply_tpm_enrol_tx
    import ops.account_ops as A
    kv_ops.init_env()
    pub = aik_pub_area(b"honest")
    name_hex = E.aik_name_hex(pub)
    attest_native.verify_ek = lambda chain, now, height=None: {"ok": True, "identity": EK_ID}
    attest_native.ek_public_der = lambda der: ek_spki
    A._tpm_anchor_time = lambda h: 0
    eid = E.enrol_id(P.CHAIN_ID, EK_ID, name_hex)
    enrol_tx = {"recipient": "tpm_enrol", "sender": "o" * 46, "data": {"ek": ["30"], "pub": pub.hex()}}

    def apply(tx, h, revert=False):
        with kv_ops.write_txn():
            apply_tpm_enrol_tx(tx, h, revert=revert)

    # written undrawn
    apply(enrol_tx, H1)
    undrawn = kv_ops.tpm_enrol_get(eid)
    check("the enrol writes NO challengers (the dice do not exist yet)", undrawn["challengers"] == [])
    check("a commitment to nothing is refused cleanly (AssertionError, not max() of nothing)",
          refused(lambda: E.apply_commit(undrawn, "o" * 46, "00" * 32, opens + 1)))
    drawn = T.tpm_drawn_challengers(undrawn, opens)
    outsider = next(a for a in HONEST + EVIL if a not in drawn)
    secrets = {}

    def challenge(who, h):
        s_, r_ = os.urandom(32), os.urandom(32)
        blob, enc = tpm_aik.make_credential(ek_spki, bytes.fromhex(name_hex), s_, seed=r_)
        secrets[who] = (s_, r_, blob, enc)
        return {"recipient": "tpm_challenge", "sender": who,
                "data": {"id": eid, "blob": blob.hex(), "enc": enc.hex()}}

    check("a drawn challenger cannot answer before the draw epoch", refused(lambda: apply(challenge(drawn[0], opens - 1), opens - 1)))
    check("the record is untouched by the refused challenge", kv_ops.tpm_enrol_get(eid) == undrawn)
    check("an undrawn pool member cannot answer", refused(lambda: apply(challenge(outsider, opens), opens)))
    first = challenge(drawn[0], opens)
    apply(first, opens)
    rec = kv_ops.tpm_enrol_get(eid)
    check("the first challenge materialises the drawn set into the record",
          rec["challengers"] == sorted(drawn) and len(rec["blobs"]) == 1, rec["challengers"])
    apply(first, opens, revert=True)
    check("rolling back the materialising challenge restores the undrawn record exactly", kv_ops.tpm_enrol_get(eid) == undrawn)
    apply(first, opens)
    for i, who in enumerate(drawn[1:]):
        apply(challenge(who, opens + 1 + i), opens + 1 + i)
    # the chip opens every challenge, commits, the challengers reveal — the honest enrolment completes
    joined = b"".join(tpm_aik.activate_credential(decrypt, secrets[c][2], secrets[c][3], bytes.fromhex(name_hex))
                      for c in sorted(drawn))
    hc = opens + 10
    apply({"recipient": "tpm_commit", "sender": "o" * 46,
           "data": {"id": eid, "commit": tpm_aik.credential_commitment(joined)}}, hc)
    for i, c in enumerate(sorted(drawn)):
        apply({"recipient": "tpm_reveal", "sender": c,
               "data": {"id": eid, "secret": secrets[c][0].hex(), "seed": secrets[c][1].hex()}}, hc + 1 + i)
    done = kv_ops.tpm_enrol_get(eid)
    check("an honest enrolment under the delayed draw completes (proven)", done["state"] == "proven", done["state"])
    check("...within its window", done["hp"] < H1 + E.enrol_window(H1))
    return kv_ops, eid


kv_ops, EID = consensus_path()


# === 4b. VALIDATION (validate_transaction, signed transactions) =====================================================
def validation_path():
    import logging as _lg
    from ops import attest_native
    T._anchor_time = lambda tx, h: 1_790_000_000
    root = sorted(P.DEVICE_ATTEST_EK_ROOTS)[0]
    attest_native.verify_ek = lambda chain, now, roots=None, height=None: {
        "ok": True, "root_sha256": root, "identity": EK_ID, "ek_identity": EK_ID}
    opener = generate_keydict()

    def signed(kd, recipient, data, h):
        tx = {"sender": kd["address"], "recipient": recipient, "amount": 0, "fee": 0, "timestamp": 1, "data": data,
              "nonce": f"n{h}{recipient}", "public_key": kd["public_key"], "max_block": h, "chain_id": P.CHAIN_ID}
        tx["txid"] = T.create_txid(tx)
        tx["signature"] = sign(private_key=kd["private_key"], message=unhex(tx["txid"]))
        return tx

    def verdict(tx, h):
        try:
            T.validate_transaction(tx, _lg.getLogger("t"), block_height=h)
            return "accepted"
        except Exception as e:
            return f"{type(e).__name__}: {e}"

    pub = aik_pub_area(b"validate")
    eid = E.enrol_id(P.CHAIN_ID, EK_ID, E.aik_name_hex(pub))
    kv_ops.tpm_enrol_del(eid)
    kv_ops.tpm_enrol_open_set(EK_ID, None)
    enrol = {"ek": ["30" * 40], "pub": pub.hex()}
    v = verdict(signed(opener, "tpm_enrol", enrol, H1), H1)
    check("a tpm_enrol against a pool of >= k validates (no draw at the enrol)", v == "accepted", v)
    build(BASE + 1200, HONEST[:2])                    # a pool that cannot seat k
    v = verdict(signed(opener, "tpm_enrol", enrol, H1), H1)
    check("a tpm_enrol against a pool of < k is refused up front",
          "not enough independent challengers" in v, v)
    build(BASE + 1200, HONEST + EVIL)

    rec = rec_for(pub, owner=opener["address"], h=H1)
    with kv_ops.write_txn():
        kv_ops.tpm_enrol_set(eid, rec)
    drawn = T.tpm_drawn_challengers(rec, opens)
    outsider = next(a for a in HONEST + EVIL if a not in drawn)
    s_, r_ = os.urandom(32), os.urandom(32)
    blob, enc = tpm_aik.make_credential(ek_spki, bytes.fromhex(E.aik_name_hex(pub)), s_, seed=r_)
    ch = {"id": eid, "blob": blob.hex(), "enc": enc.hex()}
    v = verdict(signed(KEYS[drawn[0]], "tpm_challenge", ch, opens - 1), opens - 1)
    check("validation refuses a drawn challenger's answer before the draw epoch", "are drawn at block" in v, v)
    v = verdict(signed(KEYS[drawn[0]], "tpm_challenge", ch, opens), opens)
    check("validation accepts a drawn challenger's answer from the draw epoch", v == "accepted", v)
    v = verdict(signed(KEYS[outsider], "tpm_challenge", ch, opens), opens)
    check("validation refuses an undrawn pool member", "not a drawn challenger" in v, v)
    v = verdict(signed(opener, "tpm_commit", {"id": eid, "commit": "00" * 32}, opens), opens)
    check("validation refuses a commitment before anyone was drawn", "have not been drawn yet" in v, v)
    with kv_ops.write_txn():
        kv_ops.tpm_enrol_del(eid)


validation_path()


# === 5. THE CHALLENGER LOOP AND THE CLIENT'S VIEW ===================================================================
def loop_and_view():
    import loops.core_loop as core_loop
    from loops.core_loop import CoreClient as Core
    from ops.key_ops import generate_keys
    kv_ops.tpm_enrol_del(EID)
    pub = aik_pub_area(b"loop")
    rec = rec_for(pub, h=H1)
    eid = E.enrol_id(P.CHAIN_ID, EK_ID, E.aik_name_hex(pub))
    kv_ops.tpm_enrol_set(eid, rec)
    drawn = T.tpm_drawn_challengers(rec, opens)
    kd = generate_keys()

    class Mem:
        def __init__(self, tip):
            self.keydict, self.address = kd, drawn[0]
            self.latest_block = {"block_number": tip}
            self.transaction_pool, self.submitted = [], []

        def merge_transaction(self, tx, user_origin=False):
            self.submitted.append(tx)
            self.transaction_pool.append(tx)
            return {"result": True}

    def core_at(tip, me=None):
        mem = Mem(tip)
        if me:
            mem.address = me
        core = types.SimpleNamespace(memserver=mem, logger=logging.getLogger("tpmdraw"))
        for m in ("maybe_tpm_challenge", "maybe_tpm_prune_secrets", "_tpm_tx_pending",
                  "_tpm_secrets_path", "_tpm_secrets_load", "_tpm_secrets_save"):
            setattr(core, m, getattr(Core, m).__get__(core))
        return core

    c = core_at(opens - 1)
    c.maybe_tpm_challenge()
    check("the challenger loop waits while the draw does not exist yet", c.memserver.submitted == [])
    c = core_at(opens)
    c.maybe_tpm_challenge()
    check("a drawn challenger answers a delayed enrolment once its draw epoch has come",
          [t["recipient"] for t in c.memserver.submitted] == ["tpm_challenge"])
    outsider = next(a for a in HONEST + EVIL if a not in drawn)
    c = core_at(opens, me=outsider)
    c.maybe_tpm_challenge()
    check("a pool member that was not drawn stays out", c.memserver.submitted == [])

    pending = T.tpm_challengers_view(rec, opens - 1)
    check("the client view never serves an empty set: k placeholders while the draw is pending",
          len(pending["challengers"]) == K and pending["draw_pending"] and pending["draw_at"] == opens, pending)
    ready = T.tpm_challengers_view(rec, opens)
    check("the client view serves the set the chain will enforce once it exists",
          ready["challengers"] == sorted(drawn) and not ready["draw_pending"], ready)
    check("a record with a written set is served as stored", T.tpm_challengers_view(dict(rec, challengers=sorted(drawn)), opens) == {})


loop_and_view()

print("\nALL OK" if not FAILED else f"\n{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
