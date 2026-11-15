/*
 * test_a_piece_refused_because_the_player_stands_there_says_so.mjs — playtest 2026-11-15, the agent building on its own
 * plot: looking straight down, the 1 m piece's outline was red and Place said only "No room for that piece there" —
 * nothing said the piece would be inside the player. land.js placement now gives why: "me" when the player's own body
 * is all that is in the way (not another piece), and Place says "That piece would be where you stand — step back, or
 * aim farther off" — in all 17 languages; any other refusal still says "No room".
 * Run: node tests/test_a_piece_refused_because_the_player_stands_there_says_so.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const I = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const pl = page.slice(page.indexOf("function placement(a) {"), page.indexOf("function riseShape()"));
ok(/const inBody = me\.plot === c\.plot && pieces\.some\(inMe\), onPiece = /.test(pl) && /const clash = inBody \|\| onPiece;/.test(pl) && /why: inBody && !onPiece \? "me" : ""/.test(pl),
  "placement says why it refuses: the player's own body alone is \"me\"; another piece in the way is not");
ok(/if \(!pl\.ok\) return notify\(pl\.why === "me" \? T\("noRoomMe", "That piece would be where you stand — step back, or aim farther off\."\) : T\("noRoom", "No room for that piece there\."\)\);/.test(page),
  "Place says the piece would be where the player stands — and \"No room\" for every other refusal");
ok(Object.keys(I).length === 17 && Object.keys(I).every((l) => typeof I[l]["land.noRoomMe"] === "string" && I[l]["land.noRoomMe"].length > 10), "the message is in all 17 languages");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
