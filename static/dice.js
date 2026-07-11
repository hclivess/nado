// dice.js — NADO Dice: a provably-fair, peer-banked MULTIPLAYER "roll under" dice on the execution layer, built
// on the shared game SDK (nadodapp.js). Slide your win chance, the payout auto-scales (99 ÷ target → a flat 1%
// edge). A table SPINS ITSELF every ROUND blocks — no bank reveal, no secrets. Each seat gets its OWN roll from
// FINALIZED L1 block hashes nobody can predict while betting is open:
//     roll_g = HASH( BLOCKHASH(sh) + BLOCKHASH(sh+1) + seatId ) % 100
// Once the settle block is final, anyone can settle a seat (it pays the bettor); losing stakes fold into the
// bankroll so the table keeps rolling. Ordinary upgradable stackvm contract, no game-specific API.
import { NadoDapp, rawToNado, nadoToRaw, randId, _m, $, base, gate, canPay, hoist, orderCards, chainResult, blocksToTime,
         lsLoad as load, lsSave as save, lsPrune, wireWallet, stickyInputs, renderWallet, renderScore, scoreBump, scoreSort,
         recentChips, statusLabel, tablesOf as allTables, readTable,
         loadQR, drawQR, resolveAliases, disp, share, shareInvite } from "./nadodapp.js";

const CID = "9cbf40d70631f7ee86f58192de847273";
const GICON = '<svg style="vertical-align:-3px" viewBox="0 0 48 48" width="16" height="16" aria-hidden="true">     <rect x="9" y="9" width="30" height="30" rx="7" fill="#e6edf3" stroke="#243140" stroke-width="2"/>     <circle cx="17" cy="17" r="2.8" fill="#20272f"/><circle cx="31" cy="17" r="2.8" fill="#20272f"/>     <circle cx="24" cy="24" r="2.8" fill="#00ad93"/>     <circle cx="17" cy="31" r="2.8" fill="#20272f"/><circle cx="31" cy="31" r="2.8" fill="#20272f"/></svg>';
const PN = 100, MMIN = 2, MMAX = 98, EDGE = 99, BLOCK_SECS = 6, ROUND = 20;
const dapp = new NadoDapp({ cid: CID, app: "Dice" });

const LS_T = "nado_dice_tables", LS_S = "nado_dice_seats";
let lastSto = null;
let activeTable = null, lastTable = null, lastSeats = [], target = 50;
let knownTables = new Set(), knownSeats = new Set();

function pruneAndTrack(sto) {
  knownTables = lsPrune(LS_T, allTables(sto));
  knownSeats = lsPrune(LS_S, Object.keys(_m(sto, "gg")));
}
const multOf = (M) => EDGE / M;
const returnRaw = (stake, M) => BigInt(stake) * BigInt(EDGE) / BigInt(M);

// ---- reads (dice-specific storage schema) --------------------------------------------------------
const tableFrom = (sto, t) => readTable(sto, t, dapp.cursor, ROUND);
function seatsOfTable(sto, t) {
  t = String(t); const gg = _m(sto, "gg"), cur = dapp.cursor, out = [];
  for (const g of Object.keys(gg)) if (String(gg[g]) === t) {
    const M = _m(sto, "gm")[g] || 0, gh = _m(sto, "gh")[g] || 0, settled = !!_m(sto, "gd")[g];
    const s = { g: Number(g), addr: _m(sto, "ga")[g], stake: _m(sto, "gs")[g] || 0, M, gh, settled };
    if (settled) { const gr = _m(sto, "gr")[g] || 0; s.roll = gr ? gr - 1 : null; s.win = !!_m(sto, "gw")[g]; }
    else if (cur != null && cur >= gh + 1) { s.roll = chainResult(dapp.bh(gh), dapp.bh(gh + 1), g, PN); s.ready = true; s.win = s.roll != null ? s.roll < M : null; }
    else { s.pending = true; s.spinsIn = cur != null ? gh - cur : null; }
    out.push(s);
  }
  return out.sort((a, b) => b.g - a.g);
}
async function fetchTable(t) { const sto = await dapp.storage(); return sto ? tableFrom(sto, t) : null; }

// ---- actions -------------------------------------------------------------------------------------
function openTable(t, bankrollRaw) {
  const T = load(LS_T); T[t] = { bankroll: bankrollRaw.toString(), ts: Date.now() }; save(LS_T, T);
  activeTable = t; $("joinId").value = String(t);
  render();
  dapp.call("open", [t], bankrollRaw, "bank a dice table #" + t + " · " + rawToNado(bankrollRaw) + " NADO", { table: t, phase: "open" });
}
function reopenTable() {
  const T = load(LS_T)[activeTable]; if (!T || !T.bankroll) return;
  const raw = BigInt(T.bankroll);
  if (!canPay(dapp, raw, "Re-opening this table")) return;
  openTable(activeTable, raw);
}
async function newTable() {
  const raw = nadoToRaw($("bankrollAmt").value);
  if (!raw) { $("status").textContent = "Enter a bankroll (NADO)."; return; }
  await dapp.refresh();
  if (!canPay(dapp, raw, "Banking this table")) return;
  openTable(randId(), raw);
}
async function doBet() {
  const t = activeTable;
  if (!t) { $("status").textContent = "Pick a table first."; return; }
  const stake = nadoToRaw($("stakeAmt").value);
  if (!stake) { $("status").textContent = "Enter a stake (NADO)."; return; }
  const tb = await fetchTable(t);
  if (!tb || !tb.exists) { $("status").textContent = dapp.whereIs("table", t); return; }
  if (tb.closed) { $("status").textContent = "That table is closed."; return; }
  await dapp.refresh();
  if (!canPay(dapp, stake, "This roll")) { render(); return; }
  const need = returnRaw(stake, target) - stake;
  if (BigInt(tb.bankroll) - BigInt(tb.committed) < need) { $("status").textContent = "This table can't cover a " + multOf(target).toFixed(2) + "× win right now. Lower your stake or raise your win chance."; render(); return; }
  const g = randId(), S = load(LS_S);
  S[g] = { table: t, stake: stake.toString(), M: target, ts: Date.now() }; save(LS_S, S);
  render();
  dapp.call("bet", [g, t, target], stake, "roll under " + target + " for " + rawToNado(stake) + " NADO · table #" + t, { table: t, seat: g, phase: "bet" });
}
function fundTable() {
  const raw = nadoToRaw($("fundAmt").value);
  if (!raw) { $("status").textContent = "Enter an amount to add to this table's bankroll."; return; }
  if (!canPay(dapp, raw, "The top-up")) return;
  dapp.call("fund", [activeTable], raw, "top up table #" + activeTable + " bankroll · " + rawToNado(raw) + " NADO", { table: activeTable, phase: "fund" });
}
const settleSeat = (g) => dapp.call("settle", [g], null, "collect seat #" + g, { table: activeTable, phase: "settle" });
// AUTO-COLLECT: a resolved WINNING seat settles itself (value-free → auto-signs, a quick bounce). One per
// tick; `autoTried` stops a rejected settle from looping. Opt-out per game (default on).
const autoTried = new Set();
function maybeAutoSettle() {
  if (localStorage.getItem("nado_dice_autocollect") === "0") return;
  if (!dapp.me || dapp.inflight || !lastTable || !lastTable.exists) return;
  const t = lastSeats.find((s) => s.addr === dapp.me && !s.settled && s.ready && s.win && !autoTried.has(s.g));
  if (!t) return;
  autoTried.add(t.g);
  settleSeat(t.g);
}
const closeTable = () => dapp.call("close", [activeTable], null, "close table #" + activeTable, { table: activeTable, phase: "close" });

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
        const gh = _m(sto, "gh")[g] || 0; if (!_m(sto, "gd")[g] && cur != null && cur >= gh + 1) need.push(gh, gh + 1);
      }
      if (need.length) await dapp.blockHashes(need, { fast: true });   // dice rolls: PUBLIC + on-chain-validated -> provisional (fast) is safe; results show ~one block after the roll instead of waiting out finality
      lastSeats = seatsOfTable(sto, activeTable);
    }
    renderLobby(sto); renderScoreboard(boardFrom(sto));
  }
  await resolveAliases([dapp.me].concat(lastTable ? [lastTable.bank] : []).concat(lastSeats.map((s) => s.addr)));
  render();
  maybeAutoSettle();
}
function boardFrom(sto) {
  const stats = {};
  for (const g of Object.keys(_m(sto, "gd"))) {
    if (!_m(sto, "gd")[g]) continue;
    const t = String(_m(sto, "gg")[g]), bank = _m(sto, "ta")[t]; if (!bank) continue;
    const M = _m(sto, "gm")[g] || 1, stake = _m(sto, "gs")[g] || 0, win = !!_m(sto, "gw")[g];
    const net = win ? Number(returnRaw(stake, M)) - stake : -stake;
    scoreBump(stats, _m(sto, "ga")[g], net); scoreBump(stats, bank, -net);
  }
  return scoreSort(stats);
}
const renderScoreboard = (board) => renderScore($("scoreList"), board, dapp.me, "No settled rolls yet — be the first on the board.");
function renderLobby(sto) {
  const el = $("lobbyList"); if (!el) return;
  const tables = allTables(sto).map((t) => tableFrom(sto, t)).filter((t) => t.exists && !t.closed);
  tables.sort((a, b) => b.seatCount - a.seatCount || b.id - a.id);
  const shown = tables.slice(0, 24);
  el.innerHTML = shown.length ? shown.map((t) => {
    const left = t.roundEndsIn != null ? " · next roll " + blocksToTime(t.roundEndsIn) : "";
    return '<button class="chip betting" data-t="' + t.id + '">🟢 #' + t.id + " · bank " + rawToNado(t.bankroll) + " · " + t.seatCount + " roll" + (t.seatCount === 1 ? "" : "s") + left + "</button>";
  }).join(" ") : '<span class="dim">No tables yet — bank one below.</span>';
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => selectTable(parseInt(b.dataset.t, 10)));
}
function selectTable(id) {
  activeTable = id; $("joinId").value = String(id);
  $("status").textContent = "Table #" + id + " — set your stake and win chance, then Place roll.";
  refreshActive();
  try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {}
}

// ---- render --------------------------------------------------------------------------------------
// MAX BET: the biggest stake this table can still cover at the current win-chance. A win pays
// returnRaw(stake,target); the bank's exposure is that minus the stake, and it must fit the free bankroll:
//   stake*(EDGE-target)/target <= (bankroll - committed)  =>  stake <= free*target/(EDGE-target)
function maxBetRaw() {
  const tb = lastTable;
  if (!tb || !tb.exists || tb.closed) return null;
  const free = BigInt(tb.bankroll) - BigInt(tb.committed);
  if (free <= 0n || EDGE - target <= 0) return null;
  return free * BigInt(target) / BigInt(EDGE - target);
}
function syncStakeSlider() {
  const sl = $("stakeSlider"), wrap = $("stakeSliderWrap"); if (!sl || !wrap) return;
  const maxRaw = maxBetRaw();
  if (maxRaw == null || maxRaw <= 0n) { wrap.classList.add("hidden"); return; }
  wrap.classList.remove("hidden");
  const maxN = parseFloat(rawToNado(maxRaw)) || 0;
  sl.max = String(maxN);
  sl.step = String(Math.max(maxN / 200, 0.001));
  const curN = parseFloat($("stakeAmt").value) || 0;
  sl.value = String(Math.min(curN, maxN));
  $("maxBetVal").textContent = rawToNado(maxRaw) + " NADO";
  $("stakeSliderVal").textContent = "stake " + ($("stakeAmt").value || "0") + " NADO";
}
function syncSlider() {
  target = Math.min(MMAX, Math.max(MMIN, parseInt($("target").value, 10) || 50));
  $("winChanceTarget").textContent = target;
  $("winChance").textContent = target + "%";
  $("multiplier").textContent = multOf(target).toFixed(2) + "×";
  const stake = nadoToRaw($("stakeAmt").value);
  $("payoutPreview").textContent = stake ? "win pays " + rawToNado(returnRaw(stake, target)) + " NADO" : "";
  syncStakeSlider();
}
function wireUI() {
  wireWallet(dapp);
  stickyInputs(dapp, ['stakeAmt', 'bankrollAmt', 'fundAmt', 'bankAmt']);   // typed amounts persist across turns
  $("btnNewTable").onclick = newTable;
  $("btnBet").onclick = doBet;
  $("btnGoTable").onclick = () => { const id = parseInt($("joinId").value, 10); if (id) selectTable(id); else $("status").textContent = "Enter a table ID, or pick one from the lobby."; };
  $("btnClose").onclick = closeTable;
  const ac = $("autoCollect");
  if (ac) { ac.checked = localStorage.getItem("nado_dice_autocollect") !== "0";
    ac.onchange = () => { try { localStorage.setItem("nado_dice_autocollect", ac.checked ? "1" : "0"); } catch (e) {} }; }
  $("btnReopen").onclick = reopenTable;
  $("btnFund").onclick = fundTable;
  $("btnShare").onclick = () => share(base() + "/?table=" + activeTable, "Roll at my dice table #" + activeTable + " on NADO:", $("btnShare"));
  $("target").oninput = () => { syncSlider(); render(); };
  $("stakeAmt").oninput = () => { syncSlider(); render(); };
  $("stakeSlider").oninput = () => { const v = $("stakeSlider").value; $("stakeAmt").value = String(v); syncSlider(); render(); };
  $("btnMaxBet").onclick = () => { const m = maxBetRaw(); if (m && m > 0n) { $("stakeAmt").value = rawToNado(m); syncSlider(); render(); } };
}
function render() {
  const signedIn = renderWallet(dapp);
  gate({ play: signedIn, bankcard: signedIn, bankroll: signedIn, activeGame: activeTable != null });
  const tb = (activeTable != null && lastTable && lastTable.exists && !lastTable.closed) ? lastTable : null;
  const stake = nadoToRaw($("stakeAmt").value);
  const need = stake ? returnRaw(stake, target) - stake : null;
  const covers = !(tb && need != null && (BigInt(tb.bankroll) - BigInt(tb.committed)) < need);
  const canAfford = !(signedIn && stake && dapp.exec < stake);
  const betable = !!tb && !!stake && canAfford && covers;
  if ($("btnBet")) { $("btnBet").disabled = !betable; $("btnBet").classList.toggle("pulse", betable && signedIn); }
  let hint = "";
  if (signedIn && activeTable != null) {
    if (!tb && !lastTable?.exists) hint = dapp.whereIs("table", activeTable, (load(LS_T)[activeTable] || {}).ts);
    else if (lastTable && lastTable.closed) hint = "Table #" + activeTable + " is closed.";
    else if (!stake) hint = "Enter a stake (NADO) and set your win chance, then Place roll — you can bet at your own table too.";
    else if (dapp.exec < stake) hint = "Not enough NADO — this rolls " + rawToNado(stake) + " but your exec balance is " + rawToNado(dapp.exec) + ". Deposit at least " + rawToNado(stake - dapp.exec) + " more below.";
    else if (tb && !covers) hint = "This table's bankroll can't cover a " + multOf(target).toFixed(2) + "× win (free: " + rawToNado(BigInt(tb.bankroll) - BigInt(tb.committed)) + " NADO). Lower your stake, raise your win chance, or Top up the bankroll.";
  }
  const jh = $("joinHint"); if (jh) { jh.textContent = hint; jh.classList.toggle("hidden", !hint); }
  syncStakeSlider();   // keep the max-bet slider in step with the table's live free cover
  const T = load(LS_T), S = load(LS_S), mine = [];
  for (const t of Object.keys(T)) mine.push({ id: +t, role: "bank", ts: T[t].ts });
  for (const g of Object.keys(S)) mine.push({ id: S[g].table, seat: g, role: "bet", ts: S[g].ts });
  mine.sort((a, b) => b.ts - a.ts); const seen = new Set();
  const shown = mine.filter((x) => {
    x.live = x.role === "bank" ? knownTables.has(String(x.id)) : knownSeats.has(String(x.seat));
    x.icon = x.role === "bank" ? "🏦" : "🎲";
    const k = String(x.id); if (seen.has(k)) return false; seen.add(k); return true;
  }).slice(0, 8);
  for (const x of shown) {
    if (!x.live || !lastSto) continue;
    const tb = tableFrom(lastSto, x.id);
    if (!tb.exists) continue;
    if (tb.closed) x.tag = "finished ✓";
    else {
      x.tag = "live";
      const mySeats = seatsOfTable(lastSto, x.id).filter((st) => st.addr === dapp.me);
      if (mySeats.some((st) => !st.settled && st.ready && st.win)) x.tag = "💰 win to collect";
      else if (mySeats.some((st) => st.pending)) x.tag = "your bet spins soon";
    }
  }
  recentChips($("recent"), shown, selectTable, "No tables yet.");
  renderActive();
}
function renderActive() {
  if (activeTable == null) return;
  const tb = lastTable || {}, T = load(LS_T)[activeTable] || {};
  const iAmBank = tb.bank === dapp.me, mySeats = lastSeats.filter((s) => s.addr === dapp.me);
  $("gameId").textContent = "#" + activeTable;
  shareInvite("table", activeTable, "Roll at my dice table #" + activeTable + " on NADO:", 180);
  $("gBank").textContent = tb.exists ? (disp(tb.bank) + (iAmBank ? " — that's you (you're the house here)" : "")) : (T.bankroll ? "you (opening…)" : "—");
  $("gBankroll").textContent = tb.exists ? rawToNado(tb.bankroll) + " NADO" : (T.bankroll ? rawToNado(T.bankroll) + " NADO" : "—");
  $("gCover").textContent = tb.exists ? rawToNado(BigInt(tb.bankroll) - BigInt(tb.committed)) + " NADO free" : "—";
  let phaseTxt = dapp.whereIs("table", activeTable, T.ts);
  if (tb.exists) {
    if (tb.closed) phaseTxt = "table closed";
    else phaseTxt = "🟢 rolling every " + blocksToTime(ROUND) + " — next roll in " + (tb.roundEndsIn != null ? blocksToTime(tb.roundEndsIn) : "…") + " · " + tb.seatCount + " roll" + (tb.seatCount === 1 ? "" : "s");
  }
  $("gStatus").textContent = phaseTxt;
  $("btnReopen").classList.toggle("hidden", !(!tb.exists && T.bankroll && T.ts && Date.now() - T.ts > 120000));
  // die shows the most recent resolved roll at this table
  const resolved = lastSeats.filter((s) => s.roll != null).sort((a, b) => b.gh - a.gh);
  const die = $("die");
  if (die) { if (resolved.length) { die.textContent = resolved[0].roll; die.className = "die " + (resolved[0].win ? "wroll" : "lroll"); } else { die.textContent = "?"; die.className = "die"; } }
  const seatRow = (s) => {
    const you = s.addr === dapp.me ? '<b style="color:var(--accent2)">you</b> ' : "";
    let out = "on <b>under " + s.M + "</b> <span class='dim'>(" + multOf(s.M).toFixed(2) + "×)</span>";
    if (s.roll != null) out += ' → rolled <b class="' + (s.win ? "wroll" : "lroll") + '">' + s.roll + "</b> "
        + (s.settled ? (s.win ? '<span class="b ok">won ' + rawToNado(returnRaw(s.stake, s.M)) + "</span>" : '<span class="b dimb">no win</span>')
                     : (s.win ? '<span class="b pend">won ' + rawToNado(returnRaw(s.stake, s.M)) + " — collect</span>" : '<span class="b dimb">lost</span>'));
    else out += ' <span class="b pend">rolls in ' + (s.spinsIn != null ? blocksToTime(s.spinsIn) : "…") + "</span>";
    return '<div class="seat">' + you + disp(s.addr) + ' · <span class="mono">' + rawToNado(s.stake) + "</span> " + out + "</div>";
  };
  $("seats").innerHTML = lastSeats.length ? lastSeats.map(seatRow).join("") : '<span class="dim">No rolls yet — be the first to bet.</span>';
  const wrap = $("myActions"); wrap.innerHTML = "";
  for (const s of mySeats) {
    if (s.settled || !s.ready) continue;
    const b = document.createElement("button"); b.className = "primary"; b.style.flex = "1 1 auto";
    b.textContent = s.win ? "💰 Collect " + rawToNado(returnRaw(s.stake, s.M)) + " (seat #" + s.g + ")" : "Close out seat #" + s.g;
    b.onclick = () => settleSeat(s.g); if (s.win || iAmBank) wrap.appendChild(b);
  }
  $("btnClose").classList.toggle("hidden", !(iAmBank && tb.exists && !tb.closed && tb.settledCount >= tb.seatCount));
  $("btnClose").textContent = tb.seatCount === 0 ? "Cancel — reclaim bankroll" : "Close table — reclaim " + rawToNado(tb.pool);
  $("fundRow").classList.toggle("hidden", !(iAmBank && tb.exists && !tb.closed));
}

// ---- boot ----------------------------------------------------------------------------------------
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.table != null) activeTable = pend.table;
  $("status").textContent = statusLabel(pend, ok, err);
});
async function boot() {
  try { await dapp.init(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload."; return; }
  wireUI(); loadQR(); syncSlider(); orderCards(["activeGame","lobby","play","bankcard","walletcard","bankroll","scoreboard"]);
  const q = new URLSearchParams(location.search).get("table");
  if (q) { $("joinId").value = q; if (activeTable == null) activeTable = parseInt(q, 10); }
  render(); refreshActive();
  setInterval(refreshActive, 3000);
}
boot();
