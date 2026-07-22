// reversi.js — NADO Reversi (Othello): staked 8x8 where the CONTRACT is the referee: move() walks all
// 8 directions ON-CHAIN, requires at least one flip (the legality rule), flips every bracketed run and
// alternates turns; two passes in a row make the contract count the discs itself and pay the pot to the
// majority (equal counts refund both). Built on the shared PvP board-game scaffold (pvpgame.js) — this
// file is ONLY the reversi board: its decode, its render, its move/pass encoding.
import { NadoDapp, rawToNado, _m, $, disp, gate, hoist } from "./nadodapp.js?v=4984604e";
import { PvpGame } from "./pvpgame.js?v=ba9e61e6";
import { BoardDaily, gameModes } from "./board-daily-ui.js?v=5400e8a1";   // shared free Daily Challenge + mode picker
import * as RULES from "./reversi-rules.js?v=b3c2a4b7";
import { Practice } from "./practice.js?v=77683a2a";   // free in-browser practice vs the computer

const CID = "20931f1cbce1f1040f9d0c8f6c78c29c";
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

pvp.boot(["activeGame", "lobby", "opencard", "practice", "walletcard", "bankroll", "scoreboard", "dailyCard"])
  // boot() is async and reorders every card to the top; hoist the picker AFTER that so
  // the mode choice sits above the cards it switches between
  .then(() => hoist("modeBar")).catch(() => {});

// ---- MODE PICKER + free DAILY CHALLENGE (both shared: board-daily-ui.js / nadodapp modeBar) --------
// Stakes, practice and the daily are the same three choices in every game, so the picker and the whole
// daily surface come from the SDK; this file only says which rules to use and how a cell should look.
const daily = new BoardDaily(dapp, RULES, { name: "Daily Flip", mount: "dailyPlay", listEl: "dailyList",
                                            marks: ["", "⚫", "⚪"] });
const LS_MODE = "nado_reversi_mode";
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


// ---- PRACTICE MODE (free, in-browser — you are ⚫ vs a greedy corner-hungry ⚪; nothing on-chain) -------
const prac = new Practice("reversi");
let pb, pOver;
function pReset() {
  pb = Array.from({ length: 8 }, () => Array(8).fill(0));
  pb[3][3] = 2; pb[4][4] = 2; pb[3][4] = 1; pb[4][3] = 1;   // the standard opening cross
  pOver = false;
}
const pLegal = (k) => { const out = []; for (let c = 0; c < 8; c++) for (let r = 0; r < 8; r++) if (flipsFor(pb, c, r, k).length) out.push(c * 8 + r); return out; };
function pPlace(c, r, k) { const fl = flipsFor(pb, c, r, k); pb[c][r] = k; for (const [fc, fr] of fl) pb[fc][fr] = k; }
const pCount = () => { let n1 = 0, n2 = 0; for (const col of pb) for (const k of col) { if (k === 1) n1++; else if (k === 2) n2++; } return [n1, n2]; };
function pAiMove() {                        // greedy max-flips, corners heavily preferred, edges mildly
  let best = null, bestS = -1;
  for (const p of pLegal(2)) {
    const c = Math.floor(p / 8), r = p % 8;
    const corner = (c === 0 || c === 7) && (r === 0 || r === 7), edge = c === 0 || c === 7 || r === 0 || r === 7;
    const s = flipsFor(pb, c, r, 2).length + (corner ? 8 : edge ? 2 : 0);
    if (s > bestS) { bestS = s; best = [c, r]; }
  }
  pPlace(best[0], best[1], 2);
}
function pEnd() {                           // neither side can move — count the discs
  const [n1, n2] = pCount();
  pOver = true;
  prac.tally(n1 > n2 ? "w" : n1 < n2 ? "l" : "d");
  $("pResult").innerHTML = (n1 > n2 ? "🏆 " + window.t("sdk.prYouWin", "You win!")
    : n1 < n2 ? "💀 " + window.t("sdk.prAiWins", "The computer wins.")
    : "🤝 " + window.t("sdk.prDraw", "Draw.")) + " ⚫ " + n1 + " · ⚪ " + n2;
  pRender();
}
function pStep() {                          // the computer answers; it keeps moving while you have no reply
  let note = "";
  for (;;) {
    if (pLegal(2).length) pAiMove();
    else note = "🤖 " + window.t("sdk.prAiPasses", "The computer has no move — it passes.");
    if (pLegal(1).length) { $("pResult").innerHTML = note || window.t("sdk.prYourMove", "▶ YOUR MOVE (practice)"); return pRender(); }
    if (!pLegal(2).length) return pEnd();
    note = window.t("sdk.prYouPass", "You have no move — you pass.");
  }
}
function pTap(p) {
  if (pOver) return;
  const c = Math.floor(p / 8), r = p % 8;
  if (!flipsFor(pb, c, r, 1).length) return;
  pPlace(c, r, 1);
  pStep();
}
function pRender() {
  prac.strip($("pStrip"), { chips: false, tally: true });
  const legal = pOver ? [] : pLegal(1);
  let html = "";
  for (let r = 0; r < 8; r++) for (let c = 0; c < 8; c++) {
    const k = pb[c][r], p = c * 8 + r, canGo = legal.includes(p);
    html += '<div class="rvc' + (k === 1 ? " p1" : k === 2 ? " p2" : "") + (canGo ? " legal" : "")
      + '" data-pp="' + p + '">' + (k ? '<div class="d"></div>' : canGo ? '<div class="hint"></div>' : "") + "</div>";
  }
  $("pBoard").innerHTML = html;
  $("pBoard").querySelectorAll("[data-pp]").forEach((el) => el.onclick = () => pTap(parseInt(el.dataset.pp, 10)));
  const [n1, n2] = pCount();
  $("pCounts").innerHTML = "⚫ <b>" + n1 + "</b> · ⚪ <b>" + n2 + "</b>";
}
if ($("pBoard")) {
  $("pNew").onclick = () => { pReset(); $("pResult").textContent = ""; pRender(); };
  pReset(); pRender();
}
