/*
 * test_garments_are_makehuman_outfits_split_at_the_waist_into_the_wardrobes_slots_and_shoes_on_every_build.mjs — #172
 * step 3 (the characters' clothes were colours painted on the body). static/human/wear.bin's clothes items as
 * tools/human/build_wear.py writes them from MakeHuman's CC0 outfits, read by land-human-data.js parseWear:
 *   1. an outfit for the male builds and one for the female, and shoes — each with a texture beside it and a part a vertex;
 *   2. the outfit splits at the waist: its shirt vertices lie over the hips joint less 8 cm in EVERY build, its trousers
 *      under, and both parts are there (a shirt that is all trousers is a cut at the wrong height); shoes sit at the feet;
 *   3. the parts are drawn by the wardrobe's slots: wornOf reads the look's body and legs slots and dresses a look with
 *      no slots at all (a townsperson's) in both;
 *   4. skinned to the body: the shirt's weight on the torso and arm bones, the trousers' on the hips and legs, the shoes'
 *      on the feet and shins.
 * Run: node tests/test_garments_are_makehuman_outfits_split_at_the_waist_into_the_wardrobes_slots_and_shoes_on_every_build.mjs
 */
import { readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Hd = await import(join(ROOT, "static", "land-human-data.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const load = (f) => { const r = readFileSync(join(ROOT, "static", "human", f)); return r.buffer.slice(r.byteOffset, r.byteOffset + r.byteLength); };
const W = Hd.parseWear(load("wear.bin")), D = Hd.parseHuman(load("crew.bin"));
const clothes = W.items.filter((it) => it.kind === "clothes");
const male = clothes.find((it) => it.name.startsWith("male_")), female = clothes.find((it) => it.name.startsWith("female_")), shoes = clothes.find((it) => it.name.startsWith("shoes"));

// 1. the items
ok(male && female && shoes, `an outfit for the male builds, one for the female, and shoes: ${clothes.map((i) => i.name).join(", ")}`);
ok(clothes.every((it) => existsSync(join(ROOT, "static", "human", it.tex)) && it.part && it.part.length === it.nV), "every garment has its texture beside it and a part a vertex");
ok(W.items.filter((it) => it.kind !== "clothes").every((it) => it.part && it.part.every((p) => p === Hd.PART.none)), "hair and eyebrows carry no part");

// 2. the waist and the feet, in every build
for (let v = 0; v < 3; v++) {
  const hips = D.vars[v].heads[Hd.B.hips][1], waist = hips - 0.08, ankle = D.vars[v].heads[Hd.B.ft[0]][1];
  for (const it of [male, female]) {
    let top = 0, legs = 0, bad = 0;
    for (let i = 0; i < it.nV; i++) {
      const y = it.pos[v][i * 3 + 1], p = it.part[i];
      if (p === Hd.PART.top) { top++; if (y < waist - 0.12) bad++; } else if (p === Hd.PART.legs) { legs++; if (y > waist + 0.12) bad++; } else bad++;
    }
    ok(top > 200 && legs > 200 && bad / it.nV < 0.02, `${D.vars[v].name}: ${it.name} splits at the waist (${top} shirt vertices over it, ${legs} trousers under, ${bad} astray)`);
  }
  let low = 0;
  for (let i = 0; i < shoes.nV; i++) if (shoes.pos[v][i * 3 + 1] < ankle + 0.25) low++;
  ok(low === shoes.nV && shoes.part.every((p) => p === Hd.PART.shoes), `${D.vars[v].name}: the shoes sit at the feet (all ${shoes.nV} vertices within 25 cm over the ankle)`);
}

// 3. the slots
ok(JSON.stringify(Hd.wornOf({ worn: { body: "linen_shirt" } })) === JSON.stringify({ body: true, legs: false })
   && JSON.stringify(Hd.wornOf({ worn: {} })) === JSON.stringify({ body: false, legs: false })
   && JSON.stringify(Hd.wornOf({ skin: 1 })) === JSON.stringify({ body: true, legs: true }), "wornOf: the wardrobe's body and legs slots; a look without slots (a townsperson) wears both");

// 4. skinned to the right bones
const share = (it, bones, only) => { let w = 0, t = 0; for (let i = 0; i < it.nV; i++) { if (only != null && it.part[i] !== only) continue; for (let j = 0; j < 4; j++) { t += it.skinW[i * 4 + j]; if (bones.includes(it.skinI[i * 4 + j])) w += it.skinW[i * 4 + j]; } } return w / t; };
const torso = [Hd.B.hips, Hd.B.spine, Hd.B.chest, Hd.B.neck, ...Hd.B.sh, ...Hd.B.ua, ...Hd.B.fa], legsB = [Hd.B.hips, ...Hd.B.th, ...Hd.B.sn], feet = [...Hd.B.ft, ...Hd.B.sn];
for (const it of [male, female]) {
  ok(share(it, torso, Hd.PART.top) > 0.9, `${it.name}: the shirt's weight is on the torso and arms (${(100 * share(it, torso, Hd.PART.top)).toFixed(0)} %)`);
  ok(share(it, legsB, Hd.PART.legs) > 0.9, `${it.name}: the trousers' weight is on the hips and legs (${(100 * share(it, legsB, Hd.PART.legs)).toFixed(0)} %)`);
}
ok(share(shoes, feet, null) > 0.9, `shoes: the weight is on the feet and shins (${(100 * share(shoes, feet, null)).toFixed(0)} %)`);

// 5. LIFTED OFF THE BODY (the operator's real-GPU screenshot, 2026-11-12): a garment is pushed out along its skinned
// normal — 2 cm for an outfit, 6 mm for shoes, 4 mm for the brows — so it never loses the depth test to the body under it
const hv = readFileSync(join(ROOT, "static", "land-human.js"), "utf8");
ok(/function wearMaterial\(tex, map, lum, dark, clothes, lums, lift = 0\)/.test(hv) && /m\.positionNode = lift \? skinned\(T, false\)\.add\(nrm\.mul\(float\(lift\)\)\) : skinned\(T, false\);/.test(hv), "a worn item's position is its skinned position pushed out along its skinned normal by `lift`");
ok(/const lift = clothes \? \(it\.name\.startsWith\("shoes"\) \? 0\.006 : 0\.02\) : it\.kind === "eyebrows" \? 0\.004 : 0;/.test(hv), "an outfit is lifted 2 cm, shoes 6 mm, the brows 4 mm, hair not at all");
ok(/clamp\(dot\(tx\.rgb, vec3\(0\.2126, 0\.7152, 0\.0722\)\)\.div\(float\(Math\.max\(0\.05, lum\)\)\), 0\.25, 1\.6\)/.test(hv), "hair keeps its texture's light and dark: never black, never blown out");

console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
