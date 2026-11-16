/*
 * test_a_sown_crop_says_when_it_will_be_ripe.mjs — playtest 2026-11-16, the agent's field east of town: tilling said
 * the soil and "sow wheat seed on it", and once sown nothing said how long it would take (the world server knew: twenty
 * minutes on loam, held in the plot's `grow` — measured, every seed ripe 20 min after sowing). land.js sownNotice says
 * "Sown: ripe in about {n} min — then break it to harvest." (17 languages) after a seed is placed, by cropMinutes: the
 * server's own crop_due rule (crop_s × the soil's time, × moist with water within reach of the field's layer). The
 * page's cropMinutes runs here against that rule for every soil, dry and moist.
 * Run: node tests/test_a_sown_crop_says_when_it_will_be_ripe.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const server = readFileSync(join(ROOT, "scripts", "land_server.py"), "utf8");
const RULES = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8"));
const lang = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const fn = (name) => { const i = page.indexOf(`function ${name}(`); return page.slice(i, page.indexOf("\n}\n", i) + 2); };
ok(/t = F\["crop_s"\] \* F\["soil"\]\[await self\.soil_at\(face, u, v\)\]\["time"\]/.test(server) && /if await self\.moist\(face, u, v, h - 1\):\s*\n\s*t \*= F\["moist"\]/.test(server),
  "(the server's rule: crop_s × the soil's time, × moist when water is near the field under the seed)");
const F = RULES.farming;
for (const [soil, S] of Object.entries(F.soil)) {
  if (S.till === false) continue;
  for (const wet of [false, true]) {
    const asked = [];
    const cropMinutes = new Function("RULES", "Wd", "P", "colAt", "moistAt", fn("cropMinutes") + "\nreturn cropMinutes;")(
      RULES, { soilOf: () => soil }, { face: 0 }, () => ({}), (u, v, h) => { asked.push(h); return wet; });
    const want = Math.round(F.crop_s * S.time * (wet ? F.moist : 1) / 60), got = cropMinutes(1, 2, 141);
    ok(got === want && asked[0] === 140, `${soil}, ${wet ? "water near" : "dry"}: ${got} min (the server's ${want}; water looked for at the field's layer)`);
  }
}
ok(/if \(RULES\.items\[id\]\.places === B\.wheatyoung\) sownNotice\(cu, cv, ch\);/.test(page), "a seed placed says it (after the world server took it)");
ok(Object.values(lang).every((t) => (t["land.sown"] || "").includes("{n}")), "the line is in all 17 languages, the minutes kept");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
