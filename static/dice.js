// dice.js — NADO Dice: a provably-fair, peer-banked MULTIPLAYER "roll under" dice on the execution layer, built
// on the shared game SDK (nadodapp.js). Slide your win chance, the payout auto-scales (99 ÷ target → a flat 1%
// edge). A table SPINS ITSELF every ROUND blocks — no bank reveal, no secrets. Each seat gets its OWN roll from
// FINALIZED L1 block hashes nobody can predict while betting is open:
//     roll_g = HASH( BLOCKHASH(sh) + BLOCKHASH(sh+1) + seatId ) % 100
// Once the settle block is final, anyone can settle a seat (it pays the bettor); losing stakes fold into the
// bankroll so the table keeps rolling. Ordinary upgradable stackvm contract, no game-specific API.
import { NadoDapp, rawToNado, nadoToRaw, randId, _m, $, base, gate, canPay, orderCards, chainResultAlg, blocksToTime, wireWallet, stickyInputs, renderWallet, renderScore, scoreBump, scoreSort, alertBar, notify, loadQR, resolveAliases, disp, share, shareInvite } from "./nadodapp.js";
import { BankedGame } from "./bankedgame.js";   // the ONE banked-table reader/lobby (shared by every house game)
import { Practice } from "./practice.js";      // free in-browser practice (play chips, no chain)

const CID = "b37251eb6b8bbeedd3a69cad7d6611a1";
const GICON = '<svg style="vertical-align:-3px" viewBox="0 0 48 48" width="16" height="16" aria-hidden="true">     <rect x="9" y="9" width="30" height="30" rx="7" fill="#e6edf3" stroke="#243140" stroke-width="2"/>     <circle cx="17" cy="17" r="2.8" fill="#20272f"/><circle cx="31" cy="17" r="2.8" fill="#20272f"/>     <circle cx="24" cy="24" r="2.8" fill="#00ad93"/>     <circle cx="17" cy="31" r="2.8" fill="#20272f"/><circle cx="31" cy="31" r="2.8" fill="#20272f"/></svg>';
const PN = 100, MMIN = 2, MMAX = 98, EDGE = 99, BLOCK_SECS = 6, ROUND = 20;
const dapp = new NadoDapp({ cid: CID, app: "Dice" });
const bg = new BankedGame(dapp, { icon: "🎲" });   // shared table reader/actions/lobby/tracking (bg.active = selected table)

let lastSto = null;
let lastTable = null, lastSeats = [], target = 50;
let seatsN = 40;   // cap how many of a table's (unbounded) seats we render at once; "Show more" grows it

const multOf = (M) => EDGE / M;
const returnRaw = (stake, M) => BigInt(stake) * BigInt(EDGE) / BigInt(M);

// ---- reads (dice-specific storage schema) --------------------------------------------------------
const tableFrom = (sto, t) => bg.read(sto, t);
// bg.seats walks the seats + sorts newest-first by bound block height; we add the dice fields (target, roll, win)
const seatsOfTable = (sto, t) => bg.seats(sto, t, (g, s) => {
  s.M = _m(sto, "gm")[g] || 0;
  if (s.settled) { const gr = _m(sto, "gr")[g] || 0; s.roll = gr ? gr - 1 : null; s.win = !!_m(sto, "gw")[g]; }
  else if (s.ready) { s.roll = chainResultAlg(dapp.bh(s.gh), dapp.bh(s.gh + 1), g, PN); s.win = s.roll != null ? s.roll < s.M : null; }
  else { s.pending = true; s.spinsIn = dapp.cursor != null ? s.gh - dapp.cursor : null; }
  return s;
});
async function fetchTable(t) { const sto = await dapp.storage({ append: ["gg", "ga", "gs", "gm", "gh", "gr", "gw", "gd"] }); return sto ? tableFrom(sto, t) : null; }

// ---- actions -------------------------------------------------------------------------------------
function openTable(t, bankrollRaw) {
  // bg.reopen (bg.open with OUR id, same bytecode) — we mint t first so the signing label's #{t} is the real table id
  bg.reopen(t, bankrollRaw, window.t("dice.callOpen", "bank a dice table #{t} · {amt} NADO", { t, amt: rawToNado(bankrollRaw) }));
  $("joinId").value = String(t);
  render();
}
function reopenTable() {
  const T = bg.tableRec(bg.active); if (!T || !T.bankroll) return;
  const raw = BigInt(T.bankroll);
  if (!canPay(dapp, raw, "Re-opening this table")) return;
  openTable(bg.active, raw);
}
async function newTable() {
  const raw = nadoToRaw($("bankrollAmt").value);
  if (!raw) return alertBar(window.t("dice.enterBankroll", "Enter a bankroll (NADO)."));
  await dapp.refresh();
  if (!canPay(dapp, raw, "Banking this table")) return;
  openTable(randId(), raw);
}
async function doBet() {
  const t = bg.active;
  if (!t) return alertBar(window.t("dice.pickFirst", "Pick a table first."));
  const stake = nadoToRaw($("stakeAmt").value);
  if (!stake) return alertBar(window.t("dice.enterStake", "Enter a stake (NADO)."));
  const tb = await fetchTable(t);
  if (!tb || !tb.exists) return alertBar(dapp.whereIs("table", t));
  if (tb.closed) return alertBar(window.t("dice.tableClosed", "That table is closed."));
  await dapp.refresh();
  if (!canPay(dapp, stake, "This roll")) { render(); return; }
  const need = returnRaw(stake, target) - stake;
  if (BigInt(tb.pool) - BigInt(tb.committed) < need) { alertBar(window.t("dice.cantCover1", "This table can't cover a {m}× win right now. Lower your stake or raise your win chance.", { m: multOf(target).toFixed(2) })); render(); return; }
  const g = randId();
  bg.rememberSeat(g, { table: t, stake: stake.toString(), M: target });   // pin t — bg.active may move during the awaits above
  render();
  dapp.call("bet", [g, t, target], stake, window.t("dice.callBet", "roll under {target} for {amt} NADO · table #{t}", { target, amt: rawToNado(stake), t }), { table: t, seat: g, phase: "bet" });
}
function fundTable() {
  const raw = nadoToRaw($("fundAmt").value);
  if (!raw) return alertBar(window.t("dice.enterFund", "Enter an amount to add to this table's bankroll."));
  if (!canPay(dapp, raw, "The top-up")) return;
  bg.fund(raw, window.t("dice.callFund", "top up table #{t} bankroll · {amt} NADO", { t: bg.active, amt: rawToNado(raw) }));
}
const settleSeat = (g) => dapp.call("settle", [g], null, window.t("dice.callSettle", "collect seat #{g}", { g }), { table: bg.active, phase: "settle" });
// AUTO-COLLECT a resolved WINNING seat (shared SDK tick — opt-out slider, one-per-refresh, autoTried dedup)
function maybeAutoSettle() {
  if (!lastTable || !lastTable.exists) return;
  dapp.autoCollect(lastSeats.filter((s) => s.addr === dapp.me && !s.settled && s.ready && s.win), (s) => settleSeat(s.g));
}
const closeTable = () => bg.close(window.t("dice.callClose", "close table #{t}", { t: bg.active }));

async function refreshActive() {
  await dapp.refresh();
  dapp.settleInflight();   // SDK: retire the optimistic 'confirming…' status once the action lands
  const sto = await dapp.storage({ append: ["gg", "ga", "gs", "gm", "gh", "gr", "gw", "gd"] });
  if (sto) {
    lastSto = sto;
    bg.track(sto);
    if (bg.active != null) {
      lastTable = tableFrom(sto, bg.active);
      const cur = dapp.cursor, need = [];
      for (const g of Object.keys(_m(sto, "gg"))) if (String(_m(sto, "gg")[g]) === String(bg.active)) {
        const gh = _m(sto, "gh")[g] || 0; if (!_m(sto, "gd")[g] && cur != null && cur >= gh + 1) need.push(gh, gh + 1);
      }
      if (need.length) await dapp.blockHashes(need, { fast: true });   // dice rolls: PUBLIC + on-chain-validated -> provisional (fast) is safe; results show ~one block after the roll instead of waiting out finality
      lastSeats = seatsOfTable(sto, bg.active);
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
    const M = _m(sto, "gm")[g] || 1, stake = _m(sto, "gs")[g] || 0, win = !!_m(sto, "gw")[g];
    const net = win ? Number(returnRaw(stake, M)) - stake : -stake;
    const who = _m(sto, "ga")[g];
    scoreBump(stats, who, net); if (bank !== who) scoreBump(stats, bank, -net);   // self-play: the bank leg would cancel your own win to a bogus ±0
  }
  return scoreSort(stats);
}
const renderScoreboard = (board) => renderScore($("scoreList"), board, dapp.me, window.t("dice.noScores", "No settled rolls yet — be the first on the board."));
function renderLobby(sto) {
  bg.lobby($("lobbyList"), sto, (t) => {
    const left = t.roundEndsIn != null ? window.t("dice.nextRoll", " · next roll {time}", { time: blocksToTime(t.roundEndsIn) }) : "";
    const rolls = t.seatCount === 1 ? window.t("dice.roll", "roll") : window.t("dice.rolls", "rolls");
    return window.t("dice.lobbyChip", "🟢 #{id} · bank {bank} · {n} {rolls}{left}", { id: t.id, bank: rawToNado(t.pool), n: t.seatCount, rolls, left });
  }, selectTable, (a, b) => (b.seatCount - a.seatCount) || (b.id - a.id));   // busiest tables first
}
function selectTable(id) {
  bg.active = id; seatsN = 40; $("joinId").value = String(id);
  notify(window.t("dice.tableSelected", "Table #{id} — set your stake and win chance, then Place roll.", { id }));
  refreshActive();
  try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {}
}

// ---- render --------------------------------------------------------------------------------------
// MAX BET: the biggest stake we OFFER. Three caps, take the smallest:
//   1. contract cover — the bank's exposure (payout-stake) must fit its free bankroll:
//        stake*(EDGE-target)/target <= free   =>   stake <= free*target/(EDGE-target)
//   2. the free bankroll itself — never OFFER a stake bigger than the bank holds. At low multipliers cap #1
//      balloons (at 1.01x it is ~98*free, since the bank barely risks anything), which is solvent but absurd
//      to offer; capping at `free` keeps "you can't stake more than the bank has". Still <= cap #1, so the
//      chain never rejects it.
//   3. your own playable balance — never offer a stake you can't afford.
function maxBetRaw() {
  const tb = lastTable;
  if (!tb || !tb.exists || tb.closed) return null;
  const free = BigInt(tb.pool) - BigInt(tb.committed);
  if (free <= 0n || EDGE - target <= 0) return null;
  const cover = free * BigInt(target) / BigInt(EDGE - target);
  let cap = cover < free ? cover : free;                 // min(contract cover, bank size)
  const bal = dapp.exec || 0n;
  if (bal > 0n && bal < cap) cap = bal;                  // min(..., your balance)
  return cap;
}
const syncStakeSlider = () => dapp.syncStakeSlider(maxBetRaw());   // shared SDK slider
function syncSlider() {
  target = Math.min(MMAX, Math.max(MMIN, parseInt($("target").value, 10) || 50));
  $("winChanceTarget").textContent = target;
  $("winChance").textContent = target + "%";
  $("multiplier").textContent = multOf(target).toFixed(2) + "×";
  const stake = nadoToRaw($("stakeAmt").value);
  $("payoutPreview").textContent = stake ? window.t("dice.winPays", "win pays {amt} NADO", { amt: rawToNado(returnRaw(stake, target)) }) : "";
  syncStakeSlider();
}
function wireUI() {
  wireWallet(dapp);
  stickyInputs(dapp, ['stakeAmt', 'bankrollAmt', 'fundAmt', 'bankAmt']);   // typed amounts persist across turns
  $("btnNewTable").onclick = newTable;
  $("btnBet").onclick = doBet;
  $("btnGoTable").onclick = () => { const id = parseInt($("joinId").value, 10); if (id) selectTable(id); else alertBar(window.t("dice.enterTableId", "Enter a table ID, or pick one from the lobby.")); };
  $("btnClose").onclick = closeTable;
  if ($("btnMoreSeats")) $("btnMoreSeats").onclick = () => { seatsN += 60; renderActive(); };
  dapp.wireAutoCollect();
  $("btnReopen").onclick = reopenTable;
  $("btnFund").onclick = fundTable;
  $("btnShare").onclick = () => share(base() + "/?table=" + bg.active, window.t("dice.shareText", "Roll at my dice table #{t} on NADO:", { t: bg.active }), $("btnShare"));
  $("target").oninput = () => { syncSlider(); render(); };
  dapp.wireStakeSlider(maxBetRaw, () => { syncSlider(); render(); });   // owns stakeAmt input + the % slider + Max
  dapp.wirePctSlider("bankroll", { slider: "bankrollSlider", input: "bankrollAmt" }, () => dapp.exec, render);   // bank a table: % of your playable balance
  dapp.wirePctSlider("fund", { slider: "fundSlider", input: "fundAmt" }, () => dapp.exec, render);   // top up the bankroll: % of your playable balance
}
function render() {
  dapp.reflectUrl("table", bg.active);   // address bar = the shareable link to the selected table
  dapp.syncPctSlider("bankroll", { slider: "bankrollSlider", input: "bankrollAmt" }, dapp.exec);
  dapp.syncPctSlider("fund", { slider: "fundSlider", input: "fundAmt" }, dapp.exec);
  const signedIn = renderWallet(dapp);
  gate({ play: signedIn, bankcard: signedIn, bankroll: signedIn, activeGame: bg.active != null });
  const tb = (bg.active != null && lastTable && lastTable.exists && !lastTable.closed) ? lastTable : null;
  const stake = nadoToRaw($("stakeAmt").value);
  const need = stake ? returnRaw(stake, target) - stake : null;
  const covers = !(tb && need != null && (BigInt(tb.pool) - BigInt(tb.committed)) < need);
  const canAfford = !(signedIn && stake && dapp.exec < stake);
  const betable = !!tb && !!stake && canAfford && covers;
  if ($("btnBet")) { $("btnBet").disabled = !betable; $("btnBet").classList.toggle("pulse", betable && signedIn); }
  let hint = "";
  if (signedIn && bg.active != null) {
    if (!tb && !lastTable?.exists) hint = dapp.whereIs("table", bg.active, (bg.tableRec(bg.active) || {}).ts);
    else if (lastTable && lastTable.closed) hint = window.t("dice.tableClosedN", "Table #{t} is closed.", { t: bg.active });
    else if (!stake) hint = window.t("dice.enterStakeHint", "Enter a stake (NADO) and set your win chance, then Place roll — you can bet at your own table too.");
    else if (dapp.exec < stake) hint = window.t("dice.notEnough", "Not enough NADO — this rolls {need} but your exec balance is {have}. Deposit at least {short} more below.", { need: rawToNado(stake), have: rawToNado(dapp.exec), short: rawToNado(stake - dapp.exec) });
    else if (tb && !covers) hint = window.t("dice.cantCover2", "This table's bankroll can't cover a {m}× win (free: {free} NADO). Lower your stake, raise your win chance, or Top up the bankroll.", { m: multOf(target).toFixed(2), free: rawToNado(BigInt(tb.pool) - BigInt(tb.committed)) });
  }
  const jh = $("joinHint"); if (jh) { jh.textContent = hint; jh.classList.toggle("hidden", !hint); }
  syncStakeSlider();   // keep the max-bet slider in step with the table's live free cover
  bg.recent($("recent"), selectTable, (x) => {   // my banked tables + bets, tagged with what needs me
    if (!lastSto) return null;
    const tb = tableFrom(lastSto, x.id);
    if (!tb.exists) return null;
    if (tb.closed) return "finished ✓";
    const mySeats = seatsOfTable(lastSto, x.id).filter((st) => st.addr === dapp.me);
    if (mySeats.some((st) => !st.settled && st.ready && st.win)) return "💰 win to collect";
    if (mySeats.some((st) => st.pending)) return "your bet spins soon";
    return "live";
  });
  renderActive();
}
function renderActive() {
  if (bg.active == null) return;
  const tb = lastTable || {}, T = bg.tableRec(bg.active) || {};
  const iAmBank = tb.bank === dapp.me, mySeats = lastSeats.filter((s) => s.addr === dapp.me);
  $("gameId").textContent = "#" + bg.active;
  shareInvite("table", bg.active, window.t("dice.shareText", "Roll at my dice table #{t} on NADO:", { t: bg.active }), 180);
  $("gBank").textContent = tb.exists ? (disp(tb.bank) + (iAmBank ? window.t("dice.thatsYou", " — that's you (you're the house here)") : "")) : (T.bankroll ? window.t("dice.opening", "you (opening…)") : "—");
  $("gBankroll").textContent = tb.exists ? rawToNado(tb.pool) + " NADO" : (T.bankroll ? rawToNado(T.bankroll) + " NADO" : "—");
  $("gCover").textContent = tb.exists ? window.t("dice.nadoFree", "{amt} NADO free", { amt: rawToNado(BigInt(tb.pool) - BigInt(tb.committed)) }) : "—";
  let phaseTxt = dapp.whereIs("table", bg.active, T.ts);
  if (tb.exists) {
    if (tb.closed) phaseTxt = window.t("dice.phaseClosed", "table closed");
    else phaseTxt = window.t("dice.phaseRolling", "🟢 rolling every {every} — next roll in {next} · {n} {rolls}", { every: blocksToTime(ROUND), next: tb.roundEndsIn != null ? blocksToTime(tb.roundEndsIn) : "…", n: tb.seatCount, rolls: tb.seatCount === 1 ? window.t("dice.roll", "roll") : window.t("dice.rolls", "rolls") });
  }
  $("gStatus").textContent = phaseTxt;
  $("btnReopen").classList.toggle("hidden", !(!tb.exists && T.bankroll && T.ts && Date.now() - T.ts > 120000));
  // die shows the most recent resolved roll — lastSeats is already newest-first, so the first with a roll wins
  const top = lastSeats.find((s) => s.roll != null);
  const die = $("die");
  if (die) { if (top) { die.textContent = top.roll; die.className = "die " + (top.win ? "wroll" : "lroll"); } else { die.textContent = "?"; die.className = "die"; } }
  const seatRow = (s) => {
    const you = s.addr === dapp.me ? '<b style="color:var(--accent2)">' + window.t("dice.you", "you") + '</b> ' : "";
    let out = window.t("dice.seatBet", "on <b>under {m}</b> <span class='dim'>({mult}×)</span>", { m: s.M, mult: multOf(s.M).toFixed(2) });
    if (s.roll != null) out += ' → ' + window.t("dice.rolled", "rolled") + ' <b class="' + (s.win ? "wroll" : "lroll") + '">' + s.roll + "</b> "
        + (s.settled ? (s.win ? '<span class="b ok">' + window.t("dice.won", "won {amt}", { amt: rawToNado(returnRaw(s.stake, s.M)) }) + "</span>" : '<span class="b dimb">' + window.t("dice.noWin", "no win") + "</span>")
                     : (s.win ? '<span class="b pend">' + window.t("dice.wonCollect", "won {amt} — collect", { amt: rawToNado(returnRaw(s.stake, s.M)) }) + "</span>" : '<span class="b dimb">' + window.t("dice.lost", "lost") + "</span>"));
    else out += ' <span class="b pend">' + window.t("dice.rollsIn", "rolls in {time}", { time: s.spinsIn != null ? blocksToTime(s.spinsIn) : "…" }) + "</span>";
    return '<div class="seat">' + you + disp(s.addr) + ' · <span class="mono">' + rawToNado(s.stake) + "</span> " + out + "</div>";
  };
  // render only a capped slice — a busy table accrues unboundedly many seats over its life
  $("seats").innerHTML = lastSeats.length ? lastSeats.slice(0, seatsN).map(seatRow).join("") : '<span class="dim">' + window.t("dice.noRolls", "No rolls yet — be the first to bet.") + "</span>";
  const bms = $("btnMoreSeats");
  if (bms) {
    bms.classList.toggle("hidden", lastSeats.length <= seatsN);
    if (lastSeats.length > seatsN) bms.textContent = window.t("dice.showMoreN", "Show more ({n} more)", { n: lastSeats.length - seatsN });
  }
  const wrap = $("myActions"); wrap.innerHTML = "";
  for (const s of mySeats) {
    if (s.settled || !s.ready) continue;
    const b = document.createElement("button"); b.className = "primary"; b.style.flex = "1 1 auto";
    b.textContent = s.win ? window.t("dice.collectSeat", "💰 Collect {amt} (seat #{g})", { amt: rawToNado(returnRaw(s.stake, s.M)), g: s.g }) : window.t("dice.closeOutSeat", "Close out seat #{g}", { g: s.g });
    b.onclick = () => settleSeat(s.g); if (s.win || iAmBank) wrap.appendChild(b);
  }
  $("btnClose").classList.toggle("hidden", !(iAmBank && tb.exists && !tb.closed && tb.settledCount >= tb.seatCount));
  $("btnClose").textContent = tb.seatCount === 0 ? window.t("dice.cancelReclaim", "Cancel — reclaim bankroll") : window.t("dice.closeReclaim", "Close table — reclaim {amt}", { amt: rawToNado(tb.pool) });
  $("fundRow").classList.toggle("hidden", !(iAmBank && tb.exists && !tb.closed));
}

// ---- boot ----------------------------------------------------------------------------------------
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.table != null) bg.active = pend.table;
  dapp.showReturn(pend, ok, err);
});
async function boot() {
  try { await dapp.init(); } catch (e) { alertBar(window.t("dice.cryptoFail", "Crypto bundle failed to load — reload.")); return; }
  wireUI(); loadQR(); syncSlider(); orderCards(["activeGame","lobby","play","practice","bankcard","walletcard","bankroll","scoreboard"]);
  const q = new URLSearchParams(location.search).get("table");
  if (q) { $("joinId").value = q; if (bg.active == null) bg.active = parseInt(q, 10); }
  render(); refreshActive();
  setInterval(refreshActive, 3000);
}
boot();

// ---- PRACTICE MODE (free, fully in-browser — play chips, local RNG, nothing on-chain) -------------------
// Same 99÷chance payout as the contract; Math.random is fine here because nothing is at stake.
const prac = new Practice("dice");
let pracHist = [];
function pracRender() {
  prac.strip($("pStrip"), { chips: true, onReset: pracRender });
  const M = parseInt($("pSlider").value, 10);
  $("pOdds").textContent = M + "% · " + multOf(M).toFixed(2) + "×";
  $("pHist").innerHTML = pracHist.slice(0, 10).map((h) =>
    '<span class="chip" style="border-color:' + (h.win ? "var(--accent2)" : "var(--danger)") + '">' + h.roll + "</span>").join(" ");
}
function pracRoll() {
  const M = parseInt($("pSlider").value, 10), bet = parseInt($("pStake").value, 10) || 0;
  if (!prac.canBet(bet, notify)) return;
  const roll = Math.floor(Math.random() * PN);
  const win = roll < M;
  const net = win ? Math.floor(bet * EDGE / M) - bet : -bet;
  prac.addChips(net);
  pracHist.unshift({ roll, win });
  $("pResult").innerHTML = win
    ? '<span style="color:var(--accent2)">🎉 ' + window.t("sdk.prWin", "Rolled {r} — WIN +{n} chips!", { r: roll, n: net }) + "</span>"
    : '<span style="color:var(--danger)">' + window.t("sdk.prLose", "Rolled {r} — lost {n} chips.", { r: roll, n: -net }) + "</span>";
  pracRender();
}
if ($("pRoll")) {
  $("pRoll").onclick = pracRoll;
  $("pSlider").oninput = pracRender;
  pracRender();
}
