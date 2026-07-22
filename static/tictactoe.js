// tictactoe.js — NADO Tic-Tac-Toe: staked 3x3 where the CONTRACT is the referee (unlike chess, a 3x3
// board fits in the VM): move() checks turn + free cell ON-CHAIN, detects three-in-a-row and pays the
// pot instantly, and a full board auto-refunds both stakes. Ply-bound moves (the chess retry-race
// lesson), resign/abort escapes, and a short ~30-min move clock. Built on the shared PvP board-game
// scaffold (pvpgame.js) — this file is ONLY the tic-tac-toe board: its decode, its render, its move.
import { NadoDapp, rawToNado, _m, $, disp, gate, hoist } from "./nadodapp.js?v=77a0d4df";
import { PvpGame } from "./pvpgame.js?v=eb8aca5a";
import { BoardDaily, gameModes } from "./board-daily-ui.js?v=07887a3f";   // shared free Daily Challenge + mode picker
import * as RULES from "./tictactoe-rules.js?v=d91a7a7f";
import { Practice } from "./practice.js?v=1e947bde";   // free in-browser practice vs the computer

const CID = "bd279df315335d99fdc6b91e623895f4";
const dapp = new NadoDapp({ cid: CID, app: "TicTacToe" });
const LINES = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [0, 3, 6], [1, 4, 7], [2, 5, 8], [0, 4, 8], [2, 4, 6]];

const pvp = new PvpGame(dapp, {
  icon: "⭕",
  marks: ["✕", "◯"],
  appendMaps: ["bd"],
  decode(gm, sto, g) {
    gm.board = Array.from({ length: 9 }, (_, i) => _m(sto, "bd")[String(g * 16 + i)] || 0);
    gm.winLine = null;
    for (const ln of LINES) { const v = gm.board[ln[0]]; if (v && v === gm.board[ln[1]] && v === gm.board[ln[2]]) gm.winLine = ln; }
  },
  lobbyChip: (g) => window.t("ttt.lobbyChip", "⭕ #{id} · stake {stake} · by {who}", { id: g.id, stake: rawToNado(g.stake), who: disp(g.p1) }),
  shareText: (gm) => window.t("ttt.shareText", "Beat me at tic-tac-toe for {amt} NADO on NADO:", { amt: gm.exists ? rawToNado(gm.stake) : "" }),
  inviteTitle: window.t ? window.t("ttt.inviteTitle", "You're invited to tic-tac-toe") : "You're invited to tic-tac-toe",
  inviteBody: (gm) => window.t("ttt.inviteBody", "Play {who} for <b>{amt} NADO</b> — winner takes the pot.", { who: disp(gm.p1), amt: rawToNado(gm.stake) }),
  yourMoveText: () => window.t("ttt.yourMove", "▶ YOUR MOVE — tap a cell"),
  renderBoard(gm) {
    const marks = ["", "✕", "◯"], cls = ["", "x", "o"];
    const pend = pvp.pendingMove;
    $("board").innerHTML = gm.board.map((c, i) => {
      const winCell = gm.winLine && gm.winLine.includes(i);
      const isPend = pend && pend.cell === i && c === 0;
      return '<div class="cell ' + cls[c] + (winCell ? " win" : "") + (c || gm.sd || gm.turnAddr !== dapp.me ? " dead" : "") + (isPend ? " pend" : "") +
        '" data-c="' + i + '">' + (isPend ? marks[gm.mc % 2 + 1] : marks[c]) + "</div>";
    }).join("");
    $("board").querySelectorAll(".cell").forEach((el) => el.onclick = () => moveCell(parseInt(el.dataset.c, 10)));
  },
});

function moveCell(i) {
  const gm = pvp.last;
  if (!gm || gm.sd || gm.turnAddr !== dapp.me || gm.board[i] !== 0 || pvp.pendingMove) return;   // one move per turn — ignore taps while it confirms
  pvp.pendingMove = { ply: gm.mc, cell: i };
  pvp.render();
  pvp.move([i], (gm.mc % 2 === 0 ? "✕" : "◯") + " on cell " + (i + 1) + " · game #" + pvp.active, { cell: i });
}

pvp.boot(["activeGame", "lobby", "opencard", "practice", "walletcard", "bankroll", "scoreboard", "dailyCard"])
  // boot() is async and reorders every card to the top; hoist the picker AFTER that so
  // the mode choice sits above the cards it switches between
  .then(() => hoist("modeBar")).catch(() => {});

// ---- MODE PICKER + free DAILY CHALLENGE (both shared: board-daily-ui.js / nadodapp modeBar) --------
// Stakes, practice and the daily are the same three choices in every game, so the picker and the whole
// daily surface come from the SDK; this file only says which rules to use and how a cell should look.
const daily = new BoardDaily(dapp, RULES, { name: "Daily Three", mount: "dailyPlay", listEl: "dailyList",
                                            marks: ["", "✕", "◯"] });
const LS_MODE = "nado_tictactoe_mode";
const MODES = ["play", "practice", "daily"];
// ?mode=daily deep-links straight to a mode (shareable, and the last choice otherwise sticks)
let mode = (() => {
  const q = new URLSearchParams(location.search).get("mode");
  if (MODES.includes(q)) return q;
  try { const v = localStorage.getItem(LS_MODE); return MODES.includes(v) ? v : "play"; } catch (e) { return "play"; }
})();
const setMode = (k) => { mode = k; try { localStorage.setItem(LS_MODE, k); } catch (e) {} pvp.render(); };
const redrawDaily = () => { daily.render(redrawDaily); daily.renderBoard(pvp.lastSto); };

function applyMode() {
  gameModes($("modeBar"), mode, setMode);
  const play = mode === "play", prac = mode === "practice", day = mode === "daily";
  const signedIn = !!dapp.me;
  gate({ lobby: play, opencard: play && signedIn, bankroll: play && signedIn, scoreboard: play,
         activeGame: play && pvp.active != null, practice: prac, dailyCard: day });
  if (!day) return;
  // entering the daily seeds today's board if nobody has yet — a free, permissionless call, and the
  // shared driver resumes it by itself if the wallet has to redirect for a first-ever action
  daily.ensure(pvp.lastSto).then((a) => {
    if (!a && dapp.me && !daily.seeding) daily.seedNow(() => pvp.storage(), redrawDaily);
    else redrawDaily();
  });
}
const _pvpRender = pvp.render.bind(pvp);
pvp.render = function () { _pvpRender(); applyMode(); };   // mode gating layers over the scaffold's own
applyMode();
setInterval(() => { if (mode === "daily") daily.renderBoard(pvp.lastSto); }, 8000);


// ---- PRACTICE MODE (free, in-browser — you are X vs a perfect-play minimax O; nothing on-chain) --------
const prac = new Practice("tictactoe");
let pb = Array(9).fill(0), pOver = false;
const pWin = (b, m) => LINES.find((ln) => b[ln[0]] === m && b[ln[1]] === m && b[ln[2]] === m) || null;
function pMinimax(b, me, depth) {           // returns [score, move] for the player `me` (1=X human, 2=O ai)
  if (pWin(b, 2)) return [10 - depth, -1];
  if (pWin(b, 1)) return [depth - 10, -1];
  if (!b.includes(0)) return [0, -1];
  let best = me === 2 ? [-99, -1] : [99, -1];
  for (let i = 0; i < 9; i++) {
    if (b[i]) continue;
    b[i] = me;
    const [s] = pMinimax(b, 3 - me, depth + 1);
    b[i] = 0;
    if (me === 2 ? s > best[0] : s < best[0]) best = [s, i];
  }
  return best;
}
function pRender() {
  prac.strip($("pStrip"), { chips: false, tally: true });
  const wl = pWin(pb, 1) || pWin(pb, 2);
  $("pBoard").innerHTML = pb.map((c, i) =>
    '<div class="cell ' + (c === 1 ? "x" : c === 2 ? "o" : "") + (wl && wl.includes(i) ? " win" : "")
    + (c || pOver ? " dead" : "") + '" data-p="' + i + '">' + ["", "✕", "◯"][c] + "</div>").join("");
  $("pBoard").querySelectorAll("[data-p]").forEach((el) => el.onclick = () => pTap(parseInt(el.dataset.p, 10)));
}
function pEnd(msg, res) { pOver = true; prac.tally(res); $("pResult").innerHTML = msg; pRender(); }
function pTap(i) {
  if (pOver || pb[i]) return;
  pb[i] = 1;
  if (pWin(pb, 1)) return pEnd("🏆 " + window.t("sdk.prYouWin", "You win!"), "w");
  if (!pb.includes(0)) return pEnd("🤝 " + window.t("sdk.prDraw", "Draw."), "d");
  const [, mv] = pMinimax(pb.slice(), 2, 0);
  pb[mv] = 2;
  if (pWin(pb, 2)) return pEnd("💀 " + window.t("sdk.prAiWins", "The computer wins."), "l");
  if (!pb.includes(0)) return pEnd("🤝 " + window.t("sdk.prDraw", "Draw."), "d");
  $("pResult").textContent = "";
  pRender();
}
if ($("pBoard")) {
  $("pNew").onclick = () => { pb = Array(9).fill(0); pOver = false; $("pResult").textContent = ""; pRender(); };
  pRender();
}
