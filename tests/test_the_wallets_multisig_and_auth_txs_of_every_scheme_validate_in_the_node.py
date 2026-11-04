"""The wallet's multisig and auth transactions of every scheme validate in the node (protocol.SIG_SCHEME_KEYS_HEIGHT,
doc/signature-schemes.md; operator 2026-11-04: "extend it to multisig and auth").

The wallet's OWN code is run — static/interface.js's msigTrySignLocal, msigEntryAddress, schemeSignEntry, authKey,
authKeyIn, authPop, authBuildTx, authProtectedCfg and authSignerKeypair, extracted and evaluated under node with the
vendored bundle (static/vendor/nado-crypto.js) the browser loads — and what it builds goes through the node's
validate_transaction and auth_ops.apply_auth_tx. Pins:
  - an SLH-DSA member and an ML-DSA-44 member co-sign a multisig proposal in the wallet; the entries name their schemes,
    msigEntryAddress reads each back as its member, and the node accepts the spend from the gate;
  - below the gate the wallet's SLH-DSA member does not sign (no entry a node would refuse);
  - an SLH-DSA account protects itself in the wallet (hot + recovery, both [alg, key]); the node accepts it and installs
    it; the wallet's signer child of the account's scheme then rotates with hot + recovery, and the node accepts that;
  - an ML-DSA-44 account's signer child keeps exactly the seed it always had; an SLH-DSA one's is domain-separated by
    the scheme; authKeyIn finds a key only under its own scheme.

Run: python3 tests/test_the_wallets_multisig_and_auth_txs_of_every_scheme_validate_in_the_node.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-walletsigkeys-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
os.environ["NADO_AUTH_FORCE"] = "1"
import copy, json, logging, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
from genesis import create_indexers
create_indexers()
import protocol as P
from ops import kv_ops, auth_ops as A, transaction_ops as T
from ops.account_ops import create_account
from ops.multisig_ops import multisig_address, draft_multisig_spend
from hashing import blake2b_hash
import signatures as S

logger = logging.getLogger("walletsigkeys"); logger.addHandler(logging.NullHandler())
fails = 0
POST = P.SIG_SCHEME_KEYS_HEIGHT
PRE = POST - 1
SLH = "slhdsa128s"
SEEDS = {"msig_slh": "a1" * 32, "msig_44": "b2" * 32, "msig_65": "c3" * 32, "master": "d4" * 32, "rec": "e5" * 32}


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


SRC = open(os.path.join(ROOT, "static", "interface.js"), encoding="utf-8").read()


def fn_src(name):
    i = SRC.index("function " + name + "(")
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


# ---- the node's side of the scenario ----------------------------------------------------------------------------------
MS = S.from_private_key(SEEDS["msig_slh"], SLH)
MM = S.from_private_key(SEEDS["msig_44"])
MX = S.from_private_key(SEEDS["msig_65"], "mldsa65")
members = sorted([MS["address"], MM["address"], MX["address"]])
create_account(multisig_address(2, members), balance=10 ** 12)
PAYEE = S.generate_keydict()["address"]
proposal = draft_multisig_spend(2, members, PAYEE, 1000, P.MIN_TX_FEE * 6, POST + 10)
ACCT_SEED = blake2b_hash(["hd-account-v1", SEEDS["master"], 1, SLH], size=32)      # the wallet's child #1 of SLH-DSA
SACC = S.from_private_key(ACCT_SEED, SLH)
create_account(SACC["address"], balance=10 ** 12)
kv_ops.account_set_field(SACC["address"], "public_key", SACC["public_key"])

helpers = "\n".join([
    fn_src("jsonEscapeAscii"), fn_src("canonicalize"), fn_src("canonicalBytes"), fn_src("blake2bHash"),
    fn_src("makeAddress"), const_line("const SIG_ML44 ="), const_line("const SIG_DST_SLH ="), const_line("const SIG_NAMES ="),
    fn_src("schemeLib"), fn_src("schemeKeygen"), fn_src("schemeSign"), fn_src("schemeVerify"), fn_src("schemeOf"),
    fn_src("keypairFromPriv"), fn_src("accountChildSeed"), fn_src("accountKeypair"), fn_src("createTxid"),
    const_line("const DOMAIN_HD_AUTH ="), fn_src("authAlg"), fn_src("authSignerKeypair"), fn_src("authKey"),
    fn_src("authKeyIn"), fn_src("schemeKeysLive"), fn_src("schemeSignEntry"), fn_src("authPop"), fn_src("authBuildTx"),
    fn_src("authProtectedCfg"), fn_src("msigEntryAddress"), fn_src("msigTrySignLocal"),
    const_line("const ADDR_RE ="), const_line("const MSIG_RE ="), fn_src("validateAddress"), fn_src("validatePayee"),
])
js = r"""
const C = await import(process.argv[2]);
const { blake2b, bytesToHex, hexToBytes, ml_dsa44, ml_dsa65, ml_dsa87, slh_dsa_sha2_128s, shake256 } = C;
const IN = JSON.parse(process.argv[3]);
const P = IN.P;
const ADDR_PREFIX = P.ADDRESS_PREFIX, ADDR_BODY = P.ADDRESS_BODY, ADDR_CK = P.ADDRESS_CHECKSUM, CHAIN_ID = P.CHAIN_ID;
const MSIG_PREFIX = P.MSIG_PREFIX;
const DOMAIN_ADDRESS_V2 = P.DOMAIN_ADDRESS_V2, MIN_TX_FEE = P.MIN_TX_FEE, DOMAIN_HD_ACCOUNT = "hd-account-v1";
const AUTH_FEE_PER_ENTRY = MIN_TX_FEE;
const _enc = new TextEncoder();
const i18 = (k, d, v) => String(d).replace(/\{(\w+)\}/g, (_, n) => (v && n in v ? v[n] : ""));
const state = { latest: IN.post, activeIdx: 1, wallet: null };
const hdAlg = (i) => (i === 1 ? "slhdsa128s" : undefined);            // the wallet's account #1 signs with SLH-DSA
const nowSeconds = () => 1, randNonce = () => "abcdefgh", guardFrom = (h) => h;
const log = () => {};
""" + helpers + r"""
const out = {};
// ---- multisig: two members of two schemes co-sign the node's proposal ----
const tx = IN.proposal;
const slhM = keypairFromPriv(IN.seeds.msig_slh, "slhdsa128s"), m44 = keypairFromPriv(IN.seeds.msig_44);
state.latest = IN.pre; state.wallet = slhM;
const pre = JSON.parse(JSON.stringify(tx));
out.preSigned = msigTrySignLocal(pre);
state.latest = IN.post;
out.slhSigned = msigTrySignLocal(tx);
state.wallet = m44; out.m44Signed = msigTrySignLocal(tx);
state.wallet = slhM; out.slhTwice = msigTrySignLocal(tx);
out.msig = tx;
out.payee = { msig: validatePayee(IN.msigAddr), msigAsAddress: validateAddress(IN.msigAddr), plain: validatePayee(IN.plainAddr),
              badSum: validatePayee(IN.msigAddr.slice(0, -1) + (IN.msigAddr.endsWith("0") ? "1" : "0")) };
out.entryAddrs = tx.signature.map(msigEntryAddress);
// ---- auth: the SLH-DSA account #1 protects itself, then rotates with hot + recovery ----
const hot = accountKeypair(IN.seeds.master, 1), rec = keypairFromPriv(IN.seeds.rec, authAlg());
out.hot = { address: hot.address, pk: hot.publicKey, alg: hot.alg };
const cfg1 = authProtectedCfg(1, hot, rec);
out.protect = authBuildTx(hot.address, [hot], { op: "set", cfg: cfg1, pop: { [rec.publicKey]: authPop(hot.address, cfg1, rec) } }, IN.post);
const nk = authSignerKeypair(IN.seeds.master, 1, 1);
out.nk = { pk: nk.publicKey, alg: nk.alg, privateKey: nk.privateKey };
const cfg2 = { v: 2, keys: [authKey(nk), ...cfg1.keys.slice(1)], sign: cfg1.sign, reconf: cfg1.reconf };
out.rotate = authBuildTx(hot.address, [hot, rec], { op: "set", cfg: cfg2, pop: { [nk.publicKey]: authPop(hot.address, cfg2, nk) } }, IN.post);
out.inOwn = authKeyIn(cfg1.keys, rec);
out.inOther = authKeyIn(cfg1.keys, { publicKey: rec.publicKey });
state.activeIdx = 0;
out.ml44Signer = authSignerKeypair(IN.seeds.master, 0, 2).privateKey;
// a file, not stdout: process.exit drops a pipe's unflushed tail, and three SLH-DSA signatures are ~50 KB
(await import("node:fs")).writeFileSync(process.argv[4], JSON.stringify(out));
process.exit(0);
"""
node = shutil.which("node")
if not node:
    print("SKIP  node is not installed")
    sys.exit(0)
script = os.path.join(os.environ["HOME"], "walletsigkeys.mjs")
open(script, "w").write(js)
pexp = {k: getattr(P, k) for k in ("ADDRESS_PREFIX", "ADDRESS_BODY", "ADDRESS_CHECKSUM", "DOMAIN_ADDRESS_V2", "MIN_TX_FEE",
                                   "SIG_SCHEME_SIZES", "SIG_SCHEMES_OFFERED", "SIG_SCHEME_KEYS_HEIGHT", "CHAIN_ID", "MSIG_PREFIX")}
inp = {"P": pexp, "seeds": SEEDS, "proposal": proposal, "pre": PRE, "post": POST,
       "msigAddr": multisig_address(2, members), "plainAddr": PAYEE}
res = os.path.join(os.environ["HOME"], "walletsigkeys.json")
r = subprocess.run([node, script, os.path.join(ROOT, "static", "vendor", "nado-crypto.js"), json.dumps(inp), res],
                   capture_output=True, text=True, timeout=900, cwd=ROOT)
out = json.load(open(res)) if r.returncode == 0 and os.path.exists(res) else {}
check("the wallet's multisig and auth code runs under node with the vendored bundle", bool(out), r.stderr[-1500:])
if out:
    # multisig
    check("below the gate the wallet's SLH-DSA member does not sign", out["preSigned"] is False)
    check("from the gate both members sign in the wallet, and a second signature is not added",
          out["slhSigned"] and out["m44Signed"] and out["slhTwice"] is False)
    check("the entries name their schemes (SLH-DSA, then none for ML-DSA-44)",
          [e.get("alg") for e in out["msig"]["signature"]] == [SLH, None], [e.get("alg") for e in out["msig"]["signature"]])
    check("msigEntryAddress reads each entry back as its member", out["entryAddrs"] == [MS["address"], MM["address"]],
          out["entryAddrs"])
    v = verdict(out["msig"], POST)
    check("the node accepts the wallet's mixed-scheme multisig spend from the gate", v is None, v)
    v = verdict(out["msig"], PRE)
    check("...and refuses it below the gate", v is not None, v)
    # Send pays a multisig account (validatePayee); assets, allowances and members keep validateAddress
    check("Send accepts the shared account as a payee, and a plain address still", out["payee"]["msig"] and out["payee"]["plain"], out["payee"])
    check("...but validateAddress (assets, allowances, multisig members) still refuses it, and a bad checksum is refused",
          out["payee"]["msigAsAddress"] is False and out["payee"]["badSum"] is False, out["payee"])
    # auth
    check("the wallet's account #1 is the node's SLH-DSA account", out["hot"]["address"] == SACC["address"] and out["hot"]["alg"] == SLH)
    p = out["protect"]
    check("the protect config names both keys [alg, key]", all(isinstance(k, list) and k[0] == SLH for k in p["data"]["cfg"]["keys"]),
          p["data"]["cfg"]["keys"])
    check("the protect tx pays the SLH-DSA entry's floor (3)", p["fee"] == 3 * P.MIN_TX_FEE, p["fee"])
    v = verdict(p, POST)
    check("the node accepts the wallet's SLH-DSA protect from the gate", v is None, v)
    v = verdict(p, PRE)
    check("...and refuses it below the gate", v is not None, v)
    T.validate_transaction(copy.deepcopy(p), logger, block_height=POST)
    A.apply_auth_tx(p, POST, logger)
    rt = out["rotate"]
    check("the rotation is signed by hot + recovery, both SLH-DSA, paying 3 + 3", [e.get("alg") for e in rt["signature"]] == [SLH, SLH]
          and rt["fee"] == 6 * P.MIN_TX_FEE, ([e.get("alg") for e in rt["signature"]], rt["fee"]))
    v = verdict(rt, POST)
    check("the node accepts the wallet's SLH-DSA rotation (the reconfig policy)", v is None, v)
    check("the wallet's SLH-DSA signer child is the scheme-separated seed",
          out["nk"]["alg"] == SLH and out["nk"]["privateKey"] == blake2b_hash(["hd-auth-signer-v1", SEEDS["master"], 1, 1, SLH], size=32))
    check("an ML-DSA-44 account's signer child keeps the seed it always had",
          out["ml44Signer"] == blake2b_hash(["hd-auth-signer-v1", SEEDS["master"], 0, 2], size=32))
    check("authKeyIn finds a key only under its own scheme", out["inOwn"] is True and out["inOther"] is False)

print("\nALL PASS — the wallet's multisig and auth transactions of every scheme validate in the node" if not fails
      else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
