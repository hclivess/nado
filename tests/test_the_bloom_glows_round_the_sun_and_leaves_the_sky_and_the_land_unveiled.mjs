// The bloom glows round the sun and leaves the sky and the land unveiled (2026-11-22, the Chlorophyll shot).
//
// At a threshold of 0.92 the whole bright sky and every cloud bloomed; blurred over the frame, that was a grey veil on
// everything dark: the same view drawn without the effects (?plain) measured the far forest (32, 51, 27) and a shaded
// patch of meadow (30, 44, 13), with them (54, 68, 54) and (75, 84, 47) — against the reference's forest (43, 54, 28).
//   1. the bloom's threshold is over the sky's brightness (above 1.5: a lit cloud's top reads about 1-1.3 before tone
//      mapping) and under the sun disc's (drawn at 6x its star's colour), so the sun still glows;
//   2. the pipeline uses that threshold, not a number of its own.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const th = Number((page.match(/const BLOOM_THRESHOLD = ([\d.]+);/) || [])[1]);
const sun = Number((page.match(/sunDisc\.material\.color\.setRGB\((\d+) \* star\.colour\[0\]/) || [])[1]);
ok(th > 1.5 && sun && th < sun, `the bloom's threshold (${th}) is over the sky's brightness and under the sun disc's (${sun}x)`);
ok(page.includes("main.add(bloom(main, 0.18, 0.35, BLOOM_THRESHOLD))") && !/bloom\(main, [\d.]+, [\d.]+, [\d.]+\)/.test(page), "the pipeline blooms at that threshold");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
