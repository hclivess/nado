// roulette.js — NADO Roulette: a provably-fair, peer-banked, MULTIPLAYER European (single-zero) roulette on the
// execution layer, built on the shared game SDK (nadodapp.js). A table is one shared wheel that SPINS ITSELF
// every ROUND blocks — no bank reveal, no secrets, no "spin" button ever. A BANK opens a table with a bankroll;
// bettors take independent seats any time, each staking on a set of covered numbers. A bet binds to the round it
// lands in, whose result is fixed by FINALIZED L1 block hashes nobody can predict while betting is open:
//   result = HASH( BLOCKHASH(sh) + BLOCKHASH(sh+1) + tableId ) % 37
// Once the settle block is final, ANYONE can settle a seat (it pays the bettor) — a stalling bank can't rob
// anyone. A win pays the true 36/count; losing stakes fold into the bankroll. Ordinary upgradable stackvm
// contract, no game-specific API.
import { NadoDapp, rawToNado, nadoToRaw, randId, _m, $, base, gate, canPay, orderCards, chainResultAlg, blocksToTime, wireWallet, stickyInputs, renderWallet, renderScore, scoreBump, scoreSort, alertBar, notify, confirmingLabel, loadQR, resolveAliases, disp, share, shareInvite , installModes } from "./nadodapp.js";
import { BankedGame } from "./bankedgame.js";   // the ONE banked-table reader/lobby (shared by every house game)
import { Practice } from "./practice.js";      // free in-browser practice (play chips, no chain)

const CID = "a01d2b0e6a598821b57ef927bb5e25e8";
const GICON = '<svg style="vertical-align:-3px" viewBox="0 0 48 48" width="16" height="16" aria-hidden="true">     <circle cx="24" cy="24" r="16" fill="#0b0f14" stroke="#b5810f" stroke-width="2"/>     <g stroke="#0b0f14" stroke-width=".6">       <path d="M24 24 L24 8 A16 16 0 0 1 35.3 12.7 Z" fill="#d0362b"/>       <path d="M24 24 L35.3 12.7 A16 16 0 0 1 40 24 Z" fill="#20272f"/>       <path d="M24 24 L40 24 A16 16 0 0 1 35.3 35.3 Z" fill="#1f8f4e"/>       <path d="M24 24 L35.3 35.3 A16 16 0 0 1 24 40 Z" fill="#d0362b"/>       <path d="M24 24 L24 40 A16 16 0 0 1 12.7 35.3 Z" fill="#20272f"/>       <path d="M24 24 L12.7 35.3 A16 16 0 0 1 8 24 Z" fill="#d0362b"/>       <path d="M24 24 L8 24 A16 16 0 0 1 12.7 12.7 Z" fill="#20272f"/>       <path d="M24 24 L12.7 12.7 A16 16 0 0 1 24 8 Z" fill="#20272f"/></g>     <circle cx="24" cy="24" r="6" fill="#e3b341" stroke="#b5810f" stroke-width="1.4"/>     <circle cx="24" cy="24" r="2.2" fill="#0b0f14"/>     <circle cx="24" cy="10.5" r="2" fill="#fff"/></svg>';
const PN = 37, MAXSLOTS = 18, BLOCK_SECS = 6, ROUND = 20;   // ROUND must match the contract
const dapp = new NadoDapp({ cid: CID, app: "Roulette" });
const bg = new BankedGame(dapp, { icon: "🎯" });   // shared banked-table SDK (reader/open/lobby/recent/seats); 🎯 = the seat-chip icon roulette always used
bg.LS_T = "nado_roul_tables"; bg.LS_S = "nado_roul_seats";   // pre-SDK localStorage keys (slug default would be nado_roulette_*) — keep users' existing pending table/seat records
const RED = new Set([1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]);
const colorOf = (n) => n === 0 ? "green" : (RED.has(n) ? "red" : "black");
const colorName = (n) => { const c = colorOf(n); return c === "red" ? window.t("roul.colRed", "RED") : c === "black" ? window.t("roul.colBlack", "BLACK") : window.t("roul.colGreen", "GREEN"); };

let lastSto = null;
let lastTable = null, lastSeats = [], selected = new Set();   // the selected table id lives in bg.active
let seatsN = 40;   // cap how many of a table's (unbounded) seats we render at once; "Show more" grows it

function reopenTable() {   // retry an open that never landed (same id is still fresh on-chain)
  const T = bg.tableRec(bg.active); if (!T || !T.bankroll) return;
  const raw = BigInt(T.bankroll);
  if (!canPay(dapp, raw, "Re-opening this table")) return;
  openTable(bg.active, raw);
}


// ---- reads (roulette-specific storage schema) ----------------------------------------------------
function coveredOf(sto, g) { const mask = BigInt(_m(sto, "gmask")[String(g)] || 0), out = []; for (let n = 0; n < PN; n++) if ((mask >> BigInt(n)) & 1n) out.push(n); return out; }
const tableFrom = (sto, t) => bg.read(sto, t);
function seatsOfTable(sto, t) {   // bg.seats walks the seat maps + sorts newest-first; roulette adds mask/result fields
  t = String(t); const cur = dapp.cursor;
  return bg.seats(sto, t, (g, s) => {
    const covered = coveredOf(sto, g), cn = _m(sto, "gc")[g] || covered.length || 1;
    s.count = cn; s.covered = covered; s.mult = Math.floor(36 / cn);
    if (s.settled) { const gr = _m(sto, "gr")[g] || 0; s.result = gr ? gr - 1 : null; s.win = !!_m(sto, "gw")[g]; }
    else if (cur != null && cur >= s.gh + 1) { s.result = chainResultAlg(dapp.bh(s.gh), dapp.bh(s.gh + 1), t, PN); s.ready = true; s.win = s.result != null ? covered.includes(s.result) : null; }
    else { s.pending = true; s.spinsIn = cur != null ? s.gh - cur : null; }   // waiting for its round to end
    return s;
  });
}
async function fetchTable(t) { const sto = await dapp.storage({ append: ["gg", "ga", "gs", "gmask", "gc", "gh", "gr", "gw", "gd"] }); return sto ? tableFrom(sto, t) : null; }

// ---- bet maths -----------------------------------------------------------------------------------
const betCount = () => selected.size;
const betMult = () => { const c = betCount(); return c >= 1 && c <= MAXSLOTS ? Math.floor(36 / c) : 0; };
const betMask = () => { let m = 0n; for (const n of selected) m |= (1n << BigInt(n)); return m.toString(); };   // 37-bit coverage mask (arg-packed)

// ---- actions -------------------------------------------------------------------------------------
function openTable(t, bankrollRaw) {   // bg.reopen = SDK open with an EXPLICIT id (newTable passes a fresh randId; Reopen retries the stuck one) — the label needs t up front
  bg.reopen(t, bankrollRaw, "bank roulette table #" + t + " · " + rawToNado(bankrollRaw) + " NADO");
  $("joinId").value = String(t);
  render();
}
async function newTable() {
  const raw = nadoToRaw($("bankrollAmt").value);
  if (!raw) return alertBar(window.t("roul.needBankroll", "Enter a bankroll (NADO) to bank a table."));
  await dapp.refresh();
  if (!canPay(dapp, raw, "Banking this table")) return;
  openTable(randId(), raw);
}
async function doBet() {
  const t = bg.active;
  if (!t) return alertBar(window.t("roul.pickTableFirst", "Pick a table first."));
  if (!betCount()) return alertBar(window.t("roul.pickNumber", "Pick at least one number on the table to bet on."));
  if (dapp.busy("bet", "table", t)) return notify(confirmingLabel());   // one bet confirming at a time — a re-click would place a second seat
  const stake = nadoToRaw($("stakeAmt").value);
  if (!stake) return alertBar(window.t("roul.enterStake", "Enter a stake (NADO)."));
  const tb = await fetchTable(t);
  if (!tb || !tb.exists) return alertBar(dapp.whereIs("table", t));
  if (tb.closed) return alertBar(window.t("roul.tableClosedMsg", "That table is closed."));
  await dapp.refresh();
  if (!canPay(dapp, stake, "This bet")) { render(); return; }
  const need = stake * BigInt(betMult() - 1);
  if (BigInt(tb.pool) - BigInt(tb.committed) < need) { alertBar(window.t("roul.cantCoverNow", "This table can't cover a {mult}× win right now (bankroll left: {left} NADO). Lower your stake or widen your bet.", { mult: betMult(), left: rawToNado(BigInt(tb.pool) - BigInt(tb.committed)) })); render(); return; }
  const g = randId();
  bg.rememberSeat(g, { stake: stake.toString(), numbers: [...selected] });
  render();
  dapp.call("bet", [g, t, betMask()], stake, "bet " + rawToNado(stake) + " NADO on " + selected.size + " number(s) · table #" + t, { table: t, seat: g, phase: "bet" });
}
function fundTable() {
  const raw = nadoToRaw($("fundAmt").value);
  if (!raw) return alertBar(window.t("roul.enterTopUp", "Enter an amount to add to this table's bankroll."));
  if (!canPay(dapp, raw, "The top-up")) return;
  bg.fund(raw, "top up table #" + bg.active + " bankroll · " + rawToNado(raw) + " NADO");
}
const settleSeat = (g) => { if (dapp.busy("settle", "seat", g)) return; dapp.call("settle", [g], null, "collect seat #" + g, { table: bg.active, seat: g, phase: "settle" }); };
// AUTO-COLLECT a resolved WINNING seat (shared SDK tick — opt-out slider, one-per-refresh, autoTried dedup)
function maybeAutoSettle() {
  if (!lastTable || !lastTable.exists) return;
  dapp.autoCollect(lastSeats.filter((s) => s.addr === dapp.me && !s.settled && s.ready && s.win), (s) => settleSeat(s.g));
}
const closeTable = () => bg.close("close table #" + bg.active);

async function refreshActive() {
  await dapp.refresh();
  const sto = await dapp.storage({ append: ["gg", "ga", "gs", "gmask", "gc", "gh", "gr", "gw", "gd"] });
  if (sto) {
    lastSto = sto;
    bg.track(sto);
    // release the click guard the instant an action's effect is on-chain (bg.landed = open/fund/close/bet;
    // settle when the seat flips to settled). MUST run with sto in hand — tip-advance alone no longer clears it.
    dapp.settleInflight((f) => bg.landed(f, sto) || (f.phase === "settle" && f.seat != null && !!_m(sto, "gd")[String(f.seat)]));
    if (bg.active != null) {
      lastTable = tableFrom(sto, bg.active);
      // fetch the block hashes needed to resolve every finished-but-unsettled seat at this table
      // (kept local instead of bg.prefetchHashes: the SDK caps at 30 heights, this fetches every needed pair)
      const cur = dapp.cursor, need = [];
      for (const g of Object.keys(_m(sto, "gg"))) if (String(_m(sto, "gg")[g]) === String(bg.active)) {
        const gh = _m(sto, "gh")[g] || 0; if (!_m(sto, "gd")[g] && cur != null && cur >= gh + 1) { need.push(gh, gh + 1); }
      }
      if (need.length) await dapp.blockHashes(need, { fast: true });   // roulette spins: PUBLIC + on-chain-validated -> provisional (fast) is safe; results show ~one block after the roll instead of waiting out finality
      lastSeats = seatsOfTable(sto, bg.active);
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
    const cn = _m(sto, "gc")[g] || 1, stake = _m(sto, "gs")[g] || 0, win = !!_m(sto, "gw")[g];
    const net = win ? stake * (Math.floor(36 / cn) - 1) : -stake;
    const who = _m(sto, "ga")[g];
    scoreBump(stats, who, net); if (bank !== who) scoreBump(stats, bank, -net);   // self-play: the bank leg would cancel your own win to a bogus ±0
  }
  return scoreSort(stats);
}
const renderScoreboard = (board) => renderScore($("scoreList"), board, dapp.me, window.t("roul.noScores", "No settled bets yet — be the first on the board."));
function renderLobby(sto) {
  bg.lobby($("lobbyList"), sto, (t) => {
    const left = t.roundEndsIn != null ? window.t("roul.nextSpinShort", " · next spin {t}", { t: blocksToTime(t.roundEndsIn) }) : "";
    const seat = t.seatCount === 1 ? window.t("roul.seatOne", "seat") : window.t("roul.seatMany", "seats");
    return window.t("roul.lobbyChip", "🟢 #{id} · bank {bank} · {n} {seat}{left}", { id: t.id, bank: rawToNado(t.pool), n: t.seatCount, seat, left });
  }, selectTable, (a, b) => b.seatCount - a.seatCount || b.id - a.id);   // busiest wheel first (not the SDK's free-bankroll sort)
}
function selectTable(id) {
  bg.active = id; seatsN = 40; $("joinId").value = String(id);
  notify(window.t("roul.tableSelected", "Table #{id} — build your bet on the layout and set a stake, then Place bet.", { id }));
  refreshActive();
  try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {}
}

// ---- the roulette TABLE (bet builder) ------------------------------------------------------------
const GROUPS = { "1-18": range(1, 18), "19-36": range(19, 36), EVEN: range(1,36).filter(n=>n%2===0), ODD: range(1,36).filter(n=>n%2===1),
  RED: [...RED].sort((a,b)=>a-b), BLACK: range(1,36).filter(n=>!RED.has(n)),
  "1st 12": range(1,12), "2nd 12": range(13,24), "3rd 12": range(25,36), C1: col(1), C2: col(2), C3: col(3) };
function range(a, b) { const o = []; for (let i = a; i <= b; i++) o.push(i); return o; }
function col(c) { return range(1, 36).filter((n) => (n % 3) === (c % 3)); }
function buildTable() {
  const grid = $("tableGrid"); if (!grid || grid.dataset.built) return; grid.dataset.built = "1";
  let html = '<button class="cell green zero" data-n="0">0</button>';
  for (let rrow = 0; rrow < 3; rrow++) for (let ccol = 0; ccol < 12; ccol++) {
    const n = ccol * 3 + (3 - rrow);
    html += '<button class="cell ' + colorOf(n) + '" data-n="' + n + '" style="grid-row:' + (rrow + 1) + ';grid-column:' + (ccol + 2) + '">' + n + "</button>";
  }
  for (let rrow = 0; rrow < 3; rrow++) html += '<button class="cell col2to1" data-grp="C' + (3 - rrow) + '" style="grid-row:' + (rrow + 1) + ';grid-column:14">2:1</button>';
  grid.innerHTML = html;
  grid.querySelectorAll("[data-n]").forEach((b) => b.onclick = () => toggleNum(parseInt(b.dataset.n, 10)));
  grid.querySelectorAll("[data-grp]").forEach((b) => b.onclick = () => selectGroup(b.dataset.grp));
  document.querySelectorAll("[data-grp2]").forEach((b) => b.onclick = () => selectGroup(b.dataset.grp2));
  const clr = $("btnClearBet"); if (clr) clr.onclick = () => { selected = new Set(); paintTable(); render(); };
}
function toggleNum(n) { if (selected.has(n)) selected.delete(n); else if (selected.size < MAXSLOTS) selected.add(n); paintTable(); render(); }
function selectGroup(key) { selected = new Set((GROUPS[key] || []).slice(0, MAXSLOTS)); paintTable(); render(); }
function paintTable() { document.querySelectorAll("#tableGrid .cell[data-n]").forEach((b) => b.classList.toggle("sel", selected.has(parseInt(b.dataset.n, 10)))); }

// ---- render --------------------------------------------------------------------------------------
// MAX BET: the biggest stake this table can cover for the current selection. A win returns stake*M, so the
// bank's exposure is stake*(M-1) and it must fit the free bankroll:  stake <= (bankroll-committed)/(M-1).
function maxBetRaw() {
  const tb = lastTable, M = betMult();
  if (!tb || !tb.exists || tb.closed || M <= 1) return null;
  const free = BigInt(tb.pool) - BigInt(tb.committed);
  if (free <= 0n) return null;
  let cap = free / BigInt(M - 1);                        // exposure (M-1)*stake must fit the free bankroll
  if (cap > free) cap = free;                            // never offer a stake bigger than the bank holds
  const bal = dapp.exec || 0n;
  if (bal > 0n && bal < cap) cap = bal;                  // never offer a stake you can't afford
  return cap;
}
const syncStakeSlider = () => dapp.syncStakeSlider(maxBetRaw());   // shared SDK slider
function wireUI() {
  wireWallet(dapp);
  stickyInputs(dapp, ['stakeAmt', 'bankrollAmt', 'fundAmt', 'bankAmt', 'betAmt']);   // typed amounts persist across turns
  $("btnNewTable").onclick = newTable;
  $("btnBet").onclick = doBet;
  $("btnGoTable").onclick = () => { const id = parseInt($("joinId").value, 10); if (id) selectTable(id); else alertBar(window.t("roul.enterTableId", "Enter a table ID, or pick one from the lobby.")); };
  dapp.wireStakeSlider(maxBetRaw, () => render());   // owns stakeAmt input + the % slider + Max
  dapp.wirePctSlider("bankroll", { slider: "bankrollSlider", input: "bankrollAmt" }, () => dapp.exec, render);   // bank a table: % of your playable balance
  dapp.wirePctSlider("fund", { slider: "fundSlider", input: "fundAmt" }, () => dapp.exec, render);   // top up the bankroll: % of your playable balance
  $("btnClose").onclick = closeTable;
  if ($("btnMoreSeats")) $("btnMoreSeats").onclick = () => { seatsN += 60; renderActive(); };
  dapp.wireAutoCollect();
  $("btnFund").onclick = fundTable;
  $("btnReopen").onclick = reopenTable;
  $("btnShare").onclick = () => share(base() + "/?table=" + bg.active, window.t("roul.shareText", "Bet at my roulette table #{id} on NADO:", { id: bg.active }), $("btnShare"));
  buildTable();
}
var render = function render() {
  dapp.reflectUrl("table", bg.active);   // address bar = the shareable link to the selected table
  dapp.syncPctSlider("bankroll", { slider: "bankrollSlider", input: "bankrollAmt" }, dapp.exec);
  dapp.syncPctSlider("fund", { slider: "fundSlider", input: "fundAmt" }, dapp.exec);
  const signedIn = renderWallet(dapp);
  gate({ play: signedIn, bankcard: signedIn, bankroll: signedIn, activeGame: bg.active != null });
  const c = betCount(), M = betMult(), stakeRaw = nadoToRaw($("stakeAmt").value);
  if ($("betInfo")) $("betInfo").innerHTML = c
    ? window.t("roul.covering", "Covering <b>{c}</b> {nWord} · pays <b>{m}×</b>", { c, nWord: (c > 1 ? window.t("roul.numbersWord", "numbers") : window.t("roul.numberWord", "number")), m: M }) + (stakeRaw ? window.t("roul.winReturns", " · win returns <b>{v} NADO</b> (net +{net})", { v: rawToNado(stakeRaw * BigInt(M)), net: rawToNado(stakeRaw * BigInt(M - 1)) }) : "")
    : '<span class="dim">' + window.t("roul.tapToBuild", "Tap numbers or a bet region on the table to build your bet.") + "</span>";
  const tb = (bg.active != null && lastTable && lastTable.exists && !lastTable.closed) ? lastTable : null;
  const canAfford = !(signedIn && stakeRaw && dapp.exec < stakeRaw);
  const need = (stakeRaw && M) ? stakeRaw * BigInt(M - 1) : null;
  const bankCovers = !(tb && need != null && (BigInt(tb.pool) - BigInt(tb.committed)) < need);
  const betBusy = tb && dapp.busy("bet", "table", tb.id);
  const betable = !!tb && !!c && !!stakeRaw && canAfford && bankCovers && !betBusy;
  if ($("btnBet")) { $("btnBet").disabled = !betable; $("btnBet").classList.toggle("pulse", betable && signedIn); $("btnBet").textContent = betBusy ? confirmingLabel() : window.t("roul.placeBet", "Place bet"); }
  // hint (only meaningful once a table is open)
  let hint = "";
  if (signedIn && bg.active != null) {
    if (!tb && !lastTable?.exists) hint = dapp.whereIs("table", bg.active, (bg.tableRec(bg.active) || {}).ts);
    else if (lastTable && lastTable.closed) hint = window.t("roul.hintClosed", "Table #{id} is closed.", { id: bg.active });
    else if (!c) hint = window.t("roul.hintPickNumbers", "Tap numbers or a bet region on the table to build your bet — you can bet at your own table too.");
    else if (!stakeRaw) hint = window.t("roul.hintEnterStake", "Enter a stake (NADO), then Place bet.");
    else if (dapp.exec < stakeRaw) hint = window.t("roul.hintNotEnough", "Not enough NADO — your bet stakes {stake} but your exec balance is {bal}. Deposit at least {need} more below.", { stake: rawToNado(stakeRaw), bal: rawToNado(dapp.exec), need: rawToNado(stakeRaw - dapp.exec) });
    else if (tb && !bankCovers) hint = window.t("roul.hintCantCover", "This table's bankroll can't cover a {mult}× win (free: {free} NADO). Lower your stake, widen your bet, or Top up the bankroll.", { mult: M, free: rawToNado(BigInt(tb.pool) - BigInt(tb.committed)) });
  }
  const jh = $("joinHint"); if (jh) { jh.textContent = hint; jh.classList.toggle("hidden", !hint); }
  syncStakeSlider();   // keep the max-bet slider in step with the selection + live free cover
  // "Your tables" — never hide a placed bet/table; mark pending until it lands (SDK builds/dedups the chips)
  bg.recent($("recent"), selectTable, (x) => {
    if (!lastSto) return;
    const tb = tableFrom(lastSto, x.id);
    if (!tb.exists) return;
    if (tb.closed) return window.t("roul.tagFinished", "finished ✓");
    const mySeats = seatsOfTable(lastSto, x.id).filter((st) => st.addr === dapp.me);
    if (mySeats.some((st) => !st.settled && st.ready && st.win)) return window.t("roul.tagWin", "💰 win to collect");
    if (mySeats.some((st) => st.pending)) return window.t("roul.tagSpinsSoon", "your bet spins soon");
    return window.t("roul.tagLive", "live");
  });
  renderActive();
}
function renderActive() {
  if (bg.active == null) return;
  const tb = lastTable || {}, T = bg.tableRec(bg.active) || {};
  const iAmBank = tb.bank === dapp.me, mySeats = lastSeats.filter((s) => s.addr === dapp.me);
  $("gameId").textContent = "#" + bg.active;
  shareInvite("table", bg.active, window.t("roul.shareText", "Bet at my roulette table #{id} on NADO:", { id: bg.active }), 180);
  $("gBank").textContent = tb.exists ? (disp(tb.bank) + (iAmBank ? window.t("roul.thatsYou", " — that's you (you're the house here)") : "")) : (T.bankroll ? window.t("roul.opening", "you (opening…)") : "—");
  $("gBankroll").textContent = tb.exists ? rawToNado(tb.pool) + " NADO" : (T.bankroll ? rawToNado(T.bankroll) + " NADO" : "—");
  $("gCover").textContent = tb.exists ? window.t("roul.nadoFree", "{v} NADO free", { v: rawToNado(BigInt(tb.pool) - BigInt(tb.committed)) }) : "—";
  // status
  let phaseTxt = dapp.whereIs("table", bg.active, T.ts);
  if (tb.exists) {
    if (tb.closed) phaseTxt = window.t("roul.tableClosedStatus", "table closed");
    else phaseTxt = window.t("roul.spinningStatus", "🟢 spinning every {every} — next spin in {next} · {n} {seat}", { every: blocksToTime(ROUND), next: (tb.roundEndsIn != null ? blocksToTime(tb.roundEndsIn) : "…"), n: tb.seatCount, seat: (tb.seatCount === 1 ? window.t("roul.seatOne", "seat") : window.t("roul.seatMany", "seats")) });
  }
  $("gStatus").textContent = phaseTxt;
  $("btnReopen").classList.toggle("hidden", !(!tb.exists && T.bankroll && T.ts && Date.now() - T.ts > 120000));
  // wheel: show the most recent resolvable result at this table (settled or client-computed), else spinning/idle
  const top = lastSeats.find((s) => s.result != null);   // lastSeats is newest-first, so first-with-result is newest
  const wheel = $("wheel"), anyPending = lastSeats.some((s) => s.pending);
  if (top) { const n = top.result; wheel.className = "wheel " + colorOf(n); wheel.textContent = n; $("result").textContent = window.t("roul.lastSpin", "Last spin: {color} {n}", { color: colorName(n), n }); }
  else if (anyPending) { wheel.className = "wheel spin"; wheel.textContent = "?"; $("result").textContent = window.t("roul.bettingOpen", "Betting open — the wheel spins soon"); }
  else { wheel.className = "wheel"; wheel.textContent = "?"; $("result").textContent = tb.exists && !tb.closed ? window.t("roul.placeBets", "Place your bets!") : "…"; }
  // seats
  const seatRow = (s) => {
    const youTag = s.addr === dapp.me ? '<b style="color:var(--accent2)">' + window.t("roul.you", "you") + "</b> " : "";
    const pips = s.covered.slice(0, 6).map((n) => '<span class="pip ' + colorOf(n) + '">' + n + "</span>").join("") + (s.covered.length > 6 ? " +" + (s.covered.length - 6) : "");
    let tag = "";
    if (s.settled) tag = s.win ? '<span class="b ok">' + window.t("roul.won", "won {v}", { v: rawToNado(BigInt(s.stake) * BigInt(s.mult)) }) + "</span>" : '<span class="b dimb">' + window.t("roul.noWin", "no win ({n})", { n: s.result }) + "</span>";
    else if (s.ready) tag = s.win ? '<span class="b pend">' + window.t("roul.wonCollect", "won {v} — collect", { v: rawToNado(BigInt(s.stake) * BigInt(s.mult)) }) + "</span>" : '<span class="b dimb">' + window.t("roul.lost", "lost ({n})", { n: (s.result != null ? s.result : "?") }) + "</span>";
    else tag = '<span class="b pend">' + window.t("roul.spinsInTag", "spins in {t}", { t: (s.spinsIn != null ? blocksToTime(s.spinsIn) : "…") }) + "</span>";
    return '<div class="seat">' + youTag + disp(s.addr) + ' · <span class="mono">' + rawToNado(s.stake) + "</span> " + window.t("roul.on", "on") + " " + pips + " <span class='dim'>(" + s.mult + "×)</span> " + tag + "</div>";
  };
  // render only a capped slice — a busy table accrues unboundedly many seats over its life
  $("seats").innerHTML = lastSeats.length ? lastSeats.slice(0, seatsN).map(seatRow).join("") : '<span class="dim">' + window.t("roul.noSeats", "No seats yet — be the first to bet.") + "</span>";
  const bms = $("btnMoreSeats");
  if (bms) {
    bms.classList.toggle("hidden", lastSeats.length <= seatsN);
    if (lastSeats.length > seatsN) bms.textContent = window.t("roul.showMoreN", "Show more ({n} more)", { n: lastSeats.length - seatsN });
  }
  // my collect actions
  const wrap = $("myActions"); wrap.innerHTML = "";
  for (const s of mySeats) {
    if (s.settled || !s.ready) continue;
    const b = document.createElement("button"); b.className = "primary"; b.style.flex = "1 1 auto";
    b.textContent = s.win ? window.t("roul.collectSeat", "💰 Collect {v} (seat #{g})", { v: rawToNado(BigInt(s.stake) * BigInt(s.mult)), g: s.g }) : window.t("roul.closeOutSeat", "Close out seat #{g}", { g: s.g });
    b.onclick = () => settleSeat(s.g); if (s.win || iAmBank) wrap.appendChild(b);
  }
  // bank controls
  $("btnClose").classList.toggle("hidden", !(iAmBank && tb.exists && !tb.closed && tb.settledCount >= tb.seatCount));
  $("btnClose").textContent = tb.seatCount === 0 ? window.t("roul.cancelReclaim", "Cancel — reclaim bankroll") : window.t("roul.closeReclaim", "Close table — reclaim {v}", { v: rawToNado(tb.pool) });
  $("fundRow").classList.toggle("hidden", !(iAmBank && tb.exists && !tb.closed));
}

// ---- boot ----------------------------------------------------------------------------------------
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.table != null) bg.active = pend.table;
  dapp.showReturn(pend, ok, err);
});
async function boot() {
  try { await dapp.init(); } catch (e) { alertBar(window.t("roul.cryptoFail", "Crypto bundle failed to load — reload.")); return; }
  wireUI(); loadQR(); orderCards(["activeGame","lobby","play","practice","bankcard","walletcard","bankroll","scoreboard"]);

// ONE mode picker, from the SDK — the same control in every game. Practice used to be a card parked
// below the staked game with no way to switch to it; now it is a mode you choose, and ?mode=practice
// links straight to it.
const modes = installModes(dapp, {
  modes: [
    { key: "play", icon: "🎡", label: window.t("sdk.modePlay", "Play for stakes"),
      hint: window.t("sdk.modePlayHint", "Real NADO on the execution layer."), cards: ["activeGame", "lobby", "play", "bankcard", "scoreboard"] },
    { key: "practice", icon: "🤖", label: window.t("sdk.modePractice", "Practice"),
      badge: window.t("sdk.free", "free"),
      hint: window.t("sdk.modePracticeHint", "Play the computer in your browser — nothing on-chain."),
      cards: ["practice"] },
  ],
});
// mode gating layers OVER the game's own render, which gates cards by sign-in/table state
const _render0 = render;
render = function () { _render0.apply(this, arguments); modes.apply(); };
modes.apply();
  const q = new URLSearchParams(location.search).get("table");
  if (q) { $("joinId").value = q; if (bg.active == null) bg.active = parseInt(q, 10); }
  paintTable(); render(); refreshActive();
  setInterval(refreshActive, 3000);
}
boot();

// ---- PRACTICE MODE (free, fully in-browser — play chips, local RNG, nothing on-chain) -------------------
// Same payout as the contract: a win returns stake × floor(36 ÷ numbers-covered) (see seatsOfTable's
// `mult` and boardFrom's net). Math.random is fine here because nothing is at stake.
const prac = new Practice("roulette");
let pracSel = new Set(), pracHist = [];
function pracBuildGrid() {
  const grid = $("pGrid"); if (!grid || grid.dataset.built) return; grid.dataset.built = "1";
  let html = "";
  for (let n = 0; n < PN; n++) html += '<button class="cell ' + colorOf(n) + '" data-pn="' + n + '" style="height:30px;font-size:12px">' + n + "</button>";
  grid.innerHTML = html;
  grid.querySelectorAll("[data-pn]").forEach((b) => b.onclick = () => {
    const n = parseInt(b.dataset.pn, 10);
    if (pracSel.has(n)) pracSel.delete(n); else if (pracSel.size < MAXSLOTS) pracSel.add(n);
    pracRender();
  });
}
function pracRender() {
  prac.strip($("pStrip"), { chips: true, onReset: pracRender });
  document.querySelectorAll("#pGrid [data-pn]").forEach((b) => b.classList.toggle("sel", pracSel.has(parseInt(b.dataset.pn, 10))));
  const c = pracSel.size, m = c ? Math.floor(36 / c) : 0;
  $("pInfo").innerHTML = c
    ? window.t("roul.covering", "Covering <b>{c}</b> {nWord} · pays <b>{m}×</b>", { c, nWord: c > 1 ? window.t("roul.numbersWord", "numbers") : window.t("roul.numberWord", "number"), m })
    : '<span class="dim">' + window.t("roul.tapToBuild", "Tap numbers or a bet region on the table to build your bet.") + "</span>";
  $("pHist").innerHTML = pracHist.slice(0, 10).map((h) =>
    '<span class="pip ' + colorOf(h.n) + '"' + (h.win ? ' style="box-shadow:0 0 0 2px var(--accent2)"' : "") + ">" + h.n + "</span>").join("");
}
function pracSpin() {
  const bet = parseInt($("pStake").value, 10) || 0;
  if (!pracSel.size) return notify(window.t("roul.pickNumber", "Pick at least one number on the table to bet on."));
  if (!prac.canBet(bet, notify)) return;
  const n = Math.floor(Math.random() * PN);                       // 0..36, same wheel as the chain's mod 37
  const win = pracSel.has(n), mult = Math.floor(36 / pracSel.size);   // contract payout: stake × floor(36/covered)
  const net = win ? bet * (mult - 1) : -bet;
  prac.addChips(net);
  pracHist.unshift({ n, win });
  document.querySelectorAll("#pGrid [data-pn]").forEach((b) => { b.style.outline = ""; b.style.boxShadow = ""; });
  const cell = document.querySelector('#pGrid [data-pn="' + n + '"]');
  if (cell) { cell.style.outline = "3px solid var(--accent2)"; cell.style.boxShadow = "0 0 10px rgba(0,201,167,.7)"; }
  $("pResult").innerHTML = win
    ? '<span style="color:var(--accent2)">🎉 ' + window.t("sdk.prRlWin", "Ball landed on {n} ({color}) — WIN +{net} chips ({m}×)!", { n, color: colorName(n), net, m: mult }) + "</span>"
    : '<span style="color:var(--danger)">' + window.t("sdk.prRlLose", "Ball landed on {n} ({color}) — lost {net} chips.", { n, color: colorName(n), net: -net }) + "</span>";
  pracRender();
}
if ($("pSpin")) {
  pracBuildGrid();
  $("pSpin").onclick = pracSpin;
  $("pClear").onclick = () => { pracSel = new Set(); pracRender(); };
  pracRender();
}
