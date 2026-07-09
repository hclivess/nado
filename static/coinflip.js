// coinflip.js — NADO Coin Flip: a fair, STAKED 2-player commit-reveal game on the execution layer, built on
// the shared game SDK (nadodapp.js). Value flows through the bridge: deposit L1 NADO -> exec balance -> stake
// into a game pot -> winner takes the pot -> withdraw to L1. It is an ON-CHAIN CONTRACT (runtime stackvm, cid
// below) called via the GENERIC exec `call` op — the stake is escrowed as the call's VALUE and paid out by the
// contract's PAY; there is NO coinflip-specific API. All reads derive from the contract's storage. Login + every
// signature is delegated to the NADO wallet via the SDK; the key never touches this origin.
import { NadoDapp, rawToNado, nadoToRaw, randId, randSecret, commitHashOf, blake2bHash, _m, $, base,
         loadQR, drawQR, resolveAliases, disp, share } from "./nadodapp.js";

const CID = "7ee95a0abd6e00d12edc3bf39f4c8f2d";   // the Coin Flip CONTRACT (staked via VALUE/PAY, no native API)
const dapp = new NadoDapp({ cid: CID, app: "Coin Flip" });

const LS_G = "nado_coinflip_games";
const gamesLoad = () => { try { return JSON.parse(localStorage.getItem(LS_G) || "{}"); } catch { return {}; } };
const gamesSave = (g) => { try { localStorage.setItem(LS_G, JSON.stringify(g)); } catch {} };
let active = null, lastGame = null;
const stageCache = {};     // gid -> {settled, ncom, stake} : drives the game-list colours + Join affordability

// insufficient-exec-balance message: what the game costs, what you hold, and exactly how much more to deposit
const shortfallMsg = (need, have) => "Not enough NADO to join — this game stakes " + rawToNado(need) + ", but your exec balance is "
  + rawToNado(have) + ". Deposit at least " + rawToNado(need - have) + " more NADO below, then join.";
// coin result — MUST match the contract: HASH(s1+s2) % 2, HASH = blake2b(decimal string) as a 256-bit int
function coinResult(s1, s2) { return Number(BigInt("0x" + blake2bHash((BigInt(s1) + BigInt(s2)).toString())) % 2n); }

// ---- reads: game / lobby / scoreboard are all DERIVED from the contract's storage maps ----------
const allGids = (sto) => Object.keys(_m(sto, "nn"));
function gameFrom(sto, gid) {
  gid = String(gid); const nn = _m(sto, "nn")[gid] || 0;
  if (!nn) return { exists: false };
  const p1 = _m(sto, "p1")[gid], p2 = _m(sto, "p2")[gid];
  const r1 = _m(sto, "r1")[gid] ? 1 : 0, r2 = _m(sto, "r2")[gid] ? 1 : 0;
  const players = {};
  if (p1) players[p1] = { slot: 1, committed: true, revealed: !!r1 };
  if (p2) players[p2] = { slot: 2, committed: true, revealed: !!r2 };
  const settled = !!_m(sto, "sd")[gid], ws = _m(sto, "ws")[gid] || 0;
  const g = { exists: true, stake: _m(sto, "st")[gid] || 0, pot: _m(sto, "pt")[gid] || 0, settled,
              ncom: nn, nrev: r1 + r2, deadline: _m(sto, "dl")[gid] || 0, players };
  if (settled && ws) { g.winner_slot = ws; g.result = ws === 1 ? 0 : 1; }
  else if (r1 && r2) { const s1 = _m(sto, "s1")[gid], s2 = _m(sto, "s2")[gid]; if (s1 != null && s2 != null) { g.result = coinResult(s1, s2); g.winner_slot = g.result === 0 ? 1 : 2; } }
  return g;
}
function lobbyFrom(sto) {
  return allGids(sto).map((gid) => {
    const nn = _m(sto, "nn")[gid], settled = !!_m(sto, "sd")[gid];
    return { game: gid, stake: _m(sto, "st")[gid] || 0, pot: _m(sto, "pt")[gid] || 0, settled, ncom: nn,
             nrev: (_m(sto, "r1")[gid] ? 1 : 0) + (_m(sto, "r2")[gid] ? 1 : 0),
             stage: settled ? "done" : (nn >= 2 ? "live" : "open"), deadline: _m(sto, "dl")[gid] || 0 };
  }).sort((a, b) => b.deadline - a.deadline);
}
function boardFrom(sto) {
  const stats = {};
  const bump = (a, won, net) => { const x = stats[a] || (stats[a] = { addr: a, wins: 0, losses: 0, games: 0, net: 0 }); x.games++; x.net += net; won ? x.wins++ : x.losses++; };
  for (const gid of allGids(sto)) {
    if (!_m(sto, "sd")[gid]) continue;
    const p1 = _m(sto, "p1")[gid], p2 = _m(sto, "p2")[gid], ws = _m(sto, "ws")[gid];
    if (!p1 || !p2 || !ws) continue;
    const stake = _m(sto, "st")[gid] || 0, win = ws === 1 ? p1 : p2, lose = ws === 1 ? p2 : p1;
    bump(win, true, stake); bump(lose, false, -stake);
  }
  return Object.values(stats).sort((a, b) => (b.net - a.net) || (b.wins - a.wins));
}
async function fetchGame(gid) { const sto = await dapp.storage(); return sto ? gameFrom(sto, gid) : null; }

// ---- actions -------------------------------------------------------------------------------------
function doDeposit() {
  const raw = nadoToRaw($("bankAmt").value);
  if (!raw) { $("status").textContent = "Enter an amount to deposit."; return; }
  if (raw + 1000n > dapp.l1) {
    $("status").textContent = "Not enough in your L1 wallet: you have " + rawToNado(dapp.l1) +
      " NADO (deposit needs " + rawToNado(raw) + " + a tiny fee). Mine or receive more first.";
    return;
  }
  dapp.deposit(raw);
}
async function newGame() {
  const raw = nadoToRaw($("stakeAmt").value);
  if (!raw) { $("status").textContent = "Enter a stake (NADO)."; return; }
  if (dapp.exec < raw) { $("status").textContent = "Deposit first — your exec balance is " + rawToNado(dapp.exec) + " NADO."; return; }
  bet(randId(), raw, "open");
}
async function joinGame() {
  const gid = parseInt($("joinId").value, 10);
  if (!gid) return;
  $("btnJoin").classList.remove("pulse");
  const g = await fetchGame(gid);
  if (!g || !g.exists) { $("status").textContent = "No such game yet — ask your opponent for the ID after they open it."; return; }
  if (g.settled || g.ncom >= 2) { $("status").textContent = "That game is full or already settled."; return; }
  await dapp.refresh();
  const need = BigInt(g.stake);
  if (dapp.exec < need) {
    $("status").textContent = "You need " + rawToNado(need) + " NADO in your exec balance to join (you have "
      + rawToNado(dapp.exec) + "). Deposit first — and if your L1 wallet is empty too, mine or receive some NADO.";
    render(); return;
  }
  bet(gid, need, "join");
}
function bet(gameId, stakeRaw, method) {   // method: "open" (slot 1) or "join" (slot 2) — the contract escrows VALUE
  const g = gamesLoad();
  const secretStr = (g[gameId] && g[gameId].secret) ? g[gameId].secret : randSecret().toString();
  g[gameId] = { secret: secretStr, role: method, ts: Date.now(), bet: (g[gameId] || {}).bet, reveal: (g[gameId] || {}).reveal, stake: stakeRaw.toString() }; gamesSave(g);
  active = gameId; render();
  dapp.call(method, [gameId, commitHashOf(BigInt(secretStr))], stakeRaw,
        (method === "open" ? "open" : "join") + " game #" + gameId + " · " + rawToNado(stakeRaw) + " NADO",
        { gameId, phase: "bet" });
}
async function joinActive() {
  if (active == null || !lastGame || !lastGame.exists) return;
  await dapp.refresh();
  const need = BigInt(lastGame.stake);
  if (dapp.exec < need) { $("status").textContent = "You need " + rawToNado(need) + " NADO in your exec balance to join (you have " + rawToNado(dapp.exec) + ")."; render(); return; }
  bet(active, need, "join");
}
function reveal() {
  const g = gamesLoad()[active];
  if (!g) { $("status").textContent = "No secret for this game on this device."; return; }
  const slot = (lastGame && lastGame.players && lastGame.players[dapp.me]) ? lastGame.players[dapp.me].slot : (g.role === "join" ? 2 : 1);
  dapp.call("reveal" + slot, [active, BigInt(g.secret)], null, "flip the coin · game #" + active, { gameId: active, phase: "reveal" });
}
// deterministic rematch id -> BOTH players clicking "Play again" land in the SAME game (no split-into-two)
function rematchGidFor(oldGid) { return Number((BigInt(oldGid) * 6364136223846793005n + 1442695040888963407n) % 1000000000n); }
async function rematch() {
  const stake = (lastGame && lastGame.exists) ? BigInt(lastGame.stake)
    : ((gamesLoad()[active] || {}).stake ? BigInt(gamesLoad()[active].stake) : null);
  if (!stake) { $("status").textContent = "Open a new game from the panel above."; return; }
  if (dapp.exec < stake) { $("status").textContent = "Deposit more to play again — you have " + rawToNado(dapp.exec) + " NADO, need " + rawToNado(stake) + "."; return; }
  const rgid = rematchGidFor(active);
  const rg = await fetchGame(rgid);
  bet(rgid, stake, (rg && rg.exists && rg.ncom >= 1 && !rg.settled) ? "join" : "open");
}
const settle = () => dapp.call("settle", [active], null, "settle game #" + active, { gameId: active, phase: "settle" });
const claim = () => dapp.call("claim", [active], null, "claim game #" + active, { gameId: active, phase: "claim" });
const cancelGame = () => dapp.call("cancel", [active], null, "cancel game #" + active, { gameId: active, phase: "cancel" });
function doWithdraw() {
  const raw = nadoToRaw($("bankAmt").value);
  if (!raw) { $("status").textContent = "Enter an amount to withdraw."; return; }
  if (dapp.exec < raw) { $("status").textContent = "You only have " + rawToNado(dapp.exec) + " NADO in the exec layer."; return; }
  dapp.withdraw(raw);
}

async function refreshActive() {
  await dapp.refresh();
  const sto = await dapp.storage();
  if (sto) {
    if (active != null) lastGame = gameFrom(sto, active);
    for (const gid of allGids(sto)) stageCache[gid] = { settled: !!_m(sto, "sd")[gid], ncom: _m(sto, "nn")[gid] || 0, stake: _m(sto, "st")[gid] || 0 };
    renderLobby(lobbyFrom(sto));
    renderScoreboard(boardFrom(sto));
  }
  await resolveAliases([dapp.me].concat(lastGame && lastGame.players ? Object.keys(lastGame.players) : []));
  render();
}
async function renderScoreboard(board) {
  const el = $("scoreList"); if (!el) return;
  if (!board.length) { el.innerHTML = '<span class="dim">No finished games yet — be the first on the board.</span>'; return; }
  const top = board.slice(0, 10);
  await resolveAliases(top.map((r) => r.addr));
  el.innerHTML = '<table class="score"><thead><tr><th>#</th><th>Player</th><th>W–L</th><th>Net</th></tr></thead><tbody>'
    + top.map((r, i) => {
        const net = (r.net < 0 ? "-" : "+") + rawToNado(Math.abs(r.net)) + " NADO";
        const you = r.addr === dapp.me;
        return '<tr' + (you ? ' class="me"' : "") + '><td>' + (i + 1) + '</td><td>' + disp(r.addr) + (you ? " (you)" : "") +
          '</td><td>W' + r.wins + "–L" + r.losses + '</td><td class="' + (r.net >= 0 ? "pos" : "neg") + '">' + net + "</td></tr>";
      }).join("") + "</tbody></table>";
}
function renderLobby(games) {
  const el = $("lobbyList"); if (!el) return;
  const rank = { open: 0, live: 1, done: 2 }, tag = { open: "⏳", live: "▶", done: "✓" }, verb = { open: " · join", live: " · watch", done: "" };
  const shown = (games || []).slice().sort((a, b) => rank[a.stage] - rank[b.stage]).slice(0, 24);
  if (!shown.length) { el.innerHTML = '<span class="dim">No games yet — open one above.</span>'; return; }
  el.innerHTML = shown.map((g) => '<button class="chip ' + g.stage + '" data-lg="' + g.game + '">' + tag[g.stage] + " #" + g.game + " · " + rawToNado(g.stake) + " NADO" + verb[g.stage] + "</button>").join(" ");
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => {
    active = parseInt(b.dataset.lg, 10); $("joinId").value = b.dataset.lg; refreshActive();
    try { window.scrollTo({ top: 0, behavior: "smooth" }); } catch {}
  });
}

// ---- render --------------------------------------------------------------------------------------
function wireUI() {
  $("btnSignIn").onclick = () => dapp.signIn();
  $("btnDeposit").onclick = doDeposit;
  $("btnNew").onclick = newGame;
  $("btnJoin").onclick = joinGame;
  $("joinId").oninput = () => render();
  $("btnReveal").onclick = reveal;
  $("btnSettle").onclick = settle;
  $("btnClaim").onclick = claim;
  $("btnWithdraw").onclick = doWithdraw;
  $("btnShare").onclick = () => share(base() + "/?game=" + active, "Flip me " + (lastGame && lastGame.exists ? "for " + rawToNado(lastGame.stake) + " NADO " : "") + "on NADO — join game #" + active + ":", $("btnShare"));
  $("btnRematch").onclick = rematch;
  $("btnJoinActive").onclick = joinActive;
  $("btnCancel").onclick = cancelGame;
}
const badge = (s) => s === "confirmed" ? '<span class="b ok">confirmed ✓</span>' : s === "pending" ? '<span class="b pend">pending…</span>' : '<span class="b dimb">—</span>';
function render() {
  const signedIn = !!dapp.me;
  $("btnSignIn").classList.toggle("hidden", signedIn);
  $("who").textContent = signedIn ? disp(dapp.me) : "not signed in";
  $("bal").textContent = rawToNado(dapp.exec) + " NADO";
  $("l1bal").textContent = rawToNado(dapp.l1) + " NADO";
  $("play").classList.toggle("hidden", !signedIn);
  $("bankroll").classList.toggle("hidden", !signedIn);
  const jid = ($("joinId").value || "").trim();
  const lgv = lastGame || {};
  let iAmIn = false, stageJoinable = true;
  if (jid && String(active) === jid && lgv.exists) {
    iAmIn = !!(lgv.players && lgv.players[dapp.me]);
    stageJoinable = !lgv.settled && lgv.ncom < 2;
  } else if (jid) {
    iAmIn = !!(gamesLoad()[jid] || {}).bet;
    const js = stageCache[jid];
    if (js) stageJoinable = !js.settled && js.ncom < 2;
  }
  let needStake = null;
  if (jid && String(active) === jid && lgv.exists) needStake = BigInt(lgv.stake || 0);
  else if (jid && stageCache[jid] && stageCache[jid].stake != null) needStake = BigInt(stageCache[jid].stake);
  const canAfford = !(signedIn && needStake != null && dapp.exec < needStake);
  const joinable = !!jid && !iAmIn && stageJoinable && canAfford;
  $("btnJoin").disabled = !!jid && !joinable;
  $("btnJoin").classList.toggle("pulse", joinable && signedIn);
  $("btnSignIn").classList.toggle("pulse", joinable && !signedIn);
  const jh = $("joinHint");
  const showShortfall = !!jid && signedIn && !iAmIn && stageJoinable && needStake != null && dapp.exec < needStake;
  if (jh) { jh.textContent = showShortfall ? shortfallMsg(needStake, dapp.exec) : ""; jh.classList.toggle("hidden", !showShortfall); }
  const g = gamesLoad();
  const ids = Object.keys(g).filter((id) => stageCache[id]).sort((a, b) => g[b].ts - g[a].ts).slice(0, 8);
  $("recent").innerHTML = ids.length
    ? ids.map((id) => {
        const st = stageCache[id]; let cls = "", tag = "";
        if (st) { if (st.settled) { cls = " done"; tag = "✓ "; } else if (st.ncom >= 2) { cls = " live"; tag = "▶ "; } else { cls = " open"; tag = "⏳ "; } }
        return '<button class="chip' + cls + '" data-g="' + id + '">' + tag + "#" + id + " · " + rawToNado(g[id].stake || "0") + "</button>";
      }).join(" ")
    : '<span class="dim">No games yet.</span>';
  $("recent").querySelectorAll(".chip").forEach((b) => b.onclick = () => {
    active = parseInt(b.dataset.g, 10); $("joinId").value = String(active);
    $("status").textContent = "Game #" + active + " selected.";
    refreshActive();
    try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {}
  });
  renderActive();
}
function renderActive() {
  const box = $("activeGame");
  if (active == null) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  const lg = lastGame || {}, local = gamesLoad()[active] || {}, mine = (lg.players || {})[dapp.me];
  $("gameId").textContent = "#" + active;
  $("shareLink").value = base() + "/?game=" + active;
  drawQR($("shareQR"), $("shareQRNote"), base() + "/?game=" + active, 200);
  $("pot").textContent = lg.exists ? rawToNado(lg.pot) + " NADO" : "—";
  $("stakeShown").textContent = lg.exists ? rawToNado(lg.stake) + " NADO" : (local.stake ? rawToNado(local.stake) + " NADO" : "—");
  $("gStatus").textContent = lg.exists ? (lg.ncom + "/2 in · " + lg.nrev + "/2 flipped" + (lg.settled ? " · settled" : " · ⚡ live")) : "opening…";
  const pl = lg.players || {};
  const byslot = Object.keys(pl).sort((a, b) => pl[a].slot - pl[b].slot);
  let playersHtml = byslot.map((a) => '<span class="chip">' + (a === dapp.me ? "you " : "") + disp(a) + " · slot " + pl[a].slot + (pl[a].revealed ? " ✓" : "") + "</span>").join(" ");
  const myJoinPending = !mine && local.bet === "pending" && lg.exists && lg.ncom < 2;
  if (myJoinPending) playersHtml += ' <span class="chip" style="opacity:.75">you · confirming…</span>';
  $("players").innerHTML = playersHtml || '<span class="dim">no players yet</span>';
  const betC = mine ? "confirmed" : local.bet, revC = (mine && mine.revealed) ? "confirmed" : local.reveal;
  const showMine = !!mine || (local.bet === "pending" && !lg.settled);
  $("myBet").classList.toggle("hidden", !showMine);
  $("myReveal").classList.toggle("hidden", !showMine);
  if (!mine && local.bet === "pending" && lg.exists && lg.ncom >= 2)
    $("myBet").innerHTML = 'Your bet: <span class="b" style="background:rgba(248,81,73,.16);color:var(--danger)">didn\'t land — game filled first (your stake is safe)</span>';
  else
    $("myBet").innerHTML = "Your bet: " + badge(betC);
  $("myReveal").innerHTML = "Your flip: " + badge(revC);
  const bothIn = lg.ncom === 2, bothRev = lg.nrev === 2;
  const pastDeadline = lg.exists && !lg.settled && dapp.cursor != null && dapp.cursor > lg.deadline;
  $("btnReveal").classList.toggle("hidden", !(mine && !mine.revealed && bothIn && !lg.settled));
  $("btnSettle").classList.toggle("hidden", !(bothRev && !lg.settled));
  if (bothRev && !lg.settled) $("btnSettle").textContent = (mine && lg.winner_slot === mine.slot) ? "💰 Collect the pot" : "Pay out the winner";
  $("btnClaim").classList.toggle("hidden", !pastDeadline);
  $("btnCancel").classList.toggle("hidden", !(dapp.me && lg.exists && !lg.settled && lg.ncom === 1 && mine && mine.slot === 1));
  const canSeeJoinActive = !!(dapp.me && lg.exists && !lg.settled && lg.ncom < 2 && !mine);
  $("btnJoinActive").classList.toggle("hidden", !canSeeJoinActive);
  const needActive = lg.exists ? BigInt(lg.stake || 0) : 0n;
  const shortActive = canSeeJoinActive && dapp.exec < needActive;
  $("btnJoinActive").disabled = shortActive;
  const jah = $("joinActiveHint");
  if (jah) { jah.textContent = shortActive ? shortfallMsg(needActive, dapp.exec) : ""; jah.classList.toggle("hidden", !shortActive); }
  $("btnRematch").classList.toggle("hidden", !lg.settled);
  const coin = $("coin");
  if (lg.settled && (lg.result === 0 || lg.result === 1)) {
    coin.className = "coin " + (lg.result === 0 ? "heads" : "tails"); coin.textContent = lg.result === 0 ? "H" : "T";
    const iWon = mine && lg.winner_slot === mine.slot;
    $("result").textContent = (lg.result === 0 ? "HEADS" : "TAILS") + " — " + (mine ? (iWon ? "you WON " + rawToNado(BigInt(lg.stake) * 2n) + " NADO 🎉" : "you lost") : "slot " + lg.winner_slot + " won");
  } else if (lg.result === 0 || lg.result === 1) {
    coin.className = "coin " + (lg.result === 0 ? "heads" : "tails"); coin.textContent = lg.result === 0 ? "H" : "T";
    const iWon = mine && lg.winner_slot === mine.slot;
    const outcome = (lg.result === 0 ? "HEADS" : "TAILS") + " — " + (mine ? (iWon ? "you WON " + rawToNado(BigInt(lg.stake) * 2n) + " NADO 🎉" : "you lost") : "slot " + lg.winner_slot + " won");
    $("result").textContent = outcome + " · paying the winner…";
  } else {
    coin.className = "coin spin"; coin.textContent = "?";
    $("result").textContent = bothIn ? "Both in — flip the coin!"
      : myJoinPending ? "Your join is confirming on-chain (~1 min)…"
      : "Waiting for a second player…";
  }
}

// ---- boot ----------------------------------------------------------------------------------------
dapp.onReturn((pend, ok, err) => {
  const label = { connect: "Signed in.", deposit: "Deposit submitted — confirming on-chain…", bet: "Bet submitted — confirming…",
    reveal: "Flip submitted — confirming…", settle: "Settling…", claim: "Claiming…", withdraw: "Withdrawal submitted." }[pend && pend.phase] || "Submitted.";
  if (pend && pend.gameId != null) active = pend.gameId;
  if (ok && pend && pend.phase === "bet") { const g = gamesLoad(); if (g[pend.gameId]) { g[pend.gameId].bet = "pending"; gamesSave(g); } }
  if (ok && pend && pend.phase === "reveal") { const g = gamesLoad(); if (g[pend.gameId]) { g[pend.gameId].reveal = "pending"; gamesSave(g); } }
  $("status").textContent = ok ? label : "Rejected" + (err ? ": " + err : ".");
});
async function boot() {
  try { await dapp.init(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload."; return; }
  wireUI();
  if ($("play") && $("activeGame")) $("play").parentNode.insertBefore($("activeGame"), $("play"));
  loadQR();
  const q = new URLSearchParams(location.search).get("game");
  if (q) { $("joinId").value = q; if (active == null) active = parseInt(q, 10); }
  render();
  refreshActive();
  setInterval(refreshActive, 3000);
}
boot();
