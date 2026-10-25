# G5: the carry that loses nothing (doc/stwo-migration.md 6.5, 9.5)

Started 2026-10-25. **Operator rule (2026-10-20): the carry carries EVERYTHING.** Every contract's full storage is
re-encoded into the generation-29 formats. Nothing is reset to fresh-deploy storage, and no pot is refunded in place of
carrying it. This is the permanent mechanism (`tools/carry.py`) that moves to mainnet, not a per-generation script.
The inherited `tools/alphanet6_carryforward.py` resets every contract that has no carry hook and refunds its pot to
the deployer. That design is the one being replaced.

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

Pinned end to end by `tests/test_a_carried_contract_plays_on_gen29_exactly_as_it_would_have_on_gen28.py`: a farm
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

- **Commit-reveal and hashlock contracts have no in-flight hook**: coinflip, holdem, battleship, hexholm, stormhold,
  farkle and otc (otc's hashlocks also change layout between v1 and v2). With storage, the carry refuses them as "no
  carry rule"; each needs `carry_in_flight` (an open round blocks) so a contract at rest carries. Empty today.
- **The autogame Daily Gauntlet replays claims through the VM hash** (`static/autogame-daily.js` dailyWorld via
  algHashn, also the faucet oracle): a gen-28 day's claims must replay under alghash after the reroll, or the board of
  the reroll day drops them. The other daily boards seed through blake2b and are unaffected. (G6, with the wallet.)
- **The browser reads pets' traits from the roll table on gen 29** (`static/pets-genes.js`: speciesIdOf, statOf, coat,
  shiny), instead of from the gene; that also retires the gen-29 gene-exposure gap (v2 `hatch` stores only 64 of the
  gene's 256 bits as gl/gh). (G6.)
- **History displays recompute from stored seeds** (coinflip's face, pets' battle replays, hamster's race animation,
  poker's board): the stored results are right, the replays of pre-reroll history would draw differently. Display
  only; G6 replays a pre-reroll record with the old hash.
- **L1 escrows are still refunded, not carried**: open invites and HTLC locks (tools/alphanet6_carryforward.py step
  5b). Same rule: carry them.

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
