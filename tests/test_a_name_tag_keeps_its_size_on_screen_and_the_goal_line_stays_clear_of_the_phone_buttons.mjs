/*
 * test_a_name_tag_keeps_its_size_on_screen_and_the_goal_line_stays_clear_of_the_phone_buttons.mjs — playtest
 * 2026-11-15 on the phone layout (800 × 480): standing at Maren to talk, her 1.6 m name tag filled the top of the screen
 * and was cut off behind the HUD; and the goal line ("First: talk to Maren …") ran under the Use button.
 *   1. a name tag (land.js label) is an unattenuated sprite — the same size on screen near or far, PLATE_H high, four
 *      times as wide — anchored by its bottom edge where it hangs;
 *   2. a townsperson's "!" / "?" hangs from the same point one tag-height higher (center y −1.15), so the two never
 *      overlap at any distance;
 *   3. on a touch layout the goal line is at most 100vw − 560 px wide (never under 150 px): centred, it clears the left
 *      cluster (ends 208 px in) and the right one (274 px in) at 800, 915 and 1280 px;
 *   4. on a portrait phone (≤ 600 px, where the clusters span the width) it rides above the top button row (362 px:
 *      the left cluster went up a row there, 2026-11-16 — test_an_upright_phones_buttons_do_not_overlap_at_any_width).
 * Run: node tests/test_a_name_tag_keeps_its_size_on_screen_and_the_goal_line_stays_clear_of_the_phone_buttons.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8"), html = readFileSync(join(ROOT, "static", "land.html"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const lab = page.slice(page.indexOf("function label("), page.indexOf("\n}\n", page.indexOf("function label(")));
ok(/new THREE\.SpriteMaterial\(\{ map: t, depthWrite: false, transparent: true, sizeAttenuation: false \}\)/.test(lab) && /sp\.scale\.set\(PLATE_H \* 4, PLATE_H, 1\); sp\.center\.set\(0\.5, 0\);/.test(lab) && /const PLATE_H = 0\.2;/.test(page),
  "1. a name tag keeps one size on screen (unattenuated), PLATE_H high and four times as wide, hung by its bottom edge");
// the tag's share of the view's height, MEASURED on the live page (800 × 480, 72°): PLATE_H 0.07 drew a tag 1.7 % of the
// height (unreadable — the first try, from a formula that was wrong), so the share is 0.243 × PLATE_H
const share = 0.243 * Number(page.match(/const PLATE_H = ([0-9.]+);/)[1]);
ok(share > 0.04 && share < 0.07, `…about ${(share * 100).toFixed(1)} % of the view's height — readable, never the screen`);
ok(/r\.mark\.scale\.set\(PLATE_H \* 3\.5, PLATE_H \* 0\.875, 1\); r\.mark\.userData\.base = \[PLATE_H \* 3\.5, PLATE_H \* 0\.875\]; r\.mark\.center\.set\(0\.5, -1\.15\); r\.mark\.position\.set\(0, 2\.05, 0\);/.test(page) && /plate\.position\.set\(0, 2\.05, 0\); mesh\.add\(plate\);/.test(page),
  "2. a townsperson's mark hangs from the tag's own point, one tag-height above it, at every distance");
const m = html.match(/body\.touch #goal\{max-width:max\((\d+)px,calc\(100vw - (\d+)px\)\);font-size:11px\}/);
ok(!!m, "3. on a touch layout the goal line has its own width rule");
if (m) {
  const min = +m[1], side = +m[2];
  const clear = [800, 915, 1280].every((W) => { const w = Math.max(min, W - side), a = (W - w) / 2, b = a + w; return a >= 208 && b <= W - 274; });
  ok(clear, `…centred, it clears the left cluster (208 px) and the right one (274 px from the right) at 800, 915 and 1280 px`);
}
ok(/@media \(max-width:600px\)\{body\.touch #goal\{position:fixed;left:50%;transform:translateX\(-50%\);bottom:362px;/.test(html) && /body\.touch #tFire,body\.touch #tWard,body\.touch #tLevel\{bottom:294px\}/.test(html),
  "4. on a portrait phone it rides above the top button row (Fire at 228 + 58 px)");
// 5. …and shrinks with distance beyond PLATE_NEAR (a constant size overlapped Ida's and Maren's tags from 14 m: "IdaMa…")
{
  const a = page.indexOf("const PLATE_NEAR"), src = page.slice(a, page.indexOf("\nfunction label(", a));
  const sizePlates = new Function(src + "\nreturn sizePlates;")();
  const mk = (d) => { const c = { isSprite: true, userData: { base: [0.8, 0.2] }, scale: { set(x, y) { this.x = x; this.y = y; } } }; return { mesh: { position: { length: () => d }, children: [c] }, c }; };
  const at = (d) => { const m = mk(d); sizePlates(m.mesh); return m.c.scale.y; };
  ok(at(2) === 0.2 && at(8) === 0.2 && Math.abs(at(16) - 0.1) < 1e-9 && Math.abs(at(100) - 0.2 / 3) < 1e-9,
    `5. full size within 8 m (${at(2)}), half at 16 m (${at(16)}), never under a third (${at(100).toFixed(3)} at 100 m)`);
  ok((page.match(/sizePlates\(r\.mesh\);/g) || []).length === 2 && /sp\.userData\.base = \[PLATE_H \* 4, PLATE_H\];/.test(page) && /r\.mark\.userData\.base = /.test(page),
    "…applied every frame to the townspeople's and the players' tags and marks");
}
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
