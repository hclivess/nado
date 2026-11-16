/*
 * test_moving_diagonally_is_no_faster_than_straight_and_free_flight_stays_within_the_servers_pace.mjs — playtest
 * 2026-11-16, a real player's own trace: in free flight the world server pulled them back eleven times (10-50 m each),
 * at average speeds of 8-12 m/s. land.js step added forward and sideways as they came, so W+D — or the phone's stick,
 * which clamps each axis to ±1 on its own, pushed to a corner — went √2 times as fast: fast flight 85 m/s against the
 * 60 it is, past the server's PACE_MPS 65, and a diagonal run 10.6 m/s against 7.5. moveDir cuts the asked direction to
 * length 1 (a partial tilt kept); a craft's controls take the raw values (throttle and turn, not one diagonal). The
 * page's moveDir runs here on every key and stick combination, against the server's own limit.
 * Run: node tests/test_moving_diagonally_is_no_faster_than_straight_and_free_flight_stays_within_the_servers_pace.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const server = readFileSync(join(ROOT, "scripts", "land_server.py"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const i0 = page.indexOf("function moveDir(fwd, side) {");
const moveDir = new Function(page.slice(i0, page.indexOf("\n}\n", i0) + 2) + "\nreturn moveDir;")();
const sp = Object.fromEntries([...page.match(/const GRAV = [^;]*;/)[0].matchAll(/(\w+) = ([\d.]+)/g)].map((m) => [m[1], +m[2]]));
const PACE = +server.match(/^PACE_MPS, PACE_SLACK, PACE_DT_MAX = ([\d.]+),/m)[1];
ok(sp.FLY_FAST > 0 && sp.RUN > 0 && PACE > 0, `(the page's speeds: walk ${sp.WALK}, run ${sp.RUN}, fly ${sp.FLY}, fast ${sp.FLY_FAST} m/s; the server allows ${PACE})`);
// every combination a player can hold: each key pair (-1, 0, 1) plus the stick (each axis -1..1 on its own, in steps)
let worst = 0, worstAt = null;
for (const kf of [-1, 0, 1]) for (const ks of [-1, 0, 1]) for (let a = -1; a <= 1.001; a += 0.25) for (let b = -1; b <= 1.001; b += 0.25) {
  const [f, s] = moveDir(kf + a, ks + b), m = Math.hypot(f, s);
  if (m > worst) { worst = m; worstAt = [kf, ks, a, b]; }
}
ok(worst <= 1 + 1e-9, `no keys and stick together ask for more than full strength (at most ${worst.toFixed(4)}; was √2 on a diagonal, 2√2 keys plus stick)`);
ok(Math.abs(Math.hypot(...moveDir(1, 1)) - 1) < 1e-9 && moveDir(1, 0)[0] === 1, "W+D goes as fast as W alone, in between the two");
const half = moveDir(0.4, 0.3);
ok(half[0] === 0.4 && half[1] === 0.3, "a stick tilted part way keeps its tilt (a slow creep stays slow)");
ok(sp.FLY_FAST * worst <= PACE, `the fastest free flight, ${(sp.FLY_FAST * worst).toFixed(1)} m/s, is within the server's ${PACE} m/s — it is not pulled back (a diagonal was ${(sp.FLY_FAST * Math.SQRT2).toFixed(1)})`);
ok(Math.abs(sp.RUN * worst - sp.RUN) < 1e-9, `a diagonal run is ${sp.RUN} m/s, not ${(sp.RUN * Math.SQRT2).toFixed(1)}`);
const st = page.slice(page.indexOf("function step(dt) {"), page.indexOf("\n}\n", page.indexOf("function step(dt) {")));
ok(/if \(flying\) return flyStep\(dt, f0, s0\);[\s\S]*const \[fwd, side\] = moveDir\(f0, s0\);/.test(st) && /const wu = \(sy \* fwd \+ cy \* side\) \* sp/.test(st),
  "walking and free flight go by moveDir; a craft's controls take the raw throttle and turn");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
