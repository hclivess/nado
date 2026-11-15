/*
 * test_a_teleport_or_any_move_the_player_did_not_walk_is_never_undone_by_a_saved_place_waiting_for_its_plot.mjs —
 * #180 item 3 (playtest 2026-11-11): "/tp spawn" typed seconds after the page loaded answered "At the landing." and the
 * player was then back at the old place; the second /tp held. The cause: a saved place on a built floor or underground
 * waits for its plot's edits (land.js pendingPlace, set in load / placeAt) and applyPlot took it back when they arrived —
 * after the teleport. Pinned on the page's code:
 *   1. the place is taken back only from applyPlot, and only while pendingPlace is set (it is cleared there);
 *   2. every move the player did not walk clears it BEFORE it sets the place: the world server's pos_fix (/tp, a move
 *      put back), waking after death, boarding a craft, leaving one, and the offline /tp spawn;
 *   3. a model of the race: load with a pending place, a teleport, then the plot's edits — the teleport stands.
 * Run: node tests/test_a_teleport_or_any_move_the_player_did_not_walk_is_never_undone_by_a_saved_place_waiting_for_its_plot.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 1. where the pending place is taken back
const takes = [...page.matchAll(/= pendingPlace(?![\w.])/g)].length;
ok(takes === 1 && /if \(pendingPlace && Wd\.plotOf\(pendingPlace\[0\][^\n]*=== plot\) \{\n\s+const \[f, u, v, h, yaw, pitch\] = pendingPlace, pf = P\.face;\n\s+pendingPlace = null;/.test(page),
  "1. a saved place is taken back in one place only — when its own plot's edits arrive — and is cleared there");

// 2. each move the player did not walk clears it before setting the place
const before = (anchor, what) => {
  const i = page.indexOf(anchor), j = page.lastIndexOf("pendingPlace = null", i);
  ok(i > 0 && j > 0 && i - j < 900 && !/\n(async )?function /.test(page.slice(j, i)), `2. ${what} clears the pending place before it moves the player`);
};
before("P.face = m.p[0]; P.u = m.p[1]; P.v = m.p[2];", "the world server's pos_fix (/tp spawn, /tp bed, a move put back)");
before("if (wakeAt) { [P.face, P.u, P.v] = [wakeAt[0], wakeAt[1] + 1.2, wakeAt[2]]; }", "waking after death");
before("P.face = c.pose[0]; P.u = c.pose[1]; P.v = c.pose[2]; P.h = c.pose[3] - PILOT_SIT;", "boarding a craft");
before("P.u = spot.u; P.v = spot.v; P.h = spotH(P.u, P.v);", "leaving a craft");
before("const sp = townSpawn(); P.face = sp[0]; P.u = sp[1]; P.v = sp[2]; P.yaw = sp[3];", "the offline /tp spawn");

// 3. the race, modelled: the page's own order of events
{
  let pending = null; const P = { u: 0 };
  const load = () => { P.u = 100; pending = [0, 500]; };                       // saved on a roof: the surface now, the roof pending
  const tp = () => { pending = null; P.u = 0; };                               // pos_fix "tp": the landing (u 0 in the model)
  const applyPlot = () => { if (pending) { const p = pending; pending = null; P.u = p[1]; } };
  load(); tp(); applyPlot();
  ok(P.u === 0, "3. loaded with a place pending, teleported, then the plot's edits arrive: the player stays at the landing");
  load(); applyPlot();
  ok(P.u === 500, "…and with no teleport the saved place is still taken back (a reload in your mine leaves you in your mine)");
}
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
