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
  - hash-valued but only read, never re-hashed to compare (to be confirmed per contract before the carry relies on
    it): pets field 4 (genes) and hamster field 71 (race values). Carried verbatim, they keep the pet and the race
    exactly as they are.

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
