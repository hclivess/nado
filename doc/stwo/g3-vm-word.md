# G3: the contract VM's word after Goldilocks (doc/stwo-migration.md 9.4, 9.5)

Measured 2026-10-19. Route A (our own zkVM as Stwo components) was chosen 2026-10-18; this records G3's entry
measurement and the operator's decision on the VM word, which every contract and the settlement circuit build on and
which is frozen at the generation-29 reroll.

## 1. What the contracts rely on today

Today a register holds one Goldilocks field element: ADD, SUB and MUL wrap mod P = 2^64 - 2^32 + 1. To find which
contracts depend on that, the 35 light offline game tests (73 s together; the suite's recorded times) were run against
the zkVM with its field operations replaced in memory by logging versions (no file edited): every ADD/SUB/MUL whose
integer result differed from the field result was recorded with the contract (by code digest) and method.

**22 of the 27 contracts wrap** in at least one method (248 distinct contract/method/kind cases: 99 subtractions below
zero, 75 additions and 74 multiplications past P). Battleship, chess, scrapline, sovereign and stormhold logged none in
these tests, which means unmeasured here, not clean. Per contract:

| contract | subtraction below zero | add / mul past P |
|---|---|---|
| pets | 15 methods | 15 methods (hatch, fuse, resolve_battle, ...) |
| otc | 9 | post, settle |
| bet, hamster | book, quote (+ settle) | back, bclaim, bet, claim, create_market, resolve, ... |
| blackjack, holdem, coinflip, dice, roulette, slots, mines, farkle | reveal/settle paths | reveal/settle/draw/hold |
| autogame | advance | advance, commit |
| connect4, tictactoe, reversi, pool, hexholm, lend, reserve, dex, faucet | join/move/cancel/claim/... | none |

The operand sizes sort them into three patterns:

1. **Subtraction as an equality test** (almost every contract). `join` subtracts two owner digests (both near P) and
   the following NEZ asks "is the caller player 1?"; `move` computes 0 - 1 and tests it. Harmless today because the
   result only feeds NEZ/EQ. A CHECKED word (revert on underflow) would revert every one of these calls.
2. **Digests mixed into storage keys and commitments** (bet, hamster, pets, otc, ...): `create_market` computes
   3 x digest + digest; pets' `hatch` 2 x digest. The values depend on the modulus, so any new word changes them; they
   only have to be computed identically by the contract and by the game clients that mirror it.
3. **Hash-derived randomness** in reveal/settle (dice, slots, roulette, blackjack, mines, ...): the same as 2.

## 2. Decision

**Operator, 2026-10-19: a 256-bit word, wrapping.** ADD, SUB and MUL wrap mod 2^256, as in the EVM.

- A BLAKE2s digest, an owner digest (which must grow to >= 128 bits, doc/stwo-migration.md 9.2) and any amount all fit
  one register, so pattern 1 keeps working unchanged, and patterns 2 and 3 keep their shape (new values, same code),
  moved in lockstep with their client mirrors as G3 already requires.
- The rejected alternatives: a 64-bit wrapping word puts every digest across 4 registers (storage layout and
  comparisons rewritten in the ~18 contracts that store owner digests); a 64-bit checked word additionally reverts the
  subtraction-as-equality idiom everywhere.
- Cost: a wider circuit row (16 x 16-bit limbs per value instead of 4); at the measured load (74 calls in 60,000 blocks,
  doc/stwo/g1-tree-shape.md) that is affordable, and it is the price of porting 22 contracts mechanically.

## 3. What the word means, opcode by opcode (to be specified in full before code)

Fixed by the decision:
- ADD / SUB / MUL: wrap mod 2^256.
- EQ / NEZ / NOTB: exact over the word.
- LT: SOUND over the whole word (the 63-bit window, the RANGE pre-check and the "full-field compare" open item of
  zkvm.py's header all retire), so a contract can compare a hash to a target without the 2-limb gadget.
- One BLAKE2s-compression opcode replaces the 30 alghash round opcodes (HINIT/HABS/HR*/HOUT); its output is one word.

Open, for the G3 spec (each frozen at the reroll):
- DIVMOD / DIVMODW: full-width unsigned division with the remainder in r7 (the 48/15 and 32/31 windows existed only to
  stop field wrap), and what a zero divisor does (revert, as today's 1 <= b);
- LO32 and the slot-key idiom `field * 2^32 + key`: kept as plain 256-bit arithmetic, or replaced by a key-derivation
  opcode;
- caller / asset / self digests: BLAKE2s of the address, 256 bits, through the same digest-to-address registry;
- immediates (MOVI): today < P; under the new word a 256-bit immediate needs an encoding decision.
