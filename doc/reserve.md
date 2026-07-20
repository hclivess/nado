# Reserve — backing an asset with locked native value

A creator issues a token and locks native value behind it. Holders can always hand the token back and take
their share of that reserve, and the creator can only ever take the reserve back **after an announced
waiting period** — the same shape as validator unbonding, so nobody is surprised.

The point is to replace a *claim* ("I'm invested in this token") with an *enforced number* a holder can act
on: the redemption rate the contract will actually honour.

---

## 1. Why this is a contract and not a ledger field

Nothing here needs a protocol change. `doc/assets.md` §5 is built around "there is no privileged path, and
`stage_asset_effects` is the only writer"; a `reserve` field on the asset record would be the first
privileged field, and every future argument would be about who may bypass it. Keep the ledger dumb.

The primitive that makes it work is that **burn is holder-side**. `stage_asset_effects` checks
`bal(aid, actor) >= amt` for a burn and does *not* check the issuer (`execnode/state.py`, the `burn`
branch). So a vault that merely **holds** tokens can destroy them. It does not need to be the issuer, which
in turn means an ordinary person can issue a token with `asset_create` and back it here — no `for: <cid>`
deployer privilege required.

---

## 2. What the floor is, exactly

    floor = reserve / outstanding          (native value per token unit)

A redemption of `amt` pays `amt · reserve / outstanding`, then reduces **both** by what it moved. So:

    reserve' / outstanding' = (reserve − amt·reserve/outstanding) / (outstanding − amt) = reserve / outstanding

**Redemption is floor-NEUTRAL, not floor-raising.** There is no ratchet and this document does not claim
one — a pro-rata exit leaves the remaining holders exactly where they were. The floor moves in only two
places:

| event | floor |
|---|---|
| `back()` — anyone adds reserve | **up** |
| `redeem()` — a holder exits pro-rata | unchanged |
| `release()` — the creator withdraws, after notice | **down** |

An exit fee retained in the reserve *would* make it ratchet upward, and was deliberately left out: a fee on
leaving is user-hostile for something whose whole purpose is a guaranteed exit.

---

## 3. The notice period is the product

`announce(amt)` → wait `notice` blocks → `release()`. Three properties make it worth something:

- **The creator picks `notice` at open time and it is immutable.** It can never be shortened. A vault that
  commits to 30 days is making a stronger statement than one that commits to the minimum, and that is a
  number a UI can rank on. `MIN_NOTICE` is only a floor.
- **Re-announcing RESTARTS the clock.** Otherwise a creator announces a token amount, lets the timer run
  down, then swaps in the full reserve and withdraws instantly.
- **Redemption stays open the entire time.** A notice you cannot act on is decoration. During the window
  every holder can still exit at the *pre-release* floor, which is precisely the escape hatch the
  announcement exists to give them.

`release()` pays `min(pending, reserve)` — redemptions during the window may have drained the reserve below
what was announced, and clamping is friendlier than forcing the creator to start the wait over.

---

## 4. The honest gap: the contract cannot see supply

There is no opcode to read an asset's `supply` or its `mintable` flag (`doc/assets.md` §3 is five opcodes;
neither is among them). So `outstanding` is **declared by the creator at `open()`** and thereafter only
falls, as the contract burns.

The contract is never insolvent regardless — payout is always `≤ reserve` and pro-rata — but the *declared*
floor is only trustworthy if the declaration matches reality. Both halves are public reads, so the check
belongs in the UI, not the circuit:

> The floor is real **iff** `/exec/asset?id=` reports `mintable: false` **and** its `supply` equals the
> vault's `outstanding` plus everything already redeemed.

If the creator kept minting, they dilute the floor for everyone including themselves, and the registry says
so. Show the mismatch loudly; do not show a floor number next to an asset that can still be minted.

This is the strongest argument for the `ARENOUNCE` opcode that `doc/assets.md` §7 already flags as missing:
with it, a vault could refuse to open against a still-mintable asset in-circuit.

---

## 5. Field widths — where this contract can actually bite

`DIVMODW` is the only wide divide (`zkvm.py`: `1 <= b < 2^31`, `q < 2^32`). The pro-rata payout is a
`mul` + `divmodw` pair, so both operands are constrained, and the contract **enforces the bounds with
`require` rather than trusting callers** — an out-of-range divmodw is not a wrong answer, it is an
unprovable trace.

- Reserve is held in **UNITs**, `UNIT = 10^8` raw (0.01 native at `RAW = 10^10`).
- `reserve_units < 2^31` → a vault caps at ~21.4M native. `outstanding < 2^31` → ~2.1e9 token base units.
- Both bounds are re-checked on every `back()`, because that is the one path that can grow the reserve.

With `amt ≤ outstanding < 2^31` and `reserve_units < 2^31`, the product stays under 2^62 (inside the field)
and the quotient under `reserve_units < 2^31 < 2^32`. Both DIVMODW preconditions hold by construction.

### Three traps this contract actually hit

**Do not derive the unit count — have the caller state it and multiply.** `value // UNIT` compiles to
DIVMOD, whose divisor must be `< 2^15` while `UNIT` is `10^8`. Reaching for DIVMODW instead only moves the
problem: it would put an *unbounded* `value` over a quotient budget the contract cannot check until after
the divide, and an oversized quotient does not revert — it emits a trace no prover can close, which is a
denial of service wearing arithmetic's clothes. So `open`/`back` take the reserve in UNITs as an argument
and assert `value == units · UNIT`. Multiplication is total, the bound is checked *first*, and the equality
rejects dust in the same breath.

**Never order-compare a hash-derived value.** `require(asset > 0)` looks like a null check and is a
liveness bug: the `lt` macro RANGE-checks both operands, RANGE reverts at `2^62` (`_decomp62` — that bound
is exactly what makes a comparison unforgeable), and an asset id is uniform in `[0, P)` with `P ≈ 2^64`.
About **three of every four real assets** would have been refused by the vault built to back them. Use
`!= 0`; EQ carries no range gate. `tests/test_reserve.py::t_high_asset_ids_are_backable` pins it, and it
only reproduces with genuinely derived ids — a small hand-picked one passes either way.

**Everything else caller-supplied is safe to compare**, because out-of-window operands make RANGE *revert*
rather than answer wrongly. A refusal is a sound failure; a wrong comparison would not be.

---

## 6. Storage

One deployment serves every vault, keyed by a frontend `vid < 2^32`, in the usual composite slot model
`slot(field, vid) = field·2^32 + vid`.

| field | name | meaning |
|---|---|---|
| 1 | `own` | creator's address digest |
| 2 | `ast` | the asset id this vault backs |
| 3 | `res` | reserve, in UNITs |
| 4 | `out` | outstanding token base units |
| 5 | `ntc` | notice period in blocks (immutable) |
| 6 | `pnd` | announced release amount, in UNITs (0 = nothing pending) |
| 7 | `rdy` | height at which `pnd` becomes releasable |
| 9 | `list` | index list; slot 0 = count |

## 7. Methods

| method | who | value | effect |
|---|---|---|---|
| `open(vid, asset, supply, notice, units)` | anyone | native | claim `vid`, declare the asset + supply, set the immutable notice, seed the reserve (`value == units·UNIT`) |
| `back(vid, units)` | anyone | native | add reserve — raises the floor for every holder |
| `redeem(vid)` | any holder | **the asset** | burn what you sent, take `amt·res/out` |
| `announce(vid, amt)` | owner | — | start (or restart) the clock on a release |
| `cancel(vid)` | owner | — | withdraw the announcement |
| `release(vid)` | owner | — | after `rdy`, take `min(pnd, res)` |

## 8. Upgradability

Deployed **unlocked** — `upgradable` stays true, so the deployer can `op: upgrade` it in place while the
design settles (`execnode/state.py`, the `lock` op). Locking is the one-way mainnet trust switch and is a
deliberate later decision, not a default.

## 9. Files

| what | where |
|---|---|
| contract | `execnode/games/reserve.py` |
| tests | `tests/test_reserve.py` (19 checks, all executing the contract) |
| the pro-rata primitive | `zkpy.muldiv` — `mul`+`divmodw`, added for this |
| asset layer it builds on | `doc/assets.md` |
