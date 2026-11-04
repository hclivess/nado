"""A protected multisig member signs with its current key (protocol.MSIG_MEMBER_AUTH_HEIGHT, ops/multisig_ops.member_signs).

A multisig member used to be only the address its key derives. A member that PROTECTED its account and rotated its key
(doc/key-rotation.md) could then not co-sign with the key it now uses — and the key it rotated AWAY from, possibly the
stolen one, still signed for it. Driven through validate_transaction with real auth configs (auth_ops.apply_auth_tx),
under both rule sets:
  POST (from the gate):
    - the member's current key signs, its entry naming the member; the multisig spend validates;
    - the rotated-away base key no longer signs for the member (it is not in the config);
    - the current key without `member` is a non-member; `member` on a key that derives that address is refused (one
      spelling); `member` naming a member whose config does not hold the key is refused;
    - a key that is in the config but cannot sign alone (the recovery key) does not sign for the member;
    - an unprotected member signs exactly as before; an SLH-DSA protected member signs with its [alg, key];
    - `member` is refused on a non-multisig entry list;
  PRE (the block before): the old rule stands — the base key still signs, `member` is refused by shape.
  The CLI's msig-sign --member and add_member_signature(member=) build the accepted entry.

Run: python3 tests/test_a_protected_multisig_member_signs_with_its_current_key.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-msigmember-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
os.environ["NADO_AUTH_FORCE"] = "1"
import copy, json, logging, secrets, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
from genesis import create_indexers
create_indexers()
import protocol as P
from ops import kv_ops, auth_ops as A, transaction_ops as T
from ops.account_ops import create_account
from ops.multisig_ops import multisig_address, draft_multisig_spend, add_member_signature
from signatures import generate_keydict, sign, unhex

logger = logging.getLogger("msigmember"); logger.addHandler(logging.NullHandler())
fails = 0
POST = P.MSIG_MEMBER_AUTH_HEIGHT
PRE = POST - 1
FEE = P.MIN_TX_FEE
SLH = "slhdsa128s"


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def verdict(tx, h):
    try:
        T.validate_transaction(copy.deepcopy(tx), logger, block_height=h)
        return None
    except Exception as e:
        return str(e) or type(e).__name__


def protect(base, hot, rec, h):
    """Install keys [hot, recovery] (sign = hot alone, reconf = both) on base's account, signed by its base key."""
    addr = base["address"]
    kv_ops.account_set_field(addr, "public_key", base["public_key"])
    spell = lambda k: [k["alg"], k["public_key"]] if k.get("alg") else k["public_key"]   # auth_ops.key_pair's two spellings
    cfg = {"v": 1, "keys": [spell(hot), spell(rec)], "sign": ["ID", 0], "reconf": ["THRESHOLD", 2, [["ID", 0], ["ID", 1]]]}
    pop = {k["public_key"]: T.auth_pop(addr, cfg, k) for k in (hot, rec) if k["public_key"] != base["public_key"]}
    tx = T.construct_auth_tx(addr, [base], {"op": "set", "cfg": cfg, "pop": pop}, FEE * 3, h + 10)
    T.validate_transaction(copy.deepcopy(tx), logger, block_height=h)
    A.apply_auth_tx(tx, h, logger)


def entry(kd, txid, member=None):
    e = {"public_key": kd["public_key"], "signature": sign(kd["private_key"], unhex(txid), kd.get("alg"))}
    if kd.get("alg"):
        e["alg"] = kd["alg"]
    if member:
        e["member"] = member
    return e


PAYEE = generate_keydict()["address"]
BASE, HOT, REC = generate_keydict(), generate_keydict(), generate_keydict()     # the protected member: base -> hot + rec
PLAIN = generate_keydict()                                                         # an unprotected member
M = BASE["address"]
for a in (M, PLAIN["address"]):
    create_account(a, balance=10 ** 12)
protect(BASE, HOT, REC, PRE - 50)
members = sorted([M, PLAIN["address"]])
MS = multisig_address(2, members)
create_account(MS, balance=10 ** 12)


def spend(h, entries_of):
    tx = draft_multisig_spend(2, members, PAYEE, 1000, FEE * 2, h + 10)
    tx["signature"] = entries_of(tx["txid"])
    return tx


plain_e = lambda txid: entry(PLAIN, txid)
ok = spend(POST, lambda t: [entry(HOT, t, M), plain_e(t)])
check("POST: the protected member's current key signs, naming its member", verdict(ok, POST) is None, verdict(ok, POST))
old = spend(POST, lambda t: [entry(BASE, t), plain_e(t)])
v = verdict(old, POST)
check("POST: the rotated-away base key no longer signs for the member", v and "does not sign for member" in v, v)
bare = spend(POST, lambda t: [entry(HOT, t), plain_e(t)])
v = verdict(bare, POST)
check("POST: the current key without `member` is a non-member", v and "non-member" in v, v)
redundant = spend(POST, lambda t: [entry(BASE, t, M), plain_e(t)])
v = verdict(redundant, POST)
check("POST: `member` on a key that derives that very address is refused (one spelling)", v and "only when its key does not derive" in v, v)
stranger = generate_keydict()
forged = spend(POST, lambda t: [entry(stranger, t, M), plain_e(t)])
v = verdict(forged, POST)
check("POST: `member` naming a member whose config does not hold the key is refused", v and "does not sign for member" in v, v)
recovery = spend(POST, lambda t: [entry(REC, t, M), plain_e(t)])
v = verdict(recovery, POST)
check("POST: the recovery key (in the config, but not alone the signing policy) does not sign", v and "does not sign for member" in v, v)
check("POST: the unprotected member signs as before (no `member`)", verdict(ok, POST) is None and "member" not in ok["signature"][1])

# an SLH-DSA protected member
SB, SH, SR = generate_keydict(SLH), generate_keydict(SLH), generate_keydict(SLH)
create_account(SB["address"], balance=10 ** 12)
protect(SB, SH, SR, PRE - 40)
members2 = sorted([SB["address"], PLAIN["address"]])
create_account(multisig_address(2, members2), balance=10 ** 12)
tx2 = draft_multisig_spend(2, members2, PAYEE, 1000, FEE * 4, POST + 10)
tx2["signature"] = [entry(SH, tx2["txid"], SB["address"]), entry(PLAIN, tx2["txid"])]
check("POST: an SLH-DSA protected member signs with its [alg, key], naming its member", verdict(tx2, POST) is None, verdict(tx2, POST))

# `member` belongs to multisig entries only
lst = T.sign_entries({"sender": M, "recipient": PAYEE, "amount": 1, "timestamp": 1, "data": "", "nonce": secrets.token_hex(4),
                      "max_block": POST + 10, "chain_id": P.CHAIN_ID, "fee": FEE}, [HOT])
lst["signature"][0]["member"] = M
v = verdict(lst, POST)
check("POST: `member` is refused on a non-multisig entry list", v and "a signature entry carries exactly" in v, v)

# PRE: the old rule
pre_old = spend(PRE, lambda t: [entry(BASE, t), plain_e(t)])
check("PRE: below the gate the base key still signs (history replays)", verdict(pre_old, PRE) is None, verdict(pre_old, PRE))
pre_member = spend(PRE, lambda t: [entry(HOT, t, M), plain_e(t)])
v = verdict(pre_member, PRE)
check("PRE: `member` is refused by shape below the gate", v and "a signature entry carries exactly" in v, v)

# the builders: add_member_signature(member=) and the CLI's msig-sign --member
built = draft_multisig_spend(2, members, PAYEE, 1000, FEE * 2, POST + 10)
add_member_signature(built, HOT["private_key"], member=M)
check("add_member_signature(member=) names the member", built["signature"][0].get("member") == M)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import nado_cli
f = os.path.join(os.environ["HOME"], "p.json")
json.dump(built, open(f, "w"))
nado_cli.c_msig_sign(PLAIN, None, types.SimpleNamespace(file=f, member=None))
cli_tx = json.load(open(f))
check("the CLI adds the plain member, and the spend validates from the gate",
      len(cli_tx["signature"]) == 2 and verdict(cli_tx, POST) is None, verdict(cli_tx, POST))

print("ALL PASS — a protected multisig member signs with its current key" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
