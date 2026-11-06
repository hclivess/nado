// land-snap.js — where a new piece really goes: lined up with the pieces around it (static/land.js placement() calls it;
// pure, so tests drive it directly).
//
// SNAPPING ("could building have some sort of snapping to other pieces to be easier? maybe also when like two poles are
// placed, they have the same levelled height", "at least same-type blocks should snap", operator 2026-11-06). A piece is
// [x, z, y, w, d, h, m] in centimetres inside its plot (land-world BOXES). On each axis the new piece moves by the
// smallest shift that lines one of its edges up with a neighbour's — the same edge (two poles' bottoms level, a row of
// planks' faces in line), the opposite edge (flush against it, no gap), or the centres — if that shift is small: up to
// SAME_TOL for a neighbour of the same material, OTHER_TOL for any other. The axis it was placed against (its face on a
// piece's face) is already exact and keeps. A shift that would make the piece overlap anything is not taken.
export const SAME_TOL = 20, OTHER_TOL = 6, NEAR = 200, FLUSH_BIAS = 4;     // cm

const overlap = (a, b) => a[0] < b[0] + b[3] && b[0] < a[0] + a[3] && a[1] < b[1] + b[4] && b[1] < a[1] + a[4] && a[2] < b[2] + b[5] && b[2] < a[2] + a[5];
const gap = (a, b, i) => Math.max(0, b[i] - (a[i] + a[i + 3]), a[i] - (b[i] + b[i + 3]));

/** The piece `box` lined up with `list` (the plot's pieces); `fixed`: the axis it was placed against, or -1. */
export function snapBox(box, list, fixed = -1) {
  const near = list.filter((o) => gap(box, o, 0) <= NEAR && gap(box, o, 1) <= NEAR && gap(box, o, 2) <= NEAR);
  if (!near.length) return box;
  const out = box.slice();
  for (let i = 0; i < 3; i++) {
    if (i === fixed) continue;
    let best = null;
    for (const o of near) {
      const tol = o[6] === box[6] ? SAME_TOL : OTHER_TOL;
      const lo = out[i], hi = out[i] + out[i + 3], olo = o[i], ohi = o[i] + o[i + 3];
      for (const [s, flush] of [[olo - lo, 0], [ohi - hi, 0], [ohi - lo, 1], [olo - hi, 1], [(olo + ohi) / 2 - (lo + hi) / 2, 0]]) {
        const shift = Math.round(s);
        if (Math.abs(shift) > tol) continue;
        // the smaller shift wins; a same-material neighbour wins a tie; lining up the SAME edge beats sitting flush on the
        // far edge by FLUSH_BIAS (a plank beside a row is meant level with it, not stacked 2 cm higher on its top)
        const rank = Math.abs(shift) - (o[6] === box[6] ? 0.5 : 0) + (flush ? FLUSH_BIAS : 0);
        if (!best || rank < best.rank) best = { shift, rank };
      }
    }
    if (!best || !best.shift) continue;
    const moved = out.slice(); moved[i] += best.shift;
    if (!list.some((o) => overlap(moved, o))) out[i] = moved[i];
  }
  return out;
}
