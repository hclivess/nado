// ethsign.js — in-browser Ethereum leg for the OTC swap (doc/dex-bridge.md §6.5, HtlcEth.sol).
// Legacy (EIP-155) transaction signing with the SAME vendored secp256k1 the Bitcoin leg uses, keccak from
// the vendored @noble/hashes. Talks to a public RPC; per-swap keys are page-generated like the BTC leg.
import * as secp from "./vendor/noble-secp256k1.js?v=1";
import { keccak_256 } from "./vendor/noble-sha3.js?v=1";

const hexToBytes = (h) => new Uint8Array(((h.startsWith("0x") ? h.slice(2) : h).match(/../g) || []).map((x) => parseInt(x, 16)));
const bytesToHex = (b) => Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
const strip = (b) => { let i = 0; while (i < b.length && b[i] === 0) i++; return b.slice(i); };
const numBytes = (n) => strip(hexToBytes(BigInt(n).toString(16).padStart(64, "0")));

// ---- minimal RLP ---------------------------------------------------------------------------------------
function rlpItem(b) {
  if (b.length === 1 && b[0] < 0x80) return b;
  if (b.length <= 55) return new Uint8Array([0x80 + b.length, ...b]);
  const l = numBytes(b.length);
  return new Uint8Array([0xb7 + l.length, ...l, ...b]);
}
function rlpList(items) {
  const body = items.reduce((a, x) => { const e = rlpItem(x); const r = new Uint8Array(a.length + e.length); r.set(a); r.set(e, a.length); return r; }, new Uint8Array(0));
  if (body.length <= 55) return new Uint8Array([0xc0 + body.length, ...body]);
  const l = numBytes(body.length);
  return new Uint8Array([0xf7 + l.length, ...l, ...body]);
}

// ---- keys / addresses ----------------------------------------------------------------------------------
export function ethKeypair() {
  const k = secp.utils.randomPrivateKey();
  return { k: bytesToHex(k), addr: ethAddress(bytesToHex(k)) };
}
export function ethAddress(privHex) {
  const pub = secp.getPublicKey(hexToBytes(privHex), false).slice(1);
  return "0x" + bytesToHex(keccak_256(pub).slice(12));
}

// ---- EIP-155 legacy tx ---------------------------------------------------------------------------------
secp.etc.hmacSha256Async = secp.etc.hmacSha256Async || (async (key, ...msgs) => {
  const k = await crypto.subtle.importKey("raw", key, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return new Uint8Array(await crypto.subtle.sign("HMAC", k, secp.etc.concatBytes(...msgs)));
});
export async function signTx({ privHex, nonce, gasPriceWei, gasLimit, to, valueWei, dataHex, chainId }) {
  const base = [numBytes(nonce), numBytes(gasPriceWei), numBytes(gasLimit),
                hexToBytes(to || ""), numBytes(valueWei || 0), hexToBytes(dataHex || "")];
  const digest = keccak_256(rlpList([...base, numBytes(chainId), new Uint8Array(0), new Uint8Array(0)]));
  const sig = await secp.signAsync(digest, hexToBytes(privHex));
  const s2 = sig.hasHighS() ? sig.normalizeS() : sig;
  const rec = sig.hasHighS() ? 1 - sig.recovery : sig.recovery;      // normalizing S flips the recovery bit
  const v = BigInt(chainId) * 2n + 35n + BigInt(rec);
  return "0x" + bytesToHex(rlpList([...base, numBytes(v), strip(secp.etc.numberToBytesBE(s2.r, 32)), strip(secp.etc.numberToBytesBE(s2.s, 32))]));
}

// ---- tiny ABI for HtlcEth (fixed 32-byte args only — no dynamic types anywhere in it) ------------------
const pad32 = (b) => { const r = new Uint8Array(32); r.set(b, 32 - b.length); return r; };
const selector = (sig) => bytesToHex(keccak_256(new TextEncoder().encode(sig)).slice(0, 4));
export const htlcAbi = {
  fund: (claimant, Hhex, deadline) => "0x" + selector("fund(address,bytes32,uint256)")
    + bytesToHex(pad32(hexToBytes(claimant))) + bytesToHex(pad32(hexToBytes(Hhex))) + bytesToHex(pad32(numBytes(deadline))),
  claim: (keyHex, sHex) => "0x" + selector("claim(bytes32,bytes32)")
    + bytesToHex(pad32(hexToBytes(keyHex))) + bytesToHex(pad32(hexToBytes(sHex))),
  refund: (keyHex) => "0x" + selector("refund(bytes32)") + bytesToHex(pad32(hexToBytes(keyHex))),
  locks: (keyHex) => "0x" + selector("locks(bytes32)") + bytesToHex(pad32(hexToBytes(keyHex))),
  // key = keccak256(abi.encode(H, claimant, refundee, deadline))
  lockKey: (Hhex, claimant, refundee, deadline) => bytesToHex(keccak_256(new Uint8Array([
    ...pad32(hexToBytes(Hhex)), ...pad32(hexToBytes(claimant)), ...pad32(hexToBytes(refundee)), ...pad32(numBytes(deadline))]))),
};

// ---- JSON-RPC ------------------------------------------------------------------------------------------
export async function rpc(url, method, params) {
  const r = await (await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }) })).json();
  if (r.error) throw new Error(r.error.message || JSON.stringify(r.error));
  return r.result;
}
export async function sendTx(url, opts) {
  const from = ethAddress(opts.privHex);
  if (opts.dataHex) {
    // PREFLIGHT: a contract call that would revert should fail HERE, with the revert reason, before any
    // gas is spent — not land on-chain as a silent failure.
    await rpc(url, "eth_call", [{ from, to: opts.to, data: "0x" + opts.dataHex.replace(/^0x/, ""),
      value: opts.valueWei ? "0x" + BigInt(opts.valueWei).toString(16) : undefined }, "latest"]);
  }
  const [nonce, gasPrice, chainId] = await Promise.all([
    rpc(url, "eth_getTransactionCount", [from, "pending"]),
    rpc(url, "eth_gasPrice", []),
    rpc(url, "eth_chainId", []),
  ]);
  const raw = await signTx(Object.assign({}, opts, {
    nonce: BigInt(nonce), gasPriceWei: (BigInt(gasPrice) * 15n) / 10n, chainId: BigInt(chainId) }));
  return rpc(url, "eth_sendRawTransaction", [raw]);
}


// ---- deploy the (ownerless) HtlcEth — needed once per EVM chain; anyone may do it ----------------------
export async function deployHtlc(url, privHex, bytecodeHex) {
  const from = ethAddress(privHex);
  const [nonce, gasPrice, chainId] = await Promise.all([
    rpc(url, "eth_getTransactionCount", [from, "pending"]),
    rpc(url, "eth_gasPrice", []),
    rpc(url, "eth_chainId", []),
  ]);
  // ESTIMATE the gas — a hardcoded limit silently under-funds a bigger contract, and the out-of-gas
  // receipt carries no contractAddress, so the wait below would spin until it timed out with a
  // misleading "no receipt yet". Fall back to a generous limit only if the node cannot estimate.
  let gasLimit = 3_000_000n;
  try { gasLimit = (BigInt(await rpc(url, "eth_estimateGas", [{ from, data: bytecodeHex }])) * 13n) / 10n; }
  catch (e) { /* keep the fallback */ }
  const raw = await signTx({ privHex, nonce: BigInt(nonce), gasPriceWei: (BigInt(gasPrice) * 15n) / 10n,
    gasLimit, to: "", valueWei: 0n, dataHex: bytecodeHex.replace(/^0x/, ""), chainId: BigInt(chainId) });
  const txid = await rpc(url, "eth_sendRawTransaction", [raw]);
  for (let i = 0; i < 60; i++) {
    const r = await rpc(url, "eth_getTransactionReceipt", [txid]).catch(() => null);
    if (r && r.contractAddress) return { txid, address: r.contractAddress };
    if (r && r.status && BigInt(r.status) === 0n)          // mined and FAILED — say so instead of waiting
      throw new Error("deploy reverted or ran out of gas (tx " + txid + ", gas used " + BigInt(r.gasUsed || 0) + ")");
    await new Promise((res) => setTimeout(res, 2000));
  }
  throw new Error("deploy sent (" + txid + ") but no receipt yet — check the explorer");
}
export async function ethBalance(url, addr) { return BigInt(await rpc(url, "eth_getBalance", [addr, "latest"])); }


// ---- ERC-20: the token leg (HtlcErc20) plus the token calls a swap needs -------------------------------
const _pad32 = (b) => { const r = new Uint8Array(32); r.set(b, 32 - b.length); return r; };
const _sel = (sig) => bytesToHex(keccak_256(new TextEncoder().encode(sig)).slice(0, 4));
const _addr = (a) => bytesToHex(_pad32(hexToBytes(a)));
const _n = (v) => bytesToHex(_pad32(numBytes(v)));
export const erc20Abi = {
  approve: (spender, amount) => "0x" + _sel("approve(address,uint256)") + _addr(spender) + _n(amount),
  allowance: (owner, spender) => "0x" + _sel("allowance(address,address)") + _addr(owner) + _addr(spender),
  balanceOf: (who) => "0x" + _sel("balanceOf(address)") + _addr(who),
  decimals: () => "0x" + _sel("decimals()"),
  symbol: () => "0x" + _sel("symbol()"),
};
export const htlcErc20Abi = {
  fund: (token, claimant, Hhex, deadline, amount) => "0x" + _sel("fund(address,address,bytes32,uint256,uint256)")
    + _addr(token) + _addr(claimant) + bytesToHex(_pad32(hexToBytes(Hhex))) + _n(deadline) + _n(amount),
  claim: (keyHex, sHex) => "0x" + _sel("claim(bytes32,bytes32)")
    + bytesToHex(_pad32(hexToBytes(keyHex))) + bytesToHex(_pad32(hexToBytes(sHex))),
  refund: (keyHex) => "0x" + _sel("refund(bytes32)") + bytesToHex(_pad32(hexToBytes(keyHex))),
  // key = keccak256(abi.encode(token, H, claimant, refundee, deadline)) — the token is part of the identity
  lockKey: (token, Hhex, claimant, refundee, deadline) => bytesToHex(keccak_256(new Uint8Array([
    ...hexToBytes(_addr(token)), ...hexToBytes(bytesToHex(_pad32(hexToBytes(Hhex)))),
    ...hexToBytes(_addr(claimant)), ...hexToBytes(_addr(refundee)), ...hexToBytes(_n(deadline))]))),
};
// A token's decimals/symbol, read straight from the contract (cached per url+token by the caller).
export async function erc20Meta(url, token) {
  const dec = await rpc(url, "eth_call", [{ to: token, data: erc20Abi.decimals() }, "latest"]).catch(() => "0x12");
  let sym = "TOKEN";
  try {                                              // symbol() is usually a dynamic string; some tokens use bytes32
    const raw = await rpc(url, "eth_call", [{ to: token, data: erc20Abi.symbol() }, "latest"]);
    const b = hexToBytes(raw);
    if (b.length === 32) sym = new TextDecoder().decode(b).replace(/\u0000+$/, "").trim() || "TOKEN";
    else if (b.length > 64) {
      const len = Number(BigInt("0x" + bytesToHex(b.slice(32, 64))));
      sym = new TextDecoder().decode(b.slice(64, 64 + len)) || "TOKEN";
    }
  } catch (e) { /* keep the fallback */ }
  return { decimals: Number(BigInt(dec || "0x12")), symbol: sym };
}
export const toUnitsDec = (amountStr, decimals) => {   // "1.25", 6 -> 1250000n  (no float maths)
  const s = String(amountStr).trim();
  if (!/^\d*(\.\d*)?$/.test(s) || s === "" || s === ".") return 0n;
  const [w, f = ""] = s.split(".");
  return BigInt((w || "0") + (f + "0".repeat(decimals)).slice(0, decimals) || "0");
};
export const fromUnitsDec = (v, decimals) => {
  const s = BigInt(v).toString().padStart(decimals + 1, "0");
  const w = s.slice(0, s.length - decimals), f = s.slice(s.length - decimals).replace(/0+$/, "");
  return f ? `${w}.${f}` : w;
};
