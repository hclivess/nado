# G5: the carry that loses nothing (doc/stwo-migration.md 6.5, 9.5)

Started 2026-10-25. **Operator rule (2026-10-20): the carry carries EVERYTHING.** Every contract's full storage is
re-encoded into the generation-29 formats. Nothing is reset to fresh-deploy storage, and no pot is refunded in place of
carrying it. This is the permanent mechanism (`tools/carry.py`) that moves to mainnet, not a per-generation script.
The inherited `tools/alphanet6_carryforward.py` resets every contract that has no carry hook and refunds its pot to
the deployer. That design is the one being replaced.

**Historical since G9 slice 3b (2026-10-28).** The gen-28 -> gen-29 crossing this document designs ran at the gen-29
reroll and is done. With the field VM (`execnode/zkvm.py`) deleted, its re-encoding went too: `V1Hash`,
`reencode_storage`, the modules' `CARRY_WORDS` / `CARRY_OWNER_KEY_FIELDS` / `carry_hash_preimages` /
`carry_v2_storage` hooks, the `isa=` builds and `tools/carry_census.py` (with its test). From gen 29 on every generation
runs one VM, one hash and one digest, so `tools/carry.py` re-encodes nothing: it matches each contract by `build()`,
refuses anything in flight, rebases heights, and re-derives (never trusts) the registry and the asset ids. The sections
below record how the crossing was built; git history holds the code if a generation ever changes the VM hash again.

## 1. Entry measurement: the census (2026-10-25, exec cursor 357,787)

`tools/carry_census.py` on a copy of the live `exec_state.json`. It is read-only, refuses the live path, and is pinned
by `tests/test_the_carry_census_classifies_every_gen28_encoding.py`.

| contract | slots | value = digest | value >= 2^32 | key plain | key F\|digest | key hash |
|---|---|---|---|---|---|---|
| autogame | 103 | 3 | 2 | 99 | 3 | 1 |
| bet | 1,523 | 456 | 0 | 1,395 | 0 | 128 |
| dice | 79 | 10 | 0 | 79 | 0 | 0 |
| faucet | 94 | 0 | 1 | 1 | 0 | 93 |
| hamster | 38 | 1 | 6 | 38 | 0 | 0 |
| pets | 24 | 2 | 3 | 23 | 0 | 1 |
| roulette | 5 | 1 | 0 | 5 | 0 | 0 |
| slots | 299 | 41 | 3 | 299 | 0 | 0 |
| tictactoe | 9 | 1 | 0 | 9 | 0 | 0 |
| **total** | **2,174** | **515** | **15** | **1,948** | **3** | **223** |

- 18 of 27 contracts hold no storage: battleship, blackjack, chess, coinflip, connect4, dex, farkle, hexholm, holdem,
  lend, mines, otc, pool, reserve, reversi, scrapline, sovereign, stormhold. **No commit-reveal round is open**, so no
  commitment needs a preimage only a player holds. The census is rerun at the reroll, and an open commitment then is
  section 3's one hard case.
- The registry (`zk_addrs`) holds 240 entries: 13 addresses and 227 string arguments (numbers, bet descriptions).
  All 515 digest values resolve through it.
- No assets, no `abal`, no `allow`. The legacy and wide pools hold 0 commitments and 0 nullifiers.
- The 15 large values, classified one by one (`--detail`):
  - amounts, carried unchanged: slots fields 2/3 (bank balances 9.09 and 13.36 NADO), pets fields 0/12 (1.5 and
    1.0 NADO), faucet slot 7 (96.375 NADO);
  - a packed state word, carried unchanged: autogame field 25;
  - hash-valued: hamster field 71 is a resolved daily ANCHOR (a block-hash value the blake2b-seeded board reads as
    stored) — carried verbatim. Pets field 4 is the GENE, and it is NOT only read (section 2a): the census's first
    reading here was wrong, and an audit of every contract corrected it before the carry relied on it.

## 2. The transform, class by class (lossless; each one a test)

| what | gen 28 | gen 29 | how the carry gets there |
|---|---|---|---|
| contract code | v1 (alghash ISA) | `mod.build("v2")` | match by `build("v1")` equality (today's match), emit `build("v2")`; an unmatched contract REFUSES the carry |
| owner / string digest (value) | blake2b mod P | `zkvm_addr_digest(s, v2=True)` (256-bit BLAKE2s) | old digest -> registry string -> new digest |
| registry | keyed by old digest | keyed by new digest | the same walk, every entry |
| key `F*2^32 + digest` | mod P | mod 2^256 over the new digest | autogame OWNRUN (3 slots) |
| hash key | alghash over a preimage | `zkvm2.hash_words(preimage')` | a per-contract hook lists every key's preimage from the contract's own index (bet stake/claim/vote rows, faucet reward markers, pets resource/gear rows, the autogame override row); the carry remaps the digests inside each preimage and rehashes. A hash key no hook explains REFUSES the carry |
| hash-valued value only read | — | unchanged | verbatim, after confirming no code path re-hashes it to compare |
| hash-valued value compared against a fresh hash (commitment, hashlock) | alghash | — | none open today. If one is open at the reroll, it is carried and tagged legacy (section 3) |
| asset id | alghash(issuer, seed) | `state.asset_id(issuer, seed, v2=True)` | recomputed (0 today); `abal`/`allow` keys follow |
| pots, escrows | — | — | carried with their contract (Δ = 0); the reset-and-refund path is removed |

## 2a. Pets: the gene's rolls become state (found 2026-10-25)

A pet's traits are rolls of its gene, `roll32(gn + c)` = lo32(VM hash(gn + c)): tier 555, species 777, the ten base
stats 1000+i, and the browser's coat 7000 and shiny 9000. On v1 they are recomputed on every read — `_eff_stat` in
every battle, every training roll and every building's yield (`10 + trade stat`), the species check in `combine`, and
the page's animal, stat card and coat. The hash changes at gen 29, so a gene carried verbatim would have made every
carried pet a different pet: new stats, new species, new look, new building yield. No gene can be re-derived to keep
them (the traits are residues of independent 32-bit rolls).

So on v2 the rolls are STATE. `hatch` writes each into the ROLL TABLE (field `RT_BASE + j` keyed pid, j over
`ROLL_OFFSETS`, fields 100-113) and every v2 method reads the table instead of re-hashing the gene; the carry fills the
table of every carried pet with its gen-28 rolls (`pets.carry_v2_storage`). A carried pet is therefore the same pet by
construction, and a pet hatched on gen 29 rolls under BLAKE2s. The v1 build is byte-identical; the seven methods that
read a roll are declared per-ISA (`ISA_DIVERGENT_METHODS`). What still reads the gene on v2 is randomness for events
that have not happened yet (combine's reward roll), which may change freely.

Pinned end to end (until G9 retired it with `BLAKE_EXEC_HEIGHT`, when a gen-28 exec state could no longer be staged) by `tests/test_a_carried_contract_plays_on_gen29_exactly_as_it_would_have_on_gen28.py`: a farm
staffed on gen 28, carried through the real genesis loader, harvests EXACTLY its gen-28 yield on gen 29 after the
same blocks; and the bet market beside it reports the same positions and pays every claim exactly as gen 28 would.

## 2b. Measured on the live state (2026-10-25, a copy at exec cursor 357,787)

`python3 tools/carry.py <copy>` re-encodes every slot of all nine non-empty contracts — no slot unexplained:

| contract | slots | keys re-hashed | owner keys | values remapped | large values kept |
|---|---|---|---|---|---|
| bet | 1,523 | 128 | 0 | 456 | 0 |
| faucet | 94 | 93 | 0 | 0 | 1 |
| pets | 24 (+14 roll table) | 1 | 0 | 2 | 3 |
| autogame | 103 | 1 | 3 | 3 | 2 |
| slots | 299 | 0 | 0 | 41 | 3 |
| dice / hamster / roulette / tictactoe | 79 / 38 / 5 / 9 | 0 | 0 | 10 / 1 / 1 / 1 | 0 / 6 / 0 / 0 |

These equal the census. The carry itself REFUSES today, correctly, on what is in flight on the live chain: a dice table
with open bets, three unsettled hamster races, and two autogame runs in the mists (`advance(N)`, permissionless). At the
reroll those are settled on the old chain first (doc/reroll.md); nothing is reset.

## 2c. Still owed before the reroll (each a refusal today, never a silent loss)

- ~~Commit-reveal and hashlock contracts have no in-flight hook~~ — done 2026-10-25: every module now declares its
  carry rule (coinflip, holdem, farkle, stormhold, battleship, hexholm, scrapline, otc, dex, lend, pool, reserve), each
  pinned by a test that drives the real contract to an open round (refused, by name) and to rest (carried whole; for
  coinflip, farkle, the loans, the AMM pools, the vaults and the order book, played on in a gen-29 state and paying
  exactly what gen 28 pays). Rule shared by every commit-reveal game: an OPEN round blocks; a SETTLED game's unrevealed
  commitment does not (a post-settle reveal moves no value, and blocking on it would let anyone hold the reroll forever
  with a self-played game) — it carries verbatim and a reveal of it on gen 29 reverts.
- **sovereign has no carry rule, on purpose**: its world is re-derived from its log through old-chain block hashes
  (every raid roll) and the live cursor (the economy), so a world with a log cannot be carried losslessly; the carry
  refuses it (empty today). Carrying one needs each raid's seed stored and a cursor origin — a redesign, the operator's
  call if sovereign is ever played before a reroll.
- **One party can hold up a reroll** (by design of the in-flight rule, the operator's call to change): a taken loan
  until repaid or due (lend durations up to 2^32 s), an open OTC order until cancelled or expired (up to 1,000,000
  blocks), an unjoined lobby until its opener cancels it.
- ~~The autogame Daily Gauntlet replays claims through the VM hash~~ — done 2026-10-25: the Gauntlet is scored
  off-chain, so its road hash is pinned to the gen-28 alghash (`nadodapp.algHashnV1`) for every generation; a claim
  posted on gen 28 replays to the same score on gen 29 (measured without the pin: 196 -> 413). The other daily boards
  seed through blake2b and were never affected.
- ~~The browser reads pets' traits from the roll table~~ — done 2026-10-25: `static/pets-genes.js` reads the view's
  `r<c>` maps whenever a pet has them (`rollOf`/`rollsFrom`) and the gene only when it has none, which also covers the
  gen-29 gene-exposure gap (v2 exposes 64 of the gene's 256 bits as gl/gh). ~~Still on the gene: `combineStatOf`'s
  preview~~ — done 2026-10-25 (G6): the pets view serves the whole gene (`gn`) and the page reads it; the preview is
  the stat the real v2 contract raises (tests/test_a_gen29_pet_previews_the_combine_the_contract_rolls.py).
- ~~History displays recompute from stored seeds~~ — done 2026-10-25 (G6), by a different route than planned: replaying
  with the old hash is not enough, because hamster's races and holdem's boards also read the OLD chain's block hashes
  and beacons, which the new chain does not have, and no record says which generation made it. So every page follows
  one rule: a recompute is shown only when it reaches the stored result exactly, otherwise the stored result stands
  alone. Coinflip reads a settled face from the stored winner; hamster redraws a settled race only when it reaches the
  stored distances (plain numbered lanes otherwise, or when the race finished above this chain's cursor); holdem shows
  a closed hand's board only when it scores every revealed seat's stored hand; pets replays a settled battle only when
  the replay's winner is the paid one. Records made on gen 29 always reproduce, so they always redraw
  (tests/test_a_pre_reroll_game_record_is_shown_as_paid_never_redrawn.mjs). Still owed (text only): farkle's fairness
  line names the gen-28 formula (`alghash … mod P`).
- **L1 escrows**: open INVITES now carry (2026-10-25: `carried_invites`, genesis re-derives each id under the new
  `CHAIN_ID`). Open HTLC locks are still refunded: carrying one with its expiry rebased would hand the secret-holder
  the reroll's downtime as extra wall-clock time against a foreign-chain lock that kept running (the swap invariant
  "the secret-holder's lock outlasts the one they claim" could break). Carry vs. refund vs. wait-until-settled
  (a lock may run up to HTLC_MAX_TIMELOCK = 1,000,000 blocks) is the operator's decision.

## 3. The one case no transform reaches

A commitment is a hash of a secret only its player holds, so the carry cannot recompute it under the new hash. No such
round is open today. If one is open at the reroll, the carry keeps it and tags it as a legacy commitment. The reveal is
then checked against the old hash, once, for exactly the tagged rounds, and no new round can ever use that path. This
would be an exec-node rule, so it lands only if the census at the reroll finds one.

## 4. Exit tests (doc/stwo-migration.md G5)

- "A reroll loses nothing" on the live chain (6.5): Δ = 0 including every pot; every account, identity, contract and
  slot carried.
- No slot value or key equal to an old digest remains, and the remapped count equals the census.
- Every hash key is re-derived, and a key the hooks cannot explain refuses the carry.
- A carried pet, a battle and an autogame run are playable on a loopback testnet from the carried genesis.
