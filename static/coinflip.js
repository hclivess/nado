// coinflip.js — NADO Coin Flip: a fair, STAKED 2-player game on the execution layer, built on the shared game
// SDK (nadodapp.js). No secrets, no reveal, no signing dance: both players just stake. When the second player
// joins, the game binds to a settle height; once that block is finalized the coin is decided BY THE CHAIN:
//   result = HASH( BLOCKHASH(sh) + BLOCKHASH(sh+1) + gameId ) % 2   (0 -> heads/p1, 1 -> tails/p2)
// Those block hashes don't exist yet when either player stakes, so nobody can predict or steer the flip. settle
// is permissionless and pays the pot to the winner — a sore loser has nothing to withhold. It is an ON-CHAIN
// CONTRACT (runtime stackvm) called via the generic exec `call` op; the stake is escrowed as VALUE and paid by
// the contract's PAY. Login + every signature is delegated to the NADO wallet; the key never touches this origin.
import { NadoDapp, rawToNado, nadoToRaw, randId, rematchId, _m, $, base, gate, canPay, hoist, orderCards, chainResult, blocksToTime,
         lsLoad, lsSave, wireWallet, stickyInputs, renderWallet, renderScore, scoreBump, scoreSort, statusLabel,
         loadQR, drawQR, resolveAliases, disp, share, shareInvite } from "./nadodapp.js";

const CID = "d0c95d981fa9b0c521bdcff28662c0df";
const GICON = '<svg style="vertical-align:-3px" viewBox="0 0 48 48" width="16" height="16" fill="none" aria-hidden="true">     <ellipse cx="18" cy="27" rx="10.5" ry="12.5" fill="#c8901a" stroke="#8a6209" stroke-width="1.6"/>     <circle cx="28" cy="24" r="13" fill="#e3b341" stroke="#b5810f" stroke-width="2.4"/>     <circle cx="28" cy="24" r="8.6" stroke="#a9760a" stroke-width="1.3" fill="none"/>     <text x="28" y="29" text-anchor="middle" font-size="13" font-weight="800" fill="#7a5606" font-family="system-ui">N</text></svg>';
const dapp = new NadoDapp({ cid: CID, app: "Coin Flip" });
const BLOCK_SECS = 6;

const LS_G = "nado_coinflip_games";
const gamesLoad = () => lsLoad(LS_G);
const gamesSave = (g) => lsSave(LS_G, g);
let active = null, lastGame = null;
const stageCache = {};     // gid -> {settled, ncom, stake}

const shortfallMsg = (need, have) => "Not enough NADO to join — this game stakes " + rawToNado(need) + ", but your exec balance is "
  + rawToNado(have) + ". Deposit at least " + rawToNado(need - have) + " more NADO below, then join.";

// ---- reads: all DERIVED from the contract's storage maps ----------------------------------------
const allGids = (sto) => Object.keys(_m(sto, "nn"));
function gameFrom(sto, gid) {
  gid = String(gid); const nn = _m(sto, "nn")[gid] || 0;
  if (!nn) return { exists: false };
  const p1 = _m(sto, "p1")[gid], p2 = _m(sto, "p2")[gid], settled = !!_m(sto, "sd")[gid], ws = _m(sto, "ws")[gid] || 0;
  const players = {};
  if (p1) players[p1] = { slot: 1 };
  if (p2) players[p2] = { slot: 2 };
  const g = { exists: true, stake: _m(sto, "st")[gid] || 0, pot: _m(sto, "pt")[gid] || 0, settled,
              ncom: nn, sh: _m(sto, "sh")[gid] || 0, players, id: Number(gid) };
  const cur = dapp.cursor;
  if (settled && ws) { g.winner_slot = ws; g.result = ws === 1 ? 0 : 1; }
  else if (nn === 2 && cur != null && cur >= g.sh + 1) { const r = chainResult(dapp.bh(g.sh), dapp.bh(g.sh + 1), gid, 2); if (r != null) { g.result = r; g.winner_slot = r === 0 ? 1 : 2; g.ready = true; } }
  else if (nn === 2 && cur != null) g.flipsIn = g.sh + 1 - cur;
  return g;
}
function lobbyFrom(sto) {
  return allGids(sto).map((gid) => {
    const nn = _m(sto, "nn")[gid], settled = !!_m(sto, "sd")[gid];
    return { game: gid, stake: _m(sto, "st")[gid] || 0, settled, ncom: nn,
             stage: settled ? "done" : (nn >= 2 ? "live" : "open") };
  });
}
function boardFrom(sto) {
  const stats = {};
  for (const gid of allGids(sto)) {
    if (!_m(sto, "sd")[gid]) continue;
    const p1 = _m(sto, "p1")[gid], p2 = _m(sto, "p2")[gid], ws = _m(sto, "ws")[gid];
    if (!p1 || !p2 || !ws) continue;
    const stake = _m(sto, "st")[gid] || 0, win = ws === 1 ? p1 : p2, lose = ws === 1 ? p2 : p1;
    scoreBump(stats, win, stake); scoreBump(stats, lose, -stake);
  }
  return scoreSort(stats);
}
async function fetchGame(gid) { const sto = await dapp.storage(); return sto ? gameFrom(sto, gid) : null; }

// ---- actions -------------------------------------------------------------------------------------
function bet(gameId, stakeRaw, method) {   // method: "open" (slot 1) or "join" (slot 2)
  const g = gamesLoad();
  g[gameId] = { role: method, ts: Date.now(), bet: (g[gameId] || {}).bet, stake: stakeRaw.toString() }; gamesSave(g);
  active = gameId; render();
  dapp.call(method, [gameId], stakeRaw, (method === "open" ? "open" : "join") + " game #" + gameId + " · " + rawToNado(stakeRaw) + " NADO", { gameId, phase: "bet" });
}
async function newGame() {
  const raw = nadoToRaw($("stakeAmt").value);
  if (!raw) { $("status").textContent = "Enter a stake (NADO)."; return; }
  if (!canPay(dapp, raw, "Opening this game")) return;
  bet(randId(), raw, "open");
}
async function joinGame() {
  const gid = parseInt($("joinId").value, 10);
  if (!gid) return;
  const g = await fetchGame(gid);
  if (!g || !g.exists) { $("status").textContent = dapp.whereIs("game", gid); return; }
  if (g.settled || g.ncom >= 2) { $("status").textContent = "That game is full or already settled."; return; }
  await dapp.refresh();
  const need = BigInt(g.stake);
  if (!canPay(dapp, need, "Joining this game")) { render(); return; }
  bet(gid, need, "join");
}
async function joinActive() {
  if (active == null || !lastGame || !lastGame.exists) return;
  await dapp.refresh();
  const need = BigInt(lastGame.stake);
  if (!canPay(dapp, need, "Joining this game")) { render(); return; }
  bet(active, need, "join");
}
function reopenGame() {   // retry an open that never landed (same id is still fresh)
  const L = gamesLoad()[active]; if (!L || L.role !== "open" || !L.stake) return;
  const raw = BigInt(L.stake);
  if (!canPay(dapp, raw, "Re-opening this game")) return;
  bet(active, raw, "open");
}
const settle = () => dapp.call("settle", [active], null, "settle game #" + active, { gameId: active, phase: "settle" });
const cancelGame = () => dapp.call("cancel", [active], null, "cancel game #" + active, { gameId: active, phase: "cancel" });
async function rematch() {
  const stake = (lastGame && lastGame.exists) ? BigInt(lastGame.stake) : ((gamesLoad()[active] || {}).stake ? BigInt(gamesLoad()[active].stake) : null);
  if (!stake) { $("status").textContent = "Open a new game from the panel above."; return; }
  if (!canPay(dapp, stake, "The rematch")) return;
  const rgid = rematchId(active), rg = await fetchGame(rgid);
  bet(rgid, stake, (rg && rg.exists && rg.ncom >= 1 && !rg.settled) ? "join" : "open");
}

async function refreshActive() {
  await dapp.refresh();
  const sto = await dapp.storage();
  if (sto) {
    for (const gid of allGids(sto)) stageCache[gid] = { settled: !!_m(sto, "sd")[gid], ncom: _m(sto, "nn")[gid] || 0, stake: _m(sto, "st")[gid] || 0 };
    // fetch block hashes to resolve the active game's flip client-side
    if (active != null) {
      const nn = _m(sto, "nn")[String(active)] || 0, sh = _m(sto, "sh")[String(active)] || 0, cur = dapp.cursor;
      // FAST (provisional) hashes: the flip is PUBLIC randomness the settle re-validates on-chain, so a
      // reorg can only revert the settling tx visibly — never flip a coin silently. Result shows in one
      // block (~6-18s) instead of waiting ~90s for finality (same rule Farkle's dice use).
      if (nn === 2 && !_m(sto, "sd")[String(active)] && cur != null && cur >= sh + 1) await dapp.blockHashes([sh, sh + 1], { fast: true });
      lastGame = gameFrom(sto, active);
    }
    const gg = gamesLoad(); let pruned = false;
    for (const id of Object.keys(gg)) if (!stageCache[id] && Date.now() - (gg[id].ts || 0) > 600000) { delete gg[id]; pruned = true; }
    if (pruned) gamesSave(gg);
    renderLobby(lobbyFrom(sto)); renderScoreboard(boardFrom(sto));
  }
  await resolveAliases([dapp.me].concat(lastGame && lastGame.players ? Object.keys(lastGame.players) : []));
  render();
}
const renderScoreboard = (board) => renderScore($("scoreList"), board, dapp.me, "No finished games yet — be the first on the board.");
function renderLobby(games) {
  const el = $("lobbyList"); if (!el) return;
  const rank = { open: 0, live: 1, done: 2 }, tag = { open: "⏳", live: "▶", done: "✓" }, verb = { open: " · join", live: " · watch", done: "" };
  const shown = (games || []).slice().sort((a, b) => rank[a.stage] - rank[b.stage]).slice(0, 24);
  if (!shown.length) { el.innerHTML = '<span class="dim">No games yet — open one above.</span>'; return; }
  el.innerHTML = shown.map((g) => '<button class="chip ' + g.stage + '" data-lg="' + g.game + '">' + tag[g.stage] + " #" + g.game + " · " + rawToNado(g.stake) + " NADO" + verb[g.stage] + "</button>").join(" ");
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => { active = parseInt(b.dataset.lg, 10); $("joinId").value = b.dataset.lg; refreshActive(); try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {} });
}

// ---- render --------------------------------------------------------------------------------------
function wireUI() {
  wireWallet(dapp);
  stickyInputs(dapp, ['stakeAmt', 'bankAmt']);   // typed amounts persist across turns
  $("btnNew").onclick = newGame;
  $("btnJoin").onclick = joinGame;
  $("joinId").oninput = () => render();
  $("btnSettle").onclick = settle;
  $("btnShare").onclick = () => share(base() + "/?game=" + active, "Flip me " + (lastGame && lastGame.exists ? "for " + rawToNado(lastGame.stake) + " NADO " : "") + "on NADO — join game #" + active + ":", $("btnShare"));
  $("btnRematch").onclick = rematch;
  $("btnJoinActive").onclick = joinActive;
  $("btnCancel").onclick = cancelGame;
  $("btnReopen").onclick = reopenGame;
}
const badge = (s) => s === "confirmed" ? '<span class="b ok">confirmed ✓</span>' : s === "pending" ? '<span class="b pend">pending…</span>' : '<span class="b dimb">—</span>';
function render() {
  const signedIn = renderWallet(dapp);
  gate({ play: signedIn, bankroll: signedIn, activeGame: active != null });
  const jid = ($("joinId").value || "").trim();
  const lgv = lastGame || {};
  let iAmIn = false, stageJoinable = true, needStake = null;
  if (jid && String(active) === jid && lgv.exists) { iAmIn = !!(lgv.players && lgv.players[dapp.me]); stageJoinable = !lgv.settled && lgv.ncom < 2; needStake = BigInt(lgv.stake || 0); }
  else if (jid) { const js = stageCache[jid]; if (js) { stageJoinable = !js.settled && js.ncom < 2; needStake = js.stake != null ? BigInt(js.stake) : null; } }
  const canAfford = !(signedIn && needStake != null && dapp.exec < needStake);
  const joiningById = dapp.busy("bet", "gameId", jid);
  const joinable = !!jid && !iAmIn && stageJoinable && canAfford && !joiningById;
  $("btnJoin").disabled = (!!jid && !joinable) || joiningById;
  $("btnJoin").textContent = joiningById ? "⏳ Confirming…" : "Join";
  $("btnJoin").classList.toggle("pulse", joinable && signedIn);
  $("btnSignIn").classList.toggle("pulse", joinable && !signedIn);
  const jh = $("joinHint");
  const showShortfall = !!jid && signedIn && !iAmIn && stageJoinable && needStake != null && dapp.exec < needStake;
  if (jh) { jh.textContent = showShortfall ? shortfallMsg(needStake, dapp.exec) : ""; jh.classList.toggle("hidden", !showShortfall); }
  const g = gamesLoad();
  const ids = Object.keys(g).sort((a, b) => g[b].ts - g[a].ts).slice(0, 8);
  $("recent").innerHTML = ids.length
    ? ids.map((id) => {
        const st = stageCache[id]; let cls = "", tag = "", title = "";
        if (st) { if (st.settled) { cls = " done"; tag = "✓ "; } else if (st.ncom >= 2) { cls = " live"; tag = "▶ "; } else { cls = " open"; tag = "⏳ "; } }
        else { cls = " pending"; tag = "⏳ "; title = ' title="still confirming on-chain — your game hasn\'t vanished"'; }
        return '<button class="chip' + cls + '" data-g="' + id + '"' + title + ">" + tag + "#" + id + " · " + rawToNado(g[id].stake || "0") + "</button>";
      }).join(" ")
    : '<span class="dim">No games yet.</span>';
  $("recent").querySelectorAll(".chip").forEach((b) => b.onclick = () => { active = parseInt(b.dataset.g, 10); $("joinId").value = String(active); $("status").textContent = "Game #" + active + " selected."; refreshActive(); try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {} });
  renderActive();
}
function renderActive() {
  if (active == null) return;
  const lg = lastGame || {}, local = gamesLoad()[active] || {}, mine = (lg.players || {})[dapp.me];
  $("gameId").textContent = "#" + active;
  shareInvite("game", active, "Flip me on NADO — join coin flip #" + active + ":");
  $("pot").textContent = lg.exists ? rawToNado(lg.pot) + " NADO" : "—";
  $("stakeShown").textContent = lg.exists ? rawToNado(lg.stake) + " NADO" : (local.stake ? rawToNado(local.stake) + " NADO" : "—");
  $("gStatus").textContent = lg.exists ? (lg.ncom + "/2 in" + (lg.settled ? " · settled" : lg.ncom === 2 ? " · ⚡ flipping" : " · waiting")) : dapp.whereIs("game", active, local.ts);
  const pl = lg.players || {};
  const byslot = Object.keys(pl).sort((a, b) => pl[a].slot - pl[b].slot);
  let playersHtml = byslot.map((a) => '<span class="chip">' + (a === dapp.me ? "you " : "") + disp(a) + " · slot " + pl[a].slot + "</span>").join(" ");
  const myJoinPending = !mine && local.bet === "pending" && lg.exists && lg.ncom < 2;
  if (myJoinPending) playersHtml += ' <span class="chip" style="opacity:.75">you · confirming…</span>';
  $("players").innerHTML = playersHtml || '<span class="dim">no players yet</span>';
  const showMine = !!mine || (local.bet === "pending" && !lg.settled);
  $("myBet").classList.toggle("hidden", !showMine);
  $("myReveal").classList.add("hidden");   // no reveal step in the beacon model
  if (!mine && local.bet === "pending" && lg.exists && lg.ncom >= 2)
    $("myBet").innerHTML = 'Your bet: <span class="b" style="background:rgba(248,81,73,.16);color:var(--danger)">didn\'t land — game filled first (your stake is safe)</span>';
  else $("myBet").innerHTML = "Your bet: " + badge(mine ? "confirmed" : local.bet);
  // actions
  const resolved = lg.result === 0 || lg.result === 1;
  $("btnSettle").classList.toggle("hidden", !(lg.exists && !lg.settled && lg.ncom === 2 && lg.ready));
  if (lg.ready) $("btnSettle").textContent = (mine && lg.winner_slot === mine.slot) ? "💰 Collect the pot" : "Pay out the winner";
  $("btnCancel").classList.toggle("hidden", !(dapp.me && lg.exists && !lg.settled && lg.ncom === 1 && mine && mine.slot === 1));
  if (mine) dapp.clearInflight();                              // our seat is on-chain now — stop "confirming…"
  const joining = dapp.busy("bet", "gameId", active);          // just clicked join/open, not yet confirmed
  const canSeeJoinActive = !!(dapp.me && lg.exists && !lg.settled && lg.ncom < 2 && !mine && !joining);
  const needActive = lg.exists ? BigInt(lg.stake || 0) : 0n, shortActive = canSeeJoinActive && dapp.exec < needActive;
  $("btnJoinActive").classList.toggle("hidden", !(canSeeJoinActive || joining));
  $("btnJoinActive").disabled = shortActive || joining;
  $("btnJoinActive").textContent = joining ? "⏳ Joining — confirming on-chain…" : "Join this game";
  const jah = $("joinActiveHint"); if (jah) { jah.textContent = shortActive ? shortfallMsg(needActive, dapp.exec) : ""; jah.classList.toggle("hidden", !shortActive); }
  $("btnRematch").classList.toggle("hidden", !lg.settled);
  $("btnReopen").classList.toggle("hidden", !(local.role === "open" && local.stake && !lg.exists && local.ts && Date.now() - local.ts > 120000));
  // coin
  const coin = $("coin");
  if (resolved) {
    coin.className = "coin " + (lg.result === 0 ? "heads" : "tails"); coin.textContent = lg.result === 0 ? "H" : "T";
    const iWon = mine && lg.winner_slot === mine.slot;
    $("result").textContent = (lg.result === 0 ? "HEADS" : "TAILS") + " — " + (mine ? (iWon ? "you WON " + rawToNado(BigInt(lg.stake) * 2n) + " NADO 🎉" : "you lost") : "slot " + lg.winner_slot + " won") + (lg.settled ? "" : " · collect below");
  } else {
    coin.className = "coin spin"; coin.textContent = "?";
    $("result").textContent = lg.ncom === 2 ? ("Both in — the chain flips in " + (lg.flipsIn != null ? blocksToTime(lg.flipsIn) : "…"))
      : myJoinPending ? "Your join is confirming on-chain (~1 min)…" : "Waiting for a second player…";
  }
}

// ---- boot ----------------------------------------------------------------------------------------
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.gameId != null) active = pend.gameId;
  if (ok && pend && pend.phase === "bet") { const g = gamesLoad(); if (g[pend.gameId]) { g[pend.gameId].bet = "pending"; gamesSave(g); } }
  $("status").textContent = statusLabel(pend, ok, err, { bet: "Bet submitted — confirming…", settle: "Settling…" });
});
async function boot() {
  try { await dapp.init(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload."; return; }
  wireUI(); loadQR(); orderCards(["activeGame","lobby","play","walletcard","bankroll","scoreboard"]);
  const q = new URLSearchParams(location.search).get("game");
  if (q) { $("joinId").value = q; if (active == null) active = parseInt(q, 10); }
  render(); refreshActive();
  setInterval(refreshActive, 3000);
}
boot();
