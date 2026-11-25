// A CROWN'S LEAVES ARE PHOTO SCANS, NOT PAINTED SHAPES.
//
// Operator 2026-11-25: "trees liok like 2002 garbage", "yours looks like some fucking Nintendo ripoff. the reference looks
// real". Every crown's leaves were vector shapes drawn by code (land.js paintLeaves): flat fills and a drawn midrib, a
// cartoon however they were tinted. The broadleaf and birch clusters are now built from scans of real leaves — ambientCG
// LeafSet009, CC0 — by tools/land_leaves.py into static/vendor/leaves/leaves.png. Pinned:
//   1. SOURCE.txt states the CC0 licence and the source, and the PNG's bytes hash to its recorded SHA-256;
//   2. the PNG is the atlas's top row: 1024 x 512 RGBA, both tiles full of leaves (coverage), with a scan's detail — the
//      colour varies inside a leaf, where a painted shape is one flat fill (fine-grained contrast measured on covered pixels);
//   3. the page loads it into the leaf atlas's top two tiles (paintLeaves), the painted ones only as the fallback, and the
//      far forest's bake waits for it, so the far cards are pictures of the scanned crowns.
//
// Run: node tests/test_a_crowns_leaves_are_photo_scans_not_painted_shapes.mjs
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { inflateSync } from "node:zlib";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 1. licence, source, bytes
const dir = join(ROOT, "static", "vendor", "leaves"), src = readFileSync(join(dir, "SOURCE.txt"), "utf8");
const png = readFileSync(join(dir, "leaves.png")), sha = createHash("sha256").update(png).digest("hex");
ok(/CC0 1\.0 Universal \(public domain\)/.test(src) && /ambientcg\.com/.test(src) && /LeafSet009/.test(src), "SOURCE.txt names the CC0 scans (ambientCG LeafSet009)");
ok(new RegExp(`^leaves\\.png ${sha}$`, "m").test(src), `the PNG's bytes are the recorded ones (sha256 ${sha.slice(0, 12)}…)`);

// 2. the atlas row: size, coverage, a scan's grain — decoded here, in Node (CI's machines have no Pillow: the first version read
// the PNG through python3 -c "from PIL …" and died there, exit 1 with nothing checked, 2026-11-25)
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
ok(img.w === 1024 && img.h === 512 && img.mode === "RGBA", `the PNG is the atlas's top row, 1024 x 512 RGBA (${img.w} x ${img.h} ${img.mode})`);
for (const [t, name] of [[0, "broadleaf"], [1, "birch"]]) {
  let cov = 0, n = 0, dsum = 0, dn = 0;
  if (img.px) for (let y = 0; y < img.h; y += 2) for (let x = t * 512; x < (t + 1) * 512 - 2; x += 2) {
    const i = (y * img.w + x) * 4; n++;
    if (img.px[i + 3] > 200) { cov++; const j = i + 8; if (img.px[j + 3] > 200) { dsum += Math.abs(img.px[i + 1] - img.px[j + 1]); dn++; } }
  }
  const coverage = n ? cov / n : 0, grain = dn ? dsum / dn : 0;
  // (a cluster is BRANCH SPRAYS with sky between them, not a disc — 2026-11-25: discs read as a crown of rosettes at 60 m — so a
  // quarter of the tile is leaves; the crown's many overlapping cards fill it, as the vale photographs check)
  ok(coverage > 0.25, `the ${name} tile is full of leaves (${(coverage * 100).toFixed(0)} % covered)`);
  // a painted shape is one flat fill: neighbouring covered pixels differ by ~0 except at its edges; a scan's veins and blemishes
  ok(grain > 2.5, `…and has a scan's grain, the colour varying inside a leaf (mean step ${grain.toFixed(1)} of 255)`);
}

// 3. the page's use
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const pl = page.slice(page.indexOf("function paintLeaves() {"), page.indexOf("// WATER: lakes and the sea"));
ok(/img\.src = "\/static\/vendor\/leaves\/leaves\.png";/.test(pl) && /for \(let y = 0; y < Math\.min\(T, img\.height\); y\+\+\)/.test(pl) && /tex\.needsUpdate = true;\n        done\(true\);/.test(pl),
  "paintLeaves loads the scanned clusters into the atlas's top two tiles once they arrive (the painted ones the fallback)");
ok(/leaves\.userData\.ready = leafTex\.userData\.ready;/.test(page)
  && /if \(matLeaves && matLeaves\.userData\.ready\) await Promise\.race\(\[matLeaves\.userData\.ready, new Promise\(\(r\) => setTimeout\(r, 8000\)\)\]\);/.test(page),
  "the far forest's bake waits for the scans (8 s at most), so the far cards are pictures of the scanned crowns");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
