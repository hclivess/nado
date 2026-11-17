/*
 * test_an_action_sent_while_the_world_server_is_out_of_reach_says_so.mjs — playing the agent's page (2026-11-17), the
 * socket to the world server had dropped and the page was waiting to reconnect (up to 30 s between tries); "Wear Leather
 * boots" was pressed twice and nothing was worn and nothing was said: net.send dropped every message in silence while the
 * socket was down, and only placing a block and anchoring checked first. Here the page's own `net` (static/land.js) is
 * driven with the socket down and up:
 *   1. a player's own action (a request number; chat, a name, a teleport, a shot) sent while down says the world server
 *      is out of reach, in the page's existing "offline" words — and send reports that nothing went;
 *   2. once per 3 s, not once per press; the background traffic (positions, a pilot's pose, traces) says nothing;
 *   3. with the socket open everything is sent and nothing is said.
 * Run: node tests/test_an_action_sent_while_the_world_server_is_out_of_reach_says_so.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

const a = page.indexOf("const NET_ACTS = "), b = page.indexOf("} };", a);
ok(a > 0 && b > a, "the page's net and the actions it speaks up for are found");
let said = [], clock = 0;
const notify = (m) => said.push(m), T = (k, d) => `${k}|${d}`;
const performance = { now: () => clock };
const net = new Function("notify", "T", "performance", page.slice(a, b + 4) + "\nreturn net;")(notify, T, performance);

// 1
clock = 10000;
const sent = net.send({ t: "wear", slot: "feet", item: "leather_boots", req: 1 });
ok(sent === false, "with the socket down, send reports that nothing went");
ok(said.length === 1 && said[0].startsWith("offline|The world server is out of reach"), "…and a Wear pressed says the world server is out of reach, in the page's own offline words: " + JSON.stringify(said));
// 2
net.send({ t: "craft", recipe: "leather_gloves", req: 2 });
ok(said.length === 1, "a second press within 3 s says nothing more");
clock += 3500; net.send({ t: "chat", text: "hello" });
ok(said.length === 2, "…after 3 s, an action (chat) says it again");
clock += 3500;
for (const m of [{ t: "pos", p: [0, 1, 2, 3, 0] }, { t: "fly", craft: 1, pose: [] }, { t: "watch", w: "" }, { t: "trace", ev: [] }]) net.send(m);
ok(said.length === 2, "positions, a pilot's pose, the watch and traces say nothing");
for (const t of ["name", "tp", "bolt"]) { clock += 3500; net.send({ t }); }
ok(said.length === 5, "a name, a teleport and a shot are actions too");
// 3
const out = [];
net.ws = { readyState: 1, send: (s) => out.push(JSON.parse(s)) };
clock += 3500;
ok(net.send({ t: "wear", slot: "hands", item: "leather_gloves", req: 3 }) === true && out.length === 1 && out[0].item === "leather_gloves", "with the socket open the action is sent");
net.send({ t: "pos", p: [0, 0, 0, 0, 0] });
ok(out.length === 2 && said.length === 5, "…everything is, and nothing is said");
// the setBlock / anchor checks stay as they were (they speak before net.send is reached)
ok((page.match(/if \(!net\.online\) return notify\(T\("offline"/g) || []).length >= 2, "placing and anchoring still check before they act");

console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
