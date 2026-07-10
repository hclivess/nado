// farkle.js — NADO Farkle: a REAL interactive multiplayer Farkle ("Ten Thousand") on the execution layer.
// You ROLL, SEE your dice, choose which scoring dice to set aside, then BANK or push your luck — a scoreless
// roll FARKLES your turn. No autoplay. Each roll's randomness is pinned to a FUTURE block hash nobody can
// predict, so the dice are objective and unriggable. Highest banked score when the table's play window ends
// takes the whole pot. Built on the shared SDK (nadodapp.js) — matches tests/test_farkle_contract.py exactly.
import { NadoDapp, rawToNado, nadoToRaw, randId, blake2bHash, _m, $, base, gate, canPay, hoist, orderCards,
         blocksToTime, lsLoad as load, lsSave as save, lsPrune, wireWallet, renderWallet, renderScore,
         scoreBump, scoreSort, recentChips, statusLabel, shareInvite,
         loadQR, drawQR, resolveAliases, disp, share } from "./nadodapp.js";

const CID = "05ea18398f08373343f49a4f51daf78c";
const GICON = '<svg style="vertical-align:-3px" viewBox="0 0 48 48" width="16" height="16" aria-hidden="true">     <rect x="5" y="21" width="16" height="16" rx="4" fill="#e6edf3" stroke="#243140" stroke-width="1.6"/>     <circle cx="9.5" cy="25.5" r="1.6" fill="#20272f"/><circle cx="16.5" cy="32.5" r="1.6" fill="#20272f"/><circle cx="13" cy="29" r="1.6" fill="#00ad93"/>     <rect x="27" y="21" width="16" height="16" rx="4" fill="#e3b341" stroke="#8a6209" stroke-width="1.6"/>     <circle cx="31.5" cy="25.5" r="1.6" fill="#3a2a05"/><circle cx="38.5" cy="25.5" r="1.6" fill="#3a2a05"/><circle cx="31.5" cy="32.5" r="1.6" fill="#3a2a05"/><circle cx="38.5" cy="32.5" r="1.6" fill="#3a2a05"/>     <rect x="16" y="6" width="16" height="16" rx="4" fill="#d0362b" stroke="#8a1a12" stroke-width="1.6"/>     <circle cx="24" cy="14" r="1.9" fill="#fff"/></svg>';
const dapp = new NadoDapp({ cid: CID, app: "Farkle" });
const JOIN = 20, PLAY = 600, GAP = 2, MAXP = 8;           // MUST match the contract
const BASE = { 1: 1000, 2: 200, 3: 300, 4: 400, 5: 500, 6: 600 };

const LS_T = "nado_farkle_tables", LS_S = "nado_farkle_seats";
let activeTable = null, lastTable = null, lastSeats = [], lastSto = null;
let knownTables = new Set(), knownSeats = new Set();
let keep = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0 };        // client-side "dice set aside this roll"

function pruneAndTrack(sto) {
  knownTables = lsPrune(LS_T, Object.keys(_m(sto, "ta")));
  knownSeats = lsPrune(LS_S, Object.keys(_m(sto, "gg")));
}

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
  t = String(t); const host = _m(sto, "ta")[t], t0 = _m(sto, "t0")[t];
  if (!host || t0 == null) return { exists: false };
  const tb = { exists: true, id: Number(t), host, t0, ante: _m(sto, "ts")[t] || 0, pot: _m(sto, "tp")[t] || 0,
    seatCount: _m(sto, "tn")[t] || 0, finishedCount: _m(sto, "tx")[t] || 0,
    best: _m(sto, "tw")[t] || 0, leader: _m(sto, "tb")[t] || 0, closed: !!_m(sto, "tz")[t] };
  const cur = dapp.cursor;
  if (cur != null) {
    if (cur < t0 + JOIN) { tb.phase = "join"; tb.left = t0 + JOIN - cur; }
    else if (cur < t0 + JOIN + PLAY) { tb.phase = "play"; tb.left = t0 + JOIN + PLAY - cur; }
    else tb.phase = "over";
    if (tb.closed) tb.phase = "done";
  }
  return tb;
}
function seatsOfTable(sto, t) {
  t = String(t); const tn = _m(sto, "tn")[t] || 0, out = [];
  for (let i = 0; i < tn; i++) {
    const g = _m(sto, "ti")[String(Number(t) * 16 + i)];
    if (!g) continue;
    const s = { g: Number(g), idx: i, addr: _m(sto, "ga")[g], turnScore: _m(sto, "gts")[g] || 0,
      diceLeft: _m(sto, "gdl")[g] || 0, rollHeight: _m(sto, "grh")[g] || 0, rollNonce: _m(sto, "grn")[g] || 0,
      finished: !!_m(sto, "gfin")[g], final: _m(sto, "gsc")[g] || 0 };
    out.push(s);
  }
  return out.sort((a, b) => a.idx - b.idx);
}
async function fetchTable(t) { const sto = await dapp.storage(); return sto ? tableFrom(sto, t) : null; }
const mySeat = () => lastSeats.find((s) => s.addr === dapp.me);

// ---- actions -------------------------------------------------------------------------------------
function openTable(t, g, anteRaw) {
  const T = load(LS_T), S = load(LS_S);
  T[t] = { ante: anteRaw.toString(), ts: Date.now() }; save(LS_T, T);
  S[g] = { table: t, ts: Date.now() }; save(LS_S, S);
  activeTable = t; render();
  dapp.call("open", [t, g], anteRaw, "open a Farkle table #" + t + " · ante " + rawToNado(anteRaw) + " NADO", { table: t, seat: g, phase: "open" });
}
async function newTable() {
  const raw = nadoToRaw($("anteAmt").value);
  if (!raw) { $("status").textContent = "Enter an ante (NADO) — everyone antes into the pot."; return; }
  await dapp.refresh();
  if (!canPay(dapp, raw, "Opening this table")) return;
  openTable(randId(), randId(), raw);
}
async function joinTable() {
  const t = activeTable;
  if (!t) { $("status").textContent = "Pick a table first."; return; }
  const tb = await fetchTable(t);
  if (!tb || !tb.exists) { $("status").textContent = dapp.whereIs("table", t); return; }
  if (tb.phase !== "join") { $("status").textContent = "The join window for that table has closed."; return; }
  if (lastSeats.some((s) => s.addr === dapp.me)) { $("status").textContent = "You're already seated at this table."; return; }
  await dapp.refresh();
  const ante = BigInt(tb.ante);
  if (!canPay(dapp, ante, "Joining this table")) { render(); return; }
  const g = randId(), S = load(LS_S); S[g] = { table: t, ts: Date.now() }; save(LS_S, S);
  activeTable = t; render();
  dapp.call("join", [t, g], ante, "join Farkle table #" + t + " · ante " + rawToNado(ante) + " NADO", { table: t, seat: g, phase: "join" });
}
function reopenTable() {   // retry an open/join that didn't confirm (same ante, fresh attempt)
  const T = load(LS_T)[activeTable];
  if (T && T.ante) { const raw = BigInt(T.ante); if (!canPay(dapp, raw, "Re-opening this table")) return; openTable(activeTable, randId(), raw); return; }
  // otherwise retry joining
  joinTable();
}
const doRoll = (g) => { keep = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0 }; dapp.call("roll", [g], null, "roll the dice · Farkle #" + activeTable, { table: activeTable, seat: g, phase: "roll" }); };
function doHold(g, cont) {
  dapp.call("hold", [g, keep[1], keep[2], keep[3], keep[4], keep[5], keep[6], cont], null,
    (cont ? "set aside + roll again" : "bank the turn") + " · Farkle #" + activeTable, { table: activeTable, seat: g, phase: "hold" });
}
const settleTable = () => dapp.call("settle", [activeTable], null, "pay the winner · table #" + activeTable, { table: activeTable, phase: "settle" });
const reclaimTable = () => dapp.call("reclaim", [activeTable], null, "reclaim the pot · table #" + activeTable, { table: activeTable, phase: "reclaim" });
const cancelTable = () => dapp.call("cancel", [activeTable], null, "cancel table #" + activeTable, { table: activeTable, phase: "cancel" });
const timeoutSeat = (g) => dapp.call("timeout", [g], null, "time out seat #" + g, { table: activeTable, phase: "timeout" });

async function refreshActive() {
  await dapp.refresh();
  const sto = await dapp.storage();
  if (sto) {
    lastSto = sto; pruneAndTrack(sto);
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
  for (const t of Object.keys(_m(sto, "ta"))) {
    if (!_m(sto, "tz")[t]) continue;
    const lead = _m(sto, "tb")[t]; if (!lead) continue;
    const seats = Object.keys(_m(sto, "gg")).filter((g) => String(_m(sto, "gg")[g]) === String(t));
    const ante = _m(sto, "ts")[t] || 0, pot = ante * seats.length;
    for (const g of seats) scoreBump(stats, _m(sto, "ga")[g], Number(g) === lead ? pot - ante : -ante);
  }
  return scoreSort(stats);
}
const renderScoreboard = (board) => renderScore($("scoreList"), board, dapp.me, "No finished tables yet — be the first on the board.");
function renderLobby(sto) {
  const el = $("lobbyList"); if (!el) return;
  const tables = Object.keys(_m(sto, "ta")).map((t) => tableFrom(sto, t)).filter((t) => t.exists && !t.closed);
  tables.sort((a, b) => (b.phase === "join") - (a.phase === "join") || b.id - a.id);
  el.innerHTML = tables.length ? tables.slice(0, 24).map((t) => {
    const tag = t.phase === "join" ? "🟢" : t.phase === "play" ? "🎲" : "🏁";
    const info = t.phase === "join" ? " · joins close " + blocksToTime(t.left) : t.phase === "play" ? " · in play" : "";
    return '<button class="chip ' + (t.phase === "join" ? "betting" : "") + '" data-t="' + t.id + '">' + tag + " #" + t.id
      + " · pot " + rawToNado(t.pot) + " · " + t.seatCount + " player" + (t.seatCount === 1 ? "" : "s") + info + "</button>";
  }).join(" ") : '<span class="dim">No tables yet — open one below.</span>';
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => selectTable(parseInt(b.dataset.t, 10)));
}
function selectTable(id) {
  activeTable = id; $("joinId").value = String(id);
  $("status").textContent = "Table #" + id + " selected.";
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
  $("btnNewTable").onclick = newTable;
  $("btnJoin").onclick = joinTable;
  if ($("btnReopen")) $("btnReopen").onclick = reopenTable;
  $("btnGoTable").onclick = () => { const id = parseInt($("joinId").value, 10); if (id) selectTable(id); else $("status").textContent = "Enter a table ID, or pick one from the lobby."; };
  $("btnSettle").onclick = settleTable;
  $("btnReclaim").onclick = reclaimTable;
  $("btnCancel").onclick = cancelTable;
}
function render() {
  const signedIn = renderWallet(dapp);
  gate({ play: signedIn, opencard: signedIn, bankroll: signedIn, activeGame: activeTable != null });
  const T = load(LS_T), S = load(LS_S), mine = [];
  for (const t of Object.keys(T)) mine.push({ id: +t, role: "host", ts: T[t].ts });
  for (const g of Object.keys(S)) mine.push({ id: S[g].table, seat: g, role: "seat", ts: S[g].ts });
  mine.sort((a, b) => b.ts - a.ts); const seen = new Set();
  const shown = mine.filter((x) => { x.live = x.role === "host" ? knownTables.has(String(x.id)) : knownSeats.has(String(x.seat)); x.icon = GICON; const k = String(x.id); if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 8);
  for (const x of shown) { if (x.live && lastSto) { const tb = tableFrom(lastSto, x.id); if (tb.exists) x.tag = tb.closed ? "finished ✓" : tb.phase === "join" ? "joining" : tb.phase === "play" ? "in play" : "settle!"; } }
  recentChips($("recent"), shown, selectTable, "No tables yet.");
  renderActive();
}
function renderActive() {
  if (activeTable == null) return;
  const tb = lastTable || {}, T = load(LS_T)[activeTable] || {}, me = mySeat(), iAmHost = tb.host === dapp.me;
  $("gameId").textContent = "#" + activeTable;
  shareInvite("table", activeTable, "Join my Farkle table #" + activeTable + " on NADO:", 180);
  $("gPot").textContent = tb.exists ? rawToNado(tb.pot) + " NADO" : "—";
  $("gAnte").textContent = tb.exists ? rawToNado(tb.ante) + " NADO" : "—";

  let phaseTxt = dapp.whereIs("table", activeTable, T.ts);
  if (tb.exists) {
    if (tb.closed) phaseTxt = "table settled ✓";
    else if (tb.phase === "join") phaseTxt = "🟢 joining open — closes in " + blocksToTime(tb.left) + " · " + tb.seatCount + " player" + (tb.seatCount === 1 ? "" : "s");
    else if (tb.phase === "play") phaseTxt = "🎲 in play — turns close in " + blocksToTime(tb.left) + " · " + tb.finishedCount + "/" + tb.seatCount + " done";
    else phaseTxt = "🏁 play window closed — settle below";
  }
  $("gStatus").textContent = phaseTxt;
  // the ONE join affordance: only shown when you can actually take a seat (open window, not already in)
  const joinable = tb.exists && tb.phase === "join" && dapp.me && !me;
  if ($("btnJoin")) { $("btnJoin").classList.toggle("hidden", !joinable); $("btnJoin").textContent = "🪑 Sit down — ante " + (tb.exists ? rawToNado(tb.ante) : "?") + " NADO"; }
  // reopen: your open/join didn't confirm within ~2 min
  const stalled = !tb.exists && T.ts && Date.now() - T.ts > 120000;
  if ($("btnReopen")) $("btnReopen").classList.toggle("hidden", !stalled);

  const feat = $("feature"), acts = $("myActions"); acts.innerHTML = "";
  const btn = (txt, fn, primary) => { const b = document.createElement("button"); b.className = primary ? "primary" : "ghost"; b.style.flex = "1 1 auto"; b.innerHTML = txt; b.onclick = fn; acts.appendChild(b); return b; };
  if (me && tb.exists && !tb.closed && tb.phase === "play") {
    if (me.finished) {
      feat.innerHTML = '<div class="turnhdr">Your turn is done — <b class="sc">' + me.final + " banked</b>. Waiting for the others…</div>";
    } else {
      const r = myRoll(me);
      if (!me.rollHeight) {
        feat.innerHTML = '<div class="turnhdr">Your turn · <b>' + me.diceLeft + '</b> dice in hand · banked so far <b class="sc">' + me.turnScore + '</b></div>'
          + '<div class="dim small mt">Roll, then set aside the scoring dice and choose to bank or push on.</div>';
        btn("🎲 Roll " + me.diceLeft + " dice", () => doRoll(me.g), true);
      } else if (r && r.pending) {
        feat.innerHTML = '<div class="turnhdr">🎲 Rolling… the dice lock when the block finalizes' + (r.spinsIn ? " (~" + blocksToTime(r.spinsIn) + ")" : "") + ".</div>";
      } else if (r && r.dice) {
        const dice = r.dice, rolled = countsOf(dice), farkle = greedyScore(dice) === 0;
        const ks = keepScoreValid(keep, rolled, me.diceLeft);
        const keptLeft = Object.assign({}, keep);
        const diceHtml = dice.map((d) => { const setAside = keptLeft[d] > 0; if (setAside) keptLeft[d]--;
          return '<span class="die ' + (setAside ? "kept" : "") + '" data-f="' + d + '">' + dieSVG(d) + "</span>"; }).join("");
        feat.innerHTML = '<div class="turnhdr">Banked so far <b class="sc">' + me.turnScore + '</b> · this roll:</div>'
          + '<div class="dicerow">' + diceHtml + "</div>"
          + (farkle ? '<div class="farkle mt">💥 FARKLE — no scoring dice. Your turn ends at 0.</div>'
              : '<div class="mt small">Set aside: <b class="sc">' + ks.score + '</b> pt' + (ks.score === 1 ? "" : "s")
                + (ks.kept ? "" : ' <span class="dim">(tap scoring dice — 1s &amp; 5s, or three+ of a kind)</span>') + "</div>");
        feat.querySelectorAll(".die").forEach((el) => el.onclick = () => toggleKeep(parseInt(el.dataset.f, 10), dice));
        if (farkle) {
          btn("💥 End turn (farkled)", () => { keep = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0 }; doHold(me.g, 0); }, true);
        } else {
          const canAct = ks.valid;
          btn("💰 Bank " + (me.turnScore + ks.score), () => doHold(me.g, 0), canAct).disabled = !canAct;
          btn("🎲 Set aside &amp; roll on", () => doHold(me.g, 1), false).disabled = !canAct;
        }
      }
    }
  } else if (me && tb.phase === "join") {
    feat.innerHTML = '<div class="turnhdr dim">You\'re seated — the table starts when joining closes.</div>';
  } else if (tb.phase === "join") {
    feat.innerHTML = '<div class="turnhdr dim">Ante to take a seat, then it\'s roll / bank / bust — real Farkle.</div>';
  } else {
    feat.innerHTML = "";
  }

  $("seats").innerHTML = lastSeats.length ? lastSeats.map((s) => {
    const you = s.addr === dapp.me ? '<b style="color:var(--accent2)">you</b> ' : "";
    const lead = tb.leader === s.g;
    let tag;
    if (s.finished) tag = s.final > 0 ? '<span class="b ok">' + s.final + (lead ? " 👑" : "") + "</span>" : '<span class="b dimb">farkled</span>';
    else if (s.rollHeight) tag = '<span class="b pend">rolling…</span>';
    else tag = '<span class="b pend">turn: ' + s.turnScore + " · " + s.diceLeft + "d</span>";
    return '<div class="seat">' + you + disp(s.addr) + " " + tag + "</div>";
  }).join("") : '<span class="dim">No players yet.</span>';

  const allDone = tb.exists && tb.seatCount > 0 && tb.finishedCount >= tb.seatCount && !tb.closed;
  if (tb.phase === "over" && !tb.closed) for (const s of lastSeats) if (!s.finished) { btn("⏱ Finalize seat #" + s.g, () => timeoutSeat(s.g), false); break; }
  $("btnSettle").classList.toggle("hidden", !(allDone && tb.leader));
  $("btnSettle").textContent = "🏆 Pay the winner — pot " + rawToNado(tb.pot || 0);
  $("btnReclaim").classList.toggle("hidden", !(allDone && !tb.leader && iAmHost));
  $("btnCancel").classList.toggle("hidden", !(tb.exists && !tb.closed && tb.seatCount === 1 && iAmHost));
}

// ---- boot ----------------------------------------------------------------------------------------
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.table != null) activeTable = pend.table;
  $("status").textContent = statusLabel(pend, ok, err, { roll: "Rolling…", hold: "Confirming your move…", settle: "Paying the winner…", reclaim: "Reclaiming…", timeout: "Finalizing…" });
});
async function boot() {
  try { await dapp.init(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload."; return; }
  wireUI(); loadQR(); orderCards(["activeGame", "lobby", "play", "opencard", "walletcard", "bankroll", "scoreboard"]);
  const q = new URLSearchParams(location.search).get("table");
  if (q) { $("joinId").value = q; if (activeTable == null) activeTable = parseInt(q, 10); }
  render(); refreshActive();
  setInterval(refreshActive, 3000);
}
boot();
