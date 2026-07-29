# The Age of Gore — design recommendation

**Status: DESIGN. Nothing built.** Slug `gore`. This is the recommendation after three designs and three
independent judgements; it names which one to build, what it steals from the other two, and what it gives up.

---

## 1. The one to build, and what it costs

**Build the real-time gauntlet: 12 units, ~90 seconds, your hands on the units at 20 Hz, replayed by
everyone from a chain-minted seed.** The other two designs (WEGO pulses, blind simultaneous beats) are both
better *contracts* and neither is the game that was asked for. The brief says "micro intensive"; a design
whose atom is 3 seconds of world time bought with 30 seconds of chain time is a turn-based game with a
physics cutscene, however good the physics is. Only one of the three keeps a human hand on a unit while a
satchel is in the air.

The price, stated plainly and up front:

1. **No live PvP. Ever, on this substrate.** I grepped: there is no `WebSocket`, no `RTCPeerConnection`, no
   `EventSource` anywhere under `static/`. The only off-chain relay is `ops/message_pool.py`, which demands a
   *registered* sender with a valid ML-DSA signature (`_msg_is_registered`, `_msg_verify_sig` at
   `nado.py:1569`/`1579`), 12-bit hashcash per envelope (`MSG_POW_BITS = 12`), and delivery by polling `/tags`
   at 120/min. An in-page ephemeral key is not registered and is rejected. And the wallet signs through a
   hidden iframe, strictly one-in-flight with a 9s timeout (`nadodapp.js:1039`, `svc.cur`), so the page cannot
   sign input frames even if a transport existed.
2. **Off-chain signed orders are not bearer instruments, so no state channel can close unilaterally.** The
   op list is closed (`execnode/zkvm.py:58-62`) and contains no signature-verify opcode. An opponent's signed
   off-chain message is *inadmissible* to the VM. This is the strongest negative result the three designs
   produced (from the BEAT design) and it kills the whole "play fast off-chain, settle on-chain" family
   outright, not just slowly.
3. **AoE's macro layer is cut entirely in v1.** No economy, no production, no base. Myth had none either, and
   that is exactly why its micro reads.
4. **You react to a scenario, not to a person.** Adaptation and bluffing are recovered partially (ghosts, a
   shared field, an async duel) and never fully.
5. **No stake in v1.** See §6 — with no on-chain adjudicator, a symmetric duel always leaves the loser a
   costless refund option, and no bond prices it away.

What survives is the whole tactical texture: arrows as ballistic objects that land in your own legionaries'
backs, satchels that bounce and roll downhill into your line, terrain that halves a charge, twelve units that
are all you have, and friendly fire that is not a rule but the *absence* of a rule.

---

## 2. What was grafted in, and from where

| Taken | From | Why |
|---|---|---|
| The state digest as a *loud* divergence detector | BEAT design's per-beat `dg` | A cross-browser desync in an 800-line integer sim is otherwise silent. Generalised here to a per-run tick-Merkle root carried in every claim. |
| "The chain stores inputs, never assertions" | BEAT design | The clean statement of pool's boundary. Adopted verbatim as the design rule. |
| `hr0` is not raw-assemblable; stored words must stay < 2^50 | BEAT design | Verified: `zkvmasm.assemble("hr0")` → `unknown op 'HR0'`; `hash d <- s…` is the only hashing form. Both constrain the encoding. |
| Battleship's `TIMEOUT` shape over tictactoe's refund-both `abort` | WEGO + BEAT designs (independently) | `tictactoe.py:271` pays `st` back to *both* seats once `dl < cursor`, permissionless. In a staked game that is a theft button. Relevant only from v2, but it must be designed in from the start. |
| A terminal claim the opponent cannot veto (hash a state vector, count survivors) | WEGO design's `finish(g, v0..vN)` | The only construction any of the three offered that lets an escrow pay a winner without the loser's cooperation. Deferred to v3 here, but the tick-root makes it reachable. |
| Fixed tick count + hashable state as a **day-one** constraint | WEGO design (bisection fallback) + gauntlet design | Free now, impossible to retrofit. It is the entire precondition for a fraud proof. |
| Three implementations in lockstep, engine version pinned in the claim | WEGO design | This repo's standing rule; a mid-flight engine change desyncs everyone silently. |
| `DIVMOD` soundness window picks the fixed-point scale, not art | WEGO design | Verified at `zkvm.py:28`: `1 ≤ b < 2^15`, `q < 2^48`. **Q16 = 65536 does not fit; Q10/Q12 do.** Choose scales before drawing anything. |

And one thing I **rejected** from the design I'm building on: the "Will" order budget. Judgement 1 is right —
128 commands is `symsPerWord(25) = 2 × 64 words`, a serialization limit wearing a fiction hat. Myth and AoE
micro is not budgeted; the constraint is your hands. Ship `words = 128` (256 commands, ~2.8/s over 90s) and
do not dress the cap as a resource. It costs ~260 extra instructions in the contract (measured below) and
removes the one criticism that lands squarely.

---

## 3. The trust boundary, precisely

Copy pool's split and do not move it. `execnode/games/pool.py:1-13` states the rule and it holds here with
one simplification and one addition.

**The simplification: zero in-run randomness.** Pool needs `kh` for the rack; stormhold pins a fresh seed
height per move (`mh[mc] = (cursor+GAP)*4+side`). Gore shuffles nothing after generation — terrain, wave
composition and spawn ordering are all baked at generation time from two hashes, and from there the run is a
pure function of (terrain hash, wave hash, address, input log). **Drop the MH board entirely.** No per-move
seed heights, no mid-run `bhash`, no seed bookkeeping in the client. Offline replay becomes total.

**The addition: the claim is one fat object, not a stream.** 128 words on the ARG bus (`MAX_ARGS = 1024`) in a
single `post`, not 128 fee-paying calls.

### The chain arbitrates, and only this

- **Who ran** — `ctx caller`, written into `E_ADDR`.
- **The day's terrain** — `_lib.daily_anchor(A_H, A_V, DCNT, DLIST)`, verbatim. Two-phase and grind-proof by
  construction: phase 1 pins `h = cursor + gap` *before its hash exists for anybody*, phase 2 reads `BHASH(h)`
  and **stores the value**, so a snapshot-bootstrapped node with no block history can still verify a
  six-month-old claim. Measured: **60 instructions.**
- **The attempt's waves** — `muster(day)` pins `mu = cursor + GAP` at a per-player slot
  `HASH(TG_MUSTER, day, caller)` (hamster's `HASH(101, race, lane, addr)` trick). `post` resolves `BHASH(mu)`,
  requires `cursor <= mu + LIVE_WINDOW`, **writes the resolved hash to `E_MU`**, and clears the pin.
- **The wall-clock envelope** — that one `lt`. See §5; it is the only real clock in the design and it is the
  piece the source design got wrong.
- **Bounds and ordering** — `day == today ± 1`, `n <= MAX_N`, `score <= MAX_SCORE`, entry append log.
- **Money** — *nothing in v1*. The faucet rail (`_faucet_rewards.py` `GAMES` + `DAILY_VERIFY`) pays off-chain
  against a re-run of the same replay.

### The client simulates

Terrain generation, wave generation, ballistics, blast impulse, slope, collision, damage, scoring, rendering.
All of it. `static/gore-engine.js` is the entire game and it is consensus code.

### Neither touches gore

The goriest game on the chain has no gore in consensus. Blood, gibs, dismemberment, screen shake: seeded from
`H(stateHash(st), unitId)` **at render time**, never fed back into state — `autogame.js`'s `addGore`/`goreSeed`
already does exactly this, and `doc/autogame.md §4` is the rule: *consensus pays for nothing it does not decide.*

### On disagreement

There is no counterparty in v1, so there is nothing to arbitrate. A claim whose replay does not reproduce its
score simply **never renders** — `verifyEntries` (`static/provable.js:149`) drops it in every honest browser,
and `tests/gore_daily_verify.mjs` re-runs the identical replay in the distributor so it earns nothing. The
failure mode is not theft; it is a claim that vanishes.

That vanishing is also the sharpest hazard in the design, so it gets a second channel: **every claim carries a
tick-Merkle root** over the 2048 per-tick `stateHash(st)` values, plus the engine version. A verifier that
reproduces the score but not the root now knows the difference between "you cheated" and "your engine
diverged," and can name the tick. That converts a silent, browser-correlated board fragmentation into a
reproducible bug report — both the input log and both seed hashes are already on chain.

### On disconnect

Nothing. There is no on-chain run until you post a finished artifact. Autogame's principle survives *literally*
— "no input = nothing resolves" — and in a stronger form than autogame itself, because there is not even a
parked run to come back to. The worst absence costs is 90 seconds and one `muster` fee.

No AI takeover, ever. An autopilot would have to be inside the deterministic engine or replays diverge, which
means shipping a bot good enough to play for you, which means the bot's quality becomes the game. Autogame
already cut its doctrine mode for the adjacent reason (`doc/autogame.md §2`).

---

## 4. The MVP

**One shared daily field. One ~90-second defence. Twelve units. Free board only. No stake, no duel, no
campaign, no persistence.** That is the entire Myth thesis on one screen, riding a rail eight games already
ship.

### The loop

You hold a crest. Thrall come up the slope; Soulless lob from behind them. You have **6 legionaries** (melee
line), **4 archers** (arcing volleys), **2 dwarves** (satchel charges). Three physical facts generate all the
micro:

- **Arrows are objects, not raycasts.** They arc under integer gravity and land where the ballistics put them.
  Step your line forward after ordering the volley and your own arrows land in your own backs. The real order
  is never "volley" — it is "volley, *then* pull the line back four metres."
- **Satchels bounce and roll with the slope.** Thrown uphill they come back. The best move in the game is
  timing a charge into the pack as it crests; the worst is throwing while your line is engaged.
- **Friendly fire is the absence of a team check**, exactly as nothing in pool's `pocketed()` reads whose ball
  it is. Scoring makes it bite: enemy kill **+10**, friendly death **−50**, survivor **+100**, time bonus on
  the tick the last enemy dies. A satchel that takes 8 thrall and 2 of yours is **net −20**.

### The enemy has no AI. It has a script.

This is the subsystem all three designs left unpriced, and the answer that keeps it small is also the faithful
one — Myth's campaign enemies were scripted approaches, not agents. Each spawned unit carries a fixed waypoint
chain from the wave table. Runtime behaviour, entire: if a player unit is within `AGGRO`, walk straight at the
nearest (ties broken by **unit index**, a written rule) and attack; otherwise continue the chain. Soulless fire
at the nearest player unit in range every `RELOAD` ticks, arcing — **and their arrows hit their own thrall.**
~30 lines, integer, no data structure with implementation-defined iteration order.

### No pathfinding, in either direction

A\* tie-breaks end up depending on heap or hash-map iteration order and diverge silently between engines. Do
not write it. Units walk straight at the waypoint and slide along an obstacle with a fixed left-then-right
probe. It is more Myth, not less: routing around the ridge is the player's job.

### Determinism, and what it costs

`static/pool-engine.js` already paid most of this bill — **import from it, do not re-derive**: `isqrt`
(line 89, Newton-seeded then corrected until `r² ≤ n < (r+1)²`), the BigInt-Taylor `SIN`/`COS` tables
(114–138), `angleOf`'s exact integer cross-product search (144). `Math.sin`/`Math.cos` are never called; the
file's header says why. Inherit its three rounding scars verbatim, because they bite identically here:
`decay()` rounds to nearest symmetrically (truncation "swallowed two thirds of a delicate safety's roll");
velocity rides at Q14 while position rides at Q10 (round-to-nearest friction *stalls* below half a unit, so at
Q10 alone a rolling satchel never stops); the rest threshold must sit above that stall.

What is genuinely new and what it costs:

- **Ballistics** — one `z` at Q10, constant per-tick gravity. Cheap and exact.
- **Explosions** — falloff defined on `d²` needs no root at all; only knockback direction needs one `isqrt`.
  Keep blast radii powers of two so falloff is a shift.
- **Terrain** — 64×64 int16 heightfield, integer diamond-square, shift-based smoothing. Bilinear height
  lookups **round to nearest, never truncate**. Speed scales through an integer table; gradient pushes rolling
  explosives.
- **Aiming must be the simulation.** Non-negotiable, and it is pool's hardest-won lesson: `previewShot`
  (`pool-engine.js:450`) runs the *real* `simulate()` on a copy of the table "so the aiming line cannot promise
  a contact the physics will not make." Here the throw arc you drag is the arc that flies, over the real
  heightfield, showing the real blast radius and **which of your own men are inside it**. If the indicator and
  the projectile come from different code, the UI lies about friendly fire, which is the one thing this game
  cannot afford to lie about. The archer's launch-angle solver (~20 sim steps of binary search, no closed form
  in integers) therefore lives in the engine, not the UI.
- **Ordering, not arithmetic, is the real cost.** ~72 bodies is ~2 600 pair-tests/tick × 1 800 ticks ≈ 4.6M.
  Fine in JS with typed arrays — but adopt pool's exact discipline (`pool-engine.js:310-322`): only *moving*
  bodies drive the scan, each moving/moving pair visited once by its lower index. Write the rule down: *any
  spatial acceleration structure must be proven order-equivalent to the ascending sweep, or not used.*
- **Field-wrap discipline's sibling applies.** This engine runs on `Int32Array`, not Goldilocks, but every
  subtraction of a player-controlled quantity (hp, ammo, fuse) goes through a clamped helper. A wrapped
  `Int32` hp pool is the same bug in a different hat.
- **Hard bound**: exactly **2048 ticks**, always, like pool's `MAX_TICKS = 30000`. Not "up to." Fixed, so the
  per-tick hashes form a clean 2^11 tree.

### Command encoding

`dt(6) | sel(4) | verb(3) | x(6) | y(6) = 25 bits`. `symsPerWord(25) = 2` (verified), `1 << 25` is inside
int32, a packed word stays under 2^50 and survives the JSON `_view`. **`static/provable.js` needs no change.**
`sel`: 0–11 a unit, 12–14 squad A/B/C, 15 all. `verb`: MOVE, ATTACK-MOVE, HOLD, FACE, THROW, VOLLEY, CHARGE,
RETREAT. `dt = 63` is a WAIT escape advancing 62 ticks. **Running out of commands ends your input, not the
run** — the sim always plays to tick 2048 with whatever standing orders remain.

### The contract

`execnode/games/gore.py`, ~50 lines plus the ABI block.

```
DCNT_SLOT = 2   ECNT_SLOT = 3
A_H = 200  A_V = 201  DLIST = 202            # daily terrain anchor (_lib.daily_anchor)
E_DAY = 50  E_ADDR = 51  E_SCORE = 52  E_N = 53  E_TS = 54
E_MU  = 55                                   # RESOLVED muster block hash (value, not height)
E_ROOT = 56                                  # tick-Merkle root + engine version, packed < 2^50
ELIST = 60
EW_BASE = 70 .. 197                          # 128 claim words = 256 commands
MU pin: HASH(TG_MUSTER = 300, day, caller)   # per-player, per-day muster height
```

Methods:

- `anchor(day)` = `_lib.daily_anchor(A_H, A_V, DCNT_SLOT, DLIST)` — **measured: 60 instructions.**
- `muster(day)` — ~20 instructions. Requires `day == today`; if the pin is 0 **or** stale
  (`cursor > mu + LIVE_WINDOW`), write `cursor + GAP`; otherwise revert. The stale-repin branch is
  `daily_anchor`'s `repin` label, verbatim in shape.
- `post(day, score, n, root, w0..w127)` = `_lib.daily_post(..., words=128, max_n=256, max_score=60000,
  e_ts=E_TS)` with a spliced prologue, in exactly the way `pool.py` splices `tictactoe.SRC["open"]` and asserts
  the splice took. The prologue: load the pin → `require` nonzero → `bhash r5 <pin>` → `require cursor <= mu +
  LIVE_WINDOW` → `sstore E_MU <- hash value` → `sstore E_ROOT <- root` → zero the pin. Measured: `daily_post`
  at `words=64` assembles to **391 instructions**; at 128 words it is ~650, plus ~25 for the prologue.

Total on-chain surface: **under 750 instructions against `GAS_LIMIT = 131070`.** Three orders of magnitude of
headroom, on a rail that scrapline, autogame, hexholm, hamster, battleship, connect4, reversi and tictactoe
already ship.

Register `"gore"` in `execnode/games/deploy.py`'s `GAMES`. **Every later rule change goes through
`deploy.py --upgrade <cid>`, never a fresh cid.**

### The client files

| File | What it is |
|---|---|
| `static/gore-engine.js` | The sim. Exports `genField(dayHash)`, `genWaves(muHash, addr)`, `init`, `step(st, cmds)`, `run(seeds, moves) → {score, st, root}`, `stateHash(st)`, `encCmd`/`decCmd`, `previewThrow`. Imports `isqrt`/`SIN`/`COS`/`angleOf` from `pool-engine.js`. Headless under node. |
| `static/gore-art.js` | `fillRect`-only sprites + the gore layer, shaped like `autogame-art.js`, guarded by `tests/gore_art_verify.mjs`. |
| `static/gore.js` + `static/gore.html` | Client on `nadodapp.js` + `provable.js`, using `installModes`, `dailyFrame`, `seedDaily`, `entriesFrom`, `verifyEntries`, `renderTopScores`. **The game writes no plumbing of its own** — SDK-first; anything not Gore-specific goes into `nadodapp.js`. |
| `static/i18n_games/gore.json` | Then `python3 static/i18n_games/merge_games.py`. **The JSON alone ships nothing.** |
| `tests/gore_engine_test.mjs` | Golden replay vectors, node **and** in-browser. The file that keeps the game honest. |
| `tests/gore_model.py` | The readable reference implementation + differential oracle. Third of three, per this repo's rule. |
| `tests/gore_daily_verify.mjs` | Faucet oracle, registered in `_faucet_rewards.py` `GAMES` + `DAILY_VERIFY`. |
| `_gore_e2e.py` | anchor → muster → play → post → distributor ranks it; a **stolen claim does not**; a post outside `LIVE_WINDOW` **reverts**. Modelled on `_autogame_daily_e2e.py`. |

Run order matters: **`gore-engine.js` headless with bit-identical vectors under node before a single pixel is
drawn.** It is the only irreversible decision in the project.

### One SDK change, and it is not Gore-specific

`verifyEntries` (`static/provable.js:149`) today replays **every** entry on the board before sorting, so a
bogus high claim cannot squat the top. Gore's replay is 2048 ticks × ~72 bodies — heavier than a scrapline
draft by orders of magnitude. Change it to verify in **claimed-score-descending order and stop after K
survive**: a liar with a huge claimed score costs exactly one replay and then falls out, and an honest board
costs K. Every provable game benefits. Hold the engine to a measured budget of **one claim replayed headless in
under 100 ms**, and let that measurement — not art — cap the body count.

### Explicitly cut from v1

Formations, fog of war, veterancy, multiple maps, the campaign/warband, any stake, the duel escrow, the fraud
proof, the live Arena over a peer transport. **Explicitly not cut, because each is load-bearing:** arcing
projectiles that hit your own men, satchels that roll with the slope, the −50 friendly-death penalty, and gore.

---

## 5. `muster` — the piece the source design got wrong, and the fix

The gauntlet design proposed `muster` as its "one genuinely novel piece." As specified it is **worth zero**,
and the second judgement caught it exactly: the run's seed was `provableSeed("gore", day, anchor, addr)`, which
does not depend on the muster pin at all. A tool-assisted player solves the field for six hours, *then* calls
`muster`, then posts two blocks later. The window bounds muster→post; nobody cares about that quantity.

The fix is one line of seed plumbing and it makes the mechanism real:

> **The terrain is daily and shared. The waves are minted at muster.**

- Terrain = `genField(A_V[day])` — the shared daily anchor. Public, learnable across the day, and the reason
  ghosts are legible.
- Waves = `genWaves(BHASH(mu), addr)` — **does not exist for anyone, including you, until block `mu` is
  mined.** There is nothing to pre-solve.
- `post` requires `cursor <= mu + LIVE_WINDOW`, so the clock now bounds *think-time*, not bookkeeping.

Two consequences to write into the code, not the docs:

- `post` must store the **resolved hash** in `E_MU`, never the height. `record_block_hash` reaches ~20 000
  heights and a snapshot-bootstrapped node's `BHASH` read *reverts* where a from-genesis node returns a value
  (`execnode/state.py:698`). A claim that stores a height is unverifiable the moment the pin ages out. Storing
  the value is `daily_anchor` phase 2 applied per entry, and it is the same fund-lock/prune class this repo has
  already fixed across farkle/coinflip/blackjack/dice/roulette. Nothing is escrowed here, so the failure is
  merely a dead board rather than locked stakes — do it right anyway.
- Field re-rolling is legal and priced. Muster, see waves you dislike, muster again — but each re-roll costs a
  tx fee **and obliges you to actually play 90 seconds inside `LIVE_WINDOW`**. The anti-TAS mechanism does
  double duty as the anti-grind mechanism.

`LIVE_WINDOW = 100` blocks (~10 min for a 90-second run, ~6.7× slack). Do not pick that number from this
document — **instrument the observed exec lag for a week and pick it from real data.** `doc/autogame.md:84`
records this repo losing a 96-second window outright when exec trailed L1 by ~102 blocks.

---

## 6. Stakes: the theorem, and the only honest path

**Do not ship a stake in v1.** The reasoning is a theorem, not caution:

> With symmetric information and no on-chain adjudicator, the loser always holds a costless refund option, and
> no bond removes it. Price the bond above the stake and the defrauded honest player will not dispute either;
> price it below and the loser always disputes.

That is already true of chess, pool and stormhold, and `pool.py:13` says so. The BEAT design's escrow, which
otherwise gets every detail right, dies on exactly this: a loser whose army is dead is never a "sole debtor" —
he keeps committing all-hold beats to the cap, nobody owes anything at the deadline, `claim` never fires, and
`abort` refunds both. That is not an edge case; it is an always-available, fee-priced option to convert any
loss into a draw.

So the staged path:

**v2 — the async shared-field duel, stake-optional, default zero.** Both players run the *same* scenario
(shared terrain, shared muster block pinned at the second `join`), separately, whenever they like. Each posts
`commit(g, H(TAG, salt, score, n, w0..w127))`; both then `reveal`. Higher verified score wins. This buys three
real things: hidden information enforced *in-VM* (`reveal` re-folds the hash — `hash d <- s1 s2 …` is
variadic, and `battleship.claim` already folds a 128-leaf tree at **1 255 instructions**, measured), so a score
is fixed before you see your opponent's; `claim(g)` on a sole debtor using battleship's `TIMEOUT` shape
(`battleship.py:244` — `wr = caller`, the waiter, **not** tictactoe's refund-both); and a correspondence clock
(`MOVE_CLOCK = 14400` ≈ a day) so "I have to go" costs nothing and "I ghosted after seeing your score" costs
the pot.

Register pressure forces a two-level hash fold (8 registers, 130+ hashed values, and `hr0` is not
raw-assemblable — verified). `alghash.js` must mirror the exact fold shape.

State the limitation in the UI, not just the doc: **after both reveal, a spiteful loser can still refuse
`agree` and force the refund.** The escrow's function is attendance, not enforcement.

**v3 — the only trustless construction: interactive bisection.** The run is exactly 2048 ticks and the state
is a fixed integer vector, so the claim already carries a Merkle root over 2048 per-tick `stateHash(st)`
values. On dispute the two sides bisect — **11 rounds, one tx each, ~2 minutes of block time** — down to one
disputed tick, and the contract executes **one tick** in zkasm against Merkle-proved state supplied over the
ARG bus. One tick of 12 units + ~60 enemies + projectiles fits inside 131 070 steps; 2048 ticks never would.
This is the only path where a false disputer provably loses, and it is what makes bounties trustless.

Its cost is a **fourth implementation**, and I will not understate it. `autogame.build()["advance"]` assembles
to **14 745 instructions** — measured — and needed ~1 400 lines of Python emitter plus `tests/autogame_model.py`
plus a balance harness, for *discrete integer RPG arithmetic*. One tick of Q10/Q12 ballistics with `isqrt`,
per-pair blast falloff and heightfield sampling, on 8 registers with storage as the only memory, and every
scratch slot scrubbed before return or it leaks into the state root (`tests/autogame_contract_test.py` already
asserts "scratch residue in the state root") — that is a project, not a feature.

**Do not build it for v1. Do not design it out of reach either.** The two constraints that keep it reachable
are free today and impossible to retrofit: *the tick count is fixed at 2048*, and *the state vector is
hashable*. Anything that makes the run length variable — an early-out when the last enemy dies, a "play until
you lose" mode — closes that door permanently. Score the time bonus instead and keep simulating to 2048.

---

## 7. Honest risks

**The one that would kill it: silent cross-browser divergence in `gore-engine.js`.**

The engine *is* the product and it is consensus code. Pool survives this bar with 16 balls and 688 lines. Gore
runs ~72 bodies with ballistics, blast impulse, terrain sampling, a launch-angle solver and an aggro tie-break
— a state surface 5–10× pool's, and divergence probability scales with surface. The failure is not a crash and
not a wrong answer: it is that every Safari player's claims silently fail to verify in every Chrome viewer's
browser and vice versa, the board fragments by engine, and **no error message appears anywhere.** An honest
player is simply and quietly treated as a cheat.

Mitigation is the tick-Merkle root in `E_ROOT` — it makes the failure loud and names the tick — plus
`tests/gore_engine_test.mjs` run under node *and* in-browser, and `tests/gore_model.py` as an independent
oracle. But a detector is not a cure, and the posture must be the L1 state-root gate's posture: **any root
mismatch in the wild is a FATAL bug, never a game outcome.** Budget real weeks for this and treat it as the
schedule, not a phase of it.

The rest, in descending order:

- **The muster window rests on exec-lag stability.** If lag shrinks 60 blocks mid-run, honest posts revert; if
  it grows, the window silently widens and the anti-TAS defence evaporates. Instrument before choosing
  `LIVE_WINDOW`; treat a revert on `post` as a bug-level alert, never a player error. This repo has been burned
  by exactly this assumption once already.
- **Even with the fix, you cannot prove a run was played in real time.** You can prove it was legal
  (`doc/provable-practice.md §3` is candid that "scripted assistance cannot be prevented"), and you can now
  bound think-time to `LIVE_WINDOW`. A tool that solves a 90-second field in six minutes still beats the clock.
  The honest statement to the owner: **on a public chain you can prove what was done and bound how long it
  took; you cannot prove it was done by hands.**
- **Verification cost on the board.** The `verifyEntries` reordering in §4 fixes the asymptotics; the constant
  is a measurement, and it caps the body count. If ~72 bodies cannot replay headless in 100 ms, the enemy count
  comes down — and that is exactly the scale that makes it Myth.
- **The aiming solver is consensus code that lives in the UI's hot path.** ~20 sim steps per preview, re-run
  every mouse-move. If it is ever "optimised" into a separate closed-form approximation for the indicator, the
  UI starts lying about which of your own men are in the blast, and the whole design's centre of gravity is
  gone. Write that as a comment in the file, the way `previewShot` did.
- **No human opponent in v1.** Ghosts and a shared field recover rivalry, not adaptation. Micro against a fixed
  wave schedule is a solvable optimisation in a way micro against a person is not. This is the deepest
  structural concession and no v2 fully repairs it.