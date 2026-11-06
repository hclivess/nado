// land-level.js — levelling a building site (static/land.js L with a shovel; pure, so tests level real terrain).
//
// "it is currently not possible to level ground i think to have a nice clean structure" (operator, 2026-11-06); Enshrouded
// and Valheim level a site with a hoe before the foundation. The column (u, v) is made flat at layer T: natural cells above
// T are dug out, cell T becomes EDITED earth (untouched turf there is dug and replaced), hollows below T are filled with
// earth (down to depth), and an untouched air cell just above T is made an exact one (an earth placed and dug straight
// back, nothing spent). Edited cells sit on whole layers (land-world fieldOf: +1 / -1), so the surface comes out at
// exactly T + 1; an untouched air cell would blend it up to 17 cm high. The ops are plain breaks (block 0) and earth
// placements, in order — the world server judges each as ever.
import { B, BLOCKS, NATURAL, LITTER, TREE_LEAVES, TREE_WOOD, H } from "./land-world.js";

/** [[u, v, h, block], ...] for column (u, v) to lie flat at layer T. w: { block(u, v, h), edited(u, v, h), top(u, v) };
 *  axe: the player carries one, so a trunk standing in the site is felled with the rest (else it is left, a bump). */
export function levelOps(w, u, v, T, depth = 3, axe = false) {
  const ops = [];
  // a loose stone, a stick or a bush's leaves in the way come up by hand like the ground (each stood where the site's
  // surface must be: a dent or a bump of up to 17 cm); a tree trunk is felled when the player carries an axe (the world
  // server brings its crown down with it) and is otherwise left — a bump the page warns of
  for (let h = Math.min(H - 1, Math.max(w.top(u, v), T) + 2); h > T; h--) {
    const b = w.block(u, v, h);
    if (NATURAL.has(b) || LITTER.has(b) || TREE_LEAVES.has(b) || (axe && TREE_WOOD.has(b))) ops.push([u, v, h, B.air]);
    else if (b === B.air && !w.edited(u, v, h) && h === T + 1) ops.push([u, v, h, B.dirt], [u, v, h, B.air]);
  }
  const bt = w.block(u, v, T);
  if ((NATURAL.has(bt) && !w.edited(u, v, T)) || LITTER.has(bt)) ops.push([u, v, T, B.air], [u, v, T, B.dirt]);
  else if (bt === B.air || BLOCKS[bt].liquid) ops.push([u, v, T, B.dirt]);
  for (let h = T - 1; h >= T - depth; h--) {
    const b = w.block(u, v, h);
    if (b === B.air || BLOCKS[b].liquid) ops.push([u, v, h, B.dirt]); else break;
  }
  return ops;
}
/** Earth the ops need on balance: what they place, less the earth their own digs give back (grass and earth give one). */
export function earthNeeded(ops, w) {
  let need = 0, have = 0;
  for (const [u, v, h, b] of ops) {
    if (b === B.dirt) { if (have > 0) have--; else need++; }
    else { const was = w.block(u, v, h); if (was === B.grass || was === B.dirt) have++; }
  }
  return need;
}

/** Does a tree trunk stand in column (u, v) just above layer T? (levelling without an axe leaves it) */
export const trunkIn = (w, u, v, T) => [1, 2].some((d) => TREE_WOOD.has(w.block(u, v, T + d)));
