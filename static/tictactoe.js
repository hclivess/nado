// tictactoe.js — NADO Tic-Tac-Toe: staked 3x3 where the CONTRACT is the referee (unlike chess, a 3x3
// board fits in the VM): move() checks turn + free cell ON-CHAIN, detects three-in-a-row and pays the
// pot instantly, and a full board auto-refunds both stakes. Ply-bound moves (the chess retry-race
// lesson), resign/abort escapes, and a short ~30-min move clock. Built on the shared PvP board-game
// scaffold (pvpgame.js) — this file is ONLY the tic-tac-toe board: its decode, its render, its move.
import { NadoDapp, rawToNado, _m, $, disp } from "./nadodapp.js";
import { PvpGame } from "./pvpgame.js";

const CID = "68f2bf23441437af6655e2eba4a71ba1";
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
  if (!gm || gm.sd || gm.turnAddr !== dapp.me || gm.board[i] !== 0) return;
  pvp.pendingMove = { ply: gm.mc, cell: i };
  pvp.render();
  pvp.move([i], (gm.mc % 2 === 0 ? "✕" : "◯") + " on cell " + (i + 1) + " · game #" + pvp.active, { cell: i });
}

pvp.boot(["activeGame", "lobby", "opencard", "walletcard", "bankroll", "scoreboard"]);
