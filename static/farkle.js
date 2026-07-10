// farkle.js — NADO Farkle: an OPEN multi-seat, winner-takes-pot Farkle ("Ten Thousand") on the execution layer,
// built on the shared SDK (nadodapp.js). Players ante into a pot and pick a greed THRESHOLD (their push-your-luck
// strategy). At the table's settle block, each seat's WHOLE turn is auto-played on-chain from a FINALIZED L1
// block hash — one beacon draw resolves a full turn, no per-roll waits. Highest banked score takes the pot.
// The same auto-play runs here (matching the contract's die formula exactly) so you can watch your turn roll out.
import { NadoDapp, rawToNado, nadoToRaw, randId, blake2bHash, _m, $, base, gate, canPay, hoist, orderCards, blocksToTime,
         lsLoad as load, lsSave as save, lsPrune, wireWallet, renderWallet, renderScore, scoreBump, scoreSort,
         recentChips, statusLabel,
         loadQR, drawQR, resolveAliases, disp, share } from "./nadodapp.js";

const CID = "143db4a8ff9f01f95ad0b82a1e950e90";
const dapp = new NadoDapp({ cid: CID, app: "Farkle" });
const ROUND_SECS = 6, CAP = 40;   // CAP must match the contract (execnode.vm / farkle_onchain)
const THRESHOLDS = [300, 500, 750, 1000, 1500, 2000, 3000];

const LS_T = "nado_farkle_tables", LS_S = "nado_farkle_seats";
let lastSto = null;
let activeTable = null, lastTable = null, lastSeats = [], threshold = 750;
let knownTables = new Set(), knownSeats = new Set();

function pruneAndTrack(sto) {
  knownTables = lsPrune(LS_T, allTables(sto));
  knownSeats = lsPrune(LS_S, Object.keys(_m(sto, "gg")));
}

// ---- client auto-play (MUST match the contract's die formula + scoring exactly) ------------------
// seed = HASH(bh(sh)+bh(sh+1)+seatId) ; die #k = HASH(seed+k) % 6 + 1  (HASH = blake2b(decimal) as int)
function seedOf(shHex, sh1Hex, g) {
  if (!shHex || !sh1Hex) return null;
  return BigInt("0x" + blake2bHash(BigInt("0x" + shHex) + BigInt("0x" + sh1Hex) + BigInt(g)));
}
const BASE = { 1: 1000, 2: 200, 3: 300, 4: 400, 5: 500, 6: 600 };
function autoPlay(seed, thr) {   // -> { banked, rolls:[{dice,score,bust}] }
  let remaining = 6, total = 0, k = 0; const rolls = [];
  for (let iter = 0; iter < CAP; iter++) {
    const dice = [], counts = [0, 0, 0, 0, 0, 0, 0];
    for (let i = 0; i < remaining; i++) { const d = Number(BigInt("0x" + blake2bHash(seed + BigInt(k + i))) % 6n) + 1; dice.push(d); counts[d]++; }
    k += remaining;
    let score = 0, scnt = 0;
    if (remaining === 6 && [1, 2, 3, 4, 5, 6].every((f) => counts[f] === 1)) { score = 1500; scnt = 6; }
    else for (let f = 1; f <= 6; f++) { const c = counts[f]; if (c >= 3) { score += BASE[f] * (2 ** (c - 3)); scnt += c; } else if (f === 1) { score += c * 100; scnt += c; } else if (f === 5) { score += c * 50; scnt += c; } }
    rolls.push({ dice, score, bust: score === 0 });
    if (score === 0) return { banked: 0, rolls };
    total += score;
    if (total >= thr) return { banked: total, rolls };
    remaining = scnt === remaining ? 6 : remaining - scnt;
  }
  return { banked: 0, rolls };
}
// ---- reads ---------------------------------------------------------------------------------------
const allTables = (sto) => Object.keys(_m(sto, "ta"));
function tableFrom(sto, t) {
  t = String(t); const host = _m(sto, "ta")[t], sh = _m(sto, "tsh")[t];
  if (!host || sh == null) return { exists: false };
  const tb = { exists: true, id: Number(t), host, pot: _m(sto, "tp")[t] || 0, ante: _m(sto, "ts")[t] || 0,
    sh, seatCount: _m(sto, "tn")[t] || 0, resolvedCount: _m(sto, "tx")[t] || 0,
    best: _m(sto, "tw")[t] || 0, leader: _m(sto, "tb")[t] || 0, closed: !!_m(sto, "tz")[t] };
  const cur = dapp.cursor;
  tb.joinOpen = cur != null && cur < sh && !tb.closed;
  tb.rolled = cur != null && cur >= sh + 1;   // settle block finalized -> turns can resolve
  tb.joinEndsIn = cur != null ? sh - cur : null;
  tb.phase = tb.closed ? "done" : tb.joinOpen ? "betting" : tb.rolled ? "resolving" : "spinning";
  return tb;
}
function seatsOfTable(sto, t) {
  t = String(t); const gg = _m(sto, "gg"), cur = dapp.cursor, out = [];
  for (const g of Object.keys(gg)) if (String(gg[g]) === t) {
    const gh = _m(sto, "gh")[g] || 0, thr = _m(sto, "gm")[g] || 0, resolved = !!_m(sto, "gd")[g];
    const s = { g: Number(g), addr: _m(sto, "ga")[g], threshold: thr, gh, resolved };
    if (resolved) s.banked = _m(sto, "gsc")[g] || 0;
    else if (cur != null && cur >= gh + 1) {
      const seed = seedOf(dapp.bh(gh), dapp.bh(gh + 1), Number(g));
      if (seed != null) { const p = autoPlay(seed, thr); s.banked = p.banked; s.rolls = p.rolls; s.ready = true; }
      else { s.pending = true; }
    } else { s.pending = true; s.spinsIn = cur != null ? gh - cur : null; }
    out.push(s);
  }
  return out.sort((a, b) => (b.banked || 0) - (a.banked || 0) || a.g - b.g);
}
async function fetchTable(t) { const sto = await dapp.storage(); return sto ? tableFrom(sto, t) : null; }

// ---- actions -------------------------------------------------------------------------------------
function openTable(t, g, anteRaw, thr) {
  const T = load(LS_T), S = load(LS_S);
  T[t] = { ante: anteRaw.toString(), ts: Date.now() }; save(LS_T, T);
  S[g] = { table: t, threshold: thr, ts: Date.now() }; save(LS_S, S);
  activeTable = t; render();
  dapp.call("open", [t, g, thr], anteRaw, "open a Farkle table #" + t + " · ante " + rawToNado(anteRaw) + " NADO · chase " + thr, { table: t, seat: g, phase: "open" });
}
async function newTable() {
  const raw = nadoToRaw($("anteAmt").value);
  if (!raw) { $("status").textContent = "Enter an ante (NADO)."; return; }
  await dapp.refresh();
  if (!canPay(dapp, raw, "Opening this table")) return;
  openTable(randId(), randId(), raw, threshold);
}
async function joinTable() {
  const t = activeTable;
  if (!t) { $("status").textContent = "Pick a table first."; return; }
  const tb = await fetchTable(t);
  if (!tb || !tb.exists) { $("status").textContent = dapp.whereIs("table", t); return; }
  if (!tb.joinOpen) { $("status").textContent = "The join window for that table has closed."; return; }
  if (lastSeats.some((s) => s.addr === dapp.me)) { $("status").textContent = "You're already seated at this table."; return; }
  await dapp.refresh();
  const ante = BigInt(tb.ante);
  if (!canPay(dapp, ante, "Joining this table")) { render(); return; }
  const g = randId(), S = load(LS_S); S[g] = { table: t, threshold, ts: Date.now() }; save(LS_S, S); render();
  dapp.call("join", [t, g, threshold], ante, "join Farkle table #" + t + " · chase " + threshold, { table: t, seat: g, phase: "join" });
}
function reopenTable() {
  const T = load(LS_T)[activeTable]; if (!T || !T.ante) return;
  const raw = BigInt(T.ante);
  if (!canPay(dapp, raw, "Re-opening this table")) return;
  openTable(activeTable, randId(), raw, threshold);
}
const resolveSeat = (g) => dapp.call("resolve", [g], null, "roll out seat #" + g, { table: activeTable, phase: "resolve" });
const settleTable = () => dapp.call("settle", [activeTable], null, "pay the winner · table #" + activeTable, { table: activeTable, phase: "settle" });
const reclaimTable = () => dapp.call("reclaim", [activeTable], null, "reclaim the pot · table #" + activeTable, { table: activeTable, phase: "reclaim" });

async function refreshActive() {
  await dapp.refresh();
  const sto = await dapp.storage();
  if (sto) {
    lastSto = sto;
    pruneAndTrack(sto);
    if (activeTable != null) {
      lastTable = tableFrom(sto, activeTable);
      const cur = dapp.cursor, need = [];
      for (const g of Object.keys(_m(sto, "gg"))) if (String(_m(sto, "gg")[g]) === String(activeTable)) {
        const gh = _m(sto, "gh")[g] || 0; if (cur != null && cur >= gh + 1) need.push(gh, gh + 1);
      }
      if (need.length) await dapp.blockHashes(need);
      lastSeats = seatsOfTable(sto, activeTable);
    }
    renderLobby(sto); renderScoreboard(boardFrom(sto));
  }
  await resolveAliases([dapp.me].concat(lastTable ? [lastTable.host] : []).concat(lastSeats.map((s) => s.addr)));
  render();
}
function boardFrom(sto) {
  const stats = {};
  for (const t of allTables(sto)) {
    if (!_m(sto, "tz")[t]) continue;                 // only settled tables
    const lead = _m(sto, "tb")[t];                   // pot was zeroed on settle; recompute from ante*seats
    const ante = _m(sto, "ts")[t] || 0, n = _m(sto, "tn")[t] || 0, potTot = ante * n;
    for (const g of Object.keys(_m(sto, "gg"))) if (String(_m(sto, "gg")[g]) === String(t)) {
      const won = Number(g) === lead, net = won ? potTot - ante : -ante;
      scoreBump(stats, _m(sto, "ga")[g], net);
    }
  }
  return scoreSort(stats);
}
const renderScoreboard = (board) => renderScore($("scoreList"), board, dapp.me, "No finished tables yet — be the first on the board.");
function renderLobby(sto) {
  const el = $("lobbyList"); if (!el) return;
  const tables = allTables(sto).map((t) => tableFrom(sto, t)).filter((t) => t.exists && !t.closed);
  tables.sort((a, b) => (b.joinOpen - a.joinOpen) || b.id - a.id);
  el.innerHTML = tables.length ? tables.slice(0, 24).map((t) => {
    const tag = t.joinOpen ? "🟢" : t.rolled ? "🎲" : "⏳";
    const info = t.joinOpen && t.joinEndsIn != null ? " · joins close " + blocksToTime(t.joinEndsIn * ROUND_SECS / ROUND_SECS) : (t.rolled ? " · rolled" : "");
    return '<button class="chip ' + t.phase + '" data-t="' + t.id + '">' + tag + " #" + t.id + " · pot " + rawToNado(t.pot) + " · " + t.seatCount + " player" + (t.seatCount === 1 ? "" : "s") + info + "</button>";
  }).join(" ") : '<span class="dim">No tables yet — open one below.</span>';
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => selectTable(parseInt(b.dataset.t, 10)));
}
function selectTable(id) {
  activeTable = id; $("joinId").value = String(id);
  $("status").textContent = "Table #" + id + " selected.";
  refreshActive();
  try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {}
}

// ---- dice pips + turn rendering ------------------------------------------------------------------
const PIP = { 1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅" };
function rollsHTML(rolls) {
  return rolls.map((r, i) => '<div class="rollline"><span class="rn">' + (i + 1) + '</span> '
    + r.dice.map((d) => '<span class="pip' + (r.bust ? " bust" : "") + '">' + PIP[d] + "</span>").join("")
    + ' <span class="' + (r.bust ? "farkle" : "sc") + '">' + (r.bust ? "FARKLE" : "+" + r.score) + "</span></div>").join("");
}

// ---- render --------------------------------------------------------------------------------------
function syncThreshold() {
  threshold = THRESHOLDS[Math.min(THRESHOLDS.length - 1, Math.max(0, parseInt($("thr").value, 10) || 3))];
  $("thrVal").textContent = threshold;
  const tj = $("thrJoin"); if (tj) tj.textContent = threshold;
  $("thrHint").textContent = threshold <= 500 ? "cautious — bank early, low bust risk" : threshold >= 2000 ? "greedy — chase big, high bust risk" : "balanced";
}
function wireUI() {
  wireWallet(dapp);
  $("btnNewTable").onclick = newTable;
  $("btnJoin").onclick = joinTable;
  $("btnGoTable").onclick = () => { const id = parseInt($("joinId").value, 10); if (id) selectTable(id); else $("status").textContent = "Enter a table ID, or pick one from the lobby."; };
  $("btnReopen").onclick = reopenTable;
  $("btnSettle").onclick = settleTable;
  $("btnReclaim").onclick = reclaimTable;
  $("btnShare").onclick = () => share(base() + "/?table=" + activeTable, "Join my Farkle table #" + activeTable + " on NADO:", $("btnShare"));
  $("thr").oninput = () => syncThreshold();
}
function render() {
  const signedIn = renderWallet(dapp);
  gate({ play: signedIn, opencard: signedIn, bankroll: signedIn, activeGame: activeTable != null });
  const T = load(LS_T), S = load(LS_S), mine = [];
  for (const t of Object.keys(T)) mine.push({ id: +t, role: "host", ts: T[t].ts });
  for (const g of Object.keys(S)) mine.push({ id: S[g].table, seat: g, role: "seat", ts: S[g].ts });
  mine.sort((a, b) => b.ts - a.ts); const seen = new Set();
  const shown = mine.filter((x) => { x.live = x.role === "host" ? knownTables.has(String(x.id)) : knownSeats.has(String(x.seat)); x.icon = "🎲"; const k = String(x.id); if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 8);
  for (const x of shown) {
    if (!x.live || !lastSto) continue;
    const tb = tableFrom(lastSto, x.id);
    if (!tb.exists) continue;
    x.tag = tb.closed ? "finished ✓" : tb.joinOpen ? "joining" : tb.rolled ? (tb.resolvedCount >= tb.seatCount ? "settle!" : "rolled — resolve") : "rolling soon";
  }
  recentChips($("recent"), shown, selectTable, "No tables yet.");
  renderActive();
}
function renderActive() {
  if (activeTable == null) return;
  const tb = lastTable || {}, T = load(LS_T)[activeTable] || {};
  const iAmHost = tb.host === dapp.me, mySeat = lastSeats.find((s) => s.addr === dapp.me);
  $("gameId").textContent = "#" + activeTable;
  $("shareLink").value = base() + "/?table=" + activeTable;
  drawQR($("shareQR"), $("shareQRNote"), base() + "/?table=" + activeTable, 180);
  $("gPot").textContent = tb.exists ? rawToNado(tb.pot) + " NADO" : (T.ante ? "opening…" : "—");
  $("gAnte").textContent = tb.exists ? rawToNado(tb.ante) + " NADO" : (T.ante ? rawToNado(T.ante) + " NADO" : "—");
  let phaseTxt = dapp.whereIs("table", activeTable, T.ts);
  if (tb.exists) {
    if (tb.closed) phaseTxt = "table closed — settled";
    else if (tb.joinOpen) phaseTxt = "🟢 joining open — closes in " + (tb.joinEndsIn != null ? blocksToTime(tb.joinEndsIn) : "…") + " · " + tb.seatCount + " player" + (tb.seatCount === 1 ? "" : "s");
    else if (tb.rolled) phaseTxt = "🎲 rolled — " + tb.resolvedCount + "/" + tb.seatCount + " turns resolved";
    else phaseTxt = "🌀 joins closed — the chain is fixing the dice (finalizing)";
  }
  $("gStatus").textContent = phaseTxt;
  $("btnReopen").classList.toggle("hidden", !(!tb.exists && T.ante && T.ts && Date.now() - T.ts > 120000));
  // your turn (auto-played) — the headline
  const feat = $("feature");
  if (mySeat && (mySeat.banked != null)) {
    feat.innerHTML = '<div class="turnhdr">Your turn (chase ' + mySeat.threshold + ') → <b class="' + (mySeat.banked > 0 ? "sc" : "farkle") + '">' + (mySeat.banked > 0 ? mySeat.banked + " banked" : "FARKLE — 0") + "</b></div>"
      + (mySeat.rolls ? '<div class="rolls">' + rollsHTML(mySeat.rolls) + "</div>" : "");
  } else if (mySeat) {
    feat.innerHTML = '<div class="turnhdr">You\'re in (chase ' + mySeat.threshold + ") — the chain rolls your turn " + (mySeat.spinsIn != null ? "in " + blocksToTime(mySeat.spinsIn) : "soon") + ".</div>";
  } else {
    feat.innerHTML = tb.joinOpen ? '<div class="turnhdr dim">Set your greed threshold below and join.</div>' : '<div class="turnhdr dim">…</div>';
  }
  // seats
  $("seats").innerHTML = lastSeats.length ? lastSeats.map((s) => {
    const you = s.addr === dapp.me ? '<b style="color:var(--accent2)">you</b> ' : "";
    const isLead = tb.leader && s.g === tb.leader;
    const res = s.banked != null ? (s.banked > 0 ? '<span class="b ok">' + s.banked + (isLead ? " 👑" : "") + "</span>" : '<span class="b dimb">farkled</span>') : '<span class="b pend">rolling…</span>';
    return '<div class="seat">' + you + disp(s.addr) + ' <span class="dim">chase ' + s.threshold + "</span> " + res + "</div>";
  }).join("") : '<span class="dim">No players yet.</span>';
  // actions
  const wrap = $("myActions"); wrap.innerHTML = "";
  // resolve: any unresolved-but-ready seat can be rolled out (permissionless — do your own first)
  const readyUnresolved = lastSeats.filter((s) => s.ready && !s.resolved);
  if (readyUnresolved.length) {
    const mineReady = readyUnresolved.find((s) => s.addr === dapp.me) || readyUnresolved[0];
    const b = document.createElement("button"); b.className = "primary"; b.style.flex = "1 1 auto";
    b.textContent = "🎲 Roll out " + (mineReady.addr === dapp.me ? "your turn" : "seat #" + mineReady.g) + (mineReady.banked > 0 ? " (" + mineReady.banked + ")" : "");
    b.onclick = () => resolveSeat(mineReady.g); wrap.appendChild(b);
  }
  // settle / reclaim once all resolved
  const allResolved = tb.exists && tb.seatCount > 0 && tb.resolvedCount >= tb.seatCount && !tb.closed;
  $("btnSettle").classList.toggle("hidden", !(allResolved && tb.leader));
  $("btnSettle").textContent = "🏆 Pay the winner — pot " + rawToNado(tb.pot);
  $("btnReclaim").classList.toggle("hidden", !(allResolved && !tb.leader && iAmHost));
}

// ---- boot ----------------------------------------------------------------------------------------
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.table != null) activeTable = pend.table;
  $("status").textContent = statusLabel(pend, ok, err, { resolve: "Rolling out…", settle: "Paying the winner…", reclaim: "Reclaiming…" });
});
async function boot() {
  try { await dapp.init(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload."; return; }
  wireUI(); orderCards(["activeGame","lobby","play","opencard","walletcard","bankroll","scoreboard"]); loadQR(); syncThreshold();
  const q = new URLSearchParams(location.search).get("table");
  if (q) { $("joinId").value = q; if (activeTable == null) activeTable = parseInt(q, 10); }
  render(); refreshActive();
  setInterval(refreshActive, 3000);
}
boot();
