// chess.js — NADO Chess: a wager game of chess on the execution layer, built on the shared SDK (nadodapp.js)
// and a perft-verified, dependency-free chess engine (chess-engine.js). Two players stake equally; the board +
// full legality run in your browser; every move is recorded ON-CHAIN (a trustless, ordered game log with a move
// clock), and the wager settles by resignation / mutual agreement / refund-on-timeout — so nobody can ever be
// robbed (a stall or a disputed move at worst refunds both). Correspondence-style: a move confirms in ~1 min.
import { NadoDapp, rawToNado, nadoToRaw, randId, _m, $, base, hoist, resolveAliases, disp, share } from "./nadodapp.js";
import { Chess } from "./chess-engine.js";

const CID = "a17c85c704d18e5527fd833843c37295";
const dapp = new NadoDapp({ cid: CID, app: "Chess" });
const LS_G = "nado_chess_games";
const load = () => { try { return JSON.parse(localStorage.getItem(LS_G) || "{}"); } catch { return {}; } };
const save = (v) => { try { localStorage.setItem(LS_G, JSON.stringify(v)); } catch {} };
let activeGame = null, lastGame = null, engine = new Chess(), selected = null, pendingEnc = null, flipBoard = false;
let knownGames = new Set();   // game ids that exist on-chain (for "Your games")
function pruneAndTrack(sto) {
  knownGames = new Set(allGids(sto));
  const G = load(); let c = false;
  for (const g of Object.keys(G)) if (!knownGames.has(g) && Date.now() - (G[g].ts || 0) > 600000) { delete G[g]; c = true; }
  if (c) save(G);
}
function reopenGame() {   // retry an open that never landed (same id is still fresh)
  const L = load()[activeGame]; if (!L || L.role !== "white" || !L.stake) return;
  const raw = BigInt(L.stake);
  if (dapp.exec < raw) { $("status").textContent = "Deposit first — this stake needs " + rawToNado(raw) + " NADO."; return; }
  dapp.call("open", [activeGame], raw, "open chess game #" + activeGame + " · " + rawToNado(raw) + " NADO stake", { game: activeGame, phase: "open" });
}

// ---- square <-> index <-> move encoding (must match the contract: from + to*64 + promo*4096) -----
const FILES = "abcdefgh";
const sqToIdx = (sq) => (sq.charCodeAt(0) - 97) + (sq.charCodeAt(1) - 49) * 8;    // a1=0 … h8=63
const idxToSq = (i) => FILES[i % 8] + (Math.floor(i / 8) + 1);
const PROMO = [null, "n", "b", "r", "q"];
const encMove = (m) => sqToIdx(m.from) + sqToIdx(m.to) * 64 + (PROMO.indexOf(m.promotion || null) > 0 ? PROMO.indexOf(m.promotion) : 0) * 4096;
function decMove(enc) { const from = enc % 64, to = Math.floor(enc / 64) % 64, pc = Math.floor(enc / 4096);
  return { from: idxToSq(from), to: idxToSq(to), promotion: PROMO[pc] || undefined }; }
// Inline SVG piece silhouettes (viewBox 0 0 45 45), one shape set for BOTH armies — colour is done in CSS
// (.pc.w = light fill / dark outline, .pc.b = dark fill / light outline), so the pieces are crisp and the two
// sides are unmistakable at any size and identical on every OS (Unicode chess glyphs render differently per font).
const SHAPE = {
  p: '<circle cx="22.5" cy="15" r="5.2"/><path d="M14.5 34.5Q16 24 22.5 21.5 29 24 30.5 34.5Z"/>',
  r: '<path d="M13 34.5h19v-3.5h-19z"/><path d="M15.5 31v-11h14v11z"/><path d="M14 20v-6.5h4.2v2.6h3.1v-2.6h2.4v2.6h3.1v-2.6h4.2v6.5z"/>',
  n: '<path d="M17 34.5h14v-3h-14z"/><path d="M24.5 12C20 11.5 16.5 13.5 16 17c-.2 1.5.5 2.5 1.5 3-2 1.5-3 4-2.5 7l3.5-2.5c.5-.2.9.3.7.9-.7 1.6-1.2 3.6-1 5.6l.5 1h12.3c.5-6 0-12.5-3-16-1-1.5-2-2.5-3.5-3z"/>',
  b: '<circle cx="22.5" cy="9" r="2"/><path d="M22.5 11C27 15 28.5 19.5 28.5 22 28.5 25 25.5 26.5 22.5 26.5 19.5 26.5 16.5 25 16.5 22 16.5 19.5 18 15 22.5 11Z"/><path d="M14.5 34.5Q16 27.5 22.5 26.5 29 27.5 30.5 34.5Z"/>',
  q: '<path d="M13 34.5Q13.5 22 22.5 22 31.5 22 32 34.5Z"/><path d="M11 23 9 13l6.5 5.5L22.5 9.5l7 9L36 13l-2 10z"/><circle cx="9" cy="13" r="2"/><circle cx="15.5" cy="18.5" r="1.8"/><circle cx="22.5" cy="9.5" r="2"/><circle cx="29.5" cy="18.5" r="1.8"/><circle cx="36" cy="13" r="2"/>',
  k: '<rect x="21.3" y="6.5" width="2.4" height="8" rx=".4"/><rect x="18.6" y="9" width="7.8" height="2.4" rx=".4"/><path d="M13.5 34.5Q12.5 22 22.5 19.5 32.5 22 31.5 34.5Z"/>',
};
const pieceSVG = (type) => '<svg viewBox="0 0 45 45" aria-hidden="true">' + SHAPE[type] + "</svg>";

// ---- reads (chess storage schema) ----------------------------------------------------------------
const allGids = (sto) => Object.keys(_m(sto, "nn"));
function movesOf(sto, g) { const mv = _m(sto, "mv"), mc = _m(sto, "mc")[g] || 0, out = [];
  for (let i = 0; i < mc; i++) { const e = mv[String(Number(g) * 10000 + i)]; if (e) out.push(decMove(e)); } return out; }
function gameFrom(sto, g) {
  g = String(g); const nn = _m(sto, "nn")[g] || 0;
  if (!nn) return { exists: false };
  return { exists: true, id: Number(g), white: _m(sto, "p1")[g], black: _m(sto, "p2")[g],
    stake: _m(sto, "st")[g] || 0, pot: _m(sto, "pt")[g] || 0, nn, settled: !!_m(sto, "sd")[g],
    deadline: _m(sto, "dl")[g] || 0, mc: _m(sto, "mc")[g] || 0, a1: _m(sto, "a1")[g] || 0, a2: _m(sto, "a2")[g] || 0,
    moves: movesOf(sto, g) };
}
// rebuild the board by replaying the on-chain move log; corrupted (an illegal on-chain move) -> flagged
function rebuildEngine(g) {
  const e = new Chess(); let corrupt = false;
  for (const m of (g.moves || [])) { if (!e.move({ from: m.from, to: m.to, promotion: m.promotion })) { corrupt = true; break; } }
  // optimistic: show my just-submitted move until the chain reflects it
  if (!corrupt && pendingEnc != null && (g.moves || []).length === g.mc) {
    const pm = decMove(pendingEnc);
    if (myTurn(g, e) && e.move({ from: pm.from, to: pm.to, promotion: pm.promotion })) {} // applied optimistically
  }
  e._corrupt = corrupt; return e;
}
function mySide(g) { return g.white === dapp.me ? "w" : g.black === dapp.me ? "b" : null; }
function myTurn(g, e) { const s = mySide(g); return s && e.turn() === s && g.nn === 2 && !g.settled && !e.isGameOver(); }
async function fetchGame(g) { const sto = await dapp.storage(); return sto ? gameFrom(sto, g) : null; }

// ---- actions -------------------------------------------------------------------------------------
function newGame() {
  const raw = nadoToRaw($("stakeAmt").value);
  if (!raw) { $("status").textContent = "Enter a stake (NADO)."; return; }
  if (dapp.exec < raw) { $("status").textContent = "Deposit first — your exec balance is " + rawToNado(dapp.exec) + " NADO."; return; }
  const g = randId(), G = load(); G[g] = { role: "white", stake: raw.toString(), ts: Date.now() }; save(G);
  activeGame = g; pendingEnc = null; render();
  dapp.call("open", [g], raw, "open chess game #" + g + " · " + rawToNado(raw) + " NADO stake", { game: g, phase: "open" });
}
async function joinGame() {
  const g = parseInt($("joinId").value, 10);
  if (!g) { $("status").textContent = "Enter a game ID (or pick one from the lobby)."; return; }
  const gm = await fetchGame(g);
  if (!gm || !gm.exists) { $("status").textContent = "No such game yet — ask your opponent for the ID."; return; }
  if (gm.nn >= 2 || gm.settled) { $("status").textContent = "That game is full or finished."; return; }
  await dapp.refresh();
  const stake = BigInt(gm.stake);
  if (dapp.exec < stake) { $("status").textContent = "You need " + rawToNado(stake) + " NADO to match the stake (you have " + rawToNado(dapp.exec) + "). Deposit first."; render(); return; }
  const G = load(); G[g] = { role: "black", stake: stake.toString(), ts: Date.now() }; save(G);
  activeGame = g; pendingEnc = null; render();
  dapp.call("join", [g], stake, "join chess game #" + g + " · " + rawToNado(stake) + " NADO stake", { game: g, phase: "join" });
}
function submitMove(m) {
  const enc = encMove(m);
  pendingEnc = enc; selected = null; render();
  dapp.call("move", [activeGame, enc], null, "move " + m.from + m.to + (m.promotion ? "=" + m.promotion.toUpperCase() : "") + " · game #" + activeGame, { game: activeGame, phase: "move" });
}
const resignGame = () => dapp.call("resign", [activeGame], null, "resign game #" + activeGame, { game: activeGame, phase: "resign" });
const agree = (r) => dapp.call("agree", [activeGame, r], null, (r === 3 ? "agree a draw" : "confirm the result") + " · game #" + activeGame, { game: activeGame, phase: "agree" });
const abortGame = () => dapp.call("abort", [activeGame], null, "claim refund (opponent timed out) · game #" + activeGame, { game: activeGame, phase: "abort" });
const cancelGame = () => dapp.call("cancel", [activeGame], null, "cancel game #" + activeGame, { game: activeGame, phase: "cancel" });

async function refreshActive() {
  await dapp.refresh();
  const sto = await dapp.storage();
  if (sto) {
    pruneAndTrack(sto);
    if (activeGame != null) {
      lastGame = gameFrom(sto, activeGame);
      if (pendingEnc != null && lastGame.moves.length >= lastGame.mc && lastGame.moves.some((m) => encMove(m) === pendingEnc)) pendingEnc = null;
      engine = rebuildEngine(lastGame);
    }
    renderLobby(sto);
  }
  await resolveAliases([dapp.me].concat(lastGame ? [lastGame.white, lastGame.black] : []));
  render();
}
function renderLobby(sto) {
  const el = $("lobbyList"); if (!el) return;
  const games = allGids(sto).map((g) => gameFrom(sto, g)).filter((g) => g.exists && !g.settled);
  games.sort((a, b) => (a.nn - b.nn) || (b.id - a.id));
  const shown = games.slice(0, 24);
  el.innerHTML = shown.length ? shown.map((g) => {
    const stage = g.nn < 2 ? "open" : "live", verb = g.nn < 2 ? " · join" : " · watch";
    return '<button class="chip ' + stage + '" data-g="' + g.id + '">' + (g.nn < 2 ? "♙" : "▶") + " #" + g.id + " · " + rawToNado(g.stake) + " NADO" + verb + "</button>";
  }).join(" ") : '<span class="dim">No games yet — open one above.</span>';
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => { activeGame = parseInt(b.dataset.g, 10); pendingEnc = null; $("joinId").value = b.dataset.g;
    $("status").textContent = "Game #" + activeGame + " selected."; refreshActive(); try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {} });
}

// ---- board rendering + interaction ---------------------------------------------------------------
function onSquareClick(sq) {
  const g = lastGame; if (!g || !g.exists) return;
  if (!myTurn(g, engine)) { $("status").textContent = engine.isGameOver() ? "The game is over." : "Not your turn yet."; return; }
  const piece = engine.get(sq);
  if (selected) {
    const legal = engine.moves({ square: selected }).filter((m) => m.to === sq);
    if (legal.length) {
      let m = legal[0];
      if (legal.length > 1 && legal[0].promotion) {  // promotion — ask which piece
        const want = (prompt("Promote to (q, r, b, n)?", "q") || "q").toLowerCase();
        m = legal.find((x) => x.promotion === want) || legal.find((x) => x.promotion === "q") || legal[0];
      }
      submitMove(m); return;
    }
  }
  selected = (piece && piece.color === mySide(g)) ? sq : null;
  renderBoard();
}
function renderBoard() {
  const wrap = $("board"); if (!wrap) return;
  const g = lastGame || {};
  const side = mySide(g), flip = flipBoard || side === "b";   // black sees the board from their side
  const board = engine.board();   // 8x8, [0][0] = a8
  const legalTargets = selected ? new Set(engine.moves({ square: selected }).map((m) => m.to)) : new Set();
  const lastMv = (g.moves && g.moves.length) ? g.moves[g.moves.length - 1] : null;
  let html = "";
  const ranks = flip ? [...Array(8).keys()] : [...Array(8).keys()].reverse();   // display order of ranks (idx into board rows: row0=rank8)
  // board[r][c]: r=0 -> rank8, c=0 -> file a. We iterate display rows/cols.
  const rows = flip ? [7,6,5,4,3,2,1,0] : [0,1,2,3,4,5,6,7];      // board row indices top->bottom of display
  const cols = flip ? [7,6,5,4,3,2,1,0] : [0,1,2,3,4,5,6,7];
  for (const r of rows) for (const c of cols) {
    const sq = FILES[c] + (8 - r);            // board row r is rank (8-r)
    const p = board[r][c];
    const dark = (r + c) % 2 === 1;
    const cls = ["sq", dark ? "dark" : "light"];
    if (sq === selected) cls.push("sel");
    if (legalTargets.has(sq)) cls.push(p ? "capture" : "target");
    if (lastMv && (sq === lastMv.from || sq === lastMv.to)) cls.push("last");
    if (p && p.type === "k" && p.color === engine.turn() && engine.inCheck()) cls.push("check");
    html += '<div class="' + cls.join(" ") + '" data-sq="' + sq + '">' + (p ? '<span class="pc ' + p.color + '">' + pieceSVG(p.type) + "</span>" : "") + "</div>";
  }
  wrap.innerHTML = html;
  wrap.querySelectorAll(".sq").forEach((el) => el.onclick = () => onSquareClick(el.dataset.sq));
}

// ---- render --------------------------------------------------------------------------------------
function wireUI() {
  $("btnSignIn").onclick = () => dapp.signIn();
  $("btnDeposit").onclick = () => { const raw = nadoToRaw($("bankAmt").value); if (!raw) return ($("status").textContent = "Enter an amount to deposit."); if (raw + 1000n > dapp.l1) return ($("status").textContent = "Not enough in your L1 wallet (" + rawToNado(dapp.l1) + " NADO)."); dapp.deposit(raw); };
  $("btnWithdraw").onclick = () => { const raw = nadoToRaw($("bankAmt").value); if (!raw) return ($("status").textContent = "Enter an amount to withdraw."); if (dapp.exec < raw) return ($("status").textContent = "You only have " + rawToNado(dapp.exec) + " NADO in the exec layer."); dapp.withdraw(raw); };
  $("btnNew").onclick = newGame;
  $("btnJoin").onclick = joinGame;
  $("joinId").oninput = () => render();
  $("btnResign").onclick = resignGame;
  $("btnDraw").onclick = () => agree(3);
  $("btnSettle").onclick = () => { const r = resultCode(); if (r) agree(r); };
  $("btnAbort").onclick = abortGame;
  $("btnCancel").onclick = cancelGame;
  $("btnReopen").onclick = reopenGame;
  $("btnFlip").onclick = () => { flipBoard = !flipBoard; renderBoard(); };
  $("btnShare").onclick = () => share(base() + "/?game=" + activeGame, "Play me at chess for " + (lastGame && lastGame.exists ? rawToNado(lastGame.stake) + " NADO " : "") + "on NADO — game #" + activeGame + ":", $("btnShare"));
}
function resultCode() {   // 1=white wins, 2=black wins, 3=draw ; null if not over
  if (!engine.isGameOver()) return null;
  if (engine.isCheckmate()) return engine.turn() === "w" ? 2 : 1;   // side to move is mated -> other side wins
  return 3;   // stalemate / draw
}
function render() {
  const signedIn = !!dapp.me;
  $("btnSignIn").classList.toggle("hidden", signedIn);
  $("who").textContent = signedIn ? disp(dapp.me) : "not signed in";
  $("bal").textContent = rawToNado(dapp.exec) + " NADO";
  $("l1bal").textContent = rawToNado(dapp.l1) + " NADO";
  $("play").classList.toggle("hidden", !signedIn);
  $("bankroll").classList.toggle("hidden", !signedIn);
  // my recent games
  const G = load(), ids = Object.keys(G).sort((a, b) => G[b].ts - G[a].ts).slice(0, 8);   // keep every game visible (landed OR confirming)
  $("recent").innerHTML = ids.length ? ids.map((g) => { const live = knownGames.has(String(g)); return '<button class="chip' + (live ? "" : " pending") + '" data-g="' + g + '"' + (live ? "" : ' title="still confirming on-chain — your game hasn\'t vanished"') + '>' + (G[g].role === "white" ? "♔" : "♚") + " #" + g + (live ? "" : " ⏳") + "</button>"; }).join(" ") : '<span class="dim">No games yet.</span>';
  $("recent").querySelectorAll(".chip").forEach((b) => b.onclick = () => { activeGame = parseInt(b.dataset.g, 10); pendingEnc = null; refreshActive(); });
  renderActive();
}
function renderActive() {
  const box = $("activeGame");
  if (activeGame == null) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  const g = lastGame || {}, local = load()[activeGame] || {}, side = mySide(g);
  $("gameId").textContent = "#" + activeGame;
  $("shareLink").value = base() + "/?game=" + activeGame;
  $("gPot").textContent = g.exists ? rawToNado(g.pot) + " NADO" : (local.stake ? rawToNado(BigInt(local.stake) * 2n) + " NADO" : "—");
  const wName = g.white ? disp(g.white) + (g.white === dapp.me ? " (you)" : "") : "—";
  const bName = g.black ? disp(g.black) + (g.black === dapp.me ? " (you)" : "") : "waiting…";
  $("players").innerHTML = '<span class="chip">♔ ' + wName + '</span> <span class="chip">♚ ' + bName + "</span>";
  renderBoard();
  // status line
  let st = "opening…";
  const over = g.exists && g.nn === 2 && engine.isGameOver();
  const rc = resultCode();
  if (g.exists && g.settled) st = "✓ settled";
  else if (g.exists && engine._corrupt) st = "⚠ an illegal move reached the chain — this game will refund after the timeout.";
  else if (g.exists && g.nn < 2) st = local.role === "white" ? "waiting for an opponent to join…" : "opening…";
  else if (over) st = engine.isCheckmate() ? ("Checkmate — " + (rc === 1 ? "White" : "Black") + " wins") : engine.isStalemate() ? "Stalemate — draw" : "Draw";
  else if (g.exists) st = (engine.turn() === "w" ? "White" : "Black") + " to move" + (engine.inCheck() ? " · CHECK" : "") + (myTurn(g, engine) ? " — your move" : (pendingEnc != null ? " · your move is confirming (~1 min)…" : " — waiting for opponent (~1 min)"));
  $("gStatus").textContent = st;
  $("btnReopen").classList.toggle("hidden", !(local.role === "white" && local.stake && !g.exists && local.ts && Date.now() - local.ts > 120000));
  // buttons
  const iAmIn = side != null, live = g.exists && g.nn === 2 && !g.settled;
  const iAmWinner = over && ((rc === 1 && side === "w") || (rc === 2 && side === "b"));
  const iAmLoser = over && ((rc === 2 && side === "w") || (rc === 1 && side === "b"));
  $("btnResign").classList.toggle("hidden", !(live && iAmIn && !over));
  $("btnDraw").classList.toggle("hidden", !(live && iAmIn && !over));          // offer/accept a draw (both must agree)
  // settle: on a decisive result the LOSER resigns (pays the winner); on a draw both agree
  $("btnSettle").classList.toggle("hidden", !(live && iAmIn && over && rc === 3));
  $("btnSettle").textContent = "Agree draw (refund both)";
  if (live && iAmIn && over && rc !== 3) {   // decisive: loser concedes via resign to pay the winner
    $("btnResign").classList.remove("hidden");
    $("btnResign").textContent = iAmLoser ? "Concede — pay out the winner" : "Resign";
  } else $("btnResign").textContent = "Resign";
  // abort (refund) once the opponent has blown the move clock
  const pastDeadline = live && dapp.cursor != null && dapp.cursor > g.deadline;
  $("btnAbort").classList.toggle("hidden", !(iAmIn && pastDeadline));
  $("btnCancel").classList.toggle("hidden", !(g.exists && g.nn === 1 && side === "w" && !g.settled));
  $("btnFlip").classList.toggle("hidden", !g.exists);
  // agreement progress hint
  const agreed = (g.a1 || g.a2) ? " · agreements: " + (g.a1 ? "White=" + ["","W","B","draw"][g.a1] : "") + " " + (g.a2 ? "Black=" + ["","W","B","draw"][g.a2] : "") : "";
  $("settleHint").textContent = over && !g.settled
    ? (rc === 3 ? "It's a draw — both players agree to refund." : (iAmWinner ? "You won! Waiting for your opponent to concede (or claim a refund after the timeout)." : iAmLoser ? "You're beaten — concede to pay out the winner." : "")) + agreed
    : "";
}

// ---- boot ----------------------------------------------------------------------------------------
dapp.onReturn((pend, ok, err) => {
  const label = { connect: "Signed in.", deposit: "Deposit submitted — confirming…", open: "Game opening — confirming…",
    join: "Joining — confirming…", move: "Move submitted — confirming on-chain (~1 min)…", resign: "Resigning…",
    agree: "Submitting…", abort: "Claiming refund…", cancel: "Cancelling…", withdraw: "Withdrawal submitted." }[pend && pend.phase] || "Submitted.";
  if (pend && pend.game != null) activeGame = pend.game;
  if (!ok) pendingEnc = null;   // a rejected move must not linger optimistically
  $("status").textContent = ok ? label : "Rejected" + (err ? ": " + err : ".");
});
async function boot() {
  try { await dapp.init(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload."; return; }
  wireUI(); hoist("activeGame");
  const q = new URLSearchParams(location.search).get("game");
  if (q) { $("joinId").value = q; if (activeGame == null) activeGame = parseInt(q, 10); }
  render(); refreshActive();
  setInterval(refreshActive, 3000);
}
boot();
