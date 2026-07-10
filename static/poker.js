// poker.js — NADO Poker: heads-up 5-card poker SHOWDOWN for stakes on the execution layer, built on the shared
// SDK (nadodapp.js) and a verified poker engine (poker-engine.js). Both players stake and commit a secret;
// once both reveal, both browsers derive the SAME shuffled deck from HASH(s1+s2) and deal 5 cards each — nobody
// can pick their hand. The best hand wins; the pot settles by concede / mutual-agree / refund-timeout, so a
// stall or dispute can only refund, never mis-pay. Ordinary upgradable stackvm contract, no game-specific API.
import { NadoDapp, rawToNado, nadoToRaw, randId, randSecret, commitHashOf, blake2bHash, _m, $, base, resolveAliases, disp, share } from "./nadodapp.js";
import { dealHeadsUp, evalHand, compareHands, handName, cardStr } from "./poker-engine.js";

const CID = "167b7ff631fbeb53c74c5123412d13cb";
const dapp = new NadoDapp({ cid: CID, app: "Poker" });
const LS_G = "nado_poker_games";
const load = () => { try { return JSON.parse(localStorage.getItem(LS_G) || "{}"); } catch { return {}; } };
const save = (v) => { try { localStorage.setItem(LS_G, JSON.stringify(v)); } catch {} };
let activeGame = null, lastGame = null;
let knownGames = new Set();   // game ids that exist on-chain (for "Your games")
function pruneAndTrack(sto) {
  knownGames = new Set(allGids(sto));
  const G = load(); let c = false;
  for (const g of Object.keys(G)) if (!knownGames.has(g) && Date.now() - (G[g].ts || 0) > 600000) { delete G[g]; c = true; }
  if (c) save(G);
}
function reopenGame() {   // retry an open that never landed (same id is still fresh)
  const L = load()[activeGame]; if (!L || L.role !== "p1" || !L.stake || !L.secret) return;
  const raw = BigInt(L.stake);
  if (dapp.exec < raw) { $("status").textContent = "Deposit first — this stake needs " + rawToNado(raw) + " NADO."; return; }
  dapp.call("open", [activeGame, commitHashOf(BigInt(L.secret))], raw, "open poker game #" + activeGame + " · " + rawToNado(raw) + " NADO", { game: activeGame, phase: "bet" });
}

// ---- reads (poker storage schema) ----------------------------------------------------------------
const allGids = (sto) => Object.keys(_m(sto, "nn"));
function gameFrom(sto, g) {
  g = String(g); const nn = _m(sto, "nn")[g] || 0;
  if (!nn) return { exists: false };
  const r1 = _m(sto, "r1")[g] ? 1 : 0, r2 = _m(sto, "r2")[g] ? 1 : 0;
  const gm = { exists: true, id: Number(g), p1: _m(sto, "p1")[g], p2: _m(sto, "p2")[g], r1, r2,
    stake: _m(sto, "st")[g] || 0, pot: _m(sto, "pt")[g] || 0, nn, settled: !!_m(sto, "sd")[g],
    deadline: _m(sto, "dl")[g] || 0, a1: _m(sto, "a1")[g] || 0, a2: _m(sto, "a2")[g] || 0,
    s1: _m(sto, "s1")[g], s2: _m(sto, "s2")[g] };
  if (r1 && r2 && gm.s1 != null && gm.s2 != null) {
    const seed = blake2bHash((BigInt(gm.s1) + BigInt(gm.s2)).toString());
    const deal = dealHeadsUp(seed);
    gm.handP1 = deal.a; gm.handP2 = deal.b;
    const cmp = compareHands(deal.a, deal.b);
    gm.winner = cmp > 0 ? 1 : cmp < 0 ? 2 : 3;   // 1=p1, 2=p2, 3=tie
    gm.nameP1 = handName(deal.a); gm.nameP2 = handName(deal.b);
  }
  return gm;
}
function mySlot(g) { return g.p1 === dapp.me ? 1 : g.p2 === dapp.me ? 2 : 0; }
async function fetchGame(g) { const sto = await dapp.storage(); return sto ? gameFrom(sto, g) : null; }

// ---- actions -------------------------------------------------------------------------------------
function stakeBet(g, stakeRaw, role) {
  const G = load(); const secret = (G[g] && G[g].secret) ? G[g].secret : randSecret().toString();
  G[g] = { secret, role, stake: stakeRaw.toString(), ts: Date.now() }; save(G);
  activeGame = g; render();
  dapp.call(role === "p1" ? "open" : "join", [g, commitHashOf(BigInt(secret))], stakeRaw,
    (role === "p1" ? "open" : "join") + " poker game #" + g + " · " + rawToNado(stakeRaw) + " NADO", { game: g, phase: "bet" });
}
function newGame() {
  const raw = nadoToRaw($("stakeAmt").value);
  if (!raw) { $("status").textContent = "Enter a stake (NADO)."; return; }
  if (dapp.exec < raw) { $("status").textContent = "Deposit first — your exec balance is " + rawToNado(dapp.exec) + " NADO."; return; }
  stakeBet(randId(), raw, "p1");
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
  stakeBet(g, stake, "p2");
}
function revealMe() {
  const local = load()[activeGame]; if (!local) { $("status").textContent = "No secret for this game on this device."; return; }
  const slot = mySlot(lastGame || {}) || (local.role === "p1" ? 1 : 2);
  dapp.call("reveal" + slot, [activeGame, BigInt(local.secret)], null, "reveal your cards · game #" + activeGame, { game: activeGame, phase: "reveal" });
}
const resignGame = () => dapp.call("resign", [activeGame], null, "concede game #" + activeGame, { game: activeGame, phase: "resign" });
const agreeSplit = () => dapp.call("agree", [activeGame, 3], null, "agree a split · game #" + activeGame, { game: activeGame, phase: "agree" });
const abortGame = () => dapp.call("abort", [activeGame], null, "claim refund (opponent stalled) · game #" + activeGame, { game: activeGame, phase: "abort" });
const cancelGame = () => dapp.call("cancel", [activeGame], null, "cancel game #" + activeGame, { game: activeGame, phase: "cancel" });

async function refreshActive() {
  await dapp.refresh();
  const sto = await dapp.storage();
  if (sto) { pruneAndTrack(sto); if (activeGame != null) lastGame = gameFrom(sto, activeGame); renderLobby(sto); }
  await resolveAliases([dapp.me].concat(lastGame ? [lastGame.p1, lastGame.p2] : []));
  render();
}
function renderLobby(sto) {
  const el = $("lobbyList"); if (!el) return;
  const games = allGids(sto).map((g) => gameFrom(sto, g)).filter((g) => g.exists && !g.settled);
  games.sort((a, b) => (a.nn - b.nn) || (b.id - a.id));
  const shown = games.slice(0, 24);
  el.innerHTML = shown.length ? shown.map((g) => '<button class="chip ' + (g.nn < 2 ? "open" : "live") + '" data-g="' + g.id + '">' + (g.nn < 2 ? "🂠" : "▶") + " #" + g.id + " · " + rawToNado(g.stake) + " NADO" + (g.nn < 2 ? " · join" : " · watch") + "</button>").join(" ") : '<span class="dim">No games yet — open one above.</span>';
  el.querySelectorAll(".chip").forEach((b) => b.onclick = () => { activeGame = parseInt(b.dataset.g, 10); $("joinId").value = b.dataset.g; $("status").textContent = "Game #" + activeGame + " selected."; refreshActive(); try { $("activeGame").scrollIntoView({ behavior: "smooth", block: "start" }); } catch {} });
}

// ---- card rendering ------------------------------------------------------------------------------
const RANKSTR = { 14: "A", 13: "K", 12: "Q", 11: "J" }, SUITSTR = { s: "♠", h: "♥", d: "♦", c: "♣" };
function cardHTML(card, faceDown) {
  if (faceDown || !card) return '<div class="card back"></div>';
  const rank = RANKSTR[card.rank] || String(card.rank), red = card.suit === "h" || card.suit === "d";
  return '<div class="card' + (red ? " red" : "") + '">' + rank + '<span class="suit">' + SUITSTR[card.suit] + "</span></div>";
}
function handHTML(hand, faceDown) { return (hand || [null, null, null, null, null]).map((c) => cardHTML(c, faceDown || !c)).join(""); }

// ---- render --------------------------------------------------------------------------------------
function wireUI() {
  $("btnSignIn").onclick = () => dapp.signIn();
  $("btnDeposit").onclick = () => { const raw = nadoToRaw($("bankAmt").value); if (!raw) return ($("status").textContent = "Enter an amount to deposit."); if (raw + 1000n > dapp.l1) return ($("status").textContent = "Not enough in your L1 wallet (" + rawToNado(dapp.l1) + " NADO)."); dapp.deposit(raw); };
  $("btnWithdraw").onclick = () => { const raw = nadoToRaw($("bankAmt").value); if (!raw) return ($("status").textContent = "Enter an amount to withdraw."); if (dapp.exec < raw) return ($("status").textContent = "You only have " + rawToNado(dapp.exec) + " NADO in the exec layer."); dapp.withdraw(raw); };
  $("btnNew").onclick = newGame;
  $("btnJoin").onclick = joinGame;
  $("joinId").oninput = () => render();
  $("btnReveal").onclick = revealMe;
  $("btnReopen").onclick = reopenGame;
  $("btnResign").onclick = resignGame;
  $("btnSplit").onclick = agreeSplit;
  $("btnAbort").onclick = abortGame;
  $("btnCancel").onclick = cancelGame;
  $("btnShare").onclick = () => share(base() + "/?game=" + activeGame, "Play me heads-up poker for " + (lastGame && lastGame.exists ? rawToNado(lastGame.stake) + " NADO " : "") + "on NADO — game #" + activeGame + ":", $("btnShare"));
}
function render() {
  const signedIn = !!dapp.me;
  $("btnSignIn").classList.toggle("hidden", signedIn);
  $("who").textContent = signedIn ? disp(dapp.me) : "not signed in";
  $("bal").textContent = rawToNado(dapp.exec) + " NADO";
  $("l1bal").textContent = rawToNado(dapp.l1) + " NADO";
  $("play").classList.toggle("hidden", !signedIn);
  $("bankroll").classList.toggle("hidden", !signedIn);
  const G = load(), ids = Object.keys(G).sort((a, b) => G[b].ts - G[a].ts).slice(0, 8);   // keep every game visible (landed OR confirming)
  $("recent").innerHTML = ids.length ? ids.map((g) => { const live = knownGames.has(String(g)); return '<button class="chip' + (live ? "" : " pending") + '" data-g="' + g + '"' + (live ? "" : ' title="still confirming on-chain — your game hasn\'t vanished"') + '>🂡 #' + g + (live ? "" : " ⏳") + "</button>"; }).join(" ") : '<span class="dim">No games yet.</span>';
  $("recent").querySelectorAll(".chip").forEach((b) => b.onclick = () => { activeGame = parseInt(b.dataset.g, 10); refreshActive(); });
  renderActive();
}
function renderActive() {
  const box = $("activeGame");
  if (activeGame == null) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  const g = lastGame || {}, local = load()[activeGame] || {}, slot = mySlot(g);
  $("gameId").textContent = "#" + activeGame;
  $("shareLink").value = base() + "/?game=" + activeGame;
  $("gPot").textContent = g.exists ? rawToNado(g.pot) + " NADO" : (local.stake ? rawToNado(BigInt(local.stake) * 2n) + " NADO" : "—");
  const revealed = g.r1 && g.r2;
  const iAmP1 = slot === 1, iAmP2 = slot === 2;
  // my hand on top (revealed to me only after both reveal); opponent below
  const myHand = iAmP1 ? g.handP1 : iAmP2 ? g.handP2 : g.handP1;
  const oppHand = iAmP1 ? g.handP2 : iAmP2 ? g.handP1 : g.handP2;
  const myName = iAmP1 ? g.nameP1 : iAmP2 ? g.nameP2 : g.nameP1;
  const oppName = iAmP1 ? g.nameP2 : iAmP2 ? g.nameP1 : g.nameP2;
  const oppAddr = iAmP1 ? g.p2 : iAmP2 ? g.p1 : g.p2;
  $("oppLabel").textContent = (oppAddr ? disp(oppAddr) : "opponent") + (revealed && oppName ? " · " + oppName : "");
  $("myLabel").textContent = (slot ? "You" : "White") + (revealed && myName ? " · " + myName : "");
  $("oppHand").innerHTML = handHTML(oppHand, !revealed);
  $("myHand").innerHTML = handHTML(myHand, !revealed);
  // status
  let st = "opening…";
  if (g.exists && g.settled) st = "✓ settled";
  else if (g.exists && g.nn < 2) st = local.role === "p1" ? "waiting for an opponent to join…" : "joining…";
  else if (g.exists && revealed) {
    const iWon = (g.winner === slot), tie = g.winner === 3;
    st = tie ? "Tie — agree to split the pot" : (slot ? (iWon ? "You WIN — " + myName + " beats " + oppName + " 🎉" : "You lose — " + oppName + " beats " + myName) : "Result: " + (g.winner === 1 ? "White" : "Black") + " wins");
  } else if (g.exists) {
    const iRevealed = slot === 1 ? g.r1 : g.r2;
    st = iRevealed ? "waiting for your opponent to reveal…" : (local.reveal === "pending" ? "your reveal is confirming (~1 min)…" : "both in — reveal your cards to show down");
  }
  $("gStatus").textContent = st;
  $("btnReopen").classList.toggle("hidden", !(local.role === "p1" && local.stake && local.secret && !g.exists && local.ts && Date.now() - local.ts > 120000));
  // buttons
  const live = g.exists && g.nn === 2 && !g.settled, iAmIn = !!slot;
  const iRevealed = slot === 1 ? g.r1 : g.r2;
  $("btnReveal").classList.toggle("hidden", !(live && iAmIn && !iRevealed));
  const over = live && revealed;
  const iWon = over && g.winner === slot, tie = over && g.winner === 3;
  $("btnResign").classList.toggle("hidden", !(live && iAmIn && !tie && (!over || !iWon)));   // loser (or pre-showdown fold) concedes
  $("btnResign").textContent = over ? "Concede — pay out the winner" : "Fold (concede pot)";
  $("btnSplit").classList.toggle("hidden", !(over && iAmIn && tie));
  const pastDeadline = live && dapp.cursor != null && dapp.cursor > g.deadline;
  $("btnAbort").classList.toggle("hidden", !(iAmIn && pastDeadline));
  $("btnCancel").classList.toggle("hidden", !(g.exists && g.nn === 1 && slot === 1 && !g.settled));
  $("settleHint").textContent = over && !g.settled
    ? (tie ? "It's a tie — both agree to split (refund each stake)." : iWon ? "You won! Waiting for your opponent to concede (or claim a refund after the timeout)." : "You're beaten — concede to pay out the winner.")
    : "";
}

// ---- boot ----------------------------------------------------------------------------------------
dapp.onReturn((pend, ok, err) => {
  const label = { connect: "Signed in.", deposit: "Deposit submitted — confirming…", bet: "Stake submitted — confirming…",
    reveal: "Reveal submitted — confirming (~1 min)…", resign: "Conceding…", agree: "Submitting…", abort: "Claiming refund…",
    cancel: "Cancelling…", withdraw: "Withdrawal submitted." }[pend && pend.phase] || "Submitted.";
  if (pend && pend.game != null) activeGame = pend.game;
  if (ok && pend && pend.phase === "reveal") { const G = load(); if (G[pend.game]) { G[pend.game].reveal = "pending"; save(G); } }
  $("status").textContent = ok ? label : "Rejected" + (err ? ": " + err : ".");
});
async function boot() {
  try { await dapp.init(); } catch (e) { $("status").textContent = "Crypto bundle failed to load — reload."; return; }
  wireUI();
  const q = new URLSearchParams(location.search).get("game");
  if (q) { $("joinId").value = q; if (activeGame == null) activeGame = parseInt(q, 10); }
  render(); refreshActive();
  setInterval(refreshActive, 3000);
}
boot();
