"""Every signature scheme derives one key, one address and one valid transaction in every stack (doc/signature-schemes.md).

An address is a hash of the public key, so the browser and the node must derive the SAME key from the same 32-byte seed
for every scheme — or a user's account moves between the wallet and the chain. And the wallet's transaction must be one
the node accepts, signed in the convention the node verifies (FIPS 204/205 INTERNAL mode, no context).

The wallet's own code is RUN: static/interface.js's scheme layer (schemeKeygen/Sign/Verify, makeAddress, keypairFromPriv,
accountChildSeed, schemeFee, finalizeTransaction) extracted and evaluated under node with the vendored bundle
(static/vendor/nado-crypto.js) — the files a browser loads. The node side is signatures.py over native/pqsig, with the
generation 29's rules (SIG_SCHEMES_HEIGHT, inlined in G9: the rule holds from block 1). Pins:
  - for ML-DSA-44/65/87 and SLH-DSA-128s, the browser's public key and address for a seed equal the node's, and the
    known-answer digests signatures.py refuses a library without (_SCHEME_KAT) hold in the browser too;
  - a wallet-built transfer of every scheme validates in the node (tagged, fee lifted to the floor; ML-DSA-44 untagged),
    and a node signature verifies in the browser;
  - the wallet refuses to build a kind that is ML-DSA-44 only (register) for an account of another scheme;
  - noble's SLH-DSA keygen ZEROES the secret two thirds of its seed buffer (why schemeKeygen passes a copy — a reused buffer would derive a
    different key next time);
  - a derived account's seed is domain-separated by its scheme, and an ML-DSA-44 child keeps the seed it always had.

Run: python3 tests/test_every_signature_scheme_derives_one_key_in_every_stack.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-sigstacks-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import hashlib, json, logging, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
from genesis import create_indexers
create_indexers()
import protocol as P
from ops import transaction_ops as T
from ops.account_ops import create_account
from hashing import blake2b_hash
import signatures as S

logger = logging.getLogger("sigstacks"); logger.addHandler(logging.NullHandler())
fails = 0
G = 29100
SCHEMES = ("mldsa44", "mldsa65", "mldsa87", "slhdsa128s")
SEED = "42" * 32


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


SRC = open(os.path.join(ROOT, "static", "interface.js"), encoding="utf-8").read()


def fn_src(name, is_async=False):
    i = SRC.index(("async function " if is_async else "function ") + name + "(")
    j = SRC.index("{", SRC.index(")", i))
    depth = 0
    while True:
        c = SRC[j]
        depth += c == "{"
        depth -= c == "}"
        if c == "}" and depth == 0:
            return SRC[i:j + 1]
        j += 1


def const_line(prefix):
    i = SRC.index(prefix)
    return SRC[i:SRC.index("\n", i)]


PAYEE = S.generate_keydict()["address"]
node_side = {}
for a in SCHEMES:
    alg = None if a == "mldsa44" else a
    kd = S.from_private_key(SEED, alg)
    node_side[a] = kd
create_account(node_side["mldsa65"]["address"], balance=10 ** 12)
node_sig = S.sign(SEED, b"from-the-node", "slhdsa128s")
draft = lambda kd: {"sender": kd["address"], "recipient": PAYEE, "amount": 1000, "timestamp": 1, "data": "",
                    "nonce": "abcd", "max_block": G, "chain_id": P.CHAIN_ID, "public_key": kd["public_key"]}
for a in SCHEMES:
    create_account(node_side[a]["address"], balance=10 ** 12) if a != "mldsa65" else None

helpers = "\n".join([
    fn_src("jsonEscapeAscii"), fn_src("canonicalize"), fn_src("canonicalBytes"), fn_src("blake2bHash"),
    fn_src("makeAddress"), const_line("const SIG_ML44 ="), const_line("const SIG_DST_SLH ="), const_line("const SIG_NAMES ="),
    fn_src("schemeLib"), fn_src("schemeKeygen"), fn_src("schemeSign"), fn_src("schemeVerify"), fn_src("schemeFee"),
    fn_src("keypairFromPriv"), fn_src("accountChildSeed"), fn_src("createTxid"), fn_src("finalizeTransaction"),
])
helpers = helpers + "\nconst __CUR__ = " + json.dumps(fn_src("currentFeeRaw", True)) + ";"
js = r"""
const C = await import(process.argv[2]);
const { blake2b, bytesToHex, hexToBytes, ml_dsa44, ml_dsa65, ml_dsa87, slh_dsa_sha2_128s, shake256 } = C;
const IN = JSON.parse(process.argv[3]);
const P = IN.P;
const ADDR_PREFIX = P.ADDRESS_PREFIX, ADDR_BODY = P.ADDRESS_BODY, ADDR_CK = P.ADDRESS_CHECKSUM;
const DOMAIN_ADDRESS_V2 = P.DOMAIN_ADDRESS_V2, MIN_TX_FEE = P.MIN_TX_FEE, DOMAIN_HD_ACCOUNT = "hd-account-v1";
const _enc = new TextEncoder();
const i18 = (k, d, v) => String(d).replace(/\{(\w+)\}/g, (_, n) => (v && n in v ? v[n] : ""));
""" + helpers + r"""
const out = { keys: {}, kat: {}, tx: {} };
for (const a of IN.schemes) {
  const alg = a === "mldsa44" ? undefined : a;
  const kp = keypairFromPriv(IN.seed, alg);
  out.keys[a] = { pk: kp.publicKey, address: kp.address, alg: kp.alg || null };
  out.kat[a] = bytesToHex(blake2b(hexToBytes(kp.publicKey), { dkLen: 16 }));
  out.tx[a] = finalizeTransaction(IN.drafts[a], kp, MIN_TX_FEE);
}
out.nodeSigOk = schemeVerify("slhdsa128s", hexToBytes(out.keys.slhdsa128s.pk), _enc.encode("from-the-node"), hexToBytes(IN.nodeSig));
try { finalizeTransaction({ ...IN.drafts.mldsa65, recipient: "register" }, keypairFromPriv(IN.seed, "mldsa65"), 0); out.registerBuilt = true; }
catch (e) { out.registerBuilt = false; out.registerErr = e.message; }
const s48 = new Uint8Array(48).fill(5); slh_dsa_sha2_128s.keygen(s48);
out.slhWipesSeed = s48.subarray(0, 32).every((b) => b === 0) && s48[47] === 5;   // SK.seed and SK.prf zeroed; PK.seed kept
// the fee the wallet SHOWS and checks is the fee it signs (currentFeeRaw, read by Send's confirm and the fee label)
{
  const fee = (w) => new Function("state", "getRecommendedFee", "schemeFee", "schemeOf",
    __CUR__ + "\nreturn currentFeeRaw;")({ wallet: w, recommendedFee: MIN_TX_FEE }, async () => MIN_TX_FEE, schemeFee,
    (x) => (x && x.alg) || "mldsa44")();
  out.feeShown = { slh: await fee({ alg: "slhdsa128s" }), ml44: await fee({}) };
}
out.child44 = accountChildSeed(IN.seed, 1);
out.child65 = accountChildSeed(IN.seed, 1, "mldsa65");
console.log(JSON.stringify(out));
process.exit(0);
"""
node = shutil.which("node")
if not node:
    print("SKIP  node is not installed")
    sys.exit(0)
script = os.path.join(os.environ["HOME"], "stacks.mjs")
open(script, "w").write(js)
pexp = {k: getattr(P, k) for k in ("ADDRESS_PREFIX", "ADDRESS_BODY", "ADDRESS_CHECKSUM", "DOMAIN_ADDRESS_V2", "MIN_TX_FEE",
                                   "SIG_SCHEME_SIZES", "SIG_ML44_ONLY_RECIPIENTS")}
inp = {"seed": SEED, "schemes": list(SCHEMES), "P": pexp, "nodeSig": node_sig,
       "drafts": {a: draft(node_side[a]) for a in SCHEMES}}
r = subprocess.run([node, script, os.path.join(ROOT, "static", "vendor", "nado-crypto.js"), json.dumps(inp)],
                   capture_output=True, text=True, timeout=600, cwd=ROOT)
out = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else {}
check("the wallet's scheme layer runs under node with the vendored bundle", bool(out), r.stderr[-1500:])
if out:
    for a in SCHEMES:
        nk = node_side[a]
        check(f"{a}: the browser's public key for the seed equals the node's", out["keys"][a]["pk"] == nk["public_key"])
        check(f"{a}: ...and so does its address (the address commits to the scheme)", out["keys"][a]["address"] == nk["address"],
              (out["keys"][a]["address"], nk["address"]))
        if a != "mldsa44":
            ref = hashlib.blake2b(bytes.fromhex(S.from_private_key("42" * 32, a)["public_key"]), digest_size=16).hexdigest()
            check(f"{a}: the browser holds the known-answer key signatures.py pins", out["kat"][a] == S._SCHEME_KAT[a] == ref,
                  (out["kat"][a], S._SCHEME_KAT[a]))
        tx = out["tx"][a]
        try:
            T.validate_transaction(dict(tx), logger, block_height=G)
            v = None
        except Exception as e:
            v = str(e)
        check(f"{a}: the wallet's transfer validates in the node", v is None, v)
        if a == "mldsa44":
            check("mldsa44: the wallet's transaction carries no alg (every existing transaction unchanged)", "alg" not in tx)
        else:
            check(f"{a}: it names its scheme and pays the scheme's floor",
                  tx.get("alg") == a and tx["fee"] == P.MIN_TX_FEE * P.SIG_SCHEME_SIZES[a][2], (tx.get("alg"), tx.get("fee")))
    check("a node SLH-DSA signature verifies in the browser", out["nodeSigOk"] is True)
    check("the wallet refuses to build a register tx for an ML-DSA-65 account", out["registerBuilt"] is False and
          "ML-DSA-44" in out.get("registerErr", ""), out.get("registerErr"))
    check("the fee Send shows and checks is the fee signed: 3 x MIN_TX_FEE for SLH-DSA, unchanged for ML-DSA-44",
          out["feeShown"] == {"slh": 3 * P.MIN_TX_FEE, "ml44": P.MIN_TX_FEE}, out.get("feeShown"))
    check("noble's SLH-DSA keygen zeroes the secret part of the seed it is given (schemeKeygen must pass a copy)", out["slhWipesSeed"] is True)
    check("an ML-DSA-44 child account keeps the seed it always had",
          out["child44"] == blake2b_hash(["hd-account-v1", SEED, 1], size=32))
    check("a child of another scheme has its own, domain-separated seed",
          out["child65"] == blake2b_hash(["hd-account-v1", SEED, 1, "mldsa65"], size=32) != out["child44"])

print("\nALL PASS — every signature scheme derives one key in every stack" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
