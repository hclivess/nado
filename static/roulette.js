// roulette.js — NADO Roulette: a provably-fair, peer-banked, MULTIPLAYER European (single-zero) roulette on the
// execution layer, built on the shared game SDK (nadodapp.js). A table is one shared wheel that SPINS ITSELF
// every ROUND blocks — no bank reveal, no secrets, no "spin" button ever. A BANK opens a table with a bankroll;
// bettors take independent seats any time, each staking on a set of covered numbers. A bet binds to the round it
// lands in, whose result is fixed by FINALIZED L1 block hashes nobody can predict while betting is open:
//   result = HASH( BLOCKHASH(sh) + BLOCKHASH(sh+1) + tableId ) % 37
// Once the settle block is final, ANYONE can settle a seat (it pays the bettor) — a stalling bank can't rob
// anyone. A win pays the true 36/count; losing stakes fold into the bankroll. Ordinary upgradable stackvm
// contract, no game-specific API.
import { NadoDapp, rawToNado, nadoToRaw, randId, _m, $, base, gate, canPay, hoist, orderCards, chainResult, blocksToTime,
         lsLoad as load, lsSave as save, lsPrune, wireWallet, stickyInputs, renderWallet, renderScore, scoreBump, scoreSort,
         recentChips, statusLabel, tablesOf as allTables, readTable,
         loadQR, drawQR, resolveAliases, disp, share, shareInvite } from "./nadodapp.js";

const CID = "e04c329d0b57c9ea40493e957adfee9c";
const GICON = '<svg style="vertical-align:-3px" viewBox="0 0 48 48" width="16" height="16" aria-hidden="true">     <circle cx="24" cy="24" r="16" fill="#0b0f14" stroke="#b5810f" stroke-width="2"/>     <g stroke="#0b0f14" stroke-width=".6">       <path d="M24 24 L24 8 A16 16 0 0 1 35.3 12.7 Z" fill="#d0362b"/>       <path d="M24 24 L35.3 12.7 A16 16 0 0 1 40 24 Z" fill="#20272f"/>       <path d="M24 24 L40 24 A16 16 0 0 1 35.3 35.3 Z" fill="#1f8f4e"/>       <path d="M24 24 L35.3 35.3 A16 16 0 0 1 24 40 Z" fill="#d0362b"/>       <path d="M24 24 L24 40 A16 16 0 0 1 12.7 35.3 Z" fill="#20272f"/>       <path d="M24 24 L12.7 35.3 A16 16 0 0 1 8 24 Z" fill="#d0362b"/>       <path d="M24 24 L8 24 A16 16 0 0 1 12.7 12.7 Z" fill="#20272f"/>       <path d="M24 24 L12.7 12.7 A16 16 0 0 1 24 8 Z" fill="#20272f"/></g>     <circle cx="24" cy="24" r="6" fill="#e3b341" stroke="#b5810f" stroke-width="1.4"/>     <circle cx="24" cy="24" r="2.2" fill="#0b0f14"/>     <circle cx="24" cy="10.5" r="2" fill="#fff"/></svg>';
const PN = 37, MAXSLOTS = 18, BLOCK_SECS = 6, ROUND = 20;   // ROUND must match the contract
const dapp = new NadoDapp({ cid: CID, app: "Roulette" });
const RED = new Set([1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]);
const colorOf = (n) => n === 0 ? "green" : (RED.has(n) ? "red" : "black");

const LS_T = "nado_roul_tables", LS_S = "nado_roul_seats";
let lastSto = null;
let activeTable = null, lastTable = null, lastSeats = [], selected = new Set();
let knownTables = new Set(), knownSeats = new Set();

function pruneAndTrack(sto) {
  knownTables = lsPrune(LS_T, allTables(sto));
  knownSeats = lsPrune(LS_S, Object.keys(_m(sto, "gg")));
}
function reopenTable() {   // retry an open that never landed (same id is still fresh on-chain)
  const T = load(LS_T)[activeTable]; if (!T || !T.bankroll) return;
  const raw = BigInt(T.bankroll);
  if (!canPay(dapp, raw, "Re-opening this table")) return;
  openTable(activeTable, raw);
}


// ---- reads (roulette-specific storage schema) ----------------------------------------------------
function coveredOf(sto, g) { const cov = _m(sto, "cov"), out = [], b = Number(g) * PN; for (let n = 0; n < PN; n++) if (cov[String(b + n)]) out.push(n); return out; }
const tableFrom = (sto, t) => readTable(sto, t, dapp.cursor, ROUND);
function seatsOfTable(sto, t) {
  t = String(t); const gg = _m(sto, "gg"), cur = dapp.cursor, out = [];
  for (const g of Object.keys(gg)) if (String(gg[g]) === t) {
    const covered = coveredOf(sto, g), cn = _m(sto, "gc")[g] || covered.length || 1;
    const gh = _m(sto, "gh")[g] || 0, settled = !!_m(sto, "gd")[g];
    const s = { g: Number(g), addr: _m(sto, "ga")[g], stake: _m(sto, "gs")[g] || 0, count: cn, covered,
      gh, settled, mult: Math.floor(36 / cn) };
    if (settled) { const gr = _m(sto, "gr")[g] || 0; s.result = gr ? gr - 1 : null; s.win = !!_m(sto, "gw")[g]; }
    else if (cur != null && cur >= gh + 1) { s.result = chainResult(dapp.bh(gh), dapp.bh(gh + 1), t, PN); s.ready = true; s.win = s.result != null ? covered.includes(s.result) : null; }
    else { s.pending = true; s.spinsIn = cur != null ? gh - cur : null; }   // waiting for its round to end
    out.push(s);
  }
  return out.sort((a, b) => (b.gh - a.gh) || (b.g - a.g));   // newest FIRST by bound block height (seat ids are random, not time-ordered)
}
async function fetchTable(t) { const sto = await dapp.storage(); return sto ? tableFrom(sto, t) : null; }

// ---- bet maths -----------------------------------------------------------------------------------
const betCount = () => selected.size;
const betMult = () => { const c = betCount(); return c >= 1 && c <= MAXSLOTS ? Math.floor(36 / c) : 0; };
const betSlots = () => { const a = [...selected].sort((x, y) => x - y); const rep = a.length ? a[0] : 0; while (a.length < MAXSLOTS) a.push(rep); return a; };

// ---- actions -------------------------------------------------------------------------------------
function openTable(t, bankrollRaw) {
  const T = load(LS_T); T[t] = { bankroll: bankrollRaw.toString(), ts: Date.now() }; save(LS_T, T);
  activeTable = t; $("joinId").value = String(t);
  render();
  dapp.call("open", [t], bankrollRaw, "bank roulette table #" + t + " · " + rawToNado(bankrollRaw) + " NADO", { table: t, phase: "open" });
}
async function newTable() {
  const raw = nadoToRaw($("bankrollAmt").value);
  if (!raw) { $("status").textContent = "Enter a bankroll (NADO) to bank a table."; return; }
  await dapp.refresh();
  if (!canPay(dapp, raw, "Banking this table")) return;
  openTable(randId(), raw);
}
async function doBet() {
  const t = activeTable;
  if (!t) { $("status").textContent = "Pick a table first."; return; }
  if (!betCount()) { $("status").textContent = "Pick at least one number on the table to bet on."; return; }
  const stake = nadoToRaw($("stakeAmt").value);
  if (!stake) { $("status").textContent = "Enter a stake (NADO)."; return; }
  const tb = await fetchTable(t);
  if (!tb || !tb.exists) { $("status").textContent = dapp.whereIs("table", t); return; }
  if (tb.closed) { $("status").textContent = "That table is closed."; return; }
  await dapp.refresh();
  if (!canPay(dapp, stake, "This bet")) { render(); return; }
  const need = stake * BigInt(betMult() - 1);
  if (BigInt(tb.bankroll) - BigInt(tb.committed) < need) { $("status").textContent = "This table can't cover a " + betMult() + "× win right now (bankroll left: " + rawToNado(BigInt(tb.bankroll) - BigInt(tb.committed)) + " NADO). Lower your stake or widen your bet."; render(); return; }
  const g = randId(), slots = betSlots(), S = load(LS_S);
  S[g] = { table: t, stake: stake.toString(), numbers: [...selected], ts: Date.now() }; save(LS_S, S);
  render();
  dapp.call("bet", [g, t, ...slots], stake, "bet " + rawToNado(stake) + " NADO on " + selected.size + " number(s) · table #" + t, { table: t, seat: g, phase: "bet" });
}
function fundTable() {
  const raw = nadoToRaw($("fundAmt").value);
  if (!raw) { $("status").textContent = "Enter an amount to add to this table's bankroll."; return; }
  if (!canPay(dapp, raw, "The top-up")) return;
  dapp.call("fund", [activeTable], raw, "top up table #" + activeTable + " bankroll · " + rawToNado(raw) + " NADO", { table: activeTable, phase: "fund" });
}
const settleSeat = (g) => dapp.call("settle", [g], null, "collect seat #" + g, { table: activeTable, phase: "settle" });
// AUTO-COLLECT a resolved WINNING seat (shared SDK tick — opt-out slider, one-per-refresh, autoTried dedup)
function maybeAutoSettle() {
  if (!lastTable || !lastTable.exists) return;
  dapp.autoCollect(lastSeats.filter((s) => s.addr === dapp.me && !s.settled && s.ready && s.win), (s) => settleSeat(s.g));
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
      // fetch the block hashes needed to resolve every finished-but-unsettled seat at this table
      const cur = dapp.cursor, need = [];
      for (const g of Object.keys(_m(sto, "gg"))) if (String(_m(sto, "gg")[g]) === String(activeTable)) {
        const gh = _m(sto, "gh")[g] || 0; if (!_m(sto, "gd")[g] && cur != null && cur >= gh + 1) { need.push(gh, gh + 1); }
      }
      if (need.length) await dapp.blockHashes(need, { fast: true });   // roulette spins: PUBLIC + on-chain-validated -> provisional (fast) is safe; results show ~one block after the roll instead of waiting out finality
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
    const cn = _m(sto, "gc")[g] || 1, stake = _m(sto, "gs")[g] || 0, win = !!_m(sto, "gw")[g];
    const net = win ? stake * (Math.floor(36 / cn) - 1) : -stake;
    scoreBump(stats, _m(sto, "ga")[g], net); scoreBump(stats, bank, -net);
  }
  return scoreSort(stats);
}
const renderScoreboard = (board) => renderScore($("scoreList"), board, dapp.me, "No settled bets yet — be the first on the board.");
function renderLobby(sto) {
  const el = $("lobbyList"); if (!el) return;
  const tables = allTables(sto).map((t) => tableFrom(sto, t)).filter((t) => t.exists && !t.closed);
  tables.sort((a, b) => b.seatCount - a.seatCount || b.id - a.id);
  const shown = tables.slice(0, 24);
  el.innerHTML = shown.length ? shown.map((t) => {
    const left = t.roundEndsIn != null ? " · next spin " + blocksToTime(t.roundEndsIn) : "";
    return '<button class="chip betting" data-t="' + t.id + '">🟢 #' + t.id + " · bank " + rawToNado(t.bankroll) + " · " + t.seatCount + " seat" + (t.seatCount === 1 ? "" : "s") + left + "</button>";
  }).join(" ") : '<span class="dim">No tables yet — bank one below.</span>';
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => selectTable(parseInt(b.dataset.t, 10)));
}
function selectTable(id) {
  activeTable = id; $("joinId").value = String(id);
  $("status").textContent = "Table #" + id + " — build your bet on the layout and set a stake, then Place bet.";
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
  const free = BigInt(tb.bankroll) - BigInt(tb.committed);
  if (free <= 0n) return null;
  return free / BigInt(M - 1);
}
const syncStakeSlider = () => dapp.syncStakeSlider(maxBetRaw());   // shared SDK slider
function wireUI() {
  wireWallet(dapp);
  stickyInputs(dapp, ['stakeAmt', 'bankrollAmt', 'fundAmt', 'bankAmt', 'betAmt']);   // typed amounts persist across turns
  $("btnNewTable").onclick = newTable;
  $("btnBet").onclick = doBet;
  $("btnGoTable").onclick = () => { const id = parseInt($("joinId").value, 10); if (id) selectTable(id); else $("status").textContent = "Enter a table ID, or pick one from the lobby."; };
  $("stakeAmt").oninput = () => render();
  dapp.wireStakeSlider(maxBetRaw, () => render());
  $("btnClose").onclick = closeTable;
  dapp.wireAutoCollect();
  $("btnFund").onclick = fundTable;
  $("btnReopen").onclick = reopenTable;
  $("btnShare").onclick = () => share(base() + "/?table=" + activeTable, "Bet at my roulette table #" + activeTable + " on NADO:", $("btnShare"));
  buildTable();
}
function render() {
  const signedIn = renderWallet(dapp);
  gate({ play: signedIn, bankcard: signedIn, bankroll: signedIn, activeGame: activeTable != null });
  const c = betCount(), M = betMult(), stakeRaw = nadoToRaw($("stakeAmt").value);
  if ($("betInfo")) $("betInfo").innerHTML = c
    ? "Covering <b>" + c + "</b> number" + (c > 1 ? "s" : "") + " · pays <b>" + M + "×</b>" + (stakeRaw ? " · win returns <b>" + rawToNado(stakeRaw * BigInt(M)) + " NADO</b> (net +" + rawToNado(stakeRaw * BigInt(M - 1)) + ")" : "")
    : '<span class="dim">Tap numbers or a bet region on the table to build your bet.</span>';
  const tb = (activeTable != null && lastTable && lastTable.exists && !lastTable.closed) ? lastTable : null;
  const canAfford = !(signedIn && stakeRaw && dapp.exec < stakeRaw);
  const need = (stakeRaw && M) ? stakeRaw * BigInt(M - 1) : null;
  const bankCovers = !(tb && need != null && (BigInt(tb.bankroll) - BigInt(tb.committed)) < need);
  const betable = !!tb && !!c && !!stakeRaw && canAfford && bankCovers;
  if ($("btnBet")) { $("btnBet").disabled = !betable; $("btnBet").classList.toggle("pulse", betable && signedIn); }
  // hint (only meaningful once a table is open)
  let hint = "";
  if (signedIn && activeTable != null) {
    if (!tb && !lastTable?.exists) hint = dapp.whereIs("table", activeTable, (load(LS_T)[activeTable] || {}).ts);
    else if (lastTable && lastTable.closed) hint = "Table #" + activeTable + " is closed.";
    else if (!c) hint = "Tap numbers or a bet region on the table to build your bet — you can bet at your own table too.";
    else if (!stakeRaw) hint = "Enter a stake (NADO), then Place bet.";
    else if (dapp.exec < stakeRaw) hint = "Not enough NADO — your bet stakes " + rawToNado(stakeRaw) + " but your exec balance is " + rawToNado(dapp.exec) + ". Deposit at least " + rawToNado(stakeRaw - dapp.exec) + " more below.";
    else if (tb && !bankCovers) hint = "This table's bankroll can't cover a " + M + "× win (free: " + rawToNado(BigInt(tb.bankroll) - BigInt(tb.committed)) + " NADO). Lower your stake, widen your bet, or Top up the bankroll.";
  }
  const jh = $("joinHint"); if (jh) { jh.textContent = hint; jh.classList.toggle("hidden", !hint); }
  syncStakeSlider();   // keep the max-bet slider in step with the selection + live free cover
  // "Your tables" — never hide a placed bet/table; mark pending until it lands
  const T = load(LS_T), S = load(LS_S), mine = [];
  for (const t of Object.keys(T)) mine.push({ id: +t, role: "bank", ts: T[t].ts });
  for (const g of Object.keys(S)) mine.push({ id: S[g].table, seat: g, role: "bet", ts: S[g].ts });
  mine.sort((a, b) => b.ts - a.ts); const seen = new Set();
  const shown = mine.filter((x) => {
    x.live = x.role === "bank" ? knownTables.has(String(x.id)) : knownSeats.has(String(x.seat));
    x.icon = x.role === "bank" ? "🏦" : "🎯";
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
  shareInvite("table", activeTable, "Bet at my roulette table #" + activeTable + " on NADO:", 180);
  $("gBank").textContent = tb.exists ? (disp(tb.bank) + (iAmBank ? " — that's you (you're the house here)" : "")) : (T.bankroll ? "you (opening…)" : "—");
  $("gBankroll").textContent = tb.exists ? rawToNado(tb.bankroll) + " NADO" : (T.bankroll ? rawToNado(T.bankroll) + " NADO" : "—");
  $("gCover").textContent = tb.exists ? rawToNado(BigInt(tb.bankroll) - BigInt(tb.committed)) + " NADO free" : "—";
  // status
  let phaseTxt = dapp.whereIs("table", activeTable, T.ts);
  if (tb.exists) {
    if (tb.closed) phaseTxt = "table closed";
    else phaseTxt = "🟢 spinning every " + blocksToTime(ROUND) + " — next spin in " + (tb.roundEndsIn != null ? blocksToTime(tb.roundEndsIn) : "…") + " · " + tb.seatCount + " seat" + (tb.seatCount === 1 ? "" : "s");
  }
  $("gStatus").textContent = phaseTxt;
  $("btnReopen").classList.toggle("hidden", !(!tb.exists && T.bankroll && T.ts && Date.now() - T.ts > 120000));
  // wheel: show the most recent resolvable result at this table (settled or client-computed), else spinning/idle
  const resolved = lastSeats.filter((s) => s.result != null).sort((a, b) => b.gh - a.gh);
  const wheel = $("wheel"), anyPending = lastSeats.some((s) => s.pending);
  if (resolved.length) { const n = resolved[0].result; wheel.className = "wheel " + colorOf(n); wheel.textContent = n; $("result").textContent = "Last spin: " + colorOf(n).toUpperCase() + " " + n; }
  else if (anyPending) { wheel.className = "wheel spin"; wheel.textContent = "?"; $("result").textContent = "Betting open — the wheel spins soon"; }
  else { wheel.className = "wheel"; wheel.textContent = "?"; $("result").textContent = tb.exists && !tb.closed ? "Place your bets!" : "…"; }
  // seats
  const seatRow = (s) => {
    const youTag = s.addr === dapp.me ? '<b style="color:var(--accent2)">you</b> ' : "";
    const pips = s.covered.slice(0, 6).map((n) => '<span class="pip ' + colorOf(n) + '">' + n + "</span>").join("") + (s.covered.length > 6 ? " +" + (s.covered.length - 6) : "");
    let tag = "";
    if (s.settled) tag = s.win ? '<span class="b ok">won ' + rawToNado(BigInt(s.stake) * BigInt(s.mult)) + "</span>" : '<span class="b dimb">no win (' + s.result + ")</span>";
    else if (s.ready) tag = s.win ? '<span class="b pend">won ' + rawToNado(BigInt(s.stake) * BigInt(s.mult)) + " — collect</span>" : '<span class="b dimb">lost (' + (s.result != null ? s.result : "?") + ")</span>";
    else tag = '<span class="b pend">spins in ' + (s.spinsIn != null ? blocksToTime(s.spinsIn) : "…") + "</span>";
    return '<div class="seat">' + youTag + disp(s.addr) + ' · <span class="mono">' + rawToNado(s.stake) + "</span> on " + pips + " <span class='dim'>(" + s.mult + "×)</span> " + tag + "</div>";
  };
  $("seats").innerHTML = lastSeats.length ? lastSeats.map(seatRow).join("") : '<span class="dim">No seats yet — be the first to bet.</span>';
  // my collect actions
  const wrap = $("myActions"); wrap.innerHTML = "";
  for (const s of mySeats) {
    if (s.settled || !s.ready) continue;
    const b = document.createElement("button"); b.className = "primary"; b.style.flex = "1 1 auto";
    b.textContent = s.win ? "💰 Collect " + rawToNado(BigInt(s.stake) * BigInt(s.mult)) + " (seat #" + s.g + ")" : "Close out seat #" + s.g;
    b.onclick = () => settleSeat(s.g); if (s.win || iAmBank) wrap.appendChild(b);
  }
  // bank controls
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
  wireUI(); loadQR(); orderCards(["activeGame","lobby","play","bankcard","walletcard","bankroll","scoreboard"]);
  const q = new URLSearchParams(location.search).get("table");
  if (q) { $("joinId").value = q; if (activeTable == null) activeTable = parseInt(q, 10); }
  paintTable(); render(); refreshActive();
  setInterval(refreshActive, 3000);
}
boot();
