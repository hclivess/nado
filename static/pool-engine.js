// pool-engine.js — the full rules engine for NADO Pool: 8-ball, 1v1, deterministic and headless-testable
// (browser + node). Two halves:
//
//   1. A FIXED-POINT INTEGER PHYSICS SIMULATION. Consensus needs bit-identical results in every browser,
//      so NOTHING here is a float. Positions and velocities are fixed-point integers; the only division
//      is on products that provably stay under 2^53; square roots are an exact integer isqrt (Newton-
//      seeded, then corrected until r² ≤ n < (r+1)², so a differently-rounded Math.sqrt cannot change the
//      answer); and the sine table is built once from a BigInt Taylor series over a single hard-coded π/2
//      constant — Math.sin/Math.cos are NOT specified to be identical across engines and are never called.
//      Two clients replaying the same log therefore rack up the same table, ball for ball, to the unit.
//
//   2. THE 8-BALL RULESET. Break, open table, group assignment on the first legal pot, first-contact and
//      cushion-after-contact fouls, ball-in-hand on any foul, and the called-pocket 8-ball ending
//      (pocket it in the nominated pocket to win; early, wrong-pocket, or scratched-on = loss).
//
// MOVE ENCODING — one shot is one log entry, enc = op + payload·16 (the duelgame.js convention):
//   op 1 SHOT  payload bits: 0..11 angle (0..4095, CCW from +x)   12..17 power (0..63)
//                            18..20 sideSpin+3   21..23 fwdSpin+3   24..26 called pocket (0..5, 7=none)
//                            27..37 placeX (0..2047)   38..47 placeY (0..1023)   [placement used only
//                            when the shooter has ball in hand — otherwise ignored]
//   payload < 2^48, so enc < 2^52 and the value survives JSON's 2^53 integer range intact.
//
// The RACK is seeded by the join-time future block height kh (stormhold's scheme): HASH(bh(kh)+bh(kh+1)
// + salt + i) drives a Fisher-Yates shuffle, so neither player can grind a favourable break.
import { blake2bHash } from "./nadotx.js?v=a686fd33";

const H = (v) => BigInt("0x" + blake2bHash(v));

// ---- table geometry (units ≈ mm on a 9-foot table) --------------------------------------------------
export const FP = 1024;                       // position fixed-point scale (Q10)
export const VFP = 16384;                     // VELOCITY scale (Q14) — see `decay` below for why it is finer
export const W = 2540, TH = 1270;             // playing surface, cushion to cushion
export const R = 28;                          // ball radius (57 mm balls)
export const HEAD_X = 635;                    // head string — the break must be taken from behind it
export const FOOT_X = 1905, FOOT_Y = 635;     // foot spot: the rack apex, and where a potted 8 re-spots
export const BALLS = 16;                      // 0 = cue, 1..7 solids, 8 = the eight, 9..15 stripes
export const SOLIDS = 0, STRIPES = 1;
// pocket centres, indexed 0..5 — the called-pocket field on an 8-ball shot addresses this array
export const POCKETS = [[0, 0], [W / 2, 0], [W, 0], [0, TH], [W / 2, TH], [W, TH]];
export const POCKET_NAMES = ["top left", "top middle", "top right", "bottom left", "bottom middle", "bottom right"];

// Capture radius per pocket, measured to the ball's CENTRE. Corners are bigger than middles, as they are
// on a real table. Everything visual is derived from these (see POCKET_MOUTH) so the opening you see is
// exactly the opening the physics uses — they used to be set independently, and the drawn holes bulged
// onto the cloth while the real mouth sat somewhere else.
export const POCKET_RS = [76, 62, 76, 76, 62, 76];
export const POCKET_R = 76;                   // the widest — for coarse "is this near any pocket" checks

// A pocket is not a circular trapdoor. It faces a DIRECTION — corners open along the diagonal, side
// pockets square to the rail — and a ball only drops if it is travelling into that opening. Modelling
// them as plain proximity circles let a ball running along a cushion get swallowed by the side pocket it
// should have sailed straight past, and let corners accept a ball leaving them. Facings are Q16 unit
// vectors pointing the way a ball travels to go IN; the cosines are how far off that line still drops
// (corners are forgiving at ~75°, side pockets much less so at ~60°, which is what rejects rail-runners).
const POCKET_FACE = [[-46341, -46341], [0, -65536], [46341, -46341],
                     [-46341, 46341], [0, 65536], [46341, 46341]];
const POCKET_COS = [17000, 32768, 17000, 17000, 32768, 17000];

// ---- simulation constants (tuned by tests/pool_js_test.mjs, all integers) ---------------------------
const ROLL = 4090, ROLL_D = 4096;             // per-tick rolling friction ≈ 0.998535
const CUSH = 880;                             // cushion restitution (Q10) ≈ 0.859
const REST = 1966;                            // 1 + ball-ball restitution (Q10·(1+e), e ≈ 0.92)
// Resting threshold (Q14 speed). It must sit ABOVE the per-component rounding stall (341, see `decay`)
// scaled to a diagonal — with both components stalled the magnitude reaches 482, and a ball whose
// components both stopped decaying would otherwise roll for ever. 512 clears that with margin.
const STOP = 512;
const SPIN_DECAY = 995, SPIN_D = 1024;        // per-tick spin decay ≈ 0.9717
const SPIN_K = 40;                            // spin → acceleration coupling (numerator over 1024)
const MAX_TICKS = 30000;                      // hard bound: a shot always terminates
export const FRAME_TICKS = 6;                 // ticks per recorded animation frame (cosmetic only)
export const V_MIN = 4800, V_STEP = 2819;     // shot speed (Q14/tick) = V_MIN + power·V_STEP

// Two rounding rules that between them decide whether a soft shot behaves at all:
//
//  * decay() rounds to NEAREST, symmetrically. `trunc` biases every tick toward zero by up to one unit,
//    a constant drag on top of the exponential one — invisible on a break, but it swallowed two thirds
//    of a delicate safety's roll.
//  * velocity is carried at Q14 while position is Q10, and that is not decoration. Round-to-nearest
//    friction STALLS once one tick's decrement falls below half a unit: at Q10 that happens at speed
//    341, well above the resting threshold, so slow balls would roll for ever. Four extra fractional
//    bits push the stall point (21 in Q10 terms) safely below the stop threshold.
const decay = (v, num, den) => { const t = v * num; return t < 0 ? -Math.round(-t / den) : Math.round(t / den); };
const vstep = (v) => (v < 0 ? -Math.round(-v / 16) : Math.round(v / 16));   // Q14 velocity → Q10 position step
const trunc = Math.trunc;

// ---- exact integer square root ---------------------------------------------------------------------
// Math.sqrt is used only as a SEED. The correction loops make the result exact and therefore identical
// on every engine, whatever the seed rounded to.
export function isqrt(n) {
  if (n <= 0) return 0;
  let r = Math.floor(Math.sqrt(n));
  if (!(r >= 0)) r = 0;
  while (r > 0 && r * r > n) r--;
  while ((r + 1) * (r + 1) <= n) r++;
  return r;
}

// The half-width of each opening measured ALONG the rail, at the line a ball's centre travels on when it
// is against the cushion. This is the mouth: outside it the rail is solid, inside it a ball can drop.
// The renderer ends the cushions here, so what you see is what the physics does.
export const POCKET_MOUTH = POCKET_RS.map((r) => isqrt(r * r - R * R));

// pocketed(p, k): would ball `p` go down pocket `k` right now? Position AND heading, both.
function pocketed(p, k) {
  const dx = trunc(p.x / FP) - POCKETS[k][0], dy = trunc(p.y / FP) - POCKETS[k][1];
  const d2 = dx * dx + dy * dy, rk = POCKET_RS[k];
  if (d2 > rk * rk) return false;
  const sp = isqrt(p.vx * p.vx + p.vy * p.vy);
  if (sp < STOP) return d2 <= (rk * rk) / 4;          // sitting well down in the jaws — it drops
  const dot = p.vx * POCKET_FACE[k][0] + p.vy * POCKET_FACE[k][1];
  return dot >= POCKET_COS[k] * sp;                    // heading into the opening, not merely near it
}

// ---- the trig table, built from integers only -------------------------------------------------------
// sin over [0, π/2] at Q16, 1025 samples, from a BigInt Taylor series over one hard-coded constant.
// Every operation is exact integer arithmetic, so the table is byte-identical in every JS engine.
const QB = 1n << 40n;
const PI_HALF = 1727108826179n;               // round(π/2 · 2^40)
function sinQ40(x) {                          // x ∈ [0, π/2] at Q40 → sin(x) at Q40
  let term = x, sum = x;
  for (let n = 1; n <= 12; n++) {
    term = -(((term * x) / QB) * x) / QB / BigInt(2 * n * (2 * n + 1));
    if (term === 0n) break;
    sum += term;
  }
  return sum;
}
const QUARTER = (() => {
  const q = new Int32Array(1025);
  for (let i = 0; i <= 1024; i++) q[i] = Number((sinQ40((PI_HALF * BigInt(i)) / 1024n) * 65536n) / QB);
  return q;
})();
export const SIN = new Int32Array(4096), COS = new Int32Array(4096);
for (let a = 0; a < 4096; a++) {
  const quad = a >> 10, r = a & 1023;
  SIN[a] = quad === 0 ? QUARTER[r] : quad === 1 ? QUARTER[1024 - r] : quad === 2 ? -QUARTER[r] : -QUARTER[1024 - r];
  COS[a] = quad === 0 ? QUARTER[1024 - r] : quad === 1 ? -QUARTER[r] : quad === 2 ? -QUARTER[1024 - r] : QUARTER[r];
}
// angleOf(dx, dy): the 0..4095 angle index closest to the vector (dx, dy). The comparison is the EXACT
// integer cross product COS[a]·dy − SIN[a]·dx — proportional to sin(θ − a), so it is strictly monotone
// across the vector's quadrant and crosses zero exactly at the answer. (A dot-product search looks
// simpler but is useless here: near its maximum the dot product is flat to within the Q16 rounding of
// the direction vector, which put the "best" angle several steps off the true one.)
export function angleOf(dx, dy) {
  if (dx === 0 && dy === 0) return 0;
  const q = dx >= 0 ? (dy >= 0 ? 0 : 3) : (dy >= 0 ? 1 : 2);
  const cross = (a) => COS[a & 4095] * dy - SIN[a & 4095] * dx;
  let lo = q * 1024, hi = lo + 1024;                       // cross(lo) ≥ 0 ≥ cross(hi) by construction
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (cross(mid) >= 0) lo = mid; else hi = mid;
  }
  return (Math.abs(cross(lo)) <= Math.abs(cross(hi)) ? lo : hi) & 4095;
}

// ---- move encoding ----------------------------------------------------------------------------------
const P2 = (n) => Math.pow(2, n);
export function encShot(s) {
  const angle = s.angle & 4095, power = Math.max(0, Math.min(63, s.power | 0));
  const side = Math.max(-3, Math.min(3, s.side | 0)) + 3, fwd = Math.max(-3, Math.min(3, s.fwd | 0)) + 3;
  const call = s.call == null ? 7 : Math.max(0, Math.min(7, s.call | 0));
  const px = Math.max(0, Math.min(2047, s.px | 0)), py = Math.max(0, Math.min(1023, s.py | 0));
  const payload = angle + power * P2(12) + side * P2(18) + fwd * P2(21) + call * P2(24)
                + px * P2(27) + py * P2(38);
  return 1 + payload * 16;
}
// shotPayload(s): what duelgame.submit(op, payload) wants — enc = 1 + payload·16, so payload is the
// encoding without its op nibble.
export const shotPayload = (s) => (encShot(s) - 1) / 16;
export function decShot(enc) {
  const op = enc % 16, payload = Math.floor(enc / 16);
  const at = (sh, bits) => Math.floor(payload / P2(sh)) % P2(bits);
  return { op, angle: at(0, 12), power: at(12, 6), side: at(18, 3) - 3, fwd: at(21, 3) - 3,
           call: at(24, 3), px: at(27, 11), py: at(38, 10) };
}
// placement encoding: the 11/10-bit grid maps onto the legal cue-ball rectangle (≈1.2 mm per step)
export const placeToXY = (px, py) => [R + trunc((px * (W - 2 * R)) / 2047), R + trunc((py * (TH - 2 * R)) / 1023)];
export const xyToPlace = (x, y) => [Math.max(0, Math.min(2047, Math.round(((x - R) * 2047) / (W - 2 * R)))),
                                    Math.max(0, Math.min(1023, Math.round(((y - R) * 1023) / (TH - 2 * R))))];

// ---- state ------------------------------------------------------------------------------------------
export const isSolid = (i) => i >= 1 && i <= 7;
export const isStripe = (i) => i >= 9 && i <= 15;
export const groupOf = (i) => (isSolid(i) ? SOLIDS : isStripe(i) ? STRIPES : -1);

function corrupt(st, why) { st.corrupt = true; st.corruptWhy = why; return st; }

// rack(q): the 15-ball triangle. The 8 is fixed at the centre of the third row and the two back corners
// must be one solid and one stripe; everything else is shuffled from the join-time block hash.
function rackOrder(q) {
  const rest = [];
  for (let i = 1; i <= 15; i++) if (i !== 8) rest.push(i);
  if (q != null) {                                   // Fisher-Yates over the shared chain-draw formula
    for (let i = rest.length - 1; i > 0; i--) {
      const j = Number(H(q + BigInt(1000 + i)) % BigInt(i + 1));
      const t = rest[i]; rest[i] = rest[j]; rest[j] = t;
    }
  }
  const slots = new Array(15).fill(0);               // row-major; slot 4 (row 2, middle) is the 8
  slots[4] = 8;
  let k = 0;
  for (let s = 0; s < 15; s++) if (s !== 4) slots[s] = rest[k++];
  // legal rack: the two back corners (slots 10 and 14) are one solid, one stripe
  if (groupOf(slots[10]) === groupOf(slots[14])) {
    const want = 1 - groupOf(slots[10]);
    for (let s = 0; s < 15; s++) {
      if (s === 4 || s === 10 || s === 14) continue;
      if (groupOf(slots[s]) === want) { const t = slots[s]; slots[s] = slots[14]; slots[14] = t; break; }
    }
  }
  return slots;
}

export function init(g, q) {
  const b = [];
  for (let i = 0; i < BALLS; i++) b.push({ x: 0, y: 0, vx: 0, vy: 0, on: true });
  b[0].x = (HEAD_X / 2) * FP; b[0].y = FOOT_Y * FP;
  const slots = rackOrder(q);
  let s = 0;
  for (let row = 0; row < 5; row++) {
    for (let k = 0; k <= row; k++, s++) {
      const id = slots[s];
      b[id].x = (FOOT_X + row * 50) * FP;
      b[id].y = (FOOT_Y + (2 * k - row) * 29) * FP;
    }
  }
  return { g, b, turn: 0, open: true, grp: [-1, -1], broke: false, inHand: true, breakShot: true,
           over: false, result: 0, corrupt: false, corruptWhy: "", mi: 0, log: [], last: null,
           blocked: false, blockedAt: -1 };
}

// ---- physics ----------------------------------------------------------------------------------------
// placeCue(st, x, y): drop the cue ball at (x, y) in TABLE units, pushed off any ball it would overlap.
// Deterministic and total — a placement can never brick a game, it only ever ends up somewhere legal.
export function placeCue(st, x, y, kitchen) {
  const lo = R, hi = kitchen ? HEAD_X - R : W - R;
  x = Math.max(lo, Math.min(hi, x)); y = Math.max(R, Math.min(TH - R, y));
  const clash = (cx, cy) => {
    for (let i = 1; i < BALLS; i++) {
      if (!st.b[i].on) continue;
      const dx = cx - trunc(st.b[i].x / FP), dy = cy - trunc(st.b[i].y / FP);
      if (dx * dx + dy * dy < (2 * R + 1) * (2 * R + 1)) return true;
    }
    for (let k = 0; k < POCKETS.length; k++) {        // never place inside a pocket's mouth
      const dx = cx - POCKETS[k][0], dy = cy - POCKETS[k][1];
      if (dx * dx + dy * dy < POCKET_RS[k] * POCKET_RS[k]) return true;
    }
    return false;
  };
  if (clash(x, y)) {                                 // deterministic outward spiral to the nearest free spot
    outer: for (let ring = 1; ring <= 60; ring++) {
      for (let a = 0; a < 4096; a += 128) {
        const cx = Math.max(lo, Math.min(hi, x + trunc((COS[a] * ring * 12) / 65536)));
        const cy = Math.max(R, Math.min(TH - R, y + trunc((SIN[a] * ring * 12) / 65536)));
        if (!clash(cx, cy)) { x = cx; y = cy; break outer; }
      }
    }
  }
  st.b[0].x = x * FP; st.b[0].y = y * FP; st.b[0].vx = 0; st.b[0].vy = 0; st.b[0].on = true;
  return st;
}

// respot(st, id): put a ball back on the foot spot (or the first free point behind it) — used for an 8
// pocketed on the break, which is not a loss under these rules.
function respot(st, id) {
  const free = (cx, cy) => {
    for (let i = 0; i < BALLS; i++) {
      if (i === id || !st.b[i].on) continue;
      const dx = cx - trunc(st.b[i].x / FP), dy = cy - trunc(st.b[i].y / FP);
      if (dx * dx + dy * dy < (2 * R + 1) * (2 * R + 1)) return false;
    }
    return true;
  };
  let x = FOOT_X;
  const y = FOOT_Y;
  for (let step = 0; step <= 200 && !free(x, y); step++) x = Math.min(W - R, FOOT_X + step * 6);
  st.b[id].on = true; st.b[id].x = x * FP; st.b[id].y = y * FP; st.b[id].vx = 0; st.b[id].vy = 0;
}

// simulate(st, shot, wantFrames, wantPaths): run one shot to a complete stop. Mutates the ball array and
// returns the event record the ruleset judges, plus (optionally) animation frames and preview polylines —
// both cosmetic, never fed back into state.
export function simulate(st, shot, wantFrames, wantPaths) {
  const b = st.b;
  const v0 = V_MIN + shot.power * V_STEP;
  const a = shot.angle & 4095;
  b[0].vx = trunc((v0 * COS[a]) / 65536);
  b[0].vy = trunc((v0 * SIN[a]) / 65536);
  // spin rides as a VECTOR so draw/follow survive the object-ball collision: forward spin points along
  // the shot line (negative = screw back), side spin acts perpendicular to it.
  let spinFx = trunc((shot.fwd * v0 * COS[a]) / (65536 * 20));
  let spinFy = trunc((shot.fwd * v0 * SIN[a]) / (65536 * 20));
  let spinSx = trunc((-shot.side * v0 * SIN[a]) / (65536 * 30));
  let spinSy = trunc((shot.side * v0 * COS[a]) / (65536 * 30));

  const ev = { first: -1, firstAt: null, pots: [], rail: false, railAfterContact: false,
               objectRails: 0, cueScratch: false, cuePath: null, objPath: null,
               firstSample: null, railSample: null };
  if (wantPaths) { ev.cuePath = []; ev.objPath = []; }
  let railed = 0;                              // bitmask of balls that reached a cushion (break legality)
  let cueRails = 0, objRails = 0;              // cushion counts, used to trim the preview polylines
  const frames = wantFrames ? [] : null;
  const snap = () => {
    const f = new Int32Array(BALLS * 2);
    for (let i = 0; i < BALLS; i++) { f[i * 2] = b[i].on ? trunc(b[i].x / FP) : -1; f[i * 2 + 1] = b[i].on ? trunc(b[i].y / FP) : -1; }
    frames.push(f);
  };
  if (frames) snap();

  const RR = 2 * R * FP, RR2 = RR * RR;
  // Only MOVING balls are integrated, pocketed, bounced or collided — a table settles to one or two
  // rolling balls within a few hundred ticks, and walking all 120 pairs for the remaining few thousand
  // was most of a whole game's replay cost.
  const mv = new Int32Array(BALLS), isMoving = new Uint8Array(BALLS);
  for (let tick = 0; tick < MAX_TICKS; tick++) {
    let nm = 0;
    isMoving.fill(0);
    for (let i = 0; i < BALLS; i++) {
      if (!b[i].on || (b[i].vx === 0 && b[i].vy === 0)) continue;
      mv[nm++] = i; isMoving[i] = 1;
    }
    if (nm === 0) break;
    // integrate + spin acceleration
    for (let k = 0; k < nm; k++) {
      const i = mv[k], p = b[i];
      if (i === 0) {
        p.vx += trunc((spinFx * SPIN_K) / 1024) + trunc((spinSx * SPIN_K) / 1024);
        p.vy += trunc((spinFy * SPIN_K) / 1024) + trunc((spinSy * SPIN_K) / 1024);
      }
      p.x += vstep(p.vx); p.y += vstep(p.vy);
      p.vx = decay(p.vx, ROLL, ROLL_D); p.vy = decay(p.vy, ROLL, ROLL_D);
      if (p.vx * p.vx + p.vy * p.vy < STOP * STOP) { p.vx = 0; p.vy = 0; }
    }
    spinFx = decay(spinFx, SPIN_DECAY, SPIN_D); spinFy = decay(spinFy, SPIN_DECAY, SPIN_D);
    spinSx = decay(spinSx, SPIN_DECAY, SPIN_D); spinSy = decay(spinSy, SPIN_DECAY, SPIN_D);

    // pockets first — a ball over a pocket mouth is down, whatever it was about to hit
    for (let k = 0; k < nm; k++) {
      const i = mv[k], p = b[i];
      if (!p.on) continue;
      for (let q = 0; q < 6; q++) {
        if (pocketed(p, q)) {
          p.on = false; p.vx = 0; p.vy = 0;
          ev.pots.push({ ball: i, pocket: q });
          if (i === 0) ev.cueScratch = true;
          break;
        }
      }
    }
    // cushions
    for (let k = 0; k < nm; k++) {
      const i = mv[k], p = b[i];
      if (!p.on) continue;
      let hitX = false, hitY = false;
      if (p.x < R * FP && p.vx < 0) { p.x = 2 * R * FP - p.x; p.vx = -trunc((p.vx * CUSH) / FP); hitX = true; }
      else if (p.x > (W - R) * FP && p.vx > 0) { p.x = 2 * (W - R) * FP - p.x; p.vx = -trunc((p.vx * CUSH) / FP); hitX = true; }
      if (p.y < R * FP && p.vy < 0) { p.y = 2 * R * FP - p.y; p.vy = -trunc((p.vy * CUSH) / FP); hitY = true; }
      else if (p.y > (TH - R) * FP && p.vy > 0) { p.y = 2 * (TH - R) * FP - p.y; p.vy = -trunc((p.vy * CUSH) / FP); hitY = true; }
      if (hitX || hitY) {
        ev.rail = true;
        if (ev.first >= 0) ev.railAfterContact = true;
        if (i !== 0 && !(railed & (1 << i))) { railed |= 1 << i; ev.objectRails++; }
        if (i === 0) cueRails++; else if (i === ev.first) objRails++;
        if (i === 0) {
          // english bites on the cushion: the spin's TANGENTIAL half is handed to the ball, which is
          // what makes a running/check-side rebound leave at a different angle than a plain bounce.
          if (hitX) { p.vy += trunc((spinSy * 3) / 4); spinSy = trunc(spinSy / 2); }
          if (hitY) { p.vx += trunc((spinSx * 3) / 4); spinSx = trunc(spinSx / 2); }
        }
      }
    }
    // ball-to-ball: a resting ball can never initiate contact, so only the moving ones drive the scan
    // (and a moving/moving pair is visited once, by its lower index)
    for (let k = 0; k < nm; k++) {
      const i = mv[k];
      if (!b[i].on) continue;
      for (let j = 0; j < BALLS; j++) {
        if (j === i || !b[j].on) continue;
        if (isMoving[j] && j < i) continue;
        const A = b[i], B = b[j];
        const dx = B.x - A.x, dy = B.y - A.y;
        const d2 = dx * dx + dy * dy;
        if (d2 >= RR2) continue;
        const d = isqrt(d2) || 1;
        const nx = trunc((dx * FP) / d), ny = trunc((dy * FP) / d);
        const over = RR - d;
        if (over > 0) {                                  // separate, so the pair cannot stick together
          const sx = trunc((nx * over) / (2 * FP)), sy = trunc((ny * over) / (2 * FP));
          A.x -= sx; A.y -= sy; B.x += sx; B.y += sy;
        }
        const rvn = trunc(((B.vx - A.vx) * nx + (B.vy - A.vy) * ny) / FP);
        if (rvn >= 0) continue;                          // separating already
        if (ev.first < 0 && (i === 0 || j === 0)) {
          ev.first = i === 0 ? j : i;
          ev.firstAt = [trunc(b[0].x / FP), trunc(b[0].y / FP)];
        }
        const imp = trunc((rvn * REST) / (2 * FP));
        A.vx += trunc((nx * imp) / FP); A.vy += trunc((ny * imp) / FP);
        B.vx -= trunc((nx * imp) / FP); B.vy -= trunc((ny * imp) / FP);
        if (i === 0) { spinFx = trunc(spinFx / 2); spinFy = trunc(spinFy / 2); }  // contact eats half the follow
      }
    }
    if (frames && tick % FRAME_TICKS === 0) snap();
    // Preview polylines. Record freely and note WHERE the interesting events happened — trimming live
    // cannot work, because at cushion time you do not yet know a contact is still coming.
    if (ev.cuePath && tick % 8 === 0) {
      if (b[0].on && ev.cuePath.length < 600) {
        if (ev.first >= 0 && ev.firstSample == null) ev.firstSample = ev.cuePath.length / 2;
        if (cueRails > 0 && ev.railSample == null) ev.railSample = ev.cuePath.length / 2;
        ev.cuePath.push(trunc(b[0].x / FP), trunc(b[0].y / FP));
      }
      if (ev.first > 0 && b[ev.first].on && objRails === 0 && ev.objPath.length < 200) {
        ev.objPath.push(trunc(b[ev.first].x / FP), trunc(b[ev.first].y / FP));
      }
    }
  }
  // final sweep: a ball nudged by the last overlap separation can come to rest over a pocket mouth
  for (let i = 0; i < BALLS; i++) {
    b[i].vx = 0; b[i].vy = 0;
    if (!b[i].on) continue;
    for (let q = 0; q < 6; q++) {
      if (pocketed(b[i], q)) {
        b[i].on = false; ev.pots.push({ ball: i, pocket: q });
        if (i === 0) ev.cueScratch = true;
        break;
      }
    }
  }
  if (frames) snap();
  return { ev, frames };
}

// trimTo(path, maxLen): cut a flat [x,y,…] polyline once it has run `maxLen` table units.
function trimTo(path, maxLen) {
  if (!path) return path;
  let run = 0;
  for (let i = 2; i < path.length; i += 2) {
    const dx = path[i] - path[i - 2], dy = path[i + 1] - path[i - 1];
    run += isqrt(dx * dx + dy * dy);
    if (run > maxLen) return path.slice(0, i + 2);
  }
  return path;
}

// previewShot(st, shot): what this shot ACTUALLY does — run by the real simulation on a COPY of the
// table, so the aiming line cannot promise a contact the physics will not make. Drawing the preview as
// a straight ray of its own was wrong three ways at once: it ignored English (the cue ball curves), it
// ignored friction (a soft shot stops short of the ball it "hits"), and its floating-point geometry
// disagreed with the integer simulation on razor-thin cuts. Same code path, same answer, always.
export function previewShot(st, shot) {
  const c = { b: st.b.map((p) => ({ x: p.x, y: p.y, vx: 0, vy: 0, on: p.on })),
              inHand: st.inHand, breakShot: st.breakShot };
  if (st.inHand) { const [x, y] = placeToXY(shot.px, shot.py); placeCue(c, x, y, c.breakShot); }
  const from = [trunc(c.b[0].x / FP), trunc(c.b[0].y / FP)];
  const { ev } = simulate(c, shot, false, true);
  // cue line: to the contact, plus a few samples so the angle it comes off at is readable. With no
  // contact at all, stop at the first cushion — beyond that it is just noise on the cloth.
  const cut = ev.first >= 0 ? (ev.firstSample == null ? ev.cuePath.length : (ev.firstSample + 7) * 2)
            : (ev.railSample == null ? ev.cuePath.length : (ev.railSample + 1) * 2);
  const cuePath = ev.cuePath.slice(0, Math.max(4, Math.min(ev.cuePath.length, cut)));
  return { from, first: ev.first, firstAt: ev.firstAt, pots: ev.pots,
           cuePath, objPath: trimTo(ev.objPath, 620), rail: ev.rail,
           railAfterContact: ev.railAfterContact, scratch: ev.cueScratch, end: c.b };
}

// ---- 8-ball ruleset ---------------------------------------------------------------------------------
export const remaining = (st, group) => {
  let n = 0;
  for (let i = 0; i < BALLS; i++) if (st.b[i].on && groupOf(i) === group) n++;
  return n;
};
// targetGroup(st, side): which group `side` is on — -1 while the table is open, 2 once they are on the 8
export function targetGroup(st, side) {
  if (st.open) return -1;
  const g = st.grp[side];
  return remaining(st, g) === 0 ? 2 : g;
}
export function legalTargets(st, side) {
  const t = targetGroup(st, side);
  const out = [];
  for (let i = 1; i < BALLS; i++) {
    if (!st.b[i].on) continue;
    if (t === 2) { if (i === 8) out.push(i); }
    else if (t === -1) { if (i !== 8) out.push(i); }
    else if (groupOf(i) === t) out.push(i);
  }
  return out;
}

// applyShot(st, side, shot): the referee. Simulates, then judges — fouls, group assignment, whose shot
// is next, and the 8-ball ending. Returns the shot record (also pushed onto st.log).
export function applyShot(st, side, shot, wantFrames) {
  const wasOpen = st.open, myGroupBefore = st.grp[side];
  if (st.inHand) {
    const [x, y] = placeToXY(shot.px, shot.py);
    placeCue(st, x, y, st.breakShot);
  } else if (!st.b[0].on) {                        // defensive: a cue ball off the table always re-spots
    placeCue(st, trunc(HEAD_X / 2), FOOT_Y, true);
  }
  const target = targetGroup(st, side);
  const onEight = target === 2;
  const { ev, frames } = simulate(st, shot, wantFrames);

  // --- foul detection ---------------------------------------------------------------------------
  let foul = "", potMine = 0, potTheirs = 0, eightPot = null;
  for (const p of ev.pots) {
    if (p.ball === 8) eightPot = p;
    else if (p.ball !== 0) {
      const g = groupOf(p.ball);
      if (wasOpen) potMine++;                       // an open table credits whatever fell
      else if (g === myGroupBefore) potMine++;
      else potTheirs++;
    }
  }
  if (ev.cueScratch) foul = "scratch";
  else if (ev.first < 0) foul = "nohit";
  else if (st.breakShot) {
    // a legal break: something goes down, or at least four object balls reach a cushion
    if (ev.pots.length === 0 && ev.objectRails < 4) foul = "break";
  } else if (onEight) {
    if (ev.first !== 8) foul = "wrongball";
  } else if (target >= 0) {
    if (groupOf(ev.first) !== target) foul = "wrongball";
  } else if (ev.first === 8) foul = "wrongball";     // open table: the 8 is never a legal first contact
  if (!foul && !st.breakShot && ev.pots.length === 0 && !ev.railAfterContact) foul = "norail";

  // --- the 8-ball ending ------------------------------------------------------------------------
  let over = false, winner = 0;
  if (eightPot) {
    if (st.breakShot) respot(st, 8);                 // an 8 on the break is spotted, not a loss
    else if (onEight && !foul && shot.call === eightPot.pocket) { over = true; winner = side; }
    else { over = true; winner = 1 - side; }         // early, wrong pocket, or fouled on the 8 = loss
  }

  // --- group assignment -------------------------------------------------------------------------
  if (!over && wasOpen && !foul && !st.breakShot) {
    const first = ev.pots.find((p) => p.ball !== 0 && p.ball !== 8);
    if (first) {
      const g = groupOf(first.ball);
      st.grp[side] = g; st.grp[1 - side] = 1 - g; st.open = false;
    }
  }

  // --- turn ------------------------------------------------------------------------------------
  const keep = !foul && !over && potMine > 0;
  if (over) { st.over = true; st.result = winner + 1; }
  else {
    st.inHand = !!foul;
    st.turn = (!keep || foul) ? 1 - side : side;
  }
  st.breakShot = false;
  st.broke = true;
  void potTheirs;
  const rec = { side, shot, foul, pots: ev.pots.slice(), first: ev.first, keep, over,
                winner: over ? winner + 1 : 0 };
  st.log.push(rec);
  st.last = { rec, frames };
  return st.last;
}

// ---- move application + replay ----------------------------------------------------------------------
export function applyMove(st, sideNum, enc, wantFrames) {
  if (st.corrupt || st.over) return corrupt(st, "shot after the game ended");
  const side = sideNum - 1;                          // contract records 1/2; the engine indexes 0/1
  if (side !== 0 && side !== 1) return corrupt(st, "bad side");
  const shot = decShot(enc);
  if (shot.op !== 1) return corrupt(st, "unknown op " + shot.op);
  if (side !== st.turn) return corrupt(st, "shot out of turn");
  applyShot(st, side, shot, wantFrames);
  return st;
}

// replay(g, khQ, recs): rebuild the table from the on-chain log. khQ is the rack seed (null until the
// join block's hashes exist — the caller shows "racking…" until then).
export function replay(g, khQ, recs, wantFramesForLast) {
  if (khQ == null) return { blocked: true, blockedAt: -1, setup: true, mi: 0, b: [], log: [] };
  const st = init(g, khQ);
  for (let i = 0; i < recs.length; i++) {
    applyMove(st, recs[i].side, recs[i].enc, wantFramesForLast && i === recs.length - 1);
    st.mi = i + 1;
    if (st.corrupt) break;
  }
  return st;
}

// ---- aiming helpers (shared by the UI and the practice bot) -----------------------------------------
// ghostAim(st, ballId, pocketIdx): the angle that sends `ballId` at that pocket, plus the cut angle
// (0 = dead straight) — pure integer geometry over the same tables the simulation uses.
export function ghostAim(st, ballId, pocketIdx) {
  const b = st.b[ballId];
  if (!b || !b.on || !st.b[0].on) return null;
  const bx = trunc(b.x / FP), by = trunc(b.y / FP);
  const [px, py] = POCKETS[pocketIdx];
  const tx = px - bx, ty = py - by;
  const td = isqrt(tx * tx + ty * ty) || 1;
  const gx = bx - trunc((tx * 2 * R) / td), gy = by - trunc((ty * 2 * R) / td);   // ghost-ball centre
  const cx = trunc(st.b[0].x / FP), cy = trunc(st.b[0].y / FP);
  const ax = gx - cx, ay = gy - cy;
  const ad = isqrt(ax * ax + ay * ay);
  if (ad === 0) return null;
  const cut = trunc((ax * tx + ay * ty) * 65536 / (ad * td));   // Q16 cosine of the cut angle
  return { angle: angleOf(ax, ay), dist: ad, potDist: td, cut };
}
// pathClear(st, fx, fy, tx, ty, ignore): is the straight line free of other balls?
export function pathClear(st, fx, fy, tx, ty, ignore) {
  const dx = tx - fx, dy = ty - fy;
  const len = isqrt(dx * dx + dy * dy);
  if (len === 0) return true;
  for (let i = 0; i < BALLS; i++) {
    if (!st.b[i].on || (ignore && ignore.indexOf(i) >= 0)) continue;
    const bx = trunc(st.b[i].x / FP) - fx, by = trunc(st.b[i].y / FP) - fy;
    const t = trunc((bx * dx + by * dy) / len);
    if (t <= 0 || t >= len) continue;
    const px = trunc((dx * t) / len), py = trunc((dy * t) / len);
    const ox = bx - px, oy = by - py;
    if (ox * ox + oy * oy < (2 * R) * (2 * R)) return false;
  }
  return true;
}

// botShot(st, side, rnd): the practice opponent. Scores every (own ball, pocket) pair on cut angle,
// distance and a clear path, plays the best one with a little human error, and falls back to a safety
// nudge at the nearest legal ball when nothing is on.
export function botShot(st, side, rnd) {
  const targets = legalTargets(st, side);
  const cx = trunc(st.b[0].x / FP), cy = trunc(st.b[0].y / FP);
  const r0 = rnd || (() => 0.5);
  if (st.breakShot) {
    // the break is its own shot: full power straight into the apex. Scoring it like a pot attempt
    // picked a soft, angled tap that failed the four-balls-to-a-cushion rule and fouled the break.
    let apex = -1, ax = 0, ay = 0;
    for (let i = 1; i < BALLS; i++) {
      if (!st.b[i].on) continue;
      const bx = trunc(st.b[i].x / FP);
      if (apex < 0 || bx < ax) { apex = i; ax = bx; ay = trunc(st.b[i].y / FP); }
    }
    if (apex >= 0) {
      return { op: 1, angle: (angleOf(ax - cx, ay - cy) + Math.round((r0() - 0.5) * 8) + 4096) & 4095,
               power: 63, side: 0, fwd: 1, call: 7, px: 0, py: 0 };
    }
  }
  let best = null;
  for (const id of targets) {
    for (let k = 0; k < 6; k++) {
      const aim = ghostAim(st, id, k);
      if (!aim || aim.cut < 6000) continue;                       // beyond ~85° is not a shot
      const bx = trunc(st.b[id].x / FP), by = trunc(st.b[id].y / FP);
      if (!pathClear(st, cx, cy, bx, by, [0, id])) continue;
      if (!pathClear(st, bx, by, POCKETS[k][0], POCKETS[k][1], [id])) continue;
      const score = aim.cut - trunc((aim.dist + aim.potDist) * 8);
      if (!best || score > best.score) best = { score, angle: aim.angle, id, pocket: k, dist: aim.dist + aim.potDist };
    }
  }
  const r = r0;
  if (best) {
    const err = Math.round((r() - 0.5) * 14);                     // ±0.3° of aim wobble
    const power = Math.max(10, Math.min(52, 14 + trunc(best.dist / 90)));
    const call = targetGroup(st, side) === 2 ? best.pocket : 7;
    return { op: 1, angle: (best.angle + err + 4096) & 4095, power, side: 0, fwd: 0, call,
             px: 0, py: 0 };
  }
  // nothing on: roll gently at the nearest legal ball so the shot is at least not a foul
  let near = null;
  for (const id of targets) {
    const dx = trunc(st.b[id].x / FP) - cx, dy = trunc(st.b[id].y / FP) - cy;
    const d = dx * dx + dy * dy;
    if (!near || d < near.d) near = { d, id, angle: angleOf(dx, dy) };
  }
  if (!near) return { op: 1, angle: 0, power: 20, side: 0, fwd: 0, call: 7, px: 0, py: 0 };
  return { op: 1, angle: near.angle, power: Math.max(8, Math.min(40, 10 + trunc(isqrt(near.d) / 80))),
           side: 0, fwd: 0, call: 7, px: 0, py: 0 };
}

// botEnc(st, side, rnd): botShot() plus the ball-in-hand placement, encoded ready for the log.
export function botEnc(st, side, rnd) {
  const s = botShot(st, side, rnd);
  if (!st.inHand) return encShot(s);
  // With ball in hand the aim must be computed FROM the chosen spot, so place a scratch copy of the cue
  // ball there first, re-aim, then restore — applyShot() will redo the placement for real from the log.
  const [px, py] = xyToPlace(st.breakShot ? trunc(HEAD_X / 2) : trunc(W / 2), FOOT_Y);
  const saved = { x: st.b[0].x, y: st.b[0].y, on: st.b[0].on };
  const [x, y] = placeToXY(px, py);
  placeCue(st, x, y, st.breakShot);
  const re = botShot(st, side, rnd);
  st.b[0].x = saved.x; st.b[0].y = saved.y; st.b[0].on = saved.on;
  re.px = px; re.py = py;
  return encShot(re);
}
