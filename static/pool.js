// pool.js — NADO Pool: 8-ball, one against one, with or without a stake. This module owns ONLY the
// Pool half: the canvas table, the aiming rig (drag to aim, fine trim, power, English, called pocket,
// ball in hand) and the shot playback. Everything else is the shared SDK — nadodapp.js for the wallet,
// storage reads and the confirm lifecycle, duelgame.js for the escrow lobby, the on-chain move log, the
// practice-vs-computer mode and the concede/agree/refund settle, and pool-engine.js for the rules.
//
// A shot is ONE log entry, so a whole frame of pool is ~30 transactions and both browsers re-derive the
// identical table from them: the physics is integer-exact (see pool-engine.js) and the rack is seeded by
// the join block, so there is nothing for either side to disagree about.
import { NadoDapp, $, notify, disp, installModes, lsLoad, lsSave } from "./nadodapp.js?v=a8b7da3b";
import { DuelGame } from "./duelgame.js?v=51a6d3d6";
import * as E from "./pool-engine.js?v=f57297e4";
import { prand } from "./practice.js?v=a2d98706";

const CID = "043c6d95117ed222f3e95b1f2997fba9";
const dapp = new NadoDapp({ cid: CID, app: "Pool" });
const T = (k, d, v) => (typeof window !== "undefined" && window.t) ? window.t("pool." + k, d, v) : d;

// ---- ball colours (standard pool set) -----------------------------------------------------------------
const BALL_COLOR = ["#f2f4f7", "#f2c53d", "#2f6fd0", "#d1372f", "#7a3fb5", "#e07a26", "#2e9e5b", "#8d2b3a",
                    "#14181d", "#f2c53d", "#2f6fd0", "#d1372f", "#7a3fb5", "#e07a26", "#2e9e5b", "#8d2b3a"];
const RAIL = 78;                                   // table-unit width of the wooden rail drawn round the cloth

const playLog = [];                                // one entry per shot actually played (diagnostic/test hook)

// ---- aim assist ----------------------------------------------------------------------------------------
// How much of the shot to show before you take it: none, the cue ball's path only, or the full picture
// (cue path + ghost ball + where the object ball goes). Off is a real way to play — the whole preview is
// an assist — so it persists across sessions like any other preference.
const LS_ASSIST = "nado_pool_assist";
const ASSIST_MAX = 2;
let assist = (() => { const v = lsLoad(LS_ASSIST).level; return v == null ? ASSIST_MAX : Math.max(0, Math.min(ASSIST_MAX, v | 0)); })();
const setAssist = (v) => { assist = Math.max(0, Math.min(ASSIST_MAX, v | 0)); lsSave(LS_ASSIST, { level: assist }); };
const assistName = () => [T("assistOff", "off — no help at all"),
                          T("assistCue", "cue ball path only"),
                          T("assistFull", "full — ghost ball and object path")][assist];

// ---- aim state (local, never on-chain until the shot is taken) ----------------------------------------
const aim = { angle: 0, power: 30, side: 0, fwd: 0, call: null, px: null, py: null };
let dragging = null;                               // "cue" while the ball-in-hand puck is being moved
let anim = null;                                   // the shot currently playing back
// Shots are QUEUED, not just "the latest one". Two shots routinely land between renders — you break and
// the practice opponent answers at once, or a poll picks up both sides' shots — and animating only the
// last of them made the table teleport into its new layout and then roll a single ball, which reads as
// "only one ball animates". Each shot plays in turn instead.
let animQ = [];
let queuedUpTo = -1;                               // highest shot index whose frames have been queued

// ---- engine memo -------------------------------------------------------------------------------------
// Replaying every shot from the rack on each 3-second poll is ~80 ms of physics for a full frame; the log
// only ever grows, so keep the state and extend it. A reorg that rewrites the log fails the prefix check
// and falls back to a clean replay.
const memo = { key: "", encs: [], sides: [], st: null };
function rebuildEngine(gm) {
  if (!gm.kh) return null;
  const q = this.qOf(gm.kh);
  if (q == null) return E.replay(gm.id, null, []);
  const recs = gm.recs || [];
  const key = gm.id + ":" + gm.kh + ":" + q.toString();
  if (memo.key === key && memo.st && !memo.st.corrupt && memo.encs.length <= recs.length
      && memo.encs.every((e, i) => recs[i] && recs[i].enc === e && recs[i].side === memo.sides[i])) {
    for (let i = memo.encs.length; i < recs.length; i++) {
      E.applyMove(memo.st, recs[i].side, recs[i].enc, true);   // frames for EVERY new shot, so all play
      memo.st.mi = i + 1;
      memo.encs.push(recs[i].enc); memo.sides.push(recs[i].side);
      if (memo.st.corrupt) break;
      queueShot(memo.st.mi, memo.st.last && memo.st.last.frames, recs[i].side - 1, E.decShot(recs[i].enc));
    }
    return memo.st;
  }
  // A cold rebuild replays the whole log — opening a game already 20 shots deep must show the table as
  // it stands, not re-run twenty animations. Mark the history as seen; only shots that arrive AFTER
  // this play back. It is also the one place that reliably means "a DIFFERENT frame is on the table"
  // (new practice game, switched game, rematch), so the aim resets here: the SDK's startPractice does
  // not call resetLocal, and a stale angle plus a stale ball-in-hand placement from the last frame made
  // the next break fire off into nothing.
  const st = E.replay(gm.id, q, recs, false);
  memo.key = key; memo.st = st;
  memo.encs = recs.map((r) => r.enc); memo.sides = recs.map((r) => r.side);
  stopAnim(); queuedUpTo = st.mi;
  Object.assign(aim, { angle: 0, power: 30, side: 0, fwd: 0, call: null, px: null, py: null });
  return st;
}

const duel = new DuelGame(dapp, {
  prefix: "pool", icon: "🎱", marks: ["🎱", "🔴"], freeOk: true, prize: true,
  rebuild: rebuildEngine,
  // pool alternates, but a potter keeps shooting — the engine owns whose turn it is
  turnOf: (eng) => (eng && !eng.over ? eng.turn : null),
  canAct: (eng, me) => !!eng && !eng.over && eng.turn === me,
  resultOf: (eng) => (eng && eng.over ? eng.result : 0),
  // practice vs computer: the same engine, applied locally, with the engine's own shot picker answering
  applyLocal(eng, side, enc) {
    E.applyMove(eng, side, enc, true); eng.mi++;
    queueShot(eng.mi, eng.last && eng.last.frames, side - 1, E.decShot(enc));
  },
  botMove(eng, k) { return E.botEnc(eng, 1, prand(this.practice.seed + ":bot:" + k)); },
  overHint(eng, me) {
    if (!eng || !eng.over) return "";
    const last = eng.log[eng.log.length - 1];
    if (!last || !last.pots.some((p) => p.ball === 8)) return "";
    return eng.result - 1 === me ? T("hintYouSank8", "You sank the 8 in the called pocket.")
                                 : T("hintTheySank8", "The 8 went down and the frame is over.");
  },
  // reset the aim IN PLACE — rebinding it would leave every holder of the old object (the test hook,
  // any closure) pointing at a frozen snapshot
  onReset() {
    Object.assign(aim, { angle: 0, power: 30, side: 0, fwd: 0, call: null, px: null, py: null });
    stopAnim(); queuedUpTo = -1; dragging = null; memo.key = "";
  },
  onAdvance() { aim.call = null; },
  shareText: (gm, id) => T("shareText", "Rack 'em — play me at 8-ball on NADO, game #{id}:", { id }),
  inviteTitle: T("inviteTitle", "You've been challenged to a frame of 8-ball"),
  inviteBody: (gm) => (Number(gm.stake) > 0
    ? T("inviteBody", "Break against {who} for <b>{amt} NADO</b> — winner takes the pot.", { who: disp(gm.p1), amt: Number(gm.stake) / 1e10 })
    : T("inviteBodyFree", "{who} wants a free frame — no stake, just the frame.", { who: disp(gm.p1) })),
  wire: wireTable,
  renderGame,
});

// currentShot(eng): the shot the aiming rig is currently describing. The PREVIEW and the SUBMIT both
// build from this one function, so the line you were shown is by construction the shot you take.
function currentShot(eng) {
  let px = aim.px, py = aim.py;
  if (eng.inHand && px == null) {          // holding the cue ball but never dragged it — use where it sits
    const p = E.xyToPlace(Math.trunc(eng.b[0].x / E.FP), Math.trunc(eng.b[0].y / E.FP));
    px = p[0]; py = p[1];
  }
  return { angle: aim.angle, power: aim.power, side: aim.side, fwd: aim.fwd,
           call: aim.call == null ? 7 : aim.call, px: px || 0, py: py || 0 };
}

// previewFor(eng): run the REAL simulation for the current aim, memoised on everything that can change
// it. ~4 ms a shot, and only while it is your turn and nothing is animating.
let preview = null, previewKey = "";
function previewFor(eng) {
  const shot = currentShot(eng);
  const key = [shot.angle, shot.power, shot.side, shot.fwd, shot.px, shot.py, eng.mi,
               eng.b[0].x, eng.b[0].y].join(",");
  if (previewKey !== key || !preview) { previewKey = key; preview = E.previewShot(eng, shot); }
  return preview;
}

// ---- geometry: table units <-> canvas pixels ----------------------------------------------------------
function metrics() {
  const cv = $("table");
  const sc = cv.width / (E.W + 2 * RAIL);
  return { cv, sc, tx: (x) => (x + RAIL) * sc, ty: (y) => (y + RAIL) * sc,
           ux: (px) => px / sc - RAIL, uy: (py) => py / sc - RAIL };
}
function pointerUnits(ev) {
  const { cv, ux, uy } = metrics();
  const r = cv.getBoundingClientRect();
  const p = ev.touches && ev.touches[0] ? ev.touches[0] : ev;
  const scale = cv.width / r.width;
  return [Math.round(ux((p.clientX - r.left) * scale)), Math.round(uy((p.clientY - r.top) * scale))];
}

// the ball positions currently on screen: the animation frame if one is playing, else the settled table
function shownBalls(eng) {
  if (anim && anim.frames && anim.frames[anim.i]) {
    const f = anim.frames[anim.i], out = [];
    for (let i = 0; i < E.BALLS; i++) out.push({ on: f[i * 2] >= 0, x: f[i * 2], y: f[i * 2 + 1] });
    return out;
  }
  return eng.b.map((p) => ({ on: p.on, x: Math.trunc(p.x / E.FP), y: Math.trunc(p.y / E.FP) }));
}

// ---- drawing ------------------------------------------------------------------------------------------
function drawBall(g, sc, id, x, y) {
  const r = E.R * sc;
  g.save();
  g.translate(x, y);
  g.beginPath(); g.arc(0, 0, r, 0, Math.PI * 2);
  g.fillStyle = id === 0 ? "#f6f8fa" : BALL_COLOR[id];
  g.fill();
  if (E.isStripe(id)) {                             // stripes: white ball with a colour band
    g.save();
    g.beginPath(); g.arc(0, 0, r, 0, Math.PI * 2); g.clip();
    g.fillStyle = "#f6f8fa"; g.fillRect(-r, -r, 2 * r, 2 * r);
    g.fillStyle = BALL_COLOR[id]; g.fillRect(-r, -r * 0.52, 2 * r, r * 1.04);
    g.restore();
  }
  const grad = g.createRadialGradient(-r * 0.35, -r * 0.4, r * 0.1, 0, 0, r);
  grad.addColorStop(0, "rgba(255,255,255,.45)");
  grad.addColorStop(0.55, "rgba(255,255,255,0)");
  grad.addColorStop(1, "rgba(0,0,0,.35)");
  g.fillStyle = grad; g.beginPath(); g.arc(0, 0, r, 0, Math.PI * 2); g.fill();
  g.strokeStyle = "rgba(0,0,0,.45)"; g.lineWidth = Math.max(1, r * 0.06); g.stroke();
  if (id > 0 && r > 7) {                            // the numbered spot
    g.beginPath(); g.arc(0, 0, r * 0.48, 0, Math.PI * 2); g.fillStyle = "#f6f8fa"; g.fill();
    g.fillStyle = "#10151b"; g.font = "700 " + Math.round(r * 0.72) + "px system-ui,sans-serif";
    g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText(String(id), 0, r * 0.06);
  }
  g.restore();
}

function drawTable(eng, gm) {
  const { cv, sc, tx, ty } = metrics();
  const g = cv.getContext("2d");
  g.clearRect(0, 0, cv.width, cv.height);
  // rail
  const rr = 14 * sc;
  g.beginPath();
  if (g.roundRect) g.roundRect(0, 0, cv.width, cv.height, rr); else g.rect(0, 0, cv.width, cv.height);
  g.fillStyle = "#4b3323"; g.fill();
  g.strokeStyle = "#2a1c13"; g.lineWidth = Math.max(1, 2 * sc); g.stroke();
  // cloth
  const cg = g.createLinearGradient(0, ty(0), 0, ty(E.TH));
  cg.addColorStop(0, "#12694f"); cg.addColorStop(1, "#0d5540");
  g.fillStyle = cg;
  g.fillRect(tx(0), ty(0), E.W * sc, E.TH * sc);
  // head string + foot spot
  g.save();
  g.setLineDash([6 * sc, 6 * sc]); g.strokeStyle = "rgba(255,255,255,.18)"; g.lineWidth = Math.max(1, sc);
  g.beginPath(); g.moveTo(tx(E.HEAD_X), ty(0)); g.lineTo(tx(E.HEAD_X), ty(E.TH)); g.stroke();
  g.restore();
  g.fillStyle = "rgba(255,255,255,.22)";
  g.beginPath(); g.arc(tx(E.FOOT_X), ty(E.FOOT_Y), 3 * sc, 0, Math.PI * 2); g.fill();

  // POCKETS AND CUSHION JAWS, both derived from the engine's own mouth geometry (POCKET_MOUTH), so what
  // you see is exactly where a ball drops. The rubber stops short of every opening and its ends are cut
  // back at an angle — that is what gives each pocket its little pair of corners. The opening itself is
  // a CHORD along the cushion line that bulges away from the cloth: a real pocket falls away behind the
  // jaws, it does not bulge onto the playing surface (drawing them as centred circles made the two middle
  // pockets sit out in the field, which is not how a table looks).
  const CW = 30, CJ = 22, SJ = 13;                    // cushion depth into the rail, jaw cut-backs
  const M = E.POCKET_MOUTH, W2 = E.W / 2, TH2 = E.TH;
  const cushion = (pts) => {
    g.beginPath();
    g.moveTo(tx(pts[0][0]), ty(pts[0][1]));
    for (let i = 1; i < pts.length; i++) g.lineTo(tx(pts[i][0]), ty(pts[i][1]));
    g.closePath();
    const grad = g.createLinearGradient(tx(pts[0][0]), ty(pts[0][1]), tx(pts[2][0]), ty(pts[2][1]));
    grad.addColorStop(0, "#12805f"); grad.addColorStop(1, "#0a4433");
    g.fillStyle = grad; g.fill();
    g.strokeStyle = "rgba(0,0,0,.45)"; g.lineWidth = Math.max(1, 1.2 * sc); g.stroke();
    g.strokeStyle = "rgba(255,255,255,.16)"; g.lineWidth = Math.max(1, 1.4 * sc);
    g.beginPath(); g.moveTo(tx(pts[0][0]), ty(pts[0][1])); g.lineTo(tx(pts[1][0]), ty(pts[1][1])); g.stroke();
  };
  cushion([[M[0], 0], [W2 - M[1], 0], [W2 - M[1] - SJ, -CW], [M[0] + CJ, -CW]]);
  cushion([[W2 + M[1], 0], [E.W - M[2], 0], [E.W - M[2] - CJ, -CW], [W2 + M[1] + SJ, -CW]]);
  cushion([[M[3], TH2], [W2 - M[4], TH2], [W2 - M[4] - SJ, TH2 + CW], [M[3] + CJ, TH2 + CW]]);
  cushion([[W2 + M[4], TH2], [E.W - M[5], TH2], [E.W - M[5] - CJ, TH2 + CW], [W2 + M[4] + SJ, TH2 + CW]]);
  cushion([[0, M[0]], [0, TH2 - M[3]], [-CW, TH2 - M[3] - CJ], [-CW, M[0] + CJ]]);
  cushion([[E.W, M[2]], [E.W, TH2 - M[5]], [E.W + CW, TH2 - M[5] - CJ], [E.W + CW, M[2] + CJ]]);
  // each opening: the two jaw tips it spans, and the direction it falls away in
  const MOUTHS = [
    { tips: [[M[0], 0], [0, M[0]]], out: [-0.707, -0.707] },                       // top left
    { tips: [[W2 - M[1], 0], [W2 + M[1], 0]], out: [0, -1] },                      // top middle
    { tips: [[E.W, M[2]], [E.W - M[2], 0]], out: [0.707, -0.707] },                // top right
    { tips: [[0, TH2 - M[3]], [M[3], TH2]], out: [-0.707, 0.707] },                // bottom left
    { tips: [[W2 - M[4], TH2], [W2 + M[4], TH2]], out: [0, 1] },                   // bottom middle
    { tips: [[E.W - M[5], TH2], [E.W, TH2 - M[5]]], out: [0.707, 0.707] },         // bottom right
  ];
  MOUTHS.forEach((mo, i) => {
    const [a1, a2] = mo.tips;
    const mx = (a1[0] + a2[0]) / 2, my = (a1[1] + a2[1]) / 2, depth = 108;
    g.beginPath();
    g.moveTo(tx(a1[0]), ty(a1[1]));
    g.quadraticCurveTo(tx(mx + mo.out[0] * depth), ty(my + mo.out[1] * depth), tx(a2[0]), ty(a2[1]));
    g.closePath();
    g.fillStyle = "#05070a"; g.fill();
    g.strokeStyle = "rgba(0,0,0,.65)"; g.lineWidth = Math.max(1, 1.6 * sc); g.stroke();
    if (aim.call === i) { g.strokeStyle = "#00c9a7"; g.lineWidth = Math.max(2, 3 * sc); g.stroke(); }
  });
  if (!eng || eng.setup) return;

  const balls = shownBalls(eng);
  const live = !anim && !animQ.length && duel.canAct();
  // AIM ASSISTANCE, drawn from the simulation itself (see previewFor): the cue ball's real path — which
  // curves under English and stops where friction stops it — the ghost ball at the actual first contact,
  // and the object ball's real path. A separate ray-cast used to draw this, and it promised contacts the
  // physics never made.
  if (live && balls[0].on && assist > 0) {
    const pv = previewFor(eng);
    const poly = (pts, style, dash, width) => {
      if (!pts || pts.length < 4) return;
      g.strokeStyle = style; g.lineWidth = Math.max(1, width * sc); g.setLineDash(dash.map((d) => d * sc));
      g.beginPath(); g.moveTo(tx(pts[0]), ty(pts[1]));
      for (let i = 2; i < pts.length; i += 2) g.lineTo(tx(pts[i]), ty(pts[i + 1]));
      g.stroke(); g.setLineDash([]);
    };
    g.save();
    poly(pv.cuePath, "rgba(255,255,255,.72)", [9, 7], 1.6);
    if (assist >= 2 && pv.first >= 0 && pv.firstAt) {
      g.strokeStyle = "rgba(255,255,255,.55)"; g.lineWidth = Math.max(1, sc);
      g.beginPath(); g.arc(tx(pv.firstAt[0]), ty(pv.firstAt[1]), E.R * sc, 0, Math.PI * 2); g.stroke();
      const potted = pv.pots.some((x) => x.ball === pv.first);
      poly(pv.objPath, potted ? "rgba(120,240,170,.85)" : "rgba(255,220,120,.8)", [5, 5], 1.6);
    }
    g.restore();
  }
  if (live && balls[0].on) drawCue(g, sc, tx, ty, balls[0].x, balls[0].y, aim.angle, aim.power);
  // balls
  for (let i = 0; i < E.BALLS; i++) if (balls[i].on) drawBall(g, sc, i, tx(balls[i].x), ty(balls[i].y));
  // ball in hand: a dashed halo on the cue ball so the "you can move me" affordance is visible
  if (live && eng.inHand && balls[0].on) {
    g.save();
    g.setLineDash([5 * sc, 4 * sc]); g.strokeStyle = "#00c9a7"; g.lineWidth = Math.max(2, 2 * sc);
    g.beginPath(); g.arc(tx(balls[0].x), ty(balls[0].y), E.R * sc * 1.7, 0, Math.PI * 2); g.stroke();
    g.restore();
  }
  void gm;
}

function drawCue(g, sc, tx, ty, cx, cy, angle, power) {
  const ux = E.COS[angle] / 65536, uy = E.SIN[angle] / 65536;
  const back = E.R + 18 + power * 2.6;               // pull-back grows with power
  const len = 900;
  g.save();
  g.lineCap = "round";
  g.strokeStyle = "#c39a5f"; g.lineWidth = Math.max(2, 5 * sc);
  g.beginPath();
  g.moveTo(tx(cx - ux * back), ty(cy - uy * back));
  g.lineTo(tx(cx - ux * (back + len)), ty(cy - uy * (back + len)));
  g.stroke();
  g.strokeStyle = "#1d2630"; g.lineWidth = Math.max(2, 5.4 * sc);
  g.beginPath();
  g.moveTo(tx(cx - ux * (back + len * 0.62)), ty(cy - uy * (back + len * 0.62)));
  g.lineTo(tx(cx - ux * (back + len)), ty(cy - uy * (back + len)));
  g.stroke();
  g.restore();
}

// ---- the spin (English) widget -------------------------------------------------------------------------
function drawSpin(v) {
  const cv = $("spinPad"); if (!cv) return;
  v = v || aim;
  const g = cv.getContext("2d"), s = cv.width, r = s / 2 - 3;
  g.clearRect(0, 0, s, s);
  g.beginPath(); g.arc(s / 2, s / 2, r, 0, Math.PI * 2);
  g.fillStyle = "#f6f8fa"; g.fill();
  g.strokeStyle = "#8b98a6"; g.lineWidth = 1.5; g.stroke();
  g.strokeStyle = "rgba(0,0,0,.12)";
  g.beginPath(); g.moveTo(s / 2, 4); g.lineTo(s / 2, s - 4); g.moveTo(4, s / 2); g.lineTo(s - 4, s / 2); g.stroke();
  const px = s / 2 + (v.side / 3) * r * 0.78, py = s / 2 - (v.fwd / 3) * r * 0.78;
  g.beginPath(); g.arc(px, py, r * 0.2, 0, Math.PI * 2);
  g.fillStyle = "#d1372f"; g.fill();
  g.strokeStyle = "#7a1d17"; g.lineWidth = 1.5; g.stroke();
}

// ---- shot list: every legal pot the engine can see, as a one-tap aim -----------------------------------
function potOptions(eng, me) {
  const out = [];
  if (!eng || eng.over || !eng.b[0].on) return out;
  const cx = Math.trunc(eng.b[0].x / E.FP), cy = Math.trunc(eng.b[0].y / E.FP);
  for (const id of E.legalTargets(eng, me)) {
    const bx = Math.trunc(eng.b[id].x / E.FP), by = Math.trunc(eng.b[id].y / E.FP);
    for (let k = 0; k < 6; k++) {
      const a = E.ghostAim(eng, id, k);
      if (!a || a.cut < 13000) continue;                        // steeper than ~78° is not worth offering
      if (!E.pathClear(eng, cx, cy, bx, by, [0, id])) continue;
      if (!E.pathClear(eng, bx, by, E.POCKETS[k][0], E.POCKETS[k][1], [id])) continue;
      out.push({ id, pocket: k, angle: a.angle, cut: a.cut, dist: a.dist + a.potDist });
    }
  }
  out.sort((x, y) => (y.cut - x.cut) || (x.dist - y.dist));
  return out.slice(0, 8);
}

// ---- the game's own render ------------------------------------------------------------------------------
function renderGame(gm, eng) {
  const zone = $("tableZone");
  if (!eng || eng.setup || gm.nn !== 2) {
    zone.classList.add("hidden");
    $("shotBar").classList.add("hidden");
    return;
  }
  zone.classList.remove("hidden");
  // WATCHDOG. The shot bar is gated behind playback, so an animation that never finishes takes the whole
  // instrument with it — the turn badge says it is your shot and there is nothing to shoot with. Two ways
  // that happens: requestAnimationFrame does not fire in a background tab (switch away mid-shot and the
  // loop simply stops), and a thrown render would kill the loop outright. This runs on every render, and
  // refreshActive() renders at least every 3s, so an overdue animation is always cleaned up. The clock is
  // Date.now(), not the rAF timestamp, precisely because rAF may never have run.
  if (anim && Date.now() - anim.born > anim.dur + 3000) stopAnim();
  const me = duel.myIdx(gm);
  const busy = !!(anim || animQ.length);
  const mine = duel.canAct() && !busy;
  // playback is driven by queueShot() at the point each shot is APPLIED (practice apply / incremental
  // replay), not from here — render must never decide what to animate, or a re-render mid-shot restarts it
  drawTable(eng, gm);
  drawSpin(anim && anim.shot ? anim.shot : aim);

  // heads-up: group, remaining balls, foul state
  const grpName = (g) => g === 0 ? T("solids", "solids") : g === 1 ? T("stripes", "stripes") : T("open", "open table");
  const myGroup = me == null ? -1 : eng.grp[me];
  const tgt = me == null ? -1 : E.targetGroup(eng, me);
  // gm.practice seats a literal "cpu" as p2. disp() now returns non-address values verbatim (see
  // shortAddr in nadodapp.js), but the practice opponent still gets a proper localised name.
  const oppName = gm.practice ? (window.t ? window.t("sdk.prCpu", "Computer") : "Computer")
                              : disp(anim && anim.side === 0 ? gm.p1 : gm.p2);
  // Whose shot is on screen. Without this, your break and the opponent's reply play one after the other
  // with nothing between them and it reads as a single shot repeating.
  const replay = !anim ? ""
    : '<span class="stat" style="border-color:var(--gold);color:var(--gold)">'
      + (anim.side === me ? T("replayYours", "▶ replaying your shot")
         : T("replayTheirs", "▶ {who}'s shot", { who: oppName })) + "</span>";
  $("hud").innerHTML =
    '<span class="turnbadge">' + (eng.over ? T("frameOver", "FRAME OVER")
      : busy ? T("watching", "WATCHING")
      : mine ? T("yourShot", "YOUR SHOT")
      : eng.turn === me ? T("yourShotWait", "YOUR SHOT — syncing…")
      : T("theirShot", "THEIR SHOT")) + "</span>"
    + replay
    + '<span class="stat">' + T("youAre", "You're on") + " <b>" + (eng.open ? grpName(-1) : grpName(myGroup)) + "</b></span>"
    + '<span class="stat">' + T("ballsLeft", "Left") + " <b>" + (eng.open ? 15 - eng.log.reduce((n, r) => n + r.pots.filter((p) => p.ball !== 0).length, 0)
        : E.remaining(eng, myGroup) || T("theEight", "the 8")) + "</b></span>"
    + (eng.inHand && eng.turn === me && !busy ? '<span class="stat" style="border-color:#00c9a7;color:#00c9a7">' + T("ballInHand", "BALL IN HAND — drag the cue ball") + "</span>" : "");

  // the shot log
  const rows = eng.log.slice(-6).map((r, i) => {
    const n = eng.log.length - Math.min(6, eng.log.length) + i + 1;
    const who = gm.practice ? (r.side === 0 ? T("you", "You") : oppName)
                            : disp(r.side === 0 ? gm.p1 : gm.p2);   // disp() is an address shortener
    const pots = r.pots.filter((p) => p.ball !== 0).map((p) => p.ball).join(", ");
    const bits = [];
    if (pots) bits.push(T("potted", "potted {b}", { b: pots }));
    if (r.foul) bits.push("⚠ " + T("foul_" + r.foul, r.foul));
    if (!bits.length) bits.push(T("nothingDown", "nothing down"));
    return '<div><span class="dim">' + n + ".</span> " + who + " — " + bits.join(" · ") + "</div>";
  }).join("");
  $("shotLog").innerHTML = rows || '<span class="dim">' + T("noShots", "No shots yet — the break is up.") + "</span>";

  // THE SHOT BAR. While a shot is replaying it stays on screen but goes read-only and shows THAT shot's
  // settings — angle, power, English — so you can see exactly how your opponent (or the computer) played
  // it, instead of watching balls move with no idea what was struck.
  const bar = $("shotBar");
  const replaying = !!(anim && anim.shot);
  const showBar = mine || replaying;
  bar.classList.toggle("hidden", !showBar);
  // The enabled state is applied on EVERY render, before any early return. Returning early used to leave
  // the controls disabled from the last replay, so the panel could come back on your own turn visible but
  // frozen — the instrument is there and nothing responds.
  $("powerRange").disabled = replaying;
  for (const id of ["btnAimL10", "btnAimL1", "btnAimR1", "btnAimR10", "btnSpinClear"]) {
    const b2 = $(id); if (b2) b2.disabled = replaying;
  }
  if (!showBar) return;
  const shown = replaying ? anim.shot : aim;
  $("powerVal").textContent = Math.round((shown.power / 63) * 100) + "%";
  $("powerRange").value = String(shown.power);
  $("angleVal").textContent = ((shown.angle * 360) / 4096).toFixed(1) + "°";
  if ($("assistRange")) { $("assistRange").value = String(assist); $("assistVal").textContent = assistName(); }
  if (replaying) {
    $("callRow").classList.add("hidden");
    $("potBtns").innerHTML = '<span class="dim small">'
      + (anim.side === me ? T("replayYours", "▶ replaying your shot")
         : T("replayTheirs", "▶ {who}'s shot", { who: oppName }))
      + " · " + T("replaySpin", "English {sx}/{sy}", { sx: shown.side, sy: shown.fwd }) + "</span>";
    const sb = $("btnShoot");
    sb.disabled = true;
    sb.classList.remove("pulse");
    sb.textContent = T("replayWait", "▶ watching the shot…");
    return;
  }

  // called pocket — required only when the 8 is the target
  const needCall = tgt === 2;
  $("callRow").classList.toggle("hidden", !needCall);
  if (needCall) {
    $("callBtns").innerHTML = E.POCKET_NAMES.map((n, i) =>
      '<button class="chip' + (aim.call === i ? " open" : "") + '" data-call="' + i + '">' + T("pocket_" + i, n) + "</button>").join(" ");
    $("callBtns").querySelectorAll("[data-call]").forEach((b) => b.onclick = () => { aim.call = parseInt(b.dataset.call, 10); duel.render(); });
  }

  // one-tap aim at any pot the engine can see
  const opts = potOptions(eng, me);
  $("potBtns").innerHTML = opts.length
    ? opts.map((o, i) => '<button class="chip" data-pot="' + i + '">' + T("aimAt", "{b} → {p}", { b: o.id, p: T("pocket_" + o.pocket, E.POCKET_NAMES[o.pocket]) }) + "</button>").join(" ")
    : '<span class="dim small">' + T("noPots", "Nothing on — play safe: hit a legal ball and reach a cushion.") + "</span>";
  $("potBtns").querySelectorAll("[data-pot]").forEach((b) => b.onclick = () => {
    const o = opts[parseInt(b.dataset.pot, 10)];
    aim.angle = o.angle;
    if (E.targetGroup(eng, me) === 2) aim.call = o.pocket;
    duel.render();
  });

  const shoot = $("btnShoot");
  shoot.disabled = needCall && aim.call == null;
  shoot.textContent = needCall && aim.call == null ? T("pickPocket", "Call a pocket for the 8 first")
    : duel.armed && duel.armed.key === "shoot" ? duel.armed.label : T("takeShot", "🎱 Take the shot");
  shoot.classList.toggle("pulse", !!(duel.armed && duel.armed.key === "shoot"));
}

// ---- playback ------------------------------------------------------------------------------------------
// Three things this has to get right, all of them learned from watching it get them wrong:
//
//  * SPEED IS REAL TIME, not a normalised duration. Stretching every shot over the same number of
//    animation frames made a full-blooded break rush past while a gentle safety crawled — the two were
//    played at wildly different rates from the same simulation. Playback is driven by the WALL CLOCK at a
//    fixed frames-per-second, so a long shot takes longer than a short one, exactly as it should, and a
//    slow device gets the same duration (just choppier) instead of a slow-motion replay.
//    That clock is also what KILLED the double-speed bug: playback used to advance a frame counter once
//    per rAF, so a stale loop left behind by an interrupted animation would step the next one as well —
//    two loops on one shot, compounding with every interruption. Position is now a function of elapsed
//    time, so an extra loop cannot make anything run faster.
//  * EVERY ANIMATION STILL CARRIES A GENERATION, so a stale loop stops rather than burning renders for
//    an animation nobody is watching.
//  * SHOTS ARE LABELLED AND SEPARATED. Your break and the opponent's reply arrive together and used to
//    play back to back, unannounced, which reads as one shot playing twice. Each playback names whose
//    shot it is and a short beat separates them.
const PLAY_FPS = 110;                              // recorded frames (FRAME_TICKS sim ticks each) per second
const PLAY_MIN_MS = 700, PLAY_MAX_MS = 8000;       // a tap is still watchable; a monster shot still ends
const BEAT_MS = 420;                               // pause between two queued shots
let animGen = 0;

// queueShot(mi, frames, side, shot): hand one shot to the player, in order. `mi` dedupes — the engine is
// rebuilt many times per shot and must not re-queue one that already played.
function queueShot(mi, frames, side, shot) {
  if (!frames || frames.length < 2 || mi <= queuedUpTo) return;
  queuedUpTo = mi;
  // `shot` and `from` are what let the replay show the OPPONENT's instruments — their angle, power
  // and English — instead of leaving the panel blank while their shot rolls.
  animQ.push({ frames, side, shot, from: [frames[0][0], frames[0][1]] });
  if (!anim) playNext();
}
function stopAnim() { anim = null; animQ = []; animGen++; }
function playNext() {
  const next = animQ.shift();
  if (!next) { anim = null; animGen++; duel.render(); return; }
  const gen = ++animGen, len = next.frames.length;
  const dur = Math.max(PLAY_MIN_MS, Math.min(PLAY_MAX_MS, (len * 1000) / PLAY_FPS));
  anim = { frames: next.frames, side: next.side, shot: next.shot, from: next.from,
           i: 0, gen, t0: null, dur, born: Date.now() };
  playLog.push({ n: len, dur, side: next.side, t: Date.now() });
  const tick = (now) => {
    if (!anim || anim.gen !== gen) return;         // a newer animation (or a reset) owns the screen now
    if (anim.t0 == null) anim.t0 = now;
    const p = Math.min(1, (now - anim.t0) / anim.dur);
    anim.i = Math.min(len - 1, Math.floor(p * (len - 1)));
    try { duel.render(); } catch (e) { /* a render fault must not kill playback — see the watchdog */ }
    if (p >= 1) { setTimeout(() => { if (anim && anim.gen === gen) playNext(); }, BEAT_MS); return; }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

// ---- input ---------------------------------------------------------------------------------------------
function onPointer(ev, phase) {
  const eng = duel.eng;
  if (!eng || eng.setup || !duel.canAct() || anim || animQ.length) return;
  const [ux, uy] = pointerUnits(ev);
  const cx = Math.trunc(eng.b[0].x / E.FP), cy = Math.trunc(eng.b[0].y / E.FP);
  if (phase === "down" && eng.inHand) {
    const dx = ux - cx, dy = uy - cy;
    if (dx * dx + dy * dy < (E.R * 3) * (E.R * 3)) dragging = "cue";
  }
  if (dragging === "cue") {
    ev.preventDefault();
    // move the cue ball live; the engine's own placement rules decide where it actually lands
    E.placeCue(eng, ux, uy, eng.breakShot);
    const [px, py] = E.xyToPlace(Math.trunc(eng.b[0].x / E.FP), Math.trunc(eng.b[0].y / E.FP));
    aim.px = px; aim.py = py;
    if (phase === "up") dragging = null;
    duel.render();
    return;
  }
  if (phase === "down" || phase === "move") {
    if (phase === "move" && !ev.buttons && !(ev.touches && ev.touches.length)) return;
    ev.preventDefault();
    aim.angle = E.angleOf(ux - cx, uy - cy);
    duel.render();
  }
}

function takeShot() {
  const eng = duel.eng;
  if (!eng || !duel.canAct()) return;
  const me = duel.myIdx(duel.last);
  if (E.targetGroup(eng, me) === 2 && aim.call == null) return notify(T("mustCall", "Call the pocket you're putting the 8 in."));
  const shot = currentShot(eng);          // exactly what the preview line was drawn from
  aim.px = null; aim.py = null;
  duel.submit(1, E.shotPayload(shot), T("shotLabel", "shot at {a}°", { a: ((shot.angle * 360) / 4096).toFixed(0) }));
}

function wireTable() {
  const cv = $("table");
  cv.addEventListener("pointerdown", (e) => { cv.setPointerCapture(e.pointerId); onPointer(e, "down"); });
  cv.addEventListener("pointermove", (e) => onPointer(e, "move"));
  cv.addEventListener("pointerup", (e) => onPointer(e, "up"));
  cv.addEventListener("pointercancel", () => { dragging = null; });
  $("powerRange").oninput = (e) => { aim.power = Math.max(0, Math.min(63, parseInt(e.target.value, 10) || 0)); duel.render(); };
  for (const [id, d] of [["btnAimL10", -10], ["btnAimL1", -1], ["btnAimR1", 1], ["btnAimR10", 10]]) {
    $(id).onclick = () => { aim.angle = (aim.angle + d + 4096) & 4095; duel.render(); };
  }
  const sp = $("spinPad");
  const setSpin = (e) => {
    const r = sp.getBoundingClientRect();
    const p = e.touches && e.touches[0] ? e.touches[0] : e;
    const nx = ((p.clientX - r.left) / r.width) * 2 - 1, ny = 1 - ((p.clientY - r.top) / r.height) * 2;
    aim.side = Math.max(-3, Math.min(3, Math.round(nx * 3.6)));
    aim.fwd = Math.max(-3, Math.min(3, Math.round(ny * 3.6)));
    duel.render();
  };
  sp.addEventListener("pointerdown", (e) => { sp.setPointerCapture(e.pointerId); setSpin(e); });
  sp.addEventListener("pointermove", (e) => { if (e.buttons) setSpin(e); });
  $("btnSpinClear").onclick = () => { aim.side = 0; aim.fwd = 0; duel.render(); };
  // shooting is arm-then-fire: a stray tap must never spend a shot (and a transaction)
  $("btnShoot").onclick = () => duel.arm("shoot", T("tapAgainShoot", "Tap again to shoot"), takeShot);
  const as = $("assistRange");
  if (as) { as.value = String(assist); as.oninput = (e) => { setAssist(parseInt(e.target.value, 10) || 0); duel.render(); }; }
}

duel.boot(["activeGame", "lobby", "play", "walletcard", "bankroll", "scoreboard"]).catch(() => {});

// ONE mode picker, from the SDK — identical to every other game.
const modes = installModes(dapp, {
  modes: [
    { key: "play", icon: "⚔", label: window.t("pool.modePlay", "Play a frame"),
      hint: window.t("pool.modePlayHint", "Head-to-head against another player — for stakes, or for nothing at all."),
      cards: ["lobby", "play", "scoreboard"], keep: ["activeGame"] },
    { key: "practice", icon: "🎯", label: window.t("sdk.modePractice", "Practice"),
      badge: window.t("sdk.free", "free"),
      hint: window.t("sdk.modePracticeHint", "Play the computer in your browser — nothing on-chain."),
      cards: ["practice"], keep: ["activeGame"] },
  ],
});
const _duelRender = duel.render.bind(duel);
duel.render = function () { _duelRender(); modes.apply(); };
modes.apply();

// test hook: the UI E2E harness drives the real DOM against crafted engine states
if (typeof window !== "undefined") {
  window.__duel = duel;
  window.__pool = { aim, E, playLog, busy: () => !!(anim || animQ.length), queued: () => animQ.length,
                    assist: () => assist, setAssist, side: () => (anim ? anim.side : null),
                    at: () => (anim ? [anim.i, anim.frames.length, anim.dur] : null),
                    shown: () => (duel.eng ? shownBalls(duel.eng) : null) };
}
