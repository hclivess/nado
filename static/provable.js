// provable.js — the PROVABLE PRACTICE RUNS SDK: on-chain leaderboards nobody can forge, for the free
// (off-chain) practice/solo modes. The model (proven live by Scrapline's daily gauntlet): a run is a PURE
// FUNCTION of (seed, move list); the on-chain post carries the score AND the packed move list; every
// browser REPLAYS the claim through the game's real engine and silently drops entries whose replay doesn't
// reproduce the claimed score. No trusted server, no signature games — the proof is reproducibility.
//
// Two attack classes this module closes ON TOP of plain replay-verification:
//   PRE-GRIND  — a date-string seed ("daily-2026-07-16") is computable YESTERDAY, giving cheaters extra
//                grinding time. Fix: the seed binds the FIRST FINALIZED L1 BLOCK of the UTC day (the
//                "day anchor") — unknowable before the day starts, immutable once finalized.
//   COPY-THEFT — claims are public on-chain, so a shared seed lets anyone repost the day's best move
//                list under their own address. Fix: the seed also binds the POSTER'S ADDRESS — every
//                player gets their own deterministic daily run; claims are non-transferable.
//
// SOUNDNESS LIMIT (design, not code): the seed is necessarily client-known at play time, so any game
// whose optimal play is TRIVIALLY COMPUTABLE from the RNG stream (dice, slots, mines, blackjack, …)
// would turn its board into a solver race. Provable boards belong on SEARCH-HARD games only
// (scrapline drafting, deck-builders, board games vs a deterministic bot). See doc/provable-practice.md.
import { blake2bHash } from "./nadotx.js";

// ---- the day anchor -------------------------------------------------------------------------------------
// anchor(day) = the hash of the FIRST finalized L1 block whose timestamp is >= day*86400 (UTC midnight).
// Found by binary search over finalized heights (block timestamps are monotone enough: consensus enforces
// ordering at the granularity that matters here — the first-crossing search is deterministic for every
// client given the same finalized chain). Cached in localStorage: a finalized anchor never changes.
const _anchorMem = {};
async function _blk(base, h) {
  try { const r = await fetch(base + "/get_block_number?number=" + h, { cache: "no-store" }); return await r.json(); }
  catch { return null; }
}
// _blkNear: the chain may have BODY HOLES (rolling pruning / re-anchor backfills) — walk outward from h
// to the nearest block the node actually serves. The bisection below adjusts on the FOUND height, so the
// search stays sound; the rule is "the lowest SERVED finalized block with ts >= t0", deterministic for
// every client of the same origin node (each game site's verifiers all query its own origin).
async function _blkNear(base, h, lo, hi) {
  const offs = [0];
  for (let d = 1; d <= 8; d++) offs.push(d, -d);
  for (let d = 16; d <= 4096; d *= 2) offs.push(d, -d);   // exponential jumps span wide pruned bands cheaply
  for (const o of offs) {
    const hh = h + o;
    if (hh < lo || hh > hi) continue;
    const b = await _blk(base, hh);
    if (b && b.block_timestamp != null && b.block_hash) return b;
  }
  return null;
}
export async function dayAnchor(base, day) {
  const key = "nado_day_anchor_" + day;
  if (_anchorMem[day]) return _anchorMem[day];
  try { const c = localStorage.getItem(key); if (c) { _anchorMem[day] = c; return c; } } catch {}
  const st = await (await fetch(base + "/status", { cache: "no-store" })).json().catch(() => null);
  const fin = (st && st.finalized_height) || 0;
  const t0 = day * 86400;
  let lo = 1, hi = fin, first = null;
  const top = await _blkNear(base, hi, 1, fin);
  if (!top || (top.block_timestamp || 0) < t0) return null;      // the day has no finalized block yet
  first = top;                                                    // worst case the day anchors at the tip probe
  for (let step = 0; step < 64 && lo <= hi; step++) {
    const b = await _blkNear(base, (lo + hi) >> 1, lo, hi);
    if (!b) break;
    const h = Number(b.block_number);
    if (b.block_timestamp >= t0) { first = b; hi = h - 1; } else lo = h + 1;
  }
  if (!first || !first.block_hash) return null;
  _anchorMem[day] = first.block_hash;
  try { localStorage.setItem(key, first.block_hash); } catch {}
  return first.block_hash;
}

// ---- the canonical per-player daily seed ----------------------------------------------------------------
// CONSENSUS for claims: every verifier derives the same string from on-chain data (day + anchor) plus the
// poster's address (from the entry itself). Do not restyle.
export const provableSeed = (slug, day, anchorHash, addr) =>
  "daily2-" + slug + "-" + day + "-" + String(anchorHash).slice(0, 16) + "-" + addr;

// ---- generic k-bit move codec ---------------------------------------------------------------------------
// Packs a move list into field words that survive the JSON view (each word < 2^50): floor(50/bits)
// symbols per word. Scrapline's 5-bit/10-per-word layout is the bits=5 case of this codec.
export const symsPerWord = (bits) => Math.floor(50 / bits);
export function packMoves(moves, bits) {
  const per = symsPerWord(bits), words = [];
  for (let w = 0; w * per < moves.length; w++) {
    let v = 0n;
    for (let i = Math.min(moves.length, (w + 1) * per) - 1; i >= w * per; i--)
      v = v * BigInt(1 << bits) + BigInt(moves[i] & ((1 << bits) - 1));
    words.push(Number(v));
  }
  return words;
}
export function unpackMoves(words, bits, n) {
  const per = symsPerWord(bits), out = [];
  for (let i = 0; i < n; i++) {
    const w = Math.floor(i / per);
    let v = BigInt(Math.round(words[w] || 0));
    for (let k = 0; k < i % per; k++) v /= BigInt(1 << bits);
    out.push(Number(v % BigInt(1 << bits)));
  }
  return out;
}

// ---- claim verification pipeline ------------------------------------------------------------------------
// verifyEntries(entries, replayFn): entries = [{e, day, addr, score, n, words}]; replayFn(seedArgs, moves)
// must return the TRUE score (or -1). Results cached per entry id — a claim's verdict never changes.
// Returns the verified best-per-address rows, sorted, ready for renderTopScores.
const _claimCache = new Map();
export async function verifyEntries(entries, replay) {
  const best = {};
  for (const en of entries) {
    if (!en.addr || !(en.score > 0)) continue;
    if (!_claimCache.has(en.e)) {
      let v = -1;
      try { v = await replay(en); } catch {}
      _claimCache.set(en.e, v);
    }
    if (_claimCache.get(en.e) !== en.score) continue;             // bogus/unverifiable — never renders
    if (!best[en.addr] || best[en.addr].score < en.score) best[en.addr] = { addr: en.addr, score: en.score };
  }
  return Object.values(best).sort((a, b) => b.score - a.score);
}

// ---- entry reader for the scrapline-style contract layout ----------------------------------------------
// Reads today's claim entries out of a contract view: maps eday/eaddr/escore/en + word maps (ea0..).
export function entriesFrom(sto, _m, day, wordMapNames) {
  const eday = _m(sto, "eday"), eaddr = _m(sto, "eaddr"), escore = _m(sto, "escore"), en = _m(sto, "en");
  const wm = wordMapNames.map((nm) => _m(sto, nm));
  const out = [];
  for (const e of Object.keys(eday)) {
    if (eday[e] !== day) continue;
    out.push({ e, day, addr: eaddr[e], score: escore[e] || 0, n: en[e] || 0, words: wm.map((m) => m[e] || 0) });
  }
  return out;
}

export const H = (v) => blake2bHash(v);
