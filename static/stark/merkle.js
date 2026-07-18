/* Binary Merkle over field vectors — exact port of execnode/stark/merkle.py (BLAKE2b leaves/nodes).
 * With the WASM backend (setMerkleWasm), the whole tree is built in one wasm call and layers are kept as raw
 * bytes; only the ~few path siblings actually opened are hex-encoded. Pure-JS fallback otherwise. */
import { bytesToHex } from "../vendor/nado-crypto.js";
import { b2b32, tag, i8le, hexToBytes } from "./bhash.js";

// byte-for-byte with execnode/stark/backend.py `_Blake2b` (and the wasm Merkle, vendor/blake2b-wasm.js):
// leaf = blake2b(0x00 ‖ field-as-8-LE) ; node = blake2b(0x01 ‖ fromhex(a) ‖ fromhex(b)). Was canonical-JSON,
// which the Python side no longer uses — so pure-JS-committed proofs failed Python verification.
const leaf = (x) => b2b32(tag("\x00"), i8le(x));
const node = (a, b) => b2b32(tag("\x01"), hexToBytes(a), hexToBytes(b));

let _wm = null;
export function setMerkleWasm(wm) { _wm = wm; }

export function commit(values) {
  const n = values.length;
  if (_wm && n <= _wm.NMAX && (n & (n - 1)) === 0) {
    const { layers, bytes } = _wm.commit(values);
    const rootOff = layers[layers.length - 1].off;
    const root = bytesToHex(bytes.subarray(rootOff, rootOff + 32));
    return [root, { wasm: true, layers, bytes }];
  }
  let layer = values.map(leaf); const layers = [layer];
  while (layer.length > 1) {
    const nx = []; for (let i = 0; i < layer.length; i += 2) nx.push(node(layer[i], layer[i + 1]));
    layer = nx; layers.push(layer);
  }
  return [layers[layers.length - 1][0], layers];
}

export function openAt(m, index) {
  if (m && m.wasm) {
    const path = []; let idx = index;
    for (let L = 0; L < m.layers.length - 1; L++) {
      const so = m.layers[L].off + (idx ^ 1) * 32;
      path.push(bytesToHex(m.bytes.subarray(so, so + 32)));
      idx = Math.floor(idx / 2);
    }
    return path;
  }
  const path = []; let idx = index;
  for (let L = 0; L < m.length - 1; L++) { path.push(m[L][idx ^ 1]); idx = Math.floor(idx / 2); }
  return path;
}

export function verify(root, index, value, path) {
  let h = leaf(value), idx = index;
  for (const sib of path) { h = idx % 2 === 0 ? node(h, sib) : node(sib, h); idx = Math.floor(idx / 2); }
  return h === root;
}
