// coinflip.js — NADO Coin Flip: a fair, STAKED 2-player game on the execution layer, built on the shared game
// SDK (nadodapp.js). No secrets, no reveal, no signing dance: both players just stake. When the second player
// joins, the game binds to a settle height; once that block is finalized the coin is decided BY THE CHAIN:
//   result = HASH( BLOCKHASH(sh) + BLOCKHASH(sh+1) + gameId ) % 2   (0 -> heads/p1, 1 -> tails/p2)
// Those block hashes don't exist yet when either player stakes, so nobody can predict or steer the flip. settle
// is permissionless and pays the pot to the winner — a sore loser has nothing to withhold. It is an ON-CHAIN
// CONTRACT (runtime stackvm) called via the generic exec `call` op; the stake is escrowed as VALUE and paid by
// the contract's PAY. Login + every signature is delegated to the NADO wallet; the key never touches this origin.
import { NadoDapp, rawToNado, nadoToRaw, randId, blake2bHash, _m, $, base, gate,
         loadQR, drawQR, resolveAliases, disp, share } from "./nadodapp.js";

const CID = "7ee95a0abd6e00d12edc3bf39f4c8f2d";
const dapp = new NadoDapp({ cid: CID, app: "Coin Flip" });
const BLOCK_SECS = 6;

const LS_G = "nado_coinflip_games";
const gamesLoad = () => { try { return JSON.parse(localStorage.getItem(LS_G) || "{}"); } catch { return {}; } };
const gamesSave = (g) => { try { localStorage.setItem(LS_G, JSON.stringify(g)); } catch {} };
let active = null, lastGame = null;
const stageCache = {};     // gid -> {settled, ncom, stake}
const bhCache = {};        // height -> hex|null

const shortfallMsg = (need, have) => "Not enough NADO to join — this game stakes " + rawToNado(need) + ", but your exec balance is "
  + rawToNado(have) + ". Deposit at least " + rawToNado(need - have) + " more NADO below, then join.";
const blocksToTime = (b) => { b = Math.max(0, b) * BLOCK_SECS; const m = Math.floor(b / 60), s = b % 60; return m + ":" + String(s).padStart(2, "0"); };
// coin result — MUST match the contract: HASH(bh(sh)+bh(sh+1)+gid) % 2, HASH = blake2b(decimal) as int
function flipFrom(shHex, sh1Hex, g) {
  if (!shHex || !sh1Hex) return null;
  const seed = BigInt("0x" + shHex) + BigInt("0x" + sh1Hex) + BigInt(g);   // BigInt so canonicalize emits bare digits
  return Number(BigInt("0x" + blake2bHash(seed)) % 2n);
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
  else if (nn === 2 && cur != null && cur >= g.sh + 1) { const r = flipFrom(bhCache[g.sh], bhCache[g.sh + 1], gid); if (r != null) { g.result = r; g.winner_slot = r === 0 ? 1 : 2; g.ready = true; } }
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
  const stats = {}, bump = (a, won, net) => { const x = stats[a] || (stats[a] = { addr: a, wins: 0, losses: 0, games: 0, net: 0 }); x.games++; x.net += net; won ? x.wins++ : x.losses++; };
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
  if (raw + 1000n > dapp.l1) { $("status").textContent = "Not enough in your L1 wallet: you have " + rawToNado(dapp.l1) + " NADO."; return; }
  dapp.deposit(raw);
}
function doWithdraw() {
  const raw = nadoToRaw($("bankAmt").value);
  if (!raw) { $("status").textContent = "Enter an amount to withdraw."; return; }
  if (dapp.exec < raw) { $("status").textContent = "You only have " + rawToNado(dapp.exec) + " NADO in the exec layer."; return; }
  dapp.withdraw(raw);
}
function bet(gameId, stakeRaw, method) {   // method: "open" (slot 1) or "join" (slot 2)
  const g = gamesLoad();
  g[gameId] = { role: method, ts: Date.now(), bet: (g[gameId] || {}).bet, stake: stakeRaw.toString() }; gamesSave(g);
  active = gameId; render();
  dapp.call(method, [gameId], stakeRaw, (method === "open" ? "open" : "join") + " game #" + gameId + " · " + rawToNado(stakeRaw) + " NADO", { gameId, phase: "bet" });
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
  const g = await fetchGame(gid);
  if (!g || !g.exists) { $("status").textContent = "No such game yet — ask your opponent for the ID after they open it."; return; }
  if (g.settled || g.ncom >= 2) { $("status").textContent = "That game is full or already settled."; return; }
  await dapp.refresh();
  const need = BigInt(g.stake);
  if (dapp.exec < need) { $("status").textContent = shortfallMsg(need, dapp.exec); render(); return; }
  bet(gid, need, "join");
}
async function joinActive() {
  if (active == null || !lastGame || !lastGame.exists) return;
  await dapp.refresh();
  const need = BigInt(lastGame.stake);
  if (dapp.exec < need) { $("status").textContent = shortfallMsg(need, dapp.exec); render(); return; }
  bet(active, need, "join");
}
function reopenGame() {   // retry an open that never landed (same id is still fresh)
  const L = gamesLoad()[active]; if (!L || L.role !== "open" || !L.stake) return;
  const raw = BigInt(L.stake);
  if (dapp.exec < raw) { $("status").textContent = "Deposit first — this stake needs " + rawToNado(raw) + " NADO."; return; }
  bet(active, raw, "open");
}
const settle = () => dapp.call("settle", [active], null, "settle game #" + active, { gameId: active, phase: "settle" });
const cancelGame = () => dapp.call("cancel", [active], null, "cancel game #" + active, { gameId: active, phase: "cancel" });
// deterministic rematch id -> BOTH players clicking "Play again" land in the SAME game
function rematchGidFor(oldGid) { return Number((BigInt(oldGid) * 6364136223846793005n + 1442695040888963407n) % 1000000000n); }
async function rematch() {
  const stake = (lastGame && lastGame.exists) ? BigInt(lastGame.stake) : ((gamesLoad()[active] || {}).stake ? BigInt(gamesLoad()[active].stake) : null);
  if (!stake) { $("status").textContent = "Open a new game from the panel above."; return; }
  if (dapp.exec < stake) { $("status").textContent = "Deposit more to play again — you have " + rawToNado(dapp.exec) + " NADO, need " + rawToNado(stake) + "."; return; }
  const rgid = rematchGidFor(active), rg = await fetchGame(rgid);
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
      if (nn === 2 && !_m(sto, "sd")[String(active)] && cur != null && cur >= sh + 1) await fetchHashes([sh, sh + 1]);
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
async function renderScoreboard(board) {
  const el = $("scoreList"); if (!el) return;
  if (!board.length) { el.innerHTML = '<span class="dim">No finished games yet — be the first on the board.</span>'; return; }
  const top = board.slice(0, 10); await resolveAliases(top.map((r) => r.addr));
  el.innerHTML = '<table class="score"><thead><tr><th>#</th><th>Player</th><th>W–L</th><th>Net</th></tr></thead><tbody>'
    + top.map((r, i) => { const net = (r.net < 0 ? "-" : "+") + rawToNado(Math.abs(r.net)) + " NADO", you = r.addr === dapp.me;
        return '<tr' + (you ? ' class="me"' : "") + '><td>' + (i + 1) + '</td><td>' + disp(r.addr) + (you ? " (you)" : "") + '</td><td>W' + r.wins + "–L" + r.losses + '</td><td class="' + (r.net >= 0 ? "pos" : "neg") + '">' + net + "</td></tr>"; }).join("") + "</tbody></table>";
}
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
  $("btnSignIn").onclick = () => dapp.signIn();
  $("btnDeposit").onclick = doDeposit;
  $("btnNew").onclick = newGame;
  $("btnJoin").onclick = joinGame;
  $("joinId").oninput = () => render();
  $("btnSettle").onclick = settle;
  $("btnWithdraw").onclick = doWithdraw;
  $("btnShare").onclick = () => share(base() + "/?game=" + active, "Flip me " + (lastGame && lastGame.exists ? "for " + rawToNado(lastGame.stake) + " NADO " : "") + "on NADO — join game #" + active + ":", $("btnShare"));
  $("btnRematch").onclick = rematch;
  $("btnJoinActive").onclick = joinActive;
  $("btnCancel").onclick = cancelGame;
  $("btnReopen").onclick = reopenGame;
}
const badge = (s) => s === "confirmed" ? '<span class="b ok">confirmed ✓</span>' : s === "pending" ? '<span class="b pend">pending…</span>' : '<span class="b dimb">—</span>';
function render() {
  const signedIn = !!dapp.me;
  gate({ play: signedIn, bankroll: signedIn, activeGame: active != null });
  $("btnSignIn").classList.toggle("hidden", signedIn);
  $("who").textContent = signedIn ? disp(dapp.me) : "not signed in";
  $("bal").textContent = rawToNado(dapp.exec) + " NADO";
  $("l1bal").textContent = rawToNado(dapp.l1) + " NADO";
  const jid = ($("joinId").value || "").trim();
  const lgv = lastGame || {};
  let iAmIn = false, stageJoinable = true, needStake = null;
  if (jid && String(active) === jid && lgv.exists) { iAmIn = !!(lgv.players && lgv.players[dapp.me]); stageJoinable = !lgv.settled && lgv.ncom < 2; needStake = BigInt(lgv.stake || 0); }
  else if (jid) { const js = stageCache[jid]; if (js) { stageJoinable = !js.settled && js.ncom < 2; needStake = js.stake != null ? BigInt(js.stake) : null; } }
  const canAfford = !(signedIn && needStake != null && dapp.exec < needStake);
  const joinable = !!jid && !iAmIn && stageJoinable && canAfford;
  $("btnJoin").disabled = !!jid && !joinable;
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
  $("shareLink").value = base() + "/?game=" + active;
  drawQR($("shareQR"), $("shareQRNote"), base() + "/?game=" + active, 200);
  $("pot").textContent = lg.exists ? rawToNado(lg.pot) + " NADO" : "—";
  $("stakeShown").textContent = lg.exists ? rawToNado(lg.stake) + " NADO" : (local.stake ? rawToNado(local.stake) + " NADO" : "—");
  $("gStatus").textContent = lg.exists ? (lg.ncom + "/2 in" + (lg.settled ? " · settled" : lg.ncom === 2 ? " · ⚡ flipping" : " · waiting")) : "opening…";
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
  const canSeeJoinActive = !!(dapp.me && lg.exists && !lg.settled && lg.ncom < 2 && !mine);
  const needActive = lg.exists ? BigInt(lg.stake || 0) : 0n, shortActive = canSeeJoinActive && dapp.exec < needActive;
  $("btnJoinActive").classList.toggle("hidden", !canSeeJoinActive);
  $("btnJoinActive").disabled = shortActive;
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
  const label = { connect: "Signed in.", deposit: "Deposit submitted — confirming on-chain…", bet: "Bet submitted — confirming…",
    settle: "Settling…", cancel: "Cancelling…", withdraw: "Withdrawal submitted." }[pend && pend.phase] || "Submitted.";
  if (pend && pend.gameId != null) active = pend.gameId;
  if (ok && pend && pend.phase === "bet") { const g = gamesLoad(); if (g[pend.gameId]) { g[pend.gameId].bet = "pending"; gamesSave(g); } }
  $("status").textContent = ok ? label : "Rejected" + (err ? ": " + err : ".");
});
async function boot() {
  try { await dapp.init(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload."; return; }
  wireUI(); loadQR();
  const q = new URLSearchParams(location.search).get("game");
  if (q) { $("joinId").value = q; if (active == null) active = parseInt(q, 10); }
  render(); refreshActive();
  setInterval(refreshActive, 3000);
}
boot();
