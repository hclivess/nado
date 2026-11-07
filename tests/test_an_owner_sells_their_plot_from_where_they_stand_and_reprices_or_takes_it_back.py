"""
An owner puts their plot up for sale from inside Land (#126, "users should be able to put up their land for sale in an
automated process including the screenshot", operator 2026-11-07) — and the calls the page builds are the ones the
NFT market accepts, driven here through the real market contract (execnode/games/nft.py on ExecState.apply_blob), not
read off the code:

  1. the page's own sell / reprice / unlist (static/land.js, run in node with the wallet and dialogs stubbed): a sale is
     offered only on a plot the player holds, prices are read as NADO and a zero or junk price is refused before any
     wallet call; the market is the contract the market's own page names (/static/nft.js CID, read at run time);
     asking for the plot's card first puts it in line for a fresh photo; the list call escrows exactly the one title
     and asks the wallet for a visible confirm; reprice and unlist are offered only to the listing's seller;
  2. those exact payloads, applied by the owner to the market: the title is escrowed at the price, a buyer pays it and
     the creator's 5 % royalty and the seller's rest are paid in one step; on a second listing a reprice changes only
     the price, and unlist returns the title to its owner;
  3. the HUD offers Sell on your plot and Change price / Take off sale on your listing, and the strings are in 17
     languages.

Run: python3 tests/test_an_owner_sells_their_plot_from_where_they_stand_and_reprices_or_takes_it_back.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): a throwaway HOME and exec files, never the live node's
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-sell-")
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import json, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from execnode.state import ExecState, asset_id
from execnode.games import nft as N
import _harness
_report = _harness.Report()
check = _report.check

page = open(os.path.join(ROOT, "static", "land.js"), encoding="utf-8").read()
nftsrc = open(os.path.join(ROOT, "static", "nft.js"), encoding="utf-8").read()
MARKET = re.search(r'^const CID = "([0-9a-f]{32})";', nftsrc, re.M).group(1)
ISSUER, OWNER, BUYER = "ndoISSU" + "I" * 41, "ndoOWNR" + "O" * 41, "ndoBUYR" + "B" * 41
PLOT = 40938864

# 1. the page's functions, in node
block = page.split("let marketCid = null;", 1)[1].split("// ---- the live world", 1)[0]
js = r"""
const calls = [], alerts = [], fetched = [];
const nftText = %s, AID = "%s", PLOT = %d, ME = "%s";
let prompts = [], confirmOk = true;
const T = (k, en, v) => en.replace(/\{(\w+)\}/g, (m, x) => v && x in v ? String(v[x]) : m);
const RAW = 10000000000n;
const nadoToRaw = (s) => { s = String(s).trim().replace(",", "."); if (!/^\d+(\.\d+)?$/.test(s)) return null; const [w, f = ""] = s.split("."); const r = BigInt(w) * RAW + BigInt((f + "0000000000").slice(0, 10)); return r > 0n ? r : null; };
const rawToNado = (r) => { r = BigInt(r); const w = r / RAW, f = (r %% RAW).toString().padStart(10, "0").replace(/0+$/, ""); return f ? w + "." + f : String(w); };
const randId = () => 424242;
const plotLabel = (p) => String(p);
const alertBar = (m) => alerts.push(m), notify = (m) => alerts.push(m);
const explainNoBuild = () => { alerts.push("noBuild"); return false; };
const uiPrompt = async () => prompts.shift();
const uiConfirm = async () => confirmOk;
const fetch = async (u) => { fetched.push(u); return { text: async () => nftText, json: async () => ({ plot: PLOT, shot: null }) }; };
const net = { me: ME }, dapp = { me: ME, call: (...a) => calls.push(a) };
const titles = new Map([[PLOT, { aid: AID }]]), mine = new Set();
let marketCid = null;
%s
const out = {};
// not the player's plot: nothing is offered for sale
await sell(PLOT); out.notMine = { calls: calls.length, alerts: alerts.slice() };
mine.add(PLOT);
prompts = ["0"]; alerts.length = 0; await sell(PLOT); out.zero = { calls: calls.length, alerts: alerts.slice() };
prompts = ["lots"]; alerts.length = 0; await sell(PLOT); out.junk = { calls: calls.length, alerts: alerts.slice() };
prompts = ["7.5"]; confirmOk = false; await sell(PLOT); out.declined = calls.length;
prompts = ["7.5"]; confirmOk = true; await sell(PLOT); out.list = calls[calls.length - 1]; out.fetched = fetched.slice();
// a listing: only its seller may reprice or withdraw it
const t = titles.get(PLOT); mine.delete(PLOT);
t.sale = { price: 75000000000n, lid: 424242, seller: "ndoSOMEONEELSE", market: "%s" };
const before = calls.length; prompts = ["9"]; await reprice(PLOT); await unlist(PLOT); out.notSeller = calls.length - before;
t.sale.seller = ME;
prompts = ["9"]; await reprice(PLOT); out.reprice = calls[calls.length - 1];
await unlist(PLOT); out.unlist = calls[calls.length - 1];
console.log(JSON.stringify(out, (k, v) => typeof v === "bigint" ? "big:" + v : v));
"""
AID_FAKE = "1234567890123456789012345678901234567890"
r = subprocess.run(["node", "--input-type=module", "-e", js % (json.dumps(nftsrc), AID_FAKE, PLOT, OWNER, block, MARKET)],
                   capture_output=True, text=True, timeout=120)
O = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
check("a sale is offered only on a plot the player holds", O.get("notMine", {}).get("calls") == 0 and O["notMine"]["alerts"] == ["noBuild"], (O, r.stderr[-500:]))
check("a zero or junk price is refused before any wallet call",
      O.get("zero", {}).get("calls") == 0 and O.get("junk", {}).get("calls") == 0 and len(O["zero"]["alerts"]) == 1 and len(O["junk"]["alerts"]) == 1, O)
check("…and a sale the owner declines at the confirm is never sent", O.get("declined") == 0, O)
L_ = O.get("list") or [None] * 6
check("the market is the contract the market's own page names, read at run time",
      L_[5] and L_[5].get("cid") == MARKET and "/static/nft.js" in O.get("fetched", []), L_)
check("…and asking for the plot's card first puts it in line for a fresh photo", f"/land/api/card?plot={PLOT}" in O.get("fetched", []), O.get("fetched"))
check("the list call escrows exactly the one title at the price, with a visible confirm",
      L_[0] == "list" and L_[1] == [424242, "big:" + AID_FAKE, "big:75000000000"] and L_[2] == "big:1"
      and L_[5].get("asset") == AID_FAKE and L_[5].get("confirm") is True, L_)
check("reprice and unlist are offered only to the listing's seller", O.get("notSeller") == 0, O)
R_, U_ = O.get("reprice") or [None] * 6, O.get("unlist") or [None] * 6
check("…the seller's reprice names the listing and the new price, value-free, on the listing's market",
      R_[0] == "reprice" and R_[1] == [424242, "big:90000000000"] and R_[2] is None and R_[5] == {"cid": MARKET, "confirm": True}, R_)
check("…and the seller's unlist names the listing, value-free", U_[0] == "unlist" and U_[1] == [424242] and U_[2] is None and U_[5] == {"cid": MARKET, "confirm": True}, U_)

# 2. the same payloads, applied to the real market contract
st = ExecState(os.path.join(tempfile.mkdtemp(prefix="nado_land_sell_"), "s.json"))
st.cursor = 1000
code = N.build()
st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": N.ABI, "nonce": "n"}, ISSUER, "d")
cid = st.contract_id(ISSUER, code, "n")
for w in (ISSUER, OWNER, BUYER):
    st.credit_deposit(w, 10 ** 15)
st.apply_blob({"op": "asset_create", "seed": 77, "name": "Land plot 0·4998·3435", "sym": "PLOT", "dec": 0, "supply": 1,
               "mintable": False, "uri": f"https://land.nadochain.com/?plot={PLOT}"}, ISSUER, "m")
aid = int(asset_id(ISSUER, 77))
n = [0]


def call(who, method, args, value=None, asset=None):
    n[0] += 1
    blob = {"op": "call", "contract": cid, "method": method, "args": args}
    if value is not None:
        blob["value"] = value
    if asset:
        blob["asset"] = str(asset)
    return str(st.apply_blob(blob, who, f"c{n[0]}"))


def page_call(who, c, lid=None):
    """The page's dapp.call(method, args, value, label, pend, {asset}) as the wallet sends it (encBig undone)."""
    un = lambda v: int(v[4:]) if isinstance(v, str) and v.startswith("big:") else v
    args = [un(a) for a in c[1]]
    if c[0] == "list":
        args[1] = aid                                       # the stub title's id stood in for this one
    if lid is not None:
        args[0] = lid
    return call(who, c[0], args, un(c[2]), aid if (c[5] or {}).get("asset") else None)


ok = lambda s: not s.startswith("skip:") and "revert" not in s.lower()
rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
units = lambda who: int(st.asset_balance(str(aid), who))
nat = lambda who: int(st.bridge.get(who, 0))
check("the title's issuer registers its 5 % royalty, as the first wave did", ok(call(ISSUER, "register", [1, aid, 77, 500, 0])))
st.apply_blob({"op": "asset_transfer", "asset": str(aid), "to": OWNER, "amount": 1}, ISSUER, "t")
res = page_call(OWNER, L_)
check("the owner's list call is accepted: the title is escrowed at the price", ok(res) and units(OWNER) == 0 and units(cid) == 1
      and rd(N.L_PRICE, 424242) == 75000000000 and rd(N.L_LEFT, 424242) == 1, res)
o0, i0 = nat(OWNER), nat(ISSUER)
res = call(BUYER, "buy", [424242, 1], 75000000000)
check("a buyer pays it: the creator's 5 % and the seller's rest are paid in one step, the title is the buyer's",
      ok(res) and units(BUYER) == 1 and nat(ISSUER) - i0 == 75000000000 * 5 // 100 and nat(OWNER) - o0 == 75000000000 * 95 // 100, res)
# a second listing by the new owner, then reprice and unlist through the page's payloads
L2 = [L_[0], L_[1], L_[2], L_[3], L_[4], L_[5]]
check("a second owner lists it the same way", ok(page_call(BUYER, L2, lid=5151)))
res = page_call(BUYER, R_, lid=5151)
check("a reprice changes only the price", ok(res) and rd(N.L_PRICE, 5151) == 90000000000 and units(cid) == 1 and rd(N.L_LEFT, 5151) == 1, res)
check("…and only the seller's", not ok(page_call(OWNER, R_, lid=5151)))
res = page_call(BUYER, U_, lid=5151)
check("unlist returns the title to its owner", ok(res) and units(BUYER) == 1 and units(cid) == 0 and rd(N.L_ST, 5151) == N.CANCELLED, res)

# 3. the HUD and the strings
check("the HUD offers Sell on your own plot", 'id="btnSell"' in page and "sl.onclick = () => sell(plot)" in page)
check("…and Change price / Take off sale on your own listing",
      "t.sale && t.sale.seller && t.sale.seller === (net.me || dapp.me)" in page and 'id="btnReprice"' in page and 'id="btnUnlist"' in page)
check("a sale call that returns re-reads the market", "listingCache.clear();" in page)
tr = json.load(open(os.path.join(ROOT, "static", "i18n_games", "land.json"), encoding="utf-8"))
keys = sorted(set(re.findall(r'T\("((?:sell|reprice|unlist|yourSale|seeListing|noMarket|selling|repricing|unlisting)\w*)"', page)))
check(f"its {len(keys)} strings are in 17 languages, every placeholder kept",
      len(keys) >= 28 and len(tr) == 17 and all(all(l.get("land." + k) for k in keys) for l in tr.values())
      and all(set(re.findall(r"\{(\w+)\}", l["land." + k])) == set(re.findall(r"\{(\w+)\}", tr["en"]["land." + k])) for l in tr.values() for k in keys),
      [k for k in keys if any(not l.get("land." + k) for l in tr.values())])
_report.done()
