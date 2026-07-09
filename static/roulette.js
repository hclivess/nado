// roulette.js — NADO Roulette: a provably-fair, peer-banked, MULTIPLAYER European (single-zero) roulette on
// the execution layer, built on the shared game SDK (nadodapp.js). A table is one shared wheel: a BANK opens
// it with a bankroll + committed secret; during a betting WINDOW any number of BETTORS take a seat by staking
// a bet on a set of table numbers (one signature per bet — no per-player secret). When the window closes the
// bank reveals once and ONE shared spin  result = HASH(bankSecret + tableId) % 37  decides every seat. A win
// pays the true 36/count; losers' stakes go to the bank. Each seat settles independently; if the bank stalls,
// every seat force-claims its MAX win after the deadline. Ordinary upgradable stackvm contract, no game API.
import { NadoDapp, rawToNado, nadoToRaw, randId, randSecret, commitHashOf, blake2bHash, _m, $, base,
         loadQR, drawQR, resolveAliases, disp, share } from "./nadodapp.js";

const CID = "186ebadb975794e2ed7eeb1c7b5115a5";
const PN = 37, MAXSLOTS = 18, SENTINEL = 99, BLOCK_SECS = 6;
const dapp = new NadoDapp({ cid: CID, app: "Roulette" });
const RED = new Set([1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]);
const colorOf = (n) => n === 0 ? "green" : (RED.has(n) ? "red" : "black");

const LS_T = "nado_roul_tables", LS_S = "nado_roul_seats";
const load = (k) => { try { return JSON.parse(localStorage.getItem(k) || "{}"); } catch { return {}; } };
const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} };
let activeTable = null, lastTable = null, lastSeats = [], selected = new Set();

// shared spin — MUST match the contract: HASH(bankSecret + tableId) % 37
const spinResult = (secret, t) => Number(BigInt("0x" + blake2bHash((BigInt(secret) + BigInt(t)).toString())) % BigInt(PN));
const blocksToTime = (b) => { b = Math.max(0, b) * BLOCK_SECS; const m = Math.floor(b / 60), s = b % 60; return m + ":" + String(s).padStart(2, "0"); };

// ---- reads (roulette-specific storage schema) ----------------------------------------------------
const allTables = (sto) => Object.keys(_m(sto, "ta"));
function coveredOf(sto, g) { const cov = _m(sto, "cov"), out = [], b = Number(g) * PN; for (let n = 0; n < PN; n++) if (cov[String(b + n)]) out.push(n); return out; }
function tablePhase(tb) {
  if (tb.closed) return "done";
  if (tb.revealed) return "revealed";
  const cur = dapp.cursor;
  if (cur == null || cur <= tb.joinDeadline) return "betting";
  if (cur <= tb.revealDeadline) return "spinning";
  return "forfeit";
}
function tableFrom(sto, t) {
  t = String(t); const bank = _m(sto, "ta")[t];
  if (!bank) return { exists: false };
  const tb = { exists: true, id: Number(t), bank, bankroll: _m(sto, "tk")[t] || 0, pool: _m(sto, "tp")[t] || 0,
    committed: _m(sto, "tc")[t] || 0, revealed: !!_m(sto, "tr")[t], secret: _m(sto, "ts")[t] || null,
    joinDeadline: _m(sto, "tj")[t] || 0, revealDeadline: _m(sto, "tv")[t] || 0,
    seatCount: _m(sto, "tn")[t] || 0, settledCount: _m(sto, "tx")[t] || 0, closed: !!_m(sto, "tz")[t] };
  tb.result = (tb.revealed && tb.secret != null) ? spinResult(tb.secret, tb.id) : null;
  tb.phase = tablePhase(tb);
  return tb;
}
function seatsOfTable(sto, t) {
  t = String(t); const gg = _m(sto, "gg"), out = [];
  for (const g of Object.keys(gg)) if (String(gg[g]) === t) {
    const covered = coveredOf(sto, g), cn = _m(sto, "gc")[g] || covered.length || 1;
    out.push({ g: Number(g), addr: _m(sto, "ga")[g], stake: _m(sto, "gs")[g] || 0, count: cn, covered, settled: !!_m(sto, "gd")[g], mult: Math.floor(36 / cn) });
  }
  return out.sort((a, b) => a.g - b.g);
}
async function fetchTable(t) { const sto = await dapp.storage(); return sto ? tableFrom(sto, t) : null; }

// ---- bet maths -----------------------------------------------------------------------------------
const betCount = () => selected.size;
const betMult = () => { const c = betCount(); return c >= 1 && c <= MAXSLOTS ? Math.floor(36 / c) : 0; };
const betSlots = () => { const a = [...selected].sort((x, y) => x - y); while (a.length < MAXSLOTS) a.push(SENTINEL); return a; };

// ---- actions -------------------------------------------------------------------------------------
function openTable(t, bankrollRaw) {
  const T = load(LS_T); const secret = (T[t] && T[t].secret) ? T[t].secret : randSecret().toString();
  T[t] = { secret, bankroll: bankrollRaw.toString(), ts: Date.now() }; save(LS_T, T);
  activeTable = t; $("joinId").value = String(t);   // target your own table so you can also bet at it
  render();
  dapp.call("open", [t, commitHashOf(BigInt(secret))], bankrollRaw, "bank roulette table #" + t + " · " + rawToNado(bankrollRaw) + " NADO", { table: t, phase: "open" });
}
function newTable() {
  const raw = nadoToRaw($("bankrollAmt").value);
  if (!raw) { $("status").textContent = "Enter a bankroll (NADO) to bank a table."; return; }
  if (dapp.exec < raw) { $("status").textContent = "Deposit first — your exec balance is " + rawToNado(dapp.exec) + " NADO."; return; }
  openTable(randId(), raw);
}
async function doBet() {
  const t = parseInt($("joinId").value, 10);
  if (!t) { $("status").textContent = "Enter a table ID (or pick one from the lobby)."; return; }
  if (!betCount()) { $("status").textContent = "Pick at least one number on the table to bet on."; return; }
  const stake = nadoToRaw($("stakeAmt").value);
  if (!stake) { $("status").textContent = "Enter a stake (NADO)."; return; }
  const tb = await fetchTable(t);
  if (!tb || !tb.exists) { $("status").textContent = "No such table yet — ask the bank for the ID after they open it."; return; }
  if (tb.phase !== "betting") { $("status").textContent = "Betting is closed on that table (" + tb.phase + ")."; return; }
  await dapp.refresh();
  if (dapp.exec < stake) { $("status").textContent = "You need " + rawToNado(stake) + " NADO in your exec balance (you have " + rawToNado(dapp.exec) + "). Deposit first."; render(); return; }
  const need = stake * BigInt(betMult() - 1);
  if (BigInt(tb.bankroll) - BigInt(tb.committed) < need) { $("status").textContent = "This table can't cover a " + betMult() + "× win right now (bankroll left: " + rawToNado(BigInt(tb.bankroll) - BigInt(tb.committed)) + " NADO). Lower your stake or widen your bet."; render(); return; }
  const g = randId(), slots = betSlots(), S = load(LS_S);
  S[g] = { table: t, stake: stake.toString(), numbers: slots.filter((n) => n < PN), ts: Date.now() }; save(LS_S, S);
  activeTable = t; render();
  dapp.call("bet", [g, t, ...slots], stake, "bet " + rawToNado(stake) + " NADO on " + selected.size + " number(s) · table #" + t, { table: t, seat: g, phase: "bet" });
}
function revealTable() {
  const T = load(LS_T)[activeTable];
  if (!T || !T.secret) { $("status").textContent = "No bank secret for this table on this device."; return; }
  dapp.call("reveal", [activeTable, BigInt(T.secret)], null, "spin the wheel · table #" + activeTable, { table: activeTable, phase: "reveal" });
}
function fundTable() {
  const raw = nadoToRaw($("fundAmt").value);
  if (!raw) { $("status").textContent = "Enter an amount to add to this table's bankroll."; return; }
  if (dapp.exec < raw) { $("status").textContent = "Deposit first — your exec balance is " + rawToNado(dapp.exec) + " NADO."; return; }
  dapp.call("fund", [activeTable], raw, "top up table #" + activeTable + " bankroll · " + rawToNado(raw) + " NADO", { table: activeTable, phase: "fund" });
}
const settleSeat = (g) => dapp.call("settle", [g], null, "collect seat #" + g, { table: activeTable, phase: "settle" });
const claimSeat = (g) => dapp.call("claim", [g], null, "claim seat #" + g + " (bank stalled)", { table: activeTable, phase: "claim" });
const closeTable = () => dapp.call("close", [activeTable], null, "close table #" + activeTable, { table: activeTable, phase: "close" });

async function refreshActive() {
  await dapp.refresh();
  const sto = await dapp.storage();
  if (sto) {
    if (activeTable != null) { lastTable = tableFrom(sto, activeTable); lastSeats = seatsOfTable(sto, activeTable); }
    renderLobby(sto); renderScoreboard(boardFrom(sto));
  }
  await resolveAliases([dapp.me].concat(lastTable ? [lastTable.bank] : []).concat(lastSeats.map((s) => s.addr)));
  render();
}
function boardFrom(sto) {
  const stats = {}, bump = (a, net) => { const x = stats[a] || (stats[a] = { addr: a, wins: 0, losses: 0, games: 0, net: 0 }); x.games++; x.net += net; net >= 0 ? x.wins++ : x.losses++; };
  for (const g of Object.keys(_m(sto, "gd"))) {
    if (!_m(sto, "gd")[g]) continue;
    const t = String(_m(sto, "gg")[g]), tb = tableFrom(sto, t);
    if (!tb.exists || tb.result == null) continue;
    const covered = coveredOf(sto, g), cn = _m(sto, "gc")[g] || 1, stake = _m(sto, "gs")[g] || 0, win = covered.includes(tb.result);
    const net = win ? stake * (Math.floor(36 / cn) - 1) : -stake;
    bump(_m(sto, "ga")[g], net); bump(tb.bank, -net);
  }
  return Object.values(stats).sort((a, b) => (b.net - a.net) || (b.wins - a.wins));
}
async function renderScoreboard(board) {
  const el = $("scoreList"); if (!el) return;
  if (!board.length) { el.innerHTML = '<span class="dim">No finished bets yet — be the first on the board.</span>'; return; }
  const top = board.slice(0, 10); await resolveAliases(top.map((r) => r.addr));
  el.innerHTML = '<table class="score"><thead><tr><th>#</th><th>Player</th><th>W–L</th><th>Net</th></tr></thead><tbody>'
    + top.map((r, i) => { const net = (r.net < 0 ? "-" : "+") + rawToNado(Math.abs(r.net)) + " NADO", you = r.addr === dapp.me;
        return '<tr' + (you ? ' class="me"' : "") + '><td>' + (i + 1) + '</td><td>' + disp(r.addr) + (you ? " (you)" : "") + '</td><td>W' + r.wins + "–L" + r.losses + '</td><td class="' + (r.net >= 0 ? "pos" : "neg") + '">' + net + "</td></tr>"; }).join("") + "</tbody></table>";
}
function renderLobby(sto) {
  const el = $("lobbyList"); if (!el) return;
  const tables = allTables(sto).map((t) => tableFrom(sto, t)).filter((t) => t.exists && !t.closed);
  const rank = { betting: 0, spinning: 1, forfeit: 1, revealed: 2, done: 3 }, tag = { betting: "🟢", spinning: "🌀", revealed: "✓", forfeit: "⚠" };
  tables.sort((a, b) => (rank[a.phase] - rank[b.phase]) || (b.joinDeadline - a.joinDeadline));
  const shown = tables.slice(0, 24);
  el.innerHTML = shown.length ? shown.map((t) => {
    const left = t.phase === "betting" && dapp.cursor != null ? " · " + blocksToTime(t.joinDeadline - dapp.cursor) + " left" : "";
    const verb = t.phase === "betting" ? " · bet" : t.phase === "spinning" ? " · spinning" : t.phase === "forfeit" ? " · claim" : "";
    return '<button class="chip ' + t.phase + '" data-t="' + t.id + '">' + (tag[t.phase] || "") + " #" + t.id + " · bank " + rawToNado(t.bankroll) + " · " + t.seatCount + " seat" + (t.seatCount === 1 ? "" : "s") + left + verb + "</button>";
  }).join(" ") : '<span class="dim">No tables yet — bank one below.</span>';
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => {
    const id = parseInt(b.dataset.t, 10);
    activeTable = id; $("joinId").value = String(id);
    $("status").textContent = "Table #" + id + " selected — build your bet on the layout and set a stake, then Place bet.";
    refreshActive();
    try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {}
  });
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
function wireUI() {
  $("btnSignIn").onclick = () => dapp.signIn();
  $("btnDeposit").onclick = () => { const raw = nadoToRaw($("bankAmt").value); if (!raw) return ($("status").textContent = "Enter an amount to deposit."); if (raw + 1000n > dapp.l1) return ($("status").textContent = "Not enough in your L1 wallet (" + rawToNado(dapp.l1) + " NADO)."); dapp.deposit(raw); };
  $("btnWithdraw").onclick = () => { const raw = nadoToRaw($("bankAmt").value); if (!raw) return ($("status").textContent = "Enter an amount to withdraw."); if (dapp.exec < raw) return ($("status").textContent = "You only have " + rawToNado(dapp.exec) + " NADO in the exec layer."); dapp.withdraw(raw); };
  $("btnNewTable").onclick = newTable;
  $("btnBet").onclick = doBet;
  $("joinId").oninput = () => render();
  $("stakeAmt").oninput = () => render();
  $("btnReveal").onclick = revealTable;
  $("btnClose").onclick = closeTable;
  $("btnFund").onclick = fundTable;
  $("btnShare").onclick = () => share(base() + "/?table=" + activeTable, "Bet at my roulette table #" + activeTable + " on NADO:", $("btnShare"));
  buildTable();
}
function render() {
  const signedIn = !!dapp.me;
  $("btnSignIn").classList.toggle("hidden", signedIn);
  $("who").textContent = signedIn ? disp(dapp.me) : "not signed in";
  $("bal").textContent = rawToNado(dapp.exec) + " NADO";
  $("l1bal").textContent = rawToNado(dapp.l1) + " NADO";
  $("play").classList.toggle("hidden", !signedIn);
  $("bankcard").classList.toggle("hidden", !signedIn);
  $("bankroll").classList.toggle("hidden", !signedIn);
  const c = betCount(), M = betMult(), stakeRaw = nadoToRaw($("stakeAmt").value);
  $("betInfo").innerHTML = c
    ? "Covering <b>" + c + "</b> number" + (c > 1 ? "s" : "") + " · pays <b>" + M + "×</b>" + (stakeRaw ? " · win returns <b>" + rawToNado(stakeRaw * BigInt(M)) + " NADO</b> (net +" + rawToNado(stakeRaw * BigInt(M - 1)) + ")" : "")
    : '<span class="dim">Tap numbers or a bet region on the table to build your bet.</span>';
  const jid = ($("joinId").value || "").trim();
  const tb = (jid && String(activeTable) === jid && lastTable && lastTable.exists) ? lastTable : null;
  const canBetPhase = !tb || tb.phase === "betting";
  const canAfford = !(signedIn && stakeRaw && dapp.exec < stakeRaw);
  const need = (stakeRaw && M) ? stakeRaw * BigInt(M - 1) : null;
  const bankCovers = !(tb && need != null && (BigInt(tb.bankroll) - BigInt(tb.committed)) < need);
  const betable = !!jid && !!c && !!stakeRaw && canBetPhase && canAfford && bankCovers;
  $("btnBet").disabled = !betable;
  $("btnBet").classList.toggle("pulse", betable && signedIn);
  $("btnSignIn").classList.toggle("pulse", !!jid && !!c && !signedIn);
  let hint = "";
  if (jid && c && signedIn && canBetPhase) {
    if (stakeRaw && dapp.exec < stakeRaw) hint = "Not enough NADO — your bet stakes " + rawToNado(stakeRaw) + " but your exec balance is " + rawToNado(dapp.exec) + ". Deposit at least " + rawToNado(stakeRaw - dapp.exec) + " more below.";
    else if (tb && !bankCovers) hint = "This table can't cover a " + M + "× win right now (bankroll left: " + rawToNado(BigInt(tb.bankroll) - BigInt(tb.committed)) + " NADO). Lower your stake or widen your bet.";
  } else if (jid && tb && tb.phase !== "betting") hint = "Betting is closed on table #" + jid + " (" + tb.phase + ").";
  const jh = $("joinHint"); if (jh) { jh.textContent = hint; jh.classList.toggle("hidden", !hint); }
  const T = load(LS_T), S = load(LS_S), mine = [];
  for (const t of Object.keys(T)) mine.push({ id: +t, role: "bank", ts: T[t].ts });
  for (const g of Object.keys(S)) mine.push({ id: S[g].table, role: "bet", ts: S[g].ts });
  mine.sort((a, b) => b.ts - a.ts); const seen = new Set();
  $("recent").innerHTML = mine.filter((x) => { const k = x.id + x.role; if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 8)
    .map((x) => '<button class="chip" data-t="' + x.id + '">' + (x.role === "bank" ? "🏦" : "🎯") + " #" + x.id + "</button>").join(" ") || '<span class="dim">No tables yet.</span>';
  $("recent").querySelectorAll(".chip").forEach((b) => b.onclick = () => { activeTable = parseInt(b.dataset.t, 10); refreshActive(); });
  renderActive();
}
function renderActive() {
  const box = $("activeGame");
  if (activeTable == null) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  const tb = lastTable || {}, T = load(LS_T)[activeTable] || {};
  const iAmBank = tb.bank === dapp.me, mySeats = lastSeats.filter((s) => s.addr === dapp.me);
  $("gameId").textContent = "#" + activeTable;
  $("shareLink").value = base() + "/?table=" + activeTable;
  drawQR($("shareQR"), $("shareQRNote"), base() + "/?table=" + activeTable, 180);
  $("gBankroll").textContent = tb.exists ? rawToNado(tb.bankroll) + " NADO" : (T.bankroll ? rawToNado(T.bankroll) + " NADO" : "—");
  $("gCover").textContent = tb.exists ? rawToNado(BigInt(tb.bankroll) - BigInt(tb.committed)) + " NADO free" : "—";
  let phaseTxt = "opening… (confirming on-chain, ~1 min)";
  if (!tb.exists && T.ts && Date.now() - T.ts > 150000)   // opened locally but never landed on-chain
    phaseTxt = "⚠ this table didn't land — it was likely rejected (did your exec balance cover the bankroll?). Deposit enough, then open again.";
  if (tb.exists) {
    if (tb.phase === "betting") phaseTxt = "🟢 betting open — " + (dapp.cursor != null ? blocksToTime(tb.joinDeadline - dapp.cursor) + " left" : "…") + " · " + tb.seatCount + " seat" + (tb.seatCount === 1 ? "" : "s");
    else if (tb.phase === "spinning") phaseTxt = "🌀 betting closed — waiting for the bank to spin";
    else if (tb.phase === "forfeit") phaseTxt = "⚠ bank didn't spin — claim your max win";
    else if (tb.phase === "revealed") phaseTxt = "✓ spun — " + tb.settledCount + "/" + tb.seatCount + " seats collected";
    else if (tb.phase === "done") phaseTxt = "table closed";
  }
  $("gStatus").textContent = phaseTxt;
  const wheel = $("wheel");
  if (tb.result != null) { wheel.className = "wheel " + colorOf(tb.result); wheel.textContent = tb.result; $("result").textContent = colorOf(tb.result).toUpperCase() + " " + tb.result; }
  else if (tb.phase === "spinning" || tb.phase === "forfeit") { wheel.className = "wheel spin"; wheel.textContent = "?"; $("result").textContent = tb.phase === "forfeit" ? "Bank stalled — claim below" : "Betting closed — spinning soon"; }
  else { wheel.className = "wheel"; wheel.textContent = "?"; $("result").textContent = tb.phase === "betting" ? "Place your bets!" : "…"; }
  const seatRow = (s) => {
    const youTag = s.addr === dapp.me ? '<b style="color:var(--accent2)">you</b> ' : "";
    const pips = s.covered.slice(0, 6).map((n) => '<span class="pip ' + colorOf(n) + '">' + n + "</span>").join("") + (s.covered.length > 6 ? " +" + (s.covered.length - 6) : "");
    let out = "";
    if (tb.result != null) { const win = s.covered.includes(tb.result);
      out = s.settled ? (win ? '<span class="b ok">won ' + rawToNado(BigInt(s.stake) * BigInt(s.mult)) + "</span>" : '<span class="b dimb">no win</span>')
                      : (win ? '<span class="b pend">wins ' + rawToNado(BigInt(s.stake) * BigInt(s.mult)) + " — collect</span>" : '<span class="b dimb">lost</span>'); }
    return '<div class="seat">' + youTag + disp(s.addr) + ' · <span class="mono">' + rawToNado(s.stake) + "</span> on " + pips + " <span class='dim'>(" + s.mult + "×)</span> " + out + "</div>";
  };
  $("seats").innerHTML = lastSeats.length ? lastSeats.map(seatRow).join("") : '<span class="dim">No seats yet — be the first to bet.</span>';
  $("btnReveal").classList.toggle("hidden", !(iAmBank && tb.exists && !tb.revealed && tb.phase === "spinning"));
  $("btnReveal").textContent = "🌀 Spin the wheel (" + tb.seatCount + " bet" + (tb.seatCount === 1 ? "" : "s") + ")";
  const wrap = $("myActions"); wrap.innerHTML = "";
  for (const s of mySeats) {
    if (s.settled) continue;
    if (tb.phase === "revealed") { const win = s.covered.includes(tb.result);
      const b = document.createElement("button"); b.className = "primary"; b.style.flex = "1 1 auto";
      b.textContent = win ? "💰 Collect " + rawToNado(BigInt(s.stake) * BigInt(s.mult)) + " (seat #" + s.g + ")" : "Close out seat #" + s.g;
      b.onclick = () => settleSeat(s.g); if (win || iAmBank) wrap.appendChild(b);
    } else if (tb.phase === "forfeit") { const b = document.createElement("button"); b.className = "primary"; b.style.flex = "1 1 auto";
      b.textContent = "⚠ Claim max win — seat #" + s.g; b.onclick = () => claimSeat(s.g); wrap.appendChild(b); }
  }
  $("btnClose").classList.toggle("hidden", !(iAmBank && tb.exists && !tb.closed && tb.settledCount >= tb.seatCount && (tb.revealed || tb.phase === "forfeit" || tb.seatCount === 0)));
  $("btnClose").textContent = tb.seatCount === 0 ? "Cancel — reclaim bankroll" : "Close table — reclaim " + rawToNado(tb.pool);
  // the bank can top up the bankroll while the table is still taking bets (more coverage -> bigger bets fit)
  $("fundRow").classList.toggle("hidden", !(iAmBank && tb.exists && !tb.revealed && !tb.closed));
}

// ---- boot ----------------------------------------------------------------------------------------
dapp.onReturn((pend, ok, err) => {
  const label = { connect: "Signed in.", deposit: "Deposit submitted — confirming…", open: "Table opening — confirming…",
    bet: "Bet placed — confirming…", reveal: "Spinning — confirming…", settle: "Collecting…", claim: "Claiming…",
    close: "Closing…", withdraw: "Withdrawal submitted." }[pend && pend.phase] || "Submitted.";
  if (pend && pend.table != null) activeTable = pend.table;
  $("status").textContent = ok ? label : "Rejected" + (err ? ": " + err : ".");
});
async function boot() {
  try { await dapp.init(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload."; return; }
  wireUI(); loadQR();
  if ($("play") && $("activeGame")) $("play").parentNode.insertBefore($("activeGame"), $("play"));
  const q = new URLSearchParams(location.search).get("table");
  if (q) { $("joinId").value = q; if (activeTable == null) activeTable = parseInt(q, 10); }
  paintTable(); render(); refreshActive();
  setInterval(refreshActive, 3000);
}
boot();
