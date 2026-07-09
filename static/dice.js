// dice.js — NADO Dice: a provably-fair, peer-banked MULTIPLAYER dice on the execution layer, built on the
// shared game SDK (nadodapp.js). Classic adjustable-odds "roll under" dice: slide your win chance, the payout
// auto-scales (99 ÷ target → a flat 1% edge). A BANK opens a table with a bankroll + committed secret; during
// a betting WINDOW any number of BETTORS take a seat (one signature each, no per-player secret), each with
// their OWN roll  HASH(bankSecret + seatId) % 100  — so one bank reveal resolves many independent throws.
import { NadoDapp, rawToNado, nadoToRaw, randId, randSecret, commitHashOf, blake2bHash, _m, $, base,
         loadQR, drawQR, resolveAliases, disp, share } from "./nadodapp.js";

const CID = "e5e5c8558c85b3c45ef386f1fe2bccb4";
const PN = 100, MMIN = 2, MMAX = 98, EDGE = 99, BLOCK_SECS = 6;
const dapp = new NadoDapp({ cid: CID, app: "Dice" });

const LS_T = "nado_dice_tables", LS_S = "nado_dice_seats";
const load = (k) => { try { return JSON.parse(localStorage.getItem(k) || "{}"); } catch { return {}; } };
const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} };
let activeTable = null, lastTable = null, lastSeats = [], target = 50;

// dice roll — MUST match the contract: HASH(bankSecret + seatId) % 100
const rollOf = (secret, g) => Number(BigInt("0x" + blake2bHash((BigInt(secret) + BigInt(g)).toString())) % BigInt(PN));
const multOf = (M) => EDGE / M;                                  // payout multiplier (e.g. M=50 -> 1.98x)
const returnRaw = (stake, M) => BigInt(stake) * BigInt(EDGE) / BigInt(M);   // total return on a win (raw)
const blocksToTime = (b) => { b = Math.max(0, b) * BLOCK_SECS; const m = Math.floor(b / 60), s = b % 60; return m + ":" + String(s).padStart(2, "0"); };

// ---- reads (dice-specific storage schema) --------------------------------------------------------
const allTables = (sto) => Object.keys(_m(sto, "ta"));
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
  tb.phase = tablePhase(tb);
  return tb;
}
function seatsOfTable(sto, t) {
  t = String(t); const gg = _m(sto, "gg"), out = [];
  for (const g of Object.keys(gg)) if (String(gg[g]) === t) out.push({
    g: Number(g), addr: _m(sto, "ga")[g], stake: _m(sto, "gs")[g] || 0, M: _m(sto, "gm")[g] || 0, settled: !!_m(sto, "gd")[g] });
  return out.sort((a, b) => a.g - b.g);
}
async function fetchTable(t) { const sto = await dapp.storage(); return sto ? tableFrom(sto, t) : null; }

// ---- actions -------------------------------------------------------------------------------------
function openTable(t, bankrollRaw) {
  const T = load(LS_T); const secret = (T[t] && T[t].secret) ? T[t].secret : randSecret().toString();
  T[t] = { secret, bankroll: bankrollRaw.toString(), ts: Date.now() }; save(LS_T, T);
  activeTable = t; render();
  dapp.call("open", [t, commitHashOf(BigInt(secret))], bankrollRaw, "bank a dice table #" + t + " · " + rawToNado(bankrollRaw) + " NADO", { table: t, phase: "open" });
}
function newTable() {
  const raw = nadoToRaw($("bankrollAmt").value);
  if (!raw) { $("status").textContent = "Enter a bankroll (NADO)."; return; }
  if (dapp.exec < raw) { $("status").textContent = "Deposit first — your exec balance is " + rawToNado(dapp.exec) + " NADO."; return; }
  openTable(randId(), raw);
}
async function doBet() {
  const t = parseInt($("joinId").value, 10);
  if (!t) { $("status").textContent = "Enter a table ID (or pick one from the lobby)."; return; }
  const stake = nadoToRaw($("stakeAmt").value);
  if (!stake) { $("status").textContent = "Enter a stake (NADO)."; return; }
  const tb = await fetchTable(t);
  if (!tb || !tb.exists) { $("status").textContent = "No such table yet — ask the bank for the ID."; return; }
  if (tb.phase !== "betting") { $("status").textContent = "Betting is closed on that table (" + tb.phase + ")."; return; }
  await dapp.refresh();
  if (dapp.exec < stake) { $("status").textContent = "You need " + rawToNado(stake) + " NADO in your exec balance (you have " + rawToNado(dapp.exec) + "). Deposit first."; render(); return; }
  const need = returnRaw(stake, target) - stake;
  if (BigInt(tb.bankroll) - BigInt(tb.committed) < need) { $("status").textContent = "This table can't cover a " + multOf(target).toFixed(2) + "× win right now. Lower your stake or raise your win chance."; render(); return; }
  const g = randId(), S = load(LS_S);
  S[g] = { table: t, stake: stake.toString(), M: target, ts: Date.now() }; save(LS_S, S);
  activeTable = t; render();
  dapp.call("bet", [g, t, target], stake, "roll under " + target + " for " + rawToNado(stake) + " NADO · table #" + t, { table: t, seat: g, phase: "bet" });
}
function revealTable() {
  const T = load(LS_T)[activeTable];
  if (!T || !T.secret) { $("status").textContent = "No bank secret for this table on this device."; return; }
  dapp.call("reveal", [activeTable, BigInt(T.secret)], null, "roll the dice · table #" + activeTable, { table: activeTable, phase: "reveal" });
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
    if (!tb.exists || !tb.revealed || tb.secret == null) continue;
    const M = _m(sto, "gm")[g] || 1, stake = _m(sto, "gs")[g] || 0, win = rollOf(tb.secret, g) < M;
    const net = win ? Number(returnRaw(stake, M)) - stake : -stake;
    bump(_m(sto, "ga")[g], net); bump(tb.bank, -net);
  }
  return Object.values(stats).sort((a, b) => (b.net - a.net) || (b.wins - a.wins));
}
async function renderScoreboard(board) {
  const el = $("scoreList"); if (!el) return;
  if (!board.length) { el.innerHTML = '<span class="dim">No finished rolls yet — be the first on the board.</span>'; return; }
  const top = board.slice(0, 10); await resolveAliases(top.map((r) => r.addr));
  el.innerHTML = '<table class="score"><thead><tr><th>#</th><th>Player</th><th>W–L</th><th>Net</th></tr></thead><tbody>'
    + top.map((r, i) => { const net = (r.net < 0 ? "-" : "+") + rawToNado(Math.abs(r.net)) + " NADO", you = r.addr === dapp.me;
        return '<tr' + (you ? ' class="me"' : "") + '><td>' + (i + 1) + '</td><td>' + disp(r.addr) + (you ? " (you)" : "") + '</td><td>W' + r.wins + "–L" + r.losses + '</td><td class="' + (r.net >= 0 ? "pos" : "neg") + '">' + net + "</td></tr>"; }).join("") + "</tbody></table>";
}
function renderLobby(sto) {
  const el = $("lobbyList"); if (!el) return;
  const tables = allTables(sto).map((t) => tableFrom(sto, t)).filter((t) => t.exists && !t.closed);
  const rank = { betting: 0, spinning: 1, forfeit: 1, revealed: 2, done: 3 }, tag = { betting: "🟢", spinning: "🎲", revealed: "✓", forfeit: "⚠" };
  tables.sort((a, b) => (rank[a.phase] - rank[b.phase]) || (b.joinDeadline - a.joinDeadline));
  const shown = tables.slice(0, 24);
  el.innerHTML = shown.length ? shown.map((t) => {
    const left = t.phase === "betting" && dapp.cursor != null ? " · " + blocksToTime(t.joinDeadline - dapp.cursor) + " left" : "";
    const verb = t.phase === "betting" ? " · bet" : t.phase === "spinning" ? " · rolling" : t.phase === "forfeit" ? " · claim" : "";
    return '<button class="chip ' + t.phase + '" data-t="' + t.id + '">' + (tag[t.phase] || "") + " #" + t.id + " · bank " + rawToNado(t.bankroll) + " · " + t.seatCount + " roll" + (t.seatCount === 1 ? "" : "s") + left + verb + "</button>";
  }).join(" ") : '<span class="dim">No tables yet — bank one below.</span>';
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => {
    const id = parseInt(b.dataset.t, 10);
    activeTable = id; $("joinId").value = String(id);
    $("status").textContent = "Table #" + id + " selected — set your stake and win chance, then Place roll.";
    refreshActive();
    try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {}
    try { $("stakeAmt").focus(); } catch {}
  });
}

// ---- render --------------------------------------------------------------------------------------
function syncSlider() {
  target = Math.min(MMAX, Math.max(MMIN, parseInt($("target").value, 10) || 50));
  $("winChanceTarget").textContent = target;
  $("winChance").textContent = target + "%";
  $("multiplier").textContent = multOf(target).toFixed(2) + "×";
  const stake = nadoToRaw($("stakeAmt").value);
  $("payoutPreview").textContent = stake ? "win pays " + rawToNado(returnRaw(stake, target)) + " NADO" : "";
}
function wireUI() {
  $("btnSignIn").onclick = () => dapp.signIn();
  $("btnDeposit").onclick = () => { const raw = nadoToRaw($("bankAmt").value); if (!raw) return ($("status").textContent = "Enter an amount to deposit."); if (raw + 1000n > dapp.l1) return ($("status").textContent = "Not enough in your L1 wallet (" + rawToNado(dapp.l1) + " NADO)."); dapp.deposit(raw); };
  $("btnWithdraw").onclick = () => { const raw = nadoToRaw($("bankAmt").value); if (!raw) return ($("status").textContent = "Enter an amount to withdraw."); if (dapp.exec < raw) return ($("status").textContent = "You only have " + rawToNado(dapp.exec) + " NADO in the exec layer."); dapp.withdraw(raw); };
  $("btnNewTable").onclick = newTable;
  $("btnBet").onclick = doBet;
  $("btnReveal").onclick = revealTable;
  $("btnClose").onclick = closeTable;
  $("btnShare").onclick = () => share(base() + "/?table=" + activeTable, "Roll at my dice table #" + activeTable + " on NADO:", $("btnShare"));
  $("target").oninput = () => { syncSlider(); render(); };
  $("stakeAmt").oninput = () => { syncSlider(); render(); };
  $("joinId").oninput = () => render();
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
  // bet affordability (SDK-backed)
  const jid = ($("joinId").value || "").trim();
  const tb = (jid && String(activeTable) === jid && lastTable && lastTable.exists) ? lastTable : null;
  const stake = nadoToRaw($("stakeAmt").value);
  const phaseOk = !tb || tb.phase === "betting";
  const need = stake ? returnRaw(stake, target) - stake : null;
  const covers = !(tb && need != null && (BigInt(tb.bankroll) - BigInt(tb.committed)) < need);
  const canAfford = !(signedIn && stake && dapp.exec < stake);
  const betable = !!jid && !!stake && phaseOk && canAfford && covers;
  $("btnBet").disabled = !betable;
  $("btnBet").classList.toggle("pulse", betable && signedIn);
  $("btnSignIn").classList.toggle("pulse", !!jid && !!stake && !signedIn);
  let hint = "";
  if (jid && signedIn && phaseOk) {
    if (stake && dapp.exec < stake) hint = "Not enough NADO — this rolls " + rawToNado(stake) + " but your exec balance is " + rawToNado(dapp.exec) + ". Deposit at least " + rawToNado(stake - dapp.exec) + " more below.";
    else if (tb && !covers) hint = "This table can't cover a " + multOf(target).toFixed(2) + "× win right now (bankroll left: " + rawToNado(BigInt(tb.bankroll) - BigInt(tb.committed)) + " NADO). Lower your stake or raise your win chance.";
  } else if (jid && tb && tb.phase !== "betting") hint = "Betting is closed on table #" + jid + " (" + tb.phase + ").";
  const jh = $("joinHint"); if (jh) { jh.textContent = hint; jh.classList.toggle("hidden", !hint); }
  // my recent tables/seats
  const T = load(LS_T), S = load(LS_S), mine = [];
  for (const t of Object.keys(T)) mine.push({ id: +t, role: "bank", ts: T[t].ts });
  for (const g of Object.keys(S)) mine.push({ id: S[g].table, role: "bet", ts: S[g].ts });
  mine.sort((a, b) => b.ts - a.ts); const seen = new Set();
  $("recent").innerHTML = mine.filter((x) => { const k = x.id + x.role; if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 8)
    .map((x) => '<button class="chip" data-t="' + x.id + '">' + (x.role === "bank" ? "🏦" : "🎲") + " #" + x.id + "</button>").join(" ") || '<span class="dim">No tables yet.</span>';
  $("recent").querySelectorAll(".chip").forEach((b) => b.onclick = () => { activeTable = parseInt(b.dataset.t, 10); refreshActive(); });
  renderActive();
}
function renderActive() {
  const box = $("activeGame");
  if (activeTable == null) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  const tb = lastTable || {}, T = load(LS_T)[activeTable] || {}, S = load(LS_S);
  const iAmBank = tb.bank === dapp.me, mySeats = lastSeats.filter((s) => s.addr === dapp.me);
  $("gameId").textContent = "#" + activeTable;
  $("shareLink").value = base() + "/?table=" + activeTable;
  drawQR($("shareQR"), $("shareQRNote"), base() + "/?table=" + activeTable, 180);
  $("gBankroll").textContent = tb.exists ? rawToNado(tb.bankroll) + " NADO" : (T.bankroll ? rawToNado(T.bankroll) + " NADO" : "—");
  $("gCover").textContent = tb.exists ? rawToNado(BigInt(tb.bankroll) - BigInt(tb.committed)) + " NADO free" : "—";
  let phaseTxt = "opening…";
  if (tb.exists) {
    if (tb.phase === "betting") phaseTxt = "🟢 betting open — " + (dapp.cursor != null ? blocksToTime(tb.joinDeadline - dapp.cursor) + " left" : "…") + " · " + tb.seatCount + " roll" + (tb.seatCount === 1 ? "" : "s");
    else if (tb.phase === "spinning") phaseTxt = "🎲 betting closed — waiting for the bank to roll";
    else if (tb.phase === "forfeit") phaseTxt = "⚠ bank didn't roll — claim your max win";
    else if (tb.phase === "revealed") phaseTxt = "✓ rolled — " + tb.settledCount + "/" + tb.seatCount + " collected";
    else if (tb.phase === "done") phaseTxt = "table closed";
  }
  $("gStatus").textContent = phaseTxt;
  // seats — each with its own roll once revealed
  const seatRow = (s) => {
    const you = s.addr === dapp.me ? '<b style="color:var(--accent2)">you</b> ' : "";
    let out = "on <b>under " + s.M + "</b> <span class='dim'>(" + multOf(s.M).toFixed(2) + "×)</span>";
    if (tb.revealed && tb.secret != null) { const r = rollOf(tb.secret, s.g), win = r < s.M;
      out += ' → rolled <b class="' + (win ? "wroll" : "lroll") + '">' + r + "</b> "
        + (s.settled ? (win ? '<span class="b ok">won ' + rawToNado(returnRaw(s.stake, s.M)) + "</span>" : '<span class="b dimb">no win</span>')
                     : (win ? '<span class="b pend">wins ' + rawToNado(returnRaw(s.stake, s.M)) + " — collect</span>" : '<span class="b dimb">lost</span>')); }
    return '<div class="seat">' + you + disp(s.addr) + ' · <span class="mono">' + rawToNado(s.stake) + "</span> " + out + "</div>";
  };
  $("seats").innerHTML = lastSeats.length ? lastSeats.map(seatRow).join("") : '<span class="dim">No rolls yet — be the first to bet.</span>';
  // action buttons
  const bankPending = false;
  $("btnReveal").classList.toggle("hidden", !(iAmBank && tb.exists && !tb.revealed && tb.phase === "spinning" && !bankPending));
  $("btnReveal").textContent = "🎲 Roll the dice (" + tb.seatCount + " bet" + (tb.seatCount === 1 ? "" : "s") + ")";
  const wrap = $("myActions"); wrap.innerHTML = "";
  for (const s of mySeats) {
    if (s.settled) continue;
    if (tb.phase === "revealed") { const win = rollOf(tb.secret, s.g) < s.M;
      const b = document.createElement("button"); b.className = "primary"; b.style.flex = "1 1 auto";
      b.textContent = win ? "💰 Collect " + rawToNado(returnRaw(s.stake, s.M)) + " (seat #" + s.g + ")" : "Close out seat #" + s.g;
      b.onclick = () => settleSeat(s.g); if (win || iAmBank) wrap.appendChild(b);
    } else if (tb.phase === "forfeit") { const b = document.createElement("button"); b.className = "primary"; b.style.flex = "1 1 auto";
      b.textContent = "⚠ Claim max win — seat #" + s.g; b.onclick = () => claimSeat(s.g); wrap.appendChild(b); }
  }
  $("btnClose").classList.toggle("hidden", !(iAmBank && tb.exists && !tb.closed && tb.settledCount >= tb.seatCount && (tb.revealed || tb.phase === "forfeit" || tb.seatCount === 0)));
  $("btnClose").textContent = tb.seatCount === 0 ? "Cancel — reclaim bankroll" : "Close table — reclaim " + rawToNado(tb.pool);
}

// ---- boot ----------------------------------------------------------------------------------------
dapp.onReturn((pend, ok, err) => {
  const label = { connect: "Signed in.", deposit: "Deposit submitted — confirming…", open: "Table opening — confirming…",
    bet: "Bet placed — confirming…", reveal: "Rolling — confirming…", settle: "Collecting…", claim: "Claiming…",
    close: "Closing…", withdraw: "Withdrawal submitted." }[pend && pend.phase] || "Submitted.";
  if (pend && pend.table != null) activeTable = pend.table;
  $("status").textContent = ok ? label : "Rejected" + (err ? ": " + err : ".");
});
async function boot() {
  try { await dapp.init(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload."; return; }
  wireUI(); loadQR(); syncSlider();
  const q = new URLSearchParams(location.search).get("table");
  if (q) { $("joinId").value = q; if (activeTable == null) activeTable = parseInt(q, 10); }
  render(); refreshActive();
  setInterval(refreshActive, 3000);
}
boot();
