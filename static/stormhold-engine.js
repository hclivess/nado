// stormhold-engine.js — the full rules engine for NADO Stormhold, a deck-building strategy game in the
// classic Dominion-style genre (game MECHANICS are not copyrightable; all names, card titles and rules
// text here are original — no trademarked names, no copied text, no art). Deterministic and
// headless-testable (browser + node). The contract (execnode/games/stormhold.py) is only
// an escrow + ordered move log; THIS module is the referee: it replays the on-chain log into a complete
// game state, enforcing every rule. Randomness (every shuffle) comes from L1 block hashes pinned by the
// contract per move — HASH(bh(rh)+bh(rh+1)+salt+i), the shared cards.js chain-draw convention — so both
// players' browsers derive byte-identical kingdoms, decks and draws, and nobody (including the mover, who
// signed before the seed block existed) can rig a shuffle.
//
// Trust model = chess: an illegal move (wrong actor, bad payload) marks the game CORRUPT in every honest
// client; play stops and the contract's move-clock refund settles it. The wager itself settles by
// resign / mutual agree / refund-timeout.
//
// MOVE ENCODING (the on-chain `enc`, always > 0): enc = op + payload·16
//   op 1 PLAY    payload = hand index of an Action card
//   op 2 COINS   payload = bitmask of hand indices — play those Treasures (enters the buy phase)
//   op 3 BUY     payload = card id (enters the buy phase)
//   op 4 END     end of turn (clean-up, draw 5, pass)
//   op 5 DECIDE  payload answers the TOP pending decision frame (see FRAMES below)
// Ops 1-4 belong to the turn player with an empty frame stack; op 5 to the top frame's actor.
//
// FRAMES (pending decisions; payload semantics per type):
//   cel  Winnow     bitmask of hand cards to discard (draw as many)
//   chp  Purifier     bitmask (≤4 set bits) to trash
//   har  Undertow   0 = skip · 1+i = topdeck discard-pile card i
//   vas  Whirlwind     1 = play the revealed Action · 0 = discard it
//   mil  Raiders    (defender) bitmask with exactly hand-3 bits — discard those
//   bur  Collector  (defender) hand index of a Victory card to topdeck
//   ban  Storm Riders     (defender) 0/1 — which revealed treasure to trash
//   mon  Smelter     1 = trash a Copper for +3 coins · 0 = skip
//   poa  Drifter    bitmask with exactly n bits — discard those
//   remT/remG Reforge   trash hand index → gain card id (cost ≤ trashed+2)
//   thr  Echo           hand index of an Action to play twice · 4095 = skip
//   minT/minG Refinery    treasure hand index (4095 = skip) → gain treasure id ≤ cost+3, to hand
//   sen  Skywatch     d0 + 3·d1 + 9·swap — per revealed card 0 keep · 1 discard · 2 trash;
//                   swap flips the keep-order (default: first revealed goes back on top)
//   lib  Almanac    1 = set the revealed Action aside · 0 = keep it in hand
//   artG/artT Atelier   gain card id ≤5 to hand → topdeck a hand index
//   wsh  Foundry    gain card id ≤4
//   moat Windbreak  (defender) 1 = reveal (immune to the attack) · 0 = take the hit
//   tr2  (auto — Echo's second play; resolves itself, never needs input)
import { blake2bHash } from "./nadotx.js";

const H = (v) => BigInt("0x" + blake2bHash(v));

// ---- card table (Base 2E) --------------------------------------------------------------------------
export const A = 1, T = 2, V = 4, CU = 8, ATK = 16, RE = 32;   // type bits
export const CARDS = [
  { k: "copper", n: "Copper", c: 0, t: T, coin: 1 },
  { k: "silver", n: "Silver", c: 3, t: T, coin: 2 },
  { k: "gold", n: "Gold", c: 6, t: T, coin: 3 },
  { k: "homestead", n: "Homestead", c: 2, t: V, vp: 1 },
  { k: "valley", n: "Valley", c: 5, t: V, vp: 3 },
  { k: "citadel", n: "Citadel", c: 8, t: V, vp: 6 },
  { k: "blight", n: "Blight", c: 0, t: CU, vp: -1 },
  { k: "winnow", n: "Winnow", c: 2, t: A, txt: "+1 Action. Discard any number of cards, then draw that many." },
  { k: "purifier", n: "Purifier", c: 2, t: A, txt: "Trash up to 4 cards from your hand." },
  { k: "windbreak", n: "Windbreak", c: 2, t: A | RE, txt: "+2 Cards. Reveal to be unaffected by an Attack." },
  { k: "undertow", n: "Undertow", c: 3, t: A, txt: "+1 Card +1 Action. You may topdeck a card from your discard pile." },
  { k: "hawker", n: "Hawker", c: 3, t: A, txt: "+1 Card +1 Action. First Silver this turn gives +1 coin." },
  { k: "whirlwind", n: "Whirlwind", c: 3, t: A, txt: "+2 coins. Discard the top card of your deck; if it's an Action you may play it." },
  { k: "waystation", n: "Waystation", c: 3, t: A, txt: "+1 Card +2 Actions." },
  { k: "foundry", n: "Foundry", c: 3, t: A, txt: "Gain a card costing up to 4." },
  { k: "collector", n: "Collector", c: 4, t: A | ATK, txt: "Gain a Silver onto your deck. Opponent topdecks a Victory card (or reveals a hand without one)." },
  { k: "terraces", n: "Terraces", c: 4, t: V, txt: "Worth 1 VP per 10 cards you have." },
  { k: "raiders", n: "Raiders", c: 4, t: A | ATK, txt: "+2 coins. Opponent discards down to 3 cards." },
  { k: "smelter", n: "Smelter", c: 4, t: A, txt: "You may trash a Copper for +3 coins." },
  { k: "drifter", n: "Drifter", c: 4, t: A, txt: "+1 Card +1 Action +1 coin. Discard a card per empty supply pile." },
  { k: "reforge", n: "Reforge", c: 4, t: A, txt: "Trash a card; gain a card costing up to 2 more." },
  { k: "scribe", n: "Scribe", c: 4, t: A, txt: "+3 Cards." },
  { k: "echo", n: "Echo", c: 4, t: A, txt: "You may play an Action from your hand twice." },
  { k: "stormriders", n: "Storm Riders", c: 5, t: A | ATK, txt: "Gain a Gold. Opponent reveals top 2 cards, trashes a revealed non-Copper Treasure, discards the rest." },
  { k: "assembly", n: "Assembly", c: 5, t: A, txt: "+4 Cards +1 Buy. Opponent draws a card." },
  { k: "jubilee", n: "Jubilee", c: 5, t: A, txt: "+2 Actions +1 Buy +2 coins." },
  { k: "observatory", n: "Observatory", c: 5, t: A, txt: "+2 Cards +1 Action." },
  { k: "almanac", n: "Almanac", c: 5, t: A, txt: "Draw until 7 cards in hand; you may set aside Actions drawn (discarded after)." },
  { k: "nightmarket", n: "Night Market", c: 5, t: A, txt: "+1 Card +1 Action +1 Buy +1 coin." },
  { k: "refinery", n: "Refinery", c: 5, t: A, txt: "You may trash a Treasure; gain a Treasure costing up to 3 more, to your hand." },
  { k: "skywatch", n: "Skywatch", c: 5, t: A, txt: "+1 Card +1 Action. Look at your top 2 cards; trash/discard/keep them in any order." },
  { k: "stormcaller", n: "Stormcaller", c: 5, t: A | ATK, txt: "+2 Cards. Opponent gains a Blight." },
  { k: "atelier", n: "Atelier", c: 6, t: A, txt: "Gain a card costing up to 5 to your hand; put a card from your hand onto your deck." },
];
export const COPPER = 0, SILVER = 1, GOLD = 2, HOMESTEAD = 3, VALLEY = 4, CITADEL = 5, BLIGHT = 6;
export const WINDBREAK = 9, TERRACES = 16;
const KINGDOM = Array.from({ length: 26 }, (_, i) => 7 + i);
const SKIP = 4095;   // "may" sentinel for index-pick frames (Echo / Refinery)

export const encMove = (op, payload) => op + (payload || 0) * 16;
export const decMove = (enc) => ({ op: enc % 16, payload: Math.floor(enc / 16) });
const isA = (id) => !!(CARDS[id].t & A), isT = (id) => !!(CARDS[id].t & T), isV = (id) => !!(CARDS[id].t & V);
const bits = (mask) => { const r = []; for (let i = 0; mask; i++, mask = Math.floor(mask / 2)) if (mask % 2) r.push(i); return r; };

// ---- state -------------------------------------------------------------------------------------------
function blockedErr() { const e = new Error("waiting for seed block"); e.blocked = true; return e; }

function shuffled(st, arr) {
  if (st._q == null) throw blockedErr();
  st.shufN++;
  const salt = BigInt(st.g) * 16777216n + BigInt(st.shufN) * 4096n;
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Number(H(st._q + salt + BigInt(i)) % BigInt(i + 1));
    const t_ = a[i]; a[i] = a[j]; a[j] = t_;
  }
  return a;
}
function log(st, p, ev, c, n) { st.log.push({ p, ev, c, n, mi: st.mi }); if (st.log.length > 400) st.log.shift(); }
function corrupt(st, why) { st.corrupt = true; st.corruptWhy = why; }

// takeTop: reveal/take the top card of p's deck (shuffling the discard in if needed); null if none anywhere.
function takeTop(st, p) {
  const z = st.ps[p];
  if (!z.deck.length) {
    if (!z.disc.length) return null;
    z.deck = shuffled(st, z.disc); z.disc = []; log(st, p, "shuffle");
  }
  return z.deck.pop();
}
function draw(st, p, n) {
  let got = 0;
  for (let i = 0; i < n; i++) { const c = takeTop(st, p); if (c == null) break; st.ps[p].hand.push(c); got++; }
  if (got) log(st, p, "draw", null, got);
  return got;
}
// gain from the supply (skip silently if the pile is out — the rule for automatic gains); where: zone array
function gain(st, p, id, where, ev) {
  if ((st.supply[id] || 0) <= 0) return false;
  st.supply[id]--; where.push(id); log(st, p, ev || "gain", id);
  return true;
}
const piles = (st) => [COPPER, SILVER, GOLD, HOMESTEAD, VALLEY, CITADEL, BLIGHT].concat(st.kingdom);
const emptyPiles = (st) => piles(st).filter((id) => st.supply[id] === 0).length;
// gainable(st, max, treasureOnly): the supply ids a "gain a card costing up to max" frame may pick.
export const gainable = (st, max, treasureOnly) =>
  piles(st).filter((id) => st.supply[id] > 0 && CARDS[id].c <= max && (!treasureOnly || isT(id)));

// mask: optional 26-bit kingdom selection (bit b = kingdom card id 7+b), chosen by the game creator at
// open time and stored on-chain (cfg word). 0/absent = the classic kh-seeded random kingdom. An invalid
// mask (not exactly 10 kingdom bits) marks the game corrupt — the client refuses it before anyone joins.
export const maskToKingdom = (mask) => {
  const m = BigInt(mask || 0), pick = [];
  for (let b = 0n; b < 26n; b++) if ((m >> b) & 1n) pick.push(7 + Number(b));
  return m > 0n && m < (1n << 26n) && pick.length === 10 ? pick : null;
};
export const kingdomToMask = (ids) => ids.reduce((m, id) => m + Math.pow(2, id - 7), 0);

export function init(g, khQ, mask) {
  const st = {
    g: Number(g), kingdom: [], supply: {}, trash: [],
    ps: [{ deck: [], hand: [], disc: [], play: [], turns: 0 }, { deck: [], hand: [], disc: [], play: [], turns: 0 }],
    turn: 0, phase: 0, actions: 1, buys: 1, coins: 0, merch: 0, silverDone: false,
    frames: [], over: false, result: 0, corrupt: false, corruptWhy: "",
    shufN: 0, mi: 0, blocked: false, blockedAt: -1, log: [],
  };
  st._q = khQ;
  let pick;
  if (mask && Number(mask) !== 0) {
    pick = maskToKingdom(mask);
    if (!pick) { st.corrupt = true; st.corruptWhy = "invalid kingdom mask"; st.setup = false; return st; }
  } else {
    pick = shuffled(st, KINGDOM).slice(0, 10);
  }
  pick.sort((a, b) => (CARDS[a].c - CARDS[b].c) || (a - b));
  st.kingdom = pick;
  st.supply = { [COPPER]: 46, [SILVER]: 40, [GOLD]: 30, [HOMESTEAD]: 8, [VALLEY]: 8, [CITADEL]: 8, [BLIGHT]: 10 };
  for (const id of pick) st.supply[id] = isV(id) ? 8 : 10;
  for (let p = 0; p < 2; p++) {
    const cards = [COPPER, COPPER, COPPER, COPPER, COPPER, COPPER, COPPER, HOMESTEAD, HOMESTEAD, HOMESTEAD];
    st.ps[p].deck = shuffled(st, cards);
    draw(st, p, 5);
  }
  st.log = [];   // opening shuffles/draws aren't interesting
  return st;
}

// ---- attacks -------------------------------------------------------------------------------------------
// The defender first gets a Windbreak decision if they hold one; otherwise (or on decline) the effect applies.
function attack(st, p, id) {
  const d = 1 - p;
  if (st.ps[d].hand.includes(WINDBREAK)) st.frames.push({ t: "moat", p: d, atk: id });
  else applyAttack(st, id, d);
}
function applyAttack(st, id, d) {
  const z = st.ps[d];
  if (id === 17) {                                          // Raiders
    if (z.hand.length > 3) st.frames.push({ t: "mil", p: d });
  } else if (id === 31) {                                   // Stormcaller
    gain(st, d, BLIGHT, z.disc, "curse");
  } else if (id === 15) {                                   // Collector
    const vs = z.hand.filter(isV);
    if (!vs.length) log(st, d, "reveal");                   // reveals a hand with no Victory cards
    else if (new Set(vs).size === 1) {                      // only one kind — no real choice
      const i = z.hand.findIndex(isV); z.deck.push(z.hand.splice(i, 1)[0]); log(st, d, "topdeck", vs[0]);
    } else st.frames.push({ t: "bur", p: d });
  } else if (id === 23) {                                   // Storm Riders
    const rev = [];
    for (let i = 0; i < 2; i++) { const c = takeTop(st, d); if (c != null) rev.push(c); }
    log(st, d, "reveal2", null, rev.length); for (const c of rev) log(st, d, "revealc", c);
    const elig = rev.filter((c) => isT(c) && c !== COPPER);
    if (elig.length === 2 && rev[0] !== rev[1]) st.frames.push({ t: "ban", p: d, cards: rev });
    else {
      if (elig.length) { const c = elig[0]; rev.splice(rev.indexOf(c), 1); st.trash.push(c); log(st, d, "trash", c); }
      for (const c of rev) z.disc.push(c);
    }
  }
}

// ---- card effects --------------------------------------------------------------------------------------
function libraryLoop(st, p, aside) {
  const z = st.ps[p];
  while (z.hand.length < 7) {
    const c = takeTop(st, p);
    if (c == null) break;
    if (isA(c)) { st.frames.push({ t: "lib", p, card: c, aside }); return; }
    z.hand.push(c);
  }
  if (aside.length) { for (const c of aside) z.disc.push(c); log(st, p, "discard", null, aside.length); }
}
function resolveCard(st, p, id) {
  const z = st.ps[p];
  switch (id) {
    case 7: st.actions++; st.frames.push({ t: "cel", p }); break;
    case 8: st.frames.push({ t: "chp", p }); break;
    case WINDBREAK: draw(st, p, 2); break;
    case 10: draw(st, p, 1); st.actions++; if (z.disc.length) st.frames.push({ t: "har", p }); break;
    case 11: draw(st, p, 1); st.actions++; st.merch++; break;
    case 12: { st.coins += 2; const c = takeTop(st, p);
      if (c == null) break;
      if (isA(c)) st.frames.push({ t: "vas", p, card: c });
      else { z.disc.push(c); log(st, p, "discard1", c); } break; }
    case 13: draw(st, p, 1); st.actions += 2; break;
    case 14: st.frames.push({ t: "wsh", p }); break;
    case 15: { const got = gain(st, p, SILVER, z.deck, "gaindeck"); if (!got) log(st, p, "supplyout", SILVER); attack(st, p, id); break; }
    case 17: st.coins += 2; attack(st, p, id); break;
    case 18: if (z.hand.includes(COPPER)) st.frames.push({ t: "mon", p }); break;
    case 19: { draw(st, p, 1); st.actions++; st.coins++;
      const n = Math.min(emptyPiles(st), z.hand.length);
      if (n > 0) st.frames.push({ t: "poa", p, n }); break; }
    case 20: if (z.hand.length) st.frames.push({ t: "remT", p }); break;
    case 21: draw(st, p, 3); break;
    case 22: if (z.hand.some(isA)) st.frames.push({ t: "thr", p }); break;
    case 23: gain(st, p, GOLD, z.disc); attack(st, p, id); break;
    case 24: draw(st, p, 4); st.buys++; draw(st, 1 - p, 1); break;
    case 25: st.actions += 2; st.buys++; st.coins += 2; break;
    case 26: draw(st, p, 2); st.actions++; break;
    case 27: libraryLoop(st, p, []); break;
    case 28: draw(st, p, 1); st.actions++; st.buys++; st.coins++; break;
    case 29: if (z.hand.some(isT)) st.frames.push({ t: "minT", p }); break;
    case 30: { draw(st, p, 1); st.actions++;
      const cards = [];
      for (let i = 0; i < 2; i++) { const c = takeTop(st, p); if (c != null) cards.push(c); }
      if (cards.length) st.frames.push({ t: "sen", p, cards }); break; }
    case 31: draw(st, p, 2); attack(st, p, id); break;
    case 32: st.frames.push({ t: "artG", p }); break;
    default: corrupt(st, "unknown action " + id);
  }
}

// Echo's second play fires automatically once the first play's decisions drain off the stack.
function drainAuto(st) {
  while (!st.corrupt && st.frames.length && st.frames[st.frames.length - 1].t === "tr2") {
    const f = st.frames.pop();
    log(st, f.p, "play2", f.card);
    resolveCard(st, f.p, f.card);
  }
}

// ---- frame resolution ----------------------------------------------------------------------------------
function discardMask(st, p, mask, exactN) {
  const z = st.ps[p], idxs = bits(mask);
  if (idxs.some((i) => i >= z.hand.length)) return -1;
  if (exactN != null && idxs.length !== exactN) return -1;
  for (const i of idxs.slice().reverse()) z.disc.push(z.hand.splice(i, 1)[0]);
  if (idxs.length) log(st, p, "discard", null, idxs.length);
  return idxs.length;
}
function resolveFrame(st, payload) {
  const f = st.frames.pop(), p = f.p, z = st.ps[p];
  switch (f.t) {
    case "cel": { const n = discardMask(st, p, payload); if (n < 0) return corrupt(st, "cellar mask"); draw(st, p, n); break; }
    case "chp": { const idxs = bits(payload);
      if (idxs.length > 4 || idxs.some((i) => i >= z.hand.length)) return corrupt(st, "chapel mask");
      for (const i of idxs.slice().reverse()) { const c = z.hand.splice(i, 1)[0]; st.trash.push(c); log(st, p, "trash", c); } break; }
    case "har": { if (payload === 0) break;
      const i = payload - 1; if (i >= z.disc.length) return corrupt(st, "harbinger idx");
      const c = z.disc.splice(i, 1)[0]; z.deck.push(c); log(st, p, "topdeck", c); break; }
    case "vas": { if (payload === 1) { z.play.push(f.card); log(st, p, "play2", f.card); resolveCard(st, p, f.card); }
      else { z.disc.push(f.card); log(st, p, "discard1", f.card); } break; }
    case "mil": { if (discardMask(st, p, payload, z.hand.length - 3) < 0) return corrupt(st, "militia mask"); break; }
    case "bur": { if (payload >= z.hand.length || !isV(z.hand[payload])) return corrupt(st, "bureaucrat idx");
      const c = z.hand.splice(payload, 1)[0]; z.deck.push(c); log(st, p, "topdeck", c); break; }
    case "ban": { if (payload > 1 || payload >= f.cards.length) return corrupt(st, "bandit pick");
      const c = f.cards[payload];
      if (!(isT(c) && c !== COPPER)) return corrupt(st, "bandit pick not eligible");
      st.trash.push(c); log(st, p, "trash", c);
      z.disc.push(f.cards[1 - payload]); break; }
    case "mon": { if (payload === 1) { const i = z.hand.indexOf(COPPER); if (i < 0) return corrupt(st, "no copper");
      st.trash.push(z.hand.splice(i, 1)[0]); log(st, p, "trash", COPPER); st.coins += 3; } break; }
    case "poa": { if (discardMask(st, p, payload, f.n) < 0) return corrupt(st, "poacher mask"); break; }
    case "remT": { if (payload >= z.hand.length) return corrupt(st, "remodel idx");
      const c = z.hand.splice(payload, 1)[0]; st.trash.push(c); log(st, p, "trash", c);
      st.frames.push({ t: "remG", p, max: CARDS[c].c + 2 }); break; }
    case "remG": { if (payload === SKIP) { if (gainable(st, f.max).length) return corrupt(st, "remodel must gain"); break; }
      if (!CARDS[payload] || CARDS[payload].c > f.max || !(st.supply[payload] > 0)) return corrupt(st, "remodel gain");
      gain(st, p, payload, z.disc); break; }
    case "thr": { if (payload === SKIP) break;
      if (payload >= z.hand.length || !isA(z.hand[payload])) return corrupt(st, "throne idx");
      const c = z.hand.splice(payload, 1)[0]; z.play.push(c); log(st, p, "play", c);
      st.frames.push({ t: "tr2", p, card: c });
      resolveCard(st, p, c); break; }
    case "minT": { if (payload === SKIP) break;
      if (payload >= z.hand.length || !isT(z.hand[payload])) return corrupt(st, "mine trash");
      const c = z.hand.splice(payload, 1)[0]; st.trash.push(c); log(st, p, "trash", c);
      st.frames.push({ t: "minG", p, max: CARDS[c].c + 3 }); break; }
    case "minG": { if (payload === SKIP) { if (gainable(st, f.max, true).length) return corrupt(st, "mine must gain"); break; }
      if (!CARDS[payload] || !isT(payload) || CARDS[payload].c > f.max || !(st.supply[payload] > 0)) return corrupt(st, "mine gain");
      gain(st, p, payload, z.hand); break; }
    case "sen": { const d0 = payload % 3, d1 = Math.floor(payload / 3) % 3, swap = Math.floor(payload / 9) % 2;
      if (payload >= 18) return corrupt(st, "sentry payload");
      const ds = [d0, d1].slice(0, f.cards.length);
      if (f.cards.length === 1 && (d1 || swap)) return corrupt(st, "sentry payload");
      const kept = [];
      for (let i = 0; i < f.cards.length; i++) { const c = f.cards[i];
        if (ds[i] === 2) { st.trash.push(c); log(st, p, "trash", c); }
        else if (ds[i] === 1) { z.disc.push(c); log(st, p, "discard1", c); }
        else kept.push(c);
      }
      if (kept.length === 2 && swap) kept.reverse();
      for (let i = kept.length - 1; i >= 0; i--) z.deck.push(kept[i]);   // kept[0] ends on top
      break; }
    case "lib": { if (payload === 1) f.aside.push(f.card); else z.hand.push(f.card);
      libraryLoop(st, p, f.aside); break; }
    case "artG": { if (payload === SKIP) { if (gainable(st, 5).length) return corrupt(st, "artisan must gain");
        if (z.hand.length) st.frames.push({ t: "artT", p }); break; }
      if (!CARDS[payload] || CARDS[payload].c > 5 || !(st.supply[payload] > 0)) return corrupt(st, "artisan gain");
      gain(st, p, payload, z.hand);
      st.frames.push({ t: "artT", p }); break; }
    case "artT": { if (payload >= z.hand.length) return corrupt(st, "artisan topdeck");
      const c = z.hand.splice(payload, 1)[0]; z.deck.push(c); log(st, p, "topdeck", c); break; }
    case "wsh": { if (payload === SKIP) { if (gainable(st, 4).length) return corrupt(st, "workshop must gain"); break; }
      if (!CARDS[payload] || CARDS[payload].c > 4 || !(st.supply[payload] > 0)) return corrupt(st, "workshop gain");
      gain(st, p, payload, z.disc); break; }
    case "moat": { if (payload === 1) log(st, p, "immune", WINDBREAK);
      else applyAttack(st, f.atk, p); break; }
    default: corrupt(st, "unknown frame " + f.t);
  }
}

// ---- turn-level ops ------------------------------------------------------------------------------------
export const legalActor = (st) => (st.frames.length ? st.frames[st.frames.length - 1].p : st.turn);

export function applyMove(st, side, enc) {
  if (st.corrupt) return;
  if (st.over) return corrupt(st, "move after game over");
  const p = side - 1, { op, payload } = decMove(enc);
  if (p !== legalActor(st)) return corrupt(st, "wrong actor");
  if (st.frames.length) {
    if (op !== 5) return corrupt(st, "decision pending");
    resolveFrame(st, payload);
  } else {
    const z = st.ps[p];
    if (op === 1) {                                        // PLAY an action
      if (st.phase !== 0) return corrupt(st, "not action phase");
      if (st.actions < 1) return corrupt(st, "no actions left");
      if (payload >= z.hand.length || !isA(z.hand[payload])) return corrupt(st, "play idx");
      const c = z.hand.splice(payload, 1)[0]; z.play.push(c);
      st.actions--; log(st, p, "play", c);
      resolveCard(st, p, c);
    } else if (op === 2) {                                 // COINS — play treasures
      const idxs = bits(payload);
      if (!idxs.length || idxs.some((i) => i >= z.hand.length || !isT(z.hand[i]))) return corrupt(st, "coins mask");
      st.phase = 1;
      let silver = false;
      for (const i of idxs.slice().reverse()) { const c = z.hand.splice(i, 1)[0]; z.play.push(c);
        st.coins += CARDS[c].coin; if (c === SILVER) silver = true; log(st, p, "playT", c); }
      if (silver && !st.silverDone) { st.coins += st.merch; st.silverDone = true; if (st.merch) log(st, p, "merchant", SILVER, st.merch); }
    } else if (op === 3) {                                 // BUY
      const id = payload;
      if (!CARDS[id]) return corrupt(st, "buy id");
      st.phase = 1;
      if (st.buys < 1) return corrupt(st, "no buys");
      if (!(st.supply[id] > 0)) return corrupt(st, "pile empty");
      if (st.coins < CARDS[id].c) return corrupt(st, "can't afford");
      st.coins -= CARDS[id].c; st.buys--;
      gain(st, p, id, z.disc, "buy");
    } else if (op === 4) {                                 // END turn (clean-up)
      for (const c of z.hand) z.disc.push(c);
      for (const c of z.play) z.disc.push(c);
      z.hand = []; z.play = []; z.turns++;
      log(st, p, "endturn", null, z.turns);
      if (st.supply[CITADEL] === 0 || emptyPiles(st) >= 3) {
        st.over = true; st.result = computeResult(st); log(st, p, "gameover", null, st.result);
      } else {
        draw(st, p, 5);
        st.turn = 1 - p; st.phase = 0; st.actions = 1; st.buys = 1; st.coins = 0; st.merch = 0; st.silverDone = false;
      }
    } else return corrupt(st, "bad op " + op);
  }
  drainAuto(st);
}

// ---- scoring -------------------------------------------------------------------------------------------
export function allCards(st, p) { const z = st.ps[p]; return z.deck.concat(z.hand, z.disc, z.play); }
export function scoreOf(st, p) {
  const cards = allCards(st, p);
  let vp = 0;
  for (const c of cards) { if (CARDS[c].vp) vp += CARDS[c].vp; if (c === TERRACES) vp += Math.floor(cards.length / 10); }
  return vp;
}
export function computeResult(st) {   // 1 = p1 wins, 2 = p2 wins, 3 = draw (fewer-turns tie-break)
  const s0 = scoreOf(st, 0), s1 = scoreOf(st, 1);
  if (s0 !== s1) return s0 > s1 ? 1 : 2;
  if (st.ps[0].turns !== st.ps[1].turns) return st.ps[0].turns < st.ps[1].turns ? 1 : 2;
  return 3;
}

// ---- replay --------------------------------------------------------------------------------------------
// recs = [{enc, side, q}] where q = BigInt(bh(rh)) + BigInt(bh(rh+1)) or null while the seed block is
// pending. khQ likewise for the kingdom/setup seed. Replays as far as the available randomness allows;
// state.blocked/blockedAt mark where it stopped (the UI shows "shuffling…" and retries next poll).
export function replay(g, khQ, recs, mask) {
  let st;
  try { st = init(g, khQ, mask); } catch (e) { if (e.blocked) return { blocked: true, blockedAt: -1, setup: true }; throw e; }
  if (st.corrupt) return st;
  for (let i = 0; i < recs.length; i++) {
    const snap = structuredClone(st);
    st._q = recs[i].q;
    try { applyMove(st, recs[i].side, recs[i].enc); st.mi = i + 1; }
    catch (e) {
      if (!e.blocked) throw e;
      st = snap; st.blocked = true; st.blockedAt = i;
      break;
    }
    if (st.corrupt) break;
  }
  delete st._q;
  return st;
}
