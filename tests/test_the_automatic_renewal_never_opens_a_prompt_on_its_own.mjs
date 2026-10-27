/* The automatic lease renewal never opens a device prompt on its own (static/interface.js maybeRenewLease ->
 * broadcastLeaseRenewal -> computeRegisterTx, RenewNeedsTap).
 *
 * Found 2026-10-27 by tests/test_every_identity_class_can_renew.py: the renewal TIMER (no user gesture) fell through to
 * attestDevice whenever neither the statement-free, the signature nor the helper path applied. A browser refuses
 * create() without a gesture, so the lease simply lapsed — "unable to renew" — and a vouched-for wallet whose voucher
 * had not dropped a proof yet prompted ITS OWN device, or hit device.required every few minutes.
 *
 * Pins, by RUNNING the real functions with the browser and network stubbed and the device prompt as a spy:
 *   1. the timer on a device that needs a prompt opens none, and tells the owner to press Renew;
 *   2. the timer on a vouched-for wallet with no drop opens none, and points at the vouching device;
 *   3. a press (Renew armed the tap) opens exactly one prompt and renews;
 *   4. the timer still renews with no prompt where none is needed: a helper/voucher drop, a bound-for-life identity;
 *   5. maybeRenewLease is the one that passes { noPrompt: true }.
 *
 * Run: node tests/test_the_automatic_renewal_never_opens_a_prompt_on_its_own.mjs
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(HERE, "..", "static", "interface.js"), "utf8");
function fnSrc(name, isAsync = false) {
  const i = SRC.indexOf((isAsync ? "async function " : "function ") + name + "(");
  if (i === -1) throw new Error(name + " not found");
  let depth = 0, j = SRC.indexOf("{", SRC.indexOf(")", i));
  for (; j < SRC.length; j++) { if (SRC[j] === "{") depth++; else if (SRC[j] === "}" && --depth === 0) break; }
  return SRC.slice(i, j + 1);
}
let fails = 0;
const check = (name, ok, detail = "") => { console.log((ok ? "PASS  " : "FAIL  ") + name + (ok ? "" : "  " + detail)); if (!ok) fails++; };

const cls = SRC.match(/class RenewNeedsTap extends Error \{[^\n]*\}/);
check("RenewNeedsTap is defined", !!cls);

async function run({ tapArmed = false, attestVia = "platform", drops = [], perm = false, noPrompt = true }) {
  const rec = { prompts: 0, logs: [], built: [] };
  const state = { wallet: { address: "aaaa" }, tapArmed, attestVia, devbind: null, latest: 1000, pendingDrops: [] };
  const env = {
    state, REG_TARGET_MARGIN: 30, POSW_ANCHOR_OFFSET: 6,
    log: (lvl, m) => rec.logs.push(lvl + ": " + m),
    i18: (k, d) => k + "|" + d,
    rpcJSON: async () => ({ data: { block_hash: "ab".repeat(32) } }),
    RelayUnreachable: class extends Error {},
    bindIsPermanent: async () => perm,
    storedCredentialId: () => null, assertCredential: async () => null,
    helperDrops: async () => drops,
    attestDevice: async () => { rec.prompts++; state.tapArmed = false; return { att: "x" }; },
    readDeviceStatus: () => null, setRegBanner: () => {}, setDeviceStatus: () => {},
    buildRegisterTx: (w, tb, _p, _t, device) => { const tx = { txid: "t" + rec.built.length, max_block: tb, device }; rec.built.push(tx); return tx; },
    nowSeconds: () => 1,
    getLatestBlock: async () => ({ block_number: 1000 }),
    registrationDifficulty: async () => ({ reqT: 0 }),
    submitTransaction: async () => ({ data: { result: true } }),
    acceptedRegisterTx: () => {}, healSignatureRenewal: () => false,
  };
  const body = [cls[0], "let _renewingLease = false, _renewSubmitted = null;", fnSrc("computeRegisterTx", true),
                fnSrc("broadcastLeaseRenewal", true), "return broadcastLeaseRenewal;"].join("\n");
  const f = new Function(...Object.keys(env), body)(...Object.values(env));
  rec.ok = await f(7, noPrompt ? { noPrompt: true } : {});
  return rec;
}

let r = await run({});
check("1. the timer on a device that needs a prompt opens NONE", r.prompts === 0 && r.ok === false, JSON.stringify(r));
check("...and tells the owner to press Renew", r.logs.some((l) => l.includes("lease.tapToRenew")), r.logs.join(" / "));
check("...without logging it as an error (the timer backs off; nothing failed)", !r.logs.some((l) => l.startsWith("err:")), r.logs.join(" / "));

r = await run({ attestVia: "remote" });
check("2. the timer on a vouched-for wallet with no drop opens NONE and points at the vouching device",
  r.prompts === 0 && r.logs.some((l) => l.includes("lease.remoteRenew")), JSON.stringify(r));

r = await run({ tapArmed: true, noPrompt: false });
check("3. a press (the tap armed by Renew) opens exactly one prompt and renews", r.prompts === 1 && r.ok === true, JSON.stringify(r));

r = await run({ drops: [{ max_block: 1030, device: { att: "from-helper" } }] });
check("4. the timer still renews from a helper / voucher drop, with no prompt", r.prompts === 0 && r.ok === true
  && r.built[0] && r.built[0].device && r.built[0].device.att === "from-helper", JSON.stringify(r));
r = await run({ perm: true });
check("...and a bound-for-life identity renews statement-free, with no prompt", r.prompts === 0 && r.ok === true
  && r.built[0] && r.built[0].device === null, JSON.stringify(r));

check("5. maybeRenewLease (the timer) is the caller that passes { noPrompt: true }",
  /broadcastLeaseRenewal\(regEpoch, \{ noPrompt: true \}\)/.test(fnSrc("maybeRenewLease", true))
  && !/noPrompt/.test(fnSrc("renewLeaseManually", true)));

console.log(fails ? `\nFAILED: ${fails}` : "\nALL PASS — the automatic renewal never opens a prompt on its own");
process.exit(fails ? 1 : 0);
