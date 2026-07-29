/*
 * pool-engine.js referee test. The stake is DETERMINISM: two browsers replaying the same move log must
 * rack, break and pot identically, or the wager escrow is settling a game the players didn't both see.
 * Asserts: the trig table and isqrt are exact integer maths (no Math.sin/Math.sqrt rounding leaks in);
 * the encoding round-trips every field at full width; the rack is seed-determined and legal; a shot is a
 * pure function of (state, shot) — byte-identical over repeated runs and over a full replay; balls never
 * escape the table or overlap at rest; pockets accept by DIRECTION rather than mere proximity; the aim
 * preview is the shot that will actually be taken; and the 8-ball rules (break legality, group
 * assignment, first-contact / no-rail / scratch fouls, ball in hand, the called-pocket ending) fire.
 * Run from the repo root:  node tests/pool_js_test.mjs
 */
import { loadCrypto } from "../static/nadotx.js";
await loadCrypto(".");
const E = await import("../static/pool-engine.js");
const { W, TH, R, FP, BALLS, POCKETS, HEAD_X, FOOT_Y, isqrt, SIN, COS, angleOf,
        encShot, decShot, init, applyMove, applyShot, replay, simulate, placeCue, botEnc,
        targetGroup, groupOf, placeToXY, xyToPlace } = E;

let fails = 0;
const check = (name, fn) => { try { fn(); console.log("PASS  " + name); } catch (e) { fails++; console.log("FAIL  " + name + ": " + (e && e.stack || e)); } };
const prng = (seed) => { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32); };
const qOf = (i) => BigInt(i) * 1000003n + 987654321987654321n;
const fingerprint = (st) => st.b.map((p) => (p.on ? p.x + "," + p.y : "-")).join("|")
  + "#" + st.turn + st.open + st.grp.join(",") + (st.inHand ? "H" : "-") + st.over + st.result;

// a bare table we can pose exactly, so every rule is tested against a hand-built position
function posed(balls, patch) {
  const st = init(1, qOf(0));
  for (let i = 0; i < BALLS; i++) { st.b[i].on = false; st.b[i].vx = 0; st.b[i].vy = 0; }
  for (const [id, x, y] of balls) { st.b[id].on = true; st.b[id].x = x * FP; st.b[id].y = y * FP; }
  st.breakShot = false; st.inHand = false; st.broke = true; st.open = false; st.grp = [0, 1];
  return Object.assign(st, patch || {});
}

// ---- 1. integer maths --------------------------------------------------------------------------------
check("isqrt is exact for the whole range the simulation reaches", () => {
  for (const n of [0, 1, 2, 3, 4, 8, 9, 10, 65535, 65536, 1e6, 3.2e9, 6.8e12, 6.8e12 - 1]) {
    const r = isqrt(n);
    if (!(r * r <= n && (r + 1) * (r + 1) > n)) throw new Error(`isqrt(${n}) = ${r}`);
  }
  const rnd = prng(7);
  for (let i = 0; i < 20000; i++) {
    const n = Math.floor(rnd() * 6.8e12);
    const r = isqrt(n);
    if (!(r * r <= n && (r + 1) * (r + 1) > n)) throw new Error(`isqrt(${n}) = ${r}`);
  }
});

check("the trig table is a unit circle to Q16 and matches Math.sin closely enough to be right", () => {
  for (let a = 0; a < 4096; a++) {
    const m = SIN[a] * SIN[a] + COS[a] * COS[a];
    if (Math.abs(m - 65536 * 65536) > 4 * 65536) throw new Error(`a=${a} magnitude off`);
    if (Math.abs(SIN[a] - Math.sin((a * 2 * Math.PI) / 4096) * 65536) > 2) throw new Error(`SIN[${a}] off`);
    if (Math.abs(COS[a] - Math.cos((a * 2 * Math.PI) / 4096) * 65536) > 2) throw new Error(`COS[${a}] off`);
  }
  if (SIN[0] !== 0 || COS[0] !== 65536) throw new Error("angle 0 must be (1,0)");
  if (SIN[1024] !== 65536 || Math.abs(COS[1024]) > 1) throw new Error("quarter turn must be (0,1)");
});

check("angleOf inverts the table", () => {
  for (let a = 0; a < 4096; a += 7) {
    const got = angleOf(Math.round(COS[a] / 8), Math.round(SIN[a] / 8));
    const diff = Math.min((got - a + 4096) % 4096, (a - got + 4096) % 4096);
    if (diff > 1) throw new Error(`angleOf round-trip a=${a} -> ${got}`);
  }
});

// ---- 2. encoding -------------------------------------------------------------------------------------
check("shot encoding round-trips every field at full width", () => {
  const rnd = prng(11);
  for (let i = 0; i < 3000; i++) {
    const s = { angle: Math.floor(rnd() * 4096), power: Math.floor(rnd() * 64),
                side: Math.floor(rnd() * 7) - 3, fwd: Math.floor(rnd() * 7) - 3,
                call: Math.floor(rnd() * 8), px: Math.floor(rnd() * 2048), py: Math.floor(rnd() * 1024) };
    const enc = encShot(s), d = decShot(enc);
    if (enc <= 0) throw new Error("enc must be > 0 (0 is the contract's empty sentinel)");
    if (!Number.isSafeInteger(enc)) throw new Error("enc " + enc + " is not a safe integer");
    for (const k of Object.keys(s)) if (d[k] !== s[k]) throw new Error(`${k}: ${s[k]} -> ${d[k]}`);
  }
  const maxEnc = encShot({ angle: 4095, power: 63, side: 3, fwd: 3, call: 7, px: 2047, py: 1023 });
  if (!Number.isSafeInteger(maxEnc) || maxEnc >= 2 ** 53) throw new Error("max enc overflows");
});

check("placement grid maps into the legal cue-ball rectangle and back", () => {
  for (let px = 0; px < 2048; px += 37) for (let py = 0; py < 1024; py += 29) {
    const [x, y] = placeToXY(px, py);
    if (x < R || x > W - R || y < R || y > TH - R) throw new Error(`placeToXY(${px},${py}) off table`);
    const [bx, by] = xyToPlace(x, y);
    if (Math.abs(bx - px) > 1 || Math.abs(by - py) > 1) throw new Error("placement round-trip drifted");
  }
});

// ---- 3. the rack -------------------------------------------------------------------------------------
check("the rack is seed-determined, complete and legal", () => {
  for (let s = 0; s < 40; s++) {
    const st = init(1, qOf(s));
    const seen = new Set();
    for (let i = 0; i < BALLS; i++) {
      if (!st.b[i].on) throw new Error("every ball starts on the table");
      const key = st.b[i].x + ":" + st.b[i].y;
      if (seen.has(key)) throw new Error("two balls racked on the same point");
      seen.add(key);
      const x = st.b[i].x / FP, y = st.b[i].y / FP;
      if (x < R || x > W - R || y < R || y > TH - R) throw new Error(`ball ${i} racked off the table`);
    }
    for (let i = 0; i < BALLS; i++) for (let j = i + 1; j < BALLS; j++) {
      const dx = (st.b[i].x - st.b[j].x) / FP, dy = (st.b[i].y - st.b[j].y) / FP;
      if (dx * dx + dy * dy < (2 * R) * (2 * R)) throw new Error(`racked balls ${i},${j} overlap`);
    }
    if (st.b[0].x / FP > HEAD_X) throw new Error("the cue ball must rack behind the head string");
    if (fingerprint(init(1, qOf(s))) !== fingerprint(st)) throw new Error("same seed, different rack");
  }
  const racks = new Set();
  for (let s = 0; s < 40; s++) racks.add(fingerprint(init(1, qOf(s))));
  if (racks.size < 20) throw new Error("the rack shuffle barely moves: " + racks.size + " distinct in 40");
});

check("the 8 sits in the centre of the third row and the back corners are one of each", () => {
  for (let s = 0; s < 60; s++) {
    const st = init(1, qOf(s));
    const at = (row, k) => {
      const x = (1905 + row * 50) * FP, y = (635 + (2 * k - row) * 29) * FP;
      for (let i = 1; i < BALLS; i++) if (st.b[i].x === x && st.b[i].y === y) return i;
      throw new Error("no ball at row " + row + " k " + k);
    };
    if (at(2, 1) !== 8) throw new Error("the 8 must rack at the centre of the third row");
    if (groupOf(at(4, 0)) === groupOf(at(4, 4))) throw new Error("back corners must be one solid, one stripe");
  }
});

// ---- 4. physics determinism + invariants -------------------------------------------------------------
check("a shot is a pure function of (state, shot) — identical twice, identical on replay", () => {
  const rnd = prng(3);
  for (let t = 0; t < 12; t++) {
    const shot = { op: 1, angle: Math.floor(rnd() * 4096), power: Math.floor(rnd() * 64),
                   side: Math.floor(rnd() * 7) - 3, fwd: Math.floor(rnd() * 7) - 3, call: 7, px: 900, py: 500 };
    const a = init(5, qOf(t)), b = init(5, qOf(t));
    applyShot(a, 0, shot, false);
    applyShot(b, 0, shot, true);                      // asking for animation frames must not change state
    if (fingerprint(a) !== fingerprint(b)) throw new Error("frames changed the outcome at t=" + t);
    const c = replay(5, qOf(t), [{ enc: encShot(shot), side: 1 }]);
    if (fingerprint(c) !== fingerprint(a)) throw new Error("replay diverged at t=" + t);
  }
});

check("balls stay on the table, never overlap at rest, and always come to a stop", () => {
  const rnd = prng(21);
  for (let t = 0; t < 30; t++) {
    const st = init(6, qOf(t));
    for (let s = 0; s < 8 && !st.over; s++) {
      applyShot(st, st.turn, { op: 1, angle: Math.floor(rnd() * 4096), power: Math.floor(rnd() * 64),
                               side: Math.floor(rnd() * 7) - 3, fwd: Math.floor(rnd() * 7) - 3, call: 7,
                               px: Math.floor(rnd() * 2048), py: Math.floor(rnd() * 1024) }, false);
      for (let i = 0; i < BALLS; i++) {
        const p = st.b[i];
        if (p.vx !== 0 || p.vy !== 0) throw new Error("ball " + i + " still moving after the shot resolved");
        if (!p.on) continue;
        const x = p.x / FP, y = p.y / FP;
        if (x < R - 1 || x > W - R + 1 || y < R - 1 || y > TH - R + 1) throw new Error(`ball ${i} left the table`);
      }
      for (let i = 0; i < BALLS; i++) for (let j = i + 1; j < BALLS; j++) {
        if (!st.b[i].on || !st.b[j].on) continue;
        const dx = (st.b[i].x - st.b[j].x) / FP, dy = (st.b[i].y - st.b[j].y) / FP;
        if (dx * dx + dy * dy < (2 * R - 2) * (2 * R - 2)) throw new Error(`balls ${i},${j} overlap at rest`);
      }
    }
  }
});

check("a hard break scatters the rack and drives at least four balls to a cushion", () => {
  let scattered = 0, legal = 0;
  for (let s = 0; s < 20; s++) {
    const st = init(7, qOf(s));
    const before = st.b.map((p) => p.x + ":" + p.y);
    const [px, py] = xyToPlace(Math.round(HEAD_X / 2), FOOT_Y);
    applyShot(st, 0, { op: 1, angle: 0, power: 63, side: 0, fwd: 0, call: 7, px, py }, false);
    let moved = 0;
    for (let i = 1; i < BALLS; i++) if (!st.b[i].on || before[i] !== st.b[i].x + ":" + st.b[i].y) moved++;
    if (moved >= 12) scattered++;
    if (!st.log[0].foul) legal++;
  }
  if (scattered < 20) throw new Error("a max-power break must move nearly the whole rack (" + scattered + "/20)");
  if (legal < 20) throw new Error("a max-power break must be legal (" + legal + "/20)");
});

check("shot power maps to a sane roll distance", () => {
  const roll = (power) => {
    const st = init(8, qOf(1));
    for (let i = 1; i < BALLS; i++) st.b[i].on = false;
    st.b[0].x = 200 * FP; st.b[0].y = FOOT_Y * FP;
    simulate(st, { angle: 0, power, side: 0, fwd: 0 }, false);
    return st.b[0].on ? st.b[0].x / FP - 200 : 9999;             // 9999 = it found a pocket
  };
  const soft = roll(0), hard = roll(63);
  if (!(soft > 150 && soft < 500)) throw new Error("a soft tap should roll 150-500 units, got " + soft);
  if (hard !== 9999 && hard < 1500) throw new Error("a full-power shot should cross the table, got " + hard);
});

check("draw and follow move the cue ball in opposite directions off a straight pot", () => {
  const cueAfter = (fwd) => {
    const st = init(9, qOf(2));
    for (let i = 1; i < BALLS; i++) st.b[i].on = false;
    st.b[0].x = 400 * FP; st.b[0].y = FOOT_Y * FP;
    st.b[1].on = true; st.b[1].x = 1200 * FP; st.b[1].y = FOOT_Y * FP;
    simulate(st, { angle: 0, power: 22, side: 0, fwd }, false);
    return st.b[0].on ? st.b[0].x / FP : null;
  };
  const draw = cueAfter(-3), stun = cueAfter(0), follow = cueAfter(3);
  if (draw == null || stun == null || follow == null) throw new Error("the cue ball should not pot itself here");
  if (!(draw < stun)) throw new Error(`backspin must pull the cue ball back: ${draw} vs ${stun}`);
  if (!(follow > stun)) throw new Error(`topspin must push it forward: ${follow} vs ${stun}`);
});

check("side spin bends the cue ball's path", () => {
  const endY = (side) => {
    const st = init(10, qOf(3));
    for (let i = 1; i < BALLS; i++) st.b[i].on = false;
    st.b[0].x = 200 * FP; st.b[0].y = FOOT_Y * FP;
    simulate(st, { angle: 0, power: 10, side, fwd: 0 }, false);   // gentle: stops short of the far rail
    return st.b[0].on && st.b[0].x / FP < W - R - 1 ? st.b[0].y / FP : null;
  };
  const l = endY(-3), c = endY(0), r = endY(3);
  if (l == null || c == null || r == null) throw new Error("the cue ball potted itself unexpectedly");
  if (!(l < c && c < r)) throw new Error(`english must curve the path: ${l} / ${c} / ${r}`);
});

// ---- 5. pockets --------------------------------------------------------------------------------------
check("a pocket accepts by DIRECTION, not mere proximity", () => {
  const runner = posed([[0, 300, R + 1], [1, 2400, 1100]]);
  const ran = simulate(runner, { angle: 0, power: 45, side: 0, fwd: 0 }, false);
  if (ran.ev.pots.some((p) => p.ball === 0 && p.pocket === 1))
    throw new Error("a ball running the cushion was swallowed by the side pocket it passed");
  const into = posed([[0, W / 2, 600], [1, 2400, 1100]]);
  const hit = simulate(into, { angle: angleOf(0, -1), power: 30, side: 0, fwd: 0 }, false);
  if (!hit.ev.pots.some((p) => p.ball === 0 && p.pocket === 1))
    throw new Error("a ball played straight into the side pocket did not drop");
  const corner = posed([[0, 600, R + 1], [1, 2400, 1100]]);
  const cp = simulate(corner, { angle: angleOf(-1, 0), power: 30, side: 0, fwd: 0 }, false);
  if (!cp.ev.pots.some((p) => p.ball === 0 && p.pocket === 0))
    throw new Error("a ball running the rail into the corner should drop");
});

check("balls come to rest ON the cloth, never floating inside a pocket mouth", () => {
  const rnd = prng(555);
  for (let t = 0; t < 25; t++) {
    const st = init(12, qOf(t));
    for (let k = 0; k < 6 && !st.over; k++) {
      applyShot(st, st.turn, { op: 1, angle: Math.floor(rnd() * 4096), power: Math.floor(rnd() * 64),
                               side: Math.floor(rnd() * 7) - 3, fwd: Math.floor(rnd() * 7) - 3, call: 7,
                               px: Math.floor(rnd() * 2048), py: Math.floor(rnd() * 1024) }, false);
      for (let i = 0; i < BALLS; i++) {
        if (!st.b[i].on) continue;
        const x = Math.trunc(st.b[i].x / FP), y = Math.trunc(st.b[i].y / FP);
        for (let q = 0; q < 6; q++) {
          const dx = x - POCKETS[q][0], dy = y - POCKETS[q][1], jaw = E.POCKET_RS[q] / 2;
          if (dx * dx + dy * dy < jaw * jaw) throw new Error(`ball ${i} came to rest inside pocket ${q}`);
        }
      }
    }
  }
});

// ---- 6. the aim preview ------------------------------------------------------------------------------
check("the aim preview is the shot: it never promises a contact the physics does not make", () => {
  const rnd = prng(4242);
  let contacts = 0, misses = 0;
  for (let t = 0; t < 120; t++) {
    const st = init(11, qOf(t));
    const [bx, by] = xyToPlace(Math.round(HEAD_X / 2), FOOT_Y);
    applyShot(st, 0, { op: 1, angle: 0, power: 40 + (t % 20), side: 0, fwd: 0, call: 7, px: bx, py: by }, false);
    for (let k = 0; k < 4 && !st.over; k++) {
      const shot = { op: 1, angle: Math.floor(rnd() * 4096), power: Math.floor(rnd() * 64),
                     side: Math.floor(rnd() * 7) - 3, fwd: Math.floor(rnd() * 7) - 3, call: 7,
                     px: Math.floor(rnd() * 2048), py: Math.floor(rnd() * 1024) };
      const pre = E.previewShot(st, shot);
      const rec = applyShot(st, st.turn, shot, false).rec;
      if (pre.first !== rec.first) throw new Error(`preview said contact ${pre.first}, the shot made ${rec.first}`);
      const pk = (p) => p.map((x) => x.ball + "@" + x.pocket).sort().join(",");
      if (pk(pre.pots) !== pk(rec.pots)) throw new Error(`preview potted ${pk(pre.pots)}, the shot potted ${pk(rec.pots)}`);
      if (pre.first >= 0) { contacts++; if (!pre.firstAt) throw new Error("a contact with no contact point"); }
      else misses++;
      if (pre.first >= 0 && (!pre.cuePath || pre.cuePath.length < 4)) throw new Error("a contact with no cue path");
    }
  }
  if (contacts < 20 || misses < 5) throw new Error(`unbalanced sample: ${contacts} contacts, ${misses} misses`);
});

check("the preview line stops where it stops being useful", () => {
  const st = posed([[0, 400, 635], [1, 1600, 635], [9, 2400, 200]]);
  const pv = E.previewShot(st, { angle: 0, power: 63, side: 0, fwd: 0, call: 7, px: 0, py: 0 });
  if (pv.first !== 1) throw new Error("expected to strike the 1");
  const lx = pv.cuePath[pv.cuePath.length - 2], ly = pv.cuePath[pv.cuePath.length - 1];
  const dx = lx - pv.firstAt[0], dy = ly - pv.firstAt[1];
  if (isqrt(dx * dx + dy * dy) > 420) throw new Error("the cue line runs far past the contact point");
  let run = 0;
  for (let i = 2; i < pv.objPath.length; i += 2) {
    const ax = pv.objPath[i] - pv.objPath[i - 2], ay = pv.objPath[i + 1] - pv.objPath[i - 1];
    run += isqrt(ax * ax + ay * ay);
  }
  if (run > 900) throw new Error("the object line is " + run + " units long — too much clutter");
});

check("English curves the cue ball away from the straight line a ray-cast would draw", () => {
  const mk = () => posed([[0, 300, 635], [1, 1600, 635], [9, 2400, 200]]);
  const straight = E.previewShot(mk(), { angle: 0, power: 30, side: 0, fwd: 0, call: 7, px: 0, py: 0 });
  if (straight.first !== 1) throw new Error("the control shot should strike the 1, got " + straight.first);
  let curved = null;
  for (const side of [3, -3]) {
    const p = E.previewShot(mk(), { angle: 0, power: 30, side, fwd: 0, call: 7, px: 0, py: 0 });
    if (p.first !== 1 || Math.abs(p.firstAt[1] - straight.firstAt[1]) > 2) curved = p;
  }
  if (!curved) throw new Error("side spin changed neither the contact nor where it happened");
});

check("a shot too soft to reach is previewed as a miss, not a hit", () => {
  const st = posed([[0, 200, 635], [1, 2200, 635], [9, 2400, 200]]);
  const soft = E.previewShot(st, { angle: 0, power: 0, side: 0, fwd: 0, call: 7, px: 0, py: 0 });
  if (soft.first !== -1) throw new Error("a minimum-power shot across the whole table should not reach");
  const hard = E.previewShot(st, { angle: 0, power: 63, side: 0, fwd: 0, call: 7, px: 0, py: 0 });
  if (hard.first !== 1) throw new Error("a full-power shot down the same line must strike the 1");
});

// ---- 7. the 8-ball ruleset ---------------------------------------------------------------------------
const shootAt = (st, side, tx, ty, power, call, fwd) => {
  const cx = st.b[0].x / FP, cy = st.b[0].y / FP;
  return applyShot(st, side, { op: 1, angle: angleOf(Math.round(tx - cx), Math.round(ty - cy)),
                               power: power == null ? 30 : power, side: 0, fwd: fwd || 0,
                               call: call == null ? 7 : call, px: 0, py: 0 }, false);
};
// pot `ball` into `pocket` through the real ghost-ball geometry (the same helper the UI aims with)
const potShot = (st, side, ball, pocket, power, call) => {
  const aim = E.ghostAim(st, ball, pocket);
  if (!aim) throw new Error("no aim line to ball " + ball + " pocket " + pocket);
  return applyShot(st, side, { op: 1, angle: aim.angle, power: power == null ? 30 : power,
                               side: 0, fwd: 0, call: call == null ? 7 : call, px: 0, py: 0 }, false);
};

check("hitting the opponent's group first is a foul and hands over ball in hand", () => {
  const st = posed([[0, 400, 635], [1, 2000, 300], [9, 900, 635]]);
  const { rec } = shootAt(st, 0, 900, 635);
  if (rec.first !== 9) throw new Error("first contact should be the 9 (a stripe), got " + rec.first);
  if (rec.foul !== "wrongball") throw new Error("expected a wrong-ball foul, got " + (rec.foul || "none"));
  if (st.turn !== 1 || !st.inHand) throw new Error("a foul must pass the turn WITH ball in hand");
});

check("hitting nothing is a foul", () => {
  const st = posed([[0, 400, 200], [1, 400, 1100]]);
  const { rec } = shootAt(st, 0, 2400, 200, 8);
  if (rec.foul !== "nohit" && rec.foul !== "norail") throw new Error("expected a foul, got " + (rec.foul || "none"));
  if (st.turn !== 1 || !st.inHand) throw new Error("a foul must pass the turn with ball in hand");
});

check("no cushion and no pot after contact is a foul", () => {
  const st = posed([[0, 1000, 635], [1, 1100, 635]]);
  const { rec } = shootAt(st, 0, 1100, 635, 0);
  if (rec.pots.length) throw new Error("this soft nudge should not pot anything");
  if (rec.foul !== "norail") throw new Error("expected a no-rail foul, got " + (rec.foul || "none"));
});

check("scratching is a foul even on an otherwise good pot", () => {
  const st = posed([[0, 300, 300], [1, 2400, 1100]]);
  const { rec } = shootAt(st, 0, POCKETS[0][0], POCKETS[0][1], 40);
  if (!rec.pots.some((p) => p.ball === 0)) throw new Error("the cue ball should have gone down");
  if (rec.foul !== "scratch") throw new Error("expected a scratch, got " + (rec.foul || "none"));
  if (!st.inHand || st.turn !== 1) throw new Error("a scratch gives the opponent ball in hand");
});

check("potting your own ball keeps you at the table", () => {
  const st = posed([[0, 700, 400], [1, 300, 220], [9, 2400, 1100]]);
  const { rec } = potShot(st, 0, 1, 0, 26);
  if (!rec.pots.some((p) => p.ball === 1)) throw new Error("the 1 should have dropped into the top-left");
  if (rec.foul) throw new Error("clean pot flagged a foul: " + rec.foul);
  if (st.turn !== 0) throw new Error("a legal pot keeps the shooter at the table");
  if (st.inHand) throw new Error("a legal pot does not hand over ball in hand");
});

check("an open table is claimed by the group of the first ball legally potted", () => {
  const st = posed([[0, 700, 400], [9, 300, 220], [1, 2400, 1100]], { open: true, grp: [-1, -1] });
  potShot(st, 0, 9, 0, 26);
  if (st.open) throw new Error("the table should have closed");
  if (st.grp[0] !== 1 || st.grp[1] !== 0) throw new Error("potting a stripe must claim stripes: " + st.grp);
});

check("the 8 is never a legal first contact while the table is open", () => {
  const st = posed([[0, 500, 635], [8, 1200, 635], [1, 2400, 200], [9, 2400, 1100]], { open: true, grp: [-1, -1] });
  const { rec } = shootAt(st, 0, 1200, 635, 20);
  if (rec.foul !== "wrongball") throw new Error("expected a wrong-ball foul on the 8, got " + (rec.foul || "none"));
});

check("potting the 8 early loses the game", () => {
  const st = posed([[0, 700, 400], [8, 300, 220], [1, 1500, 635]]);
  const { rec } = potShot(st, 0, 8, 0, 26);
  if (!rec.pots.some((p) => p.ball === 8)) throw new Error("the 8 should have dropped");
  if (!st.over || st.result !== 2) throw new Error(`potting the 8 with balls left must lose: ${st.over} ${st.result}`);
});

check("the 8 in the called pocket wins; the wrong pocket loses", () => {
  const mk = () => posed([[0, 700, 400], [8, 300, 220], [9, 1500, 635]]);   // p1 has cleared solids
  const win = mk();
  if (targetGroup(win, 0) !== 2) throw new Error("with solids cleared the target must be the 8");
  potShot(win, 0, 8, 0, 26, 0);                            // pocket 0 = top left — called correctly
  if (!win.over || win.result !== 1) throw new Error("called-pocket 8 must win");
  const lose = mk();
  potShot(lose, 0, 8, 0, 26, 5);                           // same pot, wrong call
  if (!lose.over || lose.result !== 2) throw new Error("an uncalled 8 must lose");
});

check("scratching while potting the 8 loses", () => {
  const st = posed([[0, 400, 400], [8, 300, 300], [9, 1500, 635]]);
  const { rec } = shootAt(st, 0, POCKETS[0][0], POCKETS[0][1], 63, 0, 3);
  if (!rec.pots.some((p) => p.ball === 8) || !rec.pots.some((p) => p.ball === 0))
    throw new Error("expected both the 8 and the cue ball down, got " + JSON.stringify(rec.pots));
  if (!st.over || st.result !== 2) throw new Error("scratching on the 8 must lose");
});

check("a shot out of turn corrupts the game instead of silently applying", () => {
  const st = posed([[0, 500, 635], [1, 1200, 635], [9, 1800, 400]]);
  applyMove(st, 2, encShot({ angle: 0, power: 20, side: 0, fwd: 0, call: 7, px: 0, py: 0 }));
  if (!st.corrupt) throw new Error("p2 shooting on p1's turn must corrupt the replay");
});

check("a missing rack seed blocks the replay rather than corrupting it", () => {
  const st = replay(1, null, []);
  if (!st.blocked || !st.setup) throw new Error("a null seed must report blocked/setup");
  if (st.corrupt) throw new Error("a missing seed is not a corruption");
});

check("ball in hand always lands somewhere legal, never inside a ball or a pocket", () => {
  const rnd = prng(99);
  for (let t = 0; t < 200; t++) {
    const st = init(3, qOf(t));
    placeCue(st, Math.floor(rnd() * W), Math.floor(rnd() * TH), t % 3 === 0);
    const x = st.b[0].x / FP, y = st.b[0].y / FP;
    if (x < R || x > W - R || y < R || y > TH - R) throw new Error(`placed off table at ${x},${y}`);
    for (let i = 1; i < BALLS; i++) {
      if (!st.b[i].on) continue;
      const dx = x - st.b[i].x / FP, dy = y - st.b[i].y / FP;
      if (dx * dx + dy * dy < (2 * R) * (2 * R)) throw new Error(`placed overlapping ball ${i}`);
    }
    for (let q = 0; q < POCKETS.length; q++) {
      const dx = x - POCKETS[q][0], dy = y - POCKETS[q][1];
      if (dx * dx + dy * dy < E.POCKET_RS[q] * E.POCKET_RS[q]) throw new Error("placed inside a pocket");
    }
    if (t % 3 === 0 && x > HEAD_X - R) throw new Error("a break placement must stay behind the head string");
  }
});

// ---- 8. whole games, played by the practice bot -------------------------------------------------------
check("the bot plays full games that terminate, and every game replays identically", () => {
  let decisive = 0, corrupted = 0, breakFouls = 0;
  for (let g = 0; g < 12; g++) {
    const rnd = prng(1000 + g);
    const st = init(100 + g, qOf(g));
    const recs = [];
    for (let s = 0; s < 240 && !st.over && !st.corrupt; s++) {
      const side = st.turn;
      const enc = botEnc(st, side, rnd);
      recs.push({ enc, side: side + 1 });
      applyMove(st, side + 1, enc);
    }
    if (st.corrupt) { corrupted++; continue; }
    if (st.log[0] && st.log[0].foul) breakFouls++;
    if (st.over) decisive++;
    const again = replay(100 + g, qOf(g), recs);
    if (fingerprint(again) !== fingerprint(st)) throw new Error("replay of game " + g + " diverged");
  }
  if (corrupted) throw new Error(corrupted + " bot games corrupted themselves");
  if (decisive < 8) throw new Error("only " + decisive + "/12 bot games reached a result — the bot stalls");
  if (breakFouls > 2) throw new Error(breakFouls + "/12 bot breaks fouled — the break shot is not being played");
});

console.log(fails ? "\n" + fails + " FAILED" : "\nALL PASS");
process.exit(fails ? 1 : 0);
