// nadodapp.js — the NADO game SDK. Everything a game needs that ISN'T game-specific, in one place, so a new
// game (or another dev) writes ONLY its own contract-storage readers, UI, and actions. Covers: the delegated
// wallet session (exec_sign redirect signing — the key never touches the game origin), sign-in, deposit,
// withdraw, generic contract `call`s with VALUE escrow, contract-storage reads, exec + L1 balances, the L1
// cursor, amounts, commit-reveal secrets, QR, alias resolution, and Share. See dice.js / roulette.js.
//
// Usage:
//   import { NadoDapp, rawToNado, nadoToRaw, randId, randSecret, commitHashOf, _m, $ } from "./nadodapp.js";
//   const dapp = new NadoDapp({ cid: "…", app: "Dice" });
//   dapp.onReturn((pend, ok, err) => { /* update your #status, mark local pending state */ });
//   await dapp.init();                       // loads crypto + processes any wallet return
//   dapp.signIn(); dapp.deposit(raw); dapp.withdraw(raw);
//   dapp.call("bet", [g, t, ...args], stakeRaw, "human label", { table: t, phase: "bet" });
//   await dapp.refresh();                    // dapp.me, dapp.exec, dapp.l1, dapp.cursor
//   const sto = await dapp.storage();        // the contract's storage maps
import { loadCrypto, blake2bHash } from "./nadotx.js";
export { loadCrypto, blake2bHash };

export const RAW = 10n ** 10n;                 // 1 NADO = 1e10 raw units
const WALLET = "https://get.nadochain.com";
export const base = () => location.origin.replace(/\/+$/, "");
export const $ = (id) => document.getElementById(id);
export const _m = (sto, name) => (sto && sto[name]) || {};

// ---- amounts -------------------------------------------------------------------------------------
export function nadoToRaw(s) {
  s = String(s || "").trim(); if (!/^\d+(\.\d+)?$/.test(s)) return null;
  const [w, f = ""] = s.split("."); const raw = BigInt(w) * RAW + BigInt((f + "0000000000").slice(0, 10));
  return raw > 0n ? raw : null;
}
export const rawToNado = (raw) => { raw = BigInt(raw); const w = raw / RAW, f = (raw % RAW).toString().padStart(10, "0").replace(/0+$/, ""); return f ? `${w}.${f}` : `${w}`; };
// recursively wrap BigInt as {$big:"…"} so 256-bit args survive the URL to the wallet (JS can't JSON BigInt)
export const encBig = (v) => typeof v === "bigint" ? { $big: v.toString() }
  : Array.isArray(v) ? v.map(encBig)
  : (v && typeof v === "object") ? Object.fromEntries(Object.keys(v).map((k) => [k, encBig(v[k])])) : v;

// ---- commit-reveal secrets -----------------------------------------------------------------------
export const randId = () => globalThis.crypto.getRandomValues(new Uint32Array(1))[0] % 1000000000 + 1;   // 1..1e9
export const randSecret = () => { let h = "0x"; for (const b of globalThis.crypto.getRandomValues(new Uint8Array(32))) h += b.toString(16).padStart(2, "0"); return BigInt(h); };
export const commitHashOf = (secret) => BigInt("0x" + blake2bHash(secret));   // 256-bit; == VM HASH(secret)

// ---- QR (vendored, best-effort — same generator as the wallet) -----------------------------------
let qrEncode = null;
export async function loadQR() { try { const m = await import("./vendor/qrcode.js"); qrEncode = m.qrMatrix || null; } catch { qrEncode = null; } }
export function drawQR(canvas, note, text, targetPx) {
  if (!qrEncode || !canvas) { if (canvas) canvas.classList.add("hidden"); if (note) note.classList.remove("hidden"); return; }
  try {
    let m; try { m = qrEncode(text, "M"); } catch { m = qrEncode(text, "L"); }
    const n = m.length, quiet = 4, dim = n + quiet * 2, px = Math.max(2, Math.floor((targetPx || 200) / dim)), size = dim * px;
    canvas.width = size; canvas.height = size; canvas.style.width = size + "px"; canvas.style.height = size + "px";
    const ctx = canvas.getContext("2d"); ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, size, size); ctx.fillStyle = "#000";
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (m[r][c]) ctx.fillRect((c + quiet) * px, (r + quiet) * px, px, px);
    canvas.classList.remove("hidden"); if (note) note.classList.add("hidden");
  } catch { canvas.classList.add("hidden"); if (note) note.classList.remove("hidden"); }
}

// ---- aliases (shared @name registry the wallet/forum use) ----------------------------------------
const _aliasCache = {};
export async function resolveAliases(addrs) {
  await Promise.all([...new Set(addrs)].filter((a) => a && !(a in _aliasCache)).map(async (a) => {
    try { const r = await (await fetch(base() + "/get_aliases_of?address=" + encodeURIComponent(a), { cache: "no-store" })).json(); _aliasCache[a] = (r.aliases && r.aliases[0]) || null; }
    catch { _aliasCache[a] = null; }
  }));
}
export const disp = (addr) => !addr ? "—" : (_aliasCache[addr] ? "@" + _aliasCache[addr] : addr.slice(0, 8) + "…" + addr.slice(-4));

// ---- Share (Web Share API -> clipboard fallback), with button feedback ---------------------------
export async function share(url, text, btn) {
  if (navigator.share) { try { await navigator.share({ title: "NADO", text, url }); return; } catch (e) { if (e && e.name === "AbortError") return; } }
  let ok = false; try { await navigator.clipboard.writeText(url); ok = true; } catch {}
  if (btn) { const t = btn.textContent; btn.textContent = ok ? "Copied ✓" : "copy failed"; setTimeout(() => (btn.textContent = t.replace("Copied ✓", "Share").replace("copy failed", "Share") || "Share"), 1400); }
}

// ---- the wallet-backed dApp session --------------------------------------------------------------
export class NadoDapp {
  constructor({ cid, app, ns = "default" }) {
    this.cid = cid; this.app = app; this.ns = ns;
    const slug = app.replace(/\W+/g, "").toLowerCase();
    this.LS_ME = "nado_" + slug + "_me"; this.LS_P = "nado_" + slug + "_pending";
    this.me = localStorage.getItem(this.LS_ME) || null;
    this.exec = 0n; this.l1 = 0n; this.cursor = null;
    this._onReturn = null;
  }
  async init() { await loadCrypto(); this._handleReturn(); if (this.me) await this.refresh(); }
  onReturn(fn) { this._onReturn = fn; }        // fn(pend, ok, err) — game marks its own local state + status

  // --- delegated signing (redirect to the wallet, which signs + submits, then bounces back) ---
  _go(obj, pend) {
    const payload = btoa(unescape(encodeURIComponent(JSON.stringify(obj))));
    localStorage.setItem(this.LS_P, JSON.stringify(pend || {}));
    location.href = WALLET + "/?exec_sign=" + encodeURIComponent(payload) + "&ret=" + encodeURIComponent(base() + "/") + "&app=" + encodeURIComponent(this.app);
  }
  signIn() { this._go({ connect: true, label: "sign in" }, { phase: "connect" }); }
  deposit(raw) { this._go({ deposit: { amount: raw.toString() }, label: "deposit " + rawToNado(raw) + " NADO" }, { phase: "deposit" }); }
  withdraw(raw, pend) { this.signBlob({ op: "bridge_withdraw", amount: raw }, "withdraw " + rawToNado(raw) + " NADO to L1", pend || { phase: "withdraw" }); }
  signBlob(blob, label, pend) { this._go({ blob: encBig(blob), label }, pend); }
  // generic contract call; valueRaw (raw NADO) is ESCROWED from the caller's bridge balance into the contract
  call(method, args, valueRaw, label, pend) {
    const p = { op: "call", contract: this.cid, method, args };
    if (valueRaw != null) p.value = valueRaw;
    this.signBlob(p, label, pend);
  }
  _handleReturn() {
    const p = new URLSearchParams(location.search);
    if (!p.has("ok")) return;
    const ok = p.get("ok") === "1", addr = p.get("addr"), err = p.get("err") ? decodeURIComponent(p.get("err")) : "";
    let pend = null; try { pend = JSON.parse(localStorage.getItem(this.LS_P) || "null"); } catch {}
    localStorage.removeItem(this.LS_P);
    try { history.replaceState(null, "", location.pathname); } catch {}
    if (ok && addr) { this.me = addr; localStorage.setItem(this.LS_ME, addr); }
    if (this._onReturn) this._onReturn(pend, ok, err);
  }

  // --- reads ---
  async refresh() { await Promise.all([this._balances(), this._cursor()]); }
  async _balances() {
    if (!this.me) { this.exec = 0n; this.l1 = 0n; return; }
    try { const b = await (await fetch(base() + "/exec/bridge?ns=" + this.ns + "&provisional=1", { cache: "no-store" })).json(); this.exec = BigInt((b.balances || {})[this.me] || 0); } catch { this.exec = 0n; }
    try { const a = await (await fetch(base() + "/get_account?address=" + encodeURIComponent(this.me), { cache: "no-store" })).json(); this.l1 = BigInt(a.balance || 0); } catch { this.l1 = 0n; }
  }
  async _cursor() { try { const s = await (await fetch(base() + "/exec/root?ns=" + this.ns + "&provisional=1", { cache: "no-store" })).json(); this.cursor = s.cursor != null ? Number(s.cursor) : this.cursor; } catch {} }
  async storage() { try { return (await (await fetch(base() + "/exec/contract?ns=" + this.ns + "&cid=" + this.cid + "&provisional=1", { cache: "no-store" })).json()).storage || {}; } catch { return null; } }
}
