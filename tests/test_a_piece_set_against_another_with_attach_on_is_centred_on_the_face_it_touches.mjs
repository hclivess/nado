/*
 * test_a_piece_set_against_another_with_attach_on_is_centred_on_the_face_it_touches.mjs — ATTACH POINTS (#187, the
 * Kerbal half "attach nodes and symmetry"; symmetry shipped as Mirror). With Attach on, a piece placed against another is
 * centred on the face it touches, as a part clicks onto a node in KSP, instead of wherever the aim hit:
 *   1. land-snap.js attachTo: against each of the six faces the piece's middle lands on the neighbour's middle on the two
 *      axes of that face, and the placed axis is left flush; whole centimetres; a piece larger than the face is centred
 *      too (it overhangs evenly);
 *   2. the page applies it only with Attach on and only against a piece (not on the ground), AFTER the edge snapping
 *      (which would pull it to an edge) and before the plot clamp; the switch sits beside Mirror, is kept with the piece
 *      settings, and the piece line says so — its words in 17 languages;
 *   3. with Mirror on too, the twin is made from the attached piece, so a pair lands centred on both sides.
 * Run: node tests/test_a_piece_set_against_another_with_attach_on_is_centred_on_the_face_it_touches.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const { attachTo } = await import(join(ROOT, "static", "land-snap.js"));
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 1. the six faces of a hull 300 x 150 x 40 cm at (1000, 2000, 500)
const hull = [1000, 2000, 500, 300, 150, 40, 64];
const mid = (b, i) => b[i] + b[i + 3] / 2;
const cases = [
  ["+x (its east end)", [1300, 2017, 523, 40, 60, 30, 65], 0],
  ["-x (its west end)", [960, 2091, 501, 40, 60, 30, 65], 0],
  ["+z (its north side)", [1210, 2150, 512, 50, 80, 20, 65], 1],
  ["-z (its south side)", [1033, 1920, 509, 50, 80, 20, 65], 1],
  ["+y (on top)", [1191, 2003, 540, 70, 40, 25, 66], 2],
  ["-y (under it)", [1007, 2101, 470, 70, 40, 30, 66], 2],
];
for (const [name, box, ax] of cases) {
  const a = attachTo(box, hull, ax);
  const centred = [0, 1, 2].filter((i) => i !== ax).every((i) => Math.abs(mid(a, i) - mid(hull, i)) <= 0.5);
  ok(centred && a[ax] === box[ax] && a.slice(3).join() === box.slice(3).join() && a.slice(0, 3).every(Number.isInteger),
    `against ${name}: centred on the face on its two axes, still flush on the third, its size and kind kept: ${a.slice(0, 3).join(", ")}`);
}
const wide = attachTo([1300, 1900, 500, 40, 400, 40, 65], hull, 0);
ok(wide[1] === 1875 && wide[1] + wide[4] - (hull[1] + hull[4]) === hull[1] - wide[1], "a piece wider than the face overhangs it evenly on both sides");
const same = cases[0][1], before = same.slice();
attachTo(same, hull, 0);
ok(same.join() === before.join(), "attachTo leaves the box it is given untouched (a new box comes back)");

// 2. the page
const pl = page.slice(page.indexOf("function placement(a)"), page.indexOf("\n}\n", page.indexOf("function placement(a)")));
const iSnap = pl.indexOf("box = snapBox(box, rec0.list"), iAtt = pl.indexOf("if (piece.attach && a.box) box = attachTo(box, a.box.b, ax);"), iClamp = pl.indexOf("box[0] = Math.max(0, Math.min(Wd.PLOT_CM - w, box[0]))");
ok(iSnap > 0 && iAtt > iSnap && iClamp > iAtt, "the page centres a piece only with Attach on and against a piece, after the edge snapping and before the plot clamp");
ok(pl.indexOf("Wd.mirrorPiece(p, a.box.b)") > iAtt, "…and Mirror's twin is made from the attached piece, so a pair lands centred on both sides");
ok(page.includes('import { snapBox, piecesFor, restOnGround, attachTo } from "./land-snap.js";'), "the page takes attachTo from land-snap.js");
ok(page.includes('id="pzAttach"') && page.includes('$("pzAttach").onclick = () => { piece.attach = !piece.attach;'), "the Attach switch sits in the bag beside Mirror");
ok(page.includes("piece.attach = piece.attach === true;") && page.includes("mirror: piece.mirror, attach: piece.attach,"), "…and is kept with the piece settings (saved, reloaded, carried through a size change)");
ok(page.includes('(piece.attach ? " · " + T("attachOn"'), "the piece line says it is on");
const tr = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
ok(Object.keys(tr).length === 17 && Object.values(tr).every((l) => l["land.attach"] && l["land.attachHint"] && l["land.attachOn"]), "its words are in all 17 languages");

console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
