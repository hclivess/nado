"""A multisig member and an auth key sign with their own scheme (protocol.SIG_SCHEME_KEYS_HEIGHT, doc/signature-schemes.md;
operator 2026-11-04: "extend it to multisig and auth").

Driven on the real tables (throwaway HOME) with real signatures from native/pqsig, through validate_transaction and
auth_ops.apply_auth_tx, under BOTH rule sets: PRE = the block before the gate (every entry, key and `auth` tx is
ML-DSA-44, exactly as before) and POST = the gate.

  MULTISIG — a 2-of-3 of an SLH-DSA member, an ML-DSA-44 member and an ML-DSA-65 member:
    - POST: the SLH-DSA member and the ML-DSA-44 member spend together, paying each entry at its scheme's multiplier;
      a fee at the old per-entry count is refused;
    - the entry's `alg` is bound by the member address: the SLH-DSA key without it, or under another scheme, is a
      non-member; `"alg": "mldsa44"` and an unoffered scheme (FN-DSA) are refused — one entry, one byte string;
    - PRE: the same spend is refused by shape, and an all-ML-DSA-44 spend validates as before.
  AUTH — an ML-DSA-44 account guarded by an SLH-DSA recovery key, and an SLH-DSA account protecting itself:
    - POST: each installs, a pop under the wrong scheme is refused, and after install the account spends with its
      own-scheme key (tagged single signature or entry list), paying its scheme's floor;
    - the hash-based recovery key co-signs a rotation; apply and revert restore the account doc exactly;
    - an [alg, key] authenticator never answers key_authorized (blocks, attestations, messaging stay ML-DSA-44), and
      every SIG_ML44_ONLY_RECIPIENTS kind refuses an entry of another scheme;
    - PRE: an [alg, key] config is refused, and an SLH-DSA account's `auth` is refused (ML-DSA-44 only).

Run: python3 tests/test_a_multisig_member_and_an_auth_key_sign_with_their_own_scheme.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-sigkeys-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
os.environ["NADO_AUTH_FORCE"] = "1"
import copy, logging, secrets
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
from genesis import create_indexers
create_indexers()
import protocol as P
from ops import kv_ops, auth_ops as A, transaction_ops as T
from ops.account_ops import create_account, get_account
from ops.multisig_ops import multisig_address, draft_multisig_spend, add_member_signature
from signatures import generate_keydict, sign, unhex

logger = logging.getLogger("sigkeys"); logger.addHandler(logging.NullHandler())
fails = 0
POST = P.SIG_SCHEME_KEYS_HEIGHT
PRE = POST - 1
FEE = P.MIN_TX_FEE
SLH = "slhdsa128s"


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def verdict(tx, h):
    """None when validate_transaction accepts at height h, else its message."""
    try:
        T.validate_transaction(copy.deepcopy(tx), logger, block_height=h)
        return None
    except Exception as e:
        return str(e) or type(e).__name__


def fund(addr, pk=None):
    create_account(addr, balance=10 ** 12)
    if pk:
        kv_ops.account_set_field(addr, "public_key", pk)


def resign(tx, kds):
    """Re-sign an entry list after its body changed (fee, data): new txid, one entry per keydict in its scheme."""
    body = {k: v for k, v in tx.items() if k not in ("txid", "signature")}
    body["txid"] = T.create_txid(body)
    body["signature"] = [T._signature_entry(kd, unhex(body["txid"])) for kd in kds]
    return body


PAYEE = generate_keydict()["address"]

# ---- MULTISIG ---------------------------------------------------------------------------------------------------------
MS, MM, MX = generate_keydict(SLH), generate_keydict(), generate_keydict("mldsa65")
members = sorted([MS["address"], MM["address"], MX["address"]])
MADDR = multisig_address(2, members)
fund(MADDR)


def spend(fee, signers=((MS, SLH), (MM, None))):
    tx = draft_multisig_spend(2, members, PAYEE, 1000, fee, POST + 10)
    for kd, alg in signers:
        add_member_signature(tx, kd["private_key"], alg=alg)
    return tx


mixed = spend(FEE * 4)
check("the SLH-DSA member's entry names its scheme, the ML-DSA-44 member's carries none",
      [e.get("alg") for e in mixed["signature"]] == [SLH, None], [e.get("alg") for e in mixed["signature"]])
check("POST: an SLH-DSA and an ML-DSA-44 member spend together (fee 3 + 1 floors)", verdict(mixed, POST) is None,
      verdict(mixed, POST))
v = verdict(spend(FEE * 2), POST)
check("POST: a fee at the old per-entry count is refused", v and "per-signature floor" in v, v)
three = spend(FEE * 6, ((MS, SLH), (MX, "mldsa65")))
check("POST: the SLH-DSA and the ML-DSA-65 members spend together (fee 3 + 2)", verdict(three, POST) is None,
      verdict(three, POST))

bare = copy.deepcopy(mixed); bare["signature"][0].pop("alg")
v = verdict(bare, POST)
check("POST: the SLH-DSA key without its alg is refused (sized as ML-DSA-44)", v and "lowercase hex" in v, v)
lie = copy.deepcopy(three); lie["signature"][1]["alg"] = "mldsa87"
v = verdict(lie, POST)
check("POST: a key named under another scheme is refused (every scheme has its own sizes)", v and "lowercase hex" in v, v)
swap = copy.deepcopy(three); swap["signature"][0]["alg"] = "mldsa65"
v = verdict(swap, POST)
check("POST: an SLH-DSA key under the wrong alg is refused", v and "lowercase hex" in v, v)
OUT = generate_keydict(SLH)
stranger = copy.deepcopy(mixed)
stranger["signature"][0] = {"public_key": OUT["public_key"], "alg": SLH,
                            "signature": sign(OUT["private_key"], unhex(mixed["txid"]), SLH)}
v = verdict(stranger, POST)
check("POST: a well-formed SLH-DSA entry by a key outside the descriptor is a non-member", v and "non-member" in v, v)
spelled = copy.deepcopy(mixed); spelled["signature"][1]["alg"] = "mldsa44"
v = verdict(spelled, POST)
check("POST: \"alg\": \"mldsa44\" in an entry is refused (absence is its only spelling)", v and "absent = mldsa44" in v, v)
FN = generate_keydict("fndsa512")
fn_members = sorted([FN["address"], MM["address"]])
fund(multisig_address(1, fn_members))
fn_tx = draft_multisig_spend(1, fn_members, PAYEE, 1000, FEE * 2, POST + 10)
fn_tx["signature"] = [{"public_key": FN["public_key"], "alg": "fndsa512",
                       "signature": sign(FN["private_key"], unhex(fn_tx["txid"]), "fndsa512")}]
v = verdict(fn_tx, POST)
check("POST: an entry of an unoffered scheme (FN-DSA) is refused", v and "alg must be one of" in v, v)

# the CLI co-signs as the member its keyfile holds, in that key's scheme (scripts/nado_cli.py msig-sign)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import json, types, nado_cli
cli_file = os.path.join(os.environ["HOME"], "proposal.json")
json.dump(spend(FEE * 4, ((MM, None),)), open(cli_file, "w"))
nado_cli.c_msig_sign(MS, None, types.SimpleNamespace(file=cli_file))
cli_tx = json.load(open(cli_file))
check("the CLI's msig-sign adds the SLH-DSA member's entry in its scheme, and the spend validates",
      [e.get("alg") for e in cli_tx["signature"]] == [None, SLH] and verdict(cli_tx, POST) is None, verdict(cli_tx, POST))
v = verdict(mixed, PRE)
check("PRE: the mixed spend is refused by shape (an entry carries no alg below the gate)",
      v and "exactly signature and, optionally, public_key" in v, v)
M2 = generate_keydict()
old_members = sorted([MM["address"], M2["address"]])
fund(multisig_address(2, old_members))
old = draft_multisig_spend(2, old_members, PAYEE, 1000, FEE * 2, PRE)
for kd in (MM, M2):
    add_member_signature(old, kd["private_key"])
check("PRE: an all-ML-DSA-44 spend validates as before", verdict(old, PRE) is None, verdict(old, PRE))
check("POST: and still does", verdict(old, POST) is None, verdict(old, POST))

# ---- AUTH: an ML-DSA-44 account with a hash-based recovery key ----------------------------------------------------------
HOT, REC = generate_keydict(), generate_keydict(SLH)
OWNER = HOT["address"]
fund(OWNER, HOT["public_key"])
cfg1 = {"v": 1, "keys": [HOT["public_key"], [SLH, REC["public_key"]]], "sign": ["ID", 0],
        "reconf": ["THRESHOLD", 2, [["ID", 0], ["ID", 1]]]}
protect = T.construct_auth_tx(OWNER, [HOT], {"op": "set", "cfg": cfg1, "pop": {REC["public_key"]: T.auth_pop(OWNER, cfg1, REC)}},
                              FEE, POST + 10)
check("POST: an ML-DSA-44 account installs an SLH-DSA recovery key", verdict(protect, POST) is None, verdict(protect, POST))
v = verdict(protect, PRE)
check("PRE: an [alg, key] authenticator is refused", v and "2624-hex ML-DSA-44 public key" in v, v)
bad_pop = copy.deepcopy(protect)
bad_pop["data"]["pop"][REC["public_key"]] = sign(HOT["private_key"], A.pop_message(OWNER, cfg1))
bad_pop = resign(bad_pop, [HOT])
v = verdict(bad_pop, POST)
check("POST: a pop not made by the SLH-DSA key under its own scheme is refused", v and "proof of possession" in v, v)
dup = {"v": 1, "keys": [HOT["public_key"], [SLH, REC["public_key"]], [SLH, REC["public_key"]]], "sign": ["ID", 0],
       "reconf": ["THRESHOLD", 3, [["ID", 0], ["ID", 1], ["ID", 2]]]}
try:
    A.validate_config(dup, POST); v = None
except AssertionError as e:
    v = str(e)
check("POST: one SLH-DSA key twice is refused", v and "duplicate authenticator" in v, v)
try:
    A.validate_config({"v": 1, "keys": [[P.SIG_DEFAULT, HOT["public_key"]]], "sign": ["ID", 0], "reconf": ["ID", 0]}, POST); v = None
except AssertionError as e:
    v = str(e)
check("POST: an ML-DSA-44 key spelled [mldsa44, key] is refused (a bare string is its only spelling)",
      v and "every authenticator must be" in v, v)

before = copy.deepcopy(get_account(OWNER))
T.validate_transaction(copy.deepcopy(protect), logger, block_height=POST)
A.apply_auth_tx(protect, POST, logger)
check("installed: the config holds the SLH-DSA key as [alg, key]", get_account(OWNER)["auth"]["keys"][1] == [SLH, REC["public_key"]])
check("an [alg, key] authenticator never answers key_authorized (blocks, attestations, messaging)",
      not A.key_authorized(REC["public_key"], OWNER, POST) and A.key_authorized(HOT["public_key"], OWNER, POST))
rec_alone = T.sign_entries({"sender": OWNER, "recipient": PAYEE, "amount": 1000, "timestamp": 1, "data": "",
                            "nonce": secrets.token_hex(4), "max_block": POST + 10, "chain_id": P.CHAIN_ID, "fee": FEE * 3}, [REC])
v = verdict(rec_alone, POST)
check("the recovery key alone cannot spend (signing policy is the hot key)", v and "signing policy" in v, v)

NEW = generate_keydict()
cfg2 = {"v": 2, "keys": [NEW["public_key"], [SLH, REC["public_key"]]], "sign": ["ID", 0], "reconf": cfg1["reconf"]}
rotate = T.construct_auth_tx(OWNER, [HOT, REC], {"op": "set", "cfg": cfg2, "pop": {NEW["public_key"]: T.auth_pop(OWNER, cfg2, NEW)}},
                             FEE * 4, POST + 10)
check("the rotation's recovery entry names its scheme", [e.get("alg") for e in rotate["signature"]] == [None, SLH])
v = verdict(rotate, POST)
check("POST: hot + SLH-DSA recovery rotate the hot key at once (the reconfig policy)", v is None, v)
cheap = resign(rotate, [HOT, REC]); cheap["fee"] = FEE * 3; cheap = resign(cheap, [HOT, REC])
v = verdict(cheap, POST)
check("POST: a paying list with an SLH-DSA entry pays the whole sum (3 + 1), not the sum minus the first", v and "per-signature floor" in v, v)
mid = copy.deepcopy(get_account(OWNER))
A.apply_auth_tx(rotate, POST, logger)
check("rotated: the new hot key signs alone", A.key_authorized(NEW["public_key"], OWNER, POST + 1) and not A.key_authorized(HOT["public_key"], OWNER, POST + 1))
A.apply_auth_tx(rotate, POST, logger, revert=True)
check("revert of the rotation restores the account doc exactly", get_account(OWNER) == mid)
A.apply_auth_tx(protect, POST, logger, revert=True)
check("revert of the install restores the account doc exactly", get_account(OWNER) == before)

# ---- AUTH: an SLH-DSA account protects itself ---------------------------------------------------------------------------
SH, SR = generate_keydict(SLH), generate_keydict(SLH)
SADDR = SH["address"]
fund(SADDR, SH["public_key"])
check("the implicit config of an SLH-DSA account names its key's scheme",
      A.implicit_config(SADDR, get_account(SADDR))["keys"] == [[SLH, SH["public_key"]]])
scfg = {"v": 1, "keys": [[SLH, SH["public_key"]], [SLH, SR["public_key"]]], "sign": ["ID", 0],
        "reconf": ["THRESHOLD", 2, [["ID", 0], ["ID", 1]]]}
sdata = {"op": "set", "cfg": scfg, "pop": {SR["public_key"]: T.auth_pop(SADDR, scfg, SR)}}
stag = {"sender": SADDR, "recipient": "auth", "amount": 0, "timestamp": 1, "data": sdata, "nonce": secrets.token_hex(4),
        "max_block": POST + 10, "chain_id": P.CHAIN_ID, "fee": FEE * 3, "alg": SLH}
stag["txid"] = T.create_txid(stag)
stag["signature"] = sign(SH["private_key"], unhex(stag["txid"]), SLH)
v = verdict(stag, POST)
check("POST: an SLH-DSA account protects itself with a tagged auth tx", v is None, v)
v = verdict(stag, PRE)
check("PRE: an SLH-DSA account's auth is refused (ML-DSA-44 only)", v and "auth transaction is ML-DSA-44 only" in v, v)
slist = T.construct_auth_tx(SADDR, [SH], sdata, FEE * 3, POST + 10)
v = verdict(slist, POST)
check("POST: or with an entry list", v is None, v)

T.validate_transaction(copy.deepcopy(stag), logger, block_height=POST)
A.apply_auth_tx(stag, POST, logger)
pay = {"sender": SADDR, "recipient": PAYEE, "amount": 1000, "timestamp": 1, "data": "", "nonce": secrets.token_hex(4),
       "max_block": POST + 10, "chain_id": P.CHAIN_ID, "fee": FEE * 3, "alg": SLH, "public_key": SH["public_key"]}
pay["txid"] = T.create_txid(pay)
pay["signature"] = sign(SH["private_key"], unhex(pay["txid"]), SLH)
v = verdict(pay, POST)
check("configured: the SLH-DSA hot key spends with a tagged single signature", v is None, v)
keyless = {k: v for k, v in pay.items() if k not in ("public_key", "txid", "signature")}
keyless["txid"] = T.create_txid(keyless)
keyless["signature"] = sign(SH["private_key"], unhex(keyless["txid"]), SLH)
v = verdict(keyless, POST)
check("configured: and key-less (the sole signing key fills in under its own scheme)", v is None, v)
plist = T.sign_entries({k: v for k, v in pay.items() if k not in ("alg", "public_key", "txid", "signature")}, [SH])
v = verdict(plist, POST)
check("configured: and with an entry list", v is None, v)
cheap = T.sign_entries(dict({k: v for k, v in pay.items() if k not in ("alg", "public_key", "txid", "signature")}, fee=FEE * 2), [SH])
v = verdict(cheap, POST)
check("configured: a paying SLH-DSA list below its scheme's floor (3) is refused", v and "per-signature floor" in v, v)
check("an SLH-DSA account's keys never answer key_authorized", not A.key_authorized(SH["public_key"], SADDR, POST))
reg = T.sign_entries({"sender": SADDR, "recipient": "msgkey", "amount": 0, "timestamp": 1, "data": "",
                      "nonce": secrets.token_hex(4), "max_block": POST + 10, "chain_id": P.CHAIN_ID, "fee": FEE * 3}, [SH])
v = verdict(reg, POST)
check("an ML-DSA-44-only kind (msgkey) refuses an entry of another scheme", v and "ML-DSA-44 only" in v, v)

print("ALL PASS — a multisig member and an auth key sign with their own scheme" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
