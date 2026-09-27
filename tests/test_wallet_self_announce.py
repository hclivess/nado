"""The wallet puts its own public key on chain, unprompted (static/interface.js announceKey; operator 2026-09-27: "add
self announcement to the wallet so they secure themselves").

WHY. An account that received coins but never sent has no key on chain. Measured at gen 27: 871 such accounts. Until its
key is recorded, (1) its 21-byte format-1 address can be matched by a key someone else chose (the keyless-address
forgery), and (2) the gen-28 reroll cannot move it to the hash address its own wallet will derive. The wallet already
published a messaging key on open, but only from the messaging loop, which starts ONCE per page — a derived (HD)
account, or any account switched to later, never announced.

Pins:
  1. announceKey runs on every dashboard cycle, for the ACTIVE account (refreshDashboard calls it with the fresh account);
  2. it announces only when the chain shows NO key, and never as a paid rotation (skips an account with a bound
     messaging key) — the first msgkey bind is free under the node's SPAM_HARDEN_HEIGHT rule;
  3. the tx it sends carries the public key and pays no fee (buildMsgkeyTx puts public_key in the body; fee 0);
  4. it is throttled per address and counts only an accepted submit;
  4b. KEY ROTATION is never broken: a configured account, or a signer that is not the address's base key, never
      announces (the node records the first key it sees as the account's key, and the carry re-keys by it);
  5. the node side: a first-bind msgkey from a key-less funded account validates at the gate, and applying it records the
     sender's public key (PUBKEY-ONCE) — so the announcement actually secures the account.

Run: python3 tests/test_wallet_self_announce.py
"""
import os, sys, tempfile, logging, re
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-announce-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


js = open(os.path.join(ROOT, "static", "interface.js")).read()
fn = js[js.index("async function announceKey(acc)"):js.index("async function refreshDashboard()")]
rd = js[js.index("async function refreshDashboard()"):]
rd = rd[:rd.index("\n}\n")]

# 1
check("refreshDashboard announces for the active account on every cycle", "announceKey(acc)" in rd)
check("...using the account it just fetched (no second relay round trip)",
      re.search(r"const \[acc, ms\] = await Promise\.all\(\[getAccount\(addr\)", rd) is not None)
# 2
check("it stops once the chain shows a key", "if (acc.public_key)" in fn)
check("it never pays to re-bind a messaging key", "if (acc.kem_pub) return;" in fn)
check("an account not on chain yet is left for the next cycle", "!acc) return;" in fn)
check("a rotated (auth-configured) account never announces", "acc.auth || acc.auth_pending" in fn)
check("...and only the BASE key (the one the address derives from) ever announces — a rotated signer would pin the wrong "
      "key and the reroll would move the coins to an address the wallet never derives",
      "makeAddress(w.publicKey) !== a" in fn)
# 3
check("the announcement is a FREE msgkey (fee 0)", "buildMsgkeyTx(w, id.kemPub, await nextTargetBlock(), nowSeconds(), 0)" in fn)
b = js[js.index("function buildMsgkeyTx("):]
b = b[:b.index("\n}\n")]
check("...whose body carries the public key (what the node records)", "public_key: wallet.publicKey" in b)
# 4
check("it is throttled per address", "_keyAnnounceAt" in fn and "60000" in fn)
check("only an accepted submit marks it done", "out.data.result) { done[a] = true" in fn)
check("an account switch mid-flight never announces for the wrong account", "state.wallet !== w" in fn)

# 5 the node side, on the real tables
from genesis import create_indexers
create_indexers()
import protocol as P
from ops import transaction_ops as T
from ops.account_ops import create_account, get_account
from signatures import generate_keydict
logger = logging.getLogger("announce"); logger.addHandler(logging.NullHandler())
kd = generate_keydict()
create_account(kd["address"], balance=10 ** 9)               # received coins, never sent: no key on chain
check("(the account starts key-less)", not get_account(kd["address"]).get("public_key"))
tx = T.construct_msgkey_tx(kd, "ab" * 1184, P.SPAM_HARDEN_HEIGHT + 5)
try:
    T.validate_transaction(tx, logger, block_height=P.SPAM_HARDEN_HEIGHT)
    v = None
except Exception as e:
    v = str(e)
check("the free first bind from a key-less funded account validates at the gate", v is None, v)
T.index_transactions({"block_number": P.SPAM_HARDEN_HEIGHT, "block_transactions": [tx]}, [tx], logger)
check("applying it records the account's public key: the account is secured",
      get_account(kd["address"]).get("public_key") == kd["public_key"])

print("ALL PASS — a wallet secures its own account" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
