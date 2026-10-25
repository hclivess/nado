"""An account signs with the scheme its address commits to (protocol.py "USER-SELECTABLE SIGNATURE SCHEMES",
doc/signature-schemes.md; operator 2026-10-25: "multiple (pluggable) scheme options ... let users pick").

Driven on the real tables (throwaway HOME) with real signatures from every offered scheme (native/pqsig), under BOTH rule
sets, as every consensus change here is:

  DORMANT (gen 28, SIG_SCHEMES_HEIGHT = 2^62): a tagged transaction is refused at every height, an ML-DSA-44 transaction
  validates exactly as before, and an ML-DSA-44 address is the one it always was.

  ACTIVE (the gate at 1, gen 29): for ML-DSA-65, ML-DSA-87 and SLH-DSA-SHA2-128s —
    - an honest first transfer (carrying the key) and a later key-less one validate;
    - the address commits to the scheme: the same key under another `alg`, or untagged, derives another address and is
      refused — so is a later key-less tx naming the wrong scheme for the stored key;
    - one transaction, one byte string: `"alg": "mldsa44"` is refused (absence is its only spelling), witnesses are sized
      by the scheme and must be canonical lowercase hex;
    - FN-DSA-512 is built but NOT offered (FIPS 206 is a draft): refused even with a valid signature;
    - entry lists, multisig and every kind the chain verifies off the tx with ML-DSA-44 (register, bond, msgkey, auth,
      legacy_claim, the duty family, the TPM ceremony) are refused for a tagged tx;
    - a paying tx pays its scheme's fee multiple; the block auth leaf declares the scheme while an untagged tx's leaf is
      unchanged; and raw block-auth evidence verifies a tagged signature under its own scheme.

Run: python3 tests/test_an_account_signs_with_the_scheme_its_address_commits_to.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-sigschemes-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import logging, secrets
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
from genesis import create_indexers
create_indexers()
import protocol as P
from ops import kv_ops, transaction_ops as T
from ops.account_ops import create_account
from ops.address_ops import make_address
from execnode.stark import mldsa_block_auth as A
from signatures import generate_keydict, from_private_key, sign, unhex, verify

logger = logging.getLogger("sigschemes"); logger.addHandler(logging.NullHandler())
fails = 0
G = 29100
SCHEMES = ("mldsa65", "mldsa87", "slhdsa128s")


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def verdict(tx, h=G):
    """None when validate_transaction accepts at height h, else its message."""
    try:
        T.validate_transaction(dict(tx), logger, block_height=h)
        return None
    except Exception as e:
        return str(e) or type(e).__name__


def body(kd, recipient=None, carry_pk=True, data=""):
    b = {"sender": kd["address"], "recipient": recipient or PAYEE, "amount": 1000, "timestamp": 1, "data": data,
         "nonce": secrets.token_hex(4), "max_block": G, "chain_id": P.CHAIN_ID}
    if carry_pk:
        b["public_key"] = kd["public_key"]
    return b


def signed(b, kd, alg, fee=None):
    """Hand-signed tx with exactly the `alg` given (None = the field absent), so wrong labels can be built too."""
    tx = dict(b, fee=P.MIN_TX_FEE * 3 if fee is None else fee)
    if alg is not None:
        tx["alg"] = alg
    tx["txid"] = T.create_txid(tx)
    tx["signature"] = sign(kd["private_key"], unhex(tx["txid"]), kd.get("alg"))
    return tx


def fund(kd, with_pk=False):
    create_account(kd["address"], balance=10 ** 12)
    if with_pk:
        kv_ops.account_set_field(kd["address"], "public_key", kd["public_key"])


PAYEE = generate_keydict()["address"]
ML44 = generate_keydict(); fund(ML44)
KEYS = {a: generate_keydict(a) for a in SCHEMES}
for kd in KEYS.values():
    fund(kd)

# ---- the address commits to the scheme, and ML-DSA-44 addresses never move -----------------------------------------
check("an ML-DSA-44 address is the one it always was (no alg in its preimage)",
      make_address(ML44["public_key"]) == make_address(ML44["public_key"], alg="mldsa44") == ML44["address"])
for a, kd in KEYS.items():
    check(f"{a}: the keydict names its scheme and its address commits to it",
          kd["alg"] == a and kd["address"] == make_address(kd["public_key"], alg=a) != make_address(kd["public_key"]))
    check(f"{a}: the seed alone restores the account under its scheme", from_private_key(kd["private_key"], a) == kd)

# ---- DORMANT: the gen-28 rule set --------------------------------------------------------------------------------------
check("dormant: the gate is 2^62 on generation 28 (live consensus unchanged)",
      P.CHAIN_GENERATION != 28 or P.SIG_SCHEMES_HEIGHT == 1 << 62, P.SIG_SCHEMES_HEIGHT)
_live_gate = P.SIG_SCHEMES_HEIGHT
P.SIG_SCHEMES_HEIGHT = 1 << 62
honest44 = T.create_transaction(body(ML44), ML44["private_key"], P.MIN_TX_FEE)
check("dormant: an ML-DSA-44 transfer validates as before (no alg field)", "alg" not in honest44 and verdict(honest44) is None,
      verdict(honest44))
for a, kd in KEYS.items():
    v = verdict(signed(body(kd), kd, a))
    check(f"dormant: a {a} transfer is refused at every height", v is not None and "not active" in v, v)

# ---- ACTIVE: the gen-29 rule set -----------------------------------------------------------------------------------------
P.SIG_SCHEMES_HEIGHT = 1
check("active: the ML-DSA-44 transfer still validates", verdict(honest44) is None, verdict(honest44))
for a, kd in KEYS.items():
    units = P.SIG_SCHEME_SIZES[a][2]
    first = signed(body(kd), kd, a, fee=P.MIN_TX_FEE * units)
    check(f"{a}: an honest first transfer (carrying its key) validates", verdict(first) is None, verdict(first))
    via_builder = T.create_transaction(body(kd), kd["private_key"], P.MIN_TX_FEE, alg=a)
    check(f"{a}: create_transaction tags it and lifts the fee to the scheme's floor",
          via_builder["alg"] == a and via_builder["fee"] == P.MIN_TX_FEE * units and verdict(via_builder) is None,
          (via_builder.get("fee"), verdict(via_builder)))
    if units > 1:
        v = verdict(signed(body(kd), kd, a, fee=P.MIN_TX_FEE * units - 1))
        check(f"{a}: a paying fee below {units} x MIN_TX_FEE is refused", v is not None and "floor" in v, v)
    # PUBKEY-ONCE: once the account has published its key, a key-less tx names the scheme and validates
    kv_ops.account_set_field(kd["address"], "public_key", kd["public_key"])
    later = signed(body(kd, carry_pk=False), kd, a)
    check(f"{a}: a later key-less transfer validates", verdict(later) is None, verdict(later))
    v = verdict(signed(body(kd, carry_pk=False), kd, None))
    check(f"{a}: ...but untagged it is refused (the stored key derives this address only under {a})", v is not None, v)
    other = next(x for x in SCHEMES if x != a)
    v = verdict(signed(body(kd, carry_pk=False), kd, other))
    check(f"{a}: ...and labelled {other} it is refused", v is not None, v)
    v = verdict(signed(body(kd), kd, "mldsa44"))
    check(f"{a}: \"alg\": \"mldsa44\" is refused (absence is its only spelling)", v is not None and "alg must be" in v, v)
    tx = signed(body(kd), kd, a)
    check(f"{a}: an UPPERCASE signature is refused", verdict(dict(tx, signature=tx["signature"].upper())) is not None)
    check(f"{a}: a signature of another scheme's size is refused",
          verdict(dict(tx, signature=honest44["signature"])) is not None)
    for r in ("register", "bond", "msgkey", "auth", "legacy_claim", "duty", "tpm_enrol"):
        v = verdict(signed(body(kd, recipient=r), kd, a))
        check(f"{a}: a {r} transaction is refused (ML-DSA-44 only)", v is not None and "ML-DSA-44 only" in v, v)
    lst = signed(body(kd, carry_pk=False), kd, a)
    lst["signature"] = [{"public_key": kd["public_key"], "signature": lst["signature"]}]
    v = verdict(lst)
    check(f"{a}: an entry-list signature is refused", v is not None, v)

# a key presented as another scheme's: the same bytes can never read as an ML-DSA-44 key (sizes differ) and the address
# commits to the label — a NEW account whose first tx carries an ML-DSA-65 key labelled mldsa87 is refused
kd65 = generate_keydict("mldsa65"); fund(kd65)
v = verdict(signed(body(kd65), kd65, "mldsa87"))
check("a first tx carrying an ML-DSA-65 key labelled mldsa87 is refused", v is not None, v)

# FN-DSA-512: built and correct, never offered while FIPS 206 is a draft
fn = generate_keydict("fndsa512"); fund(fn)
fn_tx = signed(body(fn), fn, "fndsa512")
check("fndsa512: the signature itself is valid (the plugin works)",
      verify(fn_tx["signature"], fn["public_key"], unhex(fn_tx["txid"]), "fndsa512"))
v = verdict(fn_tx)
check("fndsa512: ...but the chain refuses it (not offered until FIPS 206 is final)", v is not None and "alg must be" in v, v)

# ---- the block auth leaf and raw evidence ----------------------------------------------------------------------------
tx65 = signed(body(KEYS["mldsa65"], carry_pk=False), KEYS["mldsa65"], "mldsa65")
blk = {"block_number": G, "block_transactions": [honest44, tx65]}
ents = A.auth_entries(blk)
check("auth leaf: an untagged tx keeps kind 1 and its exact entry shape",
      ents[0]["kind"] == A.KIND_SINGLE_MLDSA44 and "alg" not in ents[0])
check("auth leaf: a tagged tx declares its scheme's kind", ents[1]["kind"] == A.KIND_SINGLE_BY_ALG["mldsa65"] and
      ents[1]["alg"] == "mldsa65")
check("auth kinds are never reused", len(set(A.KIND_SINGLE_BY_ALG.values()) | {A.KIND_SINGLE_MLDSA44, A.KIND_MULTISIG_MLDSA44})
      == len(A.KIND_SINGLE_BY_ALG) + 2)
root, count = A.auth_commitments(blk)
blk.update(auth_root=root, auth_count=count)
pks = {ML44["address"]: ML44["public_key"], KEYS["mldsa65"]["address"]: KEYS["mldsa65"]["public_key"]}
vsig = lambda s, pk, txid, alg=None: verify(s, pk, unhex(txid), alg)
ok, why = A.evidence_ok(A.raw_evidence(blk), blk, resolve_pubkey=pks.get, verify_sig=vsig)
check("raw evidence verifies a tagged signature under its own scheme", ok, why)
bad = dict(blk, block_transactions=[honest44, dict(tx65, signature=signed(body(KEYS["mldsa65"]), KEYS["mldsa65"], "mldsa65")["signature"])])
ok, why = A.evidence_ok(A.raw_evidence(bad), bad, resolve_pubkey=pks.get, verify_sig=vsig)
check("raw evidence refuses a tagged signature over another txid", not ok, why)

P.SIG_SCHEMES_HEIGHT = _live_gate
print("\nALL PASS — an account signs with the scheme its address commits to" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
