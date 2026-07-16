# The Faucet — reserved L1 sink → upgradable exec contract → free play in enrolled games

Status: **DESIGN** (nothing implemented). Owner: games/exec layer. Consensus impact: one new L1
reserved recipient (alphanet: goes live fleet-wide immediately, no activation ceremony).

## 1. Purpose

New players hit a wall: every game needs NADO, and getting the first NADO means mining a presence
lease or begging in chat. The faucet closes that loop:

- anyone (the operator, a donor, a future protocol stream) can send NADO **to the literal address
  `faucet`** on L1 — no contract call, no exec-layer knowledge, works from every wallet today;
- those funds accumulate in ONE well-known **upgradable exec contract**;
- the contract dispenses small **free-play grants to players, earmarked per enrolled game**, from an
  operator-curated list with per-game amounts and budgets;
- the **games themselves surface the faucet**: an enrolled game's page offers "🚰 claim free play"
  to a signed-in player whose balance can't cover the minimum stake.

Design goals, in priority order: (1) can't be drained profitably, (2) zero new trust assumptions
(the operator can already upgrade game contracts; the faucet operator gets no NEW powers over user
funds), (3) reuses existing machinery (reserved-recipient dispatch, bridge ledger, zkVM contract,
op:upgrade, SDK), (4) one-tap UX after sign-in.

## 2. Flow overview

```
any wallet ──[L1 tx: recipient "faucet", amount A]──▶ L1: sender −(A+fee) · FAUCET_ESCROW +A
                                                          │  (keyless reserved account, like "bridge")
                            execnode tails finalized blocks│
                                                          ▼
                                     exec ledger: balance["faucet"] += A      (the contract's balance)
                                                          │
player (browser) ──[grind PoW nonce]──[call claim(gameIdx, nonce)]──▶ faucet contract:
        · game enrolled & granting?          · once per (address, game)?
        · epoch budget left?                 · alghash(caller, gameIdx, nonce) < powTarget?
                                                          │ all pass
                                                          ▼
                                             PAY caller grant  →  player's exec balance
                                                          │
                                       player stakes it in the game that earmarked it
```

## 3. L1: the `faucet` reserved recipient

Add `"faucet"` to `protocol.RESERVED_RECIPIENTS` and a keyless escrow constant
`FAUCET_ESCROW = "faucet"` (same pattern as `BRIDGE_ESCROW = "bridge"` — protocol.py:94; the
treasury note at protocol.py:236 documents the keyless-reserved-account convention).

**validate_transaction** rules (mirroring `bridge`): `amount > 0`, `fee >= MIN_TX_FEE`, no `data`
required (ignored if present), sender must afford `amount + fee`. No `reserved_uniqueness_key`
entry — like bridge deposits, many faucet donations may share a block.

**reflect_transaction** (ops/account_ops.py dispatcher — both invariants per its header,
determinism + revert symmetry):

```python
if recipient == "faucet":
    change_balance(address=sender,        amount=-(amount + fee), logger=logger, revert=revert)
    change_balance(address=FAUCET_ESCROW, amount=amount,          logger=logger, revert=revert)
    return
```

The L1 fee burns as usual. The escrow account only ever grows on L1 (the exec side spends the
mirrored balance; nothing ever exits `FAUCET_ESCROW` back to L1 in v1 — see §9 "no faucet
withdrawal").

Consensus deployment: fleet-wide at once (alphanet doctrine — no start heights). A node that hasn't
upgraded rejects `faucet` txs at the mempool door but accepts blocks containing them only after
upgrade, so this is a REQUIRED fleet update like any reserved-recipient addition.

## 4. Exec layer: crediting the contract

`execnode._apply_block` gets one branch beside `bridge` (execnode.py:211):

```python
elif r == "faucet":
    default_state.credit_deposit(FAUCET_CID, tx.get("amount", 0))
```

Contracts already hold spendable balances in the same bridge ledger keyed by their cid (that's how
game pots escrow — `st.bridge.get(cid, 0)` throughout the tests), and the zkVM `PAY` op spends the
calling contract's own balance. So crediting `FAUCET_CID` makes the donation *the contract's money*
with zero new ledger machinery.

**The well-known address.** Two options; v1 picks (a):

(a) **Fixed-name deploy**: teach `execnode/games/deploy.py` a `--at <name>` flag that registers the
    contract under the literal cid `"faucet"` instead of the derived hash (cids are plain dict-key
    strings everywhere — contracts map, storage prefix, balance key). `FAUCET_CID = "faucet"`
    becomes a protocol-level constant; the reserved L1 name, the exec ledger key, and the contract
    address are all the SAME word. Upgrades keep working (op:upgrade is deployer-bound, not
    name-bound). Guard: `--at` only accepts names in a small allowlist (`faucet`) and only from the
    operator key, so the reserved-name namespace can't be squatted.

(b) Derived cid + a constant: deploy normally, then hardcode `FAUCET_CID = "<hash>"` in execnode.
    Works, but the address is opaque and fresh chains need a two-step bootstrap. Rejected for UX.

## 5. The faucet contract (zkvmasm, upgradable in place)

Deployed once by the operator key; evolved with `op:upgrade` (same cid, storage kept) exactly like
the game contracts. Registry is **indexed** (game cids are 128-bit — wider than a field word — so
the claim arg is a small index; the index↔cid mapping ships in the ABI metadata and, for on-chain
binding, a 64-bit digest word of the cid is stored per slot).

**Storage layout** (field-keyed slots, `S(f, k) = f·2³² + k` like the games):

| field | keyed by | meaning |
|---|---|---|
| 1 `gcnt` | — | number of registry slots ever used |
| 10 `gdig` | idx | low-64-bit digest of the enrolled game's cid (binding/informational) |
| 11 `ggrant` | idx | grant per claim, raw units (0 = paused/removed) |
| 12 `gcap` | idx | max claims per epoch for this game |
| 13 `gpow` | idx | PoW target — claim needs `alghash(caller, idx, nonce) < gpow` |
| 20 `gused` | idx·2²⁰ + epoch | claims consumed this epoch (epoch = cursor / EPOCH_LENGTH, via divmodw) |
| — `claimed` | alghash(caller, idx) **as the raw slot key** | 1 once this address claimed for this game |

The `claimed` marker uses the full 64-bit hash as the storage key directly — no per-address maps
needed in a field-word VM. Collision odds for two (address, game) pairs are birthday-over-2⁶⁴
(≈10⁻⁸ even at a million claims); a collision merely denies one duplicate-looking claim, it can
never mint funds.

**Methods**

```
fund()                              value>0 — anyone can also top up straight on the exec layer
set_game(idx, dig, grant, cap, pow) deployer-only; grant=0 pauses; idx ≤ gcnt (append or edit)
claim(idx, nonce)                   the player path — checks in order:
                                      ggrant[idx] > 0                        (enrolled + granting)
                                      alghash(caller, idx, nonce) < gpow[idx] (proof of work)
                                      slot[alghash(caller, idx)] == 0          (first claim)
                                      gused[idx, epoch] < gcap[idx]           (epoch budget)
                                      balance ≥ grant                         (funded)
                                    then: mark claimed · gused++ · PAY caller ggrant[idx]
view maps                           gdig/ggrant/gcap/gpow/gused + gcnt for the hub/SDK to render
```

All ops used (`hash`, `divmodw`/`lo32`, `pay`, `ctx caller/cursor`, `arg`) exist and are
STARK-provable today; `claim` is comfortably within one proof like every game method.

## 6. Sybil resistance & drain economics

A grant is plain (withdrawable) exec balance — see §10 for why v1 does NOT build play-locked
credits — so the design must make farming uneconomical rather than impossible:

- **In-VM proof of work per claim.** The claim carries a ground nonce; the contract verifies ONE
  hash. Browsers grind with the existing `algHashn` in a worker. `gpow` is a per-game knob: target
  `2⁶⁴/2^k` costs ~2^k hashes; at k≈26-28 a laptop grinds tens of seconds to minutes per claim —
  fine once per game for a human, ruinous at farm scale for sub-NADO grants (electricity beats the
  grant well below current prices).
- **Once per (address, game)** — the `claimed` bit.
- **Per-epoch budget per game** (`gcap`): the worst-case drain rate is `Σ grant·cap` per epoch
  regardless of attacker effort — the operator sizes it to the donation inflow. Example: 8 games ×
  0.5 NADO × 20 claims/epoch-day ≈ 80 NADO/day ceiling.
- **Claim is a normal exec call**: L1 tx fee applies, at-most-once txid replay protection is free,
  and reorgs are handled the same way as every game move (finalized-only application).
- The PoW binds `caller`, so nonces can't be stolen from the mempool, and binds `idx`, so one grind
  can't be replayed across games.

## 7. Game integration ("support in the games themselves")

**SDK first** (per house rules — one implementation, every game inherits):

- `static/faucet.js` (or a nadodapp section): `faucetInfo(sto)` → enrolled games + my claim status
  (reads the faucet view maps with the game's own storage poll — one extra contract read);
  `grindClaim(idx, onProgress)` → web-worker PoW grind; `claimFaucet(idx, nonce)` → `dapp.call`
  against `FAUCET_CID` with the standard confirm lifecycle (`phase: "faucet"` return strings).
- **Enrolled game pages**: when signed in, enrolled, unclaimed, and `dapp.exec < minStake`, render
  the SDK claim bar: *"🚰 New here? Claim {amt} NADO of free play — takes a minute of your
  browser's time."* with grind progress and the usual landed/failed lifecycle. One shared i18n key
  set (`sdk.fct*`), 16 languages.
- **Hub** (`games.html`): a 🚰 badge on enrolled games' tiles.
- **Wallet**: a "donate to the faucet" row (one `construct_faucet_tx` — the bridge-deposit
  constructor with recipient `faucet`), so funding it is one tap too.

Games needing no contract change: the grant arrives as ordinary balance, so dice/roulette bets,
duel stakes, pot antes all just work. Per-game earmarking is economic (grant sized to that game's
minimum stake) + UX (the claim lives on that game's page), not enforced spending — see §10.

## 8. Funding sources

1. **Donations / operator top-ups** — the reserved address, day one.
2. **Exec-side `fund()`** — anyone with exec balance, day one.
3. **Treasury routing** — the L1 treasury already has `treasury_vote`/`treasury_execute`
   governance; a proposal type that pays the treasury→`faucet` is a natural follow-up and needs
   nothing from this design beyond the reserved address existing. NOT in v1.
4. **Protocol stream** (a slice of the anti-hoard burn or a dividend-style inflow) — explicitly out
   of scope; it's a monetary-policy decision, not a faucet feature.

## 9. Security & failure analysis

- **Drain ceiling** is `Σ grant·cap` per epoch by construction (§6) — a contract bug in `claim`
  can't exceed the contract's balance either way (`PAY` fails on insufficient funds).
- **No faucet withdrawal method.** The contract can only `PAY` through `claim`. The operator
  "recovers" funds only by upgrading the contract (a visible, deployer-signed act) — same trust
  level the games already run under. Add a `sweep` only if governance ever demands it; default no.
- **Reserved-name squatting**: the `--at faucet` deploy is allowlisted + operator-keyed (§4).
- **L1/exec supply accounting**: `FAUCET_ESCROW` on L1 mirrors the bridge convention — coins locked
  on L1, mobile on exec. Faucet grants are exec-side transfers of already-locked coins, so bridge
  solvency invariants are untouched (withdrawing a grant to L1 goes through the normal
  `bridge_withdraw` proof against the settled root, funded by the same escrow the donation locked).
- **Reorg/wedge**: donations and claims apply from FINALIZED blocks only, like everything else.
  (The 2026-07-16 exec orphaned-fork wedge is an orthogonal, known issue — nado-known-bugs.md.)
- **Grief via claimed-bit collision**: negligible probability, fails closed (denies, never pays).
- **PoW outsourcing**: someone can sell ground nonces, but the nonce binds the CLAIMER's address —
  they'd be buying their own grant at grind cost, which is the intended economics.

## 10. Non-goals in v1 (and the v2 sketch)

- **Play-locked credits** (grants spendable only inside the earmarked game) require either
  cross-contract calls (the zkVM has none) or a faucet-owned sub-ledger that every game contract
  learns to debit — a coordinated upgrade of all 18 games. V2 sketch if farming ever bites despite
  §6: faucet stores `credit[caller]`; each enrolled game adds a `freeopen/freebet` method that
  requires an operator-cosigned voucher arg... revisit only with evidence.
- **KYC-ish gating** (registration age, mined-presence requirement): the exec VM can't read L1
  account state; the PoW gate approximates "cost per identity" without new plumbing.
- **Auto-enrollment**: the list stays operator-curated; that IS the product decision the user
  asked for ("upgradable contract with a list of games").

## 11. Implementation plan

| # | change | files | test |
|---|---|---|---|
| 1 | L1 reserved recipient + escrow + reflect | protocol.py, ops/transaction_ops.py (validate + `construct_faucet_tx`), ops/account_ops.py | unit: validate/reflect/revert symmetry; reserved-recipient block tests |
| 2 | exec credit branch + `FAUCET_CID` | execnode/execnode.py | tail-replay test crediting the cid |
| 3 | fixed-name deploy `--at faucet` (allowlisted) | execnode/games/deploy.py, execnode registry | deploy + upgrade-in-place test |
| 4 | faucet contract | execnode/games/faucet.py | test_games_e2e style: set_game/claim happy path, PoW reject, double-claim reject, epoch-cap reject, pause, underfunded, upgrade keeps storage; `claim` proves |
| 5 | SDK + game/hub/wallet UX + i18n | static/faucet.js (or nadodapp section), enrolled game pages, games hub, interface.js donate row, i18n_games/sdk.json ×16 | CDP smoke: claim bar renders, grind worker completes, lifecycle strings |
| 6 | live E2E | _faucet_e2e.py | donate on L1 → exec credit → claim from a fresh key → stake it in an enrolled game |
| 7 | fleet deploy | — | L1 change ships fleet-wide at once (consensus); then contract deploy; then clients |

Rollout order matters: L1 fleet update → contract deploy at `faucet` → enroll games → ship client
UX. Each step is independently inert for old software (unknown recipient rejected at mempool;
missing contract renders no claim bar).

## 12. Open questions (operator decisions, not blockers)

1. Grant sizes / PoW difficulty / epoch caps per game (suggest: grant ≈ 2-3× the game's min stake,
   k=26, cap 20/epoch-day to start).
2. Should the wallet's donate row suggest an amount (dust roundups?)
3. Treasury routing proposal — wanted now or later?
4. Epoch granularity for budgets: raw `EPOCH_LENGTH` (60 blocks ≈ 6 min) is too fine for "daily"
   budgets — use `cursor / 14400` (~day at 6s) as the budget window instead. (Doc default: daily.)
