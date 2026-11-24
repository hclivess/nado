/*
 * test_a_reconnect_keeps_the_world_standing_and_re_meshes_only_what_changed.mjs — "smooth user experience, live in the
 * world" (the operator's goal; one real player's evening, 2026-11-24: 179 dropped sockets on their network, each one
 * re-meshing the whole town and blanking every figure for the second a reconnect takes):
 *   1. a plot's list is put in as a difference (land.js applyPlot): the same list again puts and drops nothing, and a
 *      changed one puts or drops exactly the cells that differ — each re-meshing only around itself;
 *   2. the plots this browser cached are dropped on the page's FIRST hello only, not on every reconnect;
 *   3. a dropped socket leaves the people, the animals and the townsfolk standing for NET_GRACE ms — the first
 *      "players" after the reconnect drops whoever left — and clears them only if it is still away then.
 * Run: node tests/test_a_reconnect_keeps_the_world_standing_and_re_meshes_only_what_changed.mjs
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 1. the page's own applyPlot, with putCell / dropCell that keep plotEdit as the page's do and count what they touch
const src = page.slice(page.indexOf("function applyPlot(plot, list) {"), page.indexOf("/** The town's plots"));
const plotEdit = new Map(), touched = [];
const Wd = { plotCoords: () => ({ face: 0, u0: 1000, v0: 2000 }), plotOf: () => 7 };
const putCell = (f, u, v, h, b) => { let pe = plotEdit.get(7); if (!pe) plotEdit.set(7, pe = new Map()); pe.set((u - 1000) + ":" + (v - 2000) + ":" + h, b); touched.push(["put", u, v, h, b]); };
const dropCell = (f, u, v, h) => { const pe = plotEdit.get(7); if (pe) pe.delete((u - 1000) + ":" + (v - 2000) + ":" + h); touched.push(["drop", u, v, h]); };
const applyPlot = new Function("plotsApplied", "Wd", "plotEdit", "plotList", "putCell", "dropCell", "pendingPlace", "P", "collides", src + "\nreturn applyPlot;")(
  new Set(), Wd, plotEdit, new Map(), putCell, dropCell, null, {}, () => false);
const town = []; for (let x = 0; x < 30; x++) for (let z = 0; z < 30; z++) town.push([x, z, 100, 5]);
applyPlot(7, town);
ok(touched.length === 900 && plotEdit.get(7).size === 900, `a plot first seen puts every cell (${touched.length})`);
touched.length = 0; applyPlot(7, town);
ok(touched.length === 0, `the same list again — a reconnect's resend — puts and drops nothing (${touched.length} cells touched)`);
const changed = town.filter(([x, z]) => !(x === 3 && z === 4)).map((c) => (c[0] === 9 && c[1] === 9 ? [9, 9, 100, 6] : c)).concat([[1, 1, 101, 2]]);
touched.length = 0; applyPlot(7, changed);
const sig = touched.map((t) => t.join()).sort().join(" | ");
ok(sig === ["drop,1003,2004,100", "put,1001,2001,101,2", "put,1009,2009,100,6"].sort().join(" | "),
  `a changed list touches exactly the cells that differ: ${sig}`);
ok(plotEdit.get(7).size === 900 && plotEdit.get(7).get("9:9:100") === 6 && !plotEdit.get(7).has("3:4:100"), "…and the plot holds the server's list after it");
touched.length = 0; applyPlot(7, []);
ok(touched.length === 900 && !plotEdit.has(7), "an emptied plot drops every cell and holds nothing");
ok(!/function applyPlot[\s\S]*?\n\}/.exec(page)[0].includes("request(k)"), "…and no plot re-meshes its whole column of chunks");

// 2
ok(/if \(!net\.helloed\) \{\n\s+net\.helloed = true;\n\s+for \(const \[plot, pe\] of plotEdit\)[^\n]*\n\s+plotEdit\.clear\(\); plotList\.clear\(\);\n\s+\}/.test(page),
  "the plots this browser cached are dropped on the first hello only");
// 3
const close = page.slice(page.indexOf("ws.onclose = () => {"), page.indexOf("/** Replace a plot's cells"));
ok(/const NET_GRACE = \d+;/.test(page) && Number(/const NET_GRACE = (\d+);/.exec(page)[1]) >= 5000, "a dropped socket's grace is several seconds");
ok(/net\.graceT = setTimeout\(\(\) => \{\n\s+if \(net\.online\) return;[\s\S]*others\.clear\(\);[\s\S]*animals\.clear\(\);[\s\S]*npcs\.clear\(\);\n\s+\}, NET_GRACE\);/.test(close),
  "…and the figures are cleared only if the socket is still away when it ends");
ok(!/^    others\.clear\(\);/m.test(close), "…not at once on the close");
const players = page.slice(page.indexOf('} else if (m.t === "players") {'), page.indexOf('} else if (m.t === "talk") {'));
ok(/for \(const \[id, r\] of others\) if \(!seen\.has\(id\)\) \{ scene\.remove\(r\.mesh\); others\.delete\(id\); \}/.test(players) && players.includes("animalsSeen(m.animals);") && players.includes("npcsSeen(m.npcs);"),
  "the first \"players\" after a reconnect drops whoever left meanwhile");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
