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
// The anchor lives IN THE GAME'S CONTRACT (execnode/games/_lib.daily_anchor — maps ah/av + a "days"
// index): ah[day] pins a FUTURE L1 height (grind-proof — pinned before its hash exists for anyone),
// av[day] then stores that block's hash VALUE forever. Historical L1 blocks are NOT assumed fetchable
// (nodes bootstrap from snapshots and prune bodies — a chain bisection breaks the day it's needed most),
// so no verifier ever walks the chain: everyone reads the same number out of contract storage.
export const todayIdx = () => Math.floor(Date.now() / 86400000);
export function anchorOf(sto, _m, day) {
  const v = _m(sto, "av")[day];
  return v ? String(v) : null;
}
// ensureAnchor: permissionless upkeep of today's anchor — pin if the day has no pin, resolve once the
// pinned block exists (checked against /exec/blockhash so a premature call never burns a fee on a
// revert). Fire-and-forget value-free dapp calls (background signing); at most one call per (day, pin)
// per session so polls don't spam. Returns the anchor when ready, else null.
const _anchDrive = {};
export async function ensureAnchor(dapp, base, sto, _m, day) {
  const ready = anchorOf(sto, _m, day);
  if (ready) return ready;
  if (!dapp.me) return null;                                  // upkeep needs a signer; readers just wait
  const ah = _m(sto, "ah")[day] || 0;
  if (ah) {
    try {
      const r = await (await fetch(base + "/exec/blockhash?height=" + ah, { cache: "no-store" })).json();
      if (!r || !r.hashes || !r.hashes[ah]) return null;      // pinned block still in the future — wait
    } catch { return null; }
  }
  const k = day + ":" + ah;
  if (_anchDrive[k]) return null;
  _anchDrive[k] = 1;
  dapp.call("anchor", [day], null, "seed the day-" + day + " provable board", { phase: "agree" });
  return null;
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
