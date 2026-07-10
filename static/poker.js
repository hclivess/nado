// poker.js — NADO Texas Hold'em: real MULTIPLAYER hold'em on the execution layer, built on the shared SDK
// (nadodapp.js). No house, no dealer, no turn order — the chain runs the whole hand:
//   · your HOLE CARDS come from a secret only your browser knows (committed as HASH(secret) when you sit
//     down — the "draw"), mixed with a future block hash, so nobody (including us) can see them;
//   · the FLOP / TURN / RIVER come from later block hashes that don't exist while you bet on them;
//   · each betting street has a deadline: match the street's highest bet to stay in, raise to push others,
//     do nothing to check — miss the price and you're folded (your chips stay in the pot);
//   · at SHOWDOWN one click reveals your secret; the CONTRACT re-derives your 7 cards and ranks the full
//     hand on-chain (straight flush … high card, kickers included — 4000/4000 differential-verified).
//     Best hand takes the pot. Board + each hand draw from independent decks (exact duplicates are legal).
import { NadoDapp, rawToNado, nadoToRaw, randId, randSecret, commitHashOf, blake2bHash, _m, $, base, gate,
         hoist, blocksToTime, lsLoad as load, lsSave as save, lsPrune, wireWallet, renderWallet, renderScore,
         scoreBump, scoreSort, recentChips, statusLabel,
         loadQR, drawQR, resolveAliases, disp, share } from "./nadodapp.js";

const CID = "25ca178d3d96db57a233af6012c38ce0";
const dapp = new NadoDapp({ cid: CID, app: "Hold'em" });
const J = 20, S = 30, GRACE = 5, R = 60;          // MUST match the contract (tests/test_holdem_contract.py)

const LS_T = "nado_holdem_tables", LS_S = "nado_holdem_seats";
let activeTable = null, lastTable = null, lastSeats = [];
let knownTables = new Set(), knownSeats = new Set();

function pruneAndTrack(sto) {
  knownTables = lsPrune(LS_T, Object.keys(_m(sto, "ta")));
  knownSeats = lsPrune(LS_S, Object.keys(_m(sto, "gg")));
}

// ---- card math (MUST mirror tests/holdem_onchain.py exactly — this is what the contract computes) -----
const H = (v) => BigInt("0x" + blake2bHash(v));    // vm HASH on a BigInt (canonicalize -> bare digits)
function drawCard(seed, slot, excl) {
  for (let a = 0; ; a++) {
    const c = Number(H(seed + BigInt(slot * 4096 + a)) % 52n);
    if (!excl.includes(c)) return c;
  }
}
const seedOf = (aHex, bHex, salt) => (aHex && bHex) ? H(BigInt("0x" + aHex) + BigInt("0x" + bHex) + BigInt(salt)) : null;
function holeCards(bhA, bhB, secret) {
  const hs = seedOf(bhA, bhB, secret); if (hs == null) return null;
  const h0 = drawCard(hs, 0, []); return [h0, drawCard(hs, 1, [h0])];
}
function boardCards(t, d0) {                         // as many streets as have finalized hashes
  const out = [];
  const e1 = seedOf(dapp.bh(d0 + S), dapp.bh(d0 + S + 1), t);
  if (e1 == null) return out;
  out.push(drawCard(e1, 0, [])); out.push(drawCard(e1, 1, out.slice())); out.push(drawCard(e1, 2, out.slice()));
  const e2 = seedOf(dapp.bh(d0 + 2 * S), dapp.bh(d0 + 2 * S + 1), t);
  if (e2 == null) return out;
  out.push(drawCard(e2, 3, out.slice()));
  const e3 = seedOf(dapp.bh(d0 + 3 * S), dapp.bh(d0 + 3 * S + 1), t);
  if (e3 == null) return out;
  out.push(drawCard(e3, 4, out.slice()));
  return out;
}
// full 7-card evaluator — mirror of eval7_ref (multi-deck; base-14 packing; ranks stored +1)
const RANK_NAMES = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"];
function eval7(cards) {
  const rc = Array(13).fill(0), sc = Array(4).fill(0);
  for (const c of cards) { rc[c % 13]++; sc[Math.floor(c / 13)]++; }
  let fs = 0; for (let s = 0; s < 4; s++) if (sc[s] >= 5) fs = s + 1;
  const sth = (pres) => {
    let best = 0;
    for (let hi = 4; hi < 13; hi++) { let ok = 1; for (let k = 0; k < 5; k++) if (!pres[hi - k]) ok = 0; if (ok) best = Math.max(best, hi + 1); }
    if (pres[12] && pres[0] && pres[1] && pres[2] && pres[3]) best = Math.max(best, 4);
    return best;
  };
  const st = sth(rc.map((c) => c > 0 ? 1 : 0));
  const fcnt = Array(13).fill(0);
  for (const c of cards) if (fs && Math.floor(c / 13) === fs - 1) fcnt[c % 13]++;
  const sfh = sth(fcnt.map((c) => c > 0 ? 1 : 0));
  const maxr = (pred) => { let b = 0; for (let r = 0; r < 13; r++) if (pred(r)) b = Math.max(b, r + 1); return b; };
  const qr = maxr((r) => rc[r] >= 4), tr = maxr((r) => rc[r] >= 3), p1 = maxr((r) => rc[r] >= 2);
  const p2 = maxr((r) => rc[r] >= 2 && r + 1 !== p1), fhp = maxr((r) => rc[r] >= 2 && r + 1 !== tr);
  const qk = maxr((r) => rc[r] >= 1 && r + 1 !== qr);
  const tk1 = maxr((r) => rc[r] >= 1 && r + 1 !== tr), tk2 = maxr((r) => rc[r] >= 1 && r + 1 !== tr && r + 1 !== tk1);
  const tpk = maxr((r) => rc[r] >= 1 && r + 1 !== p1 && r + 1 !== p2);
  const pk1 = maxr((r) => rc[r] >= 1 && r + 1 !== p1), pk2 = maxr((r) => rc[r] >= 1 && r + 1 !== p1 && r + 1 !== pk1),
        pk3 = maxr((r) => rc[r] >= 1 && r + 1 !== p1 && r + 1 !== pk1 && r + 1 !== pk2);
  const hk = []; for (let n = 0; n < 5; n++) hk.push(maxr((r) => rc[r] >= 1 && !hk.includes(r + 1)));
  const f = []; const wc = fcnt.slice();
  for (let n = 0; n < 5; n++) { const b = maxr((r) => wc[r] >= 1); f.push(b); if (b) wc[b - 1]--; }
  const pack = (cat, ts) => { let v = cat; for (let i = 0; i < 5; i++) v = v * 14 + (ts[i] || 0); return v; };
  if (sfh) return { v: pack(8, [sfh]), name: sfh === 13 ? "ROYAL FLUSH" : "Straight flush, " + RANK_NAMES[sfh - 1] + " high" };
  if (qr) return { v: pack(7, [qr, qk]), name: "Quads, " + RANK_NAMES[qr - 1] + "s" };
  if (tr && fhp) return { v: pack(6, [tr, fhp]), name: "Full house, " + RANK_NAMES[tr - 1] + "s full of " + RANK_NAMES[fhp - 1] + "s" };
  if (fs) return { v: pack(5, f), name: "Flush, " + RANK_NAMES[f[0] - 1] + " high" };
  if (st) return { v: pack(4, [st]), name: "Straight, " + RANK_NAMES[st - 1] + " high" };
  if (tr) return { v: pack(3, [tr, tk1, tk2]), name: "Three of a kind, " + RANK_NAMES[tr - 1] + "s" };
  if (p2) return { v: pack(2, [p1, p2, tpk]), name: "Two pair, " + RANK_NAMES[p1 - 1] + "s and " + RANK_NAMES[p2 - 1] + "s" };
  if (p1) return { v: pack(1, [p1, pk1, pk2, pk3]), name: "Pair of " + RANK_NAMES[p1 - 1] + "s" };
  return { v: pack(0, hk), name: RANK_NAMES[hk[0] - 1] + " high" };
}

// ---- reads ---------------------------------------------------------------------------------------
function tableFrom(sto, t) {
  t = String(t); const host = _m(sto, "ta")[t], t0 = _m(sto, "t0")[t];
  if (!host || t0 == null) return { exists: false };
  const tb = { exists: true, id: Number(t), host, t0, ante: _m(sto, "ts")[t] || 0, pot: _m(sto, "tp")[t] || 0,
    seatCount: _m(sto, "tn")[t] || 0, revealCount: _m(sto, "tx")[t] || 0,
    best: _m(sto, "tw")[t] || 0, leader: _m(sto, "tb")[t] || 0, closed: !!_m(sto, "tz")[t] };
  tb.d0 = tb.t0 + J;
  tb.price = (k) => _m(sto, "ms")[String(Number(t) * 8 + k)] || 0;
  const cur = dapp.cursor;
  if (cur != null) {
    if (cur < tb.d0) { tb.phase = "join"; tb.left = tb.d0 - cur; }
    else if (cur < tb.d0 + 4 * S) { tb.street = Math.floor((cur - tb.d0) / S) + 1; tb.phase = "street"; tb.left = tb.d0 + tb.street * S - cur; }
    else if (cur < tb.d0 + 4 * S + R) { tb.phase = "showdown"; tb.left = tb.d0 + 4 * S + R - cur; }
    else tb.phase = "over";
    if (tb.closed) tb.phase = "done";
  }
  return tb;
}
function seatsOfTable(sto, t) {
  t = String(t); const gg = _m(sto, "gg"), out = [];
  for (const g of Object.keys(gg)) if (String(gg[g]) === t) {
    const cs = [0, 1, 2, 3, 4].map((k) => k === 0 ? 0 : (_m(sto, "cs")[String(Number(g) * 8 + k)] || 0));
    const s = { g: Number(g), addr: _m(sto, "ga")[g], cs, revealed: !!_m(sto, "gd")[g],
      value: _m(sto, "gsc")[g] || 0, secret: _m(sto, "gr")[g] };
    s.total = cs.reduce((a, b) => a + b, 0);
    out.push(s);
  }
  return out.sort((a, b) => (b.value - a.value) || (a.g - b.g));
}
// folded = failed to match a CLOSED street's price (0 = still in)
function foldedAt(s, tb) {
  if (!tb.exists || tb.phase === "join" || dapp.cursor == null) return 0;
  const closed = tb.phase === "street" ? tb.street - 1 : 4;
  for (let k = 1; k <= closed; k++) if (s.cs[k] !== tb.price(k)) return k;
  return 0;
}
async function fetchTable(t) { const sto = await dapp.storage(); return sto ? tableFrom(sto, t) : null; }

// ---- actions -------------------------------------------------------------------------------------
function sit(t, method, anteRaw) {                   // open or join: generate the secret (the "draw") locally
  const g = randId(), x = randSecret();
  const Ssto = load(LS_S); Ssto[g] = { table: t, secret: x.toString(), ts: Date.now() }; save(LS_S, Ssto);
  if (method === "open") { const T = load(LS_T); T[t] = { ante: anteRaw.toString(), ts: Date.now() }; save(LS_T, T); }
  activeTable = t; render();
  dapp.call(method, [t, g, commitHashOf(x)], anteRaw,
    (method === "open" ? "open a hold'em table #" + t : "sit down at hold'em table #" + t) + " · ante " + rawToNado(anteRaw) + " NADO",
    { table: t, seat: g, phase: method });
}
async function newTable() {
  const raw = nadoToRaw($("anteAmt").value);
  if (!raw) { $("status").textContent = "Enter an ante (NADO) — everyone pays it to sit down."; return; }
  await dapp.refresh();
  if (dapp.exec < raw) { $("status").textContent = "Deposit first — your exec balance is " + rawToNado(dapp.exec) + " NADO."; return; }
  sit(randId(), "open", raw);
}
async function joinTable() {
  const t = activeTable;
  if (!t) { $("status").textContent = "Pick a table first."; return; }
  const tb = await fetchTable(t);
  if (!tb || !tb.exists) { $("status").textContent = dapp.whereIs("table", t); return; }
  if (tb.phase !== "join") { $("status").textContent = "Seating is closed — this hand is already underway. Open a new table."; return; }
  if (lastSeats.some((s) => s.addr === dapp.me)) { $("status").textContent = "You're already seated here."; return; }
  await dapp.refresh();
  const ante = BigInt(tb.ante);
  if (dapp.exec < ante) { $("status").textContent = "You need " + rawToNado(ante) + " NADO to match the ante (you have " + rawToNado(dapp.exec) + "). Deposit below."; render(); return; }
  sit(t, "join", ante);
}
function mySeat() { return lastSeats.find((s) => s.addr === dapp.me); }
function doBet(amountRaw, label) {
  const s = mySeat(); if (!s) return;
  dapp.call("bet", [s.g], amountRaw, label + " · table #" + activeTable, { table: activeTable, phase: "bet" });
}
function doReveal() {
  const s = mySeat(); if (!s) return;
  const rec = load(LS_S)[s.g];
  if (!rec || !rec.secret) { $("status").textContent = "This browser doesn't hold the secret for seat #" + s.g + " — show your cards from the device you joined with."; return; }
  dapp.call("reveal", [s.g, BigInt(rec.secret)], null, "showdown — show your cards · table #" + activeTable, { table: activeTable, phase: "reveal" });
}
const settleTable = () => dapp.call("settle", [activeTable], null, "pay the pot to the best hand · table #" + activeTable, { table: activeTable, phase: "settle" });
const reclaimTable = () => dapp.call("reclaim", [activeTable], null, "reclaim the dead pot · table #" + activeTable, { table: activeTable, phase: "reclaim" });
const cancelTable = () => dapp.call("cancel", [activeTable], null, "cancel table #" + activeTable, { table: activeTable, phase: "cancel" });

async function refreshActive() {
  await dapp.refresh();
  const sto = await dapp.storage();
  if (sto) {
    pruneAndTrack(sto);
    if (activeTable != null) {
      lastTable = tableFrom(sto, activeTable);
      if (lastTable.exists && dapp.cursor != null) {
        const d0 = lastTable.d0, need = [];
        for (const h of [d0, d0 + S, d0 + 2 * S, d0 + 3 * S]) if (dapp.cursor >= h + 1) need.push(h, h + 1);
        if (need.length) await dapp.blockHashes(need);
      }
      lastSeats = seatsOfTable(sto, activeTable);
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
    const lead = _m(sto, "tb")[t]; if (!lead) continue;             // cancelled / reclaimed hands don't rank
    const seats = Object.keys(_m(sto, "gg")).filter((g) => String(_m(sto, "gg")[g]) === String(t));
    const ante = _m(sto, "ts")[t] || 0, contrib = {}; let pot = 0;
    for (const g of seats) {
      let c = ante;
      for (let k = 1; k <= 4; k++) c += _m(sto, "cs")[String(Number(g) * 8 + k)] || 0;
      contrib[g] = c; pot += c;
    }
    for (const g of seats) {
      const won = Number(g) === lead;
      scoreBump(stats, _m(sto, "ga")[g], won ? pot - contrib[g] : -contrib[g]);
    }
  }
  return scoreSort(stats);
}
const renderScoreboard = (board) => renderScore($("scoreList"), board, dapp.me, "No finished hands yet — be the first on the board.");
function renderLobby(sto) {
  const el = $("lobbyList"); if (!el) return;
  const tables = Object.keys(_m(sto, "ta")).map((t) => tableFrom(sto, t)).filter((t) => t.exists && !t.closed);
  tables.sort((a, b) => (b.phase === "join") - (a.phase === "join") || b.id - a.id);
  el.innerHTML = tables.length ? tables.slice(0, 24).map((t) => {
    const tag = t.phase === "join" ? "🟢" : t.phase === "showdown" ? "🃏" : t.phase === "over" ? "🏁" : "▶";
    const info = t.phase === "join" ? " · seats close " + blocksToTime(t.left) : t.phase === "street" ? " · playing" : "";
    return '<button class="chip ' + (t.phase === "join" ? "betting" : "") + '" data-t="' + t.id + '">' + tag + " #" + t.id
      + " · ante " + rawToNado(t.ante) + " · " + t.seatCount + " player" + (t.seatCount === 1 ? "" : "s") + info + "</button>";
  }).join(" ") : '<span class="dim">No tables yet — open one below.</span>';
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => selectTable(parseInt(b.dataset.t, 10)));
}
function selectTable(id) {
  activeTable = id; $("joinId").value = String(id);
  $("status").textContent = "Table #" + id + " selected.";
  refreshActive();
  try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {}
}

// ---- card rendering (rank top-left, suit centered, correct red/black) ------------------------------
const SUITS = ["♠", "♥", "♦", "♣"];                 // suit = card // 13 : 0=♠ 1=♥ 2=♦ 3=♣
function cardHTML(c, big) {
  if (c == null) return '<div class="card back' + (big ? " big" : "") + '"></div>';
  const r = RANK_NAMES[c % 13], s = Math.floor(c / 13), red = (s === 1 || s === 2);
  return '<div class="card' + (red ? " red" : "") + (big ? " big" : "") + '">' + r + '<span class="suit">' + SUITS[s] + "</span></div>";
}
const handHTML = (cards, n, big) => Array.from({ length: n }, (_, i) => cardHTML(cards && cards[i] != null ? cards[i] : null, big)).join("");

// ---- render --------------------------------------------------------------------------------------
function wireUI() {
  wireWallet(dapp);
  $("btnNewTable").onclick = newTable;
  $("btnGoTable").onclick = () => { const id = parseInt($("joinId").value, 10); if (id) selectTable(id); else $("status").textContent = "Enter a table ID, or pick one from the lobby."; };
  $("btnReclaim").onclick = reclaimTable;
  $("btnCancel").onclick = cancelTable;
  $("btnShare").onclick = () => share(base() + "/?table=" + activeTable, "Sit down at my hold'em table #" + activeTable + " on NADO:", $("btnShare"));
}
function render() {
  const signedIn = renderWallet(dapp);
  gate({ play: signedIn, opencard: signedIn, bankroll: signedIn, activeGame: activeTable != null });
  const T = load(LS_T), Ssto = load(LS_S), mine = [];
  for (const t of Object.keys(T)) mine.push({ id: +t, role: "host", ts: T[t].ts });
  for (const g of Object.keys(Ssto)) mine.push({ id: Ssto[g].table, seat: g, role: "seat", ts: Ssto[g].ts });
  mine.sort((a, b) => b.ts - a.ts); const seen = new Set();
  const shown = mine.filter((x) => { x.live = x.role === "host" ? knownTables.has(String(x.id)) : knownSeats.has(String(x.seat)); x.icon = "🃏"; const k = x.id + x.role; if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 8);
  recentChips($("recent"), shown, selectTable, "No tables yet.");
  renderActive();
}
const STREETS = ["", "pre-flop", "flop", "turn", "river"];
function renderActive() {
  if (activeTable == null) return;
  const tb = lastTable || {}, T = load(LS_T)[activeTable] || {};
  const me = mySeat(), iAmHost = tb.host === dapp.me;
  $("gameId").textContent = "#" + activeTable;
  $("shareLink").value = base() + "/?table=" + activeTable;
  drawQR($("shareQR"), $("shareQRNote"), base() + "/?table=" + activeTable, 180);
  $("gPot").textContent = tb.exists ? rawToNado(tb.pot) + " NADO" : "—";
  $("gAnte").textContent = tb.exists ? rawToNado(tb.ante) + " NADO" : "—";

  // headline: phase + countdown — always says what happens next
  let phaseTxt = dapp.whereIs("table", activeTable, T.ts);
  if (tb.exists) {
    if (tb.closed) phaseTxt = "hand over — settled ✓";
    else if (tb.phase === "join") phaseTxt = "🟢 seating open — cards deal in " + blocksToTime(tb.left) + " · " + tb.seatCount + " player" + (tb.seatCount === 1 ? "" : "s");
    else if (tb.phase === "street") phaseTxt = "▶ " + STREETS[tb.street].toUpperCase() + " betting — street closes in " + blocksToTime(tb.left);
    else if (tb.phase === "showdown") phaseTxt = "🃏 SHOWDOWN — show your cards within " + blocksToTime(tb.left) + " · " + tb.revealCount + " shown";
    else phaseTxt = "🏁 hand finished — pay out below";
  }
  $("gStatus").textContent = phaseTxt;

  // the felt: community + my hole cards
  const board = tb.exists && tb.phase !== "join" && dapp.cursor != null ? boardCards(activeTable, tb.d0) : [];
  $("community").innerHTML = handHTML(board, 5, false);
  $("communityNote").textContent = !tb.exists ? "" :
    tb.phase === "join" ? "the board deals street by street once seating closes" :
    board.length === 0 ? "flop lands when its block finalizes…" :
    board.length === 3 ? "turn card is still in future blocks" :
    board.length === 4 ? "river card is still in future blocks" : "";
  let hole = null, holeTxt = "";
  const fk = me && tb.exists ? foldedAt(me, tb) : 0;
  if (me && tb.exists && tb.phase !== "join") {
    const rec = load(LS_S)[me.g];
    if (rec && rec.secret) hole = holeCards(dapp.bh(tb.d0), dapp.bh(tb.d0 + 1), BigInt(rec.secret));
    holeTxt = !rec || !rec.secret ? "your secret lives in the browser you joined with — open this page there to see your cards"
      : !hole ? "your hole cards land when the deal block finalizes…" : "";
  } else if (me) holeTxt = "your hole cards deal when seating closes";
  $("holeWrap").classList.toggle("hidden", !me);
  $("hole").innerHTML = handHTML(hole, 2, true);
  let handName = "";
  if (hole && board.length >= 3) handName = eval7(board.concat(hole)).name + (board.length < 5 ? " (so far)" : "");
  else if (hole) handName = "your hole cards — the flop comes next";
  $("holeNote").textContent = fk ? "✗ folded on the " + STREETS[fk] + " — your chips stay in the pot" : (handName || holeTxt);

  // players
  const priceNow = tb.exists && tb.phase === "street" ? tb.price(tb.street) : 0;
  $("seats").innerHTML = lastSeats.length ? lastSeats.map((s) => {
    const you = s.addr === dapp.me ? '<b style="color:var(--accent2)">you</b> ' : "";
    const f = tb.exists ? foldedAt(s, tb) : 0;
    let tag;
    if (s.revealed) {
      const oppHole = s.secret != null ? holeCards(dapp.bh(tb.d0), dapp.bh(tb.d0 + 1), BigInt(s.secret)) : null;
      const nm = oppHole && board.length === 5 ? eval7(board.concat(oppHole)).name : "shown";
      tag = '<span class="minihand">' + (oppHole ? handHTML(oppHole, 2, false) : "") + '</span> <span class="b ' + (tb.leader === s.g ? 'ok">👑 ' : 'dimb">') + nm + "</span>";
    }
    else if (f) tag = '<span class="b dimb">folded (' + STREETS[f] + ")</span>";
    else if (tb.phase === "street" && s.cs[tb.street] < priceNow) tag = '<span class="b pend">must call ' + rawToNado(priceNow - s.cs[tb.street]) + "</span>";
    else if (tb.phase === "showdown") tag = '<span class="b pend">yet to show</span>';
    else tag = '<span class="b ok">in ✓</span>';
    return '<div class="seat">' + you + disp(s.addr) + ' · <span class="mono">' + rawToNado(s.total + Number(tb.ante || 0)) + "</span> " + tag + "</div>";
  }).join("") : '<span class="dim">No players yet.</span>';

  // actions — ONE obvious primary thing to do at every phase
  const wrap = $("myActions"); wrap.innerHTML = "";
  const btn = (txt, fn, primary) => { const b = document.createElement("button"); b.className = primary ? "primary" : "ghost"; b.style.flex = "1 1 auto"; b.textContent = txt; b.onclick = fn; wrap.appendChild(b); return b; };
  const betRow = $("betRow");
  betRow.classList.add("hidden");
  if (tb.exists && !tb.closed && dapp.me) {
    if (tb.phase === "join" && !me) btn("🪑 Sit down — ante " + rawToNado(tb.ante) + " NADO", joinTable, true);
    if (tb.phase === "street" && me && !fk) {
      betRow.classList.remove("hidden");
      const myIn = me.cs[tb.street], owe = priceNow - myIn;
      $("betInfo").innerHTML = priceNow
        ? "Street price <b>" + rawToNado(priceNow) + "</b> · you're in for <b>" + rawToNado(myIn) + "</b>" + (owe > 0 ? ' · <b class="warn">call ' + rawToNado(owe) + " or fold when the street closes</b>" : " · matched ✓ (do nothing to check)")
        : "No bets yet this street — do nothing to <b>check</b>, or open the betting below.";
      if (owe > 0) btn("📞 Call " + rawToNado(owe) + " — stay in", () => doBet(BigInt(owe), "call " + rawToNado(owe) + " NADO"), true);
      const canRaise = tb.left > GRACE;
      const rb = btn(canRaise ? "⬆ Bet / raise the amount above" : "⬆ Raising closed (last " + GRACE + " blocks are calls only)", () => {
        const raw = nadoToRaw($("betAmt").value);
        if (!raw) { $("status").textContent = "Enter an amount — your street total above " + rawToNado(priceNow) + " raises the price for everyone."; return; }
        if (dapp.exec < raw) { $("status").textContent = "You only have " + rawToNado(dapp.exec) + " NADO playable — deposit below."; return; }
        doBet(raw, "bet " + rawToNado(raw) + " NADO");
      }, owe <= 0);
      rb.disabled = !canRaise;
    }
    if (tb.phase === "showdown" && me && !fk && !me.revealed) btn("🃏 Show your cards — claim the pot", doReveal, true);
    if (tb.phase === "over" && tb.leader) btn("🏆 Pay the pot to the best hand (" + rawToNado(tb.pot) + ")", settleTable, true);
  }
  $("btnReclaim").classList.toggle("hidden", !(tb.exists && !tb.closed && tb.phase === "over" && !tb.leader && iAmHost));
  $("btnCancel").classList.toggle("hidden", !(tb.exists && !tb.closed && tb.seatCount === 1 && iAmHost));
  const jh = $("joinHint");
  const hint = dapp.me && activeTable != null && !tb.exists ? dapp.whereIs("table", activeTable, T.ts) : "";
  if (jh) { jh.textContent = hint; jh.classList.toggle("hidden", !hint); }
}

// ---- boot ----------------------------------------------------------------------------------------
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.table != null) activeTable = pend.table;
  $("status").textContent = statusLabel(pend, ok, err, {
    open: "Table opening — confirming…", join: "Taking your seat — confirming…", bet: "Bet placed — confirming…",
    reveal: "Showing your cards — confirming…", settle: "Paying the winner…", reclaim: "Reclaiming…", cancel: "Cancelling…" });
});
async function boot() {
  try { await dapp.init(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload."; return; }
  wireUI(); loadQR(); hoist("activeGame");
  const q = new URLSearchParams(location.search).get("table");
  if (q) { $("joinId").value = q; if (activeTable == null) activeTable = parseInt(q, 10); }
  render(); refreshActive();
  setInterval(refreshActive, 3000);
}
boot();
