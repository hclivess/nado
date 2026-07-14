// reversi.js — NADO Reversi (Othello): staked 8x8 where the CONTRACT is the referee: move() walks all
// 8 directions ON-CHAIN, requires at least one flip (the legality rule), flips every bracketed run and
// alternates turns; two passes in a row make the contract count the discs itself and pay the pot to the
// majority (equal counts refund both). Built on the shared PvP board-game scaffold (pvpgame.js) — this
// file is ONLY the reversi board: its decode, its render, its move/pass encoding.
import { NadoDapp, rawToNado, _m, $, disp } from "./nadodapp.js";
import { PvpGame } from "./pvpgame.js";

const CID = "017fd842c55254328c4133dc283fcea5";
const PASS = 64;
const dapp = new NadoDapp({ cid: CID, app: "Reversi" });

const DIRS = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]];
function flipsFor(b, c, r, k) {
  if (b[c][r]) return [];
  const opp = 3 - k, out = [];
  for (const [dx, dy] of DIRS) {
    const run = []; let cc = c + dx, rr = r + dy;
    while (cc >= 0 && cc < 8 && rr >= 0 && rr < 8 && b[cc][rr] === opp) { run.push([cc, rr]); cc += dx; rr += dy; }
    if (run.length && cc >= 0 && cc < 8 && rr >= 0 && rr < 8 && b[cc][rr] === k) out.push(...run);
  }
  return out;
}
const coord = (p) => "abcdefgh"[Math.floor(p / 8)] + (p % 8 + 1);

const pvp = new PvpGame(dapp, {
  icon: "⚪",
  marks: ["⚫", "⚪"],
  appendMaps: ["bd", "lp"],
  decode(gm, sto, g) {
    gm.board = []; gm.n1 = 0; gm.n2 = 0;
    for (let c = 0; c < 8; c++) {
      const col = [];
      for (let r = 0; r < 8; r++) {
        const k = _m(sto, "bd")[String(g * 512 + (c + 1) * 16 + (r + 1))] || 0;
        col.push(k); if (k === 1) gm.n1++; else if (k === 2) gm.n2++;
      }
      gm.board.push(col);
    }
    gm.lp = !!_m(sto, "lp")[String(g)];
    gm.legal = [];
    if (gm.turn) for (let c = 0; c < 8; c++) for (let r = 0; r < 8; r++)
      if (flipsFor(gm.board, c, r, gm.turn).length) gm.legal.push(c * 8 + r);
  },
  lobbyChip: (g) => window.t("rv.lobbyChip", "⚪ #{id} · stake {stake} · by {who}", { id: g.id, stake: rawToNado(g.stake), who: disp(g.p1) }),
  shareText: (gm) => window.t("rv.shareText", "Beat me at Reversi for {amt} NADO on NADO:", { amt: gm.exists ? rawToNado(gm.stake) : "" }),
  inviteTitle: window.t ? window.t("rv.inviteTitle", "You're invited to Reversi") : "You're invited to Reversi",
  inviteBody: (gm) => window.t("rv.inviteBody", "Play {who} for <b>{amt} NADO</b> — most discs takes the pot.", { who: disp(gm.p1), amt: rawToNado(gm.stake) }),
  yourMoveText: (gm) => gm.legal.length
    ? window.t("rv.yourMove", "▶ YOUR MOVE — tap a highlighted cell")
    : window.t("rv.yourMoveNoLegal", "▶ YOUR MOVE — no legal placement, you must pass"),
  drawText: () => window.t("rv.draw", "🤝 Equal discs — both stakes refunded."),
  renderBoard(gm) {
    const myTurn = !gm.sd && gm.turnAddr === dapp.me;
    const pend = pvp.pendingMove;
    let pendFlips = [];
    if (pend && pend.pos < PASS) {
      const c = Math.floor(pend.pos / 8), r = pend.pos % 8;
      if (!gm.board[c][r]) pendFlips = flipsFor(gm.board, c, r, gm.turn || 1);
    }
    let html = "";
    for (let r = 0; r < 8; r++) for (let c = 0; c < 8; c++) {
      const k = gm.board[c][r], p = c * 8 + r;
      const isPend = pend && pend.pos === p && !k;
      const isFlip = pendFlips.some(([fc, fr]) => fc === c && fr === r);
      const canGo = myTurn && !pend && gm.legal.includes(p);
      const cls = "rvc" + (k === 1 ? " p1" : k === 2 ? " p2" : "") + (canGo ? " legal" : "")
        + (isPend ? " pend p" + gm.turn : "") + (isFlip ? " flip p" + gm.turn : "");
      html += '<div class="' + cls + '" data-p="' + p + '">' + (k || isPend || isFlip ? '<div class="d"></div>' : (canGo ? '<div class="hint"></div>' : "")) + "</div>";
    }
    $("board").innerHTML = html;
    $("board").querySelectorAll(".rvc").forEach((el) => el.onclick = () => tapCell(parseInt(el.dataset.p, 10)));
    $("counts").innerHTML = gm.exists && gm.nn === 2
      ? "⚫ <b>" + gm.n1 + "</b> · ⚪ <b>" + gm.n2 + "</b>" +
        (gm.lp && !gm.sd ? ' <span class="dim">· ' + window.t("rv.lpNote", "last move was a pass — one more pass ends the game and counts the discs") + "</span>" : "")
      : "";
  },
  extraActions(gm, btn) {
    if (!gm.sd && gm.nn === 2 && gm.turnAddr === dapp.me && !pvp.pendingMove) {
      const must = !gm.legal.length;
      btn((gm.lp ? window.t("rv.passScore", "Pass — end the game & count discs")
                 : window.t("rv.pass", "Pass — no move")), () => passMove(), must, must);
    }
  },
});

function tapCell(p) {
  const gm = pvp.last;
  if (!gm || gm.sd || gm.turnAddr !== dapp.me || pvp.pendingMove) return;
  if (!gm.legal.includes(p)) return;
  pvp.pendingMove = { ply: gm.mc, pos: p };
  pvp.render();
  pvp.move([p], (gm.turn === 1 ? "⚫" : "⚪") + " " + coord(p) + " · game #" + pvp.active, { pos: p });
}
function passMove() {
  const gm = pvp.last;
  if (!gm || gm.sd || gm.turnAddr !== dapp.me) return;
  pvp.pendingMove = { ply: gm.mc, pos: PASS };
  pvp.move([PASS], (gm.turn === 1 ? "⚫" : "⚪") + " passes · game #" + pvp.active, { pos: PASS });
}

pvp.boot(["activeGame", "lobby", "opencard", "walletcard", "bankroll", "scoreboard"]);
