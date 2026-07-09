// coinflip.js — NADO Coin Flip: a fair, STAKED 2-player commit-reveal game on the execution layer.
// Value flows through the bridge: deposit L1 NADO -> exec balance -> stake into a game pot -> winner takes the
// pot -> winner -> withdraw to L1. It is an ON-CHAIN CONTRACT (runtime stackvm, cid below) called via the
// GENERIC exec `call` op — the stake is escrowed as the call's VALUE and paid out by the contract's PAY; there
// is NO coinflip-specific API. Reads derive from the contract's storage (/exec/contract). Login + every
// signature is delegated to the NADO wallet (get.nadochain.com) via exec_sign; the key never touches this
// origin, and this page only holds the game secret until reveal.
import { loadCrypto, blake2bHash } from "./nadotx.js";

const NS = "default";
const WALLET = "https://get.nadochain.com";
const RAW = 10n ** 10n;                 // 1 NADO = 1e10 raw units
const base = () => location.origin.replace(/\/+$/, "");
const $ = (id) => document.getElementById(id);

// ---- QR (vendored, best-effort — same generator as the wallet) -----------------------------------
let qrEncode = null;
async function loadQR() { try { const m = await import("./vendor/qrcode.js"); qrEncode = m.qrMatrix || null; } catch { qrEncode = null; } }
function drawQR(canvas, note, text, targetPx) {
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
async function shareGame() {
  if (active == null) return;
  const url = base() + "/?game=" + active;
  const stake = (lastGame && lastGame.exists) ? rawToNado(lastGame.stake) + " NADO " : "";
  if (navigator.share) {
    try { await navigator.share({ title: "NADO Coin Flip", text: "Flip me for " + stake + "on NADO — join game #" + active + ":", url }); return; }
    catch (e) { if (e && e.name === "AbortError") return; }
  }
  const btn = $("btnShare"); let ok = false;
  try { await navigator.clipboard.writeText(url); ok = true; } catch {}
  if (btn) { btn.textContent = ok ? "Copied ✓" : "copy failed"; setTimeout(() => (btn.textContent = "Share"), 1400); }
}

const LS_ME = "nado_coinflip_me", LS_G = "nado_coinflip_games", LS_P = "nado_coinflip_pending";
const gamesLoad = () => { try { return JSON.parse(localStorage.getItem(LS_G) || "{}"); } catch { return {}; } };
const gamesSave = (g) => { try { localStorage.setItem(LS_G, JSON.stringify(g)); } catch {} };
let me = localStorage.getItem(LS_ME) || null;
let active = null, lastGame = null, myBalance = 0n, myL1Balance = 0n;
const FEE = 1000n;   // MIN_TX_FEE (raw) — a deposit spends amount + this from the L1 wallet
let deepLinkGame = null;   // set when arriving via ?game= — pulses the Join (or Sign-in) button until joined
const stageCache = {};     // gid -> {settled, ncom} : drives the game-list colours (settled is terminal, cached)

// ---- amounts / secrets ---------------------------------------------------------------------------
const randId = () => globalThis.crypto.getRandomValues(new Uint32Array(1))[0] % 1000000000;
const randSecret = () => { let h = "0x"; for (const b of globalThis.crypto.getRandomValues(new Uint8Array(32))) h += b.toString(16).padStart(2, "0"); return BigInt(h); };
const commitHashOf = (secret) => BigInt("0x" + blake2bHash(secret));   // 256-bit; == VM HASH(secret)
function nadoToRaw(s) {
  s = String(s || "").trim(); if (!/^\d+(\.\d+)?$/.test(s)) return null;
  const [w, f = ""] = s.split("."); const raw = BigInt(w) * RAW + BigInt((f + "0000000000").slice(0, 10));
  return raw > 0n ? raw : null;
}
const rawToNado = (raw) => { raw = BigInt(raw); const w = raw / RAW, f = (raw % RAW).toString().padStart(10, "0").replace(/0+$/, ""); return f ? `${w}.${f}` : `${w}`; };
const encBig = (v) => typeof v === "bigint" ? { $big: v.toString() }
  : Array.isArray(v) ? v.map(encBig)
  : (v && typeof v === "object") ? Object.fromEntries(Object.keys(v).map((k) => [k, encBig(v[k])])) : v;

// ---- delegated wallet signing (redirect) ---------------------------------------------------------
function go(obj, pend) {
  const payload = btoa(unescape(encodeURIComponent(JSON.stringify(obj))));
  localStorage.setItem(LS_P, JSON.stringify(pend || {}));
  location.href = WALLET + "/?exec_sign=" + encodeURIComponent(payload) + "&ret=" + encodeURIComponent(base() + "/") + "&app=" + encodeURIComponent("Coin Flip");
}
const signIn = () => go({ connect: true, label: "sign in" }, { phase: "connect" });
const deposit = (raw) => go({ deposit: { amount: raw.toString() }, label: "deposit " + rawToNado(raw) + " NADO" }, { phase: "deposit" });
const signBlob = (blob, label, pend) => go({ blob: encBig(blob), label }, pend);

// on return from the wallet
function handleReturn() {
  const p = new URLSearchParams(location.search);
  if (!p.has("ok")) return;
  const ok = p.get("ok") === "1", addr = p.get("addr"), err = p.get("err") ? decodeURIComponent(p.get("err")) : "";
  let pend = null; try { pend = JSON.parse(localStorage.getItem(LS_P) || "null"); } catch {}
  localStorage.removeItem(LS_P);
  try { history.replaceState(null, "", location.pathname); } catch {}
  if (ok && addr) { me = addr; localStorage.setItem(LS_ME, addr); }
  if (!pend) return;
  const label = { connect: "Signed in.", deposit: "Deposit submitted — confirming on-chain…", bet: "Bet submitted — confirming…",
                  reveal: "Flip submitted — confirming…", settle: "Settling…", claim: "Claiming…", withdraw: "Withdrawal submitted." }[pend.phase] || "Submitted.";
  if (pend.gameId != null) active = pend.gameId;
  if (ok && pend.phase === "bet") { const g = gamesLoad(); if (g[pend.gameId]) { g[pend.gameId].bet = "pending"; gamesSave(g); } }
  if (ok && pend.phase === "reveal") { const g = gamesLoad(); if (g[pend.gameId]) { g[pend.gameId].reveal = "pending"; gamesSave(g); } }
  $("status").textContent = ok ? label : "Rejected" + (err ? ": " + err : ".");
}

// ---- reads ---------------------------------------------------------------------------------------
async function fetchBalance() {
  if (!me) { myBalance = 0n; myL1Balance = 0n; return; }
  try {
    const b = await (await fetch(base() + "/exec/bridge?ns=" + NS + "&provisional=1", { cache: "no-store" })).json();
    myBalance = BigInt((b.balances || {})[me] || 0);
  } catch { myBalance = 0n; }
  try {
    const a = await (await fetch(base() + "/get_account?address=" + encodeURIComponent(me), { cache: "no-store" })).json();
    myL1Balance = BigInt(a.balance || 0);   // L1 wallet balance — what a deposit can draw from
  } catch { myL1Balance = 0n; }
}
const CID = "7ee95a0abd6e00d12edc3bf39f4c8f2d";   // the Coin Flip CONTRACT (runtime stackvm) — staked via VALUE/PAY, no native API

// generic contract call, signed by the wallet; valueRaw (raw NADO) is ESCROWED from the caller's bridge balance
function callC(method, args, valueRaw, label, pend) {
  const payload = { op: "call", contract: CID, method, args };
  if (valueRaw != null) payload.value = valueRaw;
  signBlob(payload, label, pend);
}
// coin result — MUST match the contract: HASH(s1+s2) % 2, HASH = blake2b(decimal string) as a 256-bit int
function coinResult(s1, s2) { return Number(BigInt("0x" + blake2bHash((BigInt(s1) + BigInt(s2)).toString())) % 2n); }

// ---- reads: game / lobby / scoreboard are all DERIVED from the contract's storage maps ----------
let lastStorage = {};
async function fetchStorage() {
  try { return (await (await fetch(base() + "/exec/contract?ns=" + NS + "&cid=" + CID + "&provisional=1", { cache: "no-store" })).json()).storage || {}; }
  catch { return null; }
}
const _m = (sto, name) => sto[name] || {};
const allGids = (sto) => Object.keys(_m(sto, "nn"));
function gameFrom(sto, gid) {
  gid = String(gid); const nn = _m(sto, "nn")[gid] || 0;
  if (!nn) return { exists: false };
  const p1 = _m(sto, "p1")[gid], p2 = _m(sto, "p2")[gid];
  const r1 = _m(sto, "r1")[gid] ? 1 : 0, r2 = _m(sto, "r2")[gid] ? 1 : 0;
  const players = {};
  if (p1) players[p1] = { slot: 1, committed: true, revealed: !!r1 };
  if (p2) players[p2] = { slot: 2, committed: true, revealed: !!r2 };
  const settled = !!_m(sto, "sd")[gid], ws = _m(sto, "ws")[gid] || 0;
  const g = { exists: true, stake: _m(sto, "st")[gid] || 0, pot: _m(sto, "pt")[gid] || 0, settled,
              ncom: nn, nrev: r1 + r2, deadline: _m(sto, "dl")[gid] || 0, players };
  if (settled && ws) { g.winner_slot = ws; g.result = ws === 1 ? 0 : 1; }
  else if (r1 && r2) { const s1 = _m(sto, "s1")[gid], s2 = _m(sto, "s2")[gid]; if (s1 != null && s2 != null) { g.result = coinResult(s1, s2); g.winner_slot = g.result === 0 ? 1 : 2; } }
  return g;
}
function lobbyFrom(sto) {
  return allGids(sto).map((gid) => {
    const nn = _m(sto, "nn")[gid], settled = !!_m(sto, "sd")[gid];
    return { game: gid, stake: _m(sto, "st")[gid] || 0, pot: _m(sto, "pt")[gid] || 0, settled, ncom: nn,
             nrev: (_m(sto, "r1")[gid] ? 1 : 0) + (_m(sto, "r2")[gid] ? 1 : 0),
             stage: settled ? "done" : (nn >= 2 ? "live" : "open"), deadline: _m(sto, "dl")[gid] || 0 };
  }).sort((a, b) => b.deadline - a.deadline);
}
function boardFrom(sto) {
  const stats = {};
  const bump = (a, won, net) => { const x = stats[a] || (stats[a] = { addr: a, wins: 0, losses: 0, games: 0, net: 0 }); x.games++; x.net += net; won ? x.wins++ : x.losses++; };
  for (const gid of allGids(sto)) {
    if (!_m(sto, "sd")[gid]) continue;
    const p1 = _m(sto, "p1")[gid], p2 = _m(sto, "p2")[gid], ws = _m(sto, "ws")[gid];
    if (!p1 || !p2 || !ws) continue;
    const stake = _m(sto, "st")[gid] || 0, win = ws === 1 ? p1 : p2, lose = ws === 1 ? p2 : p1;
    bump(win, true, stake); bump(lose, false, -stake);
  }
  return Object.values(stats).sort((a, b) => (b.net - a.net) || (b.wins - a.wins));
}
async function fetchGame(gid) { const sto = await fetchStorage(); return sto ? gameFrom(sto, gid) : null; }

const _aliasCache = {};   // address -> "@alias" | null (short address). Same registry the wallet/forum use.
async function resolveAliases(addrs) {
  await Promise.all([...new Set(addrs)].filter((a) => a && !(a in _aliasCache)).map(async (a) => {
    try { const r = await (await fetch(base() + "/get_aliases_of?address=" + encodeURIComponent(a), { cache: "no-store" })).json(); _aliasCache[a] = (r.aliases && r.aliases[0]) || null; }
    catch { _aliasCache[a] = null; }
  }));
}
const disp = (addr) => !addr ? "—" : (_aliasCache[addr] ? "@" + _aliasCache[addr] : addr.slice(0, 10) + "…" + addr.slice(-4));

// ---- actions -------------------------------------------------------------------------------------
function doDeposit() {
  const raw = nadoToRaw($("depAmt").value);
  if (!raw) { $("status").textContent = "Enter an amount to deposit."; return; }
  if (raw + FEE > myL1Balance) {
    $("status").textContent = "Not enough in your L1 wallet: you have " + rawToNado(myL1Balance) +
      " NADO (deposit needs " + rawToNado(raw) + " + a tiny fee). Mine or receive more first.";
    return;
  }
  deposit(raw);
}
async function newGame() {
  const raw = nadoToRaw($("stakeAmt").value);
  if (!raw) { $("status").textContent = "Enter a stake (NADO)."; return; }
  if (myBalance < raw) { $("status").textContent = "Deposit first — your exec balance is " + rawToNado(myBalance) + " NADO."; return; }
  bet(randId(), raw, "open");
}
async function joinGame() {
  const gid = parseInt($("joinId").value, 10);
  if (!gid) return;
  deepLinkGame = null; $("btnJoin").classList.remove("pulse");   // they clicked — stop nudging
  const g = await fetchGame(gid);
  if (!g || !g.exists) { $("status").textContent = "No such game yet — ask your opponent for the ID after they open it."; return; }
  if (g.settled || g.ncom >= 2) { $("status").textContent = "That game is full or already settled."; return; }
  await fetchBalance();                                   // fresh exec balance before committing to a bet
  const need = BigInt(g.stake);
  if (myBalance < need) {
    $("status").textContent = "You need " + rawToNado(need) + " NADO in your exec balance to join (you have "
      + rawToNado(myBalance) + "). Deposit first — and if your L1 wallet is empty too, mine or receive some NADO.";
    render(); return;
  }
  bet(gid, need, "join");
}
function bet(gameId, stakeRaw, method) {   // method: "open" (slot 1) or "join" (slot 2) — the contract escrows VALUE
  const g = gamesLoad();
  const secretStr = (g[gameId] && g[gameId].secret) ? g[gameId].secret : randSecret().toString();
  g[gameId] = { secret: secretStr, role: method, ts: Date.now(), bet: (g[gameId] || {}).bet, reveal: (g[gameId] || {}).reveal, stake: stakeRaw.toString() }; gamesSave(g);
  active = gameId; render();
  callC(method, [gameId, commitHashOf(BigInt(secretStr))], stakeRaw,
        (method === "open" ? "open" : "join") + " game #" + gameId + " · " + rawToNado(stakeRaw) + " NADO",
        { gameId, phase: "bet" });
}
// join the game currently being viewed (from the lobby / an open table)
async function joinActive() {
  if (active == null || !lastGame || !lastGame.exists) return;
  await fetchBalance();
  const need = BigInt(lastGame.stake);
  if (myBalance < need) { $("status").textContent = "You need " + rawToNado(need) + " NADO in your exec balance to join (you have " + rawToNado(myBalance) + ")."; render(); return; }
  bet(active, need, "join");
}
function reveal() {
  const g = gamesLoad()[active];
  if (!g) { $("status").textContent = "No secret for this game on this device."; return; }
  const slot = (lastGame && lastGame.players && lastGame.players[me]) ? lastGame.players[me].slot : (g.role === "join" ? 2 : 1);
  callC("reveal" + slot, [active, BigInt(g.secret)], null, "flip the coin · game #" + active, { gameId: active, phase: "reveal" });
}
// The rematch game id is DERIVED from the old game (not random), so BOTH players clicking "Play again"
// land in the SAME game — whoever's bet lands first opens it, the other joins slot 2. No split-into-two.
function rematchGidFor(oldGid) {
  return Number((BigInt(oldGid) * 6364136223846793005n + 1442695040888963407n) % 1000000000n);
}
async function rematch() {
  const stake = (lastGame && lastGame.exists) ? BigInt(lastGame.stake)
    : ((gamesLoad()[active] || {}).stake ? BigInt(gamesLoad()[active].stake) : null);
  if (!stake) { $("status").textContent = "Open a new game from the panel above."; return; }
  if (myBalance < stake) { $("status").textContent = "Deposit more to play again — you have " + rawToNado(myBalance) + " NADO, need " + rawToNado(stake) + "."; return; }
  const rgid = rematchGidFor(active);                 // deterministic -> both "Play again" clicks meet in ONE game
  const rg = await fetchGame(rgid);
  bet(rgid, stake, (rg && rg.exists && rg.ncom >= 1 && !rg.settled) ? "join" : "open");
}
const settle = () => callC("settle", [active], null, "settle game #" + active, { gameId: active, phase: "settle" });
const claim = () => callC("claim", [active], null, "claim game #" + active, { gameId: active, phase: "claim" });
const cancelGame = () => callC("cancel", [active], null, "cancel game #" + active, { gameId: active, phase: "cancel" });
function doWithdraw() {
  const raw = nadoToRaw($("wdAmt").value);
  if (!raw) { $("status").textContent = "Enter an amount to withdraw."; return; }
  if (myBalance < raw) { $("status").textContent = "You only have " + rawToNado(myBalance) + " NADO in the exec layer."; return; }
  signBlob({ op: "bridge_withdraw", amount: raw }, "withdraw " + rawToNado(raw) + " NADO to L1", { phase: "withdraw" });
}

async function refreshActive() {
  await fetchBalance();
  const sto = await fetchStorage();
  if (sto) {
    lastStorage = sto;
    if (active != null) lastGame = gameFrom(sto, active);
    for (const gid of allGids(sto)) stageCache[gid] = { settled: !!_m(sto, "sd")[gid], ncom: _m(sto, "nn")[gid] || 0 };
    renderLobby(lobbyFrom(sto));
    renderScoreboard(boardFrom(sto));
  }
  await resolveAliases([me].concat(lastGame && lastGame.players ? Object.keys(lastGame.players) : []));
  render();
}
async function renderScoreboard(board) {
  const el = $("scoreList"); if (!el) return;
  if (!board.length) { el.innerHTML = '<span class="dim">No finished games yet — be the first on the board.</span>'; return; }
  const top = board.slice(0, 10);
  await resolveAliases(top.map((r) => r.addr));
  el.innerHTML = '<table class="score"><thead><tr><th>#</th><th>Player</th><th>W–L</th><th>Net</th></tr></thead><tbody>'
    + top.map((r, i) => {
        const net = (r.net < 0 ? "-" : "+") + rawToNado(Math.abs(r.net)) + " NADO";
        const you = r.addr === me;
        return '<tr' + (you ? ' class="me"' : "") + '><td>' + (i + 1) + '</td><td>' + disp(r.addr) + (you ? " (you)" : "") +
          '</td><td>W' + r.wins + "–L" + r.losses + '</td><td class="' + (r.net >= 0 ? "pos" : "neg") + '">' + net + "</td></tr>";
      }).join("") + "</tbody></table>";
}
function renderLobby(games) {
  const el = $("lobbyList"); if (!el) return;
  const rank = { open: 0, live: 1, done: 2 }, tag = { open: "⏳", live: "▶", done: "✓" }, verb = { open: " · join", live: " · watch", done: "" };
  const shown = (games || []).slice().sort((a, b) => rank[a.stage] - rank[b.stage]).slice(0, 24);
  if (!shown.length) { el.innerHTML = '<span class="dim">No games yet — open one above.</span>'; return; }
  el.innerHTML = shown.map((g) => '<button class="chip ' + g.stage + '" data-lg="' + g.game + '">' + tag[g.stage] + " #" + g.game + " · " + rawToNado(g.stake) + " NADO" + verb[g.stage] + "</button>").join(" ");
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => {
    active = parseInt(b.dataset.lg, 10); $("joinId").value = b.dataset.lg; refreshActive();
    try { window.scrollTo({ top: 0, behavior: "smooth" }); } catch {}
  });
}

// ---- render --------------------------------------------------------------------------------------
function wireUI() {
  $("btnSignIn").onclick = signIn;
  $("btnDeposit").onclick = doDeposit;
  $("btnNew").onclick = newGame;
  $("btnJoin").onclick = joinGame;
  $("joinId").oninput = () => render();   // re-evaluate Join pulse/enabled state as the ID changes
  $("btnReveal").onclick = reveal;
  $("btnSettle").onclick = settle;
  $("btnClaim").onclick = claim;
  $("btnWithdraw").onclick = doWithdraw;
  $("btnShare").onclick = shareGame;
  $("btnRematch").onclick = rematch;
  $("btnJoinActive").onclick = joinActive;
  $("btnCancel").onclick = cancelGame;
}
const badge = (s) => s === "confirmed" ? '<span class="b ok">confirmed ✓</span>' : s === "pending" ? '<span class="b pend">pending…</span>' : '<span class="b dimb">—</span>';
function render() {
  const signedIn = !!me;
  $("btnSignIn").classList.toggle("hidden", signedIn);
  $("who").textContent = signedIn ? disp(me) : "not signed in";
  $("bal").textContent = rawToNado(myBalance) + " NADO";
  $("l1bal").textContent = rawToNado(myL1Balance) + " NADO";
  $("play").classList.toggle("hidden", !signedIn);
  $("bankroll").classList.toggle("hidden", !signedIn);
  // Join guidance: pulse + enable Join ONLY for a game (typed / deep-linked / lobby-clicked) that is joinable
  // AND you're not already in. Disable it for a game you already joined, or one that's full / settled.
  const jid = ($("joinId").value || "").trim();
  const lgv = lastGame || {};
  let iAmIn = false, stageJoinable = true;
  if (jid && String(active) === jid && lgv.exists) {          // we're viewing this game -> exact state
    iAmIn = !!(lgv.players && lgv.players[me]);
    stageJoinable = !lgv.settled && lgv.ncom < 2;
  } else if (jid) {                                            // otherwise use the cached stage / local record
    iAmIn = !!(gamesLoad()[jid] || {}).bet;
    const js = stageCache[jid];
    if (js) stageJoinable = !js.settled && js.ncom < 2;
  }
  const joinable = !!jid && !iAmIn && stageJoinable;
  $("btnJoin").disabled = !!jid && !joinable;                 // greyed out when the entered game isn't joinable
  $("btnJoin").classList.toggle("pulse", joinable && signedIn);
  $("btnSignIn").classList.toggle("pulse", joinable && !signedIn);
  const g = gamesLoad();
  const ids = Object.keys(g).filter((id) => stageCache[id]).sort((a, b) => g[b].ts - g[a].ts).slice(0, 8);   // only games that exist on-chain
  $("recent").innerHTML = ids.length
    ? ids.map((id) => {
        const st = stageCache[id]; let cls = "", tag = "";
        if (st) { if (st.settled) { cls = " done"; tag = "✓ "; } else if (st.ncom >= 2) { cls = " live"; tag = "▶ "; } else { cls = " open"; tag = "⏳ "; } }
        return '<button class="chip' + cls + '" data-g="' + id + '">' + tag + "#" + id + " · " + rawToNado(g[id].stake || "0") + "</button>";
      }).join(" ")
    : '<span class="dim">No games yet.</span>';
  $("recent").querySelectorAll(".chip").forEach((b) => b.onclick = () => { active = parseInt(b.dataset.g, 10); refreshActive(); });
  renderActive();
}
function renderActive() {
  const box = $("activeGame");
  if (active == null) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  const lg = lastGame || {}, local = gamesLoad()[active] || {}, mine = (lg.players || {})[me];
  $("gameId").textContent = "#" + active;
  $("shareLink").value = base() + "/?game=" + active;
  drawQR($("shareQR"), $("shareQRNote"), base() + "/?game=" + active, 200);
  $("pot").textContent = lg.exists ? rawToNado(lg.pot) + " NADO" : "—";
  $("stakeShown").textContent = lg.exists ? rawToNado(lg.stake) + " NADO" : (local.stake ? rawToNado(local.stake) + " NADO" : "—");
  $("gStatus").textContent = lg.exists ? (lg.ncom + "/2 in · " + lg.nrev + "/2 flipped" + (lg.settled ? " · settled" : " · ⚡ live")) : "opening…";
  const pl = lg.players || {};
  const byslot = Object.keys(pl).sort((a, b) => pl[a].slot - pl[b].slot);
  let playersHtml = byslot.map((a) => '<span class="chip">' + (a === me ? "you " : "") + disp(a) + " · slot " + pl[a].slot + (pl[a].revealed ? " ✓" : "") + "</span>").join(" ");
  // show MY join as a pending player until it lands on-chain (finality lag) — otherwise the joiner looks absent
  const myJoinPending = !mine && local.bet === "pending" && lg.exists && lg.ncom < 2;
  if (myJoinPending) playersHtml += ' <span class="chip" style="opacity:.75">you · confirming…</span>';
  $("players").innerHTML = playersHtml || '<span class="dim">no players yet</span>';
  // my local move status, upgraded to confirmed once the chain reflects it
  const betC = mine ? "confirmed" : local.bet, revC = (mine && mine.revealed) ? "confirmed" : local.reveal;
  // "Your bet/flip" only belong to MY OWN game — hide them when I'm just watching/browsing a game I'm not in
  // (e.g. a settled game opened from the public lobby), so a stale local flag can't show "flip: pending" there.
  const showMine = !!mine || (local.bet === "pending" && !lg.settled);
  $("myBet").classList.toggle("hidden", !showMine);
  $("myReveal").classList.toggle("hidden", !showMine);
  // my join was submitted but I'm not on-chain and the game already has 2 players -> it never landed (someone
  // filled it first, or my bet was rejected). Say so clearly instead of hanging on "pending" forever.
  if (!mine && local.bet === "pending" && lg.exists && lg.ncom >= 2)
    $("myBet").innerHTML = 'Your bet: <span class="b" style="background:rgba(248,81,73,.16);color:var(--danger)">didn\'t land — game filled first (your stake is safe)</span>';
  else
    $("myBet").innerHTML = "Your bet: " + badge(betC);
  $("myReveal").innerHTML = "Your flip: " + badge(revC);
  const bothIn = lg.ncom === 2, bothRev = lg.nrev === 2;
  const pastDeadline = lg.exists && !lg.settled && typeof lg.cursor === "number" && lg.cursor > lg.deadline;
  $("btnReveal").classList.toggle("hidden", !(mine && !mine.revealed && bothIn && !lg.settled));
  $("btnSettle").classList.toggle("hidden", !(bothRev && !lg.settled));
  $("btnClaim").classList.toggle("hidden", !pastDeadline);
  $("btnCancel").classList.toggle("hidden", !(me && lg.exists && !lg.settled && lg.ncom === 1 && mine && mine.slot === 1));   // reclaim an un-joined game
  $("btnJoinActive").classList.toggle("hidden", !(me && lg.exists && !lg.settled && lg.ncom < 2 && !mine));  // browse->join
  $("btnRematch").classList.toggle("hidden", !lg.settled);   // Play again (deterministic id -> both clicks meet in one game)
  // coin / result
  const coin = $("coin");
  if (lg.settled && (lg.result === 0 || lg.result === 1)) {
    coin.className = "coin " + (lg.result === 0 ? "heads" : "tails"); coin.textContent = lg.result === 0 ? "H" : "T";
    const iWon = mine && lg.winner_slot === mine.slot;
    $("result").textContent = (lg.result === 0 ? "HEADS" : "TAILS") + " — " + (mine ? (iWon ? "you WON " + rawToNado(BigInt(lg.stake) * 2n) + " NADO 🎉" : "you lost") : "slot " + lg.winner_slot + " won");
  } else if (lg.result === 0 || lg.result === 1) {
    // both have flipped -> the outcome is public + deterministic; show it NOW (don't wait for the settle tx)
    coin.className = "coin " + (lg.result === 0 ? "heads" : "tails"); coin.textContent = lg.result === 0 ? "H" : "T";
    const iWon = mine && lg.winner_slot === mine.slot;
    const outcome = (lg.result === 0 ? "HEADS" : "TAILS") + " — " + (mine ? (iWon ? "you WON " + rawToNado(BigInt(lg.stake) * 2n) + " NADO 🎉" : "you lost") : "slot " + lg.winner_slot + " won");
    $("result").textContent = outcome + " · paying the winner…";
  } else {
    coin.className = "coin spin"; coin.textContent = "?";
    $("result").textContent = bothIn ? "Both in — flip the coin!"
      : myJoinPending ? "Your join is confirming on-chain (~1 min)…"
      : "Waiting for a second player…";
  }
}

async function boot() {
  try { await loadCrypto(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload."; return; }
  wireUI();
  // put the ACTIVE GAME above the bankroll/play card so the game is visible without scrolling past deposits
  if ($("play") && $("activeGame")) $("play").parentNode.insertBefore($("activeGame"), $("play"));
  loadQR();
  handleReturn();
  const q = new URLSearchParams(location.search).get("game");
  if (q) { $("joinId").value = q; if (active == null) active = parseInt(q, 10); deepLinkGame = q; }   // deep link -> show + auto-poll + pulse Join
  if (me) await fetchBalance();
  render();
  refreshActive();               // populate the public lobby (+ balances/active game) immediately on load
  setInterval(refreshActive, 3000);
}
boot();
