/* Hash-based Proof of Sequential Work — browser prover/verifier, byte-for-byte with ops/posw.py.
 * blake2b / bytesToHex / hexToBytes are dependency-injected (deps) so this runs both in the miner
 * (which loads @noble/hashes) and in Node for the cross-language vector test. H(x) = blake2b(x, 32). */

function _concat(a, b) { const o = new Uint8Array(a.length + b.length); o.set(a, 0); o.set(b, a.length); return o; }
function _u32be(i) { return new Uint8Array([(i >>> 24) & 255, (i >>> 16) & 255, (i >>> 8) & 255, i & 255]); }

function _mkH(deps) { return (b) => deps.blake2b(b, { dkLen: 32 }); }

function _merkleLayers(leaves, H) {
  const layers = [leaves.slice()];
  let cur = layers[0];
  while (cur.length > 1) {
    const nxt = [];
    for (let i = 0; i < cur.length; i += 2) nxt.push(H(_concat(cur[i], i + 1 < cur.length ? cur[i + 1] : cur[i])));
    layers.push(nxt); cur = nxt;
  }
  return layers;
}
function _merkleProof(layers, idx) {
  const proof = [];
  for (let l = 0; l < layers.length - 1; l++) {
    const layer = layers[l], sib = idx ^ 1;
    proof.push(sib < layer.length ? layer[sib] : layer[idx]);
    idx = Math.floor(idx / 2);
  }
  return proof;
}
function _merkleVerify(leaf, idx, proof, root, H, eq) {
  let h = leaf;
  for (const sib of proof) { h = (idx & 1) ? H(_concat(sib, h)) : H(_concat(h, sib)); idx = Math.floor(idx / 2); }
  return eq(h, root);
}
function _fiatShamir(root, C, k, H, hex) {
  const out = [];
  for (let i = 0; i < k; i++) out.push(Number(BigInt("0x" + hex(H(_concat(root, _u32be(i)))) ) % BigInt(C)));
  return out;
}
function _segments(root, C, k, H, hex) {
  return Array.from(new Set([0, ..._fiatShamir(root, C, k, H, hex)])).sort((a, b) => a - b);
}

export function challengeBytes(address, anchorHash) {
  return new TextEncoder().encode(String(address) + "|" + String(anchorHash));
}

// build the Merkle commitment + Fiat-Shamir openings from the computed checkpoints (fast part)
function _buildProof(checkpoints, T, S, k, deps) {
  const H = _mkH(deps), hex = deps.bytesToHex, C = Math.floor(T / S);
  const layers = _merkleLayers(checkpoints, H);
  const root = layers[layers.length - 1][0];
  const segs = _segments(root, C, k, H, hex);
  const openings = segs.map((j) => ({
    j, cj: hex(checkpoints[j]), cj1: hex(checkpoints[j + 1]),
    pj: _merkleProof(layers, j).map(hex), pj1: _merkleProof(layers, j + 1).map(hex),
  }));
  return { root: hex(root), openings };
}

// prove() is intentionally slow: it walks the whole T-step sequential chain (that IS the cost).
export function poswProve(challenge, T, S, k, deps) {
  const H = _mkH(deps), C = Math.floor(T / S);
  const cps = [H(challenge)]; let h = cps[0];
  for (let m = 1; m <= C; m++) { for (let i = 0; i < S; i++) h = H(h); cps.push(h); }
  return _buildProof(cps, T, S, k, deps);
}

// same result, yielding so the browser UI stays responsive; reports (done, total) progress.
// Yields on a TIME budget (~every 12ms of work) rather than a fixed checkpoint count: with a fast (WASM)
// hash, a fixed count would hand control back far more often than needed and each setTimeout(0) is clamped
// to ~4ms by the browser, so the miner would sit idle most of the time. Time-budgeting keeps ~60fps
// responsiveness while spending nearly all wall-clock on hashing.
export async function poswProveAsync(challenge, T, S, k, deps, onProgress) {
  const H = _mkH(deps), C = Math.floor(T / S);
  const cps = [H(challenge)]; let h = cps[0]; let done = 0;
  const clock = (typeof performance !== "undefined" && performance.now) ? () => performance.now() : () => Date.now();
  let last = clock();
  for (let m = 1; m <= C; m++) {
    for (let i = 0; i < S; i++) { h = H(h); done++; }
    cps.push(h);
    if (clock() - last >= 12) {
      if (onProgress) onProgress(done, T);
      await new Promise((r) => setTimeout(r, 0));
      last = clock();
    }
  }
  if (onProgress) onProgress(done, T);
  return _buildProof(cps, T, S, k, deps);
}

export function poswVerify(challenge, proof, T, S, k, deps) {
  const H = _mkH(deps), hex = deps.bytesToHex, unhex = deps.hexToBytes;
  const eq = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);
  try {
    const C = Math.floor(T / S);
    const root = unhex(proof.root);
    const expected = _segments(root, C, k, H, hex);
    const opened = {};
    for (const o of proof.openings) opened[o.j] = o;
    const gotKeys = Object.keys(opened).map(Number).sort((a, b) => a - b);
    if (gotKeys.length !== expected.length || !gotKeys.every((v, i) => v === expected[i])) return false;
    const h0 = H(challenge);
    for (const j of expected) {
      const o = opened[j];
      const cj = unhex(o.cj), cj1 = unhex(o.cj1);
      if (!_merkleVerify(cj, j, o.pj.map(unhex), root, H, eq)) return false;
      if (!_merkleVerify(cj1, j + 1, o.pj1.map(unhex), root, H, eq)) return false;
      if (j === 0 && !eq(cj, h0)) return false;
      let h = cj;
      for (let i = 0; i < S; i++) h = H(h);
      if (!eq(h, cj1)) return false;
    }
    return true;
  } catch (e) { return false; }
}
