// slots.js — NADO Slots: classic 3-reel slots where PLAYERS OWN THE MACHINES, built on the shared game
// SDK (nadodapp.js). Pure beacon randomness — a spin binds to two blocks that don't exist yet when you
// sign (no house secret, no reveal, no cadence): the reels stop ~2 blocks after the spin lands.
//     stop_i = HASH( BLOCKHASH(sh) + BLOCKHASH(sh+1) + spinId  +  i ) % 64        i = 0,1,2
// Symbols come off weighted 64-stop virtual reels; the paytable pays up to 150x (exact RTP 95.796%,
// full-enumeration-proven — see tests/test_slots_contract.py). The machine's bank commits a 150x cover
// for every open spin, so it can never welsh. Settle is permissionless; a pruned spin refunds via claim.
import { NadoDapp, rawToNado, nadoToRaw, randId, blake2bHash, _m, $, base, gate, canPay, orderCards, alertBar,
         lsLoad as load, lsSave as save, lsPrune, wireWallet, stickyInputs, renderWallet, renderScore, scoreBump, scoreSort,
         recentChips, statusLabel, loadQR, drawQR, resolveAliases, disp, share, shareInvite } from "./nadodapp.js";

const CID = "1f5ea94c30db542b0754ea1dfb43ed36";
const GICON = "🎰";
const dapp = new NadoDapp({ cid: CID, app: "Slots" });
const SPIN_D = 2, MAXM2 = 300, COVER = (MAXM2 - 2) / 2;   // cover per spin = stake * 149
const SYM = ["🍒", "🍋", "🍊", "🍇", "🔔", "💎", "7️⃣"];
const LS_T = "nado_slots_machines", LS_S = "nado_slots_spins";

let lastSto = null, activeTable = null, lastTable = null, mySpins = [];
let knownTables = new Set(), knownSeats = new Set(), watch = null, reelAnim = null;

// ---- derivation (mirror of the contract — display only; settle recomputes it on-chain) --------------
const H = (v) => BigInt("0x" + blake2bHash(v));
const symOf = (r) => (r >= 16) + (r >= 30) + (r >= 42) + (r >= 52) + (r >= 58) + (r >= 62);
const TRIP2 = [16, 20, 24, 30, 60, 100, 300];
function m2Of(s0, s1, s2) {
  if (s0 === s1 && s1 === s2) return TRIP2[s0];
  const c7 = (s0 === 6) + (s1 === 6) + (s2 === 6);
  if (c7 === 2) return 10;
  if (c7 === 1) return 3;
  return (s0 === 0) + (s1 === 0) + (s2 === 0) === 2 ? 6 : 0;
}
function spinResult(bh0, bh1, g) {
  if (!bh0 || !bh1) return null;
  const q = BigInt("0x" + bh0) + BigInt("0x" + bh1) + BigInt(g);
  const stops = [0, 1, 2].map((i) => Number(H(q + BigInt(i)) % 64n));
  const syms = stops.map(symOf);
  return { stops, syms, m2: m2Of(...syms) };
}
const stopsFromGr = (gr) => { const v = gr - 1; return [v % 64, Math.floor(v / 64) % 64, Math.floor(v / 4096) % 64]; };

// ---- reads -----------------------------------------------------------------------------------------
function machineFrom(sto, t) {
  t = String(t); const bank = _m(sto, "ta")[t];
  if (!bank) return { exists: false };
  return { exists: true, id: Number(t), bank, tk: _m(sto, "tk")[t] || 0, tp: _m(sto, "tp")[t] || 0,
    tc: _m(sto, "tc")[t] || 0, tn: _m(sto, "tn")[t] || 0, tx: _m(sto, "tx")[t] || 0, closed: !!_m(sto, "tz")[t] };
}
const maxBet = (mc) => Math.max(0, Math.floor((mc.tk - mc.tc) / COVER));   // biggest bet the bank can 150×-cover (raw)
const maxBetRaw = () => { const mc = lastTable; return (mc && mc.exists && !mc.closed) ? BigInt(maxBet(mc)) : null; };
const syncStakeSlider = () => dapp.syncStakeSlider(maxBetRaw(), { label: "bet " });   // shared SDK slider
function spinsOf(sto, t) {
  t = String(t); const gg = _m(sto, "gg"), cur = dapp.cursor, out = [];
  for (const g of Object.keys(gg)) if (String(gg[g]) === t) {
    const s = { g: Number(g), addr: _m(sto, "ga")[g], stake: _m(sto, "gs")[g] || 0,
      gh: _m(sto, "gh")[g] || 0, settled: !!_m(sto, "gd")[g] };
    if (s.settled) { const gr = _m(sto, "gr")[g] || 0; if (gr) { s.stops = stopsFromGr(gr); s.syms = s.stops.map(symOf); } s.m2 = _m(sto, "gw")[g] || 0; }
    else if (cur != null && cur >= s.gh + 1) { const r = spinResult(dapp.bh(s.gh), dapp.bh(s.gh + 1), s.g); if (r) { Object.assign(s, r); s.ready = true; } else s.pending = true; }
    else s.pending = true;
    out.push(s);
  }
  return out.sort((a, b) => (b.gh - a.gh) || (b.g - a.g));   // newest FIRST by bound block height (seat ids are random, not time-ordered)
}

// ---- actions ---------------------------------------------------------------------------------------
function openMachine() {
  const raw = nadoToRaw($("bankrollAmt").value);
  if (!raw) return alertBar("Enter the bank in NADO — the machine can accept bets up to bank ÷ 149 (it must always cover a 150× jackpot).");
  if (!canPay(dapp, raw, "Banking a machine")) return;
  const t = randId();
  const T = load(LS_T); T[t] = { ts: Date.now() }; save(LS_T, T);
  activeTable = t;
  dapp.call("open", [t], raw, "open slot machine #" + t + " · bank " + rawToNado(raw) + " NADO", { table: t, phase: "open" });
}
async function doSpin() {
  const mc = lastTable; if (!mc || !mc.exists) return;
  const raw = nadoToRaw($("stakeAmt").value);
  if (!raw) return alertBar("Enter your bet in NADO.");
  const mb = maxBet(mc);
  if (raw > BigInt(mb)) return alertBar("This machine's bank can only cover bets up to " + rawToNado(mb) + " NADO right now (every spin reserves a 150× jackpot cover).");
  if (!canPay(dapp, raw, "This spin")) return;
  const g = randId();
  const S = load(LS_S); S[g] = { table: activeTable, ts: Date.now() }; save(LS_S, S);
  dapp.call("spin", [g, activeTable], raw, "🎰 spin machine #" + activeTable + " · " + rawToNado(raw) + " NADO", { table: activeTable, seat: g, phase: "spin" });
}
const settleSpin = (g, m2, stake) => dapp.call("settle", [g], null,
  (m2 > 0 ? "💰 collect " + rawToNado(BigInt(stake) * BigInt(m2) / 2n) + " NADO" : "finish spin #" + g), { table: activeTable, seat: g, phase: "settle" });
const claimSpin = (g) => dapp.call("claim", [g], null, "refund pruned spin #" + g, { table: activeTable, seat: g, phase: "settle" });
function fundMachine() {
  const raw = nadoToRaw($("fundAmt").value);
  if (!raw) return alertBar("Enter how much NADO to add to the bank.");
  if (!canPay(dapp, raw, "Topping up the bank")) return;
  dapp.call("fund", [activeTable], raw, "top up machine #" + activeTable + " · " + rawToNado(raw) + " NADO", { table: activeTable, phase: "fund" });
}
// AUTO-SETTLE via the shared SDK tick (opt-out slider, one-per-refresh, autoTried dedup). As the bank:
// settle ANY ready spin on my machine (pays winners, frees my cover). Otherwise: settle my OWN ready spins.
function maybeAutoSettle() {
  if (!lastTable || !lastTable.exists) return;
  const iAmBank = lastTable.bank === dapp.me;
  dapp.autoCollect(mySpins.filter((s) => !s.settled && s.ready && (iAmBank || s.addr === dapp.me)),
    (s) => settleSpin(s.g, s.m2, s.stake), { blocked: watch });
}
function readyWins() { return mySpins.filter((s) => s.addr === dapp.me && !s.settled && s.ready && s.m2 > 0); }
function collectWins() {
  const w = readyWins();
  if (!w.length) return;
  settleSpin(w[0].g, w[0].m2, w[0].stake);   // one tx per settle; the button re-offers the next on return
}
const closeMachine = () => dapp.call("close", [activeTable], null, "close machine #" + activeTable + " — cash the bank out", { table: activeTable, phase: "close" }, { confirm: 1 });

// ---- refresh ---------------------------------------------------------------------------------------
async function refreshAll() {
  await dapp.refresh();
  const sto = await dapp.storage();
  if (sto) {
    lastSto = sto;
    knownTables = lsPrune(LS_T, Object.keys(_m(sto, "ta")));
    knownSeats = lsPrune(LS_S, Object.keys(_m(sto, "gg")));
    if (activeTable != null) {
      lastTable = machineFrom(sto, activeTable);
      // FAST provisional hashes: slot results are PUBLIC + re-validated on-chain at settle
      const cur = dapp.cursor, need = [];
      for (const g of Object.keys(_m(sto, "gg"))) {
        if (String(_m(sto, "gg")[g]) !== String(activeTable) || _m(sto, "gd")[g]) continue;
        const gh = _m(sto, "gh")[g] || 0;
        if (cur != null && cur >= gh + 1) need.push(gh, gh + 1);
      }
      if (need.length) await dapp.blockHashes(need.slice(0, 30), { fast: true });
      mySpins = spinsOf(sto, activeTable);
    }
    if (watch) {
      const done =
        watch.phase === "open" ? !!_m(sto, "ta")[String(watch.table)] :
        watch.phase === "spin" ? !!_m(sto, "gg")[String(watch.seat)] :
        watch.phase === "settle" ? !!_m(sto, "gd")[String(watch.seat)] :
        watch.phase === "close" ? !!_m(sto, "tz")[String(watch.table)] :
        watch.phase === "fund" ? true : false;
      if (done) {
        $("status").textContent = { open: "✓ Machine is live — share it and earn the edge.", spin: "✓ Spin locked to the next blocks…",
          settle: "✓ Settled on-chain.", close: "✓ Machine closed — bank cashed out.", fund: "✓ Bank topped up." }[watch.phase] || "✓ Confirmed.";
        dapp.clearInflight();   // re-enable the SPIN button the instant the spin lands (was stuck disabled ~3 min)
        watch = null;
      }
    }
    // safety net: never leave the SPIN button disabled once the spin is visibly on-chain, even if `watch`
    // was lost to a reload — clear a "spin" inflight whose seat now exists.
    if (dapp.inflight && dapp.inflight.phase === "spin" && _m(sto, "gg")[String(dapp.inflight.seat)]) dapp.clearInflight();
    maybeAutoSettle();
    renderLobby(sto);
    renderScore($("scoreList"), boardFrom(sto), dapp.me, "No settled spins yet — pull the first lever.");
    await resolveAliases([dapp.me, lastTable && lastTable.bank].concat(mySpins.map((s) => s.addr)).filter(Boolean));
  }
  render();
}
function boardFrom(sto) {
  const stats = {};
  const gd = _m(sto, "gd");
  for (const g of Object.keys(gd)) {
    if (!gd[g]) continue;
    const stake = _m(sto, "gs")[g] || 0, m2 = _m(sto, "gw")[g] || 0;
    scoreBump(stats, _m(sto, "ga")[g], Math.floor(stake * m2 / 2) - stake);
  }
  return scoreSort(stats);
}
function renderLobby(sto) {
  const el = $("lobbyList");
  const ms = Object.keys(_m(sto, "ta")).map((t) => machineFrom(sto, t)).filter((m) => m.exists && !m.closed);
  ms.sort((a, b) => b.tk - a.tk);
  el.innerHTML = ms.length ? ms.slice(0, 24).map((m) =>
    '<button class="chip betting" data-t="' + m.id + '">🎰 #' + m.id + " · bank " + rawToNado(m.tk) + " · max bet " + rawToNado(maxBet(m)) + "</button>").join(" ")
    : '<span class="dim">No machines on the floor yet — open the first one below and earn the edge.</span>';
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => { activeTable = parseInt(b.dataset.t, 10); refreshAll(); });
}

// ---- render ----------------------------------------------------------------------------------------
function setReels(syms, spinning, winning) {
  for (let i = 0; i < 3; i++) {
    const el = $("reel" + i);
    el.classList.toggle("spin", !!spinning);
    el.classList.toggle("hit", !!winning);
    el.innerHTML = "<span>" + (syms && syms[i] != null ? SYM[syms[i]] : "❔") + "</span>";
  }
}
function render() {
  dapp.reflectUrl("table", activeTable);   // address bar = the shareable link to the selected machine
  const signedIn = renderWallet(dapp);
  gate({ opencard: signedIn, bankroll: signedIn, activeGame: activeTable != null });
  // my machines / spins chips
  const T = load(LS_T), Ssto = load(LS_S), mine = [];
  for (const t of Object.keys(T)) mine.push({ id: +t, role: "bank", ts: T[t].ts });
  for (const g of Object.keys(Ssto)) mine.push({ id: Ssto[g].table, seat: g, role: "spin", ts: Ssto[g].ts });
  mine.sort((a, b) => b.ts - a.ts);
  const seen = new Set();
  const shown = mine.filter((x) => { x.live = x.role === "bank" ? knownTables.has(String(x.id)) : knownSeats.has(String(x.seat));
    x.icon = GICON; const k = String(x.id); if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 8);
  recentChips($("recent"), shown, (id) => { activeTable = id; refreshAll(); }, "");
  if (activeTable == null) return;
  const mc = lastTable || {};
  $("gameId").textContent = "#" + activeTable;
  shareInvite("table", activeTable, "Spin my slot machine #" + activeTable + " on NADO — up to 150×:", 180);
  if (!mc.exists) { $("spinVerdict").textContent = dapp.whereIs("machine", activeTable, (load(LS_T)[activeTable] || {}).ts); setReels(null, false, false); return; }
  const iAmBank = mc.bank === dapp.me;
  $("bankTag").textContent = "— banked by " + (iAmBank ? "YOU" : disp(mc.bank)) + (mc.closed ? " · CLOSED" : "");
  $("gBank").textContent = rawToNado(mc.tk) + " NADO" + (mc.tc ? " (" + rawToNado(mc.tc) + " reserved)" : "");
  $("gMax").textContent = rawToNado(maxBet(mc)) + " NADO";
  syncStakeSlider();
  gate({ fundRow: iAmBank && !mc.closed });
  // the newest of MY spins drives the reels — ordered by the LOCAL submit time (seat ids are random, so
  // sorting by id would let an old spin hijack the reels and freeze the animation on rapid re-spins)
  const Sloc = load(LS_S);
  const mineSpins = mySpins.filter((s) => s.addr === dapp.me)
    .sort((a, b) => ((Sloc[String(b.g)] || {}).ts || 0) - ((Sloc[String(a.g)] || {}).ts || 0) || b.g - a.g);
  const cur = mineSpins[0];
  // SPINNING = the lever was just pulled (busy, seat not on-chain yet) OR the newest spin is still resolving.
  // The SPIN button is locked for the WHOLE window — you can't fire a second spin over a spinning reel.
  const spinning = dapp.busy("spin") || (cur && cur.pending);
  $("btnSpin").disabled = mc.closed || !dapp.me || spinning;
  $("btnSpin").textContent = spinning ? "🎲 Spinning…" : mc.closed ? "machine closed" : "🎰 SPIN";
  if (spinning) { setReels(null, true, false); $("spinVerdict").textContent = "🎲 The chain is spinning the reels…"; }
  else if (!cur) { setReels(null, false, false); $("spinVerdict").textContent = mc.closed ? "This machine is closed." : "Place a bet and pull the lever."; }
  else if (cur.syms) {
    const win = cur.m2 > 0, payout = BigInt(cur.stake) * BigInt(cur.m2) / 2n;
    setReels(cur.syms, false, win);
    $("spinVerdict").innerHTML = win
      ? '<span class="win">' + cur.syms.map((s) => SYM[s]).join(" ") + " — WIN " + rawToNado(payout) + " NADO (" + (cur.m2 / 2) + "×)!</span>"
      : cur.syms.map((s) => SYM[s]).join(" ") + " — no luck, spin again";
  }
  // one-tap collect: sum the player's ready winnings
  const wins = mySpins.filter((s) => s.addr === dapp.me && !s.settled && s.ready && s.m2 > 0);
  const winTotal = wins.reduce((a, s) => a + BigInt(s.stake) * BigInt(s.m2) / 2n, 0n);
  $("btnCollect").classList.toggle("hidden", wins.length === 0);
  if (wins.length) $("btnCollect").textContent = "💰 Collect " + (wins.length > 1 ? wins.length + " wins · " : "") + rawToNado(winTotal) + " NADO";
  // spin history with collect buttons
  $("mySpins").innerHTML = mySpins.slice(0, 8).map((s) => {
    const who = s.addr === dapp.me ? "<b>you</b>" : disp(s.addr);
    const res = s.syms ? s.syms.map((x) => SYM[x]).join("") : "⏳";
    const pay = s.m2 ? rawToNado(BigInt(s.stake) * BigInt(s.m2) / 2n) + " NADO" : "";
    const act = !s.settled && s.ready
      ? (s.m2 > 0 ? '<button class="pulse" style="padding:4px 10px;font-size:12px" data-collect="' + s.g + '" data-m2="' + s.m2 + '" data-stake="' + s.stake + '">💰 Collect ' + pay + "</button>"
                  : '<button class="ghost" style="padding:4px 10px;font-size:12px" data-collect="' + s.g + '" data-m2="0" data-stake="' + s.stake + '">settle</button>')
      : s.settled ? (s.m2 > 0 ? '<span style="color:var(--gold)">paid ' + pay + "</span>" : '<span class="dim">—</span>') : "";
    return '<div class="btl">' + who + " bet " + rawToNado(s.stake) + " → " + res + " " + act + "</div>";
  }).join("");
  $("mySpins").querySelectorAll("[data-collect]").forEach((b) => b.onclick = () =>
    settleSpin(parseInt(b.dataset.collect, 10), parseInt(b.dataset.m2, 10), b.dataset.stake));
}

// ---- boot ------------------------------------------------------------------------------------------
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.table != null) activeTable = pend.table;
  if (ok && pend && ["open", "spin", "settle", "close", "fund"].includes(pend.phase)) watch = pend;
  $("status").textContent = statusLabel(pend, ok, err, {
    open: "Machine opening — confirming…", spin: "🎰 Spin submitted — the reels lock to the next blocks…",
    settle: "Settling on-chain…", fund: "Topping up the bank…", close: "Closing the machine…" });
});
function wireUI() {
  wireWallet(dapp);
  stickyInputs(dapp, ['stakeAmt', 'bankrollAmt', 'fundAmt', 'bankAmt']);   // typed amounts persist across turns
  $("btnNewMachine").onclick = openMachine;
  $("btnSpin").onclick = doSpin;
  $("btnFund").onclick = fundMachine;
  $("btnCollect").onclick = collectWins;
  dapp.wireStakeSlider(maxBetRaw, () => syncStakeSlider());   // owns stakeAmt input + the % slider + Max
  dapp.wireAutoCollect();
  $("btnClose").onclick = closeMachine;
}
async function boot() {
  try { await dapp.init(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload."; return; }
  wireUI(); loadQR();
  orderCards(["activeGame", "lobby", "opencard", "paytableCard", "walletcard", "bankroll", "scoreboard"]);
  const q = new URLSearchParams(location.search).get("table");
  if (q) activeTable = parseInt(q, 10);
  render(); refreshAll();
  setInterval(refreshAll, 3000);
}
boot();
