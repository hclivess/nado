/* The Shield tab follows the pool while it is open (static/interface.js shieldTick, renderShield).
 *
 * A deposit or a received banknote lands only when the exec node applies a FINALIZED block (~45 blocks, ~5 min), long
 * after the single re-render a deposit schedules, so the pool line and the banknote list stayed stale until a reload
 * (the gen-29 rehearsal's two-user walk, 2026-10-26).
 *
 * Pins, by RUNNING the wallet's own shieldTick with the network stubbed: an open, visible Shield tab re-renders when
 * the pool moved and NOT when it did not (a full render re-runs the withdrawal sweep, so it must not fire every tick);
 * a hidden page or another tab fetches nothing; renderShield records what it showed; and a timer drives the tick.
 *
 * Run: node tests/test_the_shield_tab_follows_the_pool_while_open.mjs
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

// shieldTick, with the module-level `seen` it compares against, and every dependency stubbed
function tick({ tab = "shield", visible = "visible", pool = { notes: 3, root: "r1" }, seen = null }) {
  const rec = { fetched: 0, rendered: 0 };
  const env = {
    state: { wallet: { address: "aaaa" }, activeTab: tab }, document: { visibilityState: visible },
    execJSON: async () => { rec.fetched++; return pool; }, renderShield: async () => { rec.rendered++; },
  };
  const body = "let _shieldPoolSeen = " + JSON.stringify(seen) + ", _shieldTickBusy = false;\n" + fnSrc("shieldTick", true) +
    "\nreturn shieldTick;";
  return new Function(...Object.keys(env), body)(...Object.values(env))().then(() => rec);
}

let r = await tick({ seen: "2:r0" });
check("an open, visible Shield tab re-renders when the pool moved", r.fetched === 1 && r.rendered === 1, JSON.stringify(r));
r = await tick({ seen: "3:r1" });
check("...and does not re-render when it did not (no withdrawal sweep every tick)", r.fetched === 1 && r.rendered === 0,
  JSON.stringify(r));
r = await tick({ tab: "wallet", seen: "2:r0" });
check("another tab fetches nothing", r.fetched === 0 && r.rendered === 0, JSON.stringify(r));
r = await tick({ visible: "hidden", seen: "2:r0" });
check("a hidden page fetches nothing", r.fetched === 0 && r.rendered === 0, JSON.stringify(r));

const render = fnSrc("renderShield", true);
check("renderShield records the pool it showed, in the form shieldTick compares",
  /_shieldPoolSeen = p\.notes \+ ":" \+ p\.root/.test(render) && /p\.notes \+ ":" \+ p\.root !== _shieldPoolSeen/.test(fnSrc("shieldTick", true)));
check("a timer drives the tick", /setInterval\(\(\) => \{ shieldTick\(\); \}, \d+\)/.test(SRC));

console.log(fails ? `\nFAILED: ${fails}` : "\nALL PASS — the Shield tab follows the pool while open");
process.exit(fails ? 1 : 0);
