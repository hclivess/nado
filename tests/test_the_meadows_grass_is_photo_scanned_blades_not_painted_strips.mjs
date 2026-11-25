// THE MEADOW'S GRASS IS PHOTO-SCANNED BLADES, NOT PAINTED STRIPS.
//
// Operator 2026-11-25: the scene "looks like some fucking Nintendo ripoff. the reference looks real"; next, "Grass". Every meadow
// clump's card was 28 strips of a flat colour gradient painted by code (land.js grassCardTexture). The card is now built from
// scanned blades — Poly Haven grass_medium_02, CC0 — by tools/land_grass.py into static/vendor/grass/grass.png, with the
// painted card's light along the blade (dark at the root) and its mean colour. Pinned:
//   1. SOURCE.txt names the CC0 scan and the PNG's bytes hash to its recorded SHA-256;
//   2. the PNG is a 512 x 512 RGBA card of blades: covered enough, darker at the root than near the tip, and with a scan's grain
//      (colour varying inside a blade, where a painted strip is one flat fill a row);
//   3. the page draws it over the painted fallback when it arrives.
//
// Run: node tests/test_the_meadows_grass_is_photo_scanned_blades_not_painted_strips.mjs
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { inflateSync } from "node:zlib";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 1
const dir = join(ROOT, "static", "vendor", "grass"), src = readFileSync(join(dir, "SOURCE.txt"), "utf8");
const png = readFileSync(join(dir, "grass.png")), sha = createHash("sha256").update(png).digest("hex");
ok(/CC0 1\.0 Universal \(public domain\)/.test(src) && /grass_medium_02/.test(src) && /polyhaven/.test(src), "SOURCE.txt names the CC0 scan (Poly Haven grass_medium_02)");
ok(new RegExp(`^grass\\.png ${sha}$`, "m").test(src), `the PNG's bytes are the recorded ones (sha256 ${sha.slice(0, 12)}…)`);

// 2 (decoded here, in Node: CI's machines have no Pillow)
function decodePng(buf) {
  let p = 8, w = 0, h = 0, ct = 0, bd = 0;
  const idat = [];
  while (p < buf.length) {
    const len = buf.readUInt32BE(p), type = buf.toString("ascii", p + 4, p + 8), data = buf.subarray(p + 8, p + 8 + len);
    if (type === "IHDR") { w = data.readUInt32BE(0); h = data.readUInt32BE(4); bd = data[8]; ct = data[9]; }
    else if (type === "IDAT") idat.push(data);
    else if (type === "IEND") break;
    p += 12 + len;
  }
  if (bd !== 8 || ct !== 6) return { w, h, mode: `bit depth ${bd}, colour type ${ct}` };
  const raw = inflateSync(Buffer.concat(idat)), bpp = 4, stride = w * bpp, px = Buffer.alloc(h * stride);
  for (let y = 0; y < h; y++) {
    const f = raw[y * (stride + 1)], src = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1)), o = y * stride;
    for (let x = 0; x < stride; x++) {
      const a = x >= bpp ? px[o + x - bpp] : 0, b = y ? px[o - stride + x] : 0, c = x >= bpp && y ? px[o - stride + x - bpp] : 0;
      let v = src[x];
      if (f === 1) v += a; else if (f === 2) v += b; else if (f === 3) v += (a + b) >> 1;
      else if (f === 4) { const q = a + b - c, pa = Math.abs(q - a), pb = Math.abs(q - b), pc = Math.abs(q - c); v += pa <= pb && pa <= pc ? a : pb <= pc ? b : c; }
      px[o + x] = v & 255;
    }
  }
  return { w, h, mode: "RGBA", px };
}
const img = decodePng(png);
ok(img.w === 512 && img.h === 512 && img.mode === "RGBA", `a 512 x 512 RGBA card (${img.w} x ${img.h} ${img.mode})`);
let cov = 0, n = 0, dsum = 0, dn = 0, root = [0, 0], tip = [0, 0];
for (let y = 0; y < img.h; y += 2) for (let x = 0; x < img.w - 2; x += 2) {
  const i = (y * img.w + x) * 4; n++;
  if (img.px[i + 3] > 200) {
    cov++;
    const L = img.px[i] + img.px[i + 1] + img.px[i + 2];
    if (y > img.h * 0.85) { root[0] += L; root[1]++; } else if (y > img.h * 0.3 && y < img.h * 0.5) { tip[0] += L; tip[1]++; }
    const j = ((y + 2) * img.w + x) * 4;          // the next pixel UP the blade: a painted strip's colour is one fill a row
    if (y + 2 < img.h && img.px[j + 3] > 200) { dsum += Math.abs(img.px[i + 1] - img.px[j + 1]); dn++; }
  }
}
ok(cov / n > 0.12, `the card is full of blades (${((100 * cov) / n).toFixed(0)} % covered)`);
ok(root[1] && tip[1] && root[0] / root[1] < 0.75 * (tip[0] / tip[1]), `darker at the root than up the blade (${(root[0] / root[1] / 3).toFixed(0)} against ${(tip[0] / tip[1] / 3).toFixed(0)}), as the reference's grass is dark to the ground`);
ok(dn && dsum / dn > 1.5, `a scan's grain: the colour varies along a blade beyond the light's ramp (mean step ${(dsum / dn).toFixed(1)} of 255)`);

// 3
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8"), gc = page.slice(page.indexOf("function grassCardTexture() {"), page.indexOf("function cardClump("));
ok(/img\.src = "\/static\/vendor\/grass\/grass\.png";/.test(gc) && /g\.drawImage\(img, 0, 0, N, N\); t\.needsUpdate = true;/.test(gc),
  "the page draws the scanned card over the painted fallback when it arrives");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
