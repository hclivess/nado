// poker.js — NADO Poker: auto-dealing, peer-banked MULTIPLAYER video poker on the execution layer, built on the
// shared game SDK (nadodapp.js). A table deals itself every ROUND blocks — no bank action, no secrets. Each seat
// gets a 5-card hand from FINALIZED L1 block hashes nobody can predict while betting is open:
//     card_i = HASH( BLOCKHASH(sh) + BLOCKHASH(sh+1) + seatId*10 + i ) % 52
// The CONTRACT evaluates the hand (Jacks-or-better paytable) and pays stake × multiplier; the same evaluator
// runs here for a live preview. settle is permissionless; losing stakes fold into the bankroll. No game API.
import { NadoDapp, rawToNado, nadoToRaw, randId, blake2bHash, _m, $, base, gate, hoist,
         loadQR, drawQR, resolveAliases, disp, share } from "./nadodapp.js";

const CID = "167b7ff631fbeb53c74c5123412d13cb";
const BLOCK_SECS = 6, ROUND = 20, MAXMULT = 100;
const dapp = new NadoDapp({ cid: CID, app: "Poker" });
// paytable (must match the contract): name -> [multiplier], priority high->low
const PAYS = [["Royal flush", 100], ["Straight flush", 80], ["Four of a kind", 50], ["Full house", 22],
             ["Flush", 16], ["Straight", 10], ["Three of a kind", 4], ["Two pair", 3], ["Jacks or better", 2]];

const LS_T = "nado_poker_tables", LS_S = "nado_poker_seats";
const load = (k) => { try { return JSON.parse(localStorage.getItem(k) || "{}"); } catch { return {}; } };
const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} };
let activeTable = null, lastTable = null, lastSeats = [];
let knownTables = new Set(), knownSeats = new Set();
const bhCache = {};

function pruneAndTrack(sto) {
  knownTables = new Set(allTables(sto));
  knownSeats = new Set(Object.keys(_m(sto, "gg")));
  const T = load(LS_T); let c = false;
  for (const t of Object.keys(T)) if (!knownTables.has(t) && Date.now() - (T[t].ts || 0) > 600000) { delete T[t]; c = true; }
  if (c) save(LS_T, T);
  const S = load(LS_S); c = false;
  for (const g of Object.keys(S)) if (!knownSeats.has(g) && Date.now() - (S[g].ts || 0) > 600000) { delete S[g]; c = true; }
  if (c) save(LS_S, S);
}
const blocksToTime = (b) => { b = Math.max(0, b) * BLOCK_SECS; const m = Math.floor(b / 60), s = b % 60; return m + ":" + String(s).padStart(2, "0"); };

// ---- card + hand eval (MUST match the contract) --------------------------------------------------
function cardsOf(shHex, sh1Hex, g) {
  if (!shHex || !sh1Hex) return null;
  const base = BigInt("0x" + shHex) + BigInt("0x" + sh1Hex);
  const out = [];
  for (let i = 0; i < 5; i++) out.push(Number(BigInt("0x" + blake2bHash(base + BigInt(g * 10 + i))) % 52n));  // BigInt seed -> bare digits
  return out;
}
function handEval(cards) {   // -> { mult, name }
  const ranks = cards.map((c) => c % 13), suits = cards.map((c) => Math.floor(c / 13));
  const has = Array(13).fill(0), cnt = Array(13).fill(0);
  for (const r of ranks) { has[r] = 1; cnt[r]++; }
  const flush = suits.every((s) => s === suits[0]);
  const win = (s) => [0, 1, 2, 3, 4].every((k) => has[s + k]);
  let straight = false;
  for (let s = 0; s <= 8; s++) if (win(s)) straight = true;
  if (has[12] && has[0] && has[1] && has[2] && has[3]) straight = true;
  const sflush = straight && flush, royal = sflush && win(8);
  const quad = cnt.some((c) => c === 4), trip = cnt.some((c) => c === 3);
  const npair = cnt.filter((c) => c === 2).length, twopair = npair >= 2, fullhouse = trip && npair >= 1;
  let jacks = false; for (let v = 9; v < 13; v++) if (cnt[v] >= 2) jacks = true;
  const ind = { "Royal flush": royal, "Straight flush": sflush, "Four of a kind": quad, "Full house": fullhouse,
    "Flush": flush, "Straight": straight, "Three of a kind": trip, "Two pair": twopair, "Jacks or better": jacks };
  for (const [name, m] of PAYS) if (ind[name]) return { mult: m, name };
  return { mult: 0, name: "No pair" };
}
async function fetchHashes(heights) {
  const need = [...new Set(heights)].filter((h) => bhCache[h] === undefined);
  if (!need.length) return;
  try {
    const r = await fetch(base() + "/exec/blockhash?ns=" + dapp.ns + "&provisional=1&heights=" + need.join(","), { cache: "no-store" });
    const j = await r.json();
    for (const h of need) bhCache[h] = (j.hashes && j.hashes[String(h)]) || null;
  } catch { for (const h of need) bhCache[h] = null; }
}

// ---- reads ---------------------------------------------------------------------------------------
const allTables = (sto) => Object.keys(_m(sto, "t0"));
function tableFrom(sto, t) {
  t = String(t); const bank = _m(sto, "ta")[t], t0 = _m(sto, "t0")[t];
  if (!bank || t0 == null) return { exists: false };
  const tb = { exists: true, id: Number(t), bank, bankroll: _m(sto, "tk")[t] || 0, pool: _m(sto, "tp")[t] || 0,
    committed: _m(sto, "tc")[t] || 0, t0, seatCount: _m(sto, "tn")[t] || 0,
    settledCount: _m(sto, "tx")[t] || 0, closed: !!_m(sto, "tz")[t] };
  tb.phase = tb.closed ? "done" : "betting";
  const cur = dapp.cursor;
  if (cur != null) { tb.nextSettle = t0 + (Math.floor((cur - t0) / ROUND) + 1) * ROUND; tb.roundEndsIn = tb.nextSettle - cur; }
  return tb;
}
function seatsOfTable(sto, t) {
  t = String(t); const gg = _m(sto, "gg"), cur = dapp.cursor, out = [];
  for (const g of Object.keys(gg)) if (String(gg[g]) === t) {
    const gh = _m(sto, "gh")[g] || 0, settled = !!_m(sto, "gd")[g];
    const s = { g: Number(g), addr: _m(sto, "ga")[g], stake: _m(sto, "gs")[g] || 0, gh, settled };
    if ((settled || (cur != null && cur >= gh + 1))) {
      const cards = cardsOf(bhCache[gh], bhCache[gh + 1], Number(g));
      if (cards) { s.cards = cards; const e = handEval(cards); s.mult = e.mult; s.name = e.name; s.win = e.mult > 0; s.ready = !settled; }
      else if (!settled) { s.pending = true; s.spinsIn = 0; }
    } else { s.pending = true; s.spinsIn = cur != null ? gh - cur : null; }
    out.push(s);
  }
  return out.sort((a, b) => b.g - a.g);
}
async function fetchTable(t) { const sto = await dapp.storage(); return sto ? tableFrom(sto, t) : null; }

// ---- actions -------------------------------------------------------------------------------------
function openTable(t, bankrollRaw) {
  const T = load(LS_T); T[t] = { bankroll: bankrollRaw.toString(), ts: Date.now() }; save(LS_T, T);
  activeTable = t; $("joinId").value = String(t); render();
  dapp.call("open", [t], bankrollRaw, "bank a poker table #" + t + " · " + rawToNado(bankrollRaw) + " NADO", { table: t, phase: "open" });
}
function reopenTable() {
  const T = load(LS_T)[activeTable]; if (!T || !T.bankroll) return;
  const raw = BigInt(T.bankroll);
  if (dapp.exec < raw) { $("status").textContent = "Deposit first — this bankroll needs " + rawToNado(raw) + " NADO."; return; }
  openTable(activeTable, raw);
}
async function newTable() {
  const raw = nadoToRaw($("bankrollAmt").value);
  if (!raw) { $("status").textContent = "Enter a bankroll (NADO)."; return; }
  await dapp.refresh();
  if (dapp.exec < raw) { $("status").textContent = "Deposit first — your exec balance is " + rawToNado(dapp.exec) + " NADO, but this bankroll needs " + rawToNado(raw) + "."; return; }
  openTable(randId(), raw);
}
async function doBet() {
  const t = activeTable;
  if (!t) { $("status").textContent = "Pick a table first."; return; }
  const stake = nadoToRaw($("stakeAmt").value);
  if (!stake) { $("status").textContent = "Enter a stake (NADO)."; return; }
  const tb = await fetchTable(t);
  if (!tb || !tb.exists) { $("status").textContent = "No such table yet — ask the bank for the ID."; return; }
  if (tb.closed) { $("status").textContent = "That table is closed."; return; }
  await dapp.refresh();
  if (dapp.exec < stake) { $("status").textContent = "You need " + rawToNado(stake) + " NADO in your exec balance (you have " + rawToNado(dapp.exec) + "). Deposit first."; render(); return; }
  const need = stake * BigInt(MAXMULT - 1);   // bank must cover the max (royal, 100x)
  if (BigInt(tb.bankroll) - BigInt(tb.committed) < need) { $("status").textContent = "This table can't cover a 100× hand right now (needs " + rawToNado(need) + " free). Lower your stake or top up the bankroll."; render(); return; }
  const g = randId(), S = load(LS_S);
  S[g] = { table: t, stake: stake.toString(), ts: Date.now() }; save(LS_S, S); render();
  dapp.call("bet", [g, t], stake, "deal me in for " + rawToNado(stake) + " NADO · table #" + t, { table: t, seat: g, phase: "bet" });
}
function fundTable() {
  const raw = nadoToRaw($("fundAmt").value);
  if (!raw) { $("status").textContent = "Enter an amount to add to this table's bankroll."; return; }
  if (dapp.exec < raw) { $("status").textContent = "Deposit first — your exec balance is " + rawToNado(dapp.exec) + " NADO."; return; }
  dapp.call("fund", [activeTable], raw, "top up table #" + activeTable + " bankroll · " + rawToNado(raw) + " NADO", { table: activeTable, phase: "fund" });
}
const settleSeat = (g) => dapp.call("settle", [g], null, "collect seat #" + g, { table: activeTable, phase: "settle" });
const closeTable = () => dapp.call("close", [activeTable], null, "close table #" + activeTable, { table: activeTable, phase: "close" });

async function refreshActive() {
  await dapp.refresh();
  const sto = await dapp.storage();
  if (sto) {
    pruneAndTrack(sto);
    if (activeTable != null) {
      lastTable = tableFrom(sto, activeTable);
      const cur = dapp.cursor, need = [];
      for (const g of Object.keys(_m(sto, "gg"))) if (String(_m(sto, "gg")[g]) === String(activeTable)) {
        const gh = _m(sto, "gh")[g] || 0; if (cur != null && cur >= gh + 1) need.push(gh, gh + 1);
      }
      if (need.length) await fetchHashes(need);
      lastSeats = seatsOfTable(sto, activeTable);
    }
    renderLobby(sto); renderScoreboard(boardFrom(sto));
  }
  await resolveAliases([dapp.me].concat(lastTable ? [lastTable.bank] : []).concat(lastSeats.map((s) => s.addr)));
  render();
}
function boardFrom(sto) {
  const stats = {}, bump = (a, net) => { const x = stats[a] || (stats[a] = { addr: a, wins: 0, losses: 0, games: 0, net: 0 }); x.games++; x.net += net; net >= 0 ? x.wins++ : x.losses++; };
  for (const g of Object.keys(_m(sto, "gd"))) {
    if (!_m(sto, "gd")[g]) continue;
    const t = String(_m(sto, "gg")[g]), bank = _m(sto, "ta")[t]; if (!bank) continue;
    const mult = _m(sto, "gr")[g] || 0, stake = _m(sto, "gs")[g] || 0, net = stake * (mult - 1);
    bump(_m(sto, "ga")[g], net); bump(bank, -net);
  }
  return Object.values(stats).sort((a, b) => (b.net - a.net) || (b.wins - a.wins));
}
async function renderScoreboard(board) {
  const el = $("scoreList"); if (!el) return;
  if (!board.length) { el.innerHTML = '<span class="dim">No settled hands yet — be the first on the board.</span>'; return; }
  const top = board.slice(0, 10); await resolveAliases(top.map((r) => r.addr));
  el.innerHTML = '<table class="score"><thead><tr><th>#</th><th>Player</th><th>W–L</th><th>Net</th></tr></thead><tbody>'
    + top.map((r, i) => { const net = (r.net < 0 ? "-" : "+") + rawToNado(Math.abs(r.net)) + " NADO", you = r.addr === dapp.me;
        return '<tr' + (you ? ' class="me"' : "") + '><td>' + (i + 1) + '</td><td>' + disp(r.addr) + (you ? " (you)" : "") + '</td><td>W' + r.wins + "–L" + r.losses + '</td><td class="' + (r.net >= 0 ? "pos" : "neg") + '">' + net + "</td></tr>"; }).join("") + "</tbody></table>";
}
function renderLobby(sto) {
  const el = $("lobbyList"); if (!el) return;
  const tables = allTables(sto).map((t) => tableFrom(sto, t)).filter((t) => t.exists && !t.closed);
  tables.sort((a, b) => b.seatCount - a.seatCount || b.id - a.id);
  el.innerHTML = tables.length ? tables.slice(0, 24).map((t) => {
    const left = t.roundEndsIn != null ? " · next deal " + blocksToTime(t.roundEndsIn) : "";
    return '<button class="chip betting" data-t="' + t.id + '">🂡 #' + t.id + " · bank " + rawToNado(t.bankroll) + " · " + t.seatCount + " hand" + (t.seatCount === 1 ? "" : "s") + left + "</button>";
  }).join(" ") : '<span class="dim">No tables yet — bank one below.</span>';
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => selectTable(parseInt(b.dataset.t, 10)));
}
function selectTable(id) {
  activeTable = id; $("joinId").value = String(id);
  $("status").textContent = "Table #" + id + " — set your stake and deal in.";
  refreshActive();
  try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {}
}

// ---- card rendering ------------------------------------------------------------------------------
const RANKSTR = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"], SUITSTR = ["♠","♥","♦","♣"];
function cardHTML(c) {
  if (c == null) return '<div class="card back"></div>';
  const rank = c % 13, suit = Math.floor(c / 13), red = suit === 1 || suit === 2;
  return '<div class="card' + (red ? " red" : "") + '">' + RANKSTR[rank] + '<span class="suit">' + SUITSTR[suit] + "</span></div>";
}
function handHTML(cards) { return (cards || [null, null, null, null, null]).map(cardHTML).join(""); }

// ---- render --------------------------------------------------------------------------------------
function wireUI() {
  $("btnSignIn").onclick = () => dapp.signIn();
  $("btnDeposit").onclick = () => { const raw = nadoToRaw($("bankAmt").value); if (!raw) return ($("status").textContent = "Enter an amount to deposit."); if (raw + 1000n > dapp.l1) return ($("status").textContent = "Not enough in your L1 wallet (" + rawToNado(dapp.l1) + " NADO)."); dapp.deposit(raw); };
  $("btnWithdraw").onclick = () => { const raw = nadoToRaw($("bankAmt").value); if (!raw) return ($("status").textContent = "Enter an amount to withdraw."); if (dapp.exec < raw) return ($("status").textContent = "You only have " + rawToNado(dapp.exec) + " NADO in the exec layer."); dapp.withdraw(raw); };
  $("btnNewTable").onclick = newTable;
  $("btnBet").onclick = doBet;
  $("btnGoTable").onclick = () => { const id = parseInt($("joinId").value, 10); if (id) selectTable(id); else $("status").textContent = "Enter a table ID, or pick one from the lobby."; };
  $("stakeAmt").oninput = () => render();
  $("btnClose").onclick = closeTable;
  $("btnReopen").onclick = reopenTable;
  $("btnFund").onclick = fundTable;
  $("btnShare").onclick = () => share(base() + "/?table=" + activeTable, "Deal in at my poker table #" + activeTable + " on NADO:", $("btnShare"));
}
function render() {
  const signedIn = !!dapp.me;
  gate({ play: signedIn, bankcard: signedIn, bankroll: signedIn, activeGame: activeTable != null });
  $("btnSignIn").classList.toggle("hidden", signedIn);
  $("who").textContent = signedIn ? disp(dapp.me) : "not signed in";
  $("bal").textContent = rawToNado(dapp.exec) + " NADO";
  $("l1bal").textContent = rawToNado(dapp.l1) + " NADO";
  const tb = (activeTable != null && lastTable && lastTable.exists && !lastTable.closed) ? lastTable : null;
  const stake = nadoToRaw($("stakeAmt").value);
  const need = stake ? stake * BigInt(MAXMULT - 1) : null;
  const covers = !(tb && need != null && (BigInt(tb.bankroll) - BigInt(tb.committed)) < need);
  const canAfford = !(signedIn && stake && dapp.exec < stake);
  const betable = !!tb && !!stake && canAfford && covers;
  if ($("btnBet")) { $("btnBet").disabled = !betable; $("btnBet").classList.toggle("pulse", betable && signedIn); }
  let hint = "";
  if (signedIn && activeTable != null) {
    if (!tb && !lastTable?.exists) hint = "Table #" + activeTable + " isn't on-chain yet — if you just opened it, give it ~1 min to confirm.";
    else if (lastTable && lastTable.closed) hint = "Table #" + activeTable + " is closed.";
    else if (!stake) hint = "Enter a stake (NADO), then deal in — you can play at your own table too.";
    else if (dapp.exec < stake) hint = "Not enough NADO — this stakes " + rawToNado(stake) + " but your exec balance is " + rawToNado(dapp.exec) + ".";
    else if (tb && !covers) hint = "This table's bankroll can't cover a 100× hand (free: " + rawToNado(BigInt(tb.bankroll) - BigInt(tb.committed)) + " NADO). Lower your stake or top up.";
  }
  const jh = $("joinHint"); if (jh) { jh.textContent = hint; jh.classList.toggle("hidden", !hint); }
  const T = load(LS_T), S = load(LS_S), mine = [];
  for (const t of Object.keys(T)) mine.push({ id: +t, role: "bank", ts: T[t].ts });
  for (const g of Object.keys(S)) mine.push({ id: S[g].table, seat: g, role: "bet", ts: S[g].ts });
  mine.sort((a, b) => b.ts - a.ts); const seen = new Set();
  const shown = mine.filter((x) => { x.live = x.role === "bank" ? knownTables.has(String(x.id)) : knownSeats.has(String(x.seat)); const k = x.id + x.role; if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 8);
  $("recent").innerHTML = shown.length ? shown.map((x) => '<button class="chip' + (x.live ? "" : " pending") + '" data-t="' + x.id + '"' + (x.live ? "" : ' title="still confirming on-chain — your hand hasn\'t vanished"') + '>' + (x.role === "bank" ? "🏦" : "🂡") + " #" + x.id + (x.live ? "" : " ⏳") + "</button>").join(" ") : '<span class="dim">No tables yet.</span>';
  $("recent").querySelectorAll(".chip").forEach((b) => b.onclick = () => selectTable(parseInt(b.dataset.t, 10)));
  renderActive();
}
function renderActive() {
  if (activeTable == null) return;
  const tb = lastTable || {}, T = load(LS_T)[activeTable] || {};
  const iAmBank = tb.bank === dapp.me, mySeats = lastSeats.filter((s) => s.addr === dapp.me);
  $("gameId").textContent = "#" + activeTable;
  $("shareLink").value = base() + "/?table=" + activeTable;
  drawQR($("shareQR"), $("shareQRNote"), base() + "/?table=" + activeTable, 180);
  $("gBank").textContent = tb.exists ? (disp(tb.bank) + (iAmBank ? " — that's you (you're the house here)" : "")) : (T.bankroll ? "you (opening…)" : "—");
  $("gBankroll").textContent = tb.exists ? rawToNado(tb.bankroll) + " NADO" : (T.bankroll ? rawToNado(T.bankroll) + " NADO" : "—");
  $("gCover").textContent = tb.exists ? rawToNado(BigInt(tb.bankroll) - BigInt(tb.committed)) + " NADO free" : "—";
  let phaseTxt = "opening… (confirming on-chain, ~1 min)";
  if (!tb.exists && T.ts && Date.now() - T.ts > 150000)
    phaseTxt = "⚠ this table didn't land — likely rejected (did your exec balance cover the bankroll?). Deposit enough, then open again.";
  if (tb.exists) phaseTxt = tb.closed ? "table closed" : "🟢 dealing every " + blocksToTime(ROUND) + " — next deal in " + (tb.roundEndsIn != null ? blocksToTime(tb.roundEndsIn) : "…") + " · " + tb.seatCount + " hand" + (tb.seatCount === 1 ? "" : "s");
  $("gStatus").textContent = phaseTxt;
  $("btnReopen").classList.toggle("hidden", !(!tb.exists && T.bankroll && T.ts && Date.now() - T.ts > 120000));
  // my most-recent hand shown big
  const myLast = mySeats.find((s) => s.cards) || mySeats[0];
  const feat = $("featureHand");
  if (feat) {
    if (myLast && myLast.cards) { feat.innerHTML = handHTML(myLast.cards); $("featureResult").textContent = myLast.name + (myLast.win ? " — won " + rawToNado(BigInt(myLast.stake) * BigInt(myLast.mult)) + " (" + myLast.mult + "×)" : " — no win"); $("featureResult").className = myLast.win ? "wroll" : "dim"; }
    else if (myLast) { feat.innerHTML = handHTML(null); $("featureResult").textContent = "dealt in — next deal in " + (myLast.spinsIn != null ? blocksToTime(myLast.spinsIn) : "…"); $("featureResult").className = "dim"; }
    else { feat.innerHTML = handHTML(null); $("featureResult").textContent = tb.exists && !tb.closed ? "Set a stake and deal in" : "…"; $("featureResult").className = "dim"; }
  }
  const seatRow = (s) => {
    const you = s.addr === dapp.me ? '<b style="color:var(--accent2)">you</b> ' : "";
    let out = "";
    if (s.cards) out = '<span class="minihand">' + handHTML(s.cards) + "</span> " + (s.win ? '<span class="b ok">' + s.name + " · " + s.mult + "×</span>" : '<span class="b dimb">' + s.name + "</span>");
    else out = '<span class="b pend">deals in ' + (s.spinsIn != null ? blocksToTime(s.spinsIn) : "…") + "</span>";
    return '<div class="seat">' + you + disp(s.addr) + ' · <span class="mono">' + rawToNado(s.stake) + "</span> " + out + "</div>";
  };
  $("seats").innerHTML = lastSeats.length ? lastSeats.map(seatRow).join("") : '<span class="dim">No hands yet — be the first to deal in.</span>';
  const wrap = $("myActions"); wrap.innerHTML = "";
  for (const s of mySeats) {
    if (s.settled || !s.ready) continue;
    const b = document.createElement("button"); b.className = "primary"; b.style.flex = "1 1 auto";
    b.textContent = s.win ? "💰 Collect " + rawToNado(BigInt(s.stake) * BigInt(s.mult)) + " (seat #" + s.g + ")" : "Close out seat #" + s.g;
    b.onclick = () => settleSeat(s.g); if (s.win || iAmBank) wrap.appendChild(b);
  }
  $("btnClose").classList.toggle("hidden", !(iAmBank && tb.exists && !tb.closed && tb.settledCount >= tb.seatCount));
  $("btnClose").textContent = tb.seatCount === 0 ? "Cancel — reclaim bankroll" : "Close table — reclaim " + rawToNado(tb.pool);
  $("fundRow").classList.toggle("hidden", !(iAmBank && tb.exists && !tb.closed));
}

// ---- boot ----------------------------------------------------------------------------------------
dapp.onReturn((pend, ok, err) => {
  const label = { connect: "Signed in.", deposit: "Deposit submitted — confirming…", open: "Table opening — confirming…",
    bet: "Dealt in — confirming…", settle: "Collecting…", fund: "Topping up…", close: "Closing…", withdraw: "Withdrawal submitted." }[pend && pend.phase] || "Submitted.";
  if (pend && pend.table != null) activeTable = pend.table;
  $("status").textContent = ok ? label : "Rejected" + (err ? ": " + err : ".");
});
async function boot() {
  try { await dapp.init(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload."; return; }
  wireUI(); hoist("activeGame"); loadQR();
  const q = new URLSearchParams(location.search).get("table");
  if (q) { $("joinId").value = q; if (activeTable == null) activeTable = parseInt(q, 10); }
  render(); refreshActive();
  setInterval(refreshActive, 3000);
}
boot();
