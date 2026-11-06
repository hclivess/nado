// land_terrain.mjs — the world server's terrain oracle (scripts/land_server.py starts it beside itself): answers "which
// block does the untouched planet have here" by running static/land-world.js, the SAME generator every browser runs —
// never a second implementation of it, whose floating-point drift would let the server and the page disagree about
// what was mined. The server needs it to know what a break really yields (a player cannot claim stone where there is
// earth) and what an un-built cell goes back to.
//
// Protocol: one JSON request per line on stdin, one JSON reply per line on stdout, in order.
//   {"cells": [[face, u, v, h], ...]}  ->  {"blocks": [id, ...]}
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const W = await import(join(dirname(fileURLToPath(import.meta.url)), "..", "static", "land-world.js"));
const memo = new Map();
const col = (f, u, v) => {
  const k = (f * W.W + u) * W.W + v;
  let c = memo.get(k);
  if (!c) { if (memo.size > 500000) memo.clear(); c = W.column(f, u, v); memo.set(k, c); }
  return c;
};
const rl = createInterface({ input: process.stdin });
rl.on("line", (line) => {
  let out;
  try {
    const { cells } = JSON.parse(line);
    out = { blocks: cells.map(([f, u, v, h]) => {
      if (!(f >= 0 && f < 6 && u >= 0 && u < W.W && v >= 0 && v < W.W && Number.isInteger(h))) return -1;
      return h < 0 ? W.B.bedrock : h >= W.H ? W.B.air : W.terrainBlock(f, u, v, h, col);
    }) };
  } catch (e) { out = { error: String(e && e.message || e) }; }
  process.stdout.write(JSON.stringify(out) + "\n");
});
