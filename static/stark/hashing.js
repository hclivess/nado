/* Shared BLAKE2b-over-canonical-JSON for the browser prover — injected once (matches Python blake2b_hash). */
let _h = null;
export function initHashing(blake2bHash) { _h = blake2bHash; }
export function H(parts) { if (!_h) throw new Error("stark hashing not initialised"); return _h(parts); }
