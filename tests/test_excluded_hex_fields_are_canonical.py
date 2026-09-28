"""A transaction has one byte string: every witness the txid does not hash is canonical hex, from TX_HEX_CANONICAL_HEIGHT
(audit 2026-09-25, MED "sig/pubkey hex re-encoding"; protocol.TX_HEX_CANONICAL_HEIGHT, reroll-only).

THE FINDING, reproduced below the gate on the real tables (throwaway HOME) with real ML-DSA signatures:
  * create_txid excludes `public_key` and validate_txid strips `signature` (a string or an entry list), but verification
    decoded both through bytes.fromhex, which takes UPPERCASE, mixed case and whitespace. A relayer re-encodes a
    signed transaction: SAME txid, still valid, DIFFERENT block hash and upcoming-block hash for the same tx set — so
    two nodes holding "the same" tx build different blocks (every node assembles every block), the txid-keyed
    reconcile sees nothing to heal, and dedup-by-txid keeps whichever copy arrived first;
  * a mixed-case key on an account's FIRST transaction is stored verbatim as its PUBKEY-ONCE key; after that the
    owner's own canonical transactions fail key_bound — a relayer locks the account out;
  * found while fixing it: with an entry-LIST signature nothing verifies a top-level public_key, yet PUBKEY-ONCE stored
    it for a never-sent sender and the implicit auth config then authorizes it — a relayer that adds its own key to an
    account's list-signed first transaction spends from that account.
FROM THE GATE every such variant is refused (string signature, top-level key, null/empty key, a top-level key beside an
entry list, and each entry of an auth / multisig list: case, whitespace, extra keys, null key), honest transactions from
every in-tree signer pass, and below the gate nothing changes (gen-27 replay is byte-identical).
KNOWN OPEN (pinned so the day one closes this file says so): the signer re-signing the same txid, a relayer stripping
a public_key the account already published, reordering an entry list, dropping a surplus entry. No encoding rule can
close those — only a block hash that stops committing witness bytes.

Run: python3 tests/test_excluded_hex_fields_are_canonical.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-hexcanon-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import json, logging, re, secrets, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
from genesis import create_indexers
create_indexers()
import protocol as P
from ops import kv_ops, transaction_ops as T
from ops.account_ops import create_account
from ops.block_ops import construct_block
from ops.multisig_ops import multisig_address, draft_multisig_spend, add_member_signature
from hashing import blake2b_hash
from signatures import generate_keydict, sign, unhex, verify

logger = logging.getLogger("hexcanon"); logger.addHandler(logging.NullHandler())
fails = 0
LIVE_GATE = P.TX_HEX_CANONICAL_HEIGHT
# the rule is dormant (2^62) on gen 27 and live from block 1 on gen 28; exercise it at a height past every other gate
G = max(P.SPAM_HARDEN_HEIGHT, P.CERT_CLOCK_HEIGHT, P.TPM_DRAW_UNGRINDABLE_HEIGHT) + 100
P.TX_HEX_CANONICAL_HEIGHT = G


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def verdict(tx, h):
    """None when validate_transaction accepts at height h, else its message."""
    try:
        T.validate_transaction(dict(tx), logger, block_height=h)
        return None
    except Exception as e:
        return str(e) or type(e).__name__


def block_hash(txs, h=G):
    """The block every node would assemble from exactly `txs` on one parent (state/exec roots pinned)."""
    return construct_block(block_timestamp=1, block_number=h, parent_hash="00" * 32, creator=PAYEE, transaction_pool=txs,
                           block_reward=0, state_root="11" * 32, exec_root="22" * 32, exec_cursor=0)["block_hash"]


def upcoming_hash(txs, h=G):
    """memserver.get_upcoming_block_hash's preimage for the same tip and tx set — the determinism signal."""
    return blake2b_hash(["00" * 32, h, T.sort_transaction_pool(txs)])


def transfer(kd, carry_pk=True, max_block=None):
    body = {"sender": kd["address"], "recipient": PAYEE, "amount": 1000, "timestamp": 1, "data": "",
            "nonce": secrets.token_hex(4), "max_block": G if max_block is None else max_block, "chain_id": P.CHAIN_ID}
    if carry_pk:
        body["public_key"] = kd["public_key"]
    return T.create_transaction(body, kd["private_key"], P.MIN_TX_FEE)


def fund(kd, with_pk=True, balance=10 ** 12):
    create_account(kd["address"], balance=balance)
    if with_pk:
        kv_ops.account_set_field(kd["address"], "public_key", kd["public_key"])


PAYEE = generate_keydict()["address"]
OWNER = generate_keydict(); fund(OWNER)
canon = transfer(OWNER)
sig = canon["signature"]
spaced = " ".join(sig[i:i + 2] for i in range(0, len(sig), 2))
VARIANTS = {
    "an UPPERCASE signature": dict(canon, signature=sig.upper()),
    "a mixed-case signature": dict(canon, signature=sig[:100].upper() + sig[100:]),
    "a signature with spaces between its bytes": dict(canon, signature=spaced),
    "a signature wrapped in whitespace": dict(canon, signature=f" \n{sig}\t"),
}
# (re-casing the KEY of an account that already published one was refused before the gate too — key_bound compares the
#  stored string — so the key variant that matters is the FIRST transaction's, below)
recased_pk = dict(canon, public_key=OWNER["public_key"][:42] + OWNER["public_key"][42:].upper())
check("a re-cased key of an established account was already refused by key_bound",
      "not the key this account has on chain" in (verdict(recased_pk, G - 1) or ""), verdict(recased_pk, G - 1))

# 1. THE FINDING, below the gate ---------------------------------------------------------------------------------------
check("the honest transfer validates below the gate and at it", verdict(canon, G - 1) is None and verdict(canon, G) is None,
      (verdict(canon, G - 1), verdict(canon, G)))
for what, v in VARIANTS.items():
    check(f"THE FINDING: {what} keeps the txid", T.validate_txid(v, logger) and v["txid"] == canon["txid"])
    check(f"THE FINDING: {what} still validates below the gate (replay unchanged)", verdict(v, G - 1) is None,
          verdict(v, G - 1))
    check(f"THE FINDING: {what} changes the block hash of the same tx set", block_hash([v]) != block_hash([canon]))
    check(f"THE FINDING: {what} changes the upcoming-block hash, which the txid reconcile cannot heal",
          upcoming_hash([v]) != upcoming_hash([canon]))
check("THE FINDING: dedup by txid keeps whichever copy arrived first",
      T.sort_transaction_pool([VARIANTS["an UPPERCASE signature"], canon])[0]["signature"] == sig.upper())

# the lockout: a relayer re-cases the key on a never-sent account's FIRST tx; PUBKEY-ONCE stores it verbatim
FRESH = generate_keydict(); fund(FRESH, with_pk=False)
first = transfer(FRESH, max_block=G - 1)
first_recased = dict(first, public_key=FRESH["public_key"][:42] + FRESH["public_key"][42:].upper())
check("THE FINDING: a re-cased key on a first transaction validates below the gate", verdict(first_recased, G - 1) is None,
      verdict(first_recased, G - 1))
with kv_ops.write_txn():
    T.index_transactions({"block_number": G - 1}, [first_recased], logger)
stored = kv_ops.get_account(FRESH["address"]).get("public_key")
check("THE FINDING: PUBKEY-ONCE stored the re-cased spelling verbatim", stored == first_recased["public_key"], (stored or "")[:60])
later = transfer(FRESH, max_block=G - 1)
check("THE FINDING: the owner's own canonical-key transaction is then refused (account locked out)",
      "not the key this account has on chain" in (verdict(later, G - 1) or ""), verdict(later, G - 1))

# 2. FROM THE GATE ----------------------------------------------------------------------------------------------------
for what, v in VARIANTS.items():
    check(f"from the gate {what} is refused", "lowercase hex" in (verdict(v, G) or ""), verdict(v, G))
check("from the gate a re-cased key is refused by its shape", "lowercase hex" in (verdict(recased_pk, G) or ""),
      verdict(recased_pk, G))
check("from the gate the re-cased first-tx key is refused, so it can never be stored",
      "lowercase hex" in (verdict(dict(first_recased, max_block=G), G) or ""))
for bad in (None, ""):
    v = dict(canon, public_key=bad)
    check(f"from the gate a public_key of {bad!r} is refused (it re-encoded an omitted key)",
          "lowercase hex" in (verdict(v, G) or ""), verdict(v, G))
    check(f"...and below the gate public_key {bad!r} still validates (replay unchanged)", verdict(v, G - 1) is None,
          verdict(v, G - 1))
check("from the gate a truncated signature is refused by its shape", "lowercase hex" in (verdict(dict(canon, signature=sig[:-2]), G) or ""))
omitted = transfer(OWNER, carry_pk=False)
check("PUBKEY-ONCE: omitting the key the account published still validates at the gate", verdict(omitted, G) is None,
      verdict(omitted, G))

# entry lists: the auth path (a legacy account may sign with a one-entry list) and multisig
listed = T.sign_entries({k: v for k, v in transfer(OWNER).items() if k not in ("txid", "signature")}, [OWNER])
check("an honest one-entry list validates at the gate", verdict(listed, G) is None, verdict(listed, G))
e0 = listed["signature"][0]
ENTRY_VARIANTS = {
    "an UPPERCASE entry signature": {"public_key": e0["public_key"], "signature": e0["signature"].upper()},
    "an entry signature with whitespace": {"public_key": e0["public_key"], "signature": e0["signature"] + "\n"},
    "an UPPERCASE entry key": {"public_key": e0["public_key"].upper(), "signature": e0["signature"]},
    "an entry with an extra key": {"public_key": e0["public_key"], "signature": e0["signature"], "note": "x"},
    "an entry with a null key": {"public_key": None, "signature": e0["signature"]},
}
for what, e in ENTRY_VARIANTS.items():
    v = dict(listed, signature=[e])
    check(f"THE FINDING: {what} keeps the txid", T.validate_txid(v, logger))
    below = verdict(v, G - 1)
    # the auth path already required a lowercase 2624-hex key (auth_ops._is_hex), so only the other variants were open
    if "entry key" not in what:
        check(f"THE FINDING: {what} validates below the gate", below is None, below)
    check(f"from the gate {what} is refused", verdict(v, G) is not None and "signature entry" in verdict(v, G), verdict(v, G))

# the takeover (found while fixing this, reproduced): with an entry list nothing verifies a TOP-LEVEL public_key, yet
# PUBKEY-ONCE stored it for a never-sent sender and the implicit auth config then authorizes exactly that key
VICTIM, THIEF = generate_keydict(), generate_keydict(); fund(VICTIM, with_pk=False)


def listed_transfer(kd_sender_addr, signer, amount, h):
    body = {"sender": kd_sender_addr, "recipient": PAYEE, "amount": amount, "timestamp": 1, "data": "",
            "nonce": secrets.token_hex(4), "max_block": h, "chain_id": P.CHAIN_ID, "fee": P.MIN_TX_FEE}
    return T.sign_entries(body, [signer])


v_first = listed_transfer(VICTIM["address"], VICTIM, 1000, G - 1)
v_injected = dict(v_first, public_key=THIEF["public_key"])
check("THE TAKEOVER: a relayer's key added to a list-signed first tx keeps the txid and validates below the gate",
      T.validate_txid(v_injected, logger) and verdict(v_injected, G - 1) is None, verdict(v_injected, G - 1))
with kv_ops.write_txn():
    T.index_transactions({"block_number": G - 1}, [v_injected], logger)
check("THE TAKEOVER: PUBKEY-ONCE stored the relayer's key as the victim's",
      kv_ops.get_account(VICTIM["address"]).get("public_key") == THIEF["public_key"])
theft = listed_transfer(VICTIM["address"], THIEF, 10 ** 11, G - 1)
check("THE TAKEOVER: the relayer then spends from the victim's account below the gate", verdict(theft, G - 1) is None,
      verdict(theft, G - 1))
V3 = generate_keydict(); fund(V3, with_pk=False)                              # a fresh never-sent victim at the gate
v3_injected = dict(listed_transfer(V3["address"], V3, 1000, G), public_key=THIEF["public_key"])
check("from the gate a top-level public_key beside an entry list is refused, so the relayer's key is never stored",
      "no top-level public_key" in (verdict(v3_injected, G) or ""), verdict(v3_injected, G))
V2 = generate_keydict(); fund(V2, with_pk=False)
check("an honest list-signed first tx validates at the gate", verdict(listed_transfer(V2["address"], V2, 1000, G), G) is None,
      verdict(listed_transfer(V2["address"], V2, 1000, G), G))

K1, K2, K3 = generate_keydict(), generate_keydict(), generate_keydict()
MEMBERS = sorted([K1["address"], K2["address"], K3["address"]])
create_account(multisig_address(2, MEMBERS), balance=10 ** 12)
msig = draft_multisig_spend(2, MEMBERS, PAYEE, 1000, P.MIN_TX_FEE * 3, G)
for kd in (K1, K2, K3):
    add_member_signature(msig, kd["private_key"])


def origin_ok(tx, h):
    """validate_origin's verdict alone. A multisig SPEND fails validate_transaction's sender-address check on this tree
    before and after this change (tests/test_multisig.py t02/t10 fail at 3c5a88ac: 'Invalid sender msig…'), so the
    multisig witnesses are judged where they are verified."""
    try:
        return bool(T.validate_origin(dict(tx), h))
    except Exception:
        return False


check("an honest 3-signature multisig passes validate_origin and the witness rule at the gate",
      origin_ok(msig, G) and "signature entry" not in (verdict(msig, G) or ""), verdict(msig, G))
e_m = msig["signature"][0]
M_VARIANTS = {
    "an UPPERCASE multisig entry signature": dict(e_m, signature=e_m["signature"].upper()),
    # the tail past the address body: format 1 derives the member from the first 42 chars, format 2 lowercases the key
    "a multisig entry key with a re-cased tail": dict(e_m, public_key=e_m["public_key"][:42] + e_m["public_key"][42:].upper()),
}
for what, e in M_VARIANTS.items():
    v = dict(msig, signature=[e] + msig["signature"][1:])
    check(f"THE FINDING: {what} keeps the txid and still verifies below the gate",
          T.validate_txid(v, logger) and origin_ok(v, G - 1))
    check(f"from the gate {what} is refused", "signature entry" in (verdict(v, G) or ""), verdict(v, G))

# 3. KNOWN OPEN at the gate (no encoding rule can close these; see the docstring) -----------------------------------
resigned = dict(canon, signature=sign(OWNER["private_key"], unhex(canon["txid"])))
check("KNOWN OPEN: the signer's second signature over the same txid validates and changes the block hash",
      resigned["signature"] != sig and verdict(resigned, G) is None and block_hash([resigned]) != block_hash([canon]))
stripped = {k: v for k, v in canon.items() if k != "public_key"}
check("KNOWN OPEN: a relayer can strip a key the account already published",
      verdict(stripped, G) is None and block_hash([stripped]) != block_hash([canon]))
reordered = dict(msig, signature=list(reversed(msig["signature"])))
check("KNOWN OPEN: a multisig entry list can be reordered",
      origin_ok(reordered, G) and "signature entry" not in (verdict(reordered, G) or ""))
dropped = dict(msig, signature=msig["signature"][:2])
check("KNOWN OPEN: a surplus multisig entry can be dropped",
      origin_ok(dropped, G) and "signature entry" not in (verdict(dropped, G) or ""))
bare = dict(listed, signature=[{"signature": e0["signature"]}])
check("KNOWN OPEN: a sole authenticator's entry key can be stripped", verdict(bare, G) is None, verdict(bare, G))

# 4. every in-tree signer emits the canonical spelling ------------------------------------------------------------------
node_txs = {
    "create_transaction": canon,
    "construct_attestation_tx": T.construct_attestation_tx(OWNER, 3, "ab" * 32, G),
    "construct_unbond_tx": T.construct_unbond_tx(OWNER, 1, G),
    "construct_bond_tx": T.construct_bond_tx(OWNER, 1, P.MIN_TX_FEE, G),
    "construct_msgkey_tx": T.construct_msgkey_tx(OWNER, "aa" * 1184, G),
    "sign_entries": listed,
    "construct_auth_tx": T.construct_auth_tx(OWNER["address"], [OWNER], {"op": "cancel"}, P.MIN_TX_FEE, G),
    "multisig add_member_signature": msig,
}
for name, tx in node_txs.items():
    try:
        T.excluded_witness_check(tx, G); ok, err = True, ""
    except AssertionError as e:
        ok, err = False, str(e)
    check(f"the node's {name} emits canonical witnesses", ok, err)
check("signatures.sign and generate_keydict emit exact-length lowercase hex",
      T._canonical_hex(sig, P.MLDSA44_SIG_HEX) and T._canonical_hex(OWNER["public_key"], P.MLDSA44_PUBKEY_HEX))

node = shutil.which("node")
if node:
    seed = secrets.token_hex(32)          # a throwaway identity this test creates for itself
    probe = f"""
import * as N from '{os.path.join(ROOT, "static", "nadotx.js")}';
const w = N.keyFromSeed('{seed}');
console.log(JSON.stringify(N.buildBlobTx(w, {{op: "noop"}}, {G}, {P.MIN_TX_FEE}, '{P.CHAIN_ID}')));
"""
    f = os.path.join(os.environ["HOME"], "probe.mjs"); open(f, "w").write(probe)
    r = subprocess.run([node, f], capture_output=True, text=True, timeout=120, cwd=ROOT)
    try:
        btx = json.loads(r.stdout.strip().splitlines()[-1])
        T.excluded_witness_check(btx, G)
        ok = verify(btx["signature"], btx["public_key"], unhex(btx["txid"])) and T.validate_txid(btx, logger)
        err = ""
    except Exception as e:
        ok, err = False, f"{e} {r.stderr[-300:]}"
    check("the browser signer (static/nadotx.js finalizeTx) emits canonical witnesses that verify", ok, err)
else:
    print("SKIP  node is not installed: the browser signer was not probed")

wallet = open(os.path.join(ROOT, "static", "interface.js")).read()
check("the wallet re-cases no key or signature hex",
      not re.search(r"(sig|pub|key|hex)\w*\)?\.toUpperCase\(", wallet, re.I))
check("every wallet signing site hex-encodes with bytesToHex",
      len(re.findall(r"signature = bytesToHex\(sig\)|sig = bytesToHex\(s\)|signature: bytesToHex\(sig\)", wallet)) >= 4)
rs = open(os.path.join(ROOT, "apps", "nado-tpm-attest", "src", "tx.rs")).read()
check("the TPM helper's hex encoder is lowercase {:02x}",
      re.search(r'pub fn hex\(bytes: &\[u8\]\) -> String \{\s*bytes\.iter\(\)\.map\(\|b\| format!\("\{:02x\}", b\)\)', rs) is not None)

# 5. carried keys are canonical (a carried non-canonical key could never be matched by a canonical tx's key) --------
carried = []
for fn in ("genesis_alloc.dat", "genesis_carry.dat", "genesis_open.dat"):
    carried += re.findall(r'"public_key":\s*"([^"]*)"', open(os.path.join(ROOT, "genesis_data", fn)).read())
check("every public_key the genesis carries is canonical", all(T._canonical_hex(k, P.MLDSA44_PUBKEY_HEX) for k in carried),
      [k[:20] for k in carried if not T._canonical_hex(k, P.MLDSA44_PUBKEY_HEX)][:3])

# 6. the gate itself -----------------------------------------------------------------------------------------------------
check("the rule is reroll-only: dormant on gen 27, from block 1 on the next chain",
      LIVE_GATE == ((1 << 62) if P.CHAIN_GENERATION == 27 else 1))

print("ALL PASS — a transaction has one byte string" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
