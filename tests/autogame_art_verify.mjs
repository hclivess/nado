// autogame_art_verify.mjs — the art module's contract, enforced: every creature, prop, gore kind and
// fatality renders NON-EMPTY, INSIDE its cell, ON the ground line, DETERMINISTICALLY, and every species
// is visually DISTINCT from every other. No canvas dependency — the art's one primitive is fillRect, so
// a 30-line fake ctx is a complete renderer.
//
// Run: node tests/autogame_art_verify.mjs        (exits non-zero on any failure)
import * as ART from "../static/autogame-art.js";

let fails = 0;
const ck = (cond, msg) => { console.log((cond ? "  PASS  " : "  FAIL  ") + msg); if (!cond) fails++; };

function paint(w, h, draw) {
  const px = new Map();                      // "x,y" -> colour, plus bounds tracking
  let minX = 1e9, maxX = -1, minY = 1e9, maxY = -1, outside = 0;
  const ctx = {
    fillStyle: "#000000", imageSmoothingEnabled: false,
    fillRect(x, y, rw, rh) {
      for (let yy = y; yy < y + rh; yy++)
        for (let xx = x; xx < x + rw; xx++) {
          if (xx < 0 || yy < 0 || xx >= w || yy >= h) { outside++; continue; }
          px.set(xx + "," + yy, ctx.fillStyle);
          minX = Math.min(minX, xx); maxX = Math.max(maxX, xx);
          minY = Math.min(minY, yy); maxY = Math.max(maxY, yy);
        }
    },
  };
  draw(ctx);
  return { px, minX, maxX, minY, maxY, outside, count: px.size };
}

const sig = (r) => {                          // a cheap order-independent visual fingerprint
  let h = 0;
  for (const [k, v] of r.px) {
    let s = 0;
    for (const c of k + v) s = (s * 31 + c.charCodeAt(0)) >>> 0;
    h = (h ^ s) >>> 0;
  }
  return h;
};

// ── every creature: all 7 frames, in-cell, grounded, deterministic ──────────────────────
{
  const cases = [];
  for (let b = 0; b < ART.BIOMES; b++) {
    for (let fam = 0; fam < 3; fam++) for (let rank = 0; rank < 2; rank++)
      cases.push({ biome: b, family: fam, rank, level: 2 + b * 4, name: ART.SPECIES_NAMES[b][fam][rank] });
    cases.push({ biome: b, family: 1, rank: 2, level: 9, name: ART.BOSS_NAMES[b] });
  }
  cases.push({ biome: 3, family: 0, rank: 0, level: 8, mimic: true, name: "mimic" });
  ck(cases.length === 36, `the bestiary holds 36 creatures (${cases.length})`);

  const sigs = new Map();
  let allOk = true, groundOk = true, detOk = true, frameDiff = true;
  for (const c of cases) {
    const frames = [];
    for (let f = 0; f < ART.MON_FRAMES; f++) {
      const r = paint(ART.MON_W, ART.MON_H, (ctx) => ART.drawMonster(ctx, 0, 0, { ...c, frame: f, scale: 1 }));
      const r2 = paint(ART.MON_W, ART.MON_H, (ctx) => ART.drawMonster(ctx, 0, 0, { ...c, frame: f, scale: 1 }));
      if (r.count < 120) { allOk = false; console.log(`        thin: ${c.name} f${f} (${r.count}px)`); }
      if (r.outside) { allOk = false; console.log(`        out-of-cell: ${c.name} f${f} (${r.outside}px)`); }
      if (sig(r) !== sig(r2)) { detOk = false; console.log(`        nondeterministic: ${c.name} f${f}`); }
      // grounded: something must touch the foot/shadow band (rows FOOT-3 .. GROUND+1)
      if (f < ART.MON_FRAMES && r.maxY < ART.MON_FOOT_Y - 4) { groundOk = false; console.log(`        floats: ${c.name} f${f} maxY=${r.maxY}`); }
      frames.push(sig(r));
    }
    if (new Set(frames).size < 5) { frameDiff = false; console.log(`        static: ${c.name} has <5 distinct frames`); }
    sigs.set(c.name + (c.mimic ? "+m" : ""), frames[0]);
  }
  ck(allOk, "every creature × frame renders substantial and inside its cell");
  ck(groundOk, "every creature stands on (or falls to) the ground band");
  ck(detOk, "same opts → same pixels, twice over");
  ck(frameDiff, "every creature ANIMATES: 5+ visually distinct frames of 7");
  const uniq = new Set(sigs.values());
  ck(uniq.size === sigs.size, `all 36 creatures are visually distinct (${uniq.size}/${sigs.size})`);
}

// ── warrior: gear kits, frames, states ───────────────────────────────────────────────────
{
  const kits = [new Array(6).fill(0),
    new Array(6).fill(0).map(() => 1 + 3 * 64 + 2 * 8),
    new Array(6).fill(0).map((_, i) => 1 + 7 * 64 + 5 * 8 + (i === 0 ? 6 : 0))];
  let ok = true, det = true, kitDiff = new Set();
  for (const gear of kits) {
    for (const opts of [{ frame: 0 }, { frame: 1 }, { frame: 2 }, { frame: 3 },
                        { frame: 1, attacking: true }, { hurt: true }, { dead: true }]) {
      const r = paint(ART.FRAME_W, ART.FRAME_H, (ctx) => ART.drawWarrior(ctx, 0, 0, { gear, scale: 1, ...opts }));
      const r2 = paint(ART.FRAME_W, ART.FRAME_H, (ctx) => ART.drawWarrior(ctx, 0, 0, { gear, scale: 1, ...opts }));
      if (r.count < 150 || r.outside) ok = false;
      if (sig(r) !== sig(r2)) det = false;
    }
    kitDiff.add(sig(paint(ART.FRAME_W, ART.FRAME_H, (ctx) => ART.drawWarrior(ctx, 0, 0, { gear, scale: 1, frame: 0 }))));
  }
  ck(ok, "the wayfarer renders whole in every kit × frame × state");
  ck(det, "the wayfarer is deterministic");
  ck(kitDiff.size === kits.length, "gear changes the silhouette (kits are distinct)");
}

// ── props: every kind × every loop frame ─────────────────────────────────────────────────
{
  let ok = true, anim = true;
  for (const kind of ART.PROP_KINDS) {
    const fr = [];
    for (let f = 0; f < ART.PROP_FRAMES; f++) {
      const r = paint(ART.PROP_W, ART.PROP_H, (ctx) => ART.drawProp(ctx, 0, 0, { kind, frame: f, scale: 1 }));
      if (r.count < 100 || r.outside) { ok = false; console.log(`        prop ${kind} f${f}: ${r.count}px out=${r.outside}`); }
      fr.push(sig(r));
    }
    if (new Set(fr).size < 2) { anim = false; console.log(`        prop ${kind} does not animate`); }
  }
  ck(ok, `all ${ART.PROP_KINDS.length} props render substantial and inside the cell`);
  ck(anim, "every prop moves on its four-count");
}

// ── gore + fatalities ────────────────────────────────────────────────────────────────────
{
  let ok = true;
  for (const kind of ART.BLOOD_KINDS)
    for (let f = 0; f < ART.BLOOD_FRAMES[kind]; f++) {
      const r = paint(ART.BLOOD_W, ART.BLOOD_H, (ctx) => ART.drawBlood(ctx, 0, 0, { kind, frame: f, scale: 1, seed: 3, amount: 6 }));
      if (r.count < 4 || r.outside) { ok = false; console.log(`        blood ${kind} f${f}: ${r.count}px out=${r.outside}`); }
    }
  ck(ok, "every blood kind × frame spills inside the box");

  const gear = new Array(6).fill(0).map(() => 1 + 4 * 64 + 1 * 8);
  let fok = true;
  ART.FATALITIES.forEach((spec, which) => {
    for (let f = 0; f < spec.frames; f++) {
      const r = paint(ART.FAT_W, ART.FAT_H, (ctx) => ART.drawFatality(ctx, 0, 0, { which, frame: f, scale: 1, gear }));
      if (r.count < 80 || r.outside) { fok = false; console.log(`        fatality ${spec.name} f${f}: ${r.count}px out=${r.outside}`); }
    }
  });
  ck(fok, `all ${ART.FATALITIES.length} fatalities play whole, start to corpse`);
}

console.log(fails ? `\n${fails} FAILURES` : "\nALL PASS");
process.exit(fails ? 1 : 0);
