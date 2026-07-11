// tictactoe.js — NADO Tic-Tac-Toe: staked 3x3 where the CONTRACT is the referee (unlike chess, a 3x3
// board fits in the VM): move() checks turn + free cell ON-CHAIN, detects three-in-a-row and pays the
// pot instantly, and a full board auto-refunds both stakes. Ply-bound moves (the chess retry-race
// lesson), resign/abort escapes, and a short ~30-min move clock. Built on the shared SDK (nadodapp.js).
import { NadoDapp, rawToNado, nadoToRaw, randId, _m, $, base, gate, canPay, orderCards, alertBar, blocksToTime, inviteGate,
         lsLoad as load, lsSave as save, lsPrune, wireWallet, stickyInputs, renderWallet, renderScore, scoreBump, scoreSort,
         recentChips, statusLabel, loadQR, drawQR, resolveAliases, disp, share, shareInvite } from "./nadodapp.js";

const CID = "68f2bf23441437af6655e2eba4a71ba1";
const GICON = "⭕";
const dapp = new NadoDapp({ cid: CID, app: "TicTacToe" });
const WINDOW = 300;
const LINES = [[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]];
const LS_G = "nado_ttt_games";

let lastSto = null, activeGame = null, lastGame = null, watch = null, pendingCell = null;

// ---- reads -----------------------------------------------------------------------------------------
function gameFrom(sto, g) {
  g = String(g); const p1 = _m(sto, "p1")[g];
  if (!p1) return { exists: false };
  const gm = { exists: true, id: Number(g), p1, p2: _m(sto, "p2")[g] || null, stake: _m(sto, "st")[g] || 0,
    pot: _m(sto, "pt")[g] || 0, nn: _m(sto, "nn")[g] || 0, sd: !!_m(sto, "sd")[g], mc: _m(sto, "mc")[g] || 0,
    dl: _m(sto, "dl")[g] || 0, wr: _m(sto, "wr")[g] || 0 };
  gm.board = Array.from({ length: 9 }, (_, i) => _m(sto, "bd")[String(Number(g) * 16 + i)] || 0);
  gm.turnAddr = gm.nn === 2 && !gm.sd ? (gm.mc % 2 === 0 ? gm.p1 : gm.p2) : null;
  gm.winLine = null;
  for (const ln of LINES) { const v = gm.board[ln[0]]; if (v && v === gm.board[ln[1]] && v === gm.board[ln[2]]) gm.winLine = ln; }
  return gm;
}

// ---- actions ---------------------------------------------------------------------------------------
function newGame() {
  const raw = nadoToRaw($("stakeAmt").value);
  if (!raw) return alertBar("Enter your stake in NADO — your opponent matches it, winner takes both.");
  if (!canPay(dapp, raw, "Opening this game")) return;
  const g = randId();
  const G = load(LS_G); G[g] = { role: "x", ts: Date.now() }; save(LS_G, G);
  activeGame = g;
  dapp.call("open", [g], raw, "open tic-tac-toe #" + g + " · stake " + rawToNado(raw) + " NADO", { game: g, phase: "open" });
}
function joinGame() {
  const gm = lastGame;
  if (!gm || !gm.exists) { if (gm) dapp.clearInvite(); return; }
  if (gm.nn !== 1) { dapp.clearInvite(); return; }   // not open for a second player (empty or full/finished)
  const stake = BigInt(gm.stake);
  if (!canPay(dapp, stake, "Joining this game")) return;   // keep the invite: it re-fires when the deposit lands
  dapp.clearInvite();
  const G = load(LS_G); G[activeGame] = { role: "o", ts: Date.now() }; save(LS_G, G);
  dapp.call("join", [activeGame], stake, "join tic-tac-toe #" + activeGame + " · " + rawToNado(stake) + " NADO stake", { game: activeGame, phase: "join" });
}
function moveCell(i) {
  const gm = lastGame; if (!gm || gm.sd || gm.turnAddr !== dapp.me || gm.board[i] !== 0) return;
  pendingCell = i; render();
  // ply-bound so a stale wallet retry can never land turns later (the chess lesson)
  dapp.call("move", [activeGame, i, gm.mc], null,
    (gm.mc % 2 === 0 ? "✕" : "◯") + " on cell " + (i + 1) + " · game #" + activeGame,
    { game: activeGame, phase: "move", cell: i, ply: gm.mc });
}
const resignGame = () => dapp.call("resign", [activeGame], null, "resign game #" + activeGame, { game: activeGame, phase: "resign" }, { confirm: 1 });
const abortGame = () => dapp.call("abort", [activeGame], null, "refund a stalled game #" + activeGame, { game: activeGame, phase: "abort" });
const cancelGame = () => dapp.call("cancel", [activeGame], null, "cancel game #" + activeGame, { game: activeGame, phase: "cancel" });

// ---- refresh ---------------------------------------------------------------------------------------
async function refreshAll() {
  await dapp.refresh();
  const sto = await dapp.storage();
  if (sto) {
    lastSto = sto;
    lsPrune(LS_G, Object.keys(_m(sto, "p1")));
    if (activeGame != null) {
      lastGame = gameFrom(sto, activeGame);
      if (pendingCell != null && lastGame.exists && lastGame.board[pendingCell] !== 0) pendingCell = null;
    }
    if (watch) {
      const g = String(watch.game);
      const done =
        watch.phase === "open" ? !!_m(sto, "p1")[g] :
        watch.phase === "join" ? (_m(sto, "nn")[g] || 0) === 2 :
        watch.phase === "move" ? (_m(sto, "mc")[g] || 0) > watch.ply :
        !!_m(sto, "sd")[g];
      if (done) {
        $("status").textContent = { open: "✓ Game is on-chain — send your opponent the invite below.",
          join: "✓ You're in — X moves first.", move: "✓ Move landed.",
          resign: "✓ Resigned.", abort: "✓ Refunded.", cancel: "✓ Cancelled — stake refunded." }[watch.phase];
        watch = null;
      } else if (watch.ts && Date.now() - watch.ts > 75000) {
        $("status").textContent = "Still settling on-chain — your move and funds are safe; the board updates by itself.";
        watch = null;
      }
    }
    renderLobby(sto);
    renderScore($("scoreList"), boardFrom(sto), dapp.me, "No finished games yet — open the first challenge.");
    const gm = lastGame || {};
    await resolveAliases([dapp.me, gm.p1, gm.p2].filter(Boolean));
  }
  render();
}
function boardFrom(sto) {
  const stats = {};
  for (const g of Object.keys(_m(sto, "p1"))) {
    if (!_m(sto, "sd")[g]) continue;
    const wr = _m(sto, "wr")[g] || 0, st = _m(sto, "st")[g] || 0;
    const p1 = _m(sto, "p1")[g], p2 = _m(sto, "p2")[g];
    if (!p2 || !wr || wr === 3) continue;                    // cancelled / draw / void games don't rank
    scoreBump(stats, wr === 1 ? p1 : p2, st);
    scoreBump(stats, wr === 1 ? p2 : p1, -st);
  }
  return scoreSort(stats);
}
function renderLobby(sto) {
  const el = $("lobbyList");
  const open = Object.keys(_m(sto, "p1")).map((g) => gameFrom(sto, g))
    .filter((g) => g.exists && g.nn === 1 && !g.sd).sort((a, b) => b.id - a.id);
  el.innerHTML = open.length ? open.slice(0, 24).map((g) =>
    '<button class="chip betting" data-g="' + g.id + '">⭕ #' + g.id + " · stake " + rawToNado(g.stake) + " · by " + disp(g.p1) + "</button>").join(" ")
    : '<span class="dim">No open challenges — start one below.</span>';
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => { activeGame = parseInt(b.dataset.g, 10); refreshAll(); });
}

// ---- render ----------------------------------------------------------------------------------------
function render() {
  dapp.reflectUrl("game", activeGame);   // address bar = the shareable link to the selected game
  dapp.syncPctSlider("stake", { slider: "stakeSlider", input: "stakeAmt" }, dapp.exec);
  const signedIn = renderWallet(dapp);
  gate({ opencard: signedIn, bankroll: signedIn, activeGame: activeGame != null });
  const G = load(LS_G);
  const mine = Object.keys(G).map((g) => ({ id: +g, ts: G[g].ts, icon: GICON, live: !!(lastSto && _m(lastSto, "p1")[g]) }))
    .sort((a, b) => b.ts - a.ts).slice(0, 8);
  for (const x of mine) {
    if (!x.live || !lastSto) continue;
    const gm = gameFrom(lastSto, x.id);
    x.tag = gm.sd ? "finished ✓" : gm.nn === 1 ? "waiting" : gm.turnAddr === dapp.me ? "YOUR MOVE" : "their move";
  }
  recentChips($("recent"), mine, (id) => { activeGame = id; refreshAll(); }, "");
  if (activeGame == null) return;
  const gm = lastGame || {};
  $("gameId").textContent = "#" + activeGame;
  shareInvite("game", activeGame, "Beat me at tic-tac-toe for " + (gm.exists ? rawToNado(gm.stake) : "") + " NADO on NADO:", 180);
  if (!gm.exists) {
    $("verdict").textContent = dapp.whereIs("game", activeGame, (G[activeGame] || {}).ts);
    $("board").innerHTML = ""; $("gPot").textContent = "—"; $("gPlayers").textContent = "—"; $("gameActions").innerHTML = ""; return;
  }
  const meX = gm.p1 === dapp.me, meO = gm.p2 === dapp.me, playing = meX || meO;
  $("gPot").textContent = rawToNado(gm.pot || (gm.sd ? 0 : gm.stake)) + " NADO";
  $("gPlayers").innerHTML = '<span style="color:var(--accent2)">✕ ' + disp(gm.p1) + (meX ? " (you)" : "") + "</span> vs " +
    (gm.p2 ? '<span style="color:var(--gold)">◯ ' + disp(gm.p2) + (meO ? " (you)" : "") + "</span>" : '<span class="dim">waiting…</span>');
  // verdict line
  let v = "";
  if (gm.sd) v = gm.wr === 3 ? "🤝 Draw — both stakes refunded." : (gm.wr === 1 ? "✕" : "◯") + " wins the pot!" +
      ((gm.wr === 1 && meX) || (gm.wr === 2 && meO) ? " 🏆 That's you!" : "");
  else if (gm.nn === 1) v = meX ? "Waiting for an opponent — share the invite below." : "Open challenge — join below!";
  else if (gm.turnAddr === dapp.me) v = '<span class="yourturn">▶ YOUR MOVE — tap a cell</span>';
  else v = "Waiting for " + disp(gm.turnAddr) + " to move…";
  $("verdict").innerHTML = v;
  // the board
  const marks = ["", "✕", "◯"], cls = ["", "x", "o"];
  $("board").innerHTML = gm.board.map((c, i) => {
    const winCell = gm.winLine && gm.winLine.includes(i);
    const pend = pendingCell === i && c === 0;
    return '<div class="cell ' + cls[c] + (winCell ? " win" : "") + (c || gm.sd || gm.turnAddr !== dapp.me ? " dead" : "") + (pend ? " pend" : "") +
      '" data-c="' + i + '">' + (pend ? marks[gm.mc % 2 + 1] : marks[c]) + "</div>";
  }).join("");
  $("board").querySelectorAll(".cell").forEach((el) => el.onclick = () => moveCell(parseInt(el.dataset.c, 10)));
  // actions
  const wrap = $("gameActions"); wrap.innerHTML = "";
  if (gm.sd && dapp.me) { const rb = document.createElement("button"); rb.className = "primary"; rb.style.flex = "1 1 auto";
    rb.textContent = "↻ Play again — new game at " + rawToNado(gm.stake) + " NADO"; rb.onclick = () => rematch(gm.stake); wrap.appendChild(rb); }
  const btn = (txt, fn, primary, pulse) => { const b = document.createElement("button"); b.className = (primary ? "primary" : "ghost") + (pulse ? " pulse" : ""); b.style.flex = "1 1 auto"; b.textContent = txt; b.onclick = fn; wrap.appendChild(b); return b; };
  if (!gm.sd && dapp.me) {
    if (gm.nn === 1 && !playing) btn("⭕ Join — stake " + rawToNado(gm.stake) + " NADO", joinGame, true, true);
    if (gm.nn === 1 && meX) btn("Cancel — refund my stake", cancelGame, false);
    if (gm.nn === 2 && playing) btn("🏳 Resign — concede the pot", resignGame, false);
    if (gm.nn === 2 && dapp.cursor != null && dapp.cursor > gm.dl)
      btn("⏰ Opponent timed out — refund both stakes", abortGame, true);
    else if (gm.nn === 2 && dapp.cursor != null && gm.turnAddr !== dapp.me && playing)
      wrap.insertAdjacentHTML("beforeend", '<div class="small dim" style="flex:1 1 100%">move clock: refundable in ' + blocksToTime(gm.dl - dapp.cursor) + " if they stall</div>");
  }
}

function rematch(stakeRaw) {
  if (!canPay(dapp, BigInt(stakeRaw), "A rematch")) return;
  const g = randId(); const G = load(LS_G); G[g] = { role: "x", ts: Date.now() }; save(LS_G, G);
  activeGame = g; pendingCell = null;
  dapp.call("open", [g], BigInt(stakeRaw), "rematch tic-tac-toe #" + g + " · stake " + rawToNado(stakeRaw) + " NADO", { game: g, phase: "open" });
}
// ---- boot ------------------------------------------------------------------------------------------
const replayInvite = async (id) => {   // load the invited game FIRST so joinGame's lastGame check isn't stale
  activeGame = parseInt(id, 10);
  const sto = await dapp.storage(); if (sto) lastGame = gameFrom(sto, activeGame);
  joinGame();
};
dapp.onReturn((pend, ok, err) => {
  if (pend && pend.game != null) activeGame = pend.game;
  if (ok && pend && (pend.phase === "connect" || pend.phase === "deposit")) dapp.consumeInvite(replayInvite);
  if (!ok) pendingCell = null;
  if (ok && pend && ["open", "join", "move", "resign", "abort", "cancel"].includes(pend.phase)) watch = Object.assign({}, pend, { ts: Date.now() });
  $("status").textContent = statusLabel(pend, ok, err, {
    open: "Opening the game — confirming…", join: "Joining — confirming…", move: "Move sent — landing in the next block…",
    resign: "Resigning…", abort: "Refunding…", cancel: "Cancelling…" });
});
function wireUI() {
  wireWallet(dapp);
  dapp.wirePctSlider("stake", { slider: "stakeSlider", input: "stakeAmt" }, () => dapp.exec, render);   // play for stakes: % of your playable balance
  stickyInputs(dapp, ['stakeAmt', 'bankAmt']);   // typed amounts persist across turns
  $("btnNewGame").onclick = newGame;
}
async function boot() {
  try { await dapp.init(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload."; return; }
  wireUI(); loadQR();
  orderCards(["activeGame", "lobby", "opencard", "walletcard", "bankroll", "scoreboard"]);
  const q = new URLSearchParams(location.search).get("game");
  if (q) {
    activeGame = parseInt(q, 10);
    if (!dapp.me) { const sto = await dapp.storage(); const gm = sto ? gameFrom(sto, activeGame) : null;
      inviteGate(dapp, { id: activeGame, title: "You're invited to tic-tac-toe",
        body: gm && gm.exists ? ("Play " + disp(gm.p1) + " for <b>" + rawToNado(gm.stake) + " NADO</b> — winner takes the pot.") : "Sign in to join this game.",
        joinLabel: "Sign in & join" }); }
  }
  if (dapp.me) dapp.consumeInvite(replayInvite);   // signed in with a pending invite (e.g. reloaded mid-deposit) → auto-join
  render(); refreshAll();
  setInterval(refreshAll, 3000);
}
boot();
