// mines.js — NADO Mines: the crypto-casino classic, dealer-less, built on the shared game SDK
// (nadodapp.js + bankedgame.js). A 5x5 field hides N mines you choose; reveal tiles — every safe
// reveal multiplies your payout ×(tilesLeft·99)/((tilesLeft−N)·100) — and CASH OUT any time; one mine
// loses the stake. The tile POSITIONS are theater; the ODDS are provable: each reveal batch binds to
// two FUTURE L1 block hashes when you pick, and draw_i = HASH(bh(gh)+bh(gh+1)+seat·100 + picks+i) mod
// tilesLeft is a mine iff < N. Resolve is permissionless; reap() frees abandoned seats. See
// tests/test_mines_contract.py — the contract enforces exactly this math.
import { NadoDapp, rawToNado, nadoToRaw, blake2bHash, _m, $, gate, canPay, orderCards, alertBar, notify, confirmingLabel, lsLoad as load, wireWallet, stickyInputs, renderWallet, renderScore, scoreBump, scoreSort, randId, loadQR, resolveAliases, disp, share, shareInvite , installModes , playModes} from "./nadodapp.js?v=4984604e";
import { BankedGame } from "./bankedgame.js?v=f1ece883";
import { Practice } from "./practice.js?v=77683a2a";      // free in-browser practice (play chips, no chain)

const CID = "7eb0aea6093def505d2f83957b2333cc";
const T = 25, NMIN = 1, NMAX = 24, PICK_D = 2, REAP = 1200;
const dapp = new NadoDapp({ cid: CID, app: "Mines" });
const bg = new BankedGame(dapp, { icon: "💣" });

let lastSto = null, mySeat = null, mines = 3, sel = [], watch = null;

// ---- derivation (mirror of the contract — display only; resolve recomputes it on-chain) -------------
const H = (v) => BigInt("0x" + blake2bHash(v));
function batchDraws(bh0, bh1, g, gp, count, N) {
  if (!bh0 || !bh1) return null;
  const q = BigInt("0x" + bh0) + BigInt("0x" + bh1) + BigInt(g) * 100n;
  const draws = [];
  for (let i = 0; i < count; i++) {
    const d = Number(H(q + BigInt(gp + i)) % BigInt(T - gp - i));
    draws.push(d);
    if (d < N) return { bust: i + 1, draws };
  }
  return { bust: 0, draws };
}
// value after `count` more safe reveals from (v, gp) with N mines — EXACT contract integer math
function valueAfter(v, gp, N, count) {
  v = BigInt(v);
  for (let i = 0; i < count; i++) { const rem = BigInt(T - gp - i); v = v * rem * 99n / ((rem - BigInt(N)) * 100n); }
  return v;
}
const multAfter = (N, picks) => Number(valueAfter(10n ** 12n, 0, N, picks)) / 1e12;   // display only

// ---- reads (mines seat schema) ----------------------------------------------------------------------
function seatFrom(sto, g) {
  g = String(g); const t = _m(sto, "gg")[g];
  if (!t) return { exists: false, g: Number(g) };
  const s = { exists: true, g: Number(g), table: Number(t), addr: _m(sto, "ga")[g], stake: _m(sto, "gs")[g] || 0,
    N: _m(sto, "gn")[g] || 0, gp: _m(sto, "gp")[g] || 0, gv: _m(sto, "gv")[g] || 0, gq: _m(sto, "gq")[g] || 0,
    gc: _m(sto, "gc")[g] || 0, gh: _m(sto, "gh")[g] || 0, ge: _m(sto, "ge")[g] || 0,
    done: !!_m(sto, "gd")[g], bust: _m(sto, "gb")[g] || 0, gw: _m(sto, "gw")[g] || 0 };
  if (!s.done && s.gh) {
    if (dapp.cursor != null && dapp.cursor >= s.gh + 1) {
      s.result = batchDraws(dapp.bh(s.gh), dapp.bh(s.gh + 1), s.g, s.gp, s.gc, s.N);
      if (s.result) s.ready = true; else s.waiting = true;
    } else s.waiting = true;
  }
  s.alive = !s.done;
  s.stale = !s.done && dapp.cursor != null && s.ge && dapp.cursor > s.ge + REAP;
  return s;
}
const seatsOfTable = (sto, t) => Object.keys(_m(sto, "gg")).filter((g) => String(_m(sto, "gg")[g]) === String(t))
  .map((g) => seatFrom(sto, g)).sort((a, b) => (b.ge - a.ge) || (b.g - a.g));

// the biggest stake this table can still cover for the FIRST reveal at N mines:
// need = stake·25·99/((25−N)·100) − stake  ≤ free   =>   stake ≤ free·(25−N)·100 / (2475 − (25−N)·100)
function maxStakeRaw(m = mines) {
  const tb = lastTable(); if (!tb || !tb.exists || tb.closed) return null;
  const d = 2475n - BigInt(25 - m) * 100n;
  return d > 0n ? tb.free * BigInt(25 - m) * 100n / d : null;
}
const lastTable = () => (lastSto && bg.active != null) ? bg.read(lastSto, bg.active) : null;

// ---- actions -----------------------------------------------------------------------------------------
function newTable() {
  const raw = nadoToRaw($("bankrollAmt").value);
  if (!raw) return alertBar(window.t("mines.enterBankroll", "Enter a bankroll (NADO)."));
  if (!canPay(dapp, raw, window.t("mines.whatBank", "Banking this field"))) return;
  const t = randId();   // mint the id FIRST — bg.open picks its id after the label is built (stale #{t})
  bg.reopen(t, raw, window.t("mines.callOpen", "bank a mines field #{t} · {amt} NADO", { t, amt: rawToNado(raw) }));
  render();
}
async function placeBet(stake, m) {
  const tb = lastTable();
  if (!tb || !tb.exists) return alertBar(dapp.whereIs("field", bg.active));
  if (tb.closed) return alertBar(window.t("mines.closedField", "That field is closed."));
  if (dapp.busy("bet", "table", bg.active)) return notify(confirmingLabel());   // one round confirming at a time
  if (!stake) return alertBar(window.t("mines.enterStake", "Enter a stake (NADO)."));
  await dapp.refresh();
  if (!canPay(dapp, stake, window.t("mines.whatRound", "This round"))) return;
  const mx = maxStakeRaw(m);
  if (mx != null && stake > mx) return alertBar(window.t("mines.stakeCap", "This field can only cover rounds up to {n} NADO at {m} mines right now.", { n: rawToNado(mx), m }));
  const g = randId();
  bg.rememberSeat(g, { stake: stake.toString(), N: m, tiles: [] });
  mySeat = g; sel = [];
  dapp.call("bet", [g, bg.active, m], stake, window.t("mines.callBet", "mines: {m} mines · {amt} NADO · field #{t}", { m, amt: rawToNado(stake), t: bg.active }), { table: bg.active, seat: g, phase: "bet" });
  render();
}
const startRound = () => placeBet(nadoToRaw($("stakeAmt").value), mines);
function reveal() {
  const s = mySeatObj();
  if (!s || !s.alive || s.gh || !sel.length || dapp.busy("pick", "seat", s.g)) return;
  bg.patchSeat(s.g, { tiles: (bg.seatRec(s.g)?.tiles || []).concat(sel) });
  dapp.call("pick", [s.g, sel.length], null, window.t("mines.callPick", "reveal {n} tiles · seat #{g}", { n: sel.length, g: s.g }), { table: bg.active, seat: s.g, phase: "pick" });
  sel = [];
  render();
}
const resolveSeat = (g) => { if (dapp.busy("resolve", "seat", g)) return; dapp.call("resolve", [g], null, window.t("mines.callResolve", "resolve reveal · seat #{g}", { g }), { table: bg.active, seat: g, phase: "resolve" }); };
function cashout() {
  const s = mySeatObj();
  if (!s || !s.alive || s.gh || dapp.busy("cashout", "seat", s.g)) return;
  dapp.call("cashout", [s.g], null, window.t("mines.callCash", "💰 cash out {amt} NADO · seat #{g}", { amt: rawToNado(s.gv), g: s.g }), { table: bg.active, seat: s.g, phase: "cashout" });
}
const reapSeat = (g) => { if (dapp.busy("resolve", "seat", g)) return; dapp.call("reap", [g], null, window.t("mines.callReap", "release abandoned seat #{g}", { g }), { table: bg.active, seat: g, phase: "resolve" }); };
function fundTable() {
  const raw = nadoToRaw($("fundAmt").value);
  if (!raw) return alertBar(window.t("mines.enterFund", "Enter an amount to add to this field's bankroll."));
  if (!canPay(dapp, raw, window.t("mines.whatFund", "The top-up"))) return;
  bg.fund(raw, window.t("mines.callFund", "top up field #{t} · {amt} NADO", { t: bg.active, amt: rawToNado(raw) }));
}
const closeTable = () => bg.close(window.t("mines.callClose", "close field #{t}", { t: bg.active }), { confirm: 1 });

// AUTO-RESOLVE (the shared SDK tick): my pending batches the chain has already decided — and, as the
// bank, ANY ready or stale seat (frees the cover; busts fold into my bankroll).
function maybeAutoResolve(seats) {
  const tb = lastTable(); if (!tb || !tb.exists) return;
  const iAmBank = tb.bank === dapp.me;
  dapp.autoCollect(seats.filter((s) => !s.done && (s.ready && (iAmBank || s.addr === dapp.me) || (iAmBank && s.stale))),
    (s) => s.ready ? resolveSeat(s.g) : reapSeat(s.g), { blocked: watch });
}

// ---- refresh -----------------------------------------------------------------------------------------
async function refreshAll() {
  await dapp.refresh();
  const sto = await dapp.storage({ append: ["gd", "gb", "gw", "gp"] });
  if (sto) {
    lastSto = sto;
    bg.track(sto);
    // release the click guard the instant the effect lands (same per-phase done-test the `watch` toast uses).
    dapp.settleInflight((f) => {
      const g = String(f.seat), t = String(f.table);
      if (f.phase === "bet") return !!_m(sto, "gg")[g];
      if (f.phase === "pick") return !!(_m(sto, "gh")[g] || _m(sto, "gd")[g]);
      if (f.phase === "resolve") return !(_m(sto, "gh")[g]) || !!_m(sto, "gd")[g];
      if (f.phase === "cashout") return !!_m(sto, "gd")[g];
      return bg.landed(f, sto);   // open / fund / close
    });
    if (bg.active != null) await bg.prefetchHashes(sto);
    if (watch) {
      const g = String(watch.seat), t = String(watch.table);
      const done =
        watch.phase === "open" ? !!_m(sto, "ta")[t] :
        watch.phase === "bet" ? !!_m(sto, "gg")[g] :
        watch.phase === "pick" ? !!(_m(sto, "gh")[g] || _m(sto, "gd")[g]) :
        watch.phase === "resolve" ? !(_m(sto, "gh")[g]) || !!_m(sto, "gd")[g] :
        watch.phase === "cashout" ? !!_m(sto, "gd")[g] :
        watch.phase === "close" ? !!_m(sto, "tz")[t] : true;
      if (done) {
        dapp.clearInflight();
        const okMsg = { open: window.t("mines.stOpen", "✓ Field is live — share it and earn the edge."),
          bet: window.t("mines.stBet", "✓ Round started — tap tiles to reveal."), pick: window.t("mines.stPick", "✓ Reveal locked to the next blocks…"),
          resolve: window.t("mines.stResolve", "✓ Resolved on-chain."), cashout: window.t("mines.stCash", "✓ Cashed out — tokens are in your balance."),
          fund: window.t("mines.stFund", "✓ Bankroll topped up."), close: window.t("mines.stClose", "✓ Field closed — pool reclaimed.") }[watch.phase];
        if (okMsg) notify(okMsg);
        watch = null;
      } else if (watch.ts && Date.now() - watch.ts > 90000) watch = null;
    }
    const seats = bg.active != null ? seatsOfTable(sto, bg.active) : [];
    maybeAutoResolve(seats);
    bg.lobby($("lobbyList"), sto, (m) => window.t("mines.lobbyChip", "💣 #{id} · bank {bank} · {n} rounds", { id: m.id, bank: rawToNado(m.tk), n: m.tn }), selectTable);
    renderScore($("scoreList"), boardFrom(sto), dapp.me, window.t("mines.noScores", "No finished rounds yet — be the first on the board."), true);
    const tb = lastTable();
    await resolveAliases([dapp.me, tb && tb.exists ? tb.bank : null].concat(seats.slice(0, 12).map((s) => s.addr)).filter(Boolean));
  }
  render();
}
// the shared banked-game scoreboard walk; this game supplies only its own payout rule
// (cashed out or reaped pays gv; a bust loses the stake)
const boardFrom = (sto) => bg.scoreboard(sto, (g, stake) =>
  _m(sto, "gw")[g] ? Number(_m(sto, "gv")[g] || 0) - stake : -stake);
function selectTable(id) {
  bg.active = id; mySeat = null; sel = [];
  $("joinId").value = String(id);
  notify(window.t("mines.fieldSelected", "Field #{id} — pick your mines and stake, then Start round.", { id }));
  refreshAll();
  try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {}
}

// my newest seat at the active table (prefer a live one; else the freshest finished one, so the result
// stays up). mySeat === 0 = the player dismissed the finished round ("Change bet") — only a LIVE seat
// may take the stage again.
function mySeatObj() {
  if (!lastSto || bg.active == null) return null;
  if (mySeat) { const s = seatFrom(lastSto, mySeat); if (s.exists && String(s.table) === String(bg.active)) return s; }
  const mine = seatsOfTable(lastSto, bg.active).filter((s) => s.addr === dapp.me);
  const live = mine.find((s) => s.alive);
  const s = live || (mySeat === 0 ? null : mine[0] || null);
  if (s) mySeat = s.g;
  return s;
}

// ---- render ------------------------------------------------------------------------------------------
function tileStates(s) {
  // -> array of 25 tile states: "" hidden · sel · pend · gem · boom, from the LS pick order (this
  // device); a foreign device shows revealed counts on the leading tiles (positions are client theater).
  const st = Array(T).fill("");
  if (!s || !s.exists) return st;
  const rec = bg.seatRec(s.g) || {};
  let tiles = rec.tiles || [];
  const provisional = s.ready ? (s.result.bust ? s.result.bust - 1 : s.gc) : 0;
  const safe = s.gp + provisional;
  const mineStep = s.ready && s.result.bust ? s.gp + s.result.bust - 1 : (s.done && s.bust ? s.gp + s.bust - 1 : null);
  if (tiles.length < safe + (mineStep != null ? 1 : 0)) {           // no local record → generic placement
    tiles = Array.from({ length: T }, (_, i) => i);
  }
  for (let k = 0; k < safe && k < tiles.length; k++) st[tiles[k]] = "gem";
  if (mineStep != null && tiles[mineStep] != null) st[tiles[mineStep]] = "boom";
  if (s.waiting) for (let k = s.gp; k < s.gp + s.gc && k < tiles.length; k++) if (!st[tiles[k]]) st[tiles[k]] = "pend";
  for (const i of sel) if (!st[i]) st[i] = "sel";
  return st;
}
var render = function render() {
  dapp.reflectUrl("table", bg.active);
  dapp.syncPctSlider("bankroll", { slider: "bankrollSlider", input: "bankrollAmt" }, dapp.exec);
  dapp.syncPctSlider("fund", { slider: "fundSlider", input: "fundAmt" }, dapp.exec);
  const signedIn = renderWallet(dapp);
  gate({ play: signedIn, bankcard: signedIn, bankroll: signedIn, activeGame: bg.active != null });
  bg.recent($("recent"), selectTable, (x) => {
    if (!lastSto) return "";
    const live = seatsOfTable(lastSto, x.id).some((s) => s.addr === dapp.me && s.alive);
    return live ? window.t("mines.tagLive", "round live") : "";
  });
  if (bg.active == null) return;
  const tb = lastTable() || { exists: false };
  const Trec = bg.tableRec(bg.active) || {};
  $("gameId").textContent = "#" + bg.active;
  shareInvite("table", bg.active, window.t("mines.shareText", "Clear the minefield #{t} on NADO:", { t: bg.active }), 180);
  const iAmBank = tb.exists && tb.bank === dapp.me;
  $("gBank").textContent = tb.exists ? (disp(tb.bank) + (iAmBank ? window.t("mines.thatsYou", " — that's you (the house)") : "")) : (Trec.bankroll ? window.t("mines.opening", "you (opening…)") : "—");
  $("gBankroll").textContent = tb.exists ? rawToNado(tb.tk) + " NADO" : (Trec.bankroll ? rawToNado(Trec.bankroll) + " NADO" : "—");
  $("gCover").textContent = tb.exists ? window.t("mines.nadoFree", "{amt} NADO free", { amt: rawToNado(tb.free) }) : "—";
  $("gStatus").textContent = !tb.exists ? dapp.whereIs("field", bg.active, Trec.ts)
    : tb.closed ? window.t("mines.phaseClosed", "field closed")
    : window.t("mines.phaseOpen", "🟢 open · {n} rounds played", { n: tb.tx });
  gate({ fundRow: iAmBank && tb.exists && !tb.closed });
  $("btnClose").classList.toggle("hidden", !(iAmBank && tb.exists && !tb.closed && tb.tx >= tb.tn));
  const s = signedIn ? mySeatObj() : null;
  const inRound = s && s.exists && (s.alive || s.done);
  const betting = !s || !s.alive;
  gate({ betBuilder: signedIn && tb.exists && !tb.closed && betting, grid: !!inRound });
  // bet builder
  if (signedIn && tb.exists && betting) {
    mines = Math.min(NMAX, Math.max(NMIN, parseInt($("minesN").value, 10) || 3));
    $("minesVal").textContent = mines;
    $("nextMult").textContent = "×" + multAfter(mines, 1).toFixed(3);
    $("run5Mult").textContent = "×" + multAfter(mines, Math.min(5, T - mines)).toFixed(2);
    dapp.syncStakeSlider(maxStakeRaw());
    const stake = nadoToRaw($("stakeAmt").value);
    $("btnStart").disabled = !stake || (maxStakeRaw() != null && stake > maxStakeRaw()) || dapp.busy("bet");
    $("btnStart").classList.toggle("pulse", !$("btnStart").disabled);
  }
  if (!inRound) { $("verdict").textContent = ""; renderSeats(); return; }
  // the round
  const rem = T - s.gp, nextMult = s.alive ? Number(valueAfter(10n ** 12n, s.gp, s.N, 1)) / 1e12 : 0;
  $("mMines").textContent = s.N;
  $("mRevealed").textContent = s.gp + " / " + (T - s.N);
  $("mValue").textContent = rawToNado(s.gv) + " NADO";
  $("mMult").textContent = "×" + (Number(BigInt(s.gv) * 1000n / BigInt(s.stake)) / 1000).toFixed(3);
  const grid = $("mgrid");
  const canTap = s.alive && !s.gh && !dapp.busy("pick") && s.addr === dapp.me;
  const states = tileStates(s);
  grid.innerHTML = states.map((st, i) =>
    '<div class="tile ' + st + (canTap && !st ? " live" : "") + '" data-i="' + i + '">' +
    (st === "gem" ? "💎" : st === "boom" ? "💥" : st === "pend" ? "⏳" : st === "sel" ? "✓" : "") + "</div>").join("");
  if (!grid._deleg) { grid._deleg = true; grid.addEventListener("click", (e) => { const el = e.target.closest(".tile"); if (el) tapTile(parseInt(el.dataset.i, 10)); }); }
  // verdict + actions
  let v = "";
  if (s.done) {
    v = s.bust ? '<span class="lose">' + window.t("mines.boom", "💥 BOOM — the mine got you. Stake goes to the bank.") + "</span>"
      : s.gw === 2 ? window.t("mines.reaped", "Seat released after inactivity — {amt} NADO returned.", { amt: rawToNado(s.gv) })
      : '<span class="win">' + window.t("mines.cashed", "💰 Cashed out {amt} NADO (×{m}).", { amt: rawToNado(s.gv), m: (Number(BigInt(s.gv) * 100n / BigInt(s.stake)) / 100).toFixed(2) }) + "</span>";
  } else if (s.ready) {
    v = s.result.bust ? '<span class="lose">' + window.t("mines.boomPending", "💥 A mine — confirming the bust on-chain…") + "</span>"
      : '<span class="win">' + window.t("mines.safePending", "💎 All safe! Banking ×{m} on-chain…", { m: (Number(valueAfter(BigInt(s.gv), s.gp, s.N, s.gc) * 100n / BigInt(s.stake)) / 100).toFixed(2) }) + "</span>";
  } else if (s.waiting) v = window.t("mines.waiting", "⏳ The chain is drawing your tiles ({n} pending)…", { n: s.gc });
  else if (sel.length) v = window.t("mines.selN", "{n} tiles selected — Reveal to lock them to the next blocks.", { n: sel.length });
  else v = window.t("mines.tapTiles", "Tap tiles to reveal ({left} safe left) — next tile pays ×{m} — or cash out.", { left: (T - s.N - s.gp), m: nextMult.toFixed(3) });
  $("verdict").innerHTML = v;
  const acts = $("roundActions"); acts.innerHTML = "";
  const mkBtn = (txt, fn, primary, pulse) => { const b = document.createElement("button"); b.className = (primary ? "primary" : "ghost") + (pulse ? " pulse" : ""); b.style.flex = "1 1 auto"; b.textContent = txt; b.onclick = fn; acts.appendChild(b); return b; };
  if (s.alive && s.addr === dapp.me) {
    if (!s.gh && sel.length && !dapp.busy("pick")) mkBtn(window.t("mines.revealN", "Reveal {n} {tiles}", { n: sel.length, tiles: sel.length === 1 ? window.t("mines.tile", "tile") : window.t("mines.tiles", "tiles") }), reveal, true, true);
    if (!s.gh && s.gp > 0 && !dapp.busy("cashout")) mkBtn(window.t("mines.cashOutBtn", "💰 Cash out {amt} NADO — your {st} stake + {p} won", { amt: rawToNado(s.gv), st: rawToNado(s.stake), p: rawToNado(BigInt(s.gv) - BigInt(s.stake)) }), cashout, s.gp > 0 && !sel.length);
    if (!s.gh && s.gp === 0 && !sel.length && !dapp.busy("cashout")) mkBtn(window.t("mines.abandon", "Take my stake back"), cashout, false);
    if (s.ready && !dapp.busy("resolve")) mkBtn(window.t("mines.resolveNow", "Resolve now"), () => resolveSeat(s.g), false);
  }
  if (s.done && s.addr === dapp.me) {
    // one tap re-bets the SAME stake & mine count; "Change bet" goes back to the builder instead
    if (!dapp.busy("bet")) mkBtn(window.t("mines.playAgain", "↻ Play again — {amt} NADO · {m} mines", { amt: rawToNado(s.stake), m: s.N }), () => placeBet(BigInt(s.stake), s.N), true, true);
    mkBtn(window.t("mines.changeBet", "Change bet"), () => { mySeat = 0; sel = []; render(); }, false);
  }
  renderSeats();
}
function tapTile(i) {
  const s = mySeatObj();
  if (!s || !s.alive || s.gh || s.addr !== dapp.me) return;
  const states = tileStates(s);
  if (states[i] && states[i] !== "sel") return;
  const at = sel.indexOf(i);
  if (at >= 0) sel.splice(at, 1);
  else {
    // cap the batch: never past the safe tiles, never past what the bank can cover
    const maxSafe = T - s.N - s.gp;
    if (sel.length >= maxSafe) return alertBar(window.t("mines.allSafeSel", "Only {n} safe tiles remain.", { n: maxSafe }));
    const tb = lastTable();
    const need = valueAfter(BigInt(s.gv), s.gp, s.N, sel.length + 1) - BigInt(s.gv);
    if (tb && tb.exists && need > tb.free)
      return alertBar(window.t("mines.coverCap", "The bank can't cover that many at once — reveal fewer tiles, cash out, or ask the bank to top up."));
    sel.push(i);
  }
  render();
}
function renderSeats() {
  const el = $("seats"); if (!el || !lastSto || bg.active == null) return;
  const tb = lastTable(); const iAmBank = tb && tb.exists && tb.bank === dapp.me;
  const seats = seatsOfTable(lastSto, bg.active).slice(0, 30);
  el.innerHTML = seats.length ? seats.map((s) => {
    const you = s.addr === dapp.me ? '<b style="color:var(--accent2)">' + window.t("mines.you", "you") + "</b> " : "";
    let out = window.t("mines.seatInfo", "{m} mines · {p} revealed", { m: s.N, p: s.gp });
    if (s.done) out += " → " + (s.bust ? '<span class="b dimb">' + window.t("mines.seatBust", "💥 bust") + "</span>"
      : '<span class="b ok">' + window.t("mines.seatCashed", "cashed {amt}", { amt: rawToNado(s.gv) }) + "</span>");
    else if (s.waiting || s.ready) out += ' <span class="b pend">' + window.t("mines.seatRevealing", "revealing…") + "</span>";
    else out += ' <span class="b pend">' + window.t("mines.seatLive", "live · worth {amt}", { amt: rawToNado(s.gv) }) + "</span>";
    const reapB = s.stale && (iAmBank || s.addr === dapp.me) ? ' <button class="ghost" style="padding:2px 8px;font-size:11px" data-reap="' + s.g + '">' + window.t("mines.releaseSeat", "release") + "</button>" : "";
    return '<div class="seat">' + you + disp(s.addr) + ' · <span class="mono">' + rawToNado(s.stake) + "</span> " + out + reapB + "</div>";
  }).join("") : '<span class="dim">' + window.t("mines.noRounds", "No rounds yet — start the first one.") + "</span>";
  el.querySelectorAll("[data-reap]").forEach((b) => b.onclick = () => reapSeat(parseInt(b.dataset.reap, 10)));
}

// ---- boot --------------------------------------------------------------------------------------------
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.table != null) bg.active = pend.table;
  if (pend && pend.seat != null && pend.phase !== "resolve") mySeat = pend.seat;
  if (ok && pend && ["open", "bet", "pick", "resolve", "cashout", "fund", "close"].includes(pend.phase)) watch = Object.assign({}, pend, { ts: Date.now() });
  dapp.showReturn(pend, ok, err, {
    bet: window.t("mines.pendBet", "Round starting — confirming…"), pick: window.t("mines.pendPick", "Reveal locking to the next blocks…"),
    resolve: window.t("mines.pendResolve", "Resolving…"), cashout: window.t("mines.pendCash", "💰 Cashing out — confirming…") });
});
function wireUI() {
  wireWallet(dapp);
  stickyInputs(dapp, ["stakeAmt", "bankrollAmt", "fundAmt", "bankAmt"]);
  $("btnNewTable").onclick = newTable;
  $("btnStart").onclick = startRound;
  $("btnGoTable").onclick = () => { const id = parseInt($("joinId").value, 10); if (id) selectTable(id); else alertBar(window.t("mines.enterFieldId", "Enter a field ID, or pick one from the lobby.")); };
  $("btnClose").onclick = closeTable;
  $("btnFund").onclick = fundTable;
  $("minesN").oninput = render;
  dapp.wireStakeSlider(maxStakeRaw, render);
  dapp.wirePctSlider("bankroll", { slider: "bankrollSlider", input: "bankrollAmt" }, () => dapp.exec, render);
  dapp.wirePctSlider("fund", { slider: "fundSlider", input: "fundAmt" }, () => dapp.exec, render);
  dapp.wireAutoCollect();
}
async function boot() {
  try { await dapp.init(); } catch (e) { alertBar(window.t("mines.cryptoFail", "Crypto bundle failed to load — reload.")); return; }
  wireUI(); loadQR();
  orderCards(["activeGame", "lobby", "play", "practice", "bankcard", "walletcard", "bankroll", "scoreboard"]);

// ONE mode picker, from the SDK — the same control in every game. Practice used to be a card parked
// below the staked game with no way to switch to it; now it is a mode you choose, and ?mode=practice
// links straight to it.
const modes = installModes(dapp, {
  modes: playModes({ icon: "💣", play: ["lobby", "play", "bankcard", "scoreboard"] }),
});
// mode gating layers OVER the game's own render, which gates cards by sign-in/table state
render = modes.wrap(render);   // re-apply the mode gating after every render
  const q = new URLSearchParams(location.search).get("table");
  if (q) { $("joinId").value = q; if (bg.active == null) bg.active = parseInt(q, 10); }
  render(); refreshAll();
  setInterval(refreshAll, 3000);
}
boot();

// ---- PRACTICE MODE (free, fully in-browser — play chips, local RNG, nothing on-chain) -------------------
// EXACT contract payout chain (valueAfter: ×(tilesLeft·99)/((tilesLeft−N)·100) per safe tile, integer floor
// every step, T=25 tiles); Math.random places the mines because nothing is at stake.
const prac = new Practice("mines");
const P_UNIT = 1000000n;   // chips play in fixed-point so the integer chain floors exactly like raw units
let pRun = null;           // {N, bet, mines:Set, open:[], dead, boomAt}
const pracVal = () => pRun ? valueAfter(BigInt(pRun.bet) * P_UNIT, 0, pRun.N, pRun.open.length) : 0n;
const pracMult = (v) => (Number(v * 1000n / (BigInt(pRun.bet) * P_UNIT)) / 1000).toFixed(3);
function pracStart() {
  const N = Math.min(NMAX, Math.max(NMIN, parseInt($("pMinesN").value, 10) || 3));
  const bet = parseInt($("pStake").value, 10) || 0;
  if (!prac.canBet(bet, notify)) return;
  prac.addChips(-bet);
  const pm = new Set();
  while (pm.size < N) pm.add(Math.floor(Math.random() * T));
  pRun = { N, bet, mines: pm, open: [], dead: false, boomAt: null };
  pracRender();
}
function pracCash() {
  if (!pRun || pRun.dead || !pRun.open.length) return;
  const v = pracVal(), won = Number(v / P_UNIT);
  prac.addChips(won);
  pRun.dead = true;
  pracRender();
  $("pResult").innerHTML = '<span class="win">' + window.t("sdk.prMinesCash", "💰 Cashed out {n} play chips (×{m}).", { n: won, m: pracMult(v) }) + "</span>";
}
function pracTap(i) {
  if (!pRun || pRun.dead || pRun.open.includes(i)) return;
  if (pRun.mines.has(i)) {
    pRun.dead = true; pRun.boomAt = i;
    pracRender();
    $("pResult").innerHTML = '<span class="lose">' + window.t("sdk.prMinesBoom", "💥 BOOM — a mine. Lost {n} play chips.", { n: pRun.bet }) + "</span>";
    return;
  }
  pRun.open.push(i);
  if (pRun.open.length === T - pRun.N) return pracCash();   // cleared every safe tile — bank it
  pracRender();
}
function pracRender() {
  prac.strip($("pStrip"), { chips: true, onReset: pracRender });
  const N = Math.min(NMAX, Math.max(NMIN, parseInt($("pMinesN").value, 10) || 3));
  $("pMinesVal").textContent = N;
  $("pNextMult").textContent = "×" + multAfter(N, 1).toFixed(3);
  $("pRun5Mult").textContent = "×" + multAfter(N, Math.min(5, T - N)).toFixed(2);
  $("pMeter").classList.toggle("hidden", !pRun);
  $("pGrid").classList.toggle("hidden", !pRun);
  $("pActions").innerHTML = "";
  if (!pRun) { $("pResult").innerHTML = ""; return; }
  const live = !pRun.dead, v = pracVal();
  $("pmMines").textContent = pRun.N;
  $("pmRevealed").textContent = pRun.open.length + " / " + (T - pRun.N);
  $("pmMult").textContent = "×" + pracMult(v);
  $("pmValue").textContent = Number(v / P_UNIT) + " 🪙";
  $("pGrid").innerHTML = Array.from({ length: T }, (_, i) => {
    const st = pRun.boomAt === i ? "boom" : pRun.open.includes(i) ? "gem" : (pRun.dead && pRun.mines.has(i)) ? "boom" : "";
    return '<div class="tile ' + st + (live && !st ? " live" : "") + '" data-pi="' + i + '">' + (st === "gem" ? "💎" : st === "boom" ? "💥" : "") + "</div>";
  }).join("");
  if (live && pRun.open.length) {
    const b = document.createElement("button"); b.className = "primary"; b.style.flex = "1 1 auto";
    b.textContent = window.t("sdk.prCashOut", "💰 Cash out {n} chips (×{m})", { n: Number(v / P_UNIT), m: pracMult(v) });
    b.onclick = pracCash; $("pActions").appendChild(b);
  }
  if (live) $("pResult").innerHTML = window.t("mines.tapTiles", "Tap tiles to reveal ({left} safe left) — next tile pays ×{m} — or cash out.",
    { left: T - pRun.N - pRun.open.length, m: (Number(valueAfter(10n ** 12n, pRun.open.length, pRun.N, 1)) / 1e12).toFixed(3) });
}
if ($("pStrip")) {
  $("pStart").onclick = pracStart;
  $("pMinesN").oninput = pracRender;
  $("pGrid").addEventListener("click", (e) => { const el = e.target.closest("[data-pi]"); if (el) pracTap(parseInt(el.dataset.pi, 10)); });
  pracRender();
}
