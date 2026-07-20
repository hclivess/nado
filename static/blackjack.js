// blackjack.js — NADO Blackjack: fully provable, with NO dealer to trust, built on the shared game SDK
// (nadodapp.js + bankedgame.js + cards.js). The "dealer" is a fixed on-chain strategy (stands on 17,
// soft or hard) whose cards come from block hashes bound AFTER you stand — nothing to peek at, nothing
// to rig. Your cards bind to future blocks at deal/hit time; every card is stored on-chain (pc/dk maps)
// so the exact hand reconstructs from chain state alone. Win pays 2×, push refunds, natural blackjack
// 5:2; European no-hole-card timing. See tests/test_blackjack_contract.py.
import { NadoDapp, rawToNado, nadoToRaw, _m, $, gate, canPay, orderCards, alertBar, notify, confirmingLabel, lsLoad as load, wireWallet, stickyInputs, renderWallet, renderScore, scoreBump, scoreSort, randId, loadQR, resolveAliases, disp, share, shareInvite , installModes } from "./nadodapp.js";
import { BankedGame } from "./bankedgame.js";
import { chainCards, cardHTML, injectCardCSS, bjTotal } from "./cards.js";
import { Practice } from "./practice.js";      // free in-browser practice (play chips, no chain)

const CID = "0f513c38ee16a7882d2a0efddd8d7625";
const REAP = 1200;
const dapp = new NadoDapp({ cid: CID, app: "Blackjack" });
const bg = new BankedGame(dapp, { icon: "🃏" });

let lastSto = null, myHand = null, watch = null;

// ---- reads (blackjack seat schema; cards live on-chain in pc/dk) ------------------------------------
function handFrom(sto, g) {
  g = String(g); const t = _m(sto, "gg")[g];
  if (!t) return { exists: false, g: Number(g) };
  const s = { exists: true, g: Number(g), table: Number(t), addr: _m(sto, "ga")[g], stake: _m(sto, "gs")[g] || 0,
    gf: _m(sto, "gf")[g] || 0, gh: _m(sto, "gh")[g] || 0, gn: _m(sto, "gn")[g] || 0, ge: _m(sto, "ge")[g] || 0,
    du: _m(sto, "du")[g] || 0, done: !!_m(sto, "gd")[g], res: _m(sto, "gw")[g] || 0, dealerBest: _m(sto, "gr")[g] || 0 };
  s.cards = []; for (let k = 0; k < s.gn; k++) { const c = _m(sto, "pc")[String(s.g * 16 + k)]; if (c) s.cards.push(c - 1); }
  s.dealer = []; for (let j = 0; j < 16; j++) { const c = _m(sto, "dk")[String(s.g * 16 + j)]; if (!c) break; s.dealer.push(c - 1); }
  s.total = bjTotal(s.cards);
  // a pending binding whose blocks already exist -> PREVIEW the outcome from fast provisional hashes
  if (!s.done && s.gh && dapp.cursor != null && dapp.cursor >= s.gh + 1) {
    const bh0 = dapp.bh(s.gh), bh1 = dapp.bh(s.gh + 1);
    if (s.gf === 1) { const cs = chainCards(bh0, bh1, s.g * 64, 2), up = chainCards(bh0, bh1, s.g * 64 + 16, 1); if (cs && up) s.preview = { cards: cs, up: up[0] }; }
    else if (s.gf === 3) { const c = chainCards(bh0, bh1, s.g * 64 + s.gn, 1); if (c) s.preview = { card: c[0] }; }
    else if (s.gf === 4) { const d = previewDealer(bh0, bh1, s.g, s.du - 1); if (d) s.preview = d; }
    s.ready = !!s.preview;
  }
  s.waiting = !s.done && s.gh && !s.ready;
  s.stale = !s.done && dapp.cursor != null && s.ge && dapp.cursor > s.ge + REAP;
  return s;
}
// simulate the dealer exactly as the contract will (S17): draw dk cards until best >= 17
function previewDealer(bh0, bh1, g, up) {
  if (!bh0 || !bh1 || up == null || up < 0) return null;
  const cards = [];
  const hand = () => bjTotal([up].concat(cards));
  for (let j = 0; j < 16; j++) {
    const c = chainCards(bh0, bh1, g * 64 + 32 + j, 1); if (!c) return null;
    cards.push(c[0]);
    if (bjTotal([up].concat(cards)).total >= 17) break;
  }
  return { dealer: cards, best: hand().total, bust: hand().total > 21 };
}
const handsOfTable = (sto, t) => Object.keys(_m(sto, "gg")).filter((g) => String(_m(sto, "gg")[g]) === String(t))
  .map((g) => handFrom(sto, g)).sort((a, b) => (b.ge - a.ge) || (b.g - a.g));
const maxStakeRaw = () => { const tb = lastTable(); return tb && tb.exists && !tb.closed ? tb.free * 2n / 3n : null; };
const lastTable = () => (lastSto && bg.active != null) ? bg.read(lastSto, bg.active) : null;

// ---- actions -----------------------------------------------------------------------------------------
function newTable() {
  const raw = nadoToRaw($("bankrollAmt").value);
  if (!raw) return alertBar(window.t("bj.enterBankroll", "Enter a bankroll (NADO)."));
  if (!canPay(dapp, raw, window.t("bj.whatBank", "Banking this table"))) return;
  const t = randId();   // mint the id FIRST — bg.open picks its id after the label is built (stale #{t})
  bg.reopen(t, raw, window.t("bj.callOpen", "bank a blackjack table #{t} · {amt} NADO", { t, amt: rawToNado(raw) }));
  render();
}
async function deal() {
  const tb = lastTable();
  if (!tb || !tb.exists) return alertBar(dapp.whereIs("table", bg.active));
  if (tb.closed) return alertBar(window.t("bj.closedTable", "That table is closed."));
  if (dapp.busy("deal", "table", bg.active)) return notify(confirmingLabel());   // one deal confirming at a time
  const stake = nadoToRaw($("stakeAmt").value);
  if (!stake) return alertBar(window.t("bj.enterStake", "Enter a stake (NADO)."));
  await dapp.refresh();
  if (!canPay(dapp, stake, window.t("bj.whatHand", "This hand"))) return;
  const mx = maxStakeRaw();
  if (mx != null && stake > mx) return alertBar(window.t("bj.stakeCap", "This table can only cover hands up to {n} NADO right now (every hand reserves a 5:2 blackjack cover).", { n: rawToNado(mx) }));
  const g = randId();
  bg.rememberSeat(g, { stake: stake.toString() });
  myHand = g;
  dapp.call("deal", [g, bg.active], stake, window.t("bj.callDeal", "🃏 deal blackjack · {amt} NADO · table #{t}", { amt: rawToNado(stake), t: bg.active }), { table: bg.active, seat: g, phase: "deal" });
  render();
}
const hit = () => { const s = myHandObj(); if (s && !dapp.busy("hit", "seat", s.g)) dapp.call("hit", [s.g], null, window.t("bj.callHit", "hit — one more card · hand #{g}", { g: s.g }), { table: bg.active, seat: s.g, phase: "hit" }); };
const stand = () => { const s = myHandObj(); if (s && !dapp.busy("stand", "seat", s.g)) dapp.call("stand", [s.g], null, window.t("bj.callStand", "stand on {n} · hand #{g}", { n: s.total.total, g: s.g }), { table: bg.active, seat: s.g, phase: "stand" }); };
const RESOLVE_METHOD = { 1: "reveal", 3: "draw", 4: "settle" };
const resolveHand = (s) => { if (dapp.busy("resolve", "seat", s.g)) return; dapp.call(RESOLVE_METHOD[s.gf], [s.g], null, window.t("bj.callResolve", "land the cards · hand #{g}", { g: s.g }), { table: bg.active, seat: s.g, phase: "resolve" }); };
const reapHand = (g) => { if (dapp.busy("resolve", "seat", g)) return; dapp.call("reap", [g], null, window.t("bj.callReap", "release abandoned hand #{g}", { g }), { table: bg.active, seat: g, phase: "resolve" }); };
function fundTable() {
  const raw = nadoToRaw($("fundAmt").value);
  if (!raw) return alertBar(window.t("bj.enterFund", "Enter an amount to add to this table's bankroll."));
  if (!canPay(dapp, raw, window.t("bj.whatFund", "The top-up"))) return;
  bg.fund(raw, window.t("bj.callFund", "top up table #{t} · {amt} NADO", { t: bg.active, amt: rawToNado(raw) }));
}
const closeTable = () => bg.close(window.t("bj.callClose", "close table #{t}", { t: bg.active }), { confirm: 1 });
function maybeAutoResolve(hands) {
  const tb = lastTable(); if (!tb || !tb.exists) return;
  const iAmBank = tb.bank === dapp.me;
  dapp.autoCollect(hands.filter((s) => !s.done && (s.ready && (iAmBank || s.addr === dapp.me) || (iAmBank && s.stale && !s.ready))),
    (s) => s.ready ? resolveHand(s) : reapHand(s.g), { blocked: watch });
}

// ---- refresh -----------------------------------------------------------------------------------------
async function refreshAll() {
  await dapp.refresh();
  const sto = await dapp.storage({ append: ["gd", "gw", "pc", "dk", "gn", "gp"] });
  if (sto) {
    lastSto = sto;
    bg.track(sto);
    // release the click guard the instant the effect lands (same per-phase done-test the `watch` toast uses).
    dapp.settleInflight((f) => {
      const g = String(f.seat), t = String(f.table), gf = _m(sto, "gf")[g] || 0;
      if (f.phase === "deal") return !!_m(sto, "gg")[g];
      if (f.phase === "hit") return gf === 3 || (gf === 2 && (_m(sto, "gn")[g] || 0) > (f.gn || 2)) || !!_m(sto, "gd")[g];
      if (f.phase === "stand") return gf === 4 || !!_m(sto, "gd")[g];
      if (f.phase === "resolve") return gf !== (f.gf || 0) || !!_m(sto, "gd")[g];
      return bg.landed(f, sto);   // open / fund / close
    });
    if (bg.active != null) await bg.prefetchHashes(sto, (g) => (!_m(sto, "gd")[g] && _m(sto, "gf")[g]) ? _m(sto, "gh")[g] || 0 : 0);
    if (watch) {
      const g = String(watch.seat), t = String(watch.table), gf = _m(sto, "gf")[g] || 0;
      const done =
        watch.phase === "open" ? !!_m(sto, "ta")[t] :
        watch.phase === "deal" ? !!_m(sto, "gg")[g] :
        watch.phase === "hit" ? gf === 3 || gf === 2 && (_m(sto, "gn")[g] || 0) > (watch.gn || 2) || !!_m(sto, "gd")[g] :
        watch.phase === "stand" ? gf === 4 || !!_m(sto, "gd")[g] :
        watch.phase === "resolve" ? gf !== (watch.gf || 0) || !!_m(sto, "gd")[g] :
        watch.phase === "close" ? !!_m(sto, "tz")[t] : true;
      if (done) {
        dapp.clearInflight();
        const okMsg = { open: window.t("bj.stOpen", "✓ Table is live — share it and earn the edge."), deal: window.t("bj.stDeal", "✓ Hand dealt to the next blocks…"),
          hit: window.t("bj.stHit", "✓ Card bound — landing…"), stand: window.t("bj.stStand", "✓ Standing — the dealer draws from the next blocks…"),
          resolve: window.t("bj.stResolve", "✓ Cards landed."), fund: window.t("bj.stFund", "✓ Bankroll topped up."), close: window.t("bj.stClose", "✓ Table closed — pool reclaimed.") }[watch.phase];
        if (okMsg) notify(okMsg);
        watch = null;
      } else if (watch.ts && Date.now() - watch.ts > 90000) watch = null;
    }
    const hands = bg.active != null ? handsOfTable(sto, bg.active) : [];
    maybeAutoResolve(hands);
    bg.lobby($("lobbyList"), sto, (m) => window.t("bj.lobbyChip", "🃏 #{id} · bank {bank} · {n} hands", { id: m.id, bank: rawToNado(m.tk), n: m.tn }), selectTable);
    renderScore($("scoreList"), boardFrom(sto), dapp.me, window.t("bj.noScores", "No finished hands yet — be the first on the board."), true);
    const tb = lastTable();
    await resolveAliases([dapp.me, tb && tb.exists ? tb.bank : null].concat(hands.slice(0, 12).map((s) => s.addr)).filter(Boolean));
  }
  render();
}
// the shared banked-game scoreboard walk; this game supplies only its own payout rule
// (1 = win pays 2x, 2 = push returns the stake, 3 = blackjack pays 5:2)
const boardFrom = (sto) => bg.scoreboard(sto, (g, stake) => {
  const res = _m(sto, "gw")[g] || 0;
  const pay = res === 1 ? 2 * stake : res === 2 ? stake : res === 3 ? Math.floor(stake * 5 / 2) : 0;
  return pay - stake;
});
function selectTable(id) {
  bg.active = id; myHand = null;
  $("joinId").value = String(id);
  notify(window.t("bj.tableSelected", "Table #{id} — set your stake, then Deal.", { id }));
  refreshAll();
  try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {}
}
function myHandObj() {
  if (!lastSto || bg.active == null) return null;
  if (myHand) { const s = handFrom(lastSto, myHand); if (s.exists && String(s.table) === String(bg.active)) return s; }
  const mine = handsOfTable(lastSto, bg.active).filter((s) => s.addr === dapp.me);
  const live = mine.find((s) => !s.done);
  const s = live || (myHand === 0 ? null : mine[0] || null);
  if (s) myHand = s.g;
  return s;
}

// ---- render ------------------------------------------------------------------------------------------
const RES_TEXT = () => ({
  1: '<span class="win">' + window.t("bj.resWin", "🏆 You win — paid 2× your stake.") + "</span>",
  2: window.t("bj.resPush", "🤝 Push — stake refunded."),
  3: '<span class="win">' + window.t("bj.resBJ", "🂡 BLACKJACK! Paid 5:2.") + "</span>",
  4: '<span class="lose">' + window.t("bj.resLose", "Dealer wins this one.") + "</span>",
  5: '<span class="lose">' + window.t("bj.resBust", "💥 Bust — over 21.") + "</span>",
  6: window.t("bj.resForfeit", "Hand released after inactivity."),
});
var render = function render() {
  dapp.reflectUrl("table", bg.active);
  dapp.syncPctSlider("bankroll", { slider: "bankrollSlider", input: "bankrollAmt" }, dapp.exec);
  dapp.syncPctSlider("fund", { slider: "fundSlider", input: "fundAmt" }, dapp.exec);
  const signedIn = renderWallet(dapp);
  gate({ play: signedIn, bankcard: signedIn, bankroll: signedIn, activeGame: bg.active != null });
  bg.recent($("recent"), selectTable, (x) => {
    if (!lastSto) return "";
    const live = handsOfTable(lastSto, x.id).some((s) => s.addr === dapp.me && !s.done);
    return live ? window.t("bj.tagLive", "hand live") : "";
  });
  if (bg.active == null) return;
  const tb = lastTable() || { exists: false };
  const Trec = bg.tableRec(bg.active) || {};
  $("gameId").textContent = "#" + bg.active;
  shareInvite("table", bg.active, window.t("bj.shareText", "Play blackjack at my table #{t} on NADO:", { t: bg.active }), 180);
  const iAmBank = tb.exists && tb.bank === dapp.me;
  $("gBank").textContent = tb.exists ? (disp(tb.bank) + (iAmBank ? window.t("bj.thatsYou", " — that's you (the house)") : "")) : (Trec.bankroll ? window.t("bj.opening", "you (opening…)") : "—");
  $("gBankroll").textContent = tb.exists ? rawToNado(tb.tk) + " NADO" : (Trec.bankroll ? rawToNado(Trec.bankroll) + " NADO" : "—");
  $("gCover").textContent = tb.exists ? window.t("bj.nadoFree", "{amt} NADO free", { amt: rawToNado(tb.free) }) : "—";
  $("gStatus").textContent = !tb.exists ? dapp.whereIs("table", bg.active, Trec.ts)
    : tb.closed ? window.t("bj.phaseClosed", "table closed")
    : window.t("bj.phaseOpen", "🟢 open · {n} hands played", { n: tb.tx });
  gate({ fundRow: iAmBank && tb.exists && !tb.closed });
  $("btnClose").classList.toggle("hidden", !(iAmBank && tb.exists && !tb.closed && tb.tx >= tb.tn));
  const s = signedIn ? myHandObj() : null;
  const inHand = s && s.exists;
  gate({ betBuilder: signedIn && tb.exists && !tb.closed && (!s || s.done), felt: !!inHand });
  if (signedIn && tb.exists) {
    dapp.syncStakeSlider(maxStakeRaw());
    const stake = nadoToRaw($("stakeAmt").value);
    $("btnDeal").disabled = !stake || (maxStakeRaw() != null && stake > maxStakeRaw()) || dapp.busy("deal") || !!(s && !s.done);
    $("btnDeal").classList.toggle("pulse", !$("btnDeal").disabled);
  }
  if (!inHand) { renderHands(); return; }
  // ---- the felt ----
  const dealerCards = [];
  let dealerNote = "";
  if (s.du) dealerCards.push(s.du - 1);
  if (s.done && s.dealer.length) { dealerCards.push(...s.dealer); dealerNote = window.t("bj.dealerShows", "dealer: {n}", { n: s.dealerBest }); }
  else if (s.gf === 4 && s.preview) { dealerCards.push(...s.preview.dealer); dealerNote = window.t("bj.dealerDrawing", "dealer draws {n} — confirming…", { n: s.preview.best }); }
  else if (s.gf === 4) { dealerCards.push(null); dealerNote = window.t("bj.dealerWaits", "dealer's cards are locking to the next blocks…"); }
  else if (s.du) { dealerCards.push(null); dealerNote = window.t("bj.dealerHole", "hole card is drawn after you stand"); }
  $("dealerRow").innerHTML = dealerCards.length ? dealerCards.map((c) => cardHTML(c)).join("") : cardHTML(null) + cardHTML(null);
  $("dealerNote").textContent = dealerNote;
  const pcards = s.cards.slice();
  if (s.gf === 1 && s.preview) pcards.push(...s.preview.cards);
  if (s.gf === 3 && s.preview) pcards.push(s.preview.card);
  $("playerRow").innerHTML = pcards.length ? pcards.map((c) => cardHTML(c, true)).join("") : cardHTML(null, true) + cardHTML(null, true);
  const pt = bjTotal(pcards);
  $("playerTotal").textContent = pcards.length ? (pt.total + (pt.soft ? window.t("bj.soft", " soft") : "")) : "—";
  $("handStake").textContent = rawToNado(s.stake) + " NADO";
  // verdict
  let v = "";
  if (s.done) v = RES_TEXT()[s.res] || "";
  else if (s.gf === 1) v = s.preview ? window.t("bj.dealLanding", "Your cards are in — confirming on-chain…") : window.t("bj.dealing", "🂠 Dealing from the next blocks…");
  else if (s.gf === 3) v = s.preview ? window.t("bj.cardLanding", "Card drawn — confirming…") : window.t("bj.drawing", "🂠 Drawing your card…");
  else if (s.gf === 4) v = s.preview ? (s.preview.bust ? '<span class="win">' + window.t("bj.dealerBusting", "Dealer BUSTS with {n} — confirming your win…", { n: s.preview.best }) + "</span>" : window.t("bj.dealerLanded", "Dealer stands on {n} — settling…", { n: s.preview.best })) : window.t("bj.dealerThinking", "Dealer draws from the next blocks…");
  else if (pt.bust) v = window.t("bj.busting", "Over 21 — confirming…");
  else if (pt.natural) v = '<span class="win">' + window.t("bj.natural", "🂡 Blackjack! Stand to collect 5:2.") + "</span>";
  else v = window.t("bj.yourMove", "Your move: hit for another card, or stand on {n}.", { n: pt.total });
  $("verdict").innerHTML = v;
  // actions
  const acts = $("handActions"); acts.innerHTML = "";
  const mkBtn = (txt, fn, primary, pulse) => { const b = document.createElement("button"); b.className = (primary ? "primary" : "ghost") + (pulse ? " pulse" : ""); b.style.flex = "1 1 auto"; b.textContent = txt; b.onclick = fn; acts.appendChild(b); return b; };
  const busy = dapp.busy("hit") || dapp.busy("stand") || dapp.busy("resolve");
  if (!s.done && s.gf === 2 && s.addr === dapp.me && !busy) {
    if (s.gn < 11 && !pt.natural) mkBtn(window.t("bj.hit", "🂠 Hit"), hit, false);
    mkBtn(window.t("bj.stand", "✋ Stand on {n}", { n: pt.total }), stand, true, pt.total >= 17 || pt.natural);
  }
  if (!s.done && s.ready && !busy) mkBtn(window.t("bj.landNow", "Land the cards now"), () => resolveHand(s), false);
  if (s.done && dapp.me) mkBtn(window.t("bj.newHand", "↻ New hand"), () => { myHand = 0; render(); }, true, true);
  renderHands();
}
function renderHands() {
  const el = $("seats"); if (!el || !lastSto || bg.active == null) return;
  const tb = lastTable(); const iAmBank = tb && tb.exists && tb.bank === dapp.me;
  const hands = handsOfTable(lastSto, bg.active).slice(0, 30);
  const resShort = { 1: window.t("bj.sWin", "won 2×"), 2: window.t("bj.sPush", "push"), 3: window.t("bj.sBJ", "BLACKJACK 5:2"), 4: window.t("bj.sLose", "lost"), 5: window.t("bj.sBust", "bust"), 6: window.t("bj.sVoid", "released") };
  el.innerHTML = hands.length ? hands.map((s) => {
    const you = s.addr === dapp.me ? '<b style="color:var(--accent2)">' + window.t("bj.you", "you") + "</b> " : "";
    let out = s.done
      ? (s.res === 1 || s.res === 3 ? '<span class="b ok">' : '<span class="b dimb">') + (resShort[s.res] || "—") + "</span>"
      : '<span class="b pend">' + (s.gf === 2 ? window.t("bj.sPlaying", "{n} showing", { n: s.total.total }) : window.t("bj.sDrawing", "drawing…")) + "</span>";
    const reapB = s.stale && !s.ready && (iAmBank || s.addr === dapp.me) ? ' <button class="ghost" style="padding:2px 8px;font-size:11px" data-reap="' + s.g + '">' + window.t("bj.releaseSeat", "release") + "</button>" : "";
    return '<div class="seat">' + you + disp(s.addr) + ' · <span class="mono">' + rawToNado(s.stake) + "</span> " + out + reapB + "</div>";
  }).join("") : '<span class="dim">' + window.t("bj.noHands", "No hands yet — deal the first one.") + "</span>";
  el.querySelectorAll("[data-reap]").forEach((b) => b.onclick = () => reapHand(parseInt(b.dataset.reap, 10)));
}

// ---- boot --------------------------------------------------------------------------------------------
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.table != null) bg.active = pend.table;
  if (pend && pend.seat != null && pend.phase !== "resolve") myHand = pend.seat;
  if (ok && pend && ["open", "deal", "hit", "stand", "resolve", "fund", "close"].includes(pend.phase)) {
    watch = Object.assign({}, pend, { ts: Date.now() });
    if (lastSto && pend.seat != null) { watch.gn = _m(lastSto, "gn")[String(pend.seat)] || 2; watch.gf = _m(lastSto, "gf")[String(pend.seat)] || 0; }
  }
  dapp.showReturn(pend, ok, err, {
    deal: window.t("bj.pendDeal", "🃏 Dealing — the cards lock to the next blocks…"), hit: window.t("bj.pendHit", "Hit — your card locks to the next blocks…"),
    stand: window.t("bj.pendStand", "Standing — the dealer draws next…"), resolve: window.t("bj.pendResolve", "Landing the cards…") });
});
function wireUI() {
  wireWallet(dapp);
  stickyInputs(dapp, ["stakeAmt", "bankrollAmt", "fundAmt", "bankAmt"]);
  $("btnNewTable").onclick = newTable;
  $("btnDeal").onclick = deal;
  $("btnGoTable").onclick = () => { const id = parseInt($("joinId").value, 10); if (id) selectTable(id); else alertBar(window.t("bj.enterTableId", "Enter a table ID, or pick one from the lobby.")); };
  $("btnClose").onclick = closeTable;
  $("btnFund").onclick = fundTable;
  dapp.wireStakeSlider(maxStakeRaw, render);
  dapp.wirePctSlider("bankroll", { slider: "bankrollSlider", input: "bankrollAmt" }, () => dapp.exec, render);
  dapp.wirePctSlider("fund", { slider: "fundSlider", input: "fundAmt" }, () => dapp.exec, render);
  dapp.wireAutoCollect();
}
async function boot() {
  try { await dapp.init(); } catch (e) { alertBar(window.t("bj.cryptoFail", "Crypto bundle failed to load — reload.")); return; }
  injectCardCSS();
  wireUI(); loadQR();
  orderCards(["activeGame", "lobby", "play", "practice", "bankcard", "walletcard", "bankroll", "scoreboard"]);

// ONE mode picker, from the SDK — the same control in every game. Practice used to be a card parked
// below the staked game with no way to switch to it; now it is a mode you choose, and ?mode=practice
// links straight to it.
const modes = installModes(dapp, {
  modes: [
    { key: "play", icon: "🃏", label: window.t("sdk.modePlay", "Play for stakes"),
      hint: window.t("sdk.modePlayHint", "Real NADO on the execution layer."), cards: ["lobby", "play", "bankcard", "scoreboard"], keep: ["activeGame"] },
    { key: "practice", icon: "🤖", label: window.t("sdk.modePractice", "Practice"),
      badge: window.t("sdk.free", "free"),
      hint: window.t("sdk.modePracticeHint", "Play the computer in your browser — nothing on-chain."),
      cards: ["practice"] },
  ],
});
// mode gating layers OVER the game's own render, which gates cards by sign-in/table state
render = modes.wrap(render);   // re-apply the mode gating after every render
  const q = new URLSearchParams(location.search).get("table");
  if (q) { $("joinId").value = q; if (bg.active == null) bg.active = parseInt(q, 10); }
  render(); refreshAll();
  setInterval(refreshAll, 3000);
}
boot();

// ---- PRACTICE MODE (free, fully in-browser — play chips, local RNG, nothing on-chain) -----------------
// Mirrors the contract exactly (execnode/games/blackjack.py): infinite shoe (independent draws, same as
// the chain's per-card hashes), European no-hole-card, a natural pays 5:2 at the deal WITHOUT the dealer
// playing, the dealer draws to S17 (soft 17 stands — same bjTotal), win pays 2×, push refunds.
// Math.random is fine here because nothing is at stake.
const prac = new Practice("blackjack");
let pState = null;
const pDraw = () => Math.floor(Math.random() * 52);
const pDealerTotal = () => bjTotal([pState.up].concat(pState.dealer));
function pFinish(res, pay) { pState.done = true; pState.res = res; if (pay) prac.addChips(pay); pracRender(); }
function pDeal() {
  const bet = parseInt($("pStake").value, 10) || 0;
  if (!prac.canBet(bet, notify)) return false;
  prac.addChips(-bet);
  pState = { bet, cards: [pDraw(), pDraw()], up: pDraw(), dealer: [], done: false, res: 0 };
  if (bjTotal(pState.cards).natural) { pFinish(3, Math.floor(bet * 5 / 2)); return true; }   // reveal pays 5:2 instantly — the dealer never plays (contract)
  pracRender();
  return true;
}
function pHit() {
  pState.cards.push(pDraw());
  if (bjTotal(pState.cards).bust) return pFinish(5, 0);
  pracRender();
}
function pStand() {
  while (pState.dealer.length < 16 && pDealerTotal().total < 17) pState.dealer.push(pDraw());   // S17 — the same loop as SETTLE
  const dt = pDealerTotal(), pt = bjTotal(pState.cards);
  if (dt.bust || pt.total > dt.total) pFinish(1, 2 * pState.bet);
  else if (pt.total === dt.total) pFinish(2, pState.bet);
  else pFinish(4, 0);
}
function pracRender() {
  prac.strip($("pStrip"), { chips: true, onReset: pracRender });
  const s = pState;
  $("pFelt").classList.toggle("hidden", !s);
  $("pBetRow").classList.toggle("hidden", !!(s && !s.done));
  if (!s) return;
  const dcards = [s.up].concat(s.done ? s.dealer : [null]);
  $("pDealerRow").innerHTML = dcards.map((c) => cardHTML(c)).join("");
  $("pDealerNote").textContent = s.done
    ? (s.dealer.length ? window.t("bj.dealerShows", "dealer: {n}", { n: pDealerTotal().total }) : "")
    : window.t("bj.dealerHole", "hole card is drawn after you stand");
  $("pPlayerRow").innerHTML = s.cards.map((c) => cardHTML(c, true)).join("");
  const pt = bjTotal(s.cards);
  $("pPlayerTotal").textContent = pt.total + (pt.soft ? window.t("bj.soft", " soft") : "");
  $("pHandStake").textContent = "🪙 " + s.bet;
  const net = s.res === 1 ? s.bet : s.res === 3 ? Math.floor(s.bet * 5 / 2) - s.bet : 0;
  $("pResult").innerHTML = !s.done ? "" : (RES_TEXT()[s.res] || "")
    + (s.res === 1 || s.res === 3 ? ' <span class="chip" style="border-color:var(--win);color:var(--win)">🪙 ' + window.t("sdk.prWonChips", "+{n} play chips", { n: net }) + "</span>"
      : s.res === 2 ? "" : ' <span class="chip">🪙 ' + window.t("sdk.prLostChips", "−{n} play chips", { n: s.bet }) + "</span>");
  const acts = $("pActions"); acts.innerHTML = "";
  const mk = (txt, fn, primary) => { const b = document.createElement("button"); b.className = primary ? "primary" : "ghost"; b.style.flex = "1 1 auto"; b.textContent = txt; b.onclick = fn; acts.appendChild(b); return b; };
  if (!s.done) {
    if (s.cards.length < 11) mk(window.t("bj.hit", "🂠 Hit"), pHit, false);
    mk(window.t("bj.stand", "✋ Stand on {n}", { n: pt.total }), pStand, true);
  } else mk("↻ " + window.t("sdk.prDealAgain", "Deal again — {n} play chips", { n: s.bet }),
    () => { if (!pDeal()) { pState = null; pracRender(); } }, true);   // redeal in place — never collapse the felt
}
if ($("pDeal")) { $("pDeal").onclick = pDeal; pracRender(); }
