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
import { NadoDapp, rawToNado, nadoToRaw, randId, randSecret, commitHashOf, blake2bHash, _m, $, base, gate, canPay, alertBar, inviteGate,
         hoist, orderCards, blocksToTime, lsLoad as load, lsSave as save, lsPrune, wireWallet, stickyInputs, renderWallet, renderScore,
         scoreBump, scoreSort, recentChips, statusLabel,
         loadQR, drawQR, resolveAliases, disp, share, shareInvite } from "./nadodapp.js";

const CID = "ac32e1e848c3fcb6277a2ba40b4fbeda";
const GICON = '<svg style="vertical-align:-3px" viewBox="0 0 48 48" width="16" height="16" aria-hidden="true">     <rect x="8" y="13" width="18" height="24" rx="3" fill="#e6edf3" stroke="#243140" stroke-width="1.6" transform="rotate(-9 17 25)"/>     <path d="M14 20c-2.4 2.4-4 3.4-4 5.4 0 1.4 1.1 2.2 2.2 2.2.5 0 1-.2 1.3-.5-.2 1-.6 1.7-1.2 2.2h3.4c-.6-.5-1-1.2-1.2-2.2.3.3.8.5 1.3.5 1.1 0 2.2-.8 2.2-2.2 0-2-1.6-3-4-5.4z" fill="#20272f" transform="rotate(-9 14 25)"/>     <rect x="22" y="13" width="18" height="24" rx="3" fill="#fff" stroke="#243140" stroke-width="1.6" transform="rotate(9 31 25)"/>     <path d="M31 30c-.7-.7-3.2-2.3-3.2-4.6 0-1.3 1-2.2 2.1-2.2.6 0 1.1.3 1.1.9 0-.6.5-.9 1.1-.9 1.1 0 2.1.9 2.1 2.2 0 2.3-2.5 3.9-3.2 4.6z" fill="#d0362b" transform="rotate(9 31 26)"/></svg>';
const dapp = new NadoDapp({ cid: CID, app: "Hold'em" });
const F0 = 14, S = 20, GRACE = 5, R = 60;         // MUST match the contract (tests/test_holdem_contract.py)
// NO seating timer: the HOST controls the start — start(t) binds the deal to two future blocks (td).
// b0 = td+F0: the SHUFFLE — betting opens only once hole cards are finalized (no blind pre-flop).
// Streets are CEILINGS: the host may close_street() the moment nobody owes a call (c_k = sc[t*8+k]).

const LS_T = "nado_holdem_tables", LS_S = "nado_holdem_seats";
let lastSto = null;
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
function boardCards(t, closes) {                     // as many streets as have hashes; seeds = ACTUAL close blocks
  const out = [];
  const e1 = seedOf(dapp.bh(closes[1]), dapp.bh(closes[1] + 1), t);
  if (e1 == null) return out;
  out.push(drawCard(e1, 0, [])); out.push(drawCard(e1, 1, out.slice())); out.push(drawCard(e1, 2, out.slice()));
  const e2 = seedOf(dapp.bh(closes[2]), dapp.bh(closes[2] + 1), t);
  if (e2 == null) return out;
  out.push(drawCard(e2, 3, out.slice()));
  const e3 = seedOf(dapp.bh(closes[3]), dapp.bh(closes[3] + 1), t);
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
  tb.td = _m(sto, "td")[t] || 0;                   // deal anchor — 0 until the HOST deals
  tb.d0 = tb.td;
  tb.price = (k) => _m(sto, "ms")[String(Number(t) * 8 + k)] || 0;
  // betting timeline: b0 = td+F0 (the shuffle ends, cards visible), c_k = forced close or c_{k-1}+S
  tb.b0 = tb.td ? tb.td + F0 : 0;
  tb.closes = [tb.b0, 0, 0, 0, 0];
  for (let k = 1; k <= 4; k++) tb.closes[k] = (_m(sto, "sc")[String(Number(t) * 8 + k)] || 0) || tb.closes[k - 1] + S;
  const cur = dapp.cursor;
  if (cur != null) {
    if (!tb.td) tb.phase = "join";                                       // seating open — host hasn't dealt
    else if (cur < tb.b0) { tb.phase = "shuffle"; tb.left = tb.b0 - cur; }
    else if (cur < tb.closes[4]) {
      tb.street = 1 + (cur >= tb.closes[1]) + (cur >= tb.closes[2]) + (cur >= tb.closes[3]);
      tb.phase = "street"; tb.left = tb.closes[tb.street] - cur;
    }
    else if (cur < tb.closes[4] + R) { tb.phase = "showdown"; tb.left = tb.closes[4] + R - cur; }
    else tb.phase = "over";
    // EARLY SETTLE: every seat revealed — the contract accepts settle right now
    if (tb.phase === "showdown" && tb.seatCount > 0 && tb.revealCount >= tb.seatCount) tb.phase = "over";
    if (tb.closed) tb.phase = "done";
  }
  return tb;
}
function seatsOfTable(sto, t) {
  t = String(t); const tn = _m(sto, "tn")[t] || 0, out = [];
  for (let i = 0; i < tn; i++) {                 // JOIN ORDER via the ti index — side pots depend on it
    const g = _m(sto, "ti")[String(Number(t) * 16 + i)];
    if (!g) continue;
    const cs = [0, 1, 2, 3, 4].map((k) => k === 0 ? 0 : (_m(sto, "cs")[String(Number(g) * 8 + k)] || 0));
    const s = { g: Number(g), idx: i, addr: _m(sto, "ga")[g], cs, stack: _m(sto, "gk")[g] || 0,
      revealed: !!_m(sto, "gd")[g], value: _m(sto, "gsc")[g] || 0, secret: _m(sto, "gr")[g] };
    s.total = cs.reduce((a, b) => a + b, 0);     // street chips (ante on top of this)
    out.push(s);
  }
  return out;
}
// folded = below a CLOSED street's price while still holding chips (all-in players are never folded)
function foldedAt(s, tb) {
  if (!tb.exists || tb.phase === "join" || tb.phase === "shuffle" || dapp.cursor == null) return 0;
  const closed = tb.phase === "street" ? tb.street - 1 : 4;
  for (let k = 1; k <= closed; k++) if (s.cs[k] !== tb.price(k) && s.stack > 0) return k;
  return 0;
}
// side-pot layers — EXACT mirror of the contract's settle (tests/test_holdem_contract.py settle_ref)
function sidePots(seats, ante) {
  const C = seats.map((s) => Number(ante) + s.total);
  const V = seats.map((s) => (s.revealed && !foldedAt(s, lastTable) ? s.value : 0));
  const pots = []; let prev = 0;
  for (let pass = 0; pass < 10; pass++) {
    let L = 0;
    for (const c of C) if (c > prev && (L === 0 || c < L)) L = c;
    if (!L) break;
    const idxs = C.map((c, i) => c >= L ? i : -1).filter((i) => i >= 0);
    pots.push({ amt: (L - prev) * idxs.length, idxs });
    prev = L;
  }
  return pots;
}
async function fetchTable(t) { const sto = await dapp.storage(); return sto ? tableFrom(sto, t) : null; }

// ---- actions -------------------------------------------------------------------------------------
function sit(t, method, buyinRaw, anteRaw) {         // open or join: generate the secret (the "draw") locally
  const g = randId(), x = randSecret();
  const Ssto = load(LS_S); Ssto[g] = { table: t, secret: x.toString(), ts: Date.now() }; save(LS_S, Ssto);
  if (method === "open") { const T = load(LS_T); T[t] = { ante: anteRaw.toString(), ts: Date.now() }; save(LS_T, T); }
  activeTable = t; render();
  const args = method === "open" ? [t, g, commitHashOf(x), anteRaw] : [t, g, commitHashOf(x)];
  dapp.call(method, args, buyinRaw,
    (method === "open" ? "open a hold'em table #" + t : "sit down at hold'em table #" + t)
      + " · buy-in " + rawToNado(buyinRaw) + " NADO (ante " + rawToNado(anteRaw) + ", stack " + rawToNado(buyinRaw - anteRaw) + ")",
    { table: t, seat: g, phase: method });
}
function readBuyin(anteRaw) {
  const raw = nadoToRaw($("buyinAmt").value);
  if (!raw) { alertBar("Enter your BUY-IN — the ante (" + rawToNado(anteRaw) + " NADO) goes to the pot, the rest is your stack to bet with. A common buy-in is 20–50× the ante."); return null; }
  if (raw < anteRaw) { alertBar("The buy-in must at least cover the ante (" + rawToNado(anteRaw) + " NADO)."); return null; }
  return raw;
}
async function newTable() {
  const ante = nadoToRaw($("anteAmt").value);
  if (!ante) { $("status").textContent = "Enter an ante (NADO) — everyone pays it into the pot to sit down."; return; }
  const buyin = readBuyin(ante); if (!buyin) return;
  await dapp.refresh();
  if (!canPay(dapp, buyin, "Opening this table")) return;
  sit(randId(), "open", buyin, ante);
}
function reopenTable() {   // retry an open that didn't confirm within ~2 min
  const T = load(LS_T)[activeTable]; if (!T || !T.ante) return;
  const buyin = nadoToRaw($("buyinAmt").value) || BigInt(T.ante);
  if (!canPay(dapp, buyin, "Re-opening this table")) return;
  sit(activeTable, "open", buyin, BigInt(T.ante));
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
  const buyin = readBuyin(ante); if (!buyin) return;
  if (!canPay(dapp, buyin, "Sitting down")) { render(); return; }
  sit(t, "join", buyin, ante);
}
function mySeat() { return lastSeats.find((s) => s.addr === dapp.me); }
function doBet(amountRaw, label) {
  const s = mySeat(); if (!s) return;
  const k = lastTable && lastTable.street || 1;
  // amount is an ARG (chips move from your escrowed stack, no new value) — confirm:true so autosign never bets
  dapp.call("bet", [s.g, amountRaw], null, label + " · table #" + activeTable,
    { table: activeTable, seat: s.g, phase: "bet", k, prev: s.cs[k] }, { confirm: true });
}
function doReveal() {
  const s = mySeat(); if (!s) return;
  const rec = load(LS_S)[s.g];
  if (!rec || !rec.secret) { $("status").textContent = "This browser doesn't hold the secret for seat #" + s.g + " — show your cards from the device you joined with."; return; }
  dapp.call("reveal", [s.g, BigInt(rec.secret)], null, "showdown — show your cards · table #" + activeTable, { table: activeTable, seat: s.g, phase: "reveal" });
}
const settleTable = () => dapp.call("settle", [activeTable], null, "pay the pot to the best hand · table #" + activeTable, { table: activeTable, phase: "settle" });
const reclaimTable = () => dapp.call("reclaim", [activeTable], null, "reclaim the dead pot · table #" + activeTable, { table: activeTable, phase: "reclaim" });
const cancelTable = () => dapp.call("cancel", [activeTable], null, "cancel table #" + activeTable, { table: activeTable, phase: "cancel" });
// the HOST deals: binds the hand to two blocks that don't exist yet — nobody can know the cards
const startTable = () => dapp.call("start", [activeTable], null, "🃏 deal now · table #" + activeTable, { table: activeTable, phase: "start" });
// the HOST fast-forwards a street once nobody owes a call — a checked-around street ends NOW
const closeStreet = () => dapp.call("close_street", [activeTable], null, "⏩ close the " + STREETS[(lastTable && lastTable.street) || 1] + " · table #" + activeTable,
  { table: activeTable, phase: "closest", k: (lastTable && lastTable.street) || 1 });
function leaveTable() {
  const s = mySeat(); if (!s) return;
  dapp.call("leave", [s.g], null, "leave table #" + activeTable + " — full refund", { table: activeTable, seat: s.g, phase: "leave" });
}

async function refreshActive() {
  await dapp.refresh();
  const sto = await dapp.storage();
  if (sto) {
    lastSto = sto;
    pruneAndTrack(sto);
    if (activeTable != null) {
      lastTable = tableFrom(sto, activeTable);
      if (lastTable.exists && lastTable.td && dapp.cursor != null) {
        const d0 = lastTable.d0, pub = [];
        // HOLE-CARD seeds (d0, d0+1) stay FINALIZED — hidden info; a provisional reorg would silently
        // change your hand at showdown. The COMMUNITY streets are public -> provisional (fast) is safe.
        if (dapp.cursor >= d0 + 1) await dapp.blockHashes([d0, d0 + 1]);
        for (const h of [lastTable.closes[1], lastTable.closes[2], lastTable.closes[3]]) if (dapp.cursor >= h + 1) pub.push(h, h + 1);
        if (pub.length) await dapp.blockHashes(pub, { fast: true });
      }
      lastSeats = seatsOfTable(sto, activeTable);
    }
    if (watch) {
      const done =
        (watch.phase === "open" || watch.phase === "join") ? !!_m(sto, "gg")[String(watch.seat)] :
        (watch.phase === "bet") ? (_m(sto, "cs")[String(watch.seat * 8 + watch.k)] || 0) > (watch.prev || 0) :
        (watch.phase === "reveal") ? !!_m(sto, "gd")[String(watch.seat)] :
        (watch.phase === "start") ? (_m(sto, "td")[String(watch.table)] || 0) > 0 :
        (watch.phase === "closest") ? (_m(sto, "sc")[String(Number(watch.table) * 8 + watch.k)] || 0) > 0 :
        (watch.phase === "leave") ? !_m(sto, "gg")[String(watch.seat)] :
        (watch.phase === "settle") ? !!_m(sto, "tz")[String(watch.table)] : false;
      if (done) {
        $("status").textContent = { open: "✓ Table confirmed — you're seated. Share the link below to fill it.",
          join: "✓ Seat confirmed — you're in the hand.", bet: "✓ Bet confirmed on-chain.",
          reveal: "✓ Your hand is shown on-chain.", settle: "✓ Pot paid out.",
          start: "✓ Dealt! Cards are locking in the next blocks — hole cards appear once they finalize.",
          closest: "✓ Street closed — the next card is locking in now.",
          leave: "✓ You left the table — buy-in refunded in full." }[watch.phase];
        watch = null;
      }
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
    const info = t.phase === "join" ? " · seating open" : t.phase === "street" || t.phase === "dealing" ? " · playing" : "";
    return '<button class="chip ' + (t.phase === "join" ? "betting" : "") + '" data-t="' + t.id + '">' + tag + " #" + t.id
      + " · ante " + rawToNado(t.ante) + " · " + t.seatCount + " player" + (t.seatCount === 1 ? "" : "s") + info + "</button>";
  }).join(" ") : '<span class="dim">No tables yet — open one below.</span>';
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => selectTable(parseInt(b.dataset.t, 10)));
}
let buyinEdited = false;   // the player typed their own buy-in — stop auto-suggesting
function selectTable(id) {
  activeTable = id; $("joinId").value = String(id);
  buyinEdited = false;     // fresh table -> fresh suggestion (match the host)
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
  stickyInputs(dapp, ['anteAmt', 'betAmt', 'bankAmt', 'stakeAmt']);   // typed amounts persist across turns
  // the BUY-IN is context-dependent (never sticky, never a fixed default): it follows the ante when you
  // open (20x) and matches the HOST's buy-in when you join — until you type your own number.
  $("buyinAmt").addEventListener("input", () => { buyinEdited = true; });
  $("anteAmt").addEventListener("input", () => {
    if (buyinEdited) return;
    const a = parseFloat($("anteAmt").value);
    if (a > 0) $("buyinAmt").value = String(Math.round(a * 20 * 1e6) / 1e6);
  });
  if (!$("buyinAmt").value) $("buyinAmt").value = String((parseFloat($("anteAmt").value) || 1) * 20);
  $("btnNewTable").onclick = newTable;
  $("btnGoTable").onclick = () => { const id = parseInt($("joinId").value, 10); if (id) selectTable(id); else $("status").textContent = "Enter a table ID, or pick one from the lobby."; };
  $("btnReclaim").onclick = reclaimTable;
  $("btnCancel").onclick = cancelTable;
  if ($("btnReopen")) $("btnReopen").onclick = reopenTable;
  $("btnShare").onclick = () => share(base() + "/?table=" + activeTable, "Sit down at my hold'em table #" + activeTable + " on NADO:", $("btnShare"));
}
function render() {
  const signedIn = renderWallet(dapp);
  gate({ play: signedIn, opencard: signedIn, bankroll: signedIn, activeGame: activeTable != null });
  const T = load(LS_T), Ssto = load(LS_S), mine = [];
  for (const t of Object.keys(T)) mine.push({ id: +t, role: "host", ts: T[t].ts });
  for (const g of Object.keys(Ssto)) mine.push({ id: Ssto[g].table, seat: g, role: "seat", ts: Ssto[g].ts });
  mine.sort((a, b) => b.ts - a.ts); const seen = new Set();
  const shown = mine.filter((x) => { x.live = x.role === "host" ? knownTables.has(String(x.id)) : knownSeats.has(String(x.seat)); x.icon = GICON; const k = String(x.id); if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 8);
  for (const x of shown) {
    if (!x.live || !lastSto) continue;
    const tb = tableFrom(lastSto, x.id);
    if (!tb.exists) continue;
    x.tag = tb.closed ? "finished ✓" : tb.phase === "join" ? "seating" : tb.phase === "street" ? STREETS[tb.street] : tb.phase === "showdown" ? "SHOWDOWN" : "settle!";
  }
  recentChips($("recent"), shown, selectTable, "No tables yet.");
  renderActive();
}
const STREETS = ["", "pre-flop", "flop", "turn", "river"];
function renderActive() {
  if (activeTable == null) return;
  const tb = lastTable || {}, T = load(LS_T)[activeTable] || {};
  const me = mySeat(), iAmHost = tb.host === dapp.me;
  $("gameId").textContent = "#" + activeTable;
  shareInvite("table", activeTable, "Sit down at my hold em table #" + activeTable + " on NADO:", 180);
  $("gPot").textContent = tb.exists ? rawToNado(tb.pot) + " NADO" : "—";
  if ($("gPots")) {
    const pots = tb.exists && tb.phase !== "join" && lastSeats.length ? sidePots(lastSeats, tb.ante) : [];
    $("gPots").innerHTML = pots.length > 1 ? pots.map((p, n) =>
      '<div class="kv"><span class="k">' + (n === 0 ? "Main pot" : "Side pot " + n) + " (" + p.idxs.map((i) => disp(lastSeats[i].addr)).join(", ") + ')</span><span class="mono">' + rawToNado(p.amt) + " NADO</span></div>").join("") : "";
  }
  $("gAnte").textContent = tb.exists ? rawToNado(tb.ante) + " NADO" : "—";

  // headline: phase + countdown — always says what happens next
  let phaseTxt = dapp.whereIs("table", activeTable, T.ts);
  if (tb.exists) {
    if (tb.closed) phaseTxt = "hand over — settled ✓";
    else if (tb.phase === "join") phaseTxt = "🟢 seating open — " + tb.seatCount + " player" + (tb.seatCount === 1 ? "" : "s") + " · " + (tb.host === dapp.me ? "YOU deal when ready" : "the host deals when ready");
    else if (tb.phase === "shuffle") phaseTxt = "🂠 shuffling — your cards land in " + blocksToTime(tb.left) + " (betting opens with cards visible)";
    else if (tb.phase === "street") phaseTxt = "▶ " + STREETS[tb.street].toUpperCase() + " betting — closes in " + blocksToTime(tb.left) + " (or when the host fast-forwards)";
    else if (tb.phase === "showdown") phaseTxt = "🃏 SHOWDOWN — show your cards within " + blocksToTime(tb.left) + " · " + tb.revealCount + " shown";
    else phaseTxt = "🏁 hand finished — pay out below";
  }
  $("gStatus").textContent = phaseTxt;

  // the felt: community + my hole cards
  const board = tb.exists && tb.td && dapp.cursor != null ? boardCards(activeTable, tb.closes) : [];
  $("community").innerHTML = handHTML(board, 5, false);
  $("communityNote").textContent = !tb.exists ? "" :
    tb.phase === "join" ? "the board deals street by street once the host deals" :
    board.length === 0 ? "flop lands when its block finalizes…" :
    board.length === 3 ? "turn card is still in future blocks" :
    board.length === 4 ? "river card is still in future blocks" : "";
  let hole = null, holeTxt = "";
  const fk = me && tb.exists ? foldedAt(me, tb) : 0;
  if (me && tb.exists && tb.td) {
    const rec = load(LS_S)[me.g];
    if (rec && rec.secret) hole = holeCards(dapp.bh(tb.d0), dapp.bh(tb.d0 + 1), BigInt(rec.secret));
    holeTxt = !rec || !rec.secret ? "your secret lives in the browser you joined with — open this page there to see your cards"
      : !hole ? "your hole cards land when the deal blocks finalize…" : "";
  } else if (me) holeTxt = tb.host === dapp.me ? "hit 🃏 Deal now below when everyone's seated" : "your hole cards deal when the host starts the hand";
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
    const allin = s.stack === 0 && !f && tb.exists && tb.phase !== "join" ? ' <span class="b pend">ALL-IN</span>' : "";
    return '<div class="seat">' + you + disp(s.addr) + ' · in pot <span class="mono">' + rawToNado(s.total + Number(tb.ante || 0)) + '</span> · stack <span class="mono">' + rawToNado(s.stack) + "</span>" + allin + " " + tag + "</div>";
  }).join("") : '<span class="dim">No players yet.</span>';

  // actions — ONE obvious primary thing to do at every phase
  const wrap = $("myActions"); wrap.innerHTML = "";
  const btn = (txt, fn, primary) => { const b = document.createElement("button"); b.className = primary ? "primary" : "ghost"; b.style.flex = "1 1 auto"; b.textContent = txt; b.onclick = fn; wrap.appendChild(b); return b; };
  const betRow = $("betRow");
  betRow.classList.add("hidden");
  // joining? suggest the HOST's buy-in (ante + host stack) so a 0.1-ante table never asks for 20 NADO
  if (tb.exists && tb.phase === "join" && !me && !buyinEdited && lastSeats.length) {
    const host = lastSeats.find((s) => s.addr === tb.host) || lastSeats[0];
    $("buyinAmt").value = rawToNado(Number(tb.ante) + host.stack);
  }
  if (tb.exists && !tb.closed && dapp.me) {
    if (tb.phase === "join" && !me) {
      if (watch && watch.phase === "join") btn("⏳ Taking your seat — confirming on-chain…", () => {}, false).disabled = true;
      else btn("🪑 Sit down — buy-in " + ($("buyinAmt").value || rawToNado(tb.ante)) + " NADO (ante " + rawToNado(tb.ante) + ")", joinTable, true);
    }
    if (tb.phase === "street" && iAmHost) {
      // closable iff nobody owes a call: every seat matched the street price, is all-in, or folded earlier
      const pk = tb.price(tb.street);
      const closable = lastSeats.length > 0 && lastSeats.every((s) => s.cs[tb.street] === pk || s.stack === 0 || foldedAt(s, tb) > 0)
        && !((_m(lastSto, "sc")[String(Number(activeTable) * 8 + tb.street)] || 0) > 0);
      if (watch && watch.phase === "closest") btn("⏳ Fast-forwarding the street…", () => {}, false).disabled = true;
      else if (closable) btn("⏩ Everyone's in — deal the next card NOW", closeStreet, true);
    }
    // the HOST controls the start — nothing happens until they deal
    if (tb.phase === "join" && iAmHost) {
      if (watch && watch.phase === "start") btn("⏳ Dealing — confirming on-chain…", () => {}, false).disabled = true;
      else btn(tb.seatCount >= 2 ? "🃏 Deal now — start the hand (" + tb.seatCount + " players)"
                                 : "🃏 Deal now — or wait for players (share the invite below)", startTable, tb.seatCount >= 2);
    }
    if (tb.phase === "join" && me && !iAmHost) {
      if (watch && watch.phase === "leave") btn("⏳ Leaving — refunding…", () => {}, false).disabled = true;
      else btn("🚪 Leave the table — full refund (ante + stack)", leaveTable, false);
    }
    if (tb.phase === "shuffle") {
      const note = document.createElement("div"); note.className = "small"; note.style.cssText = "flex:1 1 100%;color:var(--accent2);font-weight:700";
      note.textContent = "🂠 Shuffling — your hole cards lock to blocks " + tb.d0 + "–" + (tb.d0 + 1) + " and appear once final; betting opens right after.";
      wrap.appendChild(note);
    }
    const rec = me ? (load(LS_S)[me.g] || {}) : {};
    const localFold = !!rec.folded;
    const setFold = (v) => { const S = load(LS_S); if (S[me.g]) { S[me.g].folded = v ? Date.now() : 0; save(LS_S, S); } render(); };
    if (tb.phase === "street" && me && !fk && localFold) {
      const note = document.createElement("div"); note.className = "small"; note.style.cssText = "flex:1 1 100%;color:var(--dim);font-weight:700";
      note.textContent = "✋ You folded — sitting this hand out. Your chips stay in the pot.";
      wrap.appendChild(note);
      btn("↩ Undo fold — you can still call until the street closes", () => setFold(false), false);
    }
    if (tb.phase === "street" && me && !fk && !localFold && me.stack === 0) {
      const note = document.createElement("div"); note.className = "small"; note.style.cssText = "flex:1 1 100%;color:var(--accent2);font-weight:700";
      note.textContent = "🔥 You're ALL-IN — nothing left to do; you're live for every pot you funded.";
      wrap.appendChild(note);
    }
    if (tb.phase === "street" && me && !fk && !localFold && me.stack > 0) {
      betRow.classList.remove("hidden");
      const myIn = me.cs[tb.street], owe = priceNow - myIn;
      $("betInfo").innerHTML = "Your stack <b>" + rawToNado(me.stack) + "</b> · " + (priceNow
        ? "street price <b>" + rawToNado(priceNow) + "</b> · you're in for <b>" + rawToNado(myIn) + "</b>" + (owe > 0 ? ' · <b class="warn">call ' + rawToNado(owe > me.stack ? me.stack : owe) + (owe > me.stack ? " (all-in)" : "") + " or fold when the street closes</b>" : " · matched ✓ (do nothing to check)")
        : "no bets yet this street — do nothing to <b>check</b>, or open the betting below.");
      if (owe > 0) {
        const callAmt = owe > me.stack ? me.stack : owe;
        btn((owe > me.stack ? "🔥 Call ALL-IN " : "📞 Call ") + rawToNado(callAmt) + " — stay in", () => doBet(BigInt(callAmt), "call " + rawToNado(callAmt) + " NADO"), true);
      }
      const canRaise = tb.left > GRACE;
      const rb = btn(canRaise ? "⬆ Bet / raise the amount above" : "⬆ Raising closed (last " + GRACE + " blocks are calls only)", () => {
        const raw = nadoToRaw($("betAmt").value);
        if (!raw) { $("status").textContent = "Enter an amount — your street total above " + rawToNado(priceNow) + " raises the price for everyone."; return; }
        if (raw > BigInt(me.stack)) { alertBar("That's more than your stack (" + rawToNado(me.stack) + " NADO) — table stakes: you bet what you brought. Use ALL-IN for everything."); return; }
        doBet(raw, "bet " + rawToNado(raw) + " NADO");
      }, owe <= 0);
      rb.disabled = !canRaise;
      if (canRaise || owe > 0) btn("🔥 ALL-IN — push your whole stack (" + rawToNado(me.stack) + ")", () => doBet(BigInt(me.stack), "ALL-IN " + rawToNado(me.stack) + " NADO"), false);
      btn("🙅 Fold" + (owe > 0 ? " — give up " + rawToNado(me.total + Number(tb.ante || 0)) + " in the pot" : ""), () => setFold(true), false);
    }
    if (tb.phase === "showdown" && me && !fk && localFold && !me.revealed) {
      const note = document.createElement("div"); note.className = "small"; note.style.cssText = "flex:1 1 100%;color:var(--dim);font-weight:700";
      note.textContent = "✋ You folded — your cards stay mucked.";
      wrap.appendChild(note);
      btn("↩ Undo — show your cards after all (you're still eligible)", () => setFold(false), false);
    }
    if (tb.phase === "showdown" && me && !fk && !localFold) {
      const stillIn = lastSeats.filter((x) => !foldedAt(x, tb));
      const waitingOn = stillIn.filter((x) => !x.revealed);
      if (!me.revealed && watch && watch.phase === "reveal") btn("⏳ Showing your hand — confirming on-chain…", () => {}, false).disabled = true;
      else if (!me.revealed) btn("🃏 Show your cards — claim the pot", doReveal, true);
      else {
        const note = document.createElement("div"); note.className = "small"; note.style.cssText = "flex:1 1 100%;color:var(--accent2);font-weight:700";
        note.textContent = "✓ Your hand is shown (" + stillIn.filter((x) => x.revealed).length + "/" + stillIn.length + ") — " +
          (waitingOn.length ? "waiting on " + waitingOn.map((x) => x.addr === dapp.me ? "you" : disp(x.addr)).join(", ") : "everyone has shown — the pot can settle right now.");
        wrap.appendChild(note);
      }
    }
    if (tb.phase === "over" && tb.leader) btn("🏆 Pay the pot to the best hand (" + rawToNado(tb.pot) + ")", settleTable, true);
  }
  $("btnReclaim").classList.toggle("hidden", !(tb.exists && !tb.closed && tb.phase === "over" && !tb.leader && iAmHost));
  $("btnCancel").classList.toggle("hidden", !(tb.exists && !tb.closed && tb.seatCount === 1 && iAmHost));
  const stalledOpen = !tb.exists && T.ts && Date.now() - T.ts > 120000;
  if ($("btnReopen")) $("btnReopen").classList.toggle("hidden", !stalledOpen);
  const jh = $("joinHint");
  const hint = dapp.me && activeTable != null && !tb.exists ? dapp.whereIs("table", activeTable, T.ts) : "";
  if (jh) { jh.textContent = hint; jh.classList.toggle("hidden", !hint); }
}

// ---- boot ----------------------------------------------------------------------------------------
let watch = null;   // the submitted action we're waiting to see ON-CHAIN (flips status to "confirmed ✓")
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.table != null) activeTable = pend.table;
  if (ok && pend && pend.phase === "connect") dapp.consumeInvite((id) => { activeTable = parseInt(id, 10); joinTable(); });
  if (ok && pend && ["open", "join", "bet", "reveal", "settle", "start", "leave", "closest"].includes(pend.phase)) watch = pend;
  $("status").textContent = statusLabel(pend, ok, err, {
    open: "Table opening — confirming…", join: "Taking your seat — confirming…", bet: "Bet placed — confirming…",
    reveal: "Showing your cards — confirming…", settle: "Paying the winner…", reclaim: "Reclaiming…", cancel: "Cancelling…",
    start: "Dealing — confirming…", leave: "Leaving the table — refunding…", closest: "Fast-forwarding the street…" });
});
async function boot() {
  try { await dapp.init(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload."; return; }
  wireUI(); loadQR(); orderCards(["activeGame","lobby","play","opencard","walletcard","bankroll","scoreboard"]);
  const q = new URLSearchParams(location.search).get("table");
  if (q) { $("joinId").value = q; if (activeTable == null) activeTable = parseInt(q, 10); }
  if (q && !dapp.me) { const tb = await fetchTable(parseInt(q, 10));
    inviteGate(dapp, { id: parseInt(q, 10), title: "You're invited to a hold'em table",
      body: tb && tb.exists ? ("Sit down for an ante of <b>" + rawToNado(tb.ante) + " NADO</b> — real multiplayer Texas Hold'em.") : "Sign in to sit down at this table.",
      joinLabel: "Sign in & sit down" }); }
  render(); refreshActive();
  setInterval(refreshActive, 3000);
}
boot();
