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
// gate(map): show/hide a set of elements by id in ONE call — map is { elementId: shouldShow }. Every game uses
// it to keep "signed-in only" panels AND the in-game STAGE (the board / wheel / felt / bet layout) hidden until
// they apply, so a player never sees a playing field for a game they haven't opened. Missing ids are ignored.
export const gate = (map) => { for (const id in map) { const el = document.getElementById(id); if (el) el.classList.toggle("hidden", !map[id]); } };
// hoist(id): move an element to the TOP of the page (right after #status) so the actual game/board is the first
// thing a player sees when they're in a game. Call once at boot; the element stays hidden (via gate) until active.
export const hoist = (id, refId = "status") => { const el = document.getElementById(id), ref = document.getElementById(refId); if (el && ref && ref.parentNode) ref.parentNode.insertBefore(el, ref.nextSibling); };
// orderCards(ids): arrange the page's cards right after #status in the given order — the GAME DISPLAY first,
// the public lobby directly under it, wallet/plumbing demoted below. So the moment a player opens/joins a
// game, the board/felt/wheel is the first thing on screen. Ids missing on a page are skipped.
export function orderCards(ids) {
  let anchor = document.getElementById("status");
  if (!anchor || !anchor.parentNode) return;
  for (const id of ids) {
    const el = document.getElementById(id);
    if (el) { anchor.parentNode.insertBefore(el, anchor.nextSibling); anchor = el; }
  }
}

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
// chainResult(shHex, sh1Hex, salt, mod): the ONE beacon-game result formula, shared by every game so it can
// never drift from the contract — result = HASH(bh(sh) + bh(sh+1) + salt) % mod. Passes a BigInt to blake2bHash
// so canonicalize emits bare digits, EXACTLY matching the VM's HASH(<int>). Returns null if a hash is missing.
export function chainResult(shHex, sh1Hex, salt, mod) {
  if (!shHex || !sh1Hex) return null;
  const seed = BigInt("0x" + shHex) + BigInt("0x" + sh1Hex) + BigInt(salt);
  return Number(BigInt("0x" + blake2bHash(seed)) % BigInt(mod));
}
// blocksToTime(blocks): render a block count as m:ss at the given block time (default 6s) — shared countdown fmt.
export const blocksToTime = (blocks, secs = 6) => { const b = Math.max(0, blocks) * secs, m = Math.floor(b / 60), s = b % 60; return m + ":" + String(s).padStart(2, "0"); };

// ---- localStorage records (per-game "my tables/seats" that survive the signing redirect) ----------
export const lsLoad = (k) => { try { return JSON.parse(localStorage.getItem(k) || "{}"); } catch { return {}; } };
export const lsSave = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} };
// prune LS records that no longer exist on-chain (after a grace window so slow confirmations survive);
// returns the Set of on-chain keys so render can mark ⏳ pending vs live.
export function lsPrune(lsKey, chainKeys, graceMs = 600000) {
  const known = new Set(chainKeys), R = lsLoad(lsKey); let c = false;
  for (const k of Object.keys(R)) if (!known.has(k) && Date.now() - (R[k].ts || 0) > graceMs) { delete R[k]; c = true; }
  if (c) lsSave(lsKey, R);
  return known;
}

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

// ---- shared UI blocks (every game has these exact elements — keep them in ONE place) --------------
// wireWallet(dapp): the sign-in / deposit / withdraw buttons ("bankAmt" input) — identical in every game.
export function wireWallet(dapp) {
  const st = (m) => { const s = $("status"); if (s) s.textContent = m; };
  if ($("btnSignIn")) $("btnSignIn").onclick = () => dapp.signIn();
  if ($("btnDeposit")) $("btnDeposit").onclick = () => { const raw = nadoToRaw($("bankAmt").value); if (!raw) return st("Enter an amount to deposit."); if (raw + 1000n > dapp.l1) return st("Not enough in your L1 wallet (" + rawToNado(dapp.l1) + " NADO)."); dapp.deposit(raw); };
  if ($("btnWithdraw")) $("btnWithdraw").onclick = () => { const raw = nadoToRaw($("bankAmt").value); if (!raw) return st("Enter an amount to withdraw."); if (dapp.exec < raw) return st("You only have " + rawToNado(dapp.exec) + " NADO in the exec layer."); dapp.withdraw(raw); };
}
// renderWallet(dapp): the who/bal/l1bal header row; returns signedIn so render() can gate on it.
export function renderWallet(dapp) {
  const signedIn = !!dapp.me;
  if ($("btnSignIn")) $("btnSignIn").classList.toggle("hidden", signedIn);
  if ($("who")) $("who").textContent = signedIn ? disp(dapp.me) : "not signed in";
  if ($("bal")) $("bal").textContent = rawToNado(dapp.exec) + " NADO";
  if ($("l1bal")) $("l1bal").textContent = rawToNado(dapp.l1) + " NADO";
  return signedIn;
}
// renderScore(el, board, me, empty): the shared win/loss leaderboard table.
export async function renderScore(el, board, me, empty) {
  if (!el) return;
  if (!board.length) { el.innerHTML = '<span class="dim">' + (empty || "No settled games yet — be the first on the board.") + "</span>"; return; }
  const top = board.slice(0, 10); await resolveAliases(top.map((r) => r.addr));
  el.innerHTML = '<table class="score"><thead><tr><th>#</th><th>Player</th><th>W–L</th><th>Net</th></tr></thead><tbody>'
    + top.map((r, i) => { const net = (r.net < 0 ? "-" : "+") + rawToNado(Math.abs(r.net)) + " NADO", you = r.addr === me;
        return '<tr' + (you ? ' class="me"' : "") + '><td>' + (i + 1) + '</td><td>' + disp(r.addr) + (you ? " (you)" : "") + '</td><td>W' + r.wins + "–L" + r.losses + '</td><td class="' + (r.net >= 0 ? "pos" : "neg") + '">' + net + "</td></tr>"; }).join("") + "</tbody></table>";
}
// scoreBump(stats, addr, net): accumulate one settled result into a leaderboard stats map.
export function scoreBump(stats, addr, net) {
  const x = stats[addr] || (stats[addr] = { addr, wins: 0, losses: 0, games: 0, net: 0 });
  x.games++; x.net += net; net >= 0 ? x.wins++ : x.losses++;
}
export const scoreSort = (stats) => Object.values(stats).sort((a, b) => (b.net - a.net) || (b.wins - a.wins));
// recentChips(el, items, icon, onSelect): "your tables/games" chips — never hides a placed bet; ⏳ until it lands.
// items: [{id, live, title?}] newest-first.
export function recentChips(el, items, onSelect, emptyMsg) {
  if (!el) return;
  el.innerHTML = items.length ? items.map((x) => '<button class="chip' + (x.live ? "" : " pending") + '" data-t="' + x.id + '"'
      + (x.live ? "" : ' title="still confirming on-chain — your bet hasn\'t vanished"') + ">" + (x.icon || "🎯") + " #" + x.id + (x.live ? "" : " ⏳") + "</button>").join(" ")
    : '<span class="dim">' + (emptyMsg || "No games yet.") + "</span>";
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => onSelect(parseInt(b.dataset.t, 10)));
}
// statusLabel(pend, ok, err, extra): the shared post-redirect status line. Games pass extra phase labels.
export function statusLabel(pend, ok, err, extra) {
  const labels = Object.assign({ connect: "Signed in.", deposit: "Deposit submitted — confirming…",
    open: "Table opening — confirming…", bet: "Bet placed — confirming…", join: "Joining — confirming…",
    settle: "Collecting — confirming on-chain (~1 min)…", fund: "Topping up…", close: "Closing…",
    resolve: "Rolling out — confirming…", cancel: "Cancelling…", withdraw: "Withdrawal submitted." }, extra || {});
  return ok ? (labels[pend && pend.phase] || "Submitted.") : "Rejected" + (err ? ": " + err : ".");
}

// ---- the shared auto-rolling table schema (roulette / dice / video-table games) -------------------
// Every table-banked beacon game stores the SAME table maps: ta=bank t0=round-anchor tk=bankroll tp=pool
// tc=committed tn=seats tx=settled tz=closed. Read them in one place so games only read their SEAT schema.
export const tablesOf = (sto) => Object.keys(_m(sto, "t0"));
export function readTable(sto, t, cursor, ROUND) {
  t = String(t); const bank = _m(sto, "ta")[t], t0 = _m(sto, "t0")[t];
  if (!bank || t0 == null) return { exists: false };
  const tb = { exists: true, id: Number(t), bank, bankroll: _m(sto, "tk")[t] || 0, pool: _m(sto, "tp")[t] || 0,
    committed: _m(sto, "tc")[t] || 0, t0, seatCount: _m(sto, "tn")[t] || 0,
    settledCount: _m(sto, "tx")[t] || 0, closed: !!_m(sto, "tz")[t] };
  tb.phase = tb.closed ? "done" : "betting";
  if (cursor != null && ROUND) { tb.nextSettle = t0 + (Math.floor((cursor - t0) / ROUND) + 1) * ROUND; tb.roundEndsIn = tb.nextSettle - cursor; }
  return tb;
}

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
    // online: null = never reached the chain API yet (first load), true = last read OK, false = last read
    // FAILED (node restarting / network). Games must consult this before claiming something "isn't on-chain" —
    // a chain hiccup must never be misreported as a vanished table/bet (that's exactly what a rug feels like).
    this.online = null;
    this._onReturn = null;
    this._bh = {};   // height -> finalized L1 block hash hex | null (BLOCKHASH randomness cache)
  }
  // blockHashes(heights): fetch + CACHE the finalized L1 block hashes for these heights (from /exec/blockhash),
  // so a beacon game can compute the same result the contract will. bh(h) reads the cache (hex | null | undefined).
  async blockHashes(heights) {
    const need = [...new Set(heights)].filter((h) => this._bh[h] === undefined);
    if (need.length) {
      try {
        const j = await (await fetch(base() + "/exec/blockhash?ns=" + this.ns + "&provisional=1&heights=" + need.join(","), { cache: "no-store" })).json();
        for (const h of need) this._bh[h] = (j.hashes && j.hashes[String(h)]) || null;
      } catch { for (const h of need) this._bh[h] = null; }
    }
    return this._bh;
  }
  bh(h) { return this._bh[h]; }
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
  async storage() {
    try { const sto = (await (await fetch(base() + "/exec/contract?ns=" + this.ns + "&cid=" + this.cid + "&provisional=1", { cache: "no-store" })).json()).storage || {}; this.online = true; return sto; }
    catch { this.online = false; return null; }
  }
  // whereIs(kind, id, openedTs): the ONE "why can't I see my table/game" message. Tri-state on this.online so
  // an unreachable/restarting exec node is reported as exactly that — never as a missing table. openedTs (ms,
  // optional) is when the player submitted the open, for confirming-vs-rejected wording.
  whereIs(kind, id, openedTs) {
    if (this.online === null) return "Loading " + kind + " #" + id + " from the chain…";
    if (this.online === false) return "Can't reach the chain right now — reconnecting… your " + kind + " and funds are safe on-chain.";
    if (openedTs) return Date.now() - openedTs > 150000
      ? "⚠ " + kind + " #" + id + " didn't land — it was likely rejected (did your exec balance cover it?)."
      : kind + " #" + id + " is confirming on-chain (~1 min)…";
    return kind + " #" + id + " isn't on-chain — if it was just opened, give it ~1 min to confirm; otherwise check the ID.";
  }
}
