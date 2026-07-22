// autogame_art_render.mjs — rasterize the art module to PNG contact sheets, no dependencies.
//
// The art file's one primitive is ctx.fillRect, which is what makes this possible: a 40-line fake ctx
// is a complete renderer. Usage:  node tests/autogame_art_render.mjs <outdir>
// Writes: warrior.png, monsters.png, props.png, fatalities.png, blood.png

import { writeFileSync, mkdirSync } from "fs";
import { deflateSync } from "zlib";
import * as ART from "../static/autogame-art.js";

const OUT = process.argv[2] || "/tmp/autogame-art";
mkdirSync(OUT, { recursive: true });

function canvas(w, h, bg = [24, 22, 34]) {
  const px = new Uint8Array(w * h * 3);
  for (let i = 0; i < w * h; i++) { px[i * 3] = bg[0]; px[i * 3 + 1] = bg[1]; px[i * 3 + 2] = bg[2]; }
  const ctx = {
    fillStyle: "#000000",
    imageSmoothingEnabled: false,
    fillRect(x, y, rw, rh) {
      const c = ctx.fillStyle;
      const r = parseInt(c.slice(1, 3), 16), g = parseInt(c.slice(3, 5), 16), b = parseInt(c.slice(5, 7), 16);
      const x0 = Math.max(0, Math.round(x)), y0 = Math.max(0, Math.round(y));
      const x1 = Math.min(w, Math.round(x + rw)), y1 = Math.min(h, Math.round(y + rh));
      for (let yy = y0; yy < y1; yy++)
        for (let xx = x0; xx < x1; xx++) {
          const i = (yy * w + xx) * 3;
          px[i] = r; px[i + 1] = g; px[i + 2] = b;
        }
    },
  };
  return { ctx, px, w, h };
}

function crc32(buf) {
  let c, table = [];
  for (let n = 0; n < 256; n++) {
    c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  let crc = 0xffffffff;
  for (const byte of buf) crc = table[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function png(path, { px, w, h }) {
  const chunk = (type, data) => {
    const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
    const body = Buffer.concat([Buffer.from(type), data]);
    const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(body));
    return Buffer.concat([len, body, crc]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8; ihdr[9] = 2; // 8-bit RGB
  const raw = Buffer.alloc(h * (1 + w * 3));
  for (let y = 0; y < h; y++) {
    raw[y * (1 + w * 3)] = 0;
    Buffer.from(px.subarray(y * w * 3, (y + 1) * w * 3)).copy(raw, y * (1 + w * 3) + 1);
  }
  writeFileSync(path, Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", ihdr), chunk("IDAT", deflateSync(raw)), chunk("IEND", Buffer.alloc(0)),
  ]));
  console.log("wrote", path, `${w}x${h}`);
}

const S = 2; // render scale

// ── warrior: 4 kits × 9 frames ──────────────────────────────────────────────────────────
{
  const kits = [
    new Array(6).fill(0),                                                       // bare
    [ART.MATERIALS && 0, 0, 0, 0, 0, 0].map((_, i) => 1 + 2 * 64 + 1 * 8 + 0),  // t2 iron
    new Array(6).fill(0).map((_, i) => 1 + 5 * 64 + 5 * 8 + (i === 0 ? 6 : 0)), // t5 gold, blazing sword
    new Array(6).fill(0).map((_, i) => 1 + 7 * 64 + 6 * 8 + (i === 2 ? 7 : 0)), // t7 meteoric, hallowed
  ];
  const cw = ART.FRAME_W * S, chh = ART.FRAME_H * S;
  const cv = canvas(cw * 9, chh * kits.length);
  kits.forEach((gear, r) => ART.drawWarriorSheet(cv.ctx, 0, r * chh, { gear, scale: S }));
  png(`${OUT}/warrior.png`, cv);
}

// ── monsters: every species × 7 frames ──────────────────────────────────────────────────
{
  const rows = [];
  for (let b = 0; b < ART.BIOMES; b++)
    for (let fam = 0; fam < 3; fam++)
      for (let rank = 0; rank < 2; rank++)
        rows.push({ biome: b, family: fam, rank, level: 1 + b * 4 + rank * 2 });
  for (let b = 0; b < ART.BIOMES; b++) rows.push({ biome: b, family: b % 3, rank: 2, level: 9 + b * 3 });
  rows.push({ biome: 2, family: 0, rank: 0, level: 8, mimic: true });
  const cw = ART.MON_W * S, chh = ART.MON_H * S;
  const cv = canvas(cw * ART.MON_FRAMES, chh * rows.length);
  rows.forEach((o, r) => ART.drawMonsterSheet(cv.ctx, 0, r * chh, { ...o, scale: S }));
  png(`${OUT}/monsters.png`, cv);
}

// ── props: kind × 4 frames ──────────────────────────────────────────────────────────────
{
  const cw = ART.PROP_W * S, chh = ART.PROP_H * S;
  const cv = canvas(cw * ART.PROP_FRAMES, chh * ART.PROP_KINDS.length);
  ART.PROP_KINDS.forEach((kind, r) => {
    for (let f = 0; f < ART.PROP_FRAMES; f++)
      ART.drawProp(cv.ctx, f * cw, r * chh, { kind, frame: f, scale: S });
  });
  png(`${OUT}/props.png`, cv);
}

// ── fatalities: which × frames ──────────────────────────────────────────────────────────
{
  const gear = new Array(6).fill(0).map((_, i) => 1 + 4 * 64 + 2 * 8);
  const maxF = Math.max(...ART.FATALITIES.map((s) => s.frames));
  const cw = ART.FAT_W * S, chh = ART.FAT_H * S;
  const cv = canvas(cw * maxF, chh * ART.FATALITIES.length);
  ART.FATALITIES.forEach((spec, r) => {
    for (let f = 0; f < spec.frames; f++)
      ART.drawFatality(cv.ctx, f * cw, r * chh, { which: r, frame: f, scale: S, gear });
  });
  png(`${OUT}/fatalities.png`, cv);
}

// ── blood: kind × frames ────────────────────────────────────────────────────────────────
{
  const maxF = Math.max(...Object.values(ART.BLOOD_FRAMES));
  const cw = ART.BLOOD_W * S, chh = ART.BLOOD_H * S;
  const cv = canvas(cw * maxF, chh * ART.BLOOD_KINDS.length, [40, 38, 50]);
  ART.BLOOD_KINDS.forEach((kind, r) => {
    for (let f = 0; f < ART.BLOOD_FRAMES[kind]; f++)
      ART.drawBlood(cv.ctx, f * cw, r * chh, { kind, frame: f, scale: S, seed: 7, amount: 6 });
  });
  png(`${OUT}/blood.png`, cv);
}
