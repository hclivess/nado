# Provable practice runs — leaderboards nobody can forge

Status: **LIVE for Scrapline** (hardened 2026-07-16); this doc is the standard for rolling boards out
to other practice modes. SDK: `static/provable.js`.

## 1. The model

Practice/solo modes run entirely in the browser — localStorage scores are one devtools call away from
any number. So an on-chain leaderboard entry is not a score, it is a **claim**: the score PLUS the
packed, deterministic move list that produced it. The contract stores claims blindly (a tx fee caps
spam); **every browser replays every claim through the game's real engine** and silently drops entries
whose replay doesn't reproduce the claimed score. There is no trusted scorer anywhere — the proof is
reproducibility. (Proven live by Scrapline's daily gauntlet board.)

## 2. The two holes plain replay-verification leaves open — and the hardened seed

```
seed = provableSeed(slug, day, dayAnchor(day), posterAddress)
     = "daily2-<slug>-<day>-<first16 of anchor hash>-<addr>"
```

- **Pre-grind.** A date-string seed (`daily-2026-07-16`) is computable YESTERDAY — a cheater grinds
  tomorrow's run all night. The **day anchor** — the hash of the *first finalized L1 block with
  timestamp ≥ UTC midnight* (deterministic binary search over finalized heights, cached; finalized ⇒
  immutable) — makes the seed unknowable before the day begins. "The chain is heavily used" is the
  whole trick: block hashes are a free, verifiable, unpredictable daily beacon.
- **Copy-theft.** Claims are public on-chain; with a shared seed anyone can repost the day's best
  move list under their own address. Binding the **poster's address** into the seed gives every
  player their own daily run — a copied move list replays into a *different* game for the thief and
  verifies to a different (almost surely worthless) score. Verifiers use the address stored in the
  entry itself, so no extra data rides the claim.

Consequences accepted: players race *scores*, not the identical run (per-run luck variance averages
out at arcade stakes); signed-out players get an `anon`-bound run they can play but never post (the
daily button says so up front). If identical-run racing is ever wanted back, the sound construction
is commit-reveal (commit `H(addr‖moves)` during the day, reveal after midnight) — costs a second tx
and next-day boards; not built.

## 3. The soundness limit: clairvoyance

To replay offline, the seed must be **client-known at play time** — so a player always *can* know
the entire RNG stream before acting. Whether that breaks the board depends on the game:

| game class | seed-known ⇒ | board verdict |
|---|---|---|
| pure luck (dice, slots, roulette, coinflip) | outcome list known ⇒ bet only winners | **never** board these |
| luck + trivial policy (blackjack, mines, farkle, battleship-vs-seed) | perfect play computable in ms | **never** |
| search-hard (scrapline drafting, stormhold-vs-bot, chess/reversi-vs-bot) | "solving" ≈ playing; optimum out of practical reach | boards are sound — they measure search skill, human or scripted |

Note the honest framing of the last row: a deterministic seeded run is a **puzzle**, and a provable
board is a *puzzle race*. Scripted assistance cannot be prevented (it never can be, in any online
leaderboard); what the proof guarantees is that every posted score was **actually achieved** under
the game's rules on that player's own run. That is the whole anti-cheat promise — and it holds.

## 4. What exists (the SDK) and how to add a board to a game

`static/provable.js`:
- `dayAnchor(base, day)` — the finalized-block day beacon (cached; null until the day's first block).
- `provableSeed(slug, day, anchor, addr)` — the consensus seed string. Do not restyle per game.
- `packMoves/unpackMoves(moves, bits)` — generic k-bit codec, `floor(50/bits)` symbols per word
  (words stay < 2^50: safe through the JSON view's number decoding). Scrapline's 5-bit layout is
  `bits=5`.
- `verifyEntries(entries, replayFn)` — cached claim verification → best-per-address sorted rows.
- `entriesFrom(sto, _m, day, wordMapNames)` — reader for the scrapline-style entry layout.

Per-game recipe:
1. Make the practice run a **pure function** `replay(seed, moves) → score` in the game's engine
   (scrapline: `verifyClaim`). Every source of randomness must come from the seed; every player
   decision must be encodable as a small integer.
2. Pick the move width. Budget: the contract post carries N words × ≤50 bits. Scrapline: 5 bits ×
   80 moves in 8 words. A chess-vs-bot board fits ~30 own-moves × 12 bits in 8 words (bot moves are
   derivable — never post them). Games whose runs exceed ~1000 bits (stormhold: hundreds of moves ×
   ~20 bits) need the claim in a DA blob with only its commitment in the post — future work.
3. Contract: reuse the scrapline `post(day, score, n, a0..)` shape (or the planned shared scores
   contract with a `gameKey`). The contract only bounds day-vs-chain-time (±1) and sizes; RULES stay
   client-verified.
4. Client: gate posting on `seed === provableSeed(slug, day, anchor, dapp.me)`; render the board
   through `entriesFrom` + `verifyEntries` + `renderTopScores`.
5. Tests: the scrapline suite's claim block is the template — honest roundtrip, inflated/wrong-day/
   truncated/garbage rejection, **copy-theft** (same words, different address must not verify) and
   **pre-grind** (different anchor must not verify).

## 5. Rollout status / candidates

- **Scrapline** — live, hardened (this doc's reference).
- **Chess practice** (mate the deterministic bot in fewest plies) — sound, fits the arg budget;
  next candidate.
- **Reversi practice** (max disc differential vs bot) — sound, 6-bit moves; candidate.
- **Stormhold practice** (win in fewest turns) — sound but needs DA-blob claims (move logs too fat
  for post args).
- **Everything luck-based** — no board, ever (see §3). Their practice modes keep local-only chips.
