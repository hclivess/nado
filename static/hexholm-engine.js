// hexholm-engine.js — HEXHOLM: the headless, deterministic rules engine for NADO's 2-4 player island
// settlement duel (classic hex-resource genre — MECHANICS ONLY: every name, card title, rules text and
// artwork here is original; game mechanics are not copyrightable, names/text/art are, so none were copied).
//
// The engine is the REFEREE (the stormhold/chess trust model): the contract records an ordered move log
// with per-move pinned FUTURE block-hash seeds; every client replays the log through this module and
// derives byte-identical state. An illegal move (or a false hidden-card claim, once secrets reveal) marks
// the game corrupt in every honest client and the settle paths take over — cheating cannot profit.
//
// THE GAME (1:1 with the classic rules):
//   • 19-hex island, radius-2: 4 Timber, 4 Wool, 4 Grain, 3 Clay, 3 Ore, 1 Wastes. Number tokens
//     {2,3×2,4×2,5×2,6×2,8×2,9×2,10×2,11×2,12} on non-waste hexes; layout seeded by the join-time block
//     hash, re-dealt until no two 6/8 touch. 9 harbors (4 any-3:1 + one 2:1 per resource) on the standard
//     coastal frame spacing, types seeded.
//   • Setup snake: each player places homestead+road, order 1..n then n..1; the second homestead pays out
//     its adjacent tiles.
//   • Turn: (optional Warden before the roll) → roll 2d6 from the move's pinned seed → production
//     (bank-limited: if a resource can't fully pay MULTIPLE claimants that round, nobody gets it) — or on
//     a 7: every hand over 7 discards half (rounded down), then the mover moves the MARAUDER and steals a
//     random card → main phase: trade (bank 4:1, harbor 3:1/2:1, table offers with the mover), build
//     (road 1T+1C · homestead 1T+1C+1W+1G · keep 2G+3O · scroll 1W+1G+1O), play at most ONE scroll per
//     turn (never one bought the same turn) → end. Supply: 15 roads, 5 homesteads, 4 keeps each.
//   • SCROLLS (dev deck, 25: 14 Warden · 5 Charter · 2 Pathwright · 2 Bounty · 2 Levy). HIDDEN via the
//     commit-reveal model: each seat commits H(secret) before the game; a buy's card = a draw from the
//     buyer's OWN private stream (seeded by the buy move's block hash + their secret) without replacement
//     from the full 25 composition — hold'em's MULTI-DECK RULE, the only sound dealer-less hidden-card
//     scheme. Total buys are capped at 25 table-wide (public counter keeps the scarcity). Playing a scroll
//     publicly CLAIMS its type; at reveal every client re-derives the stream and a false claim = corrupt.
//   • Badges: LONG ROAD (2 VP, first 5+ continuous, passes only to a strict leader, shelved on ties) and
//     WARDENS' BANNER (2 VP, first 3+ wardens played, same passing rule). Homestead 1 VP · keep 2 VP ·
//     charter 1 hidden VP. First to 10 on their own turn calls the win.
import { blake2bHash } from "./nadotx.js";

// ---- resources / costs / scrolls -------------------------------------------------------------------
export const RES = ["timber", "clay", "wool", "grain", "ore"];
export const RES_ICON = ["🌲", "🧱", "🐑", "🌾", "⛰️"];
export const COST = {
  road: [1, 1, 0, 0, 0], stead: [1, 1, 1, 1, 0], keep: [0, 0, 0, 2, 3], scroll: [0, 0, 1, 1, 1],
};
export const WARDEN = 1, CHARTER = 2, PATHWRIGHT = 3, BOUNTY = 4, LEVY = 5;
export const DEV_NAMES = { [WARDEN]: "Warden", [CHARTER]: "Charter", [PATHWRIGHT]: "Pathwright",
                           [BOUNTY]: "Bounty", [LEVY]: "Levy" };
export const DEV_BAG = [WARDEN, WARDEN, WARDEN, WARDEN, WARDEN, WARDEN, WARDEN, WARDEN, WARDEN, WARDEN,
                        WARDEN, WARDEN, WARDEN, WARDEN, CHARTER, CHARTER, CHARTER, CHARTER, CHARTER,
                        PATHWRIGHT, PATHWRIGHT, BOUNTY, BOUNTY, LEVY, LEVY];
export const SUPPLY = { road: 15, stead: 5, keep: 4 };
export const BANK_EACH = 19, HAND_LIMIT = 7, WIN_VP = 10, DEV_CAP = 25;

// ---- move encoding: op (6 bits) | a (22 bits) | b (25 bits) — always < 2^53 -------------------------
export const OP = { ROLL: 1, SETUP: 2, ROAD: 3, STEAD: 4, KEEP: 5, BUY: 6, WARDEN: 7, PATH: 8,
                    BOUNTY: 9, LEVY: 10, ROBBER: 12, DISCARD: 13, BANK: 14, OFFER: 15, ACCEPT: 16,
                    RESCIND: 18, END: 19, WIN: 20 };
const A_LIM = 2 ** 22, B_LIM = 2 ** 25;
export const enc = (op, a = 0, b = 0) => op + a * 64 + b * 64 * A_LIM;
export const dec = (e) => ({ op: e % 64, a: Math.floor(e / 64) % A_LIM, b: Math.floor(e / (64 * A_LIM)) });
// resource-count packs (trade offers: 3 bits each · discards: 5 bits each)
export const pack3 = (c) => c.reduce((s, n, r) => s + Math.min(7, n) * 8 ** r, 0);
export const unpack3 = (p) => RES.map((_, r) => Math.floor(p / 8 ** r) % 8);
export const pack5 = (c) => c.reduce((s, n, r) => s + Math.min(31, n) * 32 ** r, 0);
export const unpack5 = (p) => RES.map((_, r) => Math.floor(p / 32 ** r) % 32);

// ---- deterministic randomness (the cards.js chain-draw convention) ---------------------------------
const H = (v) => BigInt("0x" + blake2bHash(v));
const der = (q, salt) => H(q + BigInt(salt));                       // q = BigInt(bh(h)) + BigInt(bh(h+1))
const derN = (q, salt, n) => Number(der(q, salt) % BigInt(n));

// ---- board geometry (all-integer lattice: x in √3/2 units, y in 1/2 units — no float trig) ----------
// Pointy-top hex (q,r): center X = 2q+r, Y = 3r; corners at (X,Y±2) and (X±1,Y±1). Every corner lands on
// the integer lattice, so vertex identity is exact and identical in every runtime.
function buildGeometry() {
  const hexes = [];
  for (let r = -2; r <= 2; r++)
    for (let q = -2; q <= 2; q++)
      if (Math.abs(q + r) <= 2) hexes.push({ q, r, X: 2 * q + r, Y: 3 * r });
  hexes.sort((h1, h2) => h1.r - h2.r || h1.q - h2.q);
  const CO = [[0, -2], [1, -1], [1, 1], [0, 2], [-1, 1], [-1, -1]];   // clockwise corner offsets
  const vKey = (x, y) => x + "," + y;
  const vmap = new Map(), verts = [], emap = new Map(), edges = [];
  for (const h of hexes) {
    h.corners = CO.map(([dx, dy]) => {
      const k = vKey(h.X + dx, h.Y + dy);
      if (!vmap.has(k)) { vmap.set(k, verts.length); verts.push({ x: h.X + dx, y: h.Y + dy, hexes: [], edges: [], adj: [] }); }
      return vmap.get(k);
    });
  }
  // canonical vertex order (y, then x) — vertex ids are MOVE ENCODINGS, so this order is consensus
  const order = verts.map((_, i) => i).sort((a, b) => verts[a].y - verts[b].y || verts[a].x - verts[b].x);
  const remap = []; order.forEach((old, idx) => remap[old] = idx);
  const verts2 = order.map((old) => ({ ...verts[old], hexes: [], edges: [], adj: [] }));
  for (const h of hexes) { h.corners = h.corners.map((v) => remap[v]); h.corners.forEach((v) => verts2[v].hexes.push(hexes.indexOf(h))); }
  for (const h of hexes)
    for (let i = 0; i < 6; i++) {
      const a = h.corners[i], b = h.corners[(i + 1) % 6], k = Math.min(a, b) + "-" + Math.max(a, b);
      if (!emap.has(k)) { emap.set(k, edges.length); edges.push({ a: Math.min(a, b), b: Math.max(a, b), hexes: [] }); }
      edges[emap.get(k)].hexes.push(hexes.indexOf(h));
    }
  edges.sort((e1, e2) => (verts2[e1.a].y + verts2[e1.b].y) - (verts2[e2.a].y + verts2[e2.b].y)
                      || (verts2[e1.a].x + verts2[e1.b].x) - (verts2[e2.a].x + verts2[e2.b].x)
                      || e1.a - e2.a);
  edges.forEach((e, i) => { verts2[e.a].edges.push(i); verts2[e.b].edges.push(i);
                            verts2[e.a].adj.push(e.b); verts2[e.b].adj.push(e.a); });
  // hexes adjacency (for the 6/8 spacing rule) + coastal ring (harbor frame)
  hexes.forEach((h, i) => { h.id = i; h.nbr = hexes.filter((o) => o !== h &&
    Math.abs(o.q - h.q) <= 1 && Math.abs(o.r - h.r) <= 1 && Math.abs((o.q + o.r) - (h.q + h.r)) <= 1).map((o) => hexes.indexOf(o)); });
  const coastal = edges.map((e, i) => i).filter((i) => edges[i].hexes.length === 1);
  // walk the coast as a ring: start at the topmost coastal edge, follow shared vertices
  const ring = [coastal[0]]; const used = new Set(ring);
  while (ring.length < coastal.length) {
    const last = edges[ring[ring.length - 1]];
    const next = coastal.find((i) => !used.has(i) && (edges[i].a === last.a || edges[i].a === last.b ||
                                                      edges[i].b === last.a || edges[i].b === last.b));
    if (next === undefined) break;
    ring.push(next); used.add(next);
  }
  // 9 harbors on the standard frame spacing (3/4 alternating around the 30-edge coast)
  const PORT_AT = [0, 3, 7, 10, 13, 17, 20, 23, 27].map((i) => ring[i]);
  return { hexes, verts: verts2, edges, ring, PORT_AT };
}
export const GEO = buildGeometry();
export const NHEX = GEO.hexes.length, NVERT = GEO.verts.length, NEDGE = GEO.edges.length;

// ---- seeded layout ---------------------------------------------------------------------------------
const TILE_BAG = [0, 0, 0, 0, 2, 2, 2, 2, 3, 3, 3, 3, 1, 1, 1, 4, 4, 4, -1];   // res ids, -1 = Wastes
const TOKEN_BAG = [2, 3, 3, 4, 4, 5, 5, 6, 6, 8, 8, 9, 9, 10, 10, 11, 11, 12];
function shuffled(arr, q, salt) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) { const j = derN(q, salt * 1000 + i, i + 1); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}
export function layout(qkh, cap) {
  for (let attempt = 0; ; attempt++) {                     // re-deal until no two 6/8 hexes touch
    const tiles = shuffled(TILE_BAG, qkh, 11 + attempt * 7);
    const tokens = shuffled(TOKEN_BAG, qkh, 12 + attempt * 7);
    const tok = []; let t = 0;
    for (let i = 0; i < NHEX; i++) tok[i] = tiles[i] === -1 ? 0 : tokens[t++];
    const hot = (i) => tok[i] === 6 || tok[i] === 8;
    if (!GEO.hexes.some((h, i) => hot(i) && h.nbr.some(hot))) {
      const ports = shuffled([-1, -1, -1, -1, 0, 1, 2, 3, 4], qkh, 13);  // -1 = any-3:1, else 2:1 res
      return { tiles, tokens: tok, ports, first: derN(qkh, 14, cap) + 1,
               waste: tiles.indexOf(-1) };
    }
  }
}

// ---- player + state --------------------------------------------------------------------------------
function newPlayer() {
  return { res: [0, 0, 0, 0, 0], roads: new Set(), steads: new Set(), keeps: new Set(),
           devKnown: [],            // own view / verify view: drawn scroll types in draw order
           devDrawn: 0, devPlayedTurn: [], plays: { [WARDEN]: 0, [PATHWRIGHT]: 0, [BOUNTY]: 0, [LEVY]: 0 },
           buysBeforeTurn: 0, buysThisTurn: 0, roadLen: 0, owe: 0 };
}
const total = (c) => c.reduce((s, n) => s + n, 0);
const canPayCost = (res, cost) => cost.every((n, r) => res[r] >= n);
const payCost = (st, p, cost) => cost.forEach((n, r) => { p.res[r] -= n; st.bank[r] += n; });

function seatOrder(st) {                                   // ring order from the seeded first seat
  return Array.from({ length: st.cap }, (_, i) => ((st.first - 1 + i) % st.cap) + 1);
}
export function setupSlots(st) {                           // snake: order then reversed
  const o = seatOrder(st); return o.concat(o.slice().reverse());
}

// longest continuous road of a seat (edges distinct; blocked through foreign buildings)
function longestRoad(st, s) {
  const mine = st.players[s].roads; let best = 0;
  const blockAt = (v) => { for (let o = 1; o <= st.cap; o++) if (o !== s &&
    (st.players[o].steads.has(v) || st.players[o].keeps.has(v))) return true; return false; };
  const walk = (v, used, len) => {
    best = Math.max(best, len);
    if (len && blockAt(v)) return;                         // may START at a blocked vertex, not pass one
    for (const e of GEO.verts[v].edges)
      if (mine.has(e) && !used.has(e)) { used.add(e); walk(GEO.edges[e].a === v ? GEO.edges[e].b : GEO.edges[e].a, used, len + 1); used.delete(e); }
  };
  for (const e of mine) { walk(GEO.edges[e].a, new Set([e]), 1) ; walk(GEO.edges[e].b, new Set([e]), 1); }
  return best;
}
function refreshBadges(st) {
  for (let s = 1; s <= st.cap; s++) st.players[s].roadLen = longestRoad(st, s);
  // LONG ROAD: the holder keeps the badge until another road is STRICTLY longer; passes only to a UNIQUE
  // strict leader (>=5), is SHELVED (nobody holds it) when strict leaders tie, and a holder whose road
  // breaks below 5 loses it — then the unique >=5 leader (if any) takes it.
  const lens = {}; for (let s = 1; s <= st.cap; s++) lens[s] = st.players[s].roadLen;
  const contenders = Object.keys(lens).map(Number).filter((s) => lens[s] >= 5);
  const maxLen = contenders.length ? Math.max(...contenders.map((s) => lens[s])) : 0;
  const leaders = contenders.filter((s) => lens[s] === maxLen);
  const holder = st.roadHolder;
  if (holder && lens[holder] >= 5) {
    if (maxLen > lens[holder]) st.roadHolder = leaders.length === 1 ? leaders[0] : 0;
  } else {
    st.roadHolder = leaders.length === 1 ? leaders[0] : 0;
  }
  // WARDENS' BANNER: first to 3 wardens played takes it; passes only when strictly exceeded. Plays grow
  // one at a time (refresh runs after every move), so the incremental strict-exceed rule is exact.
  for (let s = 1; s <= st.cap; s++) {
    const k = st.players[s].plays[WARDEN];
    if (k >= 3 && (!st.watchHolder || (s !== st.watchHolder && k > st.players[st.watchHolder].plays[WARDEN])))
      st.watchHolder = s;
  }
}
export function publicVp(st, s) {
  const p = st.players[s];
  return p.steads.size + 2 * p.keeps.size + (st.roadHolder === s ? 2 : 0) + (st.watchHolder === s ? 2 : 0);
}
function chartersOf(st, s) {
  const p = st.players[s];
  if (st.secrets[s] == null) return null;                  // unknown without the seat's secret
  return p.devKnown.filter((t) => t === CHARTER).length;
}
export function totalVp(st, s) {
  const c = chartersOf(st, s);
  return c == null ? null : publicVp(st, s) + c;
}

// private scroll stream (multi-deck rule): the n-th draw of seat s removes a card from the buyer's OWN
// remaining 25-composition, indexed by H(buy-move seed + secret + n) — unknowable without the secret,
// un-grindable because the secret commits before the board seed exists.
function drawDev(st, s, q, n) {
  const x = st.secrets[s];
  if (x == null) return 0;                                 // hidden from this viewer
  const p = st.players[s];
  const remaining = DEV_BAG.slice();
  for (const t of p.devKnown) remaining.splice(remaining.indexOf(t), 1);
  return remaining[Number(der(q + x, 5000 + n) % BigInt(remaining.length))];
}

function grant(st, s, r, n) { const k = Math.min(n, st.bank[r]); st.players[s].res[r] += k; st.bank[r] -= k; return k; }
function production(st, roll) {
  const gains = {};                                        // seat -> [5]
  for (let s = 1; s <= st.cap; s++) gains[s] = [0, 0, 0, 0, 0];
  GEO.hexes.forEach((h, i) => {
    if (st.layout.tokens[i] !== roll || i === st.robber) return;
    const r = st.layout.tiles[i]; if (r < 0) return;
    for (const v of h.corners)
      for (let s = 1; s <= st.cap; s++) {
        if (st.players[s].steads.has(v)) gains[s][r] += 1;
        if (st.players[s].keeps.has(v)) gains[s][r] += 2;
      }
  });
  for (let r = 0; r < 5; r++) {                            // bank-shortage rule
    const claimants = Object.keys(gains).filter((s) => gains[s][r] > 0);
    const want = claimants.reduce((n, s) => n + gains[s][r], 0);
    if (want > st.bank[r] && claimants.length > 1) claimants.forEach((s) => gains[s][r] = 0);
  }
  for (let s = 1; s <= st.cap; s++) for (let r = 0; r < 5; r++) if (gains[s][r]) grant(st, s, r, gains[s][r]);
  return gains;
}

function stealFrom(st, thief, victim, q) {
  const hand = st.players[victim].res, n = total(hand);
  if (!n) return -1;
  let idx = derN(q, 3, n);
  for (let r = 0; r < 5; r++) { if (idx < hand[r]) { hand[r]--; st.players[thief].res[r]++; return r; } idx -= hand[r]; }
  return -1;
}
const adjacentSeats = (st, hex) => {
  const out = new Set();
  for (const v of GEO.hexes[hex].corners)
    for (let s = 1; s <= st.cap; s++)
      if (st.players[s].steads.has(v) || st.players[s].keeps.has(v)) out.add(s);
  return out;
};

// vertex/edge legality helpers (exported for the client's tap targets + the bot)
export function vertexFree(st, v) {
  for (let s = 1; s <= st.cap; s++) if (st.players[s].steads.has(v) || st.players[s].keeps.has(v)) return false;
  return GEO.verts[v].adj.every((w) => { for (let s = 1; s <= st.cap; s++)
    if (st.players[s].steads.has(w) || st.players[s].keeps.has(w)) return false; return true; });
}
export function edgeFree(st, e) { for (let s = 1; s <= st.cap; s++) if (st.players[s].roads.has(e)) return false; return true; }
export function edgeTouchesOwn(st, s, e) {
  const { a, b } = GEO.edges[e], p = st.players[s];
  const viaV = (v) => p.steads.has(v) || p.keeps.has(v) ||
    GEO.verts[v].edges.some((e2) => e2 !== e && p.roads.has(e2) &&
      !(vOwnedByOther(st, s, v)));                          // roads don't continue through a foreign building
  return viaV(a) || viaV(b);
}
function vOwnedByOther(st, s, v) { for (let o = 1; o <= st.cap; o++) if (o !== s &&
  (st.players[o].steads.has(v) || st.players[o].keeps.has(v))) return true; return false; }
export function steadSpotOk(st, s, v) {
  return vertexFree(st, v) && GEO.verts[v].edges.some((e) => st.players[s].roads.has(e));
}
export function portsOf(st, s) {                            // {any: bool, res: [bool×5]}
  const out = { any: false, res: [false, false, false, false, false] };
  GEO.PORT_AT.forEach((e, i) => {
    const t = st.layout.ports[i], { a, b } = GEO.edges[e], p = st.players[s];
    if (p.steads.has(a) || p.keeps.has(a) || p.steads.has(b) || p.keeps.has(b)) {
      if (t < 0) out.any = true; else out.res[t] = true;
    }
  });
  return out;
}
export function bankRate(st, s, r) { const p = portsOf(st, s); return p.res[r] ? 2 : p.any ? 3 : 4; }

// ---- the replay ------------------------------------------------------------------------------------
// recs: [{enc, side (1..cap), q (BigInt seed or null if the pinned block isn't final yet)}]
// opts: {cap, secrets: {seat: BigInt|null}}  — pass every secret you legitimately know; at settle the
// verify pass runs with all revealed secrets and false claims flip `corrupt`.
export function replay(qkh, recs, opts) {
  const cap = opts.cap;
  const st = {
    cap, secrets: opts.secrets || {}, commits: opts.commits || [],
    layout: null, bank: [BANK_EACH, BANK_EACH, BANK_EACH, BANK_EACH, BANK_EACH],
    players: {}, robber: 0, phase: "setup", setupIdx: 0, turnSeat: 0, rolled: false, dice: 0,
    devBought: 0, offers: [], roadHolder: 0, watchHolder: 0, playedScroll: false,
    over: false, winner: 0, corrupt: 0, blocked: false, mi: 0, log: [], turnNo: 0, first: 1,
    pendingWin: 0,                                          // WIN claimed but unverifiable without secrets
    playsLog: [],                                           // public scroll-play claims (verified at reveal)
  };
  for (let s = 1; s <= cap; s++) st.players[s] = newPlayer();
  if (qkh == null) { st.blocked = true; return st; }
  st.layout = layout(qkh, cap); st.first = st.layout.first; st.robber = st.layout.waste;
  const slots = setupSlots(st);
  const bad = (why, side) => { st.corrupt = side || 1; st.why = why; };
  const L = (s, msg) => st.log.push({ s, msg, mi: st.mi });

  for (let i = 0; i < recs.length && !st.corrupt && !st.over; i++) {
    const { enc: e, side, q } = recs[i];
    if (q == null) { st.blocked = true; break; }
    const { op, a, b } = dec(e), p = st.players[side];
    st.mi = i + 1;

    if (st.phase === "setup") {
      if (op !== OP.SETUP) { bad("setup move expected", side); break; }
      const want = slots[st.setupIdx];
      if (side !== want) { bad("out of setup order", side); break; }
      if (a >= NVERT || b >= NEDGE || !vertexFree(st, a)) { bad("bad setup spot", side); break; }
      const ed = GEO.edges[b];
      if (!edgeFree(st, b) || (ed.a !== a && ed.b !== a)) { bad("setup road must touch the homestead", side); break; }
      p.steads.add(a); p.roads.add(b);
      if (st.setupIdx >= cap) {                             // second homestead pays out its tiles
        for (const h of GEO.verts[a].hexes) { const r = st.layout.tiles[h]; if (r >= 0) grant(st, side, r, 1); }
      }
      L(side, "setup " + a);
      st.setupIdx++;
      if (st.setupIdx === slots.length) { st.phase = "preroll"; st.turnSeat = st.first; st.turnNo = 1;
        for (let s = 1; s <= cap; s++) { st.players[s].buysBeforeTurn = 0; } }
      refreshBadges(st);
      continue;
    }

    const endOffers = () => { st.offers = []; };
    const startTurn = () => {
      st.phase = "preroll"; st.rolled = false; st.playedScroll = false; endOffers();
      const o = seatOrder(st), at = o.indexOf(st.turnSeat);
      st.turnSeat = o[(at + 1) % cap]; st.turnNo++;
      for (let s = 1; s <= cap; s++) { const pl = st.players[s];
        pl.buysBeforeTurn = pl.devDrawn; pl.buysThisTurn = 0; }
    };
    const playGate = (type) => {                            // one scroll/turn, never one bought this turn
      if (st.playedScroll) return "one scroll per turn";
      const known = st.secrets[side] != null;
      if (known) {
        const have = p.devKnown.slice(0, p.buysBeforeTurn).filter((t) => t === type).length;
        const played = st.playsLog.filter((x) => x.s === side && x.t === type).length;
        if (played >= have) return "scroll not held before this turn";
      } else {
        const playedAll = st.playsLog.filter((x) => x.s === side).length;
        if (playedAll >= p.buysBeforeTurn) return "more plays than pre-turn buys";
      }
      return null;
    };
    st.playsLog = st.playsLog || [];

    // ---- discard phase gates everything else --------------------------------------------------------
    if (st.phase === "discard") {
      if (op !== OP.DISCARD) { bad("discard owed first", side); break; }
      if (!p.owe) { bad("no discard owed", side); break; }
      const cnt = unpack5(b);
      if (total(cnt) !== p.owe || cnt.some((n, r) => n > p.res[r])) { bad("bad discard", side); break; }
      cnt.forEach((n, r) => { p.res[r] -= n; st.bank[r] += n; });
      p.owe = 0; L(side, "discards " + p.owe);
      if (!Object.values(st.players).some((pl) => pl.owe > 0)) st.phase = "robber";
      continue;
    }

    switch (op) {
      case OP.ROLL: {
        if (side !== st.turnSeat || st.phase !== "preroll") { bad("not your roll", side); break; }
        const d1 = derN(q, 1, 6) + 1, d2 = derN(q, 2, 6) + 1;
        st.dice = d1 + d2; st.rolled = true; L(side, "rolls " + st.dice);
        if (st.dice === 7) {
          let owing = false;
          for (let s = 1; s <= cap; s++) { const n = total(st.players[s].res);
            if (n > HAND_LIMIT) { st.players[s].owe = Math.floor(n / 2); owing = true; } }
          st.phase = owing ? "discard" : "robber";
        } else { production(st, st.dice); st.phase = "main"; }
        break;
      }
      case OP.ROBBER: {
        if (side !== st.turnSeat || st.phase !== "robber") { bad("not your marauder", side); break; }
        if (a >= NHEX || a === st.robber) { bad("marauder must move", side); break; }
        st.robber = a;
        const vics = adjacentSeats(st, a); vics.delete(side);
        const withCards = [...vics].filter((s) => total(st.players[s].res) > 0);
        if (b === 0) { if (withCards.length) { bad("must steal when possible", side); break; } }
        else { if (!withCards.includes(b)) { bad("bad steal target", side); break; }
               const got = stealFrom(st, side, b, q); L(side, "steals from " + b + (got >= 0 ? "" : " (empty)")); }
        st.phase = "main";
        break;
      }
      case OP.WARDEN: {                                     // playable in preroll OR main
        if (side !== st.turnSeat || (st.phase !== "preroll" && st.phase !== "main")) { bad("not your turn", side); break; }
        const g = playGate(WARDEN); if (g) { bad(g, side); break; }
        if (a >= NHEX || a === st.robber) { bad("marauder must move", side); break; }
        st.robber = a;
        const vics = adjacentSeats(st, a); vics.delete(side);
        const withCards = [...vics].filter((s) => total(st.players[s].res) > 0);
        if (b === 0) { if (withCards.length) { bad("must steal when possible", side); break; } }
        else { if (!withCards.includes(b)) { bad("bad steal target", side); break; }
               stealFrom(st, side, b, q); }
        p.plays[WARDEN]++; st.playedScroll = true; st.playsLog.push({ s: side, t: WARDEN });
        refreshBadges(st); L(side, "plays a Warden");
        break;
      }
      case OP.PATH: {
        if (side !== st.turnSeat || st.phase !== "main") { bad("not your turn", side); break; }
        const g = playGate(PATHWRIGHT); if (g) { bad(g, side); break; }
        const left = SUPPLY.road - p.roads.size, want = [a, b].filter((e2) => e2 < NEDGE);
        if (!want.length || want.length > Math.min(2, left)) { bad("bad pathwright", side); break; }
        for (const e2 of want) {
          if (!edgeFree(st, e2) || !edgeTouchesOwn(st, side, e2)) { bad("bad free road", side); break; }
          p.roads.add(e2);
        }
        if (st.corrupt) break;
        p.plays[PATHWRIGHT]++; st.playedScroll = true; st.playsLog.push({ s: side, t: PATHWRIGHT });
        refreshBadges(st); L(side, "plays a Pathwright");
        break;
      }
      case OP.BOUNTY: {
        if (side !== st.turnSeat || st.phase !== "main") { bad("not your turn", side); break; }
        const g = playGate(BOUNTY); if (g) { bad(g, side); break; }
        if (a > 4 || b > 4) { bad("bad bounty", side); break; }
        grant(st, side, a, 1); grant(st, side, b, 1);
        p.plays[BOUNTY]++; st.playedScroll = true; st.playsLog.push({ s: side, t: BOUNTY });
        L(side, "plays a Bounty");
        break;
      }
      case OP.LEVY: {
        if (side !== st.turnSeat || st.phase !== "main") { bad("not your turn", side); break; }
        const g = playGate(LEVY); if (g) { bad(g, side); break; }
        if (a > 4) { bad("bad levy", side); break; }
        for (let s = 1; s <= cap; s++) if (s !== side) {
          const n = st.players[s].res[a]; st.players[s].res[a] = 0; p.res[a] += n;
        }
        p.plays[LEVY]++; st.playedScroll = true; st.playsLog.push({ s: side, t: LEVY });
        L(side, "plays a Levy");
        break;
      }
      case OP.ROAD: {
        if (side !== st.turnSeat || st.phase !== "main") { bad("not your turn", side); break; }
        if (p.roads.size >= SUPPLY.road || a >= NEDGE || !edgeFree(st, a) ||
            !edgeTouchesOwn(st, side, a) || !canPayCost(p.res, COST.road)) { bad("bad road", side); break; }
        payCost(st, p, COST.road); p.roads.add(a); refreshBadges(st); L(side, "builds a road");
        break;
      }
      case OP.STEAD: {
        if (side !== st.turnSeat || st.phase !== "main") { bad("not your turn", side); break; }
        if (p.steads.size >= SUPPLY.stead || a >= NVERT || !steadSpotOk(st, side, a) ||
            !canPayCost(p.res, COST.stead)) { bad("bad homestead", side); break; }
        payCost(st, p, COST.stead); p.steads.add(a); refreshBadges(st); L(side, "builds a homestead");
        break;
      }
      case OP.KEEP: {
        if (side !== st.turnSeat || st.phase !== "main") { bad("not your turn", side); break; }
        if (p.keeps.size >= SUPPLY.keep || a >= NVERT || !p.steads.has(a) ||
            !canPayCost(p.res, COST.keep)) { bad("bad keep", side); break; }
        payCost(st, p, COST.keep); p.steads.delete(a); p.keeps.add(a); L(side, "raises a keep");
        break;
      }
      case OP.BUY: {
        if (side !== st.turnSeat || st.phase !== "main") { bad("not your turn", side); break; }
        // a seat that never committed a secret has no verifiable private stream — its buys are illegal
        // (honest clients always commit; this closes the "commitless = unverifiable forever" hole)
        if (!(st.commits && st.commits[side - 1])) { bad("scroll buy without a commit", side); break; }
        if (st.devBought >= DEV_CAP || !canPayCost(p.res, COST.scroll)) { bad("bad scroll buy", side); break; }
        payCost(st, p, COST.scroll);
        const card = drawDev(st, side, q, p.devDrawn);
        p.devDrawn++; p.buysThisTurn++; st.devBought++;
        if (card) p.devKnown.push(card);
        L(side, "buys a scroll");
        break;
      }
      case OP.BANK: {
        if (side !== st.turnSeat || st.phase !== "main") { bad("not your turn", side); break; }
        const give = Math.floor(a / 8), rate = a % 8, get = b;
        if (give > 4 || get > 4 || give === get || rate < 2 || rate > 4 || bankRate(st, side, give) > rate ||
            p.res[give] < rate || st.bank[get] < 1) { bad("bad bank trade", side); break; }
        p.res[give] -= rate; st.bank[give] += rate; grant(st, side, get, 1);
        L(side, "trades the bank " + rate + ":1");
        break;
      }
      case OP.OFFER: {                                      // anyone may offer during the mover's main
        if (st.phase !== "main") { bad("offers only in the main phase", side); break; }
        const give = unpack3(a), get = unpack3(b);
        if (!total(give) || !total(get) || give.some((n, r) => n && get[r])) { bad("bad offer", side); break; }
        if (give.some((n, r) => n > p.res[r])) { bad("offer exceeds hand", side); break; }
        st.offers.push({ by: side, give, get, at: i });
        L(side, "offers a trade");
        break;
      }
      case OP.ACCEPT: {
        const off = st.offers.find((o) => o.at === a);
        if (!off || st.phase !== "main") { bad("no such offer", side); break; }
        // every table trade involves the mover: mover's offers are open to all, others' only to the mover
        if (off.by === side || (off.by !== st.turnSeat && side !== st.turnSeat)) { bad("not your trade", side); break; }
        const from = st.players[off.by], to = p;
        if (off.give.some((n, r) => n > from.res[r]) || off.get.some((n, r) => n > to.res[r])) { bad("trade unaffordable", side); break; }
        off.give.forEach((n, r) => { from.res[r] -= n; to.res[r] += n; });
        off.get.forEach((n, r) => { to.res[r] -= n; from.res[r] += n; });
        st.offers = st.offers.filter((o) => o !== off);
        L(side, "trade with " + off.by);
        break;
      }
      case OP.RESCIND: {
        const off = st.offers.find((o) => o.at === a);
        if (!off || off.by !== side) { bad("not your offer", side); break; }
        st.offers = st.offers.filter((o) => o !== off);
        break;
      }
      case OP.END: {
        if (side !== st.turnSeat || st.phase !== "main") { bad("not your turn", side); break; }
        startTurn(); L(side, "ends the turn");
        break;
      }
      case OP.WIN: {
        if (side !== st.turnSeat || (st.phase !== "main" && st.phase !== "preroll")) { bad("win on your turn", side); break; }
        const v = totalVp(st, side);
        if (v == null) { st.pendingWin = side; st.over = true; st.winner = side; L(side, "calls the win (verify at reveal)"); }
        else if (v >= WIN_VP) { st.over = true; st.winner = side; L(side, "wins with " + v); }
        else { bad("win claim below " + WIN_VP, side); }
        break;
      }
      default: bad("unknown op " + op, side);
    }
  }
  refreshBadges(st);
  return st;
}

// which seats may act RIGHT NOW (drives canAct + the bot). Setup: the slotted seat; discard: owing
// seats; otherwise the mover — plus any seat that could accept/offer during main.
export function actorsNow(st) {
  if (st.over || st.corrupt || st.blocked) return [];
  if (st.phase === "setup") return [setupSlots(st)[st.setupIdx]];
  if (st.phase === "discard") return Object.keys(st.players).map(Number).filter((s) => st.players[s].owe > 0);
  if (st.phase === "main") {
    const out = [st.turnSeat];
    for (let s = 1; s <= st.cap; s++) if (s !== st.turnSeat) out.push(s);   // offers/accepts
    return out;
  }
  return [st.turnSeat];
}

// ---- legal-move generator (bot + E2E oracle; NOT the referee — replay() is) -------------------------
export function legalMoves(st, s) {
  const out = [], p = st.players[s];
  if (st.over || st.corrupt || st.blocked) return out;
  if (st.phase === "setup") {
    if (setupSlots(st)[st.setupIdx] !== s) return out;
    for (let v = 0; v < NVERT; v++) if (vertexFree(st, v))
      for (const e of GEO.verts[v].edges) if (edgeFree(st, e)) out.push(enc(OP.SETUP, v, e));
    return out;
  }
  if (st.phase === "discard") {
    if (!p.owe) return out;
    const cnt = [0, 0, 0, 0, 0]; let left = p.owe;         // one canonical greedy discard (largest first)
    const order = [...p.res.keys()].sort((x, y) => p.res[y] - p.res[x]);
    for (const r of order) { const k = Math.min(left, p.res[r]); cnt[r] += k; left -= k; if (!left) break; }
    out.push(enc(OP.DISCARD, 0, pack5(cnt)));
    return out;
  }
  if (st.phase === "robber") {
    if (s !== st.turnSeat) return out;
    for (let h = 0; h < NHEX; h++) if (h !== st.robber) {
      const vics = [...adjacentSeats(st, h)].filter((v) => v !== s && total(st.players[v].res) > 0);
      if (vics.length) vics.forEach((v) => out.push(enc(OP.ROBBER, h, v)));
      else out.push(enc(OP.ROBBER, h, 0));
    }
    return out;
  }
  if (st.phase === "preroll") {
    if (s !== st.turnSeat) return out;
    out.push(enc(OP.ROLL));
    return out;
  }
  if (st.phase !== "main") return out;
  if (s === st.turnSeat) {
    out.push(enc(OP.END));
    if (p.roads.size < SUPPLY.road && canPayCost(p.res, COST.road))
      for (let e = 0; e < NEDGE; e++) if (edgeFree(st, e) && edgeTouchesOwn(st, s, e)) out.push(enc(OP.ROAD, e));
    if (p.steads.size < SUPPLY.stead && canPayCost(p.res, COST.stead))
      for (let v = 0; v < NVERT; v++) if (steadSpotOk(st, s, v)) out.push(enc(OP.STEAD, v));
    if (p.keeps.size < SUPPLY.keep && canPayCost(p.res, COST.keep))
      for (const v of p.steads) out.push(enc(OP.KEEP, v));
    if (st.devBought < DEV_CAP && canPayCost(p.res, COST.scroll)) out.push(enc(OP.BUY));
    for (let g = 0; g < 5; g++) { const rate = bankRate(st, s, g);
      if (p.res[g] >= rate) for (let t = 0; t < 5; t++) if (t !== g && st.bank[t] > 0) out.push(enc(OP.BANK, g * 8 + rate, t)); }
    const v = totalVp(st, s); if (v != null && v >= WIN_VP) out.push(enc(OP.WIN));
  }
  for (const off of st.offers)
    if (off.by !== s && (off.by === st.turnSeat || s === st.turnSeat) &&
        !off.get.some((n, r) => n > p.res[r]) && !off.give.some((n, r) => n > st.players[off.by].res[r]))
      out.push(enc(OP.ACCEPT, off.at));
  return out;
}
