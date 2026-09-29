"""No free, repeatable transaction (protocol.py "NO FREE REPEATABLE TRANSACTIONS"; operator 2026-09-27: "make sure it is
not exploitable in the future (no fees empty address spam)"). Betanet-8 shipped the rules at block 24000; betanet-9 runs
them from block 1, and the gate (SPAM_HARDEN_HEIGHT) is deleted — so the test halves that pinned the betanet-8 behaviour
below it went with it. What stays below the rules is height 0, which mempool admission on a genesis tip and a tx's own
max_block can still reach: there nothing moved (the kept `>= 1`).

MEASURED ON BETANET-8 BEFORE THE RULES (audit + probes, doc/security-review-2026-09-27.md §"Free transactions"):
  * tpm_ready had no fee rule and no uniqueness key, was sendable from a never-funded address, wrote the sender's account
    row (and a junk "tpm_ready" row) through the transfer fall-through, and every sender joined the challenger pool;
  * msgkey was free forever from any account that existed, even at zero balance;
  * any tx could carry unlimited extra top-level keys (the txid hashes them all) — a free message of any size;
  * one chip could open several enrolments in one block; one 10-NADO bond could land settle rows in unlimited namespaces;
    xmsg was free; one device could hop to a fresh never-funded sender every block;
  * nothing bounded how many fee-exempt txs one sender held in the mempool.

Pins, on the real tables (throwaway HOME) with real signed transactions, at block 24000 (where betanet-8 measured them)
and, for the kept `>= 1`, at height 0:
  1. shape: an unknown top-level key is refused, a key another kind carries is refused, the size caps hold (a settle's
     proof is outside the cap, a tpm_enrol and a multisig get their own room), and at height 0 nothing changes;
  2. msgkey: the first bind is free and refuses a fee, a rotation must pay MIN_TX_FEE, re-binding the same key and
     carrying data are refused, and it needs an account; at height 0 a rotation is still free;
  3. tpm_ready: refused from an unbonded account, refused with a fee, accepted from a bonded one; one per sender per block
     (a max_block of 0 occupies no key); and apply writes NO account for its sender;
  4. tpm_enrol occupies one key per endorsement identity (a max_block of 0 occupies none);
  5. settle outside the default namespace must pay, a cursor more than SETTLE_MAX_LAG behind is refused;
  6. xmsg must pay;
  7. the device-hop rule refuses a second move to a different sender in the same epoch, keeps the first move instant,
     and never touches the bound sender's own renewals;
  8. the mempool holds at most FREE_POOL_PER_SENDER fee-exempt txs per sender, keeps the LOWEST txids whatever the
     arrival order, and never limits paid txs or other senders;
  9. the node's announcer stays quiet while unbonded, the wallet pays a rotation fee, and the empty-account bypass no
     longer lists tpm_ready.

Run: python3 tests/test_free_tx_spam_bounded.py
"""
import os, sys, tempfile, logging, random
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-freespam-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
from genesis import create_indexers
create_indexers()
import protocol as P
from ops import kv_ops, transaction_ops as T
from ops.account_ops import create_account, get_account, reflect_transaction
from hashing import canonical_bytes
from signatures import generate_keydict, sign, unhex

logger = logging.getLogger("freespam"); logger.addHandler(logging.NullHandler())
# a real height, the one betanet-8 shipped the rules at, so settle cursors and epochs derived from it stay positive
H = 24000
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def verdict(tx, h):
    """None when validate_transaction accepts, else its message."""
    try:
        T.validate_transaction(tx, logger, block_height=h)
        return None
    except Exception as e:
        return str(e) or type(e).__name__


def resign(kd, tx):
    tx = {k: v for k, v in tx.items() if k not in ("txid", "signature")}
    tx["txid"] = T.create_txid(tx)
    tx["signature"] = sign(private_key=kd["private_key"], message=unhex(tx["txid"]))
    return tx


def fund(kd, balance=0, bonded=0):
    create_account(kd["address"], balance=balance, bonded=bonded)
    kv_ops.account_set_field(kd["address"], "public_key", kd["public_key"])


KEM1, KEM2 = "aa" * 1184, "bb" * 1184
MB = H + 10                                   # a max_block >= 1, so keyed-on-max_block rules apply

# 1. shape ------------------------------------------------------------------------------------------------------------
kd = generate_keydict(); fund(kd, balance=10 ** 12)
base = T.construct_msgkey_tx(kd, KEM1, MB)
padded = resign(kd, dict(base, pad="00" * 2048))
check("an unknown top-level key is refused", "unknown transaction field" in (verdict(padded, H) or ""),
      verdict(padded, H))
check("...at block 1 too (the rule holds from block 1)", "unknown transaction field" in (verdict(padded, 1) or ""),
      verdict(padded, 1))
check("...and at height 0 (mempool admission on a genesis tip) the shape rule is off, as it always was",
      "unknown transaction field" not in (verdict(padded, 0) or ""), verdict(padded, 0))
T.tx_shape_check(base, H)                                                        # the honest body passes
wrong_kind = dict(base, recipient="tpm_ready")
try:
    T.tx_shape_check(wrong_kind, H); ok = False
except AssertionError as e:
    ok = "kem_pub" in str(e)
check("a field another kind carries (kem_pub on tpm_ready) is refused", ok)


def shape_refused(tx):
    try:
        T.tx_shape_check(tx, H)
        return False
    except AssertionError as e:
        return "over the" in str(e)


claim = {"sender": kd["address"], "recipient": "htlc_claim", "amount": 0, "fee": 0, "timestamp": 1, "nonce": 1,
         "max_block": MB, "chain_id": P.CHAIN_ID, "txid": "0" * 64, "signature": "00",
         "data": {"htlc_id": "ab", "preimage": "cd", "junk": "x" * (P.TX_MAX_BYTES + 1)}}
check("a fee-exempt message padded inside its data is refused by the size cap", shape_refused(claim))
claim["data"]["junk"] = "x" * 1000
check("...and the same message at honest size passes", not shape_refused(claim))
settle = dict(claim, recipient="settle", data={"exec_cursor": 5, "state_root": "0" * 64, "proof": "x" * (4 * P.TX_MAX_BYTES)})
check("a settle's proof is outside the cap (it is verified, and prices itself)", not shape_refused(settle))
settle["data"]["junk"] = "x" * (P.TX_MAX_BYTES + 1)
check("...but everything else in a settle is inside it", shape_refused(settle))
enrol = dict(claim, recipient="tpm_enrol", data={"ek": ["ab" * 40000], "pub": "cd" * 100})
check("a tpm_enrol has room for a full endorsement chain", not shape_refused(enrol))
enrol["data"]["ek"] = ["ab" * (P.TPM_ENROL_MAX_BYTES // 2 + 1)]
check("...and no more", shape_refused(enrol))
msig = dict(claim, recipient=kd["address"], data="", multisig={"m": 2}, signature=["ab" * 3000] * 16)
check("a 16-signature multisig spend fits (8 KiB per extra signature)", not shape_refused(msig))
big = dict(claim, recipient=kd["address"], data="x" * (P.TX_MAX_BYTES + 1))
check("a plain transfer cannot carry more than the cap either", shape_refused(big))

# 2. msgkey -----------------------------------------------------------------------------------------------------------
check("the first messaging key is free", verdict(base, H) is None, verdict(base, H))
paid_first = T.construct_msgkey_tx(kd, KEM1, MB, fee=P.MIN_TX_FEE)
check("...and refuses a fee (nothing to charge for)", "fee must be 0" in (verdict(paid_first, H) or ""), verdict(paid_first, H))
reflect_transaction(base, logger=logger, block_height=H)                         # bound
rot_free = T.construct_msgkey_tx(kd, KEM2, MB)
check("a free ROTATION is refused", "minimum fee" in (verdict(rot_free, H) or ""), verdict(rot_free, H))
check("...and at height 0 (a genesis tip's mempool) it is still free, as it always was", verdict(rot_free, 0) is None,
      verdict(rot_free, 0))
rot_paid = T.construct_msgkey_tx(kd, KEM2, MB, fee=P.MIN_TX_FEE)
check("a rotation that pays MIN_TX_FEE is accepted", verdict(rot_paid, H) is None, verdict(rot_paid, H))
same = T.construct_msgkey_tx(kd, KEM1, MB, fee=P.MIN_TX_FEE)
check("re-binding the key already bound is refused, even paid", "already bound" in (verdict(same, H) or ""), verdict(same, H))
with_data = resign(kd, dict(T.construct_msgkey_tx(kd, KEM2, MB, fee=P.MIN_TX_FEE), data="hi"))
check("a msgkey carries no data", "no data" in (verdict(with_data, H) or ""), verdict(with_data, H))
bal0 = get_account(kd["address"])["balance"]
reflect_transaction(rot_paid, logger=logger, block_height=H)
check("the rotation fee is burned from the sender", get_account(kd["address"])["balance"] == bal0 - P.MIN_TX_FEE)
reflect_transaction(rot_paid, logger=logger, block_height=H, revert=True)
check("...and a rollback restores balance and key exactly",
      get_account(kd["address"])["balance"] == bal0 and get_account(kd["address"])["kem_pub"] == KEM1)
ghost = generate_keydict()
nokey = T.construct_msgkey_tx(ghost, KEM1, MB)
check("a msgkey needs an account on chain (consensus, not just mempool policy)",
      "needs an account" in (verdict(nokey, H) or ""), verdict(nokey, H))

# 3. tpm_ready --------------------------------------------------------------------------------------------------------
poor = generate_keydict(); fund(poor, balance=5 * 10 ** 10)
rich = generate_keydict(); fund(rich, balance=10 ** 11, bonded=P.B_MIN)
r_poor = T.construct_tpm_tx(poor, "tpm_ready", "", MB)
r_rich = T.construct_tpm_tx(rich, "tpm_ready", "", MB)
check("tpm_ready from an unbonded account is refused", "bonded" in (verdict(r_poor, H) or ""), verdict(r_poor, H))
check("...at block 1 too", "bonded" in (verdict(r_poor, 1) or ""), verdict(r_poor, 1))
check("tpm_ready from a bonded validator is accepted", verdict(r_rich, H) is None, verdict(r_rich, H))
r_fee = resign(rich, dict(r_rich, fee=P.MIN_TX_FEE))
check("tpm_ready with a fee is refused (a fee bought nothing, it only moved the flood)",
      "fee must be 0" in (verdict(r_fee, H) or ""), verdict(r_fee, H))
r_rich2 = T.construct_tpm_tx(rich, "tpm_ready", "", MB)
k1, k2 = T.reserved_uniqueness_key(r_rich), T.reserved_uniqueness_key(r_rich2)
check("two announcements from one sender share a uniqueness key (one per block)", k1 == k2 and k1 is not None, (k1, k2))
old = T.construct_tpm_tx(rich, "tpm_ready", "", 0)
check("...and one whose own max_block is 0 has none (the kept `>= 1`)", T.reserved_uniqueness_key(old) is None)
never = generate_keydict()
free_ready = T.construct_tpm_tx(never, "tpm_ready", "", MB)
for _h in (1, H):
    reflect_transaction(free_ready, logger=logger, block_height=_h)
check("a tpm_ready writes NO account for its sender (at block 1 as at any height)",
      get_account(never["address"], create_on_error=False) is None
      and get_account("tpm_ready", create_on_error=False) is None)

# 4. tpm_enrol --------------------------------------------------------------------------------------------------------
e1 = T.construct_tpm_tx(poor, "tpm_enrol", {"ek": ["30820102"], "pub": "00"}, MB)
e2 = T.construct_tpm_tx(rich, "tpm_enrol", {"ek": ["30820102"], "pub": "01"}, MB)
k1, k2 = T.reserved_uniqueness_key(e1), T.reserved_uniqueness_key(e2)
check("every tpm_enrol occupies a ('tpm_enrol', ...) key", k1[0] == "tpm_enrol" and k2[0] == "tpm_enrol", (k1, k2))
from unittest import mock
with mock.patch("ops.attest_native.ek_public_der", lambda der: b"same-chip-spki"):
    k1, k2 = T.reserved_uniqueness_key(e1), T.reserved_uniqueness_key(e2)
check("two enrolments of one chip (one SubjectPublicKeyInfo) share the key, whoever sends them", k1 == k2, (k1, k2))
with mock.patch("ops.attest_native.ek_public_der", lambda der: der):
    e3 = T.construct_tpm_tx(rich, "tpm_enrol", {"ek": ["30820103"], "pub": "01"}, MB)
    check("...and two chips do not", T.reserved_uniqueness_key(e1) != T.reserved_uniqueness_key(e3))
old_e = T.construct_tpm_tx(poor, "tpm_enrol", {"ek": ["30820102"], "pub": "00"}, 0)
check("an enrolment whose own max_block is 0 has no key (the kept `>= 1`)", T.reserved_uniqueness_key(old_e) is None)

# 5. settle -----------------------------------------------------------------------------------------------------------
def settle_tx(kd, cursor, ns=None, fee=0):
    data = {"exec_cursor": cursor, "state_root": "ab" * 32}
    if ns:
        data["ns"] = ns
    tx = {"sender": kd["address"], "recipient": "settle", "amount": 0, "timestamp": 1, "data": data, "nonce": 7,
          "max_block": MB, "chain_id": P.CHAIN_ID, "fee": fee, "public_key": kd["public_key"]}
    return resign(kd, tx)


s_ns = settle_tx(rich, H - 100, ns="spamspace")
check("a free settle outside the default namespace is refused", "minimum fee" in (verdict(s_ns, H) or ""), verdict(s_ns, H))
check("...at height 0 (a genesis tip's mempool) the fee rule is off, as it always was",
      "minimum fee" not in (verdict(s_ns, 0) or ""), verdict(s_ns, 0))
s_ns_paid = settle_tx(rich, H - 100, ns="spamspace", fee=P.MIN_TX_FEE)
check("...and a paid one passes the fee rule", "fee" not in (verdict(s_ns_paid, H) or ""), verdict(s_ns_paid, H))
s_old = settle_tx(rich, H - P.SETTLE_MAX_LAG - 1)
check(f"a settle more than SETTLE_MAX_LAG ({P.SETTLE_MAX_LAG}) behind its block is refused",
      "blocks behind" in (verdict(s_old, H) or ""), verdict(s_old, H))
s_ok = settle_tx(rich, H - 380)                                   # the largest honest lag measured on betanet-8
check("an honest settle (380 behind, default namespace, free) is untouched by the new rules",
      not any(w in (verdict(s_ok, H) or "") for w in ("blocks behind", "minimum fee", "unknown transaction", "over the")),
      verdict(s_ok, H))

# 6. xmsg -------------------------------------------------------------------------------------------------------------
xm = resign(rich, {"sender": rich["address"], "recipient": "xmsg", "amount": 0, "timestamp": 1, "nonce": 8,
                   "data": {"to_ns": "b", "message": {"seq": 1}, "proof": {}}, "max_block": MB,
                   "chain_id": P.CHAIN_ID, "fee": 0, "public_key": rich["public_key"]})
check("a free xmsg is refused", "minimum fee" in (verdict(xm, H) or ""), verdict(xm, H))

# 7. device hop -------------------------------------------------------------------------------------------------------
A, B, C = generate_keydict(), generate_keydict(), generate_keydict()
DKEY = "tpm:" + "d" * 64
epoch = H // P.EPOCH_LENGTH


def reg(kd, h):
    tx = {"sender": kd["address"], "recipient": "register", "amount": 0, "timestamp": 1, "data": "", "nonce": 9,
          "max_block": h, "chain_id": P.CHAIN_ID, "fee": 0, "public_key": kd["public_key"], "device": {"att": "x"}}
    return resign(kd, tx)


with mock.patch.object(T, "verify_register_device", lambda tx, anchor: None), \
        mock.patch("ops.device_attest.device_binding_key", lambda *a, **k: DKEY), \
        mock.patch("ops.block_ops.get_block_hash_by_number", lambda n: "ab" * 32):
    if True:
        kv_ops.devbind_set(DKEY, A["address"], epoch, "lease")
        v = verdict(reg(B, H), H)
        check("a device that moved to another account THIS epoch cannot move again to a different sender",
              "moved to another account this epoch" in (v or ""), v)
        v = verdict(reg(A, H), H)
        check("...its bound sender's own renewal is untouched", "moved to another account" not in (v or ""), v)
        kv_ops.devbind_set(DKEY, A["address"], epoch - 1, "lease")
        v = verdict(reg(C, H), H)
        check("...and a move from a binding made in an earlier epoch is instant", "moved to another account" not in (v or ""), v)

# 8. mempool cap ------------------------------------------------------------------------------------------------------
from memserver import MemServer


class Pool:
    _free_pool_admit = MemServer._free_pool_admit

    def __init__(self):
        self._transaction_pool = []

    def offer(self, tx):
        ok, victim = self._free_pool_admit(tx)
        if ok:
            if victim is not None:
                self._transaction_pool.remove(victim)
            self._transaction_pool.append(tx)
        return ok


def ftx(sender, i, fee=0):
    return {"sender": sender, "fee": fee, "txid": "%064x" % i}


N = P.FREE_POOL_PER_SENDER
txs = [ftx("S", i) for i in range(N * 3)]
orders = []
for seed in (1, 2, 3):
    p = Pool(); random.Random(seed).shuffle(txs)
    for t in list(txs):
        p.offer(t)
    orders.append(sorted(t["txid"] for t in p._transaction_pool))
check(f"a sender holds at most {N} fee-exempt txs in the pool", all(len(o) == N for o in orders), [len(o) for o in orders])
check("...and every arrival order converges on the same LOWEST txids (pools must not diverge)",
      orders[0] == orders[1] == orders[2] == ["%064x" % i for i in range(N)])
p = Pool()
for i in range(N):
    p.offer(ftx("S", 100 + i))
check("over the cap a higher txid is refused", not p.offer(ftx("S", 999)))
check("...a lower one replaces the highest", p.offer(ftx("S", 1)) and "%064x" % (100 + N - 1) not in
      {t["txid"] for t in p._transaction_pool})
check("paid txs are never limited", all(p.offer(ftx("S", 5000 + i, fee=P.MIN_TX_FEE)) for i in range(N)))
check("another sender is unaffected", p.offer(ftx("R", 3)))

# 9. the clients ------------------------------------------------------------------------------------------------------
core = open(os.path.join(ROOT, "loops", "core_loop.py")).read()
ann = core[core.index("def maybe_tpm_ready"):core.index("def maybe_tpm_challenge")]
check("the node's announcer stays quiet while its account is not bonded", "B_MIN" in ann and "_my_acct" in ann)
mem = open(os.path.join(ROOT, "memserver.py")).read()
byp = mem[mem.index('elif transaction.get("recipient") not in ("register", "heartbeat", "tpm_enrol"'):][:200]
check("tpm_ready is no longer in the empty-account bypass", "tpm_ready" not in byp, byp)
js = open(os.path.join(ROOT, "static", "interface.js")).read()
check("the wallet pays MIN_TX_FEE to rotate a bound messaging key (and falls back on a pre-gate chain)",
      "acc.kem_pub ? MIN_TX_FEE : 0" in js and "fee must be 0" in js)

check("the gate is gone: the rules hold from block 1", not hasattr(P, "SPAM_HARDEN_HEIGHT"))

kv_ops.close_all()
print("ALL PASS — no free repeatable transaction" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
