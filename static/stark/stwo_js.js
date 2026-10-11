/* The WALLET side of the Stwo shielded pool (doc/stwo-migration.md §5.1): the note algebra, the depth-48 tree, the
 * packed witness the WASM prover takes, and the `stwo_js` bundle the exec layer accepts (execnode/state.py
 * _apply_stwo_transfer). Loaded only when the chain says the pool is live (protocol STWO_POOL_HEIGHT); until then
 * nothing imports it at runtime.
 *
 * THE HASH IS THE CIRCUIT'S, BYTE FOR BYTE, and this file is a port of execnode/shielded_stwo.py — read that file's
 * docstring for the layout. H = BLAKE2s-256 of ONE 64-byte block of sixteen little-endian u32 words:
 *     owner = H(21, nsk[0..8])        cm = H(22, lo(v), hi(v), owner[0..8], lo(rho), hi(rho))
 *     nf    = H(23, nsk[0..8], lo(rho), hi(rho))        node = H(left[0..8], right[0..8])
 * Digests travel as 64-hex (the 32 bytes in word order). tests/test_stwo_wallet_note_algebra_matches_the_node.py
 * pins this file against the Python on vectors; a change here alone is a note nobody can spend.
 *
 * PROVING NEVER RUNS ON THE MAIN THREAD. proveSpend() starts a module Worker (./stwo_worker.js) per proof, which
 * fetches /static/vendor/stwo_js.wasm, seeds it from crypto.getRandomValues, proves, verifies its own proof exactly as
 * a node does, and is terminated — a fresh instance per proof, so its ~300 MiB is returned at once on a phone. The
 * StwoCore class is the same driver without the Worker, for the worker itself and for Node tests.
 *
 * BLAKE2s is implemented here from RFC 7693 (the vendored nado-crypto has BLAKE2b only); blake2s() is checked against
 * the RFC's Appendix B vector and Python's hashlib in the test above.
 */

// ---- user-facing errors, in the wallet's language ---------------------------------------------------------------
// The wallet speaks 16 languages (static/i18n.js). On the page window.t translates; in the Worker and in Node there is
// no window, so the English default is used and the error carries its key (i18nKey / i18nVars): _inWorker re-raises it
// on the page through _err again, translated there. Keys live in static/i18n/shield.json (tests/i18n_coverage.mjs reads
// static/stark/ too). Internal invariant errors (bad hex, a wrong-length digest) stay English: no user can reach them.
function _fill(fb, vars) { return String(fb).replace(/\{(\w+)\}/g, (m, n) => (vars && vars[n] != null ? String(vars[n]) : m)); }
function _err(k, fb, vars) { const e = new Error(typeof window !== "undefined" && window.t ? window.t(k, fb, vars) : _fill(fb, vars)); e.i18nKey = k; e.i18nVars = vars || null; e.i18nDefault = fb; return e; }
/** An error raised in the Worker, re-raised on the page in the page's language (the key travels with the message). */
export function errFromWorker(d) {
  if (d && d.key && d.fallback) return _err(d.key, d.fallback, d.vars || undefined);
  return _err("shield.stwoFailed", "the prover failed");
}
/** The prover file could not be fetched (HTTP status `s`) — raised in the Worker. */
export function errDownload(s) { return _err("shield.stwoDownload", "the private-banknote prover could not be downloaded (HTTP {s})", { s }); }

// ---- BLAKE2s-256 (RFC 7693) -----------------------------------------------------------------------------------
const IV = new Uint32Array([0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A, 0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19]);
const SIGMA = [
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15], [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
  [11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4], [7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8],
  [9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13], [2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9],
  [12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11], [13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10],
  [6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5], [10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0],
];
const rotr = (x, n) => ((x >>> n) | (x << (32 - n))) >>> 0;

function _compress(h, block, t, last) {
  const v = new Uint32Array(16), m = new Uint32Array(16);
  for (let i = 0; i < 16; i++) m[i] = block[4 * i] | (block[4 * i + 1] << 8) | (block[4 * i + 2] << 16) | (block[4 * i + 3] << 24);
  for (let i = 0; i < 8; i++) { v[i] = h[i]; v[i + 8] = IV[i]; }
  v[12] ^= t >>> 0; v[13] ^= Math.floor(t / 0x100000000) >>> 0;
  if (last) v[14] ^= 0xFFFFFFFF;
  const G = (a, b, c, d, x, y) => {
    v[a] = (v[a] + v[b] + x) >>> 0; v[d] = rotr(v[d] ^ v[a], 16);
    v[c] = (v[c] + v[d]) >>> 0;     v[b] = rotr(v[b] ^ v[c], 12);
    v[a] = (v[a] + v[b] + y) >>> 0; v[d] = rotr(v[d] ^ v[a], 8);
    v[c] = (v[c] + v[d]) >>> 0;     v[b] = rotr(v[b] ^ v[c], 7);
  };
  for (let r = 0; r < 10; r++) {
    const s = SIGMA[r];
    G(0, 4, 8, 12, m[s[0]], m[s[1]]); G(1, 5, 9, 13, m[s[2]], m[s[3]]);
    G(2, 6, 10, 14, m[s[4]], m[s[5]]); G(3, 7, 11, 15, m[s[6]], m[s[7]]);
    G(0, 5, 10, 15, m[s[8]], m[s[9]]); G(1, 6, 11, 12, m[s[10]], m[s[11]]);
    G(2, 7, 8, 13, m[s[12]], m[s[13]]); G(3, 4, 9, 14, m[s[14]], m[s[15]]);
  }
  for (let i = 0; i < 8; i++) h[i] = (h[i] ^ v[i] ^ v[i + 8]) >>> 0;
}

/** BLAKE2s (unkeyed) of `data` (Uint8Array), `outlen` bytes (1..32) -> Uint8Array. */
export function blake2s(data, outlen = 32) {
  data = data instanceof Uint8Array ? data : new Uint8Array(data);
  if (!(outlen >= 1 && outlen <= 32)) throw new Error("blake2s: outlen is 1..32");
  const h = new Uint32Array(IV);
  h[0] ^= 0x01010000 ^ outlen;
  let t = 0, off = 0;
  const block = new Uint8Array(64);
  // every full block but the last (an empty message is one all-zero final block)
  while (data.length - off > 64) {
    block.set(data.subarray(off, off + 64)); t += 64; off += 64;
    _compress(h, block, t, false);
  }
  block.fill(0); block.set(data.subarray(off)); t += data.length - off;
  _compress(h, block, t, true);
  const out = new Uint8Array(32);
  for (let i = 0; i < 8; i++) { out[4 * i] = h[i]; out[4 * i + 1] = h[i] >>> 8; out[4 * i + 2] = h[i] >>> 16; out[4 * i + 3] = h[i] >>> 24; }
  return out.slice(0, outlen);
}

// ---- hex / words -----------------------------------------------------------------------------------------------
export function toHex(b) { let s = ""; for (const x of b) s += x.toString(16).padStart(2, "0"); return s; }
export function fromHex(s) {
  s = String(s);
  if (s.length % 2 || /[^0-9a-fA-F]/.test(s)) throw new Error("bad hex");
  const b = new Uint8Array(s.length / 2);
  for (let i = 0; i < b.length; i++) b[i] = parseInt(s.slice(2 * i, 2 * i + 2), 16);
  return b;
}
function _words(d) {         // a 64-hex digest -> its eight little-endian u32 words
  const b = fromHex(d);
  if (b.length !== 32) throw new Error("a digest is 32 bytes");
  const w = [];
  for (let i = 0; i < 8; i++) w.push((b[4 * i] | (b[4 * i + 1] << 8) | (b[4 * i + 2] << 16) | (b[4 * i + 3] << 24)) >>> 0);
  return w;
}
const MASK64 = (1n << 64n) - 1n;
function _u64(x) {
  x = BigInt(x);
  if (x < 0n || x > MASK64) throw new Error("a value or rho is a u64");
  return [Number(x & 0xFFFFFFFFn), Number(x >> 32n)];
}
function _h(words16) {
  if (words16.length !== 16) throw new Error("one BLAKE2s block is sixteen u32 words");
  const b = new Uint8Array(64);
  words16.forEach((w, i) => { w = w >>> 0; b[4 * i] = w; b[4 * i + 1] = w >>> 8; b[4 * i + 2] = w >>> 16; b[4 * i + 3] = w >>> 24; });
  return toHex(blake2s(b));
}

// ---- the note algebra (execnode/shielded_stwo.py) --------------------------------------------------------------
export const DEPTH = 48;
export const DOM_OWNER = 21, DOM_CM = 22, DOM_NF = 23;
export const EMPTY_LEAF = "00".repeat(32);

/** nsk: 64-hex (the 256-bit spend key, eight u32 words) -> the owner digest, 64-hex. */
export function ownerOf(nsk) { return _h([DOM_OWNER, ..._words(nsk), 0, 0, 0, 0, 0, 0, 0]); }
export function commit(value, owner, rho) { return _h([DOM_CM, ..._u64(value), ..._words(owner), ..._u64(rho), 0, 0, 0]); }
export function nullifier(nsk, rho) { return _h([DOM_NF, ..._words(nsk), ..._u64(rho), 0, 0, 0, 0, 0]); }
export function node(left, right) { return _h([..._words(left), ..._words(right)]); }

let _EMPTY = null;
function EMPTY() {
  if (!_EMPTY) { _EMPTY = [EMPTY_LEAF]; for (let i = 0; i < DEPTH; i++) _EMPTY.push(node(_EMPTY[i], _EMPTY[i])); }
  return _EMPTY;
}
export function emptyRoot() { return EMPTY()[DEPTH]; }

/** The root of the append-only tree over `leaves` (64-hex), the shielded_stwo._Frontier rule. */
export function treeRoot(leaves) {
  const E = EMPTY(), left = new Array(DEPTH).fill(null);
  let n = 0;
  for (const leaf of leaves) {
    let i = 0, cur = String(leaf).toLowerCase(), k = n;
    while (k & 1) { cur = node(left[i], cur); k = Math.floor(k / 2); i++; }
    left[i] = cur; n++;
  }
  if (n === 0) return E[DEPTH];
  let cur = null, k = n;
  for (let i = 0; i < DEPTH; i++) {
    if (k % 2 === 1) cur = node(left[i], cur !== null ? cur : E[i]);
    else if (cur !== null) cur = node(cur, E[i]);
    k = Math.floor(k / 2);
  }
  return cur;
}

/** {sibs, dirs, root} for leaf `pos`: dirs[i] = 1 when the node is the RIGHT child at level i (the circuit's rule). */
export function treePath(leaves, pos) {
  const E = EMPTY();
  let level = leaves.map((x) => String(x).toLowerCase()), i = Number(pos);
  if (!(i >= 0 && i < level.length)) throw _err("shield.stwoNotInPool", "that banknote is not in the pool yet: try again in a minute");
  const sibs = [], dirs = [];
  for (let d = 0; d < DEPTH; d++) {
    const sib = i ^ 1;
    sibs.push(sib < level.length ? level[sib] : E[d]);
    dirs.push(i & 1);
    const next = [];
    for (let k = 0; 2 * k < level.length; k++) next.push(node(level[2 * k], 2 * k + 1 < level.length ? level[2 * k + 1] : E[d]));
    level = next; i >>= 1;
  }
  return { sibs, dirs, root: level[0] };
}

/** The circuit's `aux` public input for an unshield destination ("" for a private transfer), 64-hex:
 *  BLAKE2s-256(b"NADO/stwo-js/aux/v1\0" || dest UTF-8) (native/stwo_js lib.rs aux_of). */
export const AUX_DOMAIN = "NADO/stwo-js/aux/v1\0";
export function auxOf(dest) {
  const a = new TextEncoder().encode(AUX_DOMAIN), b = new TextEncoder().encode(String(dest || ""));
  const m = new Uint8Array(a.length + b.length); m.set(a); m.set(b, a.length);
  return toHex(blake2s(m));
}

// ---- the WASM ABI (native/stwo_js/src/prover.rs, "the wallet's WASM ABI") ----------------------------------------
export const ABI_VERSION = 1;
export const RC = { OK: 0, BAD_ARGS: 1, MALFORMED: 2, REJECTED: 3, PANIC: 4, NO_SEED: 5, SEED_REUSED: 6, NOT_A_JOINSPLIT: 7 };
export const WITNESS_BYTES = 32 + 8 + 8 + DEPTH * 32 + DEPTH + 8 + 32 + 8 + 8 + 32 + 8 + 8 + 8;

function _le64(x) { const b = new Uint8Array(8); let v = BigInt(x); if (v < 0n || v > MASK64) throw new Error("a value is a u64"); for (let i = 0; i < 8; i++) { b[i] = Number(v & 0xFFn); v >>= 8n; } return b; }
function _rd64(b, o) { let v = 0n; for (let i = 7; i >= 0; i--) v = (v << 8n) | BigInt(b[o + i]); return v; }

/** The packed witness prover.rs wallet_witness reads. Conservation v_in = v1 + v2 + fee + unshield is checked here
 *  too (the WASM refuses it anyway), so the wallet says what is wrong instead of a code. */
export function packWitness(w) {
  const vin = BigInt(w.vIn), v1 = BigInt(w.v1), v2 = BigInt(w.v2), un = BigInt(w.unshield || 0), fee = BigInt(w.fee || 0);
  if (vin !== v1 + v2 + fee + un) throw _err("shield.stwoUnbalanced", "the spend does not balance: the banknote's value must equal both outputs plus the fee and the withdrawal");
  if (w.sibs.length !== DEPTH || w.dirs.length !== DEPTH) throw new Error("the path is not depth " + DEPTH);
  const parts = [fromHex(w.nsk), _le64(vin), _le64(w.rho), ...w.sibs.map(fromHex), Uint8Array.from(w.dirs.map(Number)),
    _le64(v1), fromHex(w.o1), _le64(w.r1), _le64(v2), fromHex(w.o2), _le64(w.r2), _le64(un), _le64(fee)];
  const out = new Uint8Array(WITNESS_BYTES);
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  if (o !== WITNESS_BYTES) throw new Error("witness packing");
  return out;
}

/** The output record (prover.rs wallet_output) -> {root, nf, cm1, cm2, unshield, fee, proof}. proof: Uint8Array. */
export function parseOutput(b) {
  if (!(b instanceof Uint8Array) || b.length < 144) throw _err("shield.stwoNoProof", "the prover returned no proof");
  const d = (i) => toHex(b.subarray(32 * i, 32 * i + 32));
  return { root: d(0), nf: d(1), cm1: d(2), cm2: d(3), unshield: _rd64(b, 128), fee: _rd64(b, 136), proof: b.slice(144) };
}

/** The exact bundle execnode/state.py _apply_stwo_transfer accepts. withdraw_addr only with an unshield: a private
 *  transfer is bound to the empty destination, and the node verifies it against "" whatever the bundle says. */
export function buildBundle(out, withdrawAddr) {
  const un = BigInt(out.unshield), fee = BigInt(out.fee);
  const bundle = { stark: { stwo_js: { proof: toHex(out.proof), root: out.root, nf: out.nf, cm_out1: out.cm1, cm_out2: out.cm2,
    unshield: un.toString(), fee: fee.toString() } } };
  if (un > 0n) {
    if (!withdrawAddr) throw _err("shield.stwoNeedDest", "a withdrawal needs a destination address");
    bundle.withdraw_addr = withdrawAddr;
  }
  return bundle;
}

/** Drives one instance of the WASM (no Worker): the worker below, and tests in Node. */
export class StwoCore {
  static async instantiate(wasmBytes) {
    const { instance } = await WebAssembly.instantiate(wasmBytes, {});
    const c = new StwoCore(); c.x = instance.exports;
    if (c.x.stwo_abi_version() !== ABI_VERSION) throw _err("shield.stwoAbi", "the private-banknote prover on this page is out of date: reload the page");
    return c;
  }
  _put(bytes) { const p = this.x.stwo_alloc(bytes.length); new Uint8Array(this.x.memory.buffer, p, bytes.length).set(bytes); return p; }
  _call(bytes, f) { const p = this._put(bytes); try { return f(p, bytes.length); } finally { this.x.stwo_free(p, bytes.length); } }
  /** 32 random bytes -> RC.OK, RC.NO_SEED (all zero) or RC.SEED_REUSED. */
  seed(bytes32) { if (bytes32.length !== 32) throw new Error("a seed is 32 bytes"); return this._call(bytes32, (p) => this.x.stwo_seed(p)); }
  /** packed witness + destination -> {rc, out (Uint8Array | null)} */
  prove(witness, dest) {
    const d = new TextEncoder().encode(String(dest || ""));
    const pw = this._put(witness), pd = this._put(d);
    try {
      const rc = this.x.stwo_prove(pw, witness.length, pd, d.length);
      if (rc !== RC.OK) return { rc, out: null };
      return { rc, out: new Uint8Array(this.x.memory.buffer, this.x.stwo_out_ptr(), this.x.stwo_out_len()).slice() };
    } finally { this.x.stwo_free(pw, witness.length); this.x.stwo_free(pd, d.length); }
  }
  verifyOut(dest) { const d = new TextEncoder().encode(String(dest || "")); return this._call(d, (p, n) => this.x.stwo_verify_out(p, n)); }
  aux(dest) {
    const d = new TextEncoder().encode(String(dest || "")), po = this.x.stwo_alloc(32);
    try { this._call(d, (p, n) => this.x.stwo_aux(p, n, po)); return toHex(new Uint8Array(this.x.memory.buffer, po, 32)); }
    finally { this.x.stwo_free(po, 32); }
  }
}

/** One proof, inside a Worker: seed, prove, self-verify. -> output record bytes, or throws with the reason. */
export async function proveWith(core, witness, dest, randomBytes) {
  const rcs = core.seed(randomBytes(32));
  if (rcs === RC.SEED_REUSED) throw _err("shield.stwoSeedReused", "the prover refused a reused random seed");
  if (rcs !== RC.OK) throw _err("shield.stwoNoSeed", "the prover got no random seed");
  const { rc, out } = core.prove(witness, dest);
  if (rc === RC.NOT_A_JOINSPLIT) throw _err("shield.stwoNotJoinsplit", "this spend is not valid for that banknote");
  if (rc !== RC.OK) throw _err("shield.stwoProverCode", "the prover failed (code {c})", { c: rc });
  const v = core.verifyOut(dest);
  if (v !== RC.OK) throw _err("shield.stwoSelfVerify", "the proof made on this device does not verify (code {c})", { c: v });
  return out;
}

/** Main-thread entry: prove spending the note at `pos` of `leaves` and return {bundle, root, nf, cm1, cm2, ms}.
 *  spend = {nsk, vIn, rho, v1, o1, r1, v2, o2, r2, unshield, fee, dest}. The proof is made in a Worker; the returned
 *  public inputs are checked against this file's own algebra (root of the path, nf, both output commitments) before
 *  anything is returned, so a prover and wallet that disagree never publish. `run(witness, dest)` -> output bytes
 *  replaces the Worker (Node tests drive a StwoCore directly); the browser never passes it. */
export async function proveSpend(spend, leaves, pos, run) {
  const path = treePath(leaves, pos);
  const owner = ownerOf(spend.nsk);
  if (commit(spend.vIn, owner, spend.rho) !== String(leaves[pos]).toLowerCase()) throw _err("shield.stwoNotMine", "that banknote does not belong to this wallet");
  const un = BigInt(spend.unshield || 0), dest = un > 0n ? String(spend.dest || "") : "";
  const witness = packWitness({ ...spend, sibs: path.sibs, dirs: path.dirs });
  const t0 = Date.now();
  const out = parseOutput(await (run || _inWorker)(witness, dest));
  const want = { root: path.root, nf: nullifier(spend.nsk, spend.rho), cm1: commit(spend.v1, spend.o1, spend.r1), cm2: commit(spend.v2, spend.o2, spend.r2) };
  for (const k of Object.keys(want)) if (out[k] !== want[k]) throw _err("shield.stwoDisagree", "the prover and the wallet disagree on {k}: nothing was sent", { k });
  return { bundle: buildBundle(out, dest), ...want, ms: Date.now() - t0 };
}

function _inWorker(witness, dest) {
  return new Promise((resolve, reject) => {
    let w;
    try { w = new Worker("/static/stark/stwo_worker.js", { type: "module" }); }
    catch (e) { reject(_err("shield.stwoNoWorkers", "private banknotes need a browser with Web Workers")); return; }
    const done = (f, v) => { try { w.terminate(); } catch (e) { /* already gone */ } f(v); };
    w.onmessage = (ev) => (ev.data && ev.data.ok ? done(resolve, new Uint8Array(ev.data.out)) : done(reject, errFromWorker(ev.data)));
    w.onerror = (ev) => { if (ev && ev.preventDefault) ev.preventDefault(); done(reject, _err("shield.stwoStopped", "the prover stopped: {m}", { m: (ev && ev.message) || "worker error" })); };
    w.postMessage({ witness, dest }, [witness.buffer]);
  });
}
