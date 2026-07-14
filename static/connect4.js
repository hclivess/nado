// connect4.js — NADO Connect Four: staked 7x6 where the CONTRACT is the referee: move() checks turn +
// gravity ON-CHAIN, drops the disc, detects four-in-a-row itself and pays the pot instantly; a full
// board refunds both stakes. Built on the shared PvP board-game scaffold (pvpgame.js) — this file is
// ONLY the connect-four board: its decode, its render, its move.
import { NadoDapp, rawToNado, _m, $, disp } from "./nadodapp.js";
import { PvpGame } from "./pvpgame.js";

const CID = "67349828b38443eda30de51dea8a3d67";
const COLS = 7, ROWS = 6;
const dapp = new NadoDapp({ cid: CID, app: "ConnectFour" });

function findWin(b) {
  for (let c = 0; c < COLS; c++) for (let r = 0; r < ROWS; r++) {
    const k = b[c][r]; if (!k) continue;
    for (const [dx, dy] of [[1, 0], [0, 1], [1, 1], [1, -1]]) {
      const cells = [[c, r]];
      for (let s = 1; s < 4; s++) {
        const cc = c + s * dx, rr = r + s * dy;
        if (cc < 0 || cc >= COLS || rr < 0 || rr >= ROWS || b[cc][rr] !== k) break;
        cells.push([cc, rr]);
      }
      if (cells.length === 4) return cells;
    }
  }
  return null;
}

const pvp = new PvpGame(dapp, {
  icon: "🟡",
  marks: ["🟢", "🟡"],
  appendMaps: ["bd"],
  decode(gm, sto, g) {
    gm.board = [];
    for (let c = 0; c < COLS; c++) {
      const col = [];
      for (let r = 0; r < ROWS; r++) col.push(_m(sto, "bd")[String(g * 128 + (c + 1) * 10 + (r + 1))] || 0);
      gm.board.push(col);
    }
    gm.winCells = findWin(gm.board);
  },
  lobbyChip: (g) => window.t("c4.lobbyChip", "🟡 #{id} · stake {stake} · by {who}", { id: g.id, stake: rawToNado(g.stake), who: disp(g.p1) }),
  shareText: (gm) => window.t("c4.shareText", "Beat me at Connect Four for {amt} NADO on NADO:", { amt: gm.exists ? rawToNado(gm.stake) : "" }),
  inviteTitle: window.t ? window.t("c4.inviteTitle", "You're invited to Connect Four") : "You're invited to Connect Four",
  inviteBody: (gm) => window.t("c4.inviteBody", "Play {who} for <b>{amt} NADO</b> — winner takes the pot.", { who: disp(gm.p1), amt: rawToNado(gm.stake) }),
  yourMoveText: () => window.t("c4.yourMove", "▶ YOUR MOVE — tap a column"),
  renderBoard(gm) {
    const myTurn = !gm.sd && gm.turnAddr === dapp.me;
    const pend = pvp.pendingMove;
    const isWin = (c, r) => gm.winCells && gm.winCells.some(([wc, wr]) => wc === c && wr === r);
    let html = "";
    for (let r = ROWS - 1; r >= 0; r--) for (let c = 0; c < COLS; c++) {
      const k = gm.board[c][r];
      const isPend = pend && pend.col === c && pend.row === r && !k;
      const cls = "c4c" + (k === 1 ? " p1" : k === 2 ? " p2" : "") + (isWin(c, r) ? " win" : "")
        + (isPend ? " pend p" + (gm.mc % 2 + 1) : "") + (myTurn && !gm.board[c][ROWS - 1] ? " live" : "");
      html += '<div class="' + cls + '" data-c="' + c + '"></div>';
    }
    $("board").innerHTML = html;
    $("board").querySelectorAll(".c4c").forEach((el) => el.onclick = () => dropCol(parseInt(el.dataset.c, 10)));
  },
});

function dropCol(c) {
  const gm = pvp.last;
  if (!gm || gm.sd || gm.turnAddr !== dapp.me) return;
  let row = 0; while (row < ROWS && gm.board[c][row]) row++;
  if (row >= ROWS) return;
  pvp.pendingMove = { ply: gm.mc, col: c, row };
  pvp.render();
  pvp.move([c], (gm.mc % 2 === 0 ? "🟢" : "🟡") + " in column " + (c + 1) + " · game #" + pvp.active, { col: c });
}

pvp.boot(["activeGame", "lobby", "opencard", "walletcard", "bankroll", "scoreboard"]);
