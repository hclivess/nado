/*
 * test_the_dex_launch_tab_quotes_what_the_contract_pays_and_speaks_every_language.mjs — the DEX page's Launch tab
 * (static/dex.js, doc/launchpad.md):
 *   1. the quote an order shows (lpQuote: what it gets alone in its batch, net of the 1 % fee) is EXACTLY what the real
 *      contract pays that order — buys and sells, small and large, run through ExecState (a differential, not a re-read);
 *   2. launching passes the creator's scale (VN = the graduation target / 4) inside dex.py's bounds, and a coin's id is
 *      computed with the same function the NFT page uses (pinned against the Python by the NFT test);
 *   3. a graduated launch counts as a live pool (reserves, no shares) and a curve still running is kept out of the pool
 *      lists; the Launch mode exists and its create flow reads its progress from the chain;
 *   4. every string the tab shows exists in all 17 languages, placeholders intact.
 *
 * Run: node tests/test_the_dex_launch_tab_quotes_what_the_contract_pays_and_speaks_every_language.mjs
 */
import { readFileSync, mkdtempSync, rmSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const js = readFileSync(join(ROOT, "static", "dex.js"), "utf8"), html = readFileSync(join(ROOT, "static", "dex.html"), "utf8");

// 1. the page's quote, taken from the page's own source, against the contract's payout
const src = js.slice(js.indexOf("function lpQuote("), js.indexOf("async function lpAsset("));
const LP_FEE = 100n;
const lpQuote = new Function("LP_FEE", src + "; return lpQuote;")(LP_FEE);
const home = mkdtempSync(join(tmpdir(), "nado-test-lptab-"));
const py = `
import os, sys, json
os.environ["HOME"] = ${JSON.stringify(home)}
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "s.json"); os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "da")
sys.path.insert(0, ${JSON.stringify(ROOT)})
from execnode.state import ExecState, asset_id
from execnode.games import dex as D
U = D.UNIT; out = []
for case, (side, units) in enumerate([(1, 100), (1, 7_777), (1, 250_000), (2, 3_333), (2, 90_000)]):
    st = ExecState(os.path.join(os.environ["HOME"], f"s{case}.json")); st.cursor = 1000
    me, other = "m" * 48, "o" * 48
    for w in (me, other): st.bridge[w] = 10 ** 18
    cid = st.apply_blob({"op": "deploy", "code": D.build(), "nonce": "q", "runtime": "zkvm", "abi": D.ABI}, me, "tx").split()[1]
    st.apply_blob({"op": "asset_create", "seed": 1, "name": "Q", "sym": "Q", "dec": 8, "supply": 1_000_000 * U, "mintable": False}, me, "tx")
    aid = int(asset_id(me, 1))
    def call(s, m, a, v=0, asset=0):
        st._block_steps = 0; st.__dict__["_block_steps_by"] = {}
        return st.apply_blob({"op": "call", "contract": cid, "method": m, "args": a, "value": v, "asset": asset}, s, "tx")
    call(me, "prelaunch", [5], D.CREATE_FEE * U); call(me, "launch", [5, 1_000_000, D.VN0], 1_000_000 * U, aid)
    if side == 2:                     # someone first buys, so there is a curve to sell back to
        st.cursor += 11; call(other, "buy", [5, 1, 200_000], 200_000 * U); st.cursor += 1; call(other, "claim", [1, aid])
        st.apply_blob({"op": "asset_transfer", "asset": str(aid), "to": me, "amount": 100_000 * U}, other, "tx")
    st.cursor += 11
    slots = lambda f, k: int(((st.contracts[cid].get("storage") or {}).get("slots") or {}).get(str(f * (1 << 32) + k), 0))
    state = {"cn": slots(D.CN, 5), "ct": slots(D.CT, 5), "vn": slots(D.VN, 5)}
    n0, t0 = st.bridge[me], st.asset_balance(aid, me)
    r = call(me, "buy" if side == 1 else "sell", [5, 9, units], units * U, 0 if side == 1 else aid)
    st.cursor += 1
    call(me, "claim", [9, aid])
    got = (st.asset_balance(aid, me) - t0) // U if side == 1 else (st.bridge[me] - n0 + (0 if side == 1 else 0)) // U
    out.append({"side": side, "units": units, "state": state, "got": got})
print(json.dumps(out))
`;
let rows = [];
try { rows = JSON.parse(execFileSync("python3", ["-c", py], { cwd: home, encoding: "utf8", timeout: 300000 }).trim().split("\n").pop()); }
catch (e) { ok(false, "the contract run failed: " + String(e.message || e).slice(0, 400)); }
finally { rmSync(home, { recursive: true, force: true }); }
for (const r of rows) {
  const c = { cn: BigInt(r.state.cn), ct: BigInt(r.state.ct), vn: BigInt(r.state.vn) };
  const q = lpQuote(c, r.side, BigInt(r.units));
  ok(q === BigInt(r.got), `${r.side === 1 ? "a buy" : "a sell"} of ${r.units} units: the page quotes ${q}, the contract pays ${r.got}`);
}

// 2
const create = js.slice(js.indexOf("function lpCreate("), js.indexOf("// ================= CROSS-CHAIN"));
ok(/const target = toUnits[\s\S]{0,80}vn = target \/ 4n/.test(create) && /vn < LP_VN_MIN \|\| vn >= LP_VN_MAX/.test(create)
   && /"launch", \[job\.pid, Number\(job\.units\), Number\(job\.vn/.test(js), "launching passes the creator's scale (target / 4), inside the contract's bounds");
const dexpy = readFileSync(join(ROOT, "execnode", "games", "dex.py"), "utf8");
ok(/VN_MIN, VN_MAX = 100, 1 << 26/.test(dexpy) && /LP_VN_MIN = 100n, LP_VN_MAX = 1n << 26n/.test(js), "the page's bounds are the contract's");
const nft = readFileSync(join(ROOT, "static", "nft.js"), "utf8");
const body = (s, name) => (s.match(new RegExp(`function ${name}\\(addr, seed\\) \\{([\\s\\S]*?)\\n\\}`)) || [])[1] || "";
ok(body(js, "lpAssetId").replace(/LP_PERSON/g, "P").trim() === body(nft, "assetId").replace(/ADDR_PERSON/g, "P").trim() && /personOf\("NADOvmA1"\)/.test(js),
   "a coin's id is the NFT page's assetId (pinned against the Python there)");

// 3
ok(/const livePool = \(p\) => p\.rn > 0n && p\.rt > 0n && \(p\.sup > 0n \|\| p\.kind === 2\)/.test(js) && /filter\(\(id\) => !curveRunning\(sto, id\)\)/.test(js),
   "a graduated launch is a live pool; a running curve stays out of the pool lists");
ok(/key: "launch"/.test(js) && /cards: \["lpFeedCard", "lpCreateCard"\], keep: \["lpCoinCard"\]/.test(js) && /keep: \["liqCard"\]/.test(js) && /id="lpFeedCard"/.test(html) && /id="lpCreateCard"/.test(html),
   "the Launch mode and its cards exist; the coin card and the liquidity card are the page's to show (keep), so a mode never force-shows them");
ok(/const step = live \? 4 : reserved \? 3 : a && a\.id \? 2 : 1/.test(js), "the create flow reads its progress from the chain");

// 4
const L = ["en", "cs", "es", "pt", "fr", "de", "it", "ru", "zh", "ja", "ko", "ar", "hi", "tr", "id", "vi", "pl"];
const tr = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "dex.json"), "utf8"));
const keys = new Map();
for (const [, k, en] of js.matchAll(/LT\("([a-zA-Z0-9]+)", "((?:[^"\\]|\\.)*)"/g)) keys.set("dex." + k, en);
for (const [, k] of html.matchAll(/data-i18n(?:-ph|-html)?="(dex\.[a-zA-Z0-9]+)"/g)) if (!keys.has(k)) keys.set(k, null);
const ph = (s) => [...String(s).matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(",");
const missing = [], broken = [];
for (const [k, en] of keys) for (const l of L) {
  const v = (tr[l] || {})[k];
  if (v == null) missing.push(`${l}:${k}`);
  else if (en != null && ph(v) !== ph(en)) broken.push(`${l}:${k}`);
}
ok(keys.size > 50 && !missing.length, `every Launch string (${keys.size}) is in all 17 languages (${missing.slice(0, 6).join(" ")})`);
ok(!broken.length, `…with its placeholders intact (${broken.slice(0, 6).join(" ")})`);

if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
