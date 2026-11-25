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
import { execFileSync } from "node:child_process";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 1. licence, source, bytes
const dir = join(ROOT, "static", "vendor", "leaves"), src = readFileSync(join(dir, "SOURCE.txt"), "utf8");
const png = readFileSync(join(dir, "leaves.png")), sha = createHash("sha256").update(png).digest("hex");
ok(/CC0 1\.0 Universal \(public domain\)/.test(src) && /ambientcg\.com/.test(src) && /LeafSet009/.test(src), "SOURCE.txt names the CC0 scans (ambientCG LeafSet009)");
ok(new RegExp(`^leaves\\.png ${sha}$`, "m").test(src), `the PNG's bytes are the recorded ones (sha256 ${sha.slice(0, 12)}…)`);

// 2. the atlas row: size, coverage, a scan's detail (python + Pillow read the PNG; the suite's machines have both)
const stats = JSON.parse(execFileSync("python3", ["-I", "-c", `
import json,sys
from PIL import Image
a=Image.open(sys.argv[1]); print(json.dumps({"size":a.size,"mode":a.mode}) if a.mode!="RGBA" else "", end="")
w,h=a.size; px=a.load(); out={"size":[w,h],"mode":a.mode,"tiles":[]}
for t in range(2):
  cov=0; n=0; diffs=[]
  for y in range(0,h,2):
    for x in range(t*512,(t+1)*512-2,2):
      r,g,b,al=px[x,y]; n+=1
      if al>200:
        cov+=1; r2,g2,b2,a2=px[x+2,y]
        if a2>200: diffs.append(abs(g-g2))
  diffs.sort(); out["tiles"].append({"coverage":cov/n,"grain":sum(diffs)/max(1,len(diffs))})
print(json.dumps(out))`, join(dir, "leaves.png")], { encoding: "utf8" }).trim().split("\n").pop());
ok(stats.size[0] === 1024 && stats.size[1] === 512 && stats.mode === "RGBA", `the PNG is the atlas's top row, 1024 x 512 RGBA (${stats.size.join(" x ")} ${stats.mode})`);
for (const [i, name] of [[0, "broadleaf"], [1, "birch"]]) {
  const t = stats.tiles[i];
  ok(t.coverage > 0.3, `the ${name} tile is full of leaves (${(t.coverage * 100).toFixed(0)} % covered)`);
  // a painted shape is one flat fill: neighbouring covered pixels differ by ~0 except at its edges; a scan's veins and blemishes
  ok(t.grain > 2.5, `…and has a scan's grain, the colour varying inside a leaf (mean step ${t.grain.toFixed(1)} of 255)`);
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
