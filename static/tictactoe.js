// tictactoe.js — NADO Tic-Tac-Toe: staked 3x3 where the CONTRACT is the referee (unlike chess, a 3x3
// board fits in the VM): move() checks turn + free cell ON-CHAIN, detects three-in-a-row and pays the
// pot instantly, and a full board auto-refunds both stakes. Ply-bound moves (the chess retry-race
// lesson), resign/abort escapes, and a short ~30-min move clock. Built on the shared SDK (nadodapp.js).
import { NadoDapp, rawToNado, nadoToRaw, randId, rematchId, _m, $, base, gate, canPay, orderCards, alertBar, notify, okBar, blocksToTime, inviteGate,
         lsLoad as load, lsSave as save, lsPrune, wireWallet, stickyInputs, renderWallet, renderScore, scoreBump, scoreSort,
         recentChips, statusLabel, loadQR, drawQR, resolveAliases, disp, share, shareInvite } from "./nadodapp.js";

const CID = "68f2bf23441437af6655e2eba4a71ba1";
const GICON = "⭕";
const dapp = new NadoDapp({ cid: CID, app: "TicTacToe" });
const WINDOW = 300;
const LINES = [[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]];
const LS_G = "nado_ttt_games";

let lastSto = null, activeGame = null, lastGame = null, watch = null, pendingCell = null;
let lobbyN = 24;   // the lobby is the only discovery path (no go-to-id box), so cap + "Show more" keeps it browsable

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
async function fetchGame(g) { const sto = await dapp.storage(); return sto ? gameFrom(sto, g) : null;
}

// ---- actions ---------------------------------------------------------------------------------------
function newGame() {
  const raw = nadoToRaw($("stakeAmt").value);
  if (!raw) return alertBar(window.t("ttt.enterStake", "Enter your stake in NADO — your opponent matches it, winner takes both."));
  if (!canPay(dapp, raw, window.t("ttt.whatOpen", "Opening this game"))) return;
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
  if (!canPay(dapp, stake, window.t("ttt.whatJoin", "Joining this game"))) return;   // keep the invite: it re-fires when the deposit lands
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
const resignGame = () => dapp.call("resign", [activeGame], null, "resign game #" + activeGame, { game: activeGame, phase: "resign" });   // wallet-policy confirm — chess resign already works this way
const abortGame = () => dapp.call("abort", [activeGame], null, "refund a stalled game #" + activeGame, { game: activeGame, phase: "abort" });
const cancelGame = () => dapp.call("cancel", [activeGame], null, "cancel game #" + activeGame, { game: activeGame, phase: "cancel" });

// ---- refresh ---------------------------------------------------------------------------------------
async function refreshAll() {
  await dapp.refresh();
  dapp.settleInflight();   // SDK: retire the optimistic 'confirming…' status once the action lands
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
        okBar({ open: window.t("ttt.stOpen", "✓ Game is on-chain — send your opponent the invite below."),
          join: window.t("ttt.stJoin", "✓ You're in — X moves first."), move: window.t("ttt.stMove", "✓ Move landed."),
          resign: window.t("ttt.stResign", "✓ Resigned."), abort: window.t("ttt.stAbort", "✓ Refunded."), cancel: window.t("ttt.stCancel", "✓ Cancelled — stake refunded.") }[watch.phase]);
        watch = null;
      } else if (watch.ts && Date.now() - watch.ts > 75000) {
        notify(window.t("ttt.stSettling", "Still settling on-chain — your move and funds are safe; the board updates by itself."));
        watch = null;
      }
    }
    renderLobby(sto);
    renderScore($("scoreList"), boardFrom(sto), dapp.me, window.t("ttt.noFinished", "No finished games yet — open the first challenge."));
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
  el.innerHTML = open.length ? open.slice(0, lobbyN).map((g) =>
    '<button class="chip betting" data-g="' + g.id + '">' + window.t("ttt.lobbyChip", "⭕ #{id} · stake {stake} · by {who}", { id: g.id, stake: rawToNado(g.stake), who: disp(g.p1) }) + "</button>").join(" ")
    : '<span class="dim">' + window.t("ttt.noOpen", "No open challenges — start one below.") + '</span>';
  const bm = $("btnMoreLobby");
  if (bm) {
    bm.classList.toggle("hidden", open.length <= lobbyN);
    if (open.length > lobbyN) bm.textContent = window.t("ttt.showMoreN", "Show more ({n} more)", { n: open.length - lobbyN });
  }
  if (!el._deleg) { el._deleg = true; el.addEventListener("click", (e) => { const b = e.target.closest(".chip"); if (b) { activeGame = parseInt(b.dataset.g, 10); refreshAll(); } }); }
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
    x.tag = gm.sd ? window.t("ttt.tagFinished", "finished ✓") : gm.nn === 1 ? window.t("ttt.tagWaiting", "waiting") : gm.turnAddr === dapp.me ? window.t("ttt.tagYourMove", "YOUR MOVE") : window.t("ttt.tagTheirMove", "their move");
  }
  recentChips($("recent"), mine, (id) => { activeGame = id; refreshAll(); }, "");
  if (activeGame == null) return;
  const gm = lastGame || {};
  $("gameId").textContent = "#" + activeGame;
  shareInvite("game", activeGame, window.t("ttt.shareText", "Beat me at tic-tac-toe for {amt} NADO on NADO:", { amt: gm.exists ? rawToNado(gm.stake) : "" }), 180);
  if (!gm.exists) {
    $("verdict").textContent = dapp.whereIs("game", activeGame, (G[activeGame] || {}).ts);
    $("board").innerHTML = ""; $("gPot").textContent = "—"; $("gPlayers").textContent = "—"; $("gameActions").innerHTML = ""; return;
  }
  const meX = gm.p1 === dapp.me, meO = gm.p2 === dapp.me, playing = meX || meO;
  $("gPot").textContent = rawToNado(gm.pot || (gm.sd ? 0 : gm.stake)) + " NADO";
  const youTag = window.t("ttt.you", " (you)");
  $("gPlayers").innerHTML = '<span style="color:var(--accent2)">✕ ' + disp(gm.p1) + (meX ? youTag : "") + "</span> vs " +
    (gm.p2 ? '<span style="color:var(--gold)">◯ ' + disp(gm.p2) + (meO ? youTag : "") + "</span>" : '<span class="dim">' + window.t("ttt.waitingDots", "waiting…") + '</span>');
  // verdict line
  let v = "";
  if (gm.sd) v = gm.wr === 3 ? window.t("ttt.draw", "🤝 Draw — both stakes refunded.")
      : window.t("ttt.winsPot", "{mark} wins the pot!", { mark: gm.wr === 1 ? "✕" : "◯" }) +
      ((gm.wr === 1 && meX) || (gm.wr === 2 && meO) ? window.t("ttt.thatsYou", " 🏆 That's you!") : "");
  else if (gm.nn === 1) v = meX ? window.t("ttt.waitOpponent", "Waiting for an opponent — share the invite below.") : window.t("ttt.openJoin", "Open challenge — join below!");
  else if (gm.turnAddr === dapp.me) v = '<span class="yourturn">' + window.t("ttt.yourMove", "▶ YOUR MOVE — tap a cell") + '</span>';
  else v = window.t("ttt.waitingFor", "Waiting for {who} to move…", { who: disp(gm.turnAddr) });
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
    rb.textContent = window.t("ttt.playAgain", "↻ Play again — new game at {stake} NADO", { stake: rawToNado(gm.stake) }); rb.onclick = () => rematch(gm.stake); wrap.appendChild(rb); }
  const btn = (txt, fn, primary, pulse) => { const b = document.createElement("button"); b.className = (primary ? "primary" : "ghost") + (pulse ? " pulse" : ""); b.style.flex = "1 1 auto"; b.textContent = txt; b.onclick = fn; wrap.appendChild(b); return b; };
  if (!gm.sd && dapp.me) {
    if (gm.nn === 1 && !playing) btn(window.t("ttt.joinStake", "⭕ Join — stake {stake} NADO", { stake: rawToNado(gm.stake) }), joinGame, true, true);
    if (gm.nn === 1 && meX) btn(window.t("ttt.cancelRefund", "Cancel — refund my stake"), cancelGame, false);
    if (gm.nn === 2 && playing) btn(window.t("ttt.resignConcede", "🏳 Resign — concede the pot"), resignGame, false);
    if (gm.nn === 2 && dapp.cursor != null && dapp.cursor > gm.dl)
      btn(window.t("ttt.opponentTimedOut", "⏰ Opponent timed out — refund both stakes"), abortGame, true);
    else if (gm.nn === 2 && dapp.cursor != null && gm.turnAddr !== dapp.me && playing)
      wrap.insertAdjacentHTML("beforeend", '<div class="small dim" style="flex:1 1 100%">' + window.t("ttt.moveClock", "move clock: refundable in {t} if they stall", { t: blocksToTime(gm.dl - dapp.cursor) }) + "</div>");
  }
}

async function rematch(stakeRaw) {
  const stake = BigInt(stakeRaw);
  if (!canPay(dapp, stake, window.t("ttt.whatRematch", "A rematch"))) return;
  // DETERMINISTIC rematch: both players derive the SAME next-game id from the finished one, so they land in
  // ONE shared game — whoever taps first OPENS it, the other JOINS it (never two colliding games).
  const rid = rematchId(activeGame), rg = await fetchGame(rid);
  activeGame = rid; pendingCell = null;
  const G = load(LS_G);
  if (rg && rg.exists && rg.nn === 1 && !rg.sd) {
    G[rid] = { role: "o", ts: Date.now() }; save(LS_G, G);
    dapp.call("join", [rid], stake, "join rematch tic-tac-toe #" + rid + " · " + rawToNado(stake) + " NADO stake", { game: rid, phase: "join" });
  } else {
    G[rid] = { role: "x", ts: Date.now() }; save(LS_G, G);
    dapp.call("open", [rid], stake, "rematch tic-tac-toe #" + rid + " · stake " + rawToNado(stake) + " NADO", { game: rid, phase: "open" });
  }
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
  dapp.showReturn(pend, ok, err, {
    open: "Opening the game — confirming…", join: "Joining — confirming…", move: "Move sent — landing in the next block…",
    resign: "Resigning…", abort: "Refunding…", cancel: "Cancelling…" });
});
function wireUI() {
  wireWallet(dapp);
  dapp.wirePctSlider("stake", { slider: "stakeSlider", input: "stakeAmt" }, () => dapp.exec, render);   // play for stakes: % of your playable balance
  stickyInputs(dapp, ['stakeAmt', 'bankAmt']);   // typed amounts persist across turns
  $("btnNewGame").onclick = newGame;
  if ($("btnMoreLobby")) $("btnMoreLobby").onclick = () => { lobbyN += 48; if (lastSto) renderLobby(lastSto); };
}
async function boot() {
  try { await dapp.init(); } catch (e) { alertBar(window.t("ttt.cryptoFail", "Crypto bundle failed to load — reload.")); return; }
  wireUI(); loadQR();
  orderCards(["activeGame", "lobby", "opencard", "walletcard", "bankroll", "scoreboard"]);
  const q = new URLSearchParams(location.search).get("game");
  if (q) {
    activeGame = parseInt(q, 10);
    if (!dapp.me) { const sto = await dapp.storage(); const gm = sto ? gameFrom(sto, activeGame) : null;
      inviteGate(dapp, { id: activeGame, title: window.t("ttt.inviteTitle", "You're invited to tic-tac-toe"),
        body: gm && gm.exists ? window.t("ttt.inviteBody", "Play {who} for <b>{amt} NADO</b> — winner takes the pot.", { who: disp(gm.p1), amt: rawToNado(gm.stake) }) : window.t("ttt.inviteBodyGeneric", "Sign in to join this game."),
        joinLabel: window.t("ttt.inviteJoin", "Sign in & join") }); }
  }
  if (dapp.me) dapp.consumeInvite(replayInvite);   // signed in with a pending invite (e.g. reloaded mid-deposit) → auto-join
  render(); refreshAll();
  setInterval(refreshAll, 3000);
}
boot();
