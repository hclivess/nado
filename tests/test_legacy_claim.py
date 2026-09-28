"""An old address whose key no chain ever saw is claimed by that key (protocol.LEGACY_CLAIM_HEIGHT; operator 2026-09-28:
"sign with your old key and get the coins").

WHY. Format 2 hashes the whole key, so the gen-28 carry moves every account whose key some chain recorded; the ~332
accounts (142 NADO, measured 2026-09-28) whose key no chain ever saw stay at their OLD 46-character address, which format 2
refuses as a sender. Their owners' wallets claim them with the key they already hold.

Pins, on real tables (throwaway HOME) with real signed transactions, address format 2 in force:
  1. the owner's key claims its old address from its new one and the whole balance moves; a rollback moves it back
     exactly; a second claim is refused (nothing left);
  2. refused: another key's old address, an amount other than the whole balance, an old address that has a key on chain
     (it was re-keyed, never claimable), a bonded old address, extra data, a fee, a claim naming its own sender;
  3. one claim per old address per block (uniqueness key); below the gate nothing is claimable;
  4. ACCEPTED RISK, pinned so nobody mistakes it for a bug: a key built to share the old address's 21 bytes can claim
     too (the operator's decision; the exposure those accounts already carried);
  5. the wallet claims by itself: on format 2, from the base key only, with the exact balance, and says so in 16 languages.

Run: python3 tests/test_legacy_claim.py
"""
import os, sys, tempfile, logging
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-legacyclaim-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
from genesis import create_indexers
create_indexers()
import protocol as P
from ops import kv_ops, transaction_ops as T, address_ops as A
from ops.account_ops import create_account, get_account, reflect_transaction
from signatures import generate_keydict, sign, unhex

logger = logging.getLogger("legacy"); logger.addHandler(logging.NullHandler())
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


# format 2 and the gate in force (their values on the next chain)
P.ADDRESS_FORMAT, P.ADDRESS_CHECKSUM, P.ADDRESS_LENGTH = 2, 4, len(P.ADDRESS_PREFIX) + P.ADDRESS_BODY + 8
LIVE_GATE = P.LEGACY_CLAIM_HEIGHT
P.LEGACY_CLAIM_HEIGHT = 1
H = 1000


def owner():
    kd = generate_keydict()
    kd["address"] = A.make_address(kd["public_key"])          # its format-2 address
    return kd


def claim(kd, legacy, amount, fee=0, data=None, max_block=H + 5):
    tx = {"sender": kd["address"], "recipient": "legacy_claim", "amount": 0, "timestamp": 1,
          "data": data if data is not None else {"legacy": legacy, "amount": amount}, "nonce": 7,
          "max_block": max_block, "chain_id": P.CHAIN_ID, "fee": fee, "public_key": kd["public_key"]}
    tx["txid"] = T.create_txid(tx)
    tx["signature"] = sign(private_key=kd["private_key"], message=unhex(tx["txid"]))
    return tx


def verdict(tx, h=H):
    try:
        T.validate_transaction(tx, logger, block_height=h)
        return None
    except Exception as e:
        return str(e) or type(e).__name__


BAL = 4_249_825_619
kd = owner()
legacy = A.legacy_address(kd["public_key"])
create_account(legacy, balance=BAL)                            # carried at the old address, no key on chain

# 1
tx = claim(kd, legacy, BAL)
check("the owner's key claims its old address from its new one", verdict(tx) is None, verdict(tx))
reflect_transaction(tx, logger=logger, block_height=H)
check("...the whole balance moves to the new address",
      get_account(legacy)["balance"] == 0 and get_account(kd["address"])["balance"] == BAL)
reflect_transaction(tx, logger=logger, block_height=H, revert=True)
check("...and a rollback moves exactly that back",
      get_account(legacy)["balance"] == BAL and int((get_account(kd["address"]) or {}).get("balance", 0)) == 0)
reflect_transaction(tx, logger=logger, block_height=H)
again = claim(kd, legacy, BAL)
check("a second claim is refused (nothing left)", "whole balance" in (verdict(again) or ""), verdict(again))

# 2
kd2 = owner(); legacy2 = A.legacy_address(kd2["public_key"]); create_account(legacy2, balance=500)
other = owner()
v = verdict(claim(other, legacy2, 500))
check("another key cannot claim an old address that is not its own", "not the one claimed" in (v or ""), v)
v = verdict(claim(kd2, legacy2, 499))
check("the amount must be the whole balance", "whole balance" in (v or ""), v)
kd3 = owner(); legacy3 = A.legacy_address(kd3["public_key"]); create_account(legacy3, balance=700)
kv_ops.account_set_field(legacy3, "public_key", kd3["public_key"])
v = verdict(claim(kd3, legacy3, 700))
check("an old address with a key on chain is never claimable (it was re-keyed)", "no chain ever saw" in (v or ""), v)
kd4 = owner(); legacy4 = A.legacy_address(kd4["public_key"]); create_account(legacy4, balance=10, bonded=5)
v = verdict(claim(kd4, legacy4, 10))
check("a bonded old address cannot be claimed", "bonded" in (v or ""), v)
v = verdict(claim(kd2, legacy2, 500, data={"legacy": legacy2, "amount": 500, "extra": 1}))
check("extra data is refused", "{legacy, amount}" in (v or ""), v)
v = verdict(claim(kd2, legacy2, 500, fee=P.MIN_TX_FEE))
check("a fee is refused", "no fee" in (v or ""), v)

# 3
k1 = T.reserved_uniqueness_key(claim(kd2, legacy2, 500))
k2 = T.reserved_uniqueness_key(claim(other, legacy2, 500))
check("one claim per old address per block (the same key, whoever sends it)", k1 == k2 == ("legacy_claim", legacy2), (k1, k2))
P.LEGACY_CLAIM_HEIGHT = LIVE_GATE
v = verdict(claim(kd2, legacy2, 500), h=H)
check("below the gate nothing is claimable", "not enabled" in (v or ""), v)
P.LEGACY_CLAIM_HEIGHT = 1

# 4 ACCEPTED RISK
pk = kd2["public_key"]
forger_pub = pk[:P.ADDRESS_BODY] + ("0" if pk[P.ADDRESS_BODY] != "0" else "1") + pk[P.ADDRESS_BODY + 1:]
check("ACCEPTED RISK (operator's decision): a key sharing the old address's 21 bytes derives the same old address",
      A.legacy_address(forger_pub) == legacy2)

# 5 the wallet
js = open(os.path.join(ROOT, "static", "interface.js")).read()
fn = js[js.index("async function claimLegacy(acc)"):js.index("async function refreshDashboard()")]
check("the wallet claims on every dashboard cycle", "claimLegacy(acc)" in js[js.index("async function refreshDashboard()"):])
check("...only on format 2 and only from the base key", "ADDR_FORMAT < 2" in fn and "makeAddress(w.publicKey) !== w.address" in fn)
check("...from this key's own old address, never a keyed one", "legacyAddress(w.publicKey)" in fn and "!old.public_key" in fn)
check("...with the exact balance", "buildLegacyClaimTx(w, legacy, Number(bal)" in fn)
i18n = open(os.path.join(ROOT, "static", "i18n.js")).read()
blk = i18n[i18n.index("const T118 = "):i18n.index("for (const l in T118)")]
check("...and says so in all 16 languages", all(f'"{l}": {{"legacy.claiming"' in blk for l in
      ("en", "cs", "es", "pt", "fr", "de", "it", "ru", "zh", "ja", "ko", "ar", "hi", "tr", "id", "vi")))

kv_ops.close_all()
print("ALL PASS — an old address is claimed by its own key" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
