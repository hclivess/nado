// btcleg.js — the §6.5 Bitcoin P2WSH HTLC, client side (doc/dex-bridge.md). Pure functions, no
// dependencies: assembles the SAME witness script scripts/otc_btc_leg.py builds (parity-tested against it)
// and derives its bech32 P2WSH address. The wallet never signs Bitcoin here — this only shows a swap party
// the exact script/address for the foreign leg, to fund from any BTC wallet and verify by eye.
//   OP_IF SHA256 <H> EQUALVERIFY <claimPub> CHECKSIG OP_ELSE <T> CLTV DROP <refundPub> CHECKSIG OP_ENDIF

const hexToBytes = (h) => new Uint8Array((h.match(/../g) || []).map((x) => parseInt(x, 16)));
const bytesToHex = (b) => Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");

function scriptnum(n) {                      // minimal CScriptNum (the CLTV operand)
  const out = [];
  while (n > 0) { out.push(n & 0xff); n = Math.floor(n / 256); }
  if (out.length && out[out.length - 1] & 0x80) out.push(0);
  return new Uint8Array(out);
}

export function htlcScript(hHex, claimPubHex, refundPubHex, locktime) {
  const H = hexToBytes(hHex), cp = hexToBytes(claimPubHex), rp = hexToBytes(refundPubHex);
  if (H.length !== 32) throw new Error("hashlock must be 32 bytes hex");
  if (cp.length !== 33 || rp.length !== 33) throw new Error("pubkeys must be 33-byte compressed hex");
  if (!(Number.isInteger(locktime) && locktime > 0 && locktime < 2 ** 32))
    throw new Error("locktime must be a whole number below 2^32 (nLockTime is 32 bits)");
  const ln = scriptnum(locktime);
  const parts = [[0x63, 0xa8, 0x20], H, [0x88, 0x21], cp, [0xac, 0x67, ln.length], ln,
                 [0xb1, 0x75, 0x21], rp, [0xac, 0x68]];
  const flat = [];
  for (const p of parts) flat.push(...p);
  return bytesToHex(new Uint8Array(flat));
}

// ---- bech32 (BIP-173, v0 only) — mirrors scripts/otc_btc_leg.py exactly -------------------------------
const B32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l";
function polymod(v) {
  const G = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3];
  let chk = 1;
  for (const x of v) {
    const b = chk >>> 25;
    chk = ((chk & 0x1ffffff) << 5) ^ x;
    for (let i = 0; i < 5; i++) if ((b >>> i) & 1) chk ^= G[i];
  }
  return chk >>> 0;
}
function bech32Encode(hrp, ver, prog) {
  const data = [ver];
  let acc = 0, bits = 0;
  for (const b of prog) {
    acc = (acc << 8) | b; bits += 8;
    while (bits >= 5) { bits -= 5; data.push((acc >>> bits) & 31); }
  }
  if (bits) data.push((acc << (5 - bits)) & 31);
  const exp = [...hrp].map((c) => c.charCodeAt(0) >>> 5).concat([0], [...hrp].map((c) => c.charCodeAt(0) & 31));
  const poly = polymod(exp.concat(data, [0, 0, 0, 0, 0, 0])) ^ 1;
  const chk = Array.from({ length: 6 }, (_, i) => (poly >>> (5 * (5 - i))) & 31);
  return hrp + "1" + data.concat(chk).map((d) => B32[d]).join("");
}

export async function p2wshAddress(scriptHex, hrp = "bc") {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", hexToBytes(scriptHex)));
  return bech32Encode(hrp, 0, digest);
}
