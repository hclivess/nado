"""Each Stwo deposit a wallet makes is owned by a FRESH owner — never the zaddr's — and the wallet can still spend every
one, and recovers them from the chain on a new device (static/interface.js doShield / stwoDepositNsk / noteNskWire /
stwoRecoverDeposits; static/stark/stwo_js.js depositNsk).

Why: tests/test_a_stwo_deposit_does_not_publish_the_owner_behind_the_wallets_zaddr.mjs — a deposit publishes its
owner next to the depositing account, so the old single stable owner tied the zaddr (and every deposit) to the account.
This walks the wallet's OWN code (extracted from interface.js, run in Node with a throwaway key generated here, never a
real one) against a real ExecState and the shipped WASM prover. Pins:
  1. two deposits publish two different owners, neither the zaddr's owner, and both land in the Stwo pool;
  2. each deposit note is spent by the wallet — key chosen by its own noteNskWire — with a real proof that the real
     native verifier accepts and the exec layer applies (privately, paying a relay its fee, as the wallet sends);
  3. a wallet restored on a new device (no stored notes) finds both deposits by scanning its own shield
     transactions, recomputes their commitments, marks the spent one spent from the pool's spent set and the other
     spendable, and continues its index past them (no owner is ever reused);
  4. the restore ignores another account's deposits and a deposit the pool never applied.
SKIPs without node or a stable cargo (the verifier).

Run: python3 tests/test_each_stwo_deposit_has_its_own_owner_and_the_wallet_spends_each.py
"""
import os, sys, tempfile, json, secrets, shutil, subprocess
_REAL_HOME = os.path.expanduser("~")
_T = tempfile.mkdtemp(prefix="nado-test-stwo-deposit-owner-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
import atexit; atexit.register(shutil.rmtree, _T, ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tests._stwo_js_build import Env, wallet_prove

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {str(detail)[:600]}"))
    fails += 0 if ok else 1


if not shutil.which("node"):
    print("SKIP  no node"); sys.exit(0)
env = Env(_REAL_HOME)
if not env.have_stable():
    print("SKIP  no stable cargo: the verifier cannot be built here"); sys.exit(0)
so, _s, log = env.build_verifier()
if not so:
    print("FAIL  verifier build", (log or "")[-800:]); sys.exit(1)
os.environ["NADO_STWO_JS_LIB"] = so

import protocol as P
from execnode.state import ExecState
from execnode import shielded_stwo as SP
from ops.address_ops import make_address

# The wallet's own functions, extracted from interface.js and run in Node. `phase` "deposit" runs doShield per amount;
# "spendkeys" answers noteNskWire for each stored note; "recover" runs stwoRecoverDeposits on an empty device.
DRIVER = r"""
import fs from "fs";
import crypto from "crypto";
const c = JSON.parse(fs.readFileSync(0, "utf8"));
const SRC = fs.readFileSync(c.iface, "utf8");
const stwo = await import(c.stwo);
function fnSrc(name, isAsync = false) {
  const i = SRC.indexOf((isAsync ? "async function " : "function ") + name + "(");
  if (i === -1) throw new Error(name + " not found");
  let depth = 0, j = SRC.indexOf("{", SRC.indexOf(")", i));
  for (; j < SRC.length; j++) { if (SRC[j] === "{") depth++; else if (SRC[j] === "}" && --depth === 0) break; }
  return SRC.slice(i, j + 1);
}
const constSrc = (n) => SRC.match(new RegExp("const " + n + " = [^;]+;"))[0];
let stored = c.stored || [];
const published = [], logs = [], ls = Object.assign({}, c.ls || {});
const env = {
  state: { wallet: { address: c.address, privateKey: c.key, publicKey: "pk" } },
  _stwo: stwo,
  blake2bHash: (parts) => crypto.createHash("blake2b512").update(JSON.stringify(parts)).digest("hex").slice(0, 64),
  shieldStwo: () => true, shieldWide: () => false, ensureShielded: () => {}, refreshShieldRules: async () => {},
  shieldPaused: () => false, wideDepositClosed: () => false, _shieldTip: 0,
  nadoToRaw: (s) => BigInt(s), rawToNado: (x) => String(x), $: () => ({ value: String(c.amount || "0") }),
  log: (k, m) => logs.push([k, m]), i18: (k, fb, v) => String(fb).replace(/\{(\w+)\}/g, (m, n) => (v && v[n] != null ? String(v[n]) : m)),
  _randField: () => BigInt("0x" + crypto.randomBytes(7).toString("hex")).toString(),
  noteCommit: (v, owner, rho) => stwo.commit(v, owner, rho),
  getLatestBlock: async () => ({ block_number: 100 }), MIN_TX_FEE: 1, nowSeconds: () => 0,
  buildTransferTx: (wallet, kind, amount, fee, target, data) => { published.push({ sender: wallet.address, recipient: kind, amount: amount.toString(), data }); return {}; },
  submitTransaction: async () => ({ data: { result: true } }),
  loadNotes: () => stored.map((n) => ({ ...n })), saveNotes: (ns) => { stored = ns.map((n) => ({ ...n })); },
  setTimeout: () => {}, renderShield: async () => {},
  localStorage: { getItem: (k) => (k in ls ? ls[k] : null), setItem: (k, v) => { ls[k] = String(v); } },
  rpcJSON: async () => ({ ok: true, status: 200, data: { transactions: c.history || [] } }),
  execJSON: async (p) => (p === "/exec/field_leaves" ? { leaves: c.leaves || [], pool: "stwo" } : { nullifiers: c.spent || [] }),
  shieldNskWire: null,
};
const body = [constSrc("ZADDR_STWO"), constSrc("STWO_DEPOSIT_GAP"), fnSrc("shieldNskStwo"), fnSrc("shieldOwner"), fnSrc("ownerStr"),
  fnSrc("cmStr"), fnSrc("shieldAddr"), fnSrc("stwoDepositNsk"), fnSrc("stwoDepositKey"), fnSrc("stwoDepositIndexTake"),
  fnSrc("noteNskWire"), fnSrc("doShield", true), fnSrc("stwoRecoverDeposits", true),
  "shieldNskWire = () => shieldNskStwo();",
  "return { doShield, shieldOwner, noteNskWire, stwoRecoverDeposits, shieldNskStwo };"].join("\n");
const W = new Function(...Object.keys(env), constSrc("DOMAIN_SHIELD_NSK_STWO") + "\n" + body)(...Object.values(env));
const out = { owner: W.shieldOwner() };
if (c.phase === "deposit") { for (const a of c.amounts) { env.$ = () => ({ value: String(a) }); c.amount = a; await W.doShield(); } }
if (c.phase === "spendkeys") out.keys = stored.map((n) => W.noteNskWire(n));
if (c.phase === "recover") out.recovered = await W.stwoRecoverDeposits();
Object.assign(out, { published, stored, ls, logs });
console.log(JSON.stringify(out));
"""


def wallet(phase, **kw):
    case = dict(phase=phase, iface=os.path.join(ROOT, "static", "interface.js"),
                stwo="file://" + os.path.join(ROOT, "static", "stark", "stwo_js.js"), address=ADDR, key=KEY, **kw)
    r = subprocess.run(["node", "--input-type=module", "-e", DRIVER], input=json.dumps(case),
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


KEY = secrets.token_hex(32)                     # a throwaway wallet secret generated for this test, never a real key
ADDR = make_address("ab" * 1312)
RELAY = make_address("cd" * 1312)
GATE = 1000
P.STWO_POOL_HEIGHT = GATE

# ---- 1. two deposits through the wallet's own doShield --------------------------------------------------------------
d = wallet("deposit", amounts=[10 ** 9, 3 * 10 ** 9])
pub, stored, zowner = d["published"], d["stored"], d["owner"]
owners = [p["data"]["owner"] for p in pub]
check("1. two deposits publish two different owners", len(pub) == 2 and owners[0] != owners[1], owners)
check("...neither of them the owner the zaddr encodes", zowner not in owners, (zowner, owners))
st = ExecState(os.path.join(_T, "s.json"))
st.cursor = GATE - 1
st.apply_field_shield(777, SP.owner_of(secrets.token_hex(32)), 5)
for p in pub:
    r = st.apply_field_shield(int(p["amount"]), p["data"]["owner"], int(p["data"]["rho"]))
    check(f"...the deposit of {p['amount']} lands in the Stwo pool", "stwo note" in r, r)
check("...and the wallet's stored notes are exactly those commitments", sorted(n["cm"] for n in stored)
      == sorted(SP.commit(int(p["amount"]), p["data"]["owner"], int(p["data"]["rho"])) for p in pub), stored)

# ---- 2. each spent with the key the wallet's own noteNskWire picks ---------------------------------------------------
keys = wallet("spendkeys", stored=stored)["keys"]
FEE = 100000
for n, nsk in zip(stored, keys):
    check(f"2. note k={n['k']}: the key the wallet picks owns it", SP.commit(int(n["value"]), SP.owner_of(nsk), int(n["rho"])) == n["cm"])
    leaves = list(st.stwo_pool.commitments)
    v = int(n["value"])
    spend = {"nsk": nsk, "vIn": str(v), "rho": str(n["rho"]), "v1": "1000", "o1": SP.owner_of(secrets.token_hex(32)),
             "r1": str(secrets.randbits(64)), "v2": str(v - 1000 - FEE), "o2": zowner, "r2": str(secrets.randbits(64)),
             "unshield": str(FEE), "fee": "0", "dest": RELAY}
    if n is stored[0]:
        b = wallet_prove(spend, leaves, leaves.index(n["cm"]))["bundle"]
        r = st.apply_field_transfer(json.loads(json.dumps(b)))
        check("...spent privately (paying a relay its fee): the real verifier accepts and the exec layer applies", "field-transfer stwo" in r, r)
        spent_nf = b["stark"]["stwo_js"]["nf"]
    else:
        b2 = wallet_prove(spend, leaves, leaves.index(n["cm"]))["bundle"]
        sv = st.stwo_value
        r = st.apply_field_transfer(json.loads(json.dumps(b2)))
        check("...and the second deposit too", "field-transfer stwo" in r and st.stwo_value == sv - FEE, r)
# the restore below runs against a pool where only the FIRST deposit note is spent
st_r = ExecState(os.path.join(_T, "r.json"))
st_r.cursor = GATE - 1
st_r.apply_field_shield(777, SP.owner_of(secrets.token_hex(32)), 5)
for p in pub:
    st_r.apply_field_shield(int(p["amount"]), p["data"]["owner"], int(p["data"]["rho"]))
st_r.stwo_pool.spend(spent_nf)                           # the first deposit note spent, the second not

# ---- 3./4. restore on a new device --------------------------------------------------------------------------------
history = [dict(p, sender=ADDR) for p in pub]
other = {"sender": make_address("ef" * 1312), "recipient": "shield", "amount": "5", "data": dict(pub[0]["data"], owner=SP.owner_of(secrets.token_hex(32)))}
rec = wallet("recover", stored=[], history=history + [other], leaves=list(st_r.stwo_pool.commitments),
             spent=sorted(st_r.stwo_pool.nullifiers))
got = sorted(rec["stored"], key=lambda n: n["k"])
check("3. a restored wallet finds both deposits from its own shield transactions", rec["recovered"] == 2 and len(got) == 2, rec)
check("...with their commitments recomputed and their key indices", [n["cm"] for n in got] == [n["cm"] for n in sorted(stored, key=lambda n: n["k"])]
      and [n["k"] for n in got] == sorted(n["k"] for n in stored), got)
check("...the spent one marked spent, the other spendable", [n["spent"] for n in got] == [True, False], got)
key = "nado.stwoDep." + ADDR
check("...and the index continues past them (no owner is reused)", int(rec["ls"].get(key, 0)) == max(n["k"] for n in stored) + 1, rec["ls"])
check("...a restore runs once per account on a device", rec["ls"].get(key + ".scan") == "1")
again = wallet("recover", stored=[], history=history, leaves=[], spent=[])
check("4. a deposit the pool never applied is not banked", again["recovered"] == 0 and again["stored"] == [], again)
check("...nor another account's deposit (sanity: 2 found above, not 3)", rec["recovered"] == 2)

print("ALL PASS — each Stwo deposit has its own owner and the wallet spends and restores each" if not fails
      else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
