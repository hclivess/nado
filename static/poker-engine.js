// poker-engine.js — dependency-free heads-up 5-card showdown poker engine.
//
// ES module. Runs in browser and Node. No imports.
//
// A deterministic shared shuffle lets two independent clients derive the
// identical deal from the same seed (e.g. a blake2b hash), so a heads-up
// showdown can be settled without either side trusting the other's RNG.
//
// Cards are objects: { rank, suit }
//   rank: integer 2..14   (11=J, 12=Q, 13=K, 14=A)
//   suit: 's' | 'h' | 'd' | 'c'
//
// Exports (named + a default object bundling all of them):
//   dealHeadsUp(seedHex) -> { a: card[5], b: card[5] }
//   evalHand(cards5)     -> { category, name, ranks }
//   compareHands(a5, b5) -> 1 | -1 | 0
//   handName(cards5)     -> string
//   cardStr(card)        -> string  e.g. "A♠"

'use strict';

// ---------------------------------------------------------------------------
// Deterministic PRNG
// ---------------------------------------------------------------------------
//
// We seed a small, well-mixed generator purely from the hex string so the
// output is identical across JS engines (no reliance on Math.random, no
// dependence on floating-point rounding for the core state).
//
// State advance uses mulberry32 (32-bit integer arithmetic via >>> 0), which
// is deterministic and portable. The 32-bit seed is derived by folding the
// hex digits through an FNV-1a-style hash so the whole seed contributes.

function seedTo32(seedHex) {
  // Accept any string; normalize. We hash the raw characters so even
  // non-hex input is handled deterministically, but the intended input is hex.
  const s = String(seedHex);
  // FNV-1a 32-bit
  let h = 0x811c9dc5 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    // h *= 16777619, kept in 32-bit range via Math.imul
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  // Extra avalanche so short seeds still spread well.
  h ^= h >>> 16;
  h = Math.imul(h, 0x7feb352d) >>> 0;
  h ^= h >>> 15;
  h = Math.imul(h, 0x846ca68b) >>> 0;
  h ^= h >>> 16;
  return h >>> 0;
}

function mulberry32(a) {
  // Returns a function producing a uint32 each call (deterministic).
  let state = a >>> 0;
  return function next() {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1) >>> 0;
    t = (t ^ (t + (Math.imul(t ^ (t >>> 7), t | 61) >>> 0))) >>> 0;
    return (t ^ (t >>> 14)) >>> 0;
  };
}

// Unbiased integer in [0, n) using rejection sampling over 32-bit output.
function randInt(next, n) {
  if (n <= 0) return 0;
  const limit = Math.floor(0x100000000 / n) * n; // largest multiple of n <= 2^32
  let x;
  do {
    x = next();
  } while (x >= limit);
  return x % n;
}

// ---------------------------------------------------------------------------
// Deck + deterministic deal
// ---------------------------------------------------------------------------

const SUITS = ['s', 'h', 'd', 'c'];
const RANKS = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14];

function buildDeck() {
  const deck = [];
  // Fixed canonical order so the shuffle input is identical everywhere.
  for (let s = 0; s < SUITS.length; s++) {
    for (let r = 0; r < RANKS.length; r++) {
      deck.push({ rank: RANKS[r], suit: SUITS[s] });
    }
  }
  return deck;
}

// dealHeadsUp: pure deterministic function of seedHex only.
function dealHeadsUp(seedHex) {
  const next = mulberry32(seedTo32(seedHex));
  const deck = buildDeck();
  // Fisher–Yates from the top down.
  for (let i = deck.length - 1; i > 0; i--) {
    const j = randInt(next, i + 1);
    const tmp = deck[i];
    deck[i] = deck[j];
    deck[j] = tmp;
  }
  // Alternate deal (A, B, A, B, ...) is conventional; since all 10 come from
  // one shuffled deck they are guaranteed distinct regardless of order.
  const a = [];
  const b = [];
  for (let k = 0; k < 5; k++) {
    a.push(deck[2 * k]);
    b.push(deck[2 * k + 1]);
  }
  return { a, b };
}

// ---------------------------------------------------------------------------
// Hand evaluation
// ---------------------------------------------------------------------------

const CATEGORY_NAMES = [
  'High Card',       // 0
  'Pair',            // 1
  'Two Pair',        // 2
  'Three of a Kind', // 3
  'Straight',        // 4
  'Flush',           // 5
  'Full House',      // 6
  'Four of a Kind',  // 7
  'Straight Flush',  // 8
];

// Evaluate exactly 5 cards. Returns { category, name, ranks }.
function evalHand(cards5) {
  if (!Array.isArray(cards5) || cards5.length !== 5) {
    throw new Error('evalHand expects exactly 5 cards');
  }

  const ranks = cards5.map((c) => c.rank);
  const suits = cards5.map((c) => c.suit);

  // Count occurrences of each rank.
  const counts = new Map();
  for (const r of ranks) counts.set(r, (counts.get(r) || 0) + 1);

  // Sort rank groups by (count desc, rank desc). This yields the tiebreak
  // order for pair/trips/quads/two-pair/full-house/high-card automatically.
  const groups = Array.from(counts.entries()).sort((x, y) => {
    if (y[1] !== x[1]) return y[1] - x[1]; // higher count first
    return y[0] - x[0];                    // higher rank first
  });
  const countPattern = groups.map((g) => g[1]).join(''); // e.g. "32", "2111"
  const orderedRanks = groups.map((g) => g[0]);

  const isFlush = suits.every((s) => s === suits[0]);

  // Straight detection. Distinct sorted ranks descending.
  const distinct = Array.from(new Set(ranks)).sort((a, b) => b - a);
  let isStraight = false;
  let straightHigh = 0;
  if (distinct.length === 5) {
    if (distinct[0] - distinct[4] === 4) {
      isStraight = true;
      straightHigh = distinct[0];
    } else if (
      // Wheel: A-2-3-4-5. Ace plays LOW, straight-high = 5.
      distinct[0] === 14 &&
      distinct[1] === 5 &&
      distinct[2] === 4 &&
      distinct[3] === 3 &&
      distinct[4] === 2
    ) {
      isStraight = true;
      straightHigh = 5;
    }
  }

  let category;
  let outRanks;

  if (isStraight && isFlush) {
    category = 8; // Straight Flush (royal flush is just the top straight flush)
    outRanks = [straightHigh];
  } else if (countPattern === '41') {
    category = 7; // Four of a Kind: [quadRank, kicker]
    outRanks = orderedRanks;
  } else if (countPattern === '32') {
    category = 6; // Full House: [tripRank, pairRank]
    outRanks = orderedRanks;
  } else if (isFlush) {
    category = 5; // Flush: 5 ranks descending
    outRanks = ranks.slice().sort((a, b) => b - a);
  } else if (isStraight) {
    category = 4; // Straight: [straightHigh]
    outRanks = [straightHigh];
  } else if (countPattern === '311') {
    category = 3; // Three of a Kind: [tripRank, kicker1, kicker2]
    outRanks = orderedRanks;
  } else if (countPattern === '221') {
    category = 2; // Two Pair: [highPair, lowPair, kicker]
    outRanks = orderedRanks;
  } else if (countPattern === '2111') {
    category = 1; // Pair: [pairRank, k1, k2, k3]
    outRanks = orderedRanks;
  } else {
    category = 0; // High Card: 5 ranks descending
    outRanks = orderedRanks;
  }

  return { category, name: CATEGORY_NAMES[category], ranks: outRanks };
}

// ---------------------------------------------------------------------------
// Comparison
// ---------------------------------------------------------------------------

// compareHands: 1 if A wins, -1 if B wins, 0 if exact tie.
function compareHands(handA5, handB5) {
  const ea = evalHand(handA5);
  const eb = evalHand(handB5);
  if (ea.category !== eb.category) return ea.category > eb.category ? 1 : -1;
  const len = Math.max(ea.ranks.length, eb.ranks.length);
  for (let i = 0; i < len; i++) {
    const ra = ea.ranks[i] || 0;
    const rb = eb.ranks[i] || 0;
    if (ra !== rb) return ra > rb ? 1 : -1;
  }
  return 0;
}

// ---------------------------------------------------------------------------
// Presentation helpers
// ---------------------------------------------------------------------------

const RANK_LABEL = {
  11: 'J',
  12: 'Q',
  13: 'K',
  14: 'A',
};
const SUIT_SYMBOL = { s: '♠', h: '♥', d: '♦', c: '♣' };

function rankLabel(r) {
  return RANK_LABEL[r] || String(r);
}

function cardStr(card) {
  return rankLabel(card.rank) + (SUIT_SYMBOL[card.suit] || card.suit);
}

function handName(cards5) {
  return evalHand(cards5).name;
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export {
  dealHeadsUp,
  evalHand,
  compareHands,
  handName,
  cardStr,
};

const poker = { dealHeadsUp, evalHand, compareHands, handName, cardStr };
export default poker;

// ---------------------------------------------------------------------------
// Node self-test (runs only when executed directly: `node poker-engine.js`)
// ---------------------------------------------------------------------------

const isNodeMain =
  typeof process !== 'undefined' &&
  process.argv &&
  process.argv[1] &&
  // Compare resolved path of this module against argv[1].
  (() => {
    try {
      // import.meta.url is a file:// URL of this module.
      const here = decodeURIComponent(
        new URL(import.meta.url).pathname
      );
      const invoked = process.argv[1];
      // Match on suffix to be robust to symlinks / relative invocation.
      return (
        here === invoked ||
        here.endsWith(invoked) ||
        invoked.endsWith('poker-engine.js') && here.endsWith('poker-engine.js')
      );
    } catch (e) {
      return false;
    }
  })();

if (isNodeMain) {
  let passed = 0;
  let failed = 0;

  function ok(label, cond) {
    if (cond) {
      passed++;
      console.log('PASS: ' + label);
    } else {
      failed++;
      console.log('FAIL: ' + label);
    }
  }

  // Helper to build a hand from compact notation, e.g. "As Ks Qs Js Ts".
  function H(str) {
    return str.trim().split(/\s+/).map((tok) => {
      const suit = tok[tok.length - 1].toLowerCase();
      const rp = tok.slice(0, tok.length - 1).toUpperCase();
      let rank;
      if (rp === 'A') rank = 14;
      else if (rp === 'K') rank = 13;
      else if (rp === 'Q') rank = 12;
      else if (rp === 'J') rank = 11;
      else if (rp === 'T' || rp === '10') rank = 10;
      else rank = parseInt(rp, 10);
      return { rank, suit };
    });
  }

  // --- Category ordering: each strictly beats the next ---
  const royal = H('As Ks Qs Js Ts');       // straight flush (royal)
  const stFlush = H('9h 8h 7h 6h 5h');      // straight flush
  const quads = H('Qc Qd Qh Qs 4d');        // four of a kind
  const boat = H('Jc Jd Jh 4s 4d');         // full house
  const flush = H('Ah Jh 8h 5h 2h');        // flush
  const straight = H('9c 8d 7h 6s 5c');     // straight
  const trips = H('7c 7d 7h Kd 2s');        // three of a kind
  const twoPair = H('9c 9d 4h 4s Kd');      // two pair
  const onePair = H('5c 5d Kh 9s 2d');      // pair
  const highCard = H('Ah Qd 9c 5s 2h');     // high card

  ok('royal (SF) > straight flush', compareHands(royal, stFlush) === 1);
  ok('straight flush > quads', compareHands(stFlush, quads) === 1);
  ok('quads > full house', compareHands(quads, boat) === 1);
  ok('full house > flush', compareHands(boat, flush) === 1);
  ok('flush > straight', compareHands(flush, straight) === 1);
  ok('straight > trips', compareHands(straight, trips) === 1);
  ok('trips > two pair', compareHands(trips, twoPair) === 1);
  ok('two pair > pair', compareHands(twoPair, onePair) === 1);
  ok('pair > high card', compareHands(onePair, highCard) === 1);
  // Reverse direction sanity.
  ok('high card < pair (reverse)', compareHands(highCard, onePair) === -1);

  // --- Category classification ---
  ok('royal classified as straight flush (8)', evalHand(royal).category === 8);
  ok('quads classified (7)', evalHand(quads).category === 7);
  ok('boat classified (6)', evalHand(boat).category === 6);
  ok('flush classified (5)', evalHand(flush).category === 5);
  ok('straight classified (4)', evalHand(straight).category === 4);
  ok('trips classified (3)', evalHand(trips).category === 3);
  ok('two pair classified (2)', evalHand(twoPair).category === 2);
  ok('pair classified (1)', evalHand(onePair).category === 1);
  ok('high card classified (0)', evalHand(highCard).category === 0);

  // --- Wheel straight A-2-3-4-5 ---
  const wheel = H('Ad 2c 3h 4s 5d');
  ok('wheel is a straight (cat 4)', evalHand(wheel).category === 4);
  ok('wheel straight-high is 5', evalHand(wheel).ranks[0] === 5);
  ok('wheel beats no-straight (high card)', compareHands(wheel, highCard) === 1);
  const sixHigh = H('2c 3d 4h 5s 6c'); // 2-3-4-5-6
  ok('2-3-4-5-6 beats the wheel', compareHands(sixHigh, wheel) === 1);
  ok('wheel loses to 2-3-4-5-6', compareHands(wheel, sixHigh) === -1);
  // Ace-high straight beats king-high straight.
  const broadway = H('Ac Kd Qh Js Td');
  const kingHigh = H('Kc Qd Jh Ts 9c');
  ok('broadway (A-high straight) beats K-high straight',
    compareHands(broadway, kingHigh) === 1);

  // Wheel straight flush vs higher straight flush.
  const wheelSF = H('As 2s 3s 4s 5s');
  ok('wheel straight flush is SF (cat 8)', evalHand(wheelSF).category === 8);
  ok('6-high straight flush beats wheel SF', compareHands(stFlush, wheelSF) === 1);

  // --- Flush tiebreak by high cards ---
  const flushHi = H('Ah Kh 7h 4h 2h');
  const flushLo = H('Ah Qh 7h 4h 2h');
  ok('flush tiebreak: A-K high beats A-Q high', compareHands(flushHi, flushLo) === 1);
  const flushLow2 = H('Ah Kh 7h 4h 3h'); // differs only in the last card
  ok('flush tiebreak on last card', compareHands(flushLow2, flushHi) === 1);

  // --- Two-pair tiebreak: higher pair, then kicker ---
  const tpA = H('Kc Kd 3h 3s 9d'); // KK 33 9
  const tpB = H('Qc Qd Jh Js Ad'); // QQ JJ A
  ok('two pair: higher top pair wins (KK > QQ)', compareHands(tpA, tpB) === 1);
  const tpC = H('Kc Kd 3h 3s 9d'); // KK 33 9
  const tpD = H('Kh Ks 3c 3d 8h'); // KK 33 8
  ok('two pair: same pairs, higher kicker wins', compareHands(tpC, tpD) === 1);
  const tpE = H('Kc Kd 5h 5s 2d'); // KK 55 2
  const tpF = H('Kh Ks 4c 4d Ah'); // KK 44 A
  ok('two pair: same top pair, higher second pair wins', compareHands(tpE, tpF) === 1);

  // --- Full-house tiebreak by trip rank ---
  const fhA = H('9c 9d 9h 2s 2d'); // 999 22
  const fhB = H('8c 8d 8h Ac As'); // 888 AA
  ok('full house: higher trips win (999 > 888)', compareHands(fhA, fhB) === 1);
  const fhC = H('9c 9d 9h 2s 2d'); // 999 22
  const fhD = H('9s 9c 9d 5h 5s'); // 999 55  (need distinct cards from fhC in reality;
  // for eval it only reads ranks/suits independently, distinctness not required by evalHand)
  ok('full house: same trips, higher pair wins', compareHands(fhD, fhC) === 1);

  // --- Quads kicker ---
  const q1 = H('7c 7d 7h 7s Kd'); // 7777 K
  const q2 = H('7c 7d 7h 7s Qd'); // 7777 Q
  ok('quads: higher kicker wins', compareHands(q1, q2) === 1);
  const q3 = H('Ac Ad Ah As 2d'); // AAAA 2
  ok('higher quads beat lower quads', compareHands(q3, q1) === 1);

  // --- Trips kicker ---
  const t1 = H('7c 7d 7h Ad 2s'); // 777 A 2
  const t2 = H('7c 7d 7h Kd Qs'); // 777 K Q
  ok('trips: higher first kicker wins (A > K)', compareHands(t1, t2) === 1);
  const t3 = H('7c 7d 7h Kd 2s'); // 777 K 2
  const t4 = H('7c 7d 7h Kd 3s'); // 777 K 3  (second kicker)
  ok('trips: second kicker breaks tie', compareHands(t4, t3) === 1);

  // --- Pair kicker comparisons ---
  const p1 = H('9c 9d Ah 5s 2d'); // 99 A 5 2
  const p2 = H('9c 9d Kh 5s 2d'); // 99 K 5 2
  ok('pair: higher first kicker wins', compareHands(p1, p2) === 1);
  const p3 = H('9c 9d Kh 7s 2d'); // 99 K 7 2
  const p4 = H('9c 9d Kh 6s 2d'); // 99 K 6 2
  ok('pair: second kicker breaks tie', compareHands(p3, p4) === 1);
  const p5 = H('9c 9d Kh 7s 3d'); // 99 K 7 3
  const p6 = H('9c 9d Kh 7s 2d'); // 99 K 7 2
  ok('pair: third kicker breaks tie', compareHands(p5, p6) === 1);
  const pHi = H('Ac Ad 5h 4s 2d'); // AA
  const pLo = H('Kc Kd Qh Js Td'); // KK
  ok('pair: higher pair beats lower pair', compareHands(pHi, pLo) === 1);

  // --- High-card kicker cascade ---
  const hc1 = H('Ah Kd 9c 5s 3h');
  const hc2 = H('Ah Kd 9c 5s 2h');
  ok('high card: last kicker breaks tie', compareHands(hc1, hc2) === 1);

  // --- Exact ties return 0 ---
  const tie1 = H('Ah Kh Qh Jh 9h'); // flush
  const tie2 = H('As Ks Qs Js 9s'); // same ranks, different suit -> flush tie
  ok('exact tie (equal flushes) returns 0', compareHands(tie1, tie2) === 0);
  const tieStraight1 = H('9c 8d 7h 6s 5c');
  const tieStraight2 = H('9h 8s 7d 6c 5h');
  ok('exact tie (equal straights) returns 0',
    compareHands(tieStraight1, tieStraight2) === 0);
  const tieFH1 = H('9c 9d 9h 2s 2d');
  const tieFH2 = H('9h 9s 9c 2h 2c');
  ok('exact tie (equal full houses) returns 0', compareHands(tieFH1, tieFH2) === 0);

  // --- ranks arrays shape checks ---
  ok('boat ranks = [trip, pair]',
    JSON.stringify(evalHand(boat).ranks) === JSON.stringify([11, 4]));
  ok('two pair ranks = [hi, lo, kicker]',
    JSON.stringify(evalHand(twoPair).ranks) === JSON.stringify([9, 4, 13]));
  ok('quads ranks = [quad, kicker]',
    JSON.stringify(evalHand(quads).ranks) === JSON.stringify([12, 4]));
  ok('high card ranks descending',
    JSON.stringify(evalHand(highCard).ranks) === JSON.stringify([14, 12, 9, 5, 2]));

  // --- handName / cardStr ---
  ok('handName(boat) = Full House', handName(boat) === 'Full House');
  ok('handName(royal) = Straight Flush', handName(royal) === 'Straight Flush');
  ok('cardStr(As) = A♠', cardStr({ rank: 14, suit: 's' }) === 'A♠');
  ok('cardStr(Th) = 10♥', cardStr({ rank: 10, suit: 'h' }) === '10♥');
  ok('cardStr(2c) = 2♣', cardStr({ rank: 2, suit: 'c' }) === '2♣');

  // --- Deterministic deal ---
  const seed = 'deadbeefcafebabe0123456789abcdef';
  const d1 = dealHeadsUp(seed);
  const d2 = dealHeadsUp(seed);
  ok('deal is deterministic (same seed -> identical)',
    JSON.stringify(d1) === JSON.stringify(d2));

  // Different seeds should (essentially always) differ.
  const d3 = dealHeadsUp('ffffffffffffffffffffffffffffffff');
  ok('different seed -> different deal',
    JSON.stringify(d1) !== JSON.stringify(d3));

  // All 10 dealt cards distinct.
  (function () {
    const all = d1.a.concat(d1.b);
    const keys = new Set(all.map((c) => c.rank + c.suit));
    ok('all 10 dealt cards distinct', keys.size === 10);
    ok('each side has 5 cards', d1.a.length === 5 && d1.b.length === 5);
    // Ranks in valid range and suits valid.
    const validRank = all.every((c) => c.rank >= 2 && c.rank <= 14);
    const validSuit = all.every((c) => 'shdc'.includes(c.suit));
    ok('all dealt cards have valid rank/suit', validRank && validSuit);
  })();

  // Deal can be scored end to end.
  (function () {
    const r = compareHands(d1.a, d1.b);
    ok('dealt hands compare to a valid result (-1/0/1)',
      r === 1 || r === 0 || r === -1);
  })();

  // Full 52-card coverage across many seeds: shuffle must be a permutation.
  (function () {
    // Rebuild the full shuffled deck for one seed and confirm 52 distinct cards.
    const next = mulberry32(seedTo32(seed));
    const deck = buildDeck();
    for (let i = deck.length - 1; i > 0; i--) {
      const j = randInt(next, i + 1);
      const tmp = deck[i]; deck[i] = deck[j]; deck[j] = tmp;
    }
    const keys = new Set(deck.map((c) => c.rank + c.suit));
    ok('shuffled deck is a full 52-card permutation', keys.size === 52);
  })();

  console.log('\n' + passed + ' passed, ' + failed + ' failed');
  if (failed > 0) {
    process.exit(1);
  } else {
    process.exit(0);
  }
}
