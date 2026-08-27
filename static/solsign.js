// solsign.js — Solana leg of the OTC cross-chain swap (doc/dex-bridge.md §6.5), in the browser.
// The counterpart of btcsign.js and ethsign.js: derives the swap's escrow address, builds and signs the
// fund/claim/refund transactions, and talks JSON-RPC. Self-contained apart from the vendored ed25519.
//
// Solana specifics that shape this file:
//  * ADDRESSES ARE base58 of 32 raw bytes, not hex.
//  * THE ESCROW IS A PDA — an address derived from the swap's terms that no private key can control, so
//    only the program can move the money. Deriving it means hashing the seeds and REJECTING any result
//    that happens to be a valid ed25519 point (a curve point could have a private key behind it); the
//    bump byte counts down until an off-curve result is found. Same rule the program applies on chain.
//  * A LEGACY TRANSACTION is a compact-array format with a 3-byte header and INDEXES into one account
//    list, so building one means collecting every account, ordering it (signers first, then writable),
//    and then referring to each by position.
import * as ed from "./vendor/noble-ed25519.js?v=1";

const B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
export function b58encode(bytes) {
  let n = 0n;
  for (const b of bytes) n = n * 256n + BigInt(b);
  let out = "";
  while (n > 0n) { out = B58[Number(n % 58n)] + out; n /= 58n; }
  for (const b of bytes) { if (b === 0) out = "1" + out; else break; }
  return out || "1";
}
export function b58decode(str) {
  let n = 0n;
  for (const c of str) { const v = B58.indexOf(c); if (v < 0) throw new Error("bad base58 character"); n = n * 58n + BigInt(v); }
  const out = [];
  while (n > 0n) { out.unshift(Number(n & 0xffn)); n >>= 8n; }
  for (const c of str) { if (c === "1") out.unshift(0); else break; }
  return new Uint8Array(out);
}
const cat = (...a) => { const t = a.reduce((n, x) => n + x.length, 0), r = new Uint8Array(t); let o = 0;
  for (const x of a) { r.set(x, o); o += x.length; } return r; };
const sha256 = async (b) => new Uint8Array(await crypto.subtle.digest("SHA-256", b));
const u64le = (n) => { const b = new Uint8Array(8); let v = BigInt(n); for (let i = 0; i < 8; i++) { b[i] = Number(v & 0xffn); v >>= 8n; } return b; };
const i64le = (n) => u64le(BigInt(n) < 0n ? (1n << 64n) + BigInt(n) : BigInt(n));
function compactU16(n) {                                   // Solana's shortvec length prefix
  const out = [];
  for (;;) { let b = n & 0x7f; n >>= 7; if (n) { out.push(b | 0x80); } else { out.push(b); break; } }
  return new Uint8Array(out);
}

export const SYSTEM_PROGRAM = "11111111111111111111111111111111";

/** A fresh per-swap keypair. The secret is the 32-byte seed; the address is base58 of the public key. */
export async function solKeypair() {
  const sk = crypto.getRandomValues(new Uint8Array(32));
  const pk = await ed.getPublicKeyAsync(sk);
  return { k: [...sk].map((x) => x.toString(16).padStart(2, "0")).join(""), address: b58encode(pk) };
}
export async function solAddressOf(secretHex) {
  const sk = new Uint8Array(secretHex.match(/../g).map((x) => parseInt(x, 16)));
  return b58encode(await ed.getPublicKeyAsync(sk));
}

// A PDA has no private key, which is the whole point: the escrow can only be moved by the program. It is
// found by hashing the seeds with a descending bump until the digest is NOT a valid curve point.
function onCurve(bytes) {
  try { ed.ExtendedPoint.fromHex(bytes); return true; } catch (e) { return false; }
}
export async function findPda(seeds, programId) {
  const pid = b58decode(programId);
  const tail = cat(pid, new TextEncoder().encode("ProgramDerivedAddress"));
  for (let bump = 255; bump >= 0; bump--) {
    const h = await sha256(cat(...seeds, new Uint8Array([bump]), tail));
    if (!onCurve(h)) return { address: b58encode(h), bump };
  }
  throw new Error("no off-curve address for those seeds");
}
/** The swap's escrow address. Every term is a seed, so the ADDRESS IS THE AGREEMENT (see the program). */
export function htlcSeeds(hashlockHex, claimant, funder, deadline, lamports) {
  return [new TextEncoder().encode("htlc"),
          new Uint8Array(hashlockHex.match(/../g).map((x) => parseInt(x, 16))),
          b58decode(claimant), b58decode(funder), i64le(deadline), u64le(lamports)];
}
export const htlcPda = (programId, hashlockHex, claimant, funder, deadline, lamports) =>
  findPda(htlcSeeds(hashlockHex, claimant, funder, deadline, lamports), programId);

// ---- instructions (tags match the program's dispatch) ---------------------------------------------------
const hex2 = (h) => new Uint8Array((h || "").match(/../g).map((x) => parseInt(x, 16)));
export const ixFund = (programId, funder, lock, hashlockHex, claimant, deadline, lamports) => ({
  programId,
  keys: [{ pubkey: funder, isSigner: true, isWritable: true },
         { pubkey: lock, isSigner: false, isWritable: true },
         { pubkey: SYSTEM_PROGRAM, isSigner: false, isWritable: false }],
  data: cat(new Uint8Array([0]), hex2(hashlockHex), b58decode(claimant), i64le(deadline), u64le(lamports)),
});
export const ixClaim = (programId, caller, lock, claimant, preimageHex) => ({
  programId,
  keys: [{ pubkey: caller, isSigner: true, isWritable: false },
         { pubkey: lock, isSigner: false, isWritable: true },
         { pubkey: claimant, isSigner: false, isWritable: true }],
  data: cat(new Uint8Array([1]), hex2(preimageHex)),
});
export const ixRefund = (programId, caller, lock, funder) => ({
  programId,
  keys: [{ pubkey: caller, isSigner: true, isWritable: false },
         { pubkey: lock, isSigner: false, isWritable: true },
         { pubkey: funder, isSigner: false, isWritable: true }],
  data: new Uint8Array([2]),
});

// ---- a legacy transaction: one account list, everything else indexes into it ----------------------------
function compileMessage(payer, ixs, blockhash) {
  const meta = new Map();                                   // address -> {signer, writable}
  const touch = (pk, signer, writable) => {
    const m = meta.get(pk) || { signer: false, writable: false };
    meta.set(pk, { signer: m.signer || signer, writable: m.writable || writable });
  };
  touch(payer, true, true);
  for (const ix of ixs) { for (const k of ix.keys) touch(k.pubkey, k.isSigner, k.isWritable); touch(ix.programId, false, false); }
  const all = [...meta.entries()];
  const rank = (e) => (e[1].signer ? 0 : 2) + (e[1].writable ? 0 : 1);   // signers first, writable first
  all.sort((a, b) => (a[0] === payer ? -1 : b[0] === payer ? 1 : rank(a) - rank(b)));
  const keys = all.map((e) => e[0]);
  const numSigners = all.filter((e) => e[1].signer).length;
  const numReadonlySigned = all.filter((e) => e[1].signer && !e[1].writable).length;
  const numReadonlyUnsigned = all.filter((e) => !e[1].signer && !e[1].writable).length;
  const idx = (pk) => keys.indexOf(pk);
  const parts = [new Uint8Array([numSigners, numReadonlySigned, numReadonlyUnsigned]),
                 compactU16(keys.length), ...keys.map(b58decode), b58decode(blockhash),
                 compactU16(ixs.length)];
  for (const ix of ixs) {
    parts.push(new Uint8Array([idx(ix.programId)]));
    parts.push(compactU16(ix.keys.length), new Uint8Array(ix.keys.map((k) => idx(k.pubkey))));
    parts.push(compactU16(ix.data.length), ix.data);
  }
  return { message: cat(...parts), signerAddresses: keys.slice(0, numSigners) };
}

/** Build, sign and return the wire bytes. `secrets` maps an address to its 32-byte seed hex. */
export async function buildTx(payer, ixs, blockhash, secrets) {
  const { message, signerAddresses } = compileMessage(payer, ixs, blockhash);
  const sigs = [];
  for (const addr of signerAddresses) {
    const sk = secrets[addr];
    if (!sk) throw new Error("no key for required signer " + addr);
    sigs.push(await ed.signAsync(message, hex2(sk)));
  }
  return cat(compactU16(sigs.length), ...sigs, message);
}

// ---- JSON-RPC -------------------------------------------------------------------------------------------
export async function solRpc(url, method, params) {
  const r = await (await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }) })).json();
  if (r.error) throw new Error(r.error.message || JSON.stringify(r.error));
  return r.result;
}
export const solBalance = (url, addr) =>
  solRpc(url, "getBalance", [addr, { commitment: "confirmed" }]).then((r) => BigInt(r.value));
export const solBlockhash = (url) =>
  solRpc(url, "getLatestBlockhash", [{ commitment: "finalized" }]).then((r) => r.value.blockhash);

const b64 = (bytes) => { let s = ""; for (const b of bytes) s += String.fromCharCode(b); return btoa(s); };

/** Send and wait for confirmation. Returns the signature, or throws with the chain's own reason. */
export async function solSend(url, payer, ixs, secrets) {
  const raw = await buildTx(payer, ixs, await solBlockhash(url), secrets);
  const sig = await solRpc(url, "sendTransaction", [b64(raw), { encoding: "base64", preflightCommitment: "processed" }]);
  for (let i = 0; i < 40; i++) {
    const st = (await solRpc(url, "getSignatureStatuses", [[sig]])).value[0];
    if (st && (st.confirmationStatus === "confirmed" || st.confirmationStatus === "finalized")) {
      if (st.err) throw new Error("transaction failed: " + JSON.stringify(st.err));
      return sig;
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error("sent (" + sig + ") but not confirmed yet");
}
