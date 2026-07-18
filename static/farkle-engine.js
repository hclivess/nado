// farkle-engine.js — reference Farkle ("Ten Thousand") engine.
// Dependency-free ES module, runs in the browser and in Node.
// Kept in lockstep with /root/nado/tests/farkle_ref.py (identical rules/results).
//
// SCORING RULES:
//   single 1 = 100; single 5 = 50.
//   three of a kind: three 1s = 1000; three of face F (2..6) = F*100.
//   four of a kind  = 2x the three-of-a-kind value.
//   five of a kind  = 4x the three-of-a-kind value.
//   six of a kind   = 8x the three-of-a-kind value.
//   straight 1-2-3-4-5-6 (all six dice) = 1500.
//   2,3,4,6 alone score nothing.

// ---------------------------------------------------------------------------
// Minimal synchronous SHA-256 (so dieFromHash is sync + identical in browser).
// Operates on a Uint8Array, returns a Uint8Array(32).
// ---------------------------------------------------------------------------
const _K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
  0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
  0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
  0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
  0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
  0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

function sha256(bytes) {
  const h = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]);
  const ml = bytes.length;
  const withOne = ml + 1;
  const k = (56 - (withOne % 64) + 64) % 64;
  const total = withOne + k + 8;
  const msg = new Uint8Array(total);
  msg.set(bytes, 0);
  msg[ml] = 0x80;
  const bitLen = ml * 8;
  // 64-bit big-endian length (high 32 bits are 0 for our small inputs).
  msg[total - 4] = (bitLen >>> 24) & 0xff;
  msg[total - 3] = (bitLen >>> 16) & 0xff;
  msg[total - 2] = (bitLen >>> 8) & 0xff;
  msg[total - 1] = bitLen & 0xff;

  const w = new Uint32Array(64);
  const rotr = (x, n) => (x >>> n) | (x << (32 - n));
  for (let off = 0; off < total; off += 64) {
    for (let i = 0; i < 16; i++) {
      const j = off + i * 4;
      w[i] = (msg[j] << 24) | (msg[j + 1] << 16) | (msg[j + 2] << 8) | msg[j + 3];
    }
    for (let i = 16; i < 64; i++) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
    }
    let a = h[0], b = h[1], c = h[2], d = h[3];
    let e = h[4], f = h[5], g = h[6], hh = h[7];
    for (let i = 0; i < 64; i++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const t1 = (hh + S1 + ch + _K[i] + w[i]) | 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) | 0;
      hh = g; g = f; f = e; e = (d + t1) | 0;
      d = c; c = b; b = a; a = (t1 + t2) | 0;
    }
    h[0] = (h[0] + a) | 0; h[1] = (h[1] + b) | 0;
    h[2] = (h[2] + c) | 0; h[3] = (h[3] + d) | 0;
    h[4] = (h[4] + e) | 0; h[5] = (h[5] + f) | 0;
    h[6] = (h[6] + g) | 0; h[7] = (h[7] + hh) | 0;
  }
  const out = new Uint8Array(32);
  for (let i = 0; i < 8; i++) {
    out[i * 4] = (h[i] >>> 24) & 0xff;
    out[i * 4 + 1] = (h[i] >>> 16) & 0xff;
    out[i * 4 + 2] = (h[i] >>> 8) & 0xff;
    out[i * 4 + 3] = h[i] & 0xff;
  }
  return out;
}

function utf8Bytes(str) {
  // ASCII-safe inputs (hex + ':' + digits); encode directly.
  const out = new Uint8Array(str.length);
  for (let i = 0; i < str.length; i++) out[i] = str.charCodeAt(i) & 0xff;
  return out;
}

// ---------------------------------------------------------------------------
// dieFromHash(seedHex, index) -> die in 1..6, deterministic & portable.
//
// SCHEME (replicate exactly):
//   msg  = utf8( seedHex + ":" + decimal(index) )      // ASCII bytes
//   dig  = SHA-256(msg)                                 // 32 bytes
//   u32  = big-endian uint32 of dig[0..4)               // dig[0]<<24|...|dig[3]
//   die  = (u32 mod 6) + 1
// ---------------------------------------------------------------------------
export function dieFromHash(seedHex, index) {
  const dig = sha256(utf8Bytes(seedHex + ":" + index));
  const u32 = ((dig[0] << 24) | (dig[1] << 16) | (dig[2] << 8) | dig[3]) >>> 0;
  return (u32 % 6) + 1;
}

// ---------------------------------------------------------------------------
// scoreRoll(dice) -> { score, scoringDice, allScore }
// Maximum score from setting aside ALL scoring dice in the roll.
// ---------------------------------------------------------------------------
function threeValue(face) {
  return face === 1 ? 1000 : face * 100;
}

export function scoreRoll(dice) {
  const counts = [0, 0, 0, 0, 0, 0, 0]; // index 1..6
  for (const d of dice) counts[d]++;

  // Straight 1-2-3-4-5-6 (needs all six).
  if (dice.length === 6) {
    let straight = true;
    for (let f = 1; f <= 6; f++) if (counts[f] !== 1) { straight = false; break; }
    if (straight) {
      return { score: 1500, scoringDice: [1, 2, 3, 4, 5, 6], allScore: true };
    }
  }

  let score = 0;
  const scoringDice = [];
  for (let f = 1; f <= 6; f++) {
    const c = counts[f];
    if (c === 0) continue;
    if (c >= 3) {
      const base = threeValue(f);
      const mult = c === 3 ? 1 : c === 4 ? 2 : c === 5 ? 4 : 8;
      score += base * mult;
      for (let i = 0; i < c; i++) scoringDice.push(f);
    } else {
      // c is 1 or 2; only 1s and 5s score individually.
      if (f === 1) { score += c * 100; for (let i = 0; i < c; i++) scoringDice.push(1); }
      else if (f === 5) { score += c * 50; for (let i = 0; i < c; i++) scoringDice.push(5); }
    }
  }
  const allScore = score > 0 && scoringDice.length === dice.length;
  return { score, scoringDice, allScore };
}

// ---------------------------------------------------------------------------
// autoPlayTurn(rng, threshold) -> banked score (0 on bust).
// rng() returns a uniform die 1..6.
// ---------------------------------------------------------------------------
export function autoPlayTurn(rng, threshold) {
  let turnTotal = 0;
  let diceLeft = 6;
  for (;;) {
    const roll = [];
    for (let i = 0; i < diceLeft; i++) roll.push(rng());
    const { score, scoringDice } = scoreRoll(roll);
    if (score === 0) return 0; // BUST
    turnTotal += score;
    if (turnTotal >= threshold) return turnTotal; // BANK
    const remaining = diceLeft - scoringDice.length;
    diceLeft = remaining === 0 ? 6 : remaining; // hot dice -> fresh 6
  }
}

// ---------------------------------------------------------------------------
// Monte-Carlo payout math.
// ---------------------------------------------------------------------------
export function montecarlo(thresholds, turnsPerThreshold, rng, houseTarget = 0.975) {
  const rows = [];
  for (const T of thresholds) {
    let busts = 0;
    let sum = 0;
    const scores = new Array(turnsPerThreshold);
    for (let i = 0; i < turnsPerThreshold; i++) {
      const s = autoPlayTurn(rng, T);
      if (s === 0) busts++;
      sum += s;
      scores[i] = s;
    }
    const n = turnsPerThreshold;
    const meanScore = sum / n;
    const bustProb = busts / n;
    scores.sort((a, b) => a - b);
    const p999 = scores[Math.min(n - 1, Math.floor(0.999 * (n - 1)))];
    const suggestedK = Math.round(meanScore / houseTarget);
    const houseEdge = 1 - meanScore / suggestedK;
    rows.push({ T, bustProb, meanScore, suggestedK, houseEdge, p999 });
  }
  return rows;
}

// ---------------------------------------------------------------------------
// Self-test + CLI (Node): `node farkle-engine.js`
// ---------------------------------------------------------------------------
function _assertEq(a, b, msg) {
  if (a !== b) throw new Error(`ASSERT FAIL ${msg}: ${a} !== ${b}`);
}

function selfTest() {
  _assertEq(scoreRoll([1, 1, 1, 5, 5, 2]).score, 1100, "[1,1,1,5,5,2]");
  _assertEq(scoreRoll([1, 2, 3, 4, 5, 6]).score, 1500, "straight");
  _assertEq(scoreRoll([2, 2, 2, 3, 4, 6]).score, 200, "[2,2,2,3,4,6]");
  _assertEq(scoreRoll([5]).score, 50, "[5]");
  _assertEq(scoreRoll([2, 3, 4, 6]).score, 0, "bust");
  _assertEq(scoreRoll([1, 1, 1, 1, 1, 1]).score, 8000, "six 1s");
  _assertEq(scoreRoll([6, 6, 6, 6]).score, 1200, "four 6s");
  _assertEq(scoreRoll([5, 5, 5, 5]).score, 1000, "four 5s");
  _assertEq(scoreRoll([2, 2, 2, 2, 2]).score, 800, "five 2s");
  _assertEq(scoreRoll([1, 5]).score, 150, "[1,5]");
  _assertEq(scoreRoll([1, 2, 3, 4, 5, 6]).allScore, true, "straight allScore");
  _assertEq(scoreRoll([1, 1, 1, 5, 5, 2]).allScore, false, "not hot");
  _assertEq(scoreRoll([1, 1, 1, 5, 5, 5]).allScore, true, "hot dice");
  // dieFromHash determinism
  _assertEq(dieFromHash("deadbeef", 0), dieFromHash("deadbeef", 0), "die determinism");
  console.log("scoreRoll/dieFromHash self-test: PASS");
}

function formatTable(rows, houseTarget) {
  const pad = (s, w) => String(s).padStart(w);
  console.log("");
  console.log(`Monte-Carlo payout table (house target payout = ${houseTarget} S)`);
  console.log("T      bustProb   E[score]  suggestedK  houseEdge   maxScore(99.9pct)");
  for (const r of rows) {
    console.log(
      pad(r.T, 5) + "  " +
      pad(r.bustProb.toFixed(4), 8) + "  " +
      pad(r.meanScore.toFixed(2), 8) + "  " +
      pad(r.suggestedK, 10) + "  " +
      pad((r.houseEdge * 100).toFixed(2) + "%", 9) + "  " +
      pad(r.p999, 10)
    );
  }
}

function isMain() {
  try {
    return typeof process !== "undefined" && process.argv && process.argv[1] &&
      import.meta.url === "file://" + process.argv[1];
  } catch (e) { return false; }
}

// Print deterministic die samples for cross-checking with Python.
export function dieSamples(seedHex, n) {
  const out = [];
  for (let i = 0; i < n; i++) out.push(dieFromHash(seedHex, i));
  return out;
}

if (isMain()) {
  selfTest();
  console.log("dieFromHash('farkle-demo', 0..9):", dieSamples("farkle-demo", 10).join(","));
  const thresholds = [300, 400, 500, 600, 750, 1000, 1250, 1500, 2000, 3000];
  const TURNS = 300000;
  const rng = () => 1 + Math.floor(Math.random() * 6);
  const rows = montecarlo(thresholds, TURNS, rng);
  formatTable(rows, 0.975);
  console.log("");
  console.log("PASS");
}
