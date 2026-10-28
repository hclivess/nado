/* A Stwo spend is proven at the node config of the height it lands at (gen 28's STWO_JS_128_HEIGHT, 1 from gen 29,
 * inlined in G9: CFG_128 from block 1, CFG_340 only at height 0;
 * static/interface.js stwoCfgId, static/stark/stwo_js.js proveSpend / proveWith, static/stark/stwo_worker.js).
 *
 * A node verifies a spend at the config its landing height selects (execnode/stwo_js_native.config_id_at) and
 * refuses a proof at the other one, so a wallet that proves at the wrong config loses the spend: the relay refuses it
 * (400) and the user is told the proof does not verify. The wallet picks the config the same way stwoFeeToLive picks
 * the fee_to rule: from the pool tip + 1, the block the spend can land in.
 *
 * Pins, by RUNNING the wallet's own code: stwoCfgId is CFG_128 for every spend landing in block 1 or later (generation
 * 28's gate-below / gate-at pins retired in G9); proveSpend refuses a spend that names no config, and hands the named one to the prover
 * (the `run` hook the Worker path takes); proveWith selects it in the WASM core before proving and self-verifying;
 * the worker forwards `cfg` from its message; and the page no longer imports the retired gate.
 *
 * Run: node tests/test_a_stwo_spend_proves_at_the_config_of_the_height_it_lands_at.mjs
 */
import fs from "fs";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, "..");
const SRC = fs.readFileSync(path.join(ROOT, "static", "interface.js"), "utf8");
const WORKER = fs.readFileSync(path.join(ROOT, "static", "stark", "stwo_worker.js"), "utf8");
let fails = 0;
const check = (name, ok, detail = "") => { console.log((ok ? "PASS  " : "FAIL  ") + name + (ok ? "" : "  " + detail)); if (!ok) fails++; };

const S = await import(pathToFileURL(path.join(ROOT, "static", "stark", "stwo_js.js")).href);
check("the driver names the two node configs as the crate does (lib.rs NODE_CFG_340 = 0, NODE_CFG_128 = 1)",
  S.CFG_340 === 0 && S.CFG_128 === 1 && S.ABI_VERSION === 2, JSON.stringify([S.CFG_340, S.CFG_128, S.ABI_VERSION]));

// ---- stwoCfgId, run with the tip stubbed ------------------------------------------------------------------------------
const m = SRC.match(/function stwoCfgId\(\) \{[^\n]*\}/);
check("interface.js defines stwoCfgId", !!m);
const cfgAt = (tip) => new Function("_shieldTip", "_stwo", m[0] + "\nreturn stwoCfgId();")(tip, S);
check("the first block's spend already proves at 128", cfgAt(0) === S.CFG_128);
check("...and every later one", cfgAt(999) === S.CFG_128 && cfgAt(376000) === S.CFG_128);
check("the page no longer imports the retired gate from /protocol.js", !/STWO_JS_128_HEIGHT[\s,]*\}?\s*from\s*"\/protocol\.js"/.test(SRC)
  && !/import \{[^}]*STWO_JS_128_HEIGHT/.test(SRC));
check("the wallet's spend passes stwoCfgId() to proveSpend", /cfg: stwoCfgId\(\)/.test(SRC));

// ---- proveSpend: refuses a spend without a config, hands the named one to the prover ----------------------------------
const nsk = "11".repeat(32), rho = "5", v = "1000";
const owner = S.ownerOf(nsk);
const leaves = [S.commit(v, owner, rho)];
const spend = { nsk, vIn: v, rho, v1: "1000", o1: owner, r1: "1", v2: "0", o2: owner, r2: "2", unshield: "0", fee: "0", dest: "" };
let err = "";
try { await S.proveSpend(spend, leaves, 0, async () => { throw new Error("must not prove"); }); } catch (e) { err = String(e.message || e); }
check("proveSpend refuses a spend that names no node config (before proving)", /cfg/.test(err) && !/must not prove/.test(err), err);
for (const cfg of [S.CFG_340, S.CFG_128]) {
  let seen = null;
  try { await S.proveSpend({ ...spend, cfg }, leaves, 0, async (_w, _d, c) => { seen = c; throw new Error("stop"); }); } catch (e) { /* the stub stops it */ }
  check(`proveSpend hands config ${cfg} to the prover`, seen === cfg, String(seen));
}

// ---- proveWith: selects the config in the WASM core before seeding, proving and self-verifying -------------------------
const calls = [];
const core = {
  setConfig: (c) => calls.push(["cfg", c]), seed: () => (calls.push(["seed"]), 0),
  prove: () => (calls.push(["prove"]), { rc: 0, out: new Uint8Array(1) }), verifyOut: () => (calls.push(["verify"]), 0),
};
await S.proveWith(core, new Uint8Array(1), "", (n) => new Uint8Array(n).fill(1), S.CFG_128);
check("proveWith selects the config first, then seeds, proves and self-verifies at it",
  JSON.stringify(calls) === JSON.stringify([["cfg", 1], ["seed"], ["prove"], ["verify"]]), JSON.stringify(calls));
check("the worker forwards `cfg` from its message to proveWith",
  /const \{ witness, dest, cfg \} = ev\.data/.test(WORKER) && /crypto\.getRandomValues\(new Uint8Array\(n\)\), cfg\)/.test(WORKER));

console.log(fails ? `\nFAILED: ${fails}` : "\nALL PASS — a Stwo spend proves at the config of the height it lands at");
process.exit(fails ? 1 : 0);
