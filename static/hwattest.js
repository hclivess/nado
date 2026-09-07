// hwattest.js — hardware-wallet device attestation from the browser (doc/device-attestation.md §Hardware).
//
// Both vendors give a PER-DEVICE key certified at the factory — the thing "one device, one identity" binds. Their
// FIDO2 mode (batch certificates) is refused; these are the vendors' own genuineness protocols, spoken directly:
//   Ledger  — WebHID (Chrome/Edge/Brave). The secure-channel handshake of ledgerblue.checkGenuine: we present a
//             self-signed "unsafe manager" certificate (the device asks the user to allow it — that is the tap),
//             then the device returns its Issuer certificate (device key signed by Ledger) and an ephemeral
//             certificate signed by the device key over BOTH nonces; ours is the registration challenge.
//   Trezor  — WebUSB (Chrome/Edge/Brave). `AuthenticateDevice{challenge}`: the Safe's secure element signs the
//             challenge and returns its X.509 chain (device cert → Trezor CA, root = a per-model key pinned in
//             protocol). The device asks the user to confirm on screen — the tap. Trezor One / Model T are refused
//             by the kernel (no secure element).
// The statement is packed into the SAME {att, cdj, rp} envelope as a WebAuthn one (CBOR attestationObject with
// fmt "ledger"/"trezor"; clientData type "nado.hw"), so the transaction shape and the node's kernel path are shared.
// Nothing here touches coins: the hardware wallet only vouches for the wallet address, it does not hold its key.

import * as secp from "./vendor/noble-secp256k1.js?v=1";

const te = new TextEncoder();
const b64 = (u8) => btoa(String.fromCharCode(...u8));
const b64url = (u8) => b64(u8).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const hex = (u8) => Array.from(u8, (b) => b.toString(16).padStart(2, "0")).join("");
const cat = (...parts) => { const n = parts.reduce((a, p) => a + p.length, 0); const o = new Uint8Array(n); let i = 0; for (const p of parts) { o.set(p, i); i += p.length; } return o; };
async function sha256(u8) { return new Uint8Array(await crypto.subtle.digest("SHA-256", u8)); }

// ---- minimal CBOR encoder (maps with text keys, byte strings, arrays, text, small unsigned ints) ---------------
function cborHead(major, n) {
  if (n < 24) return Uint8Array.of((major << 5) | n);
  if (n < 256) return Uint8Array.of((major << 5) | 24, n);
  if (n < 65536) return Uint8Array.of((major << 5) | 25, n >> 8, n & 255);
  return Uint8Array.of((major << 5) | 26, (n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255);
}
export function cbor(v) {
  if (v instanceof Uint8Array) return cat(cborHead(2, v.length), v);
  if (typeof v === "string") { const b = te.encode(v); return cat(cborHead(3, b.length), b); }
  if (Array.isArray(v)) return cat(cborHead(4, v.length), ...v.map(cbor));
  if (typeof v === "number") return cborHead(0, v);
  if (v && typeof v === "object") { const ks = Object.keys(v); return cat(cborHead(5, ks.length), ...ks.map((k) => cat(cbor(k), cbor(v[k])))); }
  throw new Error("cbor: unsupported value");
}

function envelope(fmt, attStmt, challenge, vendorNote) {
  const att = cbor({ fmt, attStmt, authData: new Uint8Array(0) });
  const cdj = te.encode(JSON.stringify({ type: "nado.hw", challenge: b64url(challenge), origin: location.origin, vendor: vendorNote }));
  return { att: b64(att), cdj: b64(cdj), rp: "hw" };
}

// ================================================================= LEDGER (WebHID) =================================
const LEDGER_VENDOR_ID = 0x2c97;
const HID_CHANNEL = 0x0101, HID_TAG = 0x05, HID_PACKET = 64;

export async function connectLedger() {
  if (!navigator.hid) throw new Error("WebHID is not available in this browser — use Chrome, Edge or Brave on a computer.");
  const devs = await navigator.hid.requestDevice({ filters: [{ vendorId: LEDGER_VENDOR_ID }] });
  const dev = devs && devs[0];
  if (!dev) throw new Error("No Ledger selected.");
  if (!dev.opened) await dev.open();
  return { kind: "ledger", dev, name: dev.productName || "Ledger" };
}

function hidWrap(apdu) {
  const out = [];
  let seq = 0, off = 0;
  const first = new Uint8Array(HID_PACKET);
  first.set([HID_CHANNEL >> 8, HID_CHANNEL & 255, HID_TAG, 0, 0, apdu.length >> 8, apdu.length & 255]);
  const n0 = Math.min(apdu.length, HID_PACKET - 7);
  first.set(apdu.subarray(0, n0), 7); off = n0; out.push(first); seq = 1;
  while (off < apdu.length) {
    const p = new Uint8Array(HID_PACKET);
    p.set([HID_CHANNEL >> 8, HID_CHANNEL & 255, HID_TAG, seq >> 8, seq & 255]);
    const n = Math.min(apdu.length - off, HID_PACKET - 5);
    p.set(apdu.subarray(off, off + n), 5); off += n; seq++; out.push(p);
  }
  return out;
}

async function ledgerExchange(dev, apdu, timeoutMs = 120000) {
  const packets = hidWrap(apdu);
  let expected = -1, got = new Uint8Array(0);
  const done = new Promise((resolve, reject) => {
    const timer = setTimeout(() => { dev.removeEventListener("inputreport", onRep); reject(new Error("Ledger did not answer (confirm the prompt on the device).")); }, timeoutMs);
    function onRep(e) {
      const d = new Uint8Array(e.data.buffer, e.data.byteOffset, e.data.byteLength);
      if (((d[0] << 8) | d[1]) !== HID_CHANNEL || d[2] !== HID_TAG) return;
      const seq = (d[3] << 8) | d[4];
      let body;
      if (seq === 0) { expected = (d[5] << 8) | d[6]; body = d.subarray(7); got = new Uint8Array(0); }
      else body = d.subarray(5);
      got = cat(got, body);
      if (expected >= 0 && got.length >= expected) {
        clearTimeout(timer); dev.removeEventListener("inputreport", onRep);
        resolve(got.subarray(0, expected));
      }
    }
    dev.addEventListener("inputreport", onRep);
  });
  try {
    for (const p of packets) await dev.sendReport(0, p);
  } catch (e) {
    done.catch(() => {});                                 // the listener/timer are released by the timeout path
    throw new Error("Ledger transfer failed (unplugged, or another tab / Ledger Live holds it): " + (e && e.message || e));
  }
  const r = await done;
  const sw = (r[r.length - 2] << 8) | r[r.length - 1];
  if (sw !== 0x9000) {
    if (sw === 0x6985) throw new Error("Refused on the Ledger (the 'Allow unsafe manager' prompt was declined).");
    if (sw === 0x5515) throw new Error("The Ledger is locked — enter the PIN on the device and retry.");
    throw new Error(`Ledger answered 0x${sw.toString(16)} to APDU ${hex(apdu.subarray(0, 4))}`);
  }
  return r.subarray(0, r.length - 2);
}

function apdu(cla, ins, p1, p2, data = new Uint8Array(0)) {
  return cat(Uint8Array.of(cla, ins, p1, p2, data.length), data);
}

function derInt(u8) {                                    // DER INTEGER: strip leading zeros, keep a 0x00 pad if the high bit is set
  let i = 0; while (i < u8.length - 1 && u8[i] === 0) i++;
  const body = u8.subarray(i);
  const pad = body[0] & 0x80 ? [0] : [];
  return cat(Uint8Array.of(0x02, body.length + pad.length), Uint8Array.from(pad), body);
}
async function ecdsaDer(priv, msg) {
  const h = await sha256(msg);
  const sig = await secp.signAsync(h, priv);           // RFC 6979, low-S; the device verifies sha256(msg)
  // the vendored noble v2 Signature has no toDERRawBytes (review 2026-09-07): build SEQUENCE{INTEGER r, INTEGER s}
  const c = sig.toCompactRawBytes();
  const r = derInt(c.subarray(0, 32)), s = derInt(c.subarray(32, 64));
  return cat(Uint8Array.of(0x30, r.length + s.length), r, s);
}

// The genuineness handshake of ledgerblue.deployed.getDeployedSecretV2, with hostNonce = challenge[0..8].
export async function attestLedger(handle, challenge) {
  const dev = handle.dev;
  // target id from GET_VERSION (E0 01): [targetId(4)][len][os version]...
  const ver = await ledgerExchange(dev, apdu(0xe0, 0x01, 0, 0));
  const targetId = ver.subarray(0, 4);
  if ((targetId[3] & 0x0f) < 2) throw new Error("This Ledger runs firmware too old for the secure-channel genuineness check.");
  await ledgerExchange(dev, apdu(0xe0, 0x04, 0, 0, targetId));
  const hostNonce = challenge.subarray(0, 8);
  const auth = await ledgerExchange(dev, apdu(0xe0, 0x50, 0, 0, hostNonce));
  const batch = auth.subarray(0, 4), deviceNonce = auth.subarray(4, 12);
  // our "unsafe manager": a fresh self-signed master certificate (the device shows the allow prompt — the tap)
  const master = secp.utils.randomPrivateKey();
  const masterPub = secp.getPublicKey(master, false);
  const sigM = await ecdsaDer(master, cat(Uint8Array.of(0x01), masterPub));
  await ledgerExchange(dev, apdu(0xe0, 0x51, 0x00, 0, cat(Uint8Array.of(masterPub.length), masterPub, Uint8Array.of(sigM.length), sigM)));
  const eph = secp.utils.randomPrivateKey();
  const ephPub = secp.getPublicKey(eph, false);
  const sigE = await ecdsaDer(master, cat(Uint8Array.of(0x11), hostNonce, deviceNonce, ephPub));
  await ledgerExchange(dev, apdu(0xe0, 0x51, 0x80, 0, cat(Uint8Array.of(ephPub.length), ephPub, Uint8Array.of(sigE.length), sigE)));
  // the device's side: cert0 = Issuer certificate over its device key, cert1 = device key over nonces + ephemeral
  const cert0 = await ledgerExchange(dev, apdu(0xe0, 0x52, 0x00, 0));
  const cert1 = await ledgerExchange(dev, apdu(0xe0, 0x52, 0x80, 0));
  if (!cert0.length || !cert1.length) throw new Error("The Ledger returned no device certificate.");
  try { await ledgerExchange(dev, apdu(0xe0, 0x53, 0x00, 0)); } catch (e) { /* committing the channel is not needed */ }
  return envelope("ledger", { target_id: new Uint8Array(targetId), batch: new Uint8Array(batch), host_nonce: new Uint8Array(hostNonce),
                              device_nonce: new Uint8Array(deviceNonce), cert0: new Uint8Array(cert0), cert1: new Uint8Array(cert1) },
                  challenge, `ledger target ${hex(targetId)}`);
}

// ================================================================= TREZOR (WebUSB) =================================
const TREZOR_FILTERS = [{ vendorId: 0x1209, productId: 0x53c1 }, { vendorId: 0x1209, productId: 0x53c0 }];
const MT = { Initialize: 0, Failure: 3, Features: 17, ButtonRequest: 26, ButtonAck: 27, AuthenticateDevice: 97, AuthenticityProof: 98 };

export async function connectTrezor() {
  if (!navigator.usb) throw new Error("WebUSB is not available in this browser — use Chrome, Edge or Brave on a computer, and close Trezor Suite (it holds the device).");
  const dev = await navigator.usb.requestDevice({ filters: TREZOR_FILTERS });
  await dev.open();
  if (dev.configuration === null) await dev.selectConfiguration(1);
  await dev.claimInterface(0);
  return { kind: "trezor", dev, name: dev.productName || "Trezor" };
}

function protoVarint(n) { const o = []; while (n >= 0x80) { o.push((n & 0x7f) | 0x80); n >>>= 7; } o.push(n); return Uint8Array.of(...o); }
function protoBytesField(num, bytes) { return cat(protoVarint((num << 3) | 2), protoVarint(bytes.length), bytes); }
function protoFields(buf) {   // -> [{num, wt, bytes|varint}]
  const out = []; let i = 0;
  const varint = () => { let v = 0, s = 0; for (;;) { const b = buf[i++]; v |= (b & 0x7f) << s; if (!(b & 0x80)) return v >>> 0; s += 7; if (s > 35) throw new Error("varint"); } };
  while (i < buf.length) {
    const key = varint(), num = key >>> 3, wt = key & 7;
    if (wt === 0) out.push({ num, wt, varint: varint() });
    else if (wt === 2) { const n = varint(); out.push({ num, wt, bytes: buf.subarray(i, i + n) }); i += n; }
    else if (wt === 1) { i += 8; out.push({ num, wt }); }
    else if (wt === 5) { i += 4; out.push({ num, wt }); }
    else throw new Error("protobuf: unsupported wire type " + wt);
  }
  return out;
}

async function trezorSend(dev, type, body) {
  const hdr = Uint8Array.of(0x3f, 0x23, 0x23, type >> 8, type & 255, (body.length >>> 24) & 255, (body.length >>> 16) & 255, (body.length >>> 8) & 255, body.length & 255);
  let msg = cat(hdr, body), off = 0, first = true;
  while (first || off < msg.length) {
    const p = new Uint8Array(64);
    if (first) { const n = Math.min(msg.length, 64); p.set(msg.subarray(0, n)); off = n; first = false; }
    else { p[0] = 0x3f; const n = Math.min(msg.length - off, 63); p.set(msg.subarray(off, off + n), 1); off += n; }
    await dev.transferOut(1, p);
  }
}
function withTimeout(p, ms, what) {
  return Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error(what + " — no answer from the device (confirm on it, or reconnect)")), ms))]);
}
async function trezorRecv(dev) {
  let r = await withTimeout(dev.transferIn(1, 64), 120000, "Trezor");
  let d = new Uint8Array(r.data.buffer, r.data.byteOffset, r.data.byteLength);
  if (d[0] !== 0x3f || d[1] !== 0x23 || d[2] !== 0x23) throw new Error("Trezor: bad frame header");
  const type = (d[3] << 8) | d[4];
  const len = ((d[5] << 24) | (d[6] << 16) | (d[7] << 8) | d[8]) >>> 0;
  let body = d.subarray(9);
  while (body.length < len) {
    r = await dev.transferIn(1, 64);
    d = new Uint8Array(r.data.buffer, r.data.byteOffset, r.data.byteLength);
    if (d[0] !== 0x3f) throw new Error("Trezor: bad continuation frame");
    body = cat(body, d.subarray(1));
  }
  return { type, body: body.subarray(0, len) };
}
async function trezorCall(dev, type, body) {
  await trezorSend(dev, type, body);
  for (;;) {
    const m = await trezorRecv(dev);
    if (m.type === MT.ButtonRequest) { await trezorSend(dev, MT.ButtonAck, new Uint8Array(0)); continue; }
    if (m.type === MT.Failure) {
      const msg = protoFields(m.body).find((f) => f.num === 2 && f.bytes);
      throw new Error("Trezor refused: " + (msg ? new TextDecoder().decode(msg.bytes) : "failure"));
    }
    return m;
  }
}

export async function attestTrezor(handle, challenge) {
  const dev = handle.dev;
  await trezorCall(dev, MT.Initialize, new Uint8Array(0));              // Features — resets the session
  const m = await trezorCall(dev, MT.AuthenticateDevice, protoBytesField(1, challenge));
  if (m.type !== MT.AuthenticityProof) throw new Error("Trezor: unexpected message " + m.type + " (a Trezor One / Model T cannot authenticate — no secure element)");
  const certs = [], f = protoFields(m.body);
  let sig = null;
  for (const x of f) { if (x.num === 1 && x.bytes) certs.push(new Uint8Array(x.bytes)); if (x.num === 2 && x.bytes) sig = new Uint8Array(x.bytes); }
  if (!certs.length || !sig) throw new Error("Trezor: proof carries no certificate chain");
  return envelope("trezor", { x5c: certs, sig }, challenge, "trezor");
}

// ---- entry points used by interface.js -----------------------------------------------------------------------------
export async function connect(kind) {
  return kind === "ledger" ? connectLedger() : connectTrezor();
}
export async function attestHardware(handle, challenge) {
  if (!handle || !handle.dev) throw new Error("No hardware wallet connected — press its button first.");
  return handle.kind === "ledger" ? attestLedger(handle, challenge) : attestTrezor(handle, challenge);
}
