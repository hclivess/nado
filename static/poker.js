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
import { NadoDapp, rawToNado, nadoToRaw, randId, randSecret, algHashn, ALG_P, _m, $, base, gate, canPay, alertBar, inviteGate,
         hoist, orderCards, blocksToTime, lsLoad as load, lsSave as save, lsPrune, wireWallet, stickyInputs, renderWallet, renderScore, notify, okBar,
         scoreBump, scoreSort, recentChips, statusLabel,
         loadQR, drawQR, resolveAliases, disp, share, shareInvite } from "./nadodapp.js";
import { BankedGame } from "./bankedgame.js";   // the ONE banked-table reader — hold'em overlays its street phases

const CID = "2fb48456656d5aa253b32ff5d72401ec";   // execnode/games/holdem.py (zkVM, nonce "a5")
const GICON = '<svg style="vertical-align:-3px" viewBox="0 0 48 48" width="16" height="16" aria-hidden="true">     <rect x="8" y="13" width="18" height="24" rx="3" fill="#e6edf3" stroke="#243140" stroke-width="1.6" transform="rotate(-9 17 25)"/>     <path d="M14 20c-2.4 2.4-4 3.4-4 5.4 0 1.4 1.1 2.2 2.2 2.2.5 0 1-.2 1.3-.5-.2 1-.6 1.7-1.2 2.2h3.4c-.6-.5-1-1.2-1.2-2.2.3.3.8.5 1.3.5 1.1 0 2.2-.8 2.2-2.2 0-2-1.6-3-4-5.4z" fill="#20272f" transform="rotate(-9 14 25)"/>     <rect x="22" y="13" width="18" height="24" rx="3" fill="#fff" stroke="#243140" stroke-width="1.6" transform="rotate(9 31 25)"/>     <path d="M31 30c-.7-.7-3.2-2.3-3.2-4.6 0-1.3 1-2.2 2.1-2.2.6 0 1.1.3 1.1.9 0-.6.5-.9 1.1-.9 1.1 0 2.1.9 2.1 2.2 0 2.3-2.5 3.9-3.2 4.6z" fill="#d0362b" transform="rotate(9 31 26)"/></svg>';
const dapp = new NadoDapp({ cid: CID, app: "Hold'em" });
const bg = new BankedGame(dapp, { icon: "🂠" });   // shared reader for existence + ta/tp/tn/tz; streets overlaid below
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

// ---- card math (MUST mirror execnode/games/holdem.py exactly — this is what the zkVM contract computes) --
// roll32(x) = LO32(alghash HASH(x)); commit = H(x) = algHashn([x]); seeds are reduced mod the field.
const roll32 = (x) => Number(algHashn([x]) & 0xFFFFFFFFn);
function drawCard(seed, slot, excl) {
  for (let a = 0; ; a++) {
    const c = roll32(seed + BigInt(slot * 4096 + a)) % 52;
    if (!excl.includes(c)) return c;
  }
}
const seedOf = (aHex, bHex, salt) => { if (!aHex || !bHex) return null; const P = ALG_P();
  return algHashn([(BigInt("0x" + aHex) % P + BigInt("0x" + bHex) % P + BigInt(salt)) % P]); };
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
  const b = bg.read(sto, t);                       // ONE reader: existence (ta), pot (tp), seatCount (tn), closed (tz)
  if (!b.exists) return { exists: false };
  t = String(t);
  const tb = { exists: true, id: b.id, host: b.bank, t0: _m(sto, "t0")[t], ante: _m(sto, "ts")[t] || 0, pot: b.pool,
    seatCount: b.seatCount, revealCount: b.settledCount,
    best: _m(sto, "tw")[t] || 0, leader: _m(sto, "tb")[t] || 0, closed: b.closed };
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
  const g = randId(), x = randSecret() % ALG_P();   // field-sized: reveal passes x as a zkVM int arg (< P)
  const Ssto = load(LS_S); Ssto[g] = { table: t, secret: x.toString(), ts: Date.now() }; save(LS_S, Ssto);
  if (method === "open") { const T = load(LS_T); T[t] = { ante: anteRaw.toString(), ts: Date.now() }; save(LS_T, T); }
  activeTable = t; render();
  const args = method === "open" ? [t, g, algHashn([x]), anteRaw] : [t, g, algHashn([x])];
  const vars = { t, b: rawToNado(buyinRaw), a: rawToNado(anteRaw), s: rawToNado(buyinRaw - anteRaw) };
  const desc = method === "open"
    ? window.t("poker.openDesc", "open a hold'em table #{t} · buy-in {b} NADO (ante {a}, stack {s})", vars)
    : window.t("poker.sitDesc", "sit down at hold'em table #{t} · buy-in {b} NADO (ante {a}, stack {s})", vars);
  dapp.call(method, args, buyinRaw, desc, { table: t, seat: g, phase: method });
}
function readBuyin(anteRaw) {
  const raw = nadoToRaw($("buyinAmt").value);
  if (!raw) { alertBar(window.t("poker.enterBuyin", "Enter your BUY-IN — the ante ({a} NADO) goes to the pot, the rest is your stack to bet with. A common buy-in is 20–50× the ante.", { a: rawToNado(anteRaw) })); return null; }
  if (raw < anteRaw) { alertBar(window.t("poker.buyinCoverAnte", "The buy-in must at least cover the ante ({a} NADO).", { a: rawToNado(anteRaw) })); return null; }
  return raw;
}
async function newTable() {
  const ante = nadoToRaw($("anteAmt").value);
  if (!ante) return alertBar(window.t("poker.enterAnte", "Enter an ante (NADO) — everyone pays it into the pot to sit down."));
  const buyin = readBuyin(ante); if (!buyin) return;
  await dapp.refresh();
  if (!canPay(dapp, buyin, window.t("poker.ctxOpening", "Opening this table"))) return;
  sit(randId(), "open", buyin, ante);
}
function reopenTable() {   // retry an open that didn't confirm within ~2 min
  const T = load(LS_T)[activeTable]; if (!T || !T.ante) return;
  const buyin = nadoToRaw($("buyinAmt").value) || BigInt(T.ante);
  if (!canPay(dapp, buyin, window.t("poker.ctxReopening", "Re-opening this table"))) return;
  sit(activeTable, "open", buyin, BigInt(T.ante));
}
async function joinTable() {
  const t = activeTable;
  if (!t) return alertBar(window.t("poker.pickTableFirst", "Pick a table first."));
  const tb = await fetchTable(t);
  if (!tb || !tb.exists) { alertBar(dapp.whereIs("table", t)); if (tb) dapp.clearInvite(); return; }
  if (tb.phase !== "join") { alertBar(window.t("poker.seatingClosed", "Seating is closed — this hand is already underway. Open a new table.")); dapp.clearInvite(); return; }
  if (lastSeats.some((s) => s.addr === dapp.me)) { alertBar(window.t("poker.alreadySeated", "You're already seated here.")); dapp.clearInvite(); return; }
  await dapp.refresh();
  const ante = BigInt(tb.ante);
  const buyin = readBuyin(ante); if (!buyin) return;
  if (!canPay(dapp, buyin, window.t("poker.ctxSitting", "Sitting down"))) { render(); return; }   // keep the invite: it re-fires when the deposit lands
  dapp.clearInvite();   // committing the seat now — don't replay it again
  sit(t, "join", buyin, ante);
}
function mySeat() { return lastSeats.find((s) => s.addr === dapp.me); }
function doBet(amountRaw, label) {
  const s = mySeat(); if (!s) return;
  const k = lastTable && lastTable.street || 1;
  // amount is an ARG (chips move from your escrowed stack, no new value) — confirm:true so autosign never bets
  dapp.call("bet", [s.g, amountRaw], null, window.t("poker.betAction", "{label} · table #{t}", { label, t: activeTable }),
    { table: activeTable, seat: s.g, phase: "bet", k, prev: s.cs[k] }, { confirm: true });
}
function doReveal() {
  const s = mySeat(); if (!s) return;
  const rec = load(LS_S)[s.g];
  if (!rec || !rec.secret) return alertBar(window.t("poker.noSecretHere", "This browser doesn't hold the secret for seat #{g} — show your cards from the device you joined with.", { g: s.g }));
  dapp.call("reveal", [s.g, BigInt(rec.secret)], null, window.t("poker.revealDesc", "showdown — show your cards · table #{t}", { t: activeTable }), { table: activeTable, seat: s.g, phase: "reveal" });
}
const settleTable = () => dapp.call("settle", [activeTable], null, window.t("poker.settleDesc", "pay the pot to the best hand · table #{t}", { t: activeTable }), { table: activeTable, phase: "settle" });
// AUTO-COLLECT the WINNER's pot once the hand is over (shared SDK tick — opt-out slider, autoTried dedup)
function maybeAutoSettle() {
  const tb = lastTable;
  if (!tb || !tb.exists || tb.closed || tb.phase !== "over" || !tb.leader) return;
  const s = mySeat();
  if (!s || s.g !== tb.leader) return;   // only the winner auto-collects the pot
  dapp.autoCollect([{ g: activeTable }], () => settleTable(), { blocked: watch });
}
const reclaimTable = () => dapp.call("reclaim", [activeTable], null, window.t("poker.reclaimDesc", "reclaim the dead pot · table #{t}", { t: activeTable }), { table: activeTable, phase: "reclaim" });
const cancelTable = () => dapp.call("cancel", [activeTable], null, window.t("poker.cancelDesc", "cancel table #{t}", { t: activeTable }), { table: activeTable, phase: "cancel" });
// the HOST deals: binds the hand to two blocks that don't exist yet — nobody can know the cards
const startTable = () => dapp.call("start", [activeTable], null, window.t("poker.startDesc", "🃏 deal now · table #{t}", { t: activeTable }), { table: activeTable, phase: "start" });
// the HOST fast-forwards a street once nobody owes a call — a checked-around street ends NOW
const closeStreet = () => dapp.call("close_street", [activeTable], null, window.t("poker.closeDesc", "⏩ close the {street} · table #{t}", { street: streetName((lastTable && lastTable.street) || 1), t: activeTable }),
  { table: activeTable, phase: "closest", k: (lastTable && lastTable.street) || 1 });
function leaveTable() {
  const s = mySeat(); if (!s) return;
  dapp.call("leave", [s.g], null, window.t("poker.leaveDesc", "leave table #{t} — full refund", { t: activeTable }), { table: activeTable, seat: s.g, phase: "leave" });
}

async function refreshActive() {
  await dapp.refresh();
  dapp.settleInflight();   // SDK: retire the optimistic 'confirming…' status once the action lands
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
        okBar({ open: window.t("poker.doneOpen", "✓ Table confirmed — you're seated. Share the link below to fill it."),
          join: window.t("poker.doneJoin", "✓ Seat confirmed — you're in the hand."), bet: window.t("poker.doneBet", "✓ Bet confirmed on-chain."),
          reveal: window.t("poker.doneReveal", "✓ Your hand is shown on-chain."), settle: window.t("poker.doneSettle", "✓ Pot paid out."),
          start: window.t("poker.doneStart", "✓ Dealt! Cards are locking in the next blocks — hole cards appear once they finalize."),
          closest: window.t("poker.doneClose", "✓ Street closed — the next card is locking in now."),
          leave: window.t("poker.doneLeave", "✓ You left the table — buy-in refunded in full.") }[watch.phase]);
        watch = null;
      } else if (watch.ts && Date.now() - watch.ts > 75000) {
        notify(window.t("poker.stillSettling", "Still settling on-chain — your chips and funds are safe; the table updates by itself."));
        watch = null;
      }
    }
    renderLobby(sto); renderScoreboard(boardFrom(sto));
  }
  await resolveAliases([dapp.me].concat(lastSeats.map((s) => s.addr)));
  render();
  maybeAutoSettle();
}
function boardFrom(sto) {
  const stats = {};
  // index every seat by its table in ONE pass so we don't re-scan the whole seat map per table
  // (that was O(tables × seats), unbounded with total hand history; this is O(seats + tables)).
  const gg = _m(sto, "gg"), seatsByTable = {};
  for (const g of Object.keys(gg)) { const t = String(gg[g]); (seatsByTable[t] || (seatsByTable[t] = [])).push(g); }
  for (const t of Object.keys(_m(sto, "ta"))) {
    if (!_m(sto, "tz")[t]) continue;
    const lead = _m(sto, "tb")[t]; if (!lead) continue;             // cancelled / reclaimed hands don't rank
    const seats = seatsByTable[String(t)] || [];
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
const renderScoreboard = (board) => renderScore($("scoreList"), board, dapp.me, window.t("poker.noFinishedHands", "No finished hands yet — be the first on the board."));
function renderLobby(sto) {
  const el = $("lobbyList"); if (!el) return;
  const tables = Object.keys(_m(sto, "ta")).map((t) => tableFrom(sto, t)).filter((t) => t.exists && !t.closed);
  tables.sort((a, b) => (b.phase === "join") - (a.phase === "join") || b.id - a.id);
  el.innerHTML = tables.length ? tables.slice(0, 24).map((t) => {
    const tag = t.phase === "join" ? "🟢" : t.phase === "showdown" ? "🃏" : t.phase === "over" ? "🏁" : "▶";
    const info = t.phase === "join" ? window.t("poker.lobbySeatingOpen", " · seating open") : t.phase === "street" || t.phase === "dealing" ? window.t("poker.lobbyPlaying", " · playing") : "";
    const players = t.seatCount === 1 ? window.t("poker.players1", "{n} player", { n: t.seatCount }) : window.t("poker.playersN", "{n} players", { n: t.seatCount });
    return '<button class="chip ' + (t.phase === "join" ? "betting" : "") + '" data-t="' + t.id + '">' + tag + " #" + t.id
      + " · " + window.t("poker.lobbyAnte", "ante {a}", { a: rawToNado(t.ante) }) + " · " + players + info + "</button>";
  }).join(" ") : '<span class="dim">' + window.t("poker.noTablesOpen", "No tables yet — open one below.") + '</span>';
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => selectTable(parseInt(b.dataset.t, 10)));
}
let buyinEdited = false;   // the player typed their own buy-in — stop auto-suggesting
function selectTable(id) {
  activeTable = id; $("joinId").value = String(id);
  buyinEdited = false;     // fresh table -> fresh suggestion (match the host)
  notify(window.t("poker.tableSelected", "Table #{id} selected.", { id }));
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

// Hand-rankings cheat sheet (strongest -> weakest). `cat` matches eval7's category (v / 14^5), so the
// player's CURRENT best hand row lights up live as the board deals — beginners see exactly where they
// stand and what beats it. Example card indices are suit*13 + rank (see cardHTML): they're illustrative
// only, never re-evaluated. Card ranks: 0='2'…8='10',9='J',10='Q',11='K',12='A'; suits ♠0 ♥1 ♦2 ♣3.
const RANK_GUIDE = [
  [8, "Straight Flush", "Five in a row, all one suit (10–A = Royal Flush)", [21, 22, 23, 24, 25]],
  [7, "Four of a Kind", "All four cards of one rank", [7, 20, 33, 46, 11]],
  [6, "Full House", "Three of a kind plus a pair", [10, 23, 36, 3, 16]],
  [5, "Flush", "Five of one suit, in any order", [38, 35, 32, 30, 27]],
  [4, "Straight", "Five in a row, mixed suits", [3, 17, 31, 6, 20]],
  [3, "Three of a Kind", "Three cards of one rank", [5, 18, 31, 11, 0]],
  [2, "Two Pair", "Two different pairs", [11, 24, 2, 15, 20]],
  [1, "Pair", "Two cards of the same rank", [8, 21, 11, 3, 14]],
  [0, "High Card", "Nothing made — your highest card plays", [12, 24, 33, 42, 13]],
];
const CAT_UNIT = 14 ** 5;   // eval7 packs category as the top base-14 digit: category = v / 14^5
function renderRankGuide() {
  const el = $("rankGuide");
  if (!el) return;
  el.innerHTML = RANK_GUIDE.map(([cat, name, desc, ex]) =>
    `<div class="rk" data-cat="${cat}"><span class="rkname">${window.t("poker.rank" + cat + "name", name)}</span>` +
    `<span class="rkdesc">${window.t("poker.rank" + cat + "desc", desc)}</span>` +
    `<span class="minihand">${ex.map((c) => cardHTML(c, false)).join("")}</span></div>`).join("");
}
// highlight the row for the player's current best category (-1 clears all — pre-flop, folded-out, no seat)
function markRankGuide(cat) {
  document.querySelectorAll("#rankGuide .rk").forEach((n) => n.classList.toggle("on", +n.dataset.cat === cat));
}

// ---- render --------------------------------------------------------------------------------------
function wireUI() {
  renderRankGuide();
  wireWallet(dapp);
  dapp.wireAutoCollect();
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
  $("btnGoTable").onclick = () => { const id = parseInt($("joinId").value, 10); if (id) selectTable(id); else alertBar(window.t("poker.enterTableId", "Enter a table ID, or pick one from the lobby.")); };
  $("btnReclaim").onclick = reclaimTable;
  $("btnCancel").onclick = cancelTable;
  if ($("btnReopen")) $("btnReopen").onclick = reopenTable;
  $("btnShare").onclick = () => share(base() + "/?table=" + activeTable, window.t("poker.shareMsg", "Sit down at my hold'em table #{t} on NADO:", { t: activeTable }), $("btnShare"));
}
function render() {
  dapp.reflectUrl("table", activeTable);   // address bar = the shareable link to the selected table
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
    x.tag = tb.closed ? window.t("poker.tagFinished", "finished ✓") : tb.phase === "join" ? window.t("poker.tagSeating", "seating") : tb.phase === "street" ? streetName(tb.street) : tb.phase === "showdown" ? window.t("poker.tagShowdown", "SHOWDOWN") : window.t("poker.tagSettle", "settle!");
  }
  recentChips($("recent"), shown, selectTable, window.t("poker.noTablesShort", "No tables yet."));
  renderActive();
}
const STREETS = ["", "pre-flop", "flop", "turn", "river"];
const STREET_KEYS = ["", "preflop", "flop", "turn", "river"];
const streetName = (k) => window.t("poker.street_" + STREET_KEYS[k], STREETS[k]);
function renderActive() {
  if (activeTable == null) return;
  const tb = lastTable || {}, T = load(LS_T)[activeTable] || {};
  const me = mySeat(), iAmHost = tb.host === dapp.me;
  $("gameId").textContent = "#" + activeTable;
  shareInvite("table", activeTable, window.t("poker.shareMsg2", "Sit down at my hold em table #{t} on NADO:", { t: activeTable }), 180);
  $("gPot").textContent = tb.exists ? rawToNado(tb.pot) + " NADO" : "—";
  if ($("gPots")) {
    const pots = tb.exists && tb.phase !== "join" && lastSeats.length ? sidePots(lastSeats, tb.ante) : [];
    $("gPots").innerHTML = pots.length > 1 ? pots.map((p, n) =>
      '<div class="kv"><span class="k">' + (n === 0 ? window.t("poker.mainPot", "Main pot") : window.t("poker.sidePot", "Side pot {n}", { n })) + " (" + p.idxs.map((i) => disp(lastSeats[i].addr)).join(", ") + ')</span><span class="mono">' + rawToNado(p.amt) + " NADO</span></div>").join("") : "";
  }
  $("gAnte").textContent = tb.exists ? rawToNado(tb.ante) + " NADO" : "—";

  // headline: phase + countdown — always says what happens next
  let phaseTxt = dapp.whereIs("table", activeTable, T.ts);
  if (tb.exists) {
    const players = tb.seatCount === 1 ? window.t("poker.players1", "{n} player", { n: tb.seatCount }) : window.t("poker.playersN", "{n} players", { n: tb.seatCount });
    if (tb.closed) phaseTxt = window.t("poker.phaseOver", "hand over — settled ✓");
    else if (tb.phase === "join") phaseTxt = window.t("poker.phaseSeating", "🟢 seating open — {players} · {who}", { players, who: tb.host === dapp.me ? window.t("poker.youDeal", "YOU deal when ready") : window.t("poker.hostDeals", "the host deals when ready") });
    else if (tb.phase === "shuffle") phaseTxt = window.t("poker.phaseShuffle", "🂠 shuffling — your cards land in {time} (betting opens with cards visible)", { time: blocksToTime(tb.left) });
    else if (tb.phase === "street") phaseTxt = window.t("poker.phaseStreet", "▶ {street} betting — closes in {time} (or when the host fast-forwards)", { street: streetName(tb.street).toUpperCase(), time: blocksToTime(tb.left) });
    else if (tb.phase === "showdown") phaseTxt = window.t("poker.phaseShowdown", "🃏 SHOWDOWN — show your cards within {time} · {n} shown", { time: blocksToTime(tb.left), n: tb.revealCount });
    else phaseTxt = window.t("poker.phaseFinished", "🏁 hand finished — pay out below");
  }
  $("gStatus").textContent = phaseTxt;

  // the felt: community + my hole cards
  const board = tb.exists && tb.td && dapp.cursor != null ? boardCards(activeTable, tb.closes) : [];
  $("community").innerHTML = handHTML(board, 5, false);
  $("communityNote").textContent = !tb.exists ? "" :
    tb.phase === "join" ? window.t("poker.boardDealsLater", "the board deals street by street once the host deals") :
    board.length === 0 ? window.t("poker.flopPending", "flop lands when its block finalizes…") :
    board.length === 3 ? window.t("poker.turnPending", "turn card is still in future blocks") :
    board.length === 4 ? window.t("poker.riverPending", "river card is still in future blocks") : "";
  let hole = null, holeTxt = "";
  const fk = me && tb.exists ? foldedAt(me, tb) : 0;
  if (me && tb.exists && tb.td) {
    const rec = load(LS_S)[me.g];
    if (rec && rec.secret) hole = holeCards(dapp.bh(tb.d0), dapp.bh(tb.d0 + 1), BigInt(rec.secret));
    holeTxt = !rec || !rec.secret ? window.t("poker.secretElsewhere", "your secret lives in the browser you joined with — open this page there to see your cards")
      : !hole ? window.t("poker.holePending", "your hole cards land when the deal blocks finalize…") : "";
  } else if (me) holeTxt = tb.host === dapp.me ? window.t("poker.hostHitDeal", "hit 🃏 Deal now below when everyone's seated") : window.t("poker.holeAfterStart", "your hole cards deal when the host starts the hand");
  $("holeWrap").classList.toggle("hidden", !me);
  $("hole").innerHTML = handHTML(hole, 2, true);
  let handName = "", curCat = -1;
  if (hole && board.length >= 3) {
    const ev = eval7(board.concat(hole));
    handName = ev.name + (board.length < 5 ? window.t("poker.soFar", " (so far)") : "");
    curCat = Math.floor(ev.v / CAT_UNIT);
  } else if (hole) handName = window.t("poker.holeFlopNext", "your hole cards — the flop comes next");
  $("holeNote").textContent = fk ? window.t("poker.foldedNote", "✗ folded on the {street} — your chips stay in the pot", { street: streetName(fk) }) : (handName || holeTxt);
  markRankGuide(curCat);   // light up the player's current rank in the cheat sheet (-1 clears it)

  // players
  const priceNow = tb.exists && tb.phase === "street" ? tb.price(tb.street) : 0;
  $("seats").innerHTML = lastSeats.length ? lastSeats.map((s) => {
    const you = s.addr === dapp.me ? '<b style="color:var(--accent2)">' + window.t("poker.you", "you") + '</b> ' : "";
    const f = tb.exists ? foldedAt(s, tb) : 0;
    let tag;
    if (s.revealed) {
      const oppHole = s.secret != null ? holeCards(dapp.bh(tb.d0), dapp.bh(tb.d0 + 1), BigInt(s.secret)) : null;
      const nm = oppHole && board.length === 5 ? eval7(board.concat(oppHole)).name : window.t("poker.shown", "shown");
      tag = '<span class="minihand">' + (oppHole ? handHTML(oppHole, 2, false) : "") + '</span> <span class="b ' + (tb.leader === s.g ? 'ok">👑 ' : 'dimb">') + nm + "</span>";
    }
    else if (f) tag = '<span class="b dimb">' + window.t("poker.foldedTag", "folded ({street})", { street: streetName(f) }) + "</span>";
    else if (tb.phase === "street" && s.cs[tb.street] < priceNow) tag = '<span class="b pend">' + window.t("poker.mustCall", "must call {a}", { a: rawToNado(priceNow - s.cs[tb.street]) }) + "</span>";
    else if (tb.phase === "showdown") tag = '<span class="b pend">' + window.t("poker.yetToShow", "yet to show") + '</span>';
    else tag = '<span class="b ok">' + window.t("poker.inCheck", "in ✓") + '</span>';
    const allin = s.stack === 0 && !f && tb.exists && tb.phase !== "join" ? ' <span class="b pend">' + window.t("poker.allIn", "ALL-IN") + '</span>' : "";
    return '<div class="seat">' + you + disp(s.addr) + ' · ' + window.t("poker.inPot", "in pot") + ' <span class="mono">' + rawToNado(s.total + Number(tb.ante || 0)) + '</span> · ' + window.t("poker.stack", "stack") + ' <span class="mono">' + rawToNado(s.stack) + "</span>" + allin + " " + tag + "</div>";
  }).join("") : '<span class="dim">' + window.t("poker.noPlayers", "No players yet.") + '</span>';

  // actions — ONE obvious primary thing to do at every phase
  const wrap = $("myActions"); wrap.innerHTML = "";
  const btn = (txt, fn, primary, pulse) => { const b = document.createElement("button"); b.className = (primary ? "primary" : "ghost") + (pulse ? " pulse" : ""); b.style.flex = "1 1 auto"; b.textContent = txt; b.onclick = fn; wrap.appendChild(b); return b; };
  const betRow = $("betRow");
  betRow.classList.add("hidden");
  // joining? suggest the HOST's buy-in (ante + host stack) so a 0.1-ante table never asks for 20 NADO
  if (tb.exists && tb.phase === "join" && !me && !buyinEdited && lastSeats.length) {
    const host = lastSeats.find((s) => s.addr === tb.host) || lastSeats[0];
    $("buyinAmt").value = rawToNado(Number(tb.ante) + host.stack);
  }
  if (tb.exists && !tb.closed && dapp.me) {
    if (tb.phase === "join" && !me) {
      if (watch && watch.phase === "join") btn(window.t("poker.takingSeat", "⏳ Taking your seat — confirming on-chain…"), () => {}, false).disabled = true;
      else btn(window.t("poker.sitDownBtn", "🪑 Sit down — buy-in {b} NADO (ante {a})", { b: ($("buyinAmt").value || rawToNado(tb.ante)), a: rawToNado(tb.ante) }), joinTable, true, true);
    }
    if (tb.phase === "street" && iAmHost) {
      // closable iff nobody owes a call: every seat matched the street price, is all-in, or folded earlier
      const pk = tb.price(tb.street);
      const closable = lastSeats.length > 0 && lastSeats.every((s) => s.cs[tb.street] === pk || s.stack === 0 || foldedAt(s, tb) > 0)
        && !((_m(lastSto, "sc")[String(Number(activeTable) * 8 + tb.street)] || 0) > 0);
      if (watch && watch.phase === "closest") btn(window.t("poker.fastForwarding", "⏳ Fast-forwarding the street…"), () => {}, false).disabled = true;
      else if (closable) btn(window.t("poker.dealNextNow", "⏩ Everyone's in — deal the next card NOW"), closeStreet, true);
    }
    // the HOST controls the start — nothing happens until they deal
    if (tb.phase === "join" && iAmHost) {
      if (watch && watch.phase === "start") btn(window.t("poker.dealingConfirm", "⏳ Dealing — confirming on-chain…"), () => {}, false).disabled = true;
      else btn(tb.seatCount >= 2 ? window.t("poker.dealNowStart", "🃏 Deal now — start the hand ({n} players)", { n: tb.seatCount })
                                 : window.t("poker.dealNowWait", "🃏 Deal now — or wait for players (share the invite below)"), startTable, tb.seatCount >= 2);
    }
    if (tb.phase === "join" && me && !iAmHost) {
      if (watch && watch.phase === "leave") btn(window.t("poker.leavingRefund", "⏳ Leaving — refunding…"), () => {}, false).disabled = true;
      else btn(window.t("poker.leaveBtn", "🚪 Leave the table — full refund (ante + stack)"), leaveTable, false);
    }
    if (tb.phase === "shuffle") {
      const note = document.createElement("div"); note.className = "small"; note.style.cssText = "flex:1 1 100%;color:var(--accent2);font-weight:700";
      note.textContent = window.t("poker.shufflingNote", "🂠 Shuffling — your hole cards lock to blocks {a}–{b} and appear once final; betting opens right after.", { a: tb.d0, b: tb.d0 + 1 });
      wrap.appendChild(note);
    }
    const rec = me ? (load(LS_S)[me.g] || {}) : {};
    const localFold = !!rec.folded;
    const setFold = (v) => { const S = load(LS_S); if (S[me.g]) { S[me.g].folded = v ? Date.now() : 0; save(LS_S, S); } render(); };
    if (tb.phase === "street" && me && !fk && localFold) {
      const note = document.createElement("div"); note.className = "small"; note.style.cssText = "flex:1 1 100%;color:var(--dim);font-weight:700";
      note.textContent = window.t("poker.foldedSitOut", "✋ You folded — sitting this hand out. Your chips stay in the pot.");
      wrap.appendChild(note);
      btn(window.t("poker.undoFold", "↩ Undo fold — you can still call until the street closes"), () => setFold(false), false);
    }
    if (tb.phase === "street" && me && !fk && !localFold && me.stack === 0) {
      const note = document.createElement("div"); note.className = "small"; note.style.cssText = "flex:1 1 100%;color:var(--accent2);font-weight:700";
      note.textContent = window.t("poker.allInNote", "🔥 You're ALL-IN — nothing left to do; you're live for every pot you funded.");
      wrap.appendChild(note);
    }
    if (tb.phase === "street" && me && !fk && !localFold && me.stack > 0) {
      betRow.classList.remove("hidden");
      const myIn = me.cs[tb.street], owe = priceNow - myIn;
      let betInfo;
      if (priceNow) {
        let tail;
        if (owe > 0) {
          const callTxt = rawToNado(owe > me.stack ? me.stack : owe) + (owe > me.stack ? window.t("poker.allInParen", " (all-in)") : "");
          tail = window.t("poker.callOrFold", ' · <b class="warn">call {c} or fold when the street closes</b>', { c: callTxt });
        } else tail = window.t("poker.matchedCheck", " · matched ✓ (do nothing to check)");
        betInfo = window.t("poker.betInfoPriced", "Your stack <b>{stack}</b> · street price <b>{price}</b> · you're in for <b>{in}</b>", { stack: rawToNado(me.stack), price: rawToNado(priceNow), in: rawToNado(myIn) }) + tail;
      } else {
        betInfo = window.t("poker.betInfoOpen", "Your stack <b>{stack}</b> · no bets yet this street — do nothing to <b>check</b>, or open the betting below.", { stack: rawToNado(me.stack) });
      }
      $("betInfo").innerHTML = betInfo;
      if (owe > 0) {
        const callAmt = owe > me.stack ? me.stack : owe;
        btn((owe > me.stack ? window.t("poker.callAllInBtn", "🔥 Call ALL-IN {a} — stay in", { a: rawToNado(callAmt) }) : window.t("poker.callBtn", "📞 Call {a} — stay in", { a: rawToNado(callAmt) })), () => doBet(BigInt(callAmt), window.t("poker.callLabel", "call {a} NADO", { a: rawToNado(callAmt) })), true);
      }
      const canRaise = tb.left > GRACE;
      const rb = btn(canRaise ? window.t("poker.raiseBtn", "⬆ Bet / raise the amount above") : window.t("poker.raiseClosed", "⬆ Raising closed (last {n} blocks are calls only)", { n: GRACE }), () => {
        const raw = nadoToRaw($("betAmt").value);
        if (!raw) return alertBar(window.t("poker.enterRaise", "Enter an amount — your street total above {price} raises the price for everyone.", { price: rawToNado(priceNow) }));
        if (raw > BigInt(me.stack)) { alertBar(window.t("poker.overStack", "That's more than your stack ({stack} NADO) — table stakes: you bet what you brought. Use ALL-IN for everything.", { stack: rawToNado(me.stack) })); return; }
        doBet(raw, window.t("poker.betLabel", "bet {a} NADO", { a: rawToNado(raw) }));
      }, owe <= 0);
      rb.disabled = !canRaise;
      if (canRaise || owe > 0) btn(window.t("poker.allInBtn", "🔥 ALL-IN — push your whole stack ({stack})", { stack: rawToNado(me.stack) }), () => doBet(BigInt(me.stack), window.t("poker.allInLabel", "ALL-IN {a} NADO", { a: rawToNado(me.stack) })), false);
      btn(window.t("poker.foldBtn", "🙅 Fold") + (owe > 0 ? window.t("poker.foldGiveUp", " — give up {a} in the pot", { a: rawToNado(me.total + Number(tb.ante || 0)) }) : ""), () => setFold(true), false);
    }
    if (tb.phase === "showdown" && me && !fk && localFold && !me.revealed) {
      const note = document.createElement("div"); note.className = "small"; note.style.cssText = "flex:1 1 100%;color:var(--dim);font-weight:700";
      note.textContent = window.t("poker.foldedMucked", "✋ You folded — your cards stay mucked.");
      wrap.appendChild(note);
      btn(window.t("poker.undoShow", "↩ Undo — show your cards after all (you're still eligible)"), () => setFold(false), false);
    }
    if (tb.phase === "showdown" && me && !fk && !localFold) {
      const stillIn = lastSeats.filter((x) => !foldedAt(x, tb));
      const waitingOn = stillIn.filter((x) => !x.revealed);
      if (!me.revealed && watch && watch.phase === "reveal") btn(window.t("poker.showingHand", "⏳ Showing your hand — confirming on-chain…"), () => {}, false).disabled = true;
      else if (!me.revealed) btn(window.t("poker.showCardsBtn", "🃏 Show your cards — claim the pot"), doReveal, true);
      else {
        const note = document.createElement("div"); note.className = "small"; note.style.cssText = "flex:1 1 100%;color:var(--accent2);font-weight:700";
        note.textContent = window.t("poker.handShown", "✓ Your hand is shown ({shown}/{total}) — ", { shown: stillIn.filter((x) => x.revealed).length, total: stillIn.length }) +
          (waitingOn.length ? window.t("poker.waitingOn", "waiting on {who}", { who: waitingOn.map((x) => x.addr === dapp.me ? window.t("poker.you", "you") : disp(x.addr)).join(", ") }) : window.t("poker.allShown", "everyone has shown — the pot can settle right now."));
        wrap.appendChild(note);
      }
    }
    if (tb.phase === "over" && tb.leader) btn(window.t("poker.payPotBtn", "🏆 Pay the pot to the best hand ({pot})", { pot: rawToNado(tb.pot) }), settleTable, true);
  }
  $("btnReclaim").classList.toggle("hidden", !(tb.exists && !tb.closed && tb.phase === "over" && !tb.leader && iAmHost));
  $("btnCancel").classList.toggle("hidden", !(tb.exists && !tb.closed && tb.seatCount === 1 && iAmHost));
  const stalledOpen = !tb.exists && T.ts && Date.now() - T.ts > 120000;
  if ($("btnReopen")) $("btnReopen").classList.toggle("hidden", !stalledOpen);
  const jh = $("joinHint");
  const hint = dapp.me && activeTable != null && !tb.exists ? dapp.whereIs("table", activeTable, T.ts) : "";  // SDK-localized
  if (jh) { jh.textContent = hint; jh.classList.toggle("hidden", !hint); }
}

// ---- boot ----------------------------------------------------------------------------------------
let watch = null;   // the submitted action we're waiting to see ON-CHAIN (flips status to "confirmed ✓")
const replayInvite = (id) => { activeTable = parseInt(id, 10); const j = $("joinId"); if (j) j.value = String(activeTable); joinTable(); };
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.table != null) activeTable = pend.table;
  if (ok && pend && (pend.phase === "connect" || pend.phase === "deposit")) dapp.consumeInvite(replayInvite);
  if (ok && pend && ["open", "join", "bet", "reveal", "settle", "start", "leave", "closest"].includes(pend.phase)) watch = Object.assign({}, pend, { ts: Date.now() });
  dapp.showReturn(pend, ok, err, {
    open: window.t("poker.retOpen", "Table opening — confirming…"), join: window.t("poker.retJoin", "Taking your seat — confirming…"), bet: window.t("poker.retBet", "Bet placed — confirming…"),
    reveal: window.t("poker.retReveal", "Showing your cards — confirming…"), settle: window.t("poker.retSettle", "Paying the winner…"), reclaim: window.t("poker.retReclaim", "Reclaiming…"), cancel: window.t("poker.retCancel", "Cancelling…"),
    start: window.t("poker.retStart", "Dealing — confirming…"), leave: window.t("poker.retLeave", "Leaving the table — refunding…"), closest: window.t("poker.retClose", "Fast-forwarding the street…") });
});
async function boot() {
  try { await dapp.init(); } catch (e) { alertBar(window.t("poker.cryptoFail", "Crypto bundle failed to load — reload.")); return; }
  wireUI(); loadQR(); orderCards(["activeGame","lobby","play","opencard","walletcard","bankroll","scoreboard"]);
  const q = new URLSearchParams(location.search).get("table");
  if (q) { $("joinId").value = q; if (activeTable == null) activeTable = parseInt(q, 10); }
  if (q && !dapp.me) { const tb = await fetchTable(parseInt(q, 10));
    inviteGate(dapp, { id: parseInt(q, 10), title: window.t("poker.inviteTitle", "You're invited to a hold'em table"),
      body: tb && tb.exists ? window.t("poker.inviteBody", "Sit down for an ante of <b>{a} NADO</b> — real multiplayer Texas Hold'em.", { a: rawToNado(tb.ante) }) : window.t("poker.inviteBodyGeneric", "Sign in to sit down at this table."),
      joinLabel: window.t("poker.inviteJoin", "Sign in & sit down") }); }
  else if (dapp.me) dapp.consumeInvite(replayInvite);   // signed in with a pending invite (e.g. reloaded mid-deposit) → auto-seat
  render(); refreshActive();
  setInterval(refreshActive, 3000);
}
boot();
