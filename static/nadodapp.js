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
  s = String(s || "").trim().replace(",", ".");   // Czech/EU keyboards type "0,20" — accept it as 0.20
  if (!/^\d+(\.\d+)?$/.test(s)) return null;
  const [w, f = ""] = s.split("."); const raw = BigInt(w) * RAW + BigInt((f + "0000000000").slice(0, 10));
  return raw > 0n ? raw : null;
}
export const rawToNado = (raw) => { raw = BigInt(raw ?? 0); const w = raw / RAW, f = (raw % RAW).toString().padStart(10, "0").replace(/0+$/, ""); return f ? `${w}.${f}` : `${w}`; };   // null/undefined -> 0 (a stray undefined must never crash a whole render)
// recursively wrap BigInt as {$big:"…"} so 256-bit args survive the URL to the wallet (JS can't JSON BigInt)
export const encBig = (v) => typeof v === "bigint" ? { $big: v.toString() }
  : Array.isArray(v) ? v.map(encBig)
  : (v && typeof v === "object") ? Object.fromEntries(Object.keys(v).map((k) => [k, encBig(v[k])])) : v;

// ---- commit-reveal secrets -----------------------------------------------------------------------
export const randId = () => globalThis.crypto.getRandomValues(new Uint32Array(1))[0] % 1000000000 + 1;   // 1..1e9
// deterministic rematch id: every player at oldId who taps "Play again" derives the SAME fresh id, so they
// reconvene at one new game/table instead of scattering to random ids. (LCG mix -> uniform over 0..1e9)
export const rematchId = (oldId) => Number((BigInt(oldId) * 6364136223846793005n + 1442695040888963407n) % 1000000000n);
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

// ---- can't-miss feedback (a quiet status line reads as "nothing happened" — a real bug to users) ---
// alertBar(msg, actionLabel?, actionFn?): a fixed toast at the bottom of the viewport, visible no matter
// where the user is on the page. Call with no msg to dismiss. One at a time — a new call replaces it.
// modalDialog({title, body, okLabel, cancelLabel, onOk}): a centered blocking dialog (games have no wallet
// modal of their own). Returns nothing; onOk fires on confirm. Used by inviteGate below.
export function modalDialog({ title, body, okLabel = "OK", cancelLabel = "Cancel", onOk }) {
  document.getElementById("nadoModal")?.remove();
  const ov = document.createElement("div");
  ov.id = "nadoModal";
  ov.style.cssText = "position:fixed;inset:0;z-index:1000;display:flex;align-items:center;justify-content:center;background:rgba(4,8,12,.72);padding:16px";
  const card = document.createElement("div");
  card.style.cssText = "background:#131a23;border:1px solid #243140;border-radius:16px;max-width:420px;width:100%;padding:20px;box-shadow:0 20px 60px rgba(0,0,0,.6)";
  card.innerHTML = '<div style="font-size:17px;font-weight:800;color:#e6edf3;margin-bottom:8px">' + title + "</div>"
    + '<div style="font-size:13.5px;color:#93a1b0;line-height:1.55;margin-bottom:16px">' + body + "</div>";
  const row = document.createElement("div");
  row.style.cssText = "display:flex;gap:10px";
  const mk = (txt, primary) => { const b = document.createElement("button"); b.textContent = txt;
    b.style.cssText = "flex:1;font:inherit;font-weight:800;border-radius:11px;padding:12px;cursor:pointer;border:1px solid #243140;"
      + (primary ? "background:linear-gradient(135deg,#00ad93,#00c9a7);color:#04110a;border-color:transparent" : "background:#1a232e;color:#e6edf3"); return b; };
  const cancel = mk(cancelLabel, false), ok = mk(okLabel, true);
  cancel.onclick = () => ov.remove();
  ok.onclick = () => { ov.remove(); onOk && onOk(); };
  row.appendChild(cancel); row.appendChild(ok);
  card.appendChild(row); ov.appendChild(card);
  ov.onclick = (e) => { if (e.target === ov) ov.remove(); };
  document.body.appendChild(ov);
}
// inviteGate(dapp, {kind, id, title, body, joinLabel, onJoin}): a signed-OUT visitor who followed a share
// link gets a clear FOREGROUND dialog (not a background option). "Sign in & join" records the intent and
// redirects to the wallet; after sign-in the game replays onJoin(id). Call once on boot when a deep-link
// id is present and the user isn't signed in; call dapp.consumeInvite(onJoin) from onReturn on connect.
export function inviteGate(dapp, { kind, id, title, body, joinLabel, onJoin }) {
  if (dapp.me || id == null) return;
  modalDialog({
    title: title || "You're invited",
    body, okLabel: joinLabel || "Sign in & join", cancelLabel: "Just browse",
    onOk: () => { try { localStorage.setItem(dapp.LS_INVITE, String(id)); } catch (e) {} dapp.signIn(); },
  });
}

export function alertBar(msg, actionLabel, actionFn) {
  let el = document.getElementById("alertBar");
  if (el) el.remove();
  if (!msg) return;
  el = document.createElement("div");
  el.id = "alertBar";
  el.style.cssText = "position:fixed;left:12px;right:12px;bottom:12px;z-index:999;max-width:600px;margin:0 auto;"
    + "background:#2a1214;border:1px solid rgba(248,81,73,.65);color:#ffb4ae;font-weight:700;font-size:13.5px;"
    + "border-radius:14px;padding:13px 40px 13px 14px;line-height:1.5;box-shadow:0 10px 34px rgba(0,0,0,.6)";
  el.textContent = "⚠ " + msg + " ";
  if (actionLabel && actionFn) {
    const b = document.createElement("button");
    b.textContent = actionLabel;
    b.style.cssText = "display:block;margin-top:9px;font:inherit;font-weight:800;border:0;border-radius:9px;"
      + "padding:9px 14px;background:linear-gradient(135deg,#00ad93,#00c9a7);color:#04110a;cursor:pointer";
    b.onclick = () => { el.remove(); actionFn(); };
    el.appendChild(b);
  }
  const x = document.createElement("span");
  x.textContent = "✕";
  x.style.cssText = "position:absolute;top:10px;right:13px;cursor:pointer;color:#ff8d85;font-weight:800";
  x.onclick = () => el.remove();
  el.appendChild(x);
  document.body.appendChild(el);
}
// canPay(dapp, raw, what): the ONE affordability gate before any join/bet/open. True if payable; otherwise
// shows the toast with the exact shortfall + a "Go to Deposit" shortcut (scrolls to the bankroll box and
// pulses Deposit). Signed-out users get a sign-in prompt instead. NO game may fail a stake check silently.
export function canPay(dapp, raw, what) {
  if (!dapp.me) {
    alertBar(what + " needs a wallet — sign in first.", "Sign in with NADO wallet", () => dapp.signIn());
    return false;
  }
  if (dapp.exec >= raw) return true;
  alertBar(what + " costs " + rawToNado(raw) + " NADO in tokens — you only have "
    + rawToNado(dapp.exec) + ". Buy at least " + rawToNado(raw - dapp.exec) + " NADO of tokens (Buy in), then try again.",
    "Go to Buy in", () => {
      const bk = document.getElementById("bankroll"), bd = document.getElementById("btnDeposit");
      if (bd) bd.classList.add("pulse");
      if (bk) { bk.classList.remove("hidden"); try { bk.scrollIntoView({ behavior: "smooth", block: "center" }); } catch {} }
    });
  return false;
}

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
const _L1_FEE_RESERVE = RAW / 1000n;   // leave ~0.001 NADO of L1 for the deposit tx fee when buying in 100%
export function wireWallet(dapp) {
  const st = (m) => { const s = $("status"); if (s) s.textContent = m; };
  if ($("btnSignIn")) $("btnSignIn").onclick = () => dapp.signIn();
  if ($("btnDeposit")) $("btnDeposit").onclick = () => { const raw = nadoToRaw($("bankAmt").value); if (!raw) return st("Enter an amount to deposit."); if (raw + 1000n > dapp.l1) return st("Not enough in your L1 wallet (" + rawToNado(dapp.l1) + " NADO)."); dapp.deposit(raw); };
  if ($("btnWithdraw")) $("btnWithdraw").onclick = () => { const raw = nadoToRaw($("bankAmt").value); if (!raw) return st("Enter an amount to withdraw."); if (dapp.exec < raw) return st("You only have " + rawToNado(dapp.exec) + " NADO in the exec layer."); dapp.withdraw(raw); };
  // BUY-IN / CASH-OUT % sliders: replace the Tokens amount row with two slider rows, each with ITS OWN button
  // on the right — Buy in (a % of your L1 wallet, minus a tiny fee reserve) with Deposit, Cash out (a % of your
  // playable balance) with Withdraw. Each button submits its own slider's resolved amount (independent).
  const bankInput = $("bankAmt");
  if (bankInput && !document.getElementById("buyinSlider")) {
    const dep = $("btnDeposit"), wd = $("btnWithdraw");
    const oldRow = bankInput.closest(".row") || bankInput;
    const buyMax = () => dapp.l1 > _L1_FEE_RESERVE ? dapp.l1 - _L1_FEE_RESERVE : 0n;
    const pctOf = (slId, maxRaw) => { const p = Math.max(0, Math.min(100, parseFloat(document.getElementById(slId).value) || 0)); return p >= 100 ? maxRaw : (BigInt(Math.round(p * 100)) * maxRaw) / 10000n; };
    const mkRow = (slId, label, btn) => {
      const box = document.createElement("div"); box.style.margin = "14px 0 0";
      // header: the action verb (left) + the resolved % · amount (right) — well ABOVE the slider so the knob never covers it
      const head = document.createElement("div"); head.className = "small"; head.style.cssText = "display:flex;justify-content:space-between;gap:8px;margin-bottom:2px;font-weight:700;color:var(--txt)";
      head.innerHTML = '<span>' + label + '</span><span class="mono dim" id="' + slId + 'P">0% · 0 NADO</span>';
      // slider + its button on ONE line — the slider flexes, the button is fixed on the right (never wraps below)
      const r = document.createElement("div"); r.style.cssText = "display:flex;gap:10px;align-items:center";
      const sl = document.createElement("input"); sl.type = "range"; sl.id = slId; sl.min = "0"; sl.max = "100"; sl.value = "0"; sl.step = "1"; sl.style.cssText = "flex:1 1 auto;width:auto;min-width:0;margin:0";
      r.appendChild(sl); if (btn) { btn.style.cssText = "flex:0 0 auto"; r.appendChild(btn); }
      const hint = document.createElement("div"); hint.className = "small dim"; hint.style.marginTop = "3px"; hint.id = slId + "M";
      box.appendChild(head); box.appendChild(r); box.appendChild(hint);
      return { box, sl };
    };
    if (dep) dep.textContent = "Buy in"; if (wd) wd.textContent = "Cash out";
    const bi = mkRow("buyinSlider", "⬆ Buy in", dep);
    const co = mkRow("cashoutSlider", "⬇ Cash out", wd);
    oldRow.insertAdjacentElement("afterend", co.box);
    oldRow.insertAdjacentElement("afterend", bi.box);
    oldRow.classList.add("hidden");   // the old amount+buttons row (buttons were moved into the slider rows)
    const upd = (slId, maxFn) => { const p = Math.round(parseFloat(document.getElementById(slId).value) || 0); document.getElementById(slId + "P").textContent = p + "% · " + rawToNado(pctOf(slId, maxFn())) + " NADO"; };
    bi.sl.oninput = () => upd("buyinSlider", buyMax);
    co.sl.oninput = () => upd("cashoutSlider", () => dapp.exec);
    if (dep) dep.onclick = () => { const raw = pctOf("buyinSlider", buyMax()); if (raw <= 0n) return st("Slide how much to buy in."); if (raw + 1000n > dapp.l1) return st("Not enough in your L1 wallet (" + rawToNado(dapp.l1) + " NADO)."); dapp.deposit(raw); };
    if (wd) wd.onclick = () => { const raw = pctOf("cashoutSlider", dapp.exec); if (raw <= 0n) return st("Slide how much to cash out."); if (dapp.exec < raw) return st("You only have " + rawToNado(dapp.exec) + " NADO playable."); dapp.withdraw(raw); };
  }
}
// renderWallet(dapp): the who/bal/l1bal header row; returns signedIn so render() can gate on it.
export function renderWallet(dapp) {
  const signedIn = !!dapp.me;
  if ($("btnSignIn")) $("btnSignIn").classList.toggle("hidden", signedIn);
  if ($("who")) $("who").textContent = signedIn ? disp(dapp.me) : "not signed in";
  if ($("bal")) $("bal").textContent = rawToNado(dapp.exec) + " NADO";
  if ($("l1bal")) $("l1bal").textContent = rawToNado(dapp.l1) + " NADO";
  const bm = document.getElementById("buyinSliderM"); if (bm) bm.textContent = "of " + rawToNado(dapp.l1) + " wallet";
  const cm = document.getElementById("cashoutSliderM"); if (cm) cm.textContent = "of " + rawToNado(dapp.exec) + " playable";
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
      + (x.live ? "" : ' title="still confirming on-chain — your bet hasn\'t vanished"') + ">" + (x.icon || "🎯") + " #" + x.id
      + (x.live ? (x.tag ? " · " + x.tag : "") : " · confirming ⏳") + "</button>").join(" ")
    : '<span class="dim">' + (emptyMsg || "No games yet.") + "</span>";
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => onSelect(parseInt(b.dataset.t, 10)));
}
// statusLabel(pend, ok, err, extra): the shared post-redirect status line. Games pass extra phase labels.
export function statusLabel(pend, ok, err, extra) {
  const labels = Object.assign({ connect: "Signed in.", deposit: "Buy-in submitted — confirming…",
    open: "Table opening — confirming…", bet: "Bet placed — confirming…", join: "Joining — confirming…",
    settle: "Collecting — confirming on-chain (~1 min)…", fund: "Topping up…", close: "Closing…",
    resolve: "Rolling out — confirming…", cancel: "Cancelling…", withdraw: "Cash-out submitted." }, extra || {});
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

// ---- sticky inputs: what the player typed survives the wallet round-trip and the next turn --------
// stickyInputs(dapp, ids): per-game localStorage memory for bet/stake/amount fields — a 0.001-NADO bet
// typed once stays there for every following turn. The static value="1" defaults only apply until the
// player first types; an emptied field clears the memory (back to the default next load).
export function stickyInputs(dapp, ids) {
  const key = "nado_" + dapp.app.replace(/\W+/g, "").toLowerCase() + "_inputs";
  let saved = {}; try { saved = JSON.parse(localStorage.getItem(key) || "{}"); } catch {}
  for (const id of ids) {
    const el = $(id); if (!el) continue;
    if (saved[id] != null && saved[id] !== "") el.value = saved[id];
    el.addEventListener("input", () => {
      if (el.value === "") delete saved[id]; else saved[id] = el.value;
      try { localStorage.setItem(key, JSON.stringify(saved)); } catch (e) { /* quota */ }
    });
  }
}

// ---- Share (Web Share API -> clipboard fallback), with button feedback ---------------------------
export async function share(url, text, btn) {
  if (navigator.share) { try { await navigator.share({ title: "NADO", text, url }); return; } catch (e) { if (e && e.name === "AbortError") return; } }
  let ok = false; try { await navigator.clipboard.writeText(url); ok = true; } catch {}
  if (btn) { const t = btn.textContent; btn.textContent = ok ? "Copied ✓" : "copy failed"; setTimeout(() => (btn.textContent = t.replace("Copied ✓", "Share").replace("copy failed", "Share") || "Share"), 1400); }
}
// shareInvite(kind, id, text, qrpx): the ONE invite block every game shows — populate #shareLink, render
// #shareQR, and wire #btnShare, all from the active game/table id. Guards the empty-field case: a null id
// clears the link + hides the QR instead of leaving a stale/blank input. kind is "game" or "table".
export function shareInvite(kind, id, text, qrpx = 200) {
  const link = $("shareLink"), btn = $("btnShare");
  if (id == null) { if (link) link.value = ""; drawQR($("shareQR"), $("shareQRNote"), "", qrpx); return ""; }
  const url = base() + "/?" + kind + "=" + id;
  if (link) link.value = url;
  drawQR($("shareQR"), $("shareQRNote"), url, qrpx);
  if (btn) btn.onclick = () => share(url, text || ("Join me on NADO: " + url), btn);
  return url;
}

// ---- the wallet-backed dApp session --------------------------------------------------------------
export class NadoDapp {
  constructor({ cid, app, ns = "default" }) {
    this.cid = cid; this.app = app; this.ns = ns;
    const slug = app.replace(/\W+/g, "").toLowerCase();
    this.LS_ME = "nado_" + slug + "_me"; this.LS_P = "nado_" + slug + "_pending"; this.LS_INVITE = "nado_" + slug + "_invite";
    this.LS_AUTOCOLLECT = "nado_" + slug + "_autocollect";   // opt-out flag for auto-collect (default ON)
    this._autoTried = new Set();   // settle targets already attempted this session (stops a rejected settle looping)
    this._bgOff = false;      // learned this session: the wallet can't background-sign at all (locked / bg off / untrusted) → always redirect
    this._bgValueUI = false;  // learned: staked calls need a manual confirm here → redirect them directly (value-free still backgrounds)
    this._stakeMode = "amount";   // bet slider: "amount" = user typed a NADO figure; "pct" = user set a % of the table max
    this.me = localStorage.getItem(this.LS_ME) || null;
    this.exec = 0n; this.l1 = 0n; this.cursor = null;
    this._inviteFn = null;   // a followed share-link's join intent — sticky until the join actually commits
    this._inviteExec = null; // exec balance at last invite attempt, so a landed deposit can re-fire the join
    // online: null = never reached the chain API yet (first load), true = last read OK, false = last read
    // FAILED (node restarting / network). Games must consult this before claiming something "isn't on-chain" —
    // a chain hiccup must never be misreported as a vanished table/bet (that's exactly what a rug feels like).
    this.online = null;
    this._onReturn = null;
    this._bh = {};        // height -> block hash hex (BLOCKHASH randomness cache; provisional or finalized)
    this._bhFinal = {};   // height -> 1 once its FINALIZED hash is cached (a frozen value; provisional stays re-checkable)
    this.inflight = null;   // a submitted-but-not-yet-confirmed action (see busy())
  }
  // blockHashes(heights, {fast}): fetch + CACHE L1 block hashes for these heights (from /exec/blockhash),
  // so a beacon game can compute the same result the contract will. bh(h) reads the cache (hex|null|undefined).
  // DEFAULT = FINALIZED hashes (immutable) — required for HIDDEN info (Hold'em hole cards): a pre-finality
  // hash that reorged would silently show a different hand at showdown. fast:true opts into the PROVISIONAL
  // (pre-finality) tail — only for PUBLIC, on-chain-VALIDATED randomness (Farkle dice): a reorg there just
  // reverts the settling tx (a visible retry), never silent unfairness. fast cuts the reveal wait from
  // ~FINALITY_DEPTH (~90s) to ~one block (~6-18s). A fast (unfinal) hash is cached but re-checked (it can
  // still change), so we never freeze a provisional value.
  async blockHashes(heights, opts) {
    const fast = !!(opts && opts.fast);
    const need = [...new Set(heights)].filter((h) => this._bh[h] === undefined || (fast && !this._bhFinal[h]));
    if (need.length) {
      try {
        const url = base() + "/exec/blockhash?ns=" + this.ns + (fast ? "&provisional=1" : "") + "&heights=" + need.join(",");
        const j = await (await fetch(url, { cache: "no-store" })).json();
        for (const h of need) {
          const v = j.hashes && j.hashes[String(h)];
          if (v) { this._bh[h] = v; if (!fast) this._bhFinal[h] = 1; }   // mark finalized values as frozen
        }
      } catch {}
    }
    return this._bh;
  }
  bh(h) { return this._bh[h]; }
  async init() { await loadCrypto(); this._handleReturn(); if (this.me) await this.refresh(); }
  onReturn(fn) { this._onReturn = fn; }        // fn(pend, ok, err) — game marks its own local state + status

  // --- delegated signing (the wallet holds the key; the game NEVER sees it) -------------------------
  // Two transports. (1) REDIRECT: navigate the whole tab to the wallet, which signs + submits + bounces
  // back. Needed whenever the wallet must show UI (sign-in, deposit, a manual bet confirm) or unlock.
  // (2) BACKGROUND: for value-free autosign-eligible calls (game moves, auto-collect settles), load the
  // wallet in a HIDDEN IFRAME and let it sign + submit + postMessage the result — NO navigation, so
  // auto-collect doesn't yank the tab to the wallet and back. The iframe falls back to the redirect the
  // instant the wallet says it needs UI (locked / not autosigned / untrusted) or doesn't answer in time,
  // so the worst case is exactly today's behaviour.
  _goRedirect(obj, pend) {
    const payload = btoa(unescape(encodeURIComponent(JSON.stringify(obj))));
    localStorage.setItem(this.LS_P, JSON.stringify(pend || {}));
    location.href = WALLET + "/?exec_sign=" + encodeURIComponent(payload) + "&ret=" + encodeURIComponent(base() + "/") + "&app=" + encodeURIComponent(this.app);
  }
  // ONE persistent hidden iframe holds a loaded wallet that signs every background request over postMessage —
  // so we pay the ~1s wallet boot ONCE, not per call. Requests are serialised (one in flight; the rest queue).
  // Every failure path (service never readies, request times out, wallet says needui) falls back to the proven
  // per-call redirect, and the learned _bgOff/_bgValueUI flags stop pointless attempts.
  _ensureBgSvc() {
    if (this._bgSvc) return this._bgSvc;
    let walletOrigin; try { walletOrigin = new URL(WALLET).origin; } catch (e) { return null; }
    const frame = document.createElement("iframe");
    frame.setAttribute("aria-hidden", "true");
    frame.style.cssText = "position:fixed;left:-9999px;top:-9999px;width:1px;height:1px;border:0;opacity:0;pointer-events:none";
    frame.src = WALLET + "/?bgsvc=1";
    const svc = { frame, walletOrigin, ready: false, dead: false, cur: null, timer: 0, queue: [] };
    this._bgSvc = svc;
    svc.onMsg = (e) => {
      if (e.origin !== svc.walletOrigin) return;
      const d = e.data; if (!d) return;
      if (d.nadoBgReady) { svc.ready = true; clearTimeout(svc.readyTimer); this._bgPump(); return; }
      if (d.nadoExecSign != null && svc.cur) { const cb = svc.cur; svc.cur = null; clearTimeout(svc.timer); cb(d); }
    };
    window.addEventListener("message", svc.onMsg);
    svc.readyTimer = setTimeout(() => { if (!svc.ready) { svc.dead = true; this._bgFlushToRedirect(); } }, 12000);   // never readied (framing blocked?) → redirect everything
    (document.body || document.documentElement).appendChild(frame);
    return svc;
  }
  _bgFlushToRedirect() {
    const svc = this._bgSvc; if (!svc) return;
    const jobs = svc.queue.splice(0); if (svc.cur) { svc.cur = null; }
    for (const j of jobs) this._goRedirect(j.obj, j.pend);
  }
  _goBackground(obj, pend, isValue) {
    const svc = this._ensureBgSvc();
    if (!svc || svc.dead) return this._goRedirect(obj, pend);
    svc.queue.push({ obj, pend, isValue });
    this._bgPump();
  }
  _bgPump() {
    const svc = this._bgSvc;
    if (!svc || svc.dead || !svc.ready || svc.cur || !svc.queue.length) return;
    const job = svc.queue.shift();
    svc.cur = (d) => {
      if (d.needui) {
        if (d.reason === "off" || d.reason === "locked" || d.reason === "untrusted") this._bgOff = true;   // global block
        else if (job.isValue) this._bgValueUI = true;                                                      // staked call needs a confirm
        this._goRedirect(job.obj, job.pend);
      } else {
        const ok = d.ok === 1 || d.ok === true || d.ok === "1";   // the "ok=1" param rides as a STRING
        this._applyReturn(job.pend, ok, d.addr || null, d.err ? String(d.err) : "");
        try { this.refresh(); } catch (e) {}                      // pull the freshly-landed state, no reload
      }
      this._bgPump();                                             // serve the next queued request
    };
    svc.timer = setTimeout(() => {                                // the loaded wallet went silent → treat service as dead, redirect
      if (!svc.cur) return; svc.cur = null; svc.dead = true;
      this._goRedirect(job.obj, job.pend); this._bgFlushToRedirect();
    }, 9000);
    const payload = btoa(unescape(encodeURIComponent(JSON.stringify(job.obj))));
    try { svc.frame.contentWindow.postMessage({ nadoExecSignReq: 1, payload, ret: base() + "/", app: this.app }, svc.walletOrigin); }
    catch (e) { svc.cur = null; clearTimeout(svc.timer); this._goRedirect(job.obj, job.pend); }
  }
  _go(obj, pend, bg, isValue) {
    if (bg && !obj.confirm) this._goBackground(obj, pend, isValue);
    else this._goRedirect(obj, pend);
  }
  signIn() { this._goRedirect({ connect: true, label: "sign in" }, { phase: "connect" }); }
  deposit(raw) { this._goRedirect({ deposit: { amount: raw.toString() }, label: "buy in " + rawToNado(raw) + " NADO" }, { phase: "deposit" }); }
  withdraw(raw, pend) { this.signBlob({ op: "bridge_withdraw", amount: raw }, "cash out " + rawToNado(raw) + " NADO", pend || { phase: "withdraw" }); }
  signBlob(blob, label, pend, opts) { this._go(Object.assign({ blob: encBig(blob), label }, (opts && opts.confirm) ? { confirm: 1 } : {}), pend, !!(opts && opts.bg), !!(opts && opts.isValue)); }
  // generic contract call; valueRaw (raw NADO) is ESCROWED from the caller's bridge balance into the contract.
  // opts.confirm forces the wallet's manual confirm (e.g. a poker bet that moves chips you already escrowed) —
  // autosign must never place a bet for you. EVERY non-confirm call is BACKGROUND-able: it's attempted in a
  // hidden iframe, and the WALLET decides whether it can sign silently (value-free auto-sign, or a bet within
  // the cap / auto-sign-all for a staked call like a slot Spin) or must open for a confirm (→ needui → redirect).
  // Learned flags (_bgOff / _bgValueUI) route straight to the redirect once the wallet says it can't autosign,
  // so a non-autosign wallet never eats the iframe→redirect double-load twice.
  call(method, args, valueRaw, label, pend, opts) {
    const p = { op: "call", contract: this.cid, method, args };
    const isValue = valueRaw != null;
    if (isValue) p.value = valueRaw;
    let bg = !(opts && opts.confirm) && !this._bgOff;
    if (bg && isValue && this._bgValueUI) bg = false;   // this wallet confirms staked calls → redirect it directly
    this.signBlob(p, label, pend, Object.assign({}, opts, { bg, isValue }));
  }
  // apply a signing RESULT (from either transport) — set the address / inflight / balance-watch and fire onReturn
  _applyReturn(pend, ok, addr, err) {
    if (ok && addr) { this.me = addr; localStorage.setItem(this.LS_ME, addr); }
    // A REJECTED action (ok=0 with a reason) must be shown LOUDLY — never left to masquerade as the
    // optimistic "confirming…" placeholder. The err is the node's real reason (e.g. a chain_id mismatch).
    if (!ok && err) { try { alertBar("Rejected: " + err + (/chain id/i.test(err) ? " — hard-refresh this page and your wallet to update to the current network." : "")); } catch (e) {} }
    // remember a just-submitted action so games can show "confirming…" and NEVER re-offer the button the
    // user already clicked (e.g. coinflip "Join this game" reappearing before the join confirms on-chain).
    if (ok && pend && pend.phase && !["connect", "deposit", "withdraw"].includes(pend.phase)) {
      this.inflight = Object.assign({ ts: Date.now() }, pend);
    }
    // deposit/withdraw confirmations are watched by the SDK itself: their optimistic status line clears the
    // moment the balances MOVE (or after 3 min).
    if (ok && pend && (pend.phase === "deposit" || pend.phase === "withdraw")) this._balWatch = { phase: pend.phase, exec: null };
    if (this._onReturn) this._onReturn(pend, ok, err);
  }
  _handleReturn() {
    const p = new URLSearchParams(location.search);
    if (!p.has("ok")) return;
    const ok = p.get("ok") === "1", addr = p.get("addr"), err = p.get("err") ? decodeURIComponent(p.get("err")) : "";
    let pend = null; try { pend = JSON.parse(localStorage.getItem(this.LS_P) || "null"); } catch {}
    localStorage.removeItem(this.LS_P);
    try { history.replaceState(null, "", location.pathname); } catch {}
    this._applyReturn(pend, ok, addr, err);
  }
  // busy(phase, keyName, keyVal): is there an in-flight action of this phase for this game/table/seat?
  // Auto-expires after 3 min (a lost tx) so a stuck flag can't hide the button forever. Games call
  // dapp.clearInflight() once they SEE the effect on-chain (the definitive "it landed").
  busy(phase, keyName, keyVal) {
    const f = this.inflight;
    if (!f) return false;
    if (Date.now() - f.ts > 180000) { this.inflight = null; return false; }   // expire FIRST, whatever the
    if (f.phase !== phase) return false;   // phase asked about — else an unpolled phase sticks forever
    if (keyName != null && String(f[keyName]) !== String(keyVal)) return false;
    return true;
  }
  clearInflight() { this.inflight = null; }
  // reflectUrl(key, id): keep the address bar pointing at the selected table/game/pet, so it's the exact
  // shareable link (?<key>=<id>) and Back/refresh return here. replaceState (no history spam); only when it
  // actually changes. Pass null/"" to clear the param. Call from render().
  reflectUrl(key, id) {
    try {
      const want = (id != null && id !== "") ? "?" + key + "=" + id : "";
      if (location.search !== want) history.replaceState(null, "", location.pathname + want + location.hash);
    } catch (e) {}
  }

  // ── AUTO-COLLECT ────────────────────────────────────────────────────────────────────────────────
  // The shared "settle my winnings for me" tick every beacon game had copy-pasted. Call once per refresh
  // AFTER state is derived, passing the ALREADY-FILTERED list of settleable items (my ready wins, etc.) and
  // a settle(item) that fires the value-free settle (which auto-signs → a quick bounce, not a tap). One per
  // tick — the wallet redirect serialises it; on return the next fires until the board is clean. Opt-out via
  // nado_<slug>_autocollect. `autoTried` (per session) stops a rejected settle from looping. opts.blocked lets
  // a game pass its own "already waiting on a tx" flag (e.g. a confirmation `watch`). opts.key ids an item
  // (default it.g). Returns true if it fired a settle.
  autoCollect(candidates, settle, opts = {}) {
    if (!this.me || this.inflight || opts.blocked) return false;
    try { if (localStorage.getItem(this.LS_AUTOCOLLECT) === "0") return false; } catch (e) {}
    const keyOf = opts.key || ((x) => x.g);
    const t = (candidates || []).find((x) => !this._autoTried.has(keyOf(x)));
    if (!t) return false;
    this._autoTried.add(keyOf(t));
    settle(t);
    return true;
  }
  // wireAutoCollect(el): bind the standard "Auto-collect my winnings" slider (#autoCollect by default) to the
  // opt-out flag. Default ON. Call once from wireUI.
  wireAutoCollect(el) {
    el = el || document.getElementById("autoCollect"); if (!el) return;
    try { el.checked = localStorage.getItem(this.LS_AUTOCOLLECT) !== "0"; } catch (e) { el.checked = true; }
    el.onchange = () => { try { localStorage.setItem(this.LS_AUTOCOLLECT, el.checked ? "1" : "0"); } catch (e) {} };
  }

  // ── MAX-BET STAKE SLIDER ───────────────────────────────────────────────────────────────────────
  // ── the ONE percent-slider primitive: a fixed 0..100% slider bound to a number input, resolving to a % of
  // some live max (a bet's coverable max, your L1 wallet, your playable balance…). In "pct" mode the AMOUNT is
  // DERIVED from the live max (100% is always exactly the current max, no chasing a moving value); typing an
  // amount switches to "amount" mode and the thumb reflects the implied %. State is per `name` so many can
  // coexist. wirePctSlider() binds the slider+input+Max once; syncPctSlider() refreshes it from render().
  // ids: { slider, input, wrap?, max?, maxLabel?, pctLabel? } are element ids.
  wirePctSlider(name, ids, maxRawFn, onChange) {
    if (!this._pct) this._pct = {};
    this._pct[name] = "amount";
    const inp = ids.input && document.getElementById(ids.input);
    let sl = ids.slider && document.getElementById(ids.slider);
    if (!sl && inp && ids.slider && ids.inject !== false) {   // no slider in the HTML → inject one right after the input
      sl = document.createElement("input");
      sl.type = "range"; sl.id = ids.slider; sl.min = "0"; sl.max = "100"; sl.value = "0"; sl.step = "1"; sl.className = "mt";
      const lbl = document.createElement("div");
      lbl.className = "small dim"; lbl.style.cssText = "display:flex;justify-content:space-between;gap:8px";
      lbl.innerHTML = '<span id="' + ids.slider + '_p"></span><span id="' + ids.slider + '_m" class="mono"></span>';
      const anchor = inp.closest(".row") || inp;
      anchor.insertAdjacentElement("afterend", sl);
      sl.insertAdjacentElement("afterend", lbl);
    }
    const maxBtn = ids.max && document.getElementById(ids.max);
    if (sl) sl.oninput = () => { this._pct[name] = "pct"; onChange && onChange(); };
    if (inp) inp.oninput = () => { this._pct[name] = "amount"; onChange && onChange(); };
    if (maxBtn) maxBtn.onclick = () => { this._pct[name] = "pct"; if (sl) sl.value = "100"; onChange && onChange(); };
  }
  syncPctSlider(name, ids, maxRaw) {
    const sl = ids.slider && document.getElementById(ids.slider);
    const inp = ids.input && document.getElementById(ids.input);
    const wrap = ids.wrap ? document.getElementById(ids.wrap) : sl;
    if (!sl || !inp) return;
    if (maxRaw == null || maxRaw <= 0n) { if (wrap) wrap.classList.add("hidden"); return; }
    if (wrap) wrap.classList.remove("hidden");
    sl.min = "0"; sl.max = "100"; sl.step = "1";
    const maxN = parseFloat(rawToNado(maxRaw)) || 0;
    const mode = (this._pct && this._pct[name]) || "amount";
    if (mode === "pct") {
      const pct = Math.max(0, Math.min(100, parseFloat(sl.value) || 0));
      inp.value = rawToNado(pct >= 100 ? maxRaw : (BigInt(Math.round(pct * 100)) * maxRaw) / 10000n);   // % of the LIVE max; 100% = exact max
    } else if (document.activeElement !== sl) {
      const a = parseFloat(inp.value) || 0;
      sl.value = String(maxN > 0 ? Math.max(0, Math.min(100, Math.round(a / maxN * 100))) : 0);          // reflect the typed amount as a %
    }
    const pctNow = Math.round(parseFloat(sl.value) || 0);
    const setT = (elid, txt) => { if (elid) { const e = document.getElementById(elid); if (e) e.textContent = txt; } };
    setT(ids.maxLabel || (ids.slider + "_m"), rawToNado(maxRaw) + " NADO");
    setT(ids.pctLabel || (ids.slider + "_p"), pctNow + "% · " + (inp.value || "0") + " NADO");
  }
  // the bet slider is just the primitive bound to the stake input (kept as named helpers so games don't change)
  syncStakeSlider(maxRaw, ids = {}) {
    this.syncPctSlider("stake", { slider: ids.slider || "stakeSlider", input: ids.stake || "stakeAmt", wrap: ids.wrap || "stakeSliderWrap", maxLabel: ids.maxVal || "maxBetVal", pctLabel: ids.sliderVal || "stakeSliderVal" }, maxRaw);
  }
  wireStakeSlider(maxRawFn, onChange, ids = {}) {
    this.wirePctSlider("stake", { slider: ids.slider || "stakeSlider", input: ids.stake || "stakeAmt", max: ids.maxBtn || "btnMaxBet" }, maxRawFn, onChange);
  }

  // consumeInvite(fn): after a share-link visitor signs in (inviteGate), replay the join they asked for.
  // The intent is STICKY: it is NOT dropped on the first attempt, because joining a staked table usually
  // needs a deposit first (a wallet round-trip whose funds land a few seconds LATER). We keep the invite
  // in localStorage and re-fire fn(id) on every return AND the moment a deposit lands (exec balance rises),
  // so the seat is taken automatically instead of the player having to hunt for the table again. The game
  // MUST call dapp.clearInvite() the instant it actually commits the join (right before submitting), and
  // for terminal cases (table gone / seating closed / already seated). Pass no fn to just retry the stored
  // intent (used by the deposit-landed hook). fn(id) may be async; its return value is not required.
  consumeInvite(fn) {
    if (fn) this._inviteFn = fn;
    const f = this._inviteFn; if (!f || !this.me) return;
    let id = null; try { id = localStorage.getItem(this.LS_INVITE); } catch (e) {}
    if (id == null || id === "") { this._inviteFn = null; return; }
    this._inviteExec = this.exec;
    try { f(id); } catch (e) {}
  }
  clearInvite() { try { localStorage.removeItem(this.LS_INVITE); } catch (e) {} this._inviteFn = null; this._inviteExec = null; }

  // --- reads ---
  async refresh() { await Promise.all([this._balances(), this._cursor()]); }
  async _balances() {
    if (!this.me) { this.exec = 0n; this.l1 = 0n; return; }
    try { const b = await (await fetch(base() + "/exec/bridge?ns=" + this.ns + "&provisional=1", { cache: "no-store" })).json(); this.exec = BigInt((b.balances || {})[this.me] || 0); } catch { this.exec = 0n; }
    try { const a = await (await fetch(base() + "/get_account?address=" + encodeURIComponent(this.me), { cache: "no-store" })).json(); this.l1 = BigInt(a.balance || 0); } catch { this.l1 = 0n; }
    // deposit landed while a share-link join is still pending → replay it now that funds are here, so the
    // seat is taken automatically. Fire only on an INCREASE (never every poll) so it can't spam the toast.
    if (this._inviteFn && this._inviteExec != null && this.exec > this._inviteExec) this.consumeInvite();
    const w = this._balWatch;
    if (w) {
      if (w.exec == null) { w.exec = this.exec; w.l1 = this.l1; w.ts = Date.now(); }   // baseline: first read after return
      else if (this.exec !== w.exec || this.l1 !== w.l1 || Date.now() - w.ts > 180000) {
        this._balWatch = null;
        const el = document.getElementById("status");   // only replace the OPTIMISTIC line, never a newer message
        if (el && /confirming|submitted/i.test(el.textContent || "")) {
          el.textContent = w.phase === "deposit" ? "✓ Tokens bought — your playable balance is updated." : "✓ Cashed out — back in your main-chain wallet.";
        }
      }
    }
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
    // We ALWAYS check the exec balance BEFORE submitting (canPay), so a "didn't confirm" is never a funds
    // problem — it's the network not landing it in time. Say that plainly and point to the retry; never ask
    // the user a question they can't answer, and never touch their money to find out.
    if (openedTs) return Date.now() - openedTs > 150000
      ? "⚠ " + kind + " #" + id + " didn't confirm — the network was busy. Your funds weren't touched; tap Re-open to try again."
      : kind + " #" + id + " is confirming on-chain (~1 min)…";
    return kind + " #" + id + " isn't on-chain yet — if you just opened it, give it ~1 min; otherwise check the ID.";
  }
}
