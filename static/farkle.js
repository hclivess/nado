// farkle.js — NADO Farkle: a REAL interactive multiplayer Farkle ("Ten Thousand") on the execution layer.
// You ROLL, SEE your dice, choose which scoring dice to set aside, then BANK or push your luck — a scoreless
// roll FARKLES your turn. No autoplay. Each roll's randomness is pinned to a FUTURE block hash nobody can
// predict, so the dice are objective and unriggable. Highest banked score when the table's play window ends
// takes the whole pot. Built on the shared SDK (nadodapp.js) — matches tests/test_farkle_contract.py exactly.
import { NadoDapp, rawToNado, nadoToRaw, randId, rematchId, blake2bHash, _m, $, base, gate, canPay, orderCards, blocksToTime, lsLoad as load, lsSave as save, wireWallet, stickyInputs, renderWallet, renderScore, scoreBump, scoreSort, shareInvite, alertBar, notify, loadQR, resolveAliases, disp } from "./nadodapp.js";
import { BankedGame } from "./bankedgame.js";
import { faucetAttach } from "./faucet.js";   // airdrop free-play claims for newcomers   // the ONE banked-table reader — farkle overlays its round phases
import { Practice } from "./practice.js";      // free in-browser practice (solo score-attack, no chain)

const CID = "b56dd48000707369be1630e41bfb038d";
const GICON = '<svg style="vertical-align:-3px" viewBox="0 0 48 48" width="16" height="16" aria-hidden="true">     <rect x="5" y="21" width="16" height="16" rx="4" fill="#e6edf3" stroke="#243140" stroke-width="1.6"/>     <circle cx="9.5" cy="25.5" r="1.6" fill="#20272f"/><circle cx="16.5" cy="32.5" r="1.6" fill="#20272f"/><circle cx="13" cy="29" r="1.6" fill="#00ad93"/>     <rect x="27" y="21" width="16" height="16" rx="4" fill="#e3b341" stroke="#8a6209" stroke-width="1.6"/>     <circle cx="31.5" cy="25.5" r="1.6" fill="#3a2a05"/><circle cx="38.5" cy="25.5" r="1.6" fill="#3a2a05"/><circle cx="31.5" cy="32.5" r="1.6" fill="#3a2a05"/><circle cx="38.5" cy="32.5" r="1.6" fill="#3a2a05"/>     <rect x="16" y="6" width="16" height="16" rx="4" fill="#d0362b" stroke="#8a1a12" stroke-width="1.6"/>     <circle cx="24" cy="14" r="1.9" fill="#fff"/></svg>';
const dapp = new NadoDapp({ cid: CID, app: "Farkle" });
const bg = new BankedGame(dapp, { icon: GICON, bankIcon: GICON });   // shared reader for existence + ta/tp/tn/tz; phases overlaid below (both recent-chip roles use the dice mark)
const JOIN = 20, PLAY = 600, GAP = 2, MAXP = 8, TARGET = 4000;   // MUST match the contract
const BASE = { 1: 1000, 2: 200, 3: 300, 4: 400, 5: 500, 6: 600 };

let activeTable = null, lastTable = null, lastSeats = [], lastSto = null;
let keep = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0 };        // client-side "dice set aside this roll"

// ---- dice + scoring (mirror of tests/test_farkle_contract.py) -------------------------------------
const H = (v) => BigInt("0x" + blake2bHash(v));           // vm HASH on a BigInt
function rollDice(seatId, grh, grn, diceLeft, aHex, bHex) {
  if (!aHex || !bHex) return null;
  const seed = BigInt("0x" + aHex) + BigInt("0x" + bHex) + BigInt(seatId) * 1000n + BigInt(grn) * 10n;
  const out = [];
  for (let p = 0; p < diceLeft; p++) out.push(Number(H(seed + BigInt(p)) % 6n) + 1);
  return out;
}
const countsOf = (dice) => { const c = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0 }; for (const d of dice) c[d]++; return c; };
// greedy MAX score of a whole roll — 0 means FARKLE (no scoring dice at all)
function greedyScore(dice) {
  const c = countsOf(dice);
  if (dice.length === 6 && [1, 2, 3, 4, 5, 6].every((f) => c[f] === 1)) return 1500;
  let s = 0;
  for (let f = 1; f <= 6; f++) { const k = c[f];
    if (k >= 3) s += BASE[f] * (2 ** (k - 3));
    else if (f === 1) s += k * 100;
    else if (f === 5) s += k * 50;
  }
  return s;
}
// score + validity of a chosen keep (per-face counts) against the rolled counts
function keepScoreValid(keepC, rolled, diceLeft) {
  const straight = diceLeft === 6 && [1,2,3,4,5,6].every((f) => rolled[f] === 1) && [1,2,3,4,5,6].every((f) => keepC[f] === 1);
  let s = 0;
  for (let f = 1; f <= 6; f++) { const k = keepC[f];
    if (k >= 3) s += BASE[f] * (2 ** (k - 3));
    else if (f === 1) s += k * 100;
    else if (f === 5) s += k * 50;
  }
  s = straight ? 1500 : s;
  let ok = [1,2,3,4,5,6].every((f) => keepC[f] <= rolled[f]);
  ok = ok && [2,3,4,6].every((f) => keepC[f] === 0 || keepC[f] >= 3);
  const sum = [1,2,3,4,5,6].reduce((a, f) => a + keepC[f], 0);
  ok = ok && sum >= 1 && s > 0;
  return { score: s, valid: ok, kept: sum };
}

// ---- reads ---------------------------------------------------------------------------------------
function tableFrom(sto, t) {
  const base = bg.read(sto, t);                    // ONE reader: existence (ta), pot (tp), seatCount (tn), closed (tz)
  if (!base.exists) return { exists: false };
  t = String(t); const t0 = _m(sto, "t0")[t];
  const tb = { exists: true, id: base.id, host: base.bank, t0, ante: _m(sto, "ts")[t] || 0, pot: base.pool,
    seatCount: base.seatCount, finishedCount: base.settledCount,
    best: _m(sto, "tw")[t] || 0, leader: _m(sto, "tb")[t] || 0, closed: base.closed,
    finalRound: !!_m(sto, "tfr")[t] };
  const cur = dapp.cursor;
  if (cur != null) {
    if (cur < t0 + JOIN) { tb.phase = "join"; tb.left = t0 + JOIN - cur; }
    else if (cur < t0 + JOIN + PLAY) { tb.phase = "play"; tb.left = t0 + JOIN + PLAY - cur; }
    else tb.phase = "over";
    if (tb.closed) tb.phase = "done";
  }
  return tb;
}
// NOT bg.seats: farkle seats live in the ti[t*16+i] turn-order index (not a gg walk), carry per-ROLL state
// (gts/ggs/gdl/grh/grn — gh rebinds every roll) with gfin/gsc instead of gd, and sort by seat idx ASC.
function seatsOfTable(sto, t) {
  t = String(t); const tn = _m(sto, "tn")[t] || 0, out = [];
  for (let i = 0; i < tn; i++) {
    const g = _m(sto, "ti")[String(Number(t) * 16 + i)];
    if (!g) continue;
    const s = { g: Number(g), idx: i, addr: _m(sto, "ga")[g], turnScore: _m(sto, "gts")[g] || 0,
      grand: _m(sto, "ggs")[g] || 0,
      diceLeft: _m(sto, "gdl")[g] || 0, rollHeight: _m(sto, "grh")[g] || 0, rollNonce: _m(sto, "grn")[g] || 0,
      finished: !!_m(sto, "gfin")[g], final: _m(sto, "gsc")[g] || 0 };
    out.push(s);
  }
  return out.sort((a, b) => a.idx - b.idx);
}
async function fetchTable(t) { const sto = await dapp.storage(); return sto ? tableFrom(sto, t) : null; }
const mySeat = () => lastSeats.find((s) => s.addr === dapp.me);

// ---- actions -------------------------------------------------------------------------------------
// NOT bg.open: farkle's open signs open(t, g) — the host ALSO takes a seat and antes — and the table record
// keeps the ANTE (per-player buy-in), not a bankroll. bg.open signs open(t) alone and records { bankroll }.
function openTable(t, g, anteRaw) {
  const T = load(bg.LS_T);
  T[t] = { ante: anteRaw.toString(), ts: Date.now() }; save(bg.LS_T, T);
  bg.rememberSeat(g, { table: t });
  activeTable = t; render();
  dapp.call("open", [t, g], anteRaw, window.t("farkle.callOpen", "open a Farkle table #{t} · ante {a} NADO", { t, a: rawToNado(anteRaw) }), { table: t, seat: g, phase: "open" });
}
async function newTable() {
  const raw = nadoToRaw($("anteAmt").value);
  if (!raw) return alertBar(window.t("farkle.enterAnte", "Enter an ante (NADO) — everyone antes into the pot."));
  await dapp.refresh();
  if (!canPay(dapp, raw, "Opening this table")) return;
  openTable(randId(), randId(), raw);
}
async function joinTable() {
  const t = activeTable;
  if (!t) return alertBar(window.t("farkle.pickFirst", "Pick a table first."));
  const tb = await fetchTable(t);
  if (!tb || !tb.exists) return alertBar(dapp.whereIs("table", t));
  if (tb.phase !== "join") return alertBar(window.t("farkle.joinClosed", "The join window for that table has closed."));
  if (lastSeats.some((s) => s.addr === dapp.me)) return alertBar(window.t("farkle.alreadySeated", "You're already seated at this table."));
  await dapp.refresh();
  const ante = BigInt(tb.ante);
  if (!canPay(dapp, ante, "Joining this table")) { render(); return; }
  const g = randId(); bg.rememberSeat(g, { table: t });
  activeTable = t; render();
  dapp.call("join", [t, g], ante, window.t("farkle.callJoin", "join Farkle table #{t} · ante {a} NADO", { t, a: rawToNado(ante) }), { table: t, seat: g, phase: "join" });
}
// NOT bg.reopen: farkle retries with the recorded ANTE via its own open(t, g) (or falls back to a join);
// bg.reopen would re-sign open(t) with a bankroll — a different call for a different table shape.
function reopenTable() {   // retry an open/join that didn't confirm (same ante, fresh attempt)
  const T = bg.tableRec(activeTable);
  if (T && T.ante) { const raw = BigInt(T.ante); if (!canPay(dapp, raw, "Re-opening this table")) return; openTable(activeTable, randId(), raw); return; }
  // otherwise retry joining
  joinTable();
}
async function rematch() {
  const tb = lastTable || {}, T = bg.tableRec(activeTable) || {};
  const ante = tb.exists ? BigInt(tb.ante) : (T.ante ? BigInt(T.ante) : null);
  if (!ante) return alertBar(window.t("farkle.openFromPanel", "Open a new table from the panel above."));
  await dapp.refresh();
  if (!canPay(dapp, ante, "The rematch")) return;
  const rtid = rematchId(activeTable), rt = await fetchTable(rtid);
  if (rt && rt.exists && rt.phase === "join") {   // someone already opened the rematch -> take a seat instead of colliding
    activeTable = rtid; $("joinId").value = String(rtid); render();
    const g = randId(); bg.rememberSeat(g, { table: rtid });
    dapp.call("join", [rtid, g], ante, window.t("farkle.callJoin", "join Farkle table #{t} · ante {a} NADO", { t: rtid, a: rawToNado(ante) }), { table: rtid, seat: g, phase: "join" });
    return;
  }
  openTable(rtid, randId(), ante);
}
const doRoll = (g) => { keep = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0 }; dapp.call("roll", [g], null, window.t("farkle.callRoll", "roll the dice · Farkle #{t}", { t: activeTable }), { table: activeTable, seat: g, phase: "roll" }); };
function doHold(g, cont) {
  dapp.call("hold", [g, keep[1] | keep[2]<<3 | keep[3]<<6 | keep[4]<<9 | keep[5]<<12 | keep[6]<<15, cont], null,
    window.t(cont ? "farkle.callHoldRoll" : "farkle.callHoldBank", cont ? "set aside + roll again" : "bank the turn") + " · Farkle #" + activeTable, { table: activeTable, seat: g, phase: "hold" });
}
const settleTable = () => dapp.call("settle", [activeTable], null, window.t("farkle.callSettle", "pay the winner · table #{t}", { t: activeTable }), { table: activeTable, phase: "settle" });
const reclaimTable = () => dapp.call("reclaim", [activeTable], null, window.t("farkle.callReclaim", "reclaim the pot · table #{t}", { t: activeTable }), { table: activeTable, phase: "reclaim" });
const cancelTable = () => dapp.call("cancel", [activeTable], null, window.t("farkle.callCancel", "cancel table #{t}", { t: activeTable }), { table: activeTable, phase: "cancel" });
const timeoutSeat = (g) => dapp.call("timeout", [g], null, window.t("farkle.callTimeout", "time out seat #{g}", { g }), { table: activeTable, phase: "timeout" });

async function refreshActive() {
  await dapp.refresh();
  dapp.settleInflight();   // SDK: retire the optimistic 'confirming…' status once the action lands
  const sto = await dapp.storage();
  if (sto) {
    lastSto = sto; bg.track(sto);
    if (activeTable != null) {
      lastTable = tableFrom(sto, activeTable);
      lastSeats = seatsOfTable(sto, activeTable);
      const cur = dapp.cursor, need = [];
      for (const s of lastSeats) if (s.rollHeight && cur != null && cur >= s.rollHeight + 1) need.push(s.rollHeight, s.rollHeight + 1);
      if (need.length) await dapp.blockHashes(need, { fast: true });   // Farkle dice: PUBLIC + on-chain-validated -> provisional (fast) is safe (a reorg just reverts a hold)
    }
    renderLobby(sto); renderScoreboard(boardFrom(sto));
  }
  await resolveAliases([dapp.me].concat(lastSeats.map((s) => s.addr)));
  render();
}
function boardFrom(sto) {
  const stats = {};
  // index seats by table in ONE pass — avoids re-scanning the whole seat map per table (O(tables × seats),
  // unbounded with total game history; now O(seats + tables)).
  const gg = _m(sto, "gg"), seatsByTable = {};
  for (const g of Object.keys(gg)) { const t = String(gg[g]); (seatsByTable[t] || (seatsByTable[t] = [])).push(g); }
  for (const t of Object.keys(_m(sto, "ta"))) {
    if (!_m(sto, "tz")[t]) continue;
    const lead = _m(sto, "tb")[t]; if (!lead) continue;
    const seats = seatsByTable[String(t)] || [];
    const ante = _m(sto, "ts")[t] || 0, pot = ante * seats.length;
    for (const g of seats) scoreBump(stats, _m(sto, "ga")[g], Number(g) === lead ? pot - ante : -ante);
  }
  return scoreSort(stats);
}
const renderScoreboard = (board) => renderScore($("scoreList"), board, dapp.me, window.t("farkle.noTablesBoard", "No finished tables yet — be the first on the board."), true);
// NOT bg.lobby: farkle chips need the t0 phase windows (join/play/over via tableFrom, which bg.read lacks),
// sort join-phase tables first, and only join-phase chips get the "betting" class (bg.lobby styles them all).
function renderLobby(sto) {
  const el = $("lobbyList"); if (!el) return;
  const tables = Object.keys(_m(sto, "ta")).map((t) => tableFrom(sto, t)).filter((t) => t.exists && !t.closed);
  tables.sort((a, b) => (b.phase === "join") - (a.phase === "join") || b.id - a.id);
  el.innerHTML = tables.length ? tables.slice(0, 24).map((t) => {
    const tag = t.phase === "join" ? "🟢" : t.phase === "play" ? "🎲" : "🏁";
    const info = t.phase === "join" ? window.t("farkle.joinsClose", " · joins close {time}", { time: blocksToTime(t.left) }) : t.phase === "play" ? window.t("farkle.inPlay", " · in play") : "";
    return '<button class="chip ' + (t.phase === "join" ? "betting" : "") + '" data-t="' + t.id + '">' + tag + " #" + t.id
      + " · " + window.t("farkle.potLabel", "pot {p}", { p: rawToNado(t.pot) }) + " · "
      + window.t(t.seatCount === 1 ? "farkle.player1" : "farkle.playerN", t.seatCount === 1 ? "{n} player" : "{n} players", { n: t.seatCount }) + info + "</button>";
  }).join(" ") : '<span class="dim">' + window.t("farkle.noTablesLobby", "No tables yet — open one below.") + '</span>';
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => selectTable(parseInt(b.dataset.t, 10)));
}
function selectTable(id) {
  activeTable = id; $("joinId").value = String(id);
  notify(window.t("farkle.tableSelected", "Table #{id} selected.", { id }));
  refreshActive();
  try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {}
}

// ---- dice rendering + selection ------------------------------------------------------------------
// SVG dice — a rounded face with the standard pip layout per value; .kept re-styles it (see farkle.html)
const PIP_POS = { 1: [[50,50]], 2: [[30,30],[70,70]], 3: [[30,30],[50,50],[70,70]],
  4: [[30,30],[70,30],[30,70],[70,70]], 5: [[30,30],[70,30],[50,50],[30,70],[70,70]],
  6: [[30,30],[70,30],[30,50],[70,50],[30,70],[70,70]] };
const dieSVG = (f) => '<svg class="dieface" viewBox="0 0 100 100" aria-hidden="true"><rect x="6" y="6" width="88" height="88" rx="20"/>'
  + PIP_POS[f].map(([x,y]) => '<circle cx="' + x + '" cy="' + y + '" r="9"/>').join("") + "</svg>";
function myRoll(s) {
  if (!s || !s.rollHeight) return null;
  if (dapp.cursor == null || dapp.cursor < s.rollHeight + 1) return { pending: true, spinsIn: s.rollHeight + 1 - (dapp.cursor || 0) };
  const dice = rollDice(s.g, s.rollHeight, s.rollNonce, s.diceLeft, dapp.bh(s.rollHeight), dapp.bh(s.rollHeight + 1));
  if (!dice) return { pending: true };
  return { dice };
}
function toggleKeep(face, dice) {
  const rolled = countsOf(dice);
  if (face === 1 || face === 5) { keep[face] = keep[face] >= rolled[face] ? 0 : keep[face] + 1; }
  else { keep[face] = keep[face] >= rolled[face] ? 0 : (keep[face] < 3 ? 3 : keep[face] + 1); if (keep[face] > rolled[face]) keep[face] = 0; }
  render();
}

// ---- render --------------------------------------------------------------------------------------
function wireUI() {
  wireWallet(dapp);
  stickyInputs(dapp, ['stakeAmt', 'anteAmt', 'bankAmt']);   // typed amounts persist across turns
  $("btnNewTable").onclick = newTable;
  $("btnJoin").onclick = joinTable;
  if ($("btnReopen")) $("btnReopen").onclick = reopenTable;
  if ($("btnRematch")) $("btnRematch").onclick = rematch;
  $("btnGoTable").onclick = () => { const id = parseInt($("joinId").value, 10); if (id) selectTable(id); else alertBar(window.t("farkle.enterTableId", "Enter a table ID, or pick one from the lobby.")); };
  $("btnSettle").onclick = settleTable;
  $("btnReclaim").onclick = reclaimTable;
  $("btnCancel").onclick = cancelTable;
}
function render() {
  const signedIn = renderWallet(dapp);
  gate({ play: signedIn, opencard: signedIn, bankroll: signedIn, activeGame: activeTable != null });
  bg.recent($("recent"), selectTable, (x) => {
    if (!lastSto) return;
    const tb = tableFrom(lastSto, x.id);
    if (tb.exists) return tb.closed ? "finished ✓" : tb.phase === "join" ? "joining" : tb.phase === "play" ? "in play" : "settle!";
  });
  renderActive();
}
function renderActive() {
  if (activeTable == null) return;
  const tb = lastTable || {}, T = bg.tableRec(activeTable) || {}, me = mySeat(), iAmHost = tb.host === dapp.me;
  $("gameId").textContent = "#" + activeTable;
  shareInvite("table", activeTable, window.t("farkle.shareMsg", "Join my Farkle table #{t} on NADO:", { t: activeTable }), 180);
  $("gPot").textContent = tb.exists ? rawToNado(tb.pot) + " NADO" : "—";
  $("gAnte").textContent = tb.exists ? rawToNado(tb.ante) + " NADO" : "—";

  let phaseTxt = dapp.whereIs("table", activeTable, T.ts);
  if (tb.exists) {
    if (tb.closed) phaseTxt = window.t("farkle.tableSettled", "table settled ✓");
    else if (tb.phase === "join") phaseTxt = window.t(tb.seatCount === 1 ? "farkle.joiningOpen1" : "farkle.joiningOpenN",
      tb.seatCount === 1 ? "🟢 joining open — closes in {time} · {n} player" : "🟢 joining open — closes in {time} · {n} players", { time: blocksToTime(tb.left), n: tb.seatCount });
    else if (tb.phase === "play") phaseTxt = (tb.finalRound ? window.t("farkle.finalRoundPre", "🏁 FINAL ROUND — last turns! ") : window.t("farkle.inPlayPre", "🎲 in play — "))
      + window.t("farkle.raceTo", "race to {target}", { target: TARGET })
      + (tb.best ? window.t("farkle.leaderPart", " · leader {best}", { best: tb.best }) : "")
      + window.t("farkle.outPart", " · {done}/{total} out", { done: tb.finishedCount, total: tb.seatCount });
    else phaseTxt = window.t("farkle.windowClosed", "🏁 play window closed — settle below");
  }
  $("gStatus").textContent = phaseTxt;
  // the ONE join affordance: only shown when you can actually take a seat (open window, not already in)
  const joinable = tb.exists && tb.phase === "join" && dapp.me && !me;
  if ($("btnJoin")) { $("btnJoin").classList.toggle("hidden", !joinable); $("btnJoin").textContent = window.t("farkle.sitDown", "🪑 Sit down — ante {a} NADO", { a: tb.exists ? rawToNado(tb.ante) : "?" }); }
  // reopen: your open/join didn't confirm within ~2 min
  const stalled = !tb.exists && T.ts && Date.now() - T.ts > 120000;
  if ($("btnReopen")) $("btnReopen").classList.toggle("hidden", !stalled);

  const feat = $("feature"), acts = $("myActions"); acts.innerHTML = "";
  const btn = (txt, fn, primary) => { const b = document.createElement("button"); b.className = primary ? "primary" : "ghost"; b.style.flex = "1 1 auto"; b.innerHTML = txt; b.onclick = fn; acts.appendChild(b); return b; };
  if (me && tb.exists && !tb.closed && tb.phase === "play") {
    // grand-total header + target progress, shown above every in-turn state
    const grandHdr = '<div class="turnhdr">' + window.t("farkle.grandTotal", "Your grand total") + ' <b class="sc">' + me.grand + '</b> / ' + TARGET
      + (tb.best ? ' · ' + window.t("farkle.leaderLabel", "leader") + ' <b>' + tb.best + '</b>' : '') + '</div>'
      + (tb.finalRound ? '<div class="farkle mt">' + window.t("farkle.finalRoundTurn", "🏁 FINAL ROUND — this is your LAST turn. Bank it or bust, then you're locked.") + '</div>'
                       : '<div class="dim small mt">' + window.t("farkle.firstToTriggers", "First to {target} triggers the final round; highest grand total takes the pot.", { target: TARGET }) + '</div>');
    if (me.finished) {
      feat.innerHTML = '<div class="turnhdr">' + window.t("farkle.runDone", "Your run is done —") + ' <b class="sc">' + window.t("farkle.bankedAmt", "{n} banked", { n: me.final }) + '</b>'
        + (tb.leader === me.g ? ' ' + window.t("farkle.youLead", "👑 you lead!") : '') + '. ' + window.t("farkle.waitingOthers", "Waiting for the others…") + '</div>';
    } else {
      const r = myRoll(me);
      if (!me.rollHeight) {
        feat.innerHTML = grandHdr
          + '<div class="turnhdr mt">' + window.t("farkle.thisTurnLabel", "This turn:") + ' <b class="sc">' + me.turnScore + '</b> · <b>' + me.diceLeft + '</b> ' + window.t("farkle.diceInHand", "dice in hand") + '</div>'
          + '<div class="dim small mt">' + window.t("farkle.rollHelp", "Roll, set aside the scoring dice, then bank into your grand total or push on.") + '</div>';
        btn(window.t("farkle.rollDiceBtn", "🎲 Roll {n} dice", { n: me.diceLeft }), () => doRoll(me.g), true);
      } else if (r && r.pending) {
        feat.innerHTML = grandHdr + '<div class="turnhdr mt">' + window.t("farkle.rollingLock", "🎲 Rolling… the dice lock when the block finalizes") + (r.spinsIn ? " (~" + blocksToTime(r.spinsIn) + ")" : "") + ".</div>";
      } else if (r && r.dice) {
        const dice = r.dice, rolled = countsOf(dice), farkle = greedyScore(dice) === 0;
        const ks = keepScoreValid(keep, rolled, me.diceLeft);
        const keptLeft = Object.assign({}, keep);
        const diceHtml = dice.map((d) => { const setAside = keptLeft[d] > 0; if (setAside) keptLeft[d]--;
          return '<span class="die ' + (setAside ? "kept" : "") + '" data-f="' + d + '">' + dieSVG(d) + "</span>"; }).join("");
        const bankTo = me.grand + me.turnScore + ks.score, crosses = !tb.finalRound && bankTo >= TARGET;
        feat.innerHTML = grandHdr + '<div class="turnhdr mt">' + window.t("farkle.thisTurnSoFar", "This turn so far") + ' <b class="sc">' + me.turnScore + '</b> · ' + window.t("farkle.thisRollLabel", "this roll:") + '</div>'
          + '<div class="dicerow">' + diceHtml + "</div>"
          + (farkle ? '<div class="farkle mt">' + window.t("farkle.farkleMsg", "💥 FARKLE — no scoring dice. This turn ends at 0 (grand total {grand} stays).", { grand: me.grand }) + '</div>'
              : '<div class="mt small">' + window.t("farkle.setAsideLabel", "Set aside:") + ' <b class="sc">' + ks.score + '</b> ' + window.t(ks.score === 1 ? "farkle.pt" : "farkle.pts", ks.score === 1 ? "pt" : "pts")
                + (ks.kept ? "" : ' <span class="dim">' + window.t("farkle.tapScoring", "(tap scoring dice — 1s & 5s, or three+ of a kind)") + '</span>') + "</div>");
        feat.querySelectorAll(".die").forEach((el) => el.onclick = () => toggleKeep(parseInt(el.dataset.f, 10), dice));
        if (farkle) {
          btn(window.t("farkle.endTurnFarkled", "💥 End turn (farkled)"), () => { keep = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0 }; doHold(me.g, 0); }, true);
        } else {
          const canAct = ks.valid;
          btn(window.t("farkle.bankTo", "💰 Bank to {n}", { n: bankTo }) + (crosses ? window.t("farkle.hitsTarget", " 🏁 (hits {target}!)", { target: TARGET }) : ""), () => doHold(me.g, 0), canAct).disabled = !canAct;
          btn(window.t("farkle.setAsideRollOn", "🎲 Set aside & roll on"), () => doHold(me.g, 1), false).disabled = !canAct;
        }
      }
    }
  } else if (me && tb.phase === "join") {
    feat.innerHTML = '<div class="turnhdr dim">' + window.t("farkle.seatedWait", "You're seated — the table starts when joining closes.") + '</div>';
  } else if (tb.phase === "join") {
    feat.innerHTML = '<div class="turnhdr dim">' + window.t("farkle.anteToSeat", "Ante to take a seat, then it's roll / bank / bust — real Farkle.") + '</div>';
  } else {
    feat.innerHTML = "";
  }
  // the green felt is only shown when it actually holds content (no empty bar before/after play)
  if ($("felt")) $("felt").classList.toggle("hidden", !feat.innerHTML.trim());

  $("seats").innerHTML = lastSeats.length ? lastSeats.map((s) => {
    const you = s.addr === dapp.me ? '<b style="color:var(--accent2)">' + window.t("farkle.you", "you") + '</b> ' : "";
    const lead = tb.leader === s.g;
    let tag;
    if (s.finished) tag = s.final > 0 ? '<span class="b ok">' + s.final + (lead ? " 👑" : "") + window.t("farkle.dotOut", " · out") + '</span>' : '<span class="b dimb">' + window.t("farkle.outZero", "out · 0") + '</span>';
    else if (s.rollHeight) tag = '<span class="b ok">' + s.grand + '</span> <span class="b pend">' + window.t("farkle.rolling", "rolling…") + '</span>';
    else tag = '<span class="b ok">' + s.grand + (lead ? " 👑" : "") + '</span>' + (s.turnScore ? ' <span class="b pend">' + window.t("farkle.turnTag", "+{n} turn", { n: s.turnScore }) + "</span>" : "");
    return '<div class="seat">' + you + disp(s.addr) + " " + tag + "</div>";
  }).join("") : '<span class="dim">' + window.t("farkle.noPlayers", "No players yet.") + '</span>';

  const allDone = tb.exists && tb.seatCount > 0 && tb.finishedCount >= tb.seatCount && !tb.closed;
  if (tb.phase === "over" && !tb.closed) for (const s of lastSeats) if (!s.finished) { btn(window.t("farkle.finalizeSeat", "⏱ Finalize seat #{g}", { g: s.g }), () => timeoutSeat(s.g), false); break; }
  $("btnSettle").classList.toggle("hidden", !(allDone && tb.leader));
  $("btnSettle").textContent = window.t("farkle.paySettleBtn", "🏆 Pay the winner — pot {pot}", { pot: rawToNado(tb.pot || 0) });
  $("btnReclaim").classList.toggle("hidden", !(allDone && !tb.leader && iAmHost));
  $("btnCancel").classList.toggle("hidden", !(tb.exists && !tb.closed && tb.seatCount === 1 && iAmHost));
  // once the pot is paid, offer a one-tap rematch — everyone who was here derives the same fresh table id
  if ($("btnRematch")) $("btnRematch").classList.toggle("hidden", !(tb.exists && tb.closed && dapp.me && (me || iAmHost)));
}

// ---- boot ----------------------------------------------------------------------------------------
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.table != null) activeTable = pend.table;
  dapp.showReturn(pend, ok, err, { roll: window.t("farkle.stRoll", "Rolling…"), hold: window.t("farkle.stHold", "Confirming your move…"), settle: window.t("farkle.stSettle", "Paying the winner…"), reclaim: window.t("farkle.stReclaim", "Reclaiming…"), timeout: window.t("farkle.stTimeout", "Finalizing…") });
});
async function boot() {
  try { await dapp.init(); } catch (e) { alertBar(window.t("farkle.cryptoFail", "Crypto bundle failed to load — reload.")); return; }
  wireUI(); loadQR(); orderCards(["activeGame", "lobby", "play", "practice", "opencard", "walletcard", "bankroll", "scoreboard"]);
  const q = new URLSearchParams(location.search).get("table");
  if (q) { $("joinId").value = q; if (activeTable == null) activeTable = parseInt(q, 10); }
  render(); refreshActive();
  setInterval(refreshActive, 3000);
}
boot();

// ---- PRACTICE MODE (free, fully in-browser — solo score-attack, local dice, nothing on-chain) ----------
// 10 turns of push-your-luck scored by the EXACT rules the contract enforces (the same countsOf /
// greedyScore / keepScoreValid above validate every keep — straights, hot dice and all; see
// execnode/games/farkle.py). Math.random is fine here because nothing is at stake.
const prac = new Practice("farkle");
const P_TURNS = 10;
const P_KEEP0 = () => ({ 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0 });
let pr = null;
function pNewRun() { pr = { turn: 1, total: 0, turnScore: 0, diceLeft: 6, dice: null, keep: P_KEEP0(), over: false, isBest: false }; pracRender(); }
function pRoll() {
  pr.keep = P_KEEP0();
  pr.dice = Array.from({ length: pr.diceLeft }, () => 1 + Math.floor(Math.random() * 6));
  pracRender();
}
function pNextTurn(banked) {
  pr.total += banked;
  pr.turn++; pr.turnScore = 0; pr.diceLeft = 6; pr.dice = null; pr.keep = P_KEEP0();
  if (pr.turn > P_TURNS) { pr.over = true; pr.isBest = prac.bump("best", pr.total); }
  pracRender();
}
function pKeepRoll() {   // set aside & roll on — mirror of hold(cont=1) incl. HOT DICE (nd==0 → 6 fresh dice)
  const ks = keepScoreValid(pr.keep, countsOf(pr.dice), pr.diceLeft);
  if (!ks.valid) return;
  pr.turnScore += ks.score;
  const nd = pr.diceLeft - ks.kept;
  pr.diceLeft = nd === 0 ? 6 : nd;
  pRoll();
}
function pBank() {   // mirror of hold(cont=0): the turn score + this keep bank into the grand total
  const ks = keepScoreValid(pr.keep, countsOf(pr.dice), pr.diceLeft);
  if (!ks.valid) return;
  pNextTurn(pr.turnScore + ks.score);
}
function pToggle(face) {   // same keep semantics as toggleKeep (1s/5s singly, other faces jump to 3-of-a-kind)
  const rolled = countsOf(pr.dice), k = pr.keep;
  if (face === 1 || face === 5) { k[face] = k[face] >= rolled[face] ? 0 : k[face] + 1; }
  else { k[face] = k[face] >= rolled[face] ? 0 : (k[face] < 3 ? 3 : k[face] + 1); if (k[face] > rolled[face]) k[face] = 0; }
  pracRender();
}
function pracRender() {
  prac.strip($("pStrip"), { chips: false });
  const feat = $("pFeature"), acts = $("pActions"); if (!feat) return;
  acts.innerHTML = "";
  const mk = (txt, fn, primary) => { const b = document.createElement("button"); b.className = primary ? "primary" : "ghost"; b.style.flex = "1 1 auto"; b.innerHTML = txt; b.onclick = fn; acts.appendChild(b); return b; };
  const bb = prac.best("best");
  $("pBest").textContent = bb ? window.t("sdk.prBest", "Personal best: {n}", { n: bb }) : "";
  if (!pr || pr.over) {
    feat.innerHTML = pr && pr.over
      ? '<div class="turnhdr">' + window.t("sdk.prFinal", "🏁 Run over — final score {n}", { n: pr.total }) + (pr.isBest ? ' <span class="sc">' + window.t("sdk.prNewBest", "🏆 New personal best!") + "</span>" : "") + "</div>"
      : '<div class="turnhdr dim">' + window.t("sdk.prSoloHelp", "Solo score-attack: 10 turns of roll / set aside / bank — a farkle ends the turn at 0.") + "</div>";
    mk(pr ? "↻ " + window.t("sdk.prNewGame", "New practice game") : "🎲 " + window.t("sdk.prPlay", "Play"), pNewRun, true);
    return;
  }
  const hdr = '<div class="turnhdr">' + window.t("sdk.prTurn", "Turn {n} of {total}", { n: pr.turn, total: P_TURNS }) + " · " + window.t("farkle.grandTotal", "Your grand total") + ' <b class="sc">' + pr.total + "</b></div>";
  if (!pr.dice) {
    feat.innerHTML = hdr + '<div class="turnhdr mt">' + window.t("farkle.thisTurnLabel", "This turn:") + ' <b class="sc">' + pr.turnScore + "</b> · <b>" + pr.diceLeft + "</b> " + window.t("farkle.diceInHand", "dice in hand") + "</div>";
    mk(window.t("farkle.rollDiceBtn", "🎲 Roll {n} dice", { n: pr.diceLeft }), pRoll, true);
    return;
  }
  const rolled = countsOf(pr.dice), farkled = greedyScore(pr.dice) === 0;
  const ks = keepScoreValid(pr.keep, rolled, pr.diceLeft);
  const keptLeft = Object.assign({}, pr.keep);
  const diceHtml = pr.dice.map((d) => { const aside = keptLeft[d] > 0; if (aside) keptLeft[d]--;
    return '<span class="die ' + (aside ? "kept" : "") + '" data-pf="' + d + '">' + dieSVG(d) + "</span>"; }).join("");
  feat.innerHTML = hdr + '<div class="turnhdr mt">' + window.t("farkle.thisTurnSoFar", "This turn so far") + ' <b class="sc">' + pr.turnScore + "</b> · " + window.t("farkle.thisRollLabel", "this roll:") + "</div>"
    + '<div class="dicerow">' + diceHtml + "</div>"
    + (farkled ? '<div class="farkle mt">' + window.t("farkle.farkleMsg", "💥 FARKLE — no scoring dice. This turn ends at 0 (grand total {grand} stays).", { grand: pr.total }) + "</div>"
        : '<div class="mt small">' + window.t("farkle.setAsideLabel", "Set aside:") + ' <b class="sc">' + ks.score + "</b> " + window.t(ks.score === 1 ? "farkle.pt" : "farkle.pts", ks.score === 1 ? "pt" : "pts")
          + (ks.kept ? "" : ' <span class="dim">' + window.t("farkle.tapScoring", "(tap scoring dice — 1s & 5s, or three+ of a kind)") + "</span>") + "</div>");
  feat.querySelectorAll(".die").forEach((el) => el.onclick = () => pToggle(parseInt(el.dataset.pf, 10)));
  if (farkled) mk(window.t("farkle.endTurnFarkled", "💥 End turn (farkled)"), () => pNextTurn(0), true);
  else {
    mk(window.t("farkle.bankTo", "💰 Bank to {n}", { n: pr.total + pr.turnScore + ks.score }), pBank, true).disabled = !ks.valid;
    mk(window.t("farkle.setAsideRollOn", "🎲 Set aside & roll on"), pKeepRoll, false).disabled = !ks.valid;
  }
}
if ($("pStrip")) pracRender();
faucetAttach(dapp, "farkle");
