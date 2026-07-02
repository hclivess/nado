/* Binary Merkle over field vectors — exact port of execnode/stark/merkle.py (BLAKE2b leaves/nodes). */
import { H } from "./hashing.js";
const leaf = (x) => H(["stark-leaf", String(BigInt(x))]);
const node = (a, b) => H(["stark-node", a, b]);
export function commit(values) {
  let layer = values.map(leaf); const layers = [layer];
  while (layer.length > 1) {
    const nx = []; for (let i = 0; i < layer.length; i += 2) nx.push(node(layer[i], layer[i + 1]));
    layer = nx; layers.push(layer);
  }
  return [layers[layers.length - 1][0], layers];
}
export function openAt(layers, index) {
  const path = []; let idx = index;
  for (let L = 0; L < layers.length - 1; L++) { path.push(layers[L][idx ^ 1]); idx = Math.floor(idx / 2); }
  return path;
}
export function verify(root, index, value, path) {
  let h = leaf(value), idx = index;
  for (const sib of path) { h = idx % 2 === 0 ? node(h, sib) : node(sib, h); idx = Math.floor(idx / 2); }
  return h === root;
}
