# Assets — a second value type on the exec layer

> **Status: BUILT and usable — ledger, opcodes, proofs, blob ops, and the wallet UI.** The asset ledger,
> the six zkVM opcodes, the blob ops, state-root commitment and the execution AIR are implemented and
> tested (`tests/test_assets.py`, now 29 checks including real proofs); the wallet's Assets tab
> (`static/interface.html`/`interface.js`) issues, sends, mints, burns, renounces, approves/transfers-from
> and hosts the Reserve vault UI (`doc/reserve.md`). Asset *calls* settle both by the bonded quorum AND by
> validity proof (§8), a contract can seal its own token's supply in-circuit (`ARENOUNCE`, §3), and delegated
> spend (approve/allowance/transferFrom, §7a) and a metadata URI are in the ledger. Feature parity against
> modern token standards — present, deliberately omitted, or reasoned out — is surveyed in §9.

Until now the exec layer knew exactly one kind of value: native NADO, held in `ExecState.bridge`. Every
contract — 21 of them — could only ever move that. This note specifies the second: **fungible assets**,
created by anyone, held by anyone (including contracts), and moved with the same solvency discipline
native NADO already has.

Why it comes first in [`ROADMAP.md`](../ROADMAP.md): launchpads, AMMs, routers, wallet swaps and trading
terminals are all downstream of *having something to trade*. None of them is a hard problem once assets
exist; none of them is possible before.

---

## 1. The one design decision

Two ways to add tokens to a chain that already has a contract VM:

| | contract standard (ERC-20 shape) | **state-level ledger** (chosen) |
|---|---|---|
| where balances live | inside one contract's storage, one contract per asset | one ledger in exec state, all assets |
| consensus change | none | new state field + ops + root leaves |
| composability | contract must call contract | a contract holds assets natively, like NADO |
| wallet/explorer support | must index every token contract | one endpoint |
| an AMM swapping A for B | two cross-contract calls, two failure modes | one state transition |

We took the **state-level ledger**. The deciding argument is that this is cheap now and expensive later:
retrofitting a canonical ledger after liquidity has settled into a hundred mutually incompatible token
contracts is the migration nobody survives. The secondary argument is that `doc/dex-bridge.md` §7 already
specifies the "atomic VM swap" as *one deterministic transaction moving both legs* — which is only
straightforward if both legs are in one ledger.

Cost paid: `ExecState` gained two fields, the root gained three record tags, and the VM gained six opcodes.

---

## 2. The ledger

```
ExecState.assets = { str(asset_id): {issuer, seed, name, sym, dec, supply, mintable} }
ExecState.abal   = { str(asset_id): { holder: balance } }        # holder = an L1 address OR a cid
```

Both are committed in `state_root` via `exec_root.records_projection` — `T_ASSET_BAL` binds
(asset, holder) → balance, `T_ASSET_META` binds a digest of the asset's metadata. So "this asset's supply
is fixed at N" and "this address holds M of it" are both **provable against the settled root** by the same
bounded verifier that already proves bridge balances. An asset is not a database row somebody promised you.

Rules the ledger keeps, in the code and in the tests:

- **`supply == sum(balances)`**, always. Every op that touches one touches the other.
- **Absence == zero.** A balance that reaches 0 is deleted, and an asset nobody has ever held reads 0
  rather than raising. Two nodes with the same balances must commit the same root, so there is exactly one
  representation of "nothing".
- **`ASSET_SUPPLY_CAP = 2^62`.** Not arbitrary: every balance is ≤ supply, and the VM's `RANGE` window is
  2^62, so this is what keeps an in-contract `lt` on an asset amount *sound*. A bigger supply would make
  comparisons on balances silently forgeable — the exact bug class the compare-macro discipline exists to
  prevent.
- **No exit to L1.** An asset exists on this layer only. There is no `asset_withdraw`; the bridge machinery
  is for NADO.

### The id is derived, never assigned

```
asset_id = alghash.hashn([ zkvm_addr_digest(issuer), seed ])
```

Consequences, and this is the part that makes the rest of the roadmap buildable:

1. An issuer knows the id **before** creating the asset.
2. A **contract can compute the id of its own assets in-circuit**, with the ordinary `hash` macro:
   `hash aid <- me 1`. No registry lookup, no oracle, nobody passing it an id it has to trust. That is
   precisely what an AMM needs to own its LP token and a launchpad needs to own the token it launches.
3. Ids are field elements, so they fit in a register and travel as ordinary call args.

---

## 3. The six opcodes

Appended to `zkvm.OPS` (ids are frozen once contracts deploy against them; appending never shifts an
existing id).

| op | form | effect | io entry |
|---|---|---|---|
| `ASEL` | `asel rs` | select asset `rs` for the **next** instruction | `(IO_ASEL, asset, 0)` |
| `AMINT` | `amint rd rs` | mint `rs` of the selected asset to digest `rd` | `(IO_AMINT, to, amt)` |
| `ABURN` | `aburn rd rs` | burn `rs` of asset `rd` from **self** | `(IO_ABURN, asset, amt)` |
| `ABAL` | `abal rd rs` | `rd` = self's balance of asset `rs` | `(IO_ABAL, asset, bal)` |
| `ACTX` | `actx rd i` | `i=0` → the asset escrowed with this call, `i=1` → self's digest | — (context) |
| `ARENOUNCE` | `arenounce rd` | seal asset `rd`'s supply — self renounces its own mint (issuer-checked) | `(IO_ARENOUNCE, asset, 0)` |

`PAY` is unchanged, and gains a meaning: **`PAY` immediately after an `ASEL` moves that asset instead of
NADO.** A bare `PAY` is native NADO exactly as before, so all 21 existing contracts are untouched.

### zkasm, and why only macros are exposed

```
apay  <asset> <to> <amt>      ; ASEL asset ; PAY to amt
amint <asset> <to> <amt>      ; ASEL asset ; AMINT to amt
aburn <asset> <amt>
abal  d <asset>
actx  d asset|self
arenounce <asset>            ; seal SELF's own asset supply (issuer-checked at settle)
```

zkpy: `m.apay(...)`, `m.amint(...)`, `m.aburn(...)`, `m.arenounce(a)`, `m.abal(a)`, `m.in_asset()`, `m.me()`.

There is deliberately **no way to write a bare `asel` in zkasm.** See §4.

---

## 4. The pairing rule (the sharp edge, and the two places it is enforced)

An asset move needs three values — asset, recipient, amount — and a zkVM instruction carries two registers.
Hence `ASEL` publishes the asset and the very next instruction spends it.

That is only safe if the pairing is **atomic**. The failure it prevents:

> A jump lands directly on the `PAY`. There is no live selection, so the `PAY` moves **native NADO**
> where the contract meant to move a token. Both the `ASEL` entry and the `PAY` entry are individually
> well-formed, so nothing downstream can tell the two apart — the log is a perfectly valid description of
> a transaction the contract never intended.

This is the same shape as the existing `RANGE ; RANGE ; LT` rule (a jump into a compare macro skipping a
range check), and it is enforced the same way, in **two** independent places:

1. **`zkvm.validate_code`, at the deploy gate** — every `ASEL` must be immediately followed by `PAY` or
   `AMINT`, no jump may target that follower, and every `AMINT` must be preceded by an `ASEL`. This covers
   all bytecode, including hand-crafted JSON that never went through the assembler.
2. **`zkvm.replay_io`, in the verifier** — because replay verifies a *log*, not a program. A log arriving
   from a stranger gets the identical pairing check before any effect is derived from it.

Plus one interpreter guard: **`ASEL` of asset `0` reverts.** Asset 0 means "native", so selecting it is the
substitution the rule exists to prevent; the VM refuses rather than quietly paying NADO.

### Fail-closed replay

`replay_io(log, storage)` **rejects** any log containing an asset entry. Asset settlement requires
`with_assets=True`, which returns a sixth element — the ordered effects. A verifier that silently dropped
the asset half of a log would be confirming a state transition it had not checked; opting in is how a
caller states it can actually settle them.

---

## 5. Authority

- **Only the issuer mints**, and only while `mintable`. Checked in `ExecState.stage_asset_effects` against
  the ledger's `issuer` field — *not* against the derivation. When the issuer is a contract, see §7 for
  who may create and renounce (the deployer) versus who may mint and move (the code, and only the code). Ids are public, so a hostile contract can
  name your asset id perfectly well; what stops it is the issuer field. (Both attacks are tested.)
- **`mintable` defaults to `false`.** A fixed-supply asset is the default, not the special case.
- **`asset_renounce` is one-way and permanent**, exactly like `lock` on a contract. After it, supply can
  only ever fall.
- There is no freeze authority, no blacklist, no clawback, and no admin transfer. There is nowhere to add
  one: the ledger has no privileged path, and `stage_asset_effects` is the only writer.

---

## 6. Calls denominated in an asset

```json
{"op": "call", "contract": "<cid>", "method": "swap", "args": [...], "value": 250, "asset": "<asset_id>"}
```

`asset` names *which* value `value` is. Absent or `0` = native NADO. The amount is escrowed from the
caller's asset row into the contract before the method runs, and **refunded exactly on revert** — the same
guarantee native call value has. The contract reads the amount through `CTX_VALUE` either way and only has
to consult `ACTX_ASSET` when it cares which currency arrived.

**Atomicity across both ledgers.** A call's native payouts and its asset effects commit together or not at
all: the asset half is staged and fully validated (`stage_asset_effects`) before anything is written, so a
call that pays three assets and overdraws the fourth moves none of them, and its NADO payouts do not land
either.

---

## 7. Blob ops (the user-facing half)

| op | payload | notes |
|---|---|---|
| `asset_create` | `seed, name, sym, dec, supply, mintable`, opt `uri`, opt `for` | sender is the issuer; initial supply credited to the issuer. `for: <cid>` makes a CONTRACT the issuer — see below |
| `asset_transfer` | `asset, to, amount` | |
| `asset_mint` | `asset, to, amount` | issuer only, mintable only |
| `asset_burn` | `asset, amount` | from sender's own holding |
| `asset_renounce` | `asset` | issuer only, permanent |
| `asset_set_uri` | `asset, uri` | issuer only; reversible (metadata pointer, not a supply promise) |
| `asset_approve` | `asset, spender, amount` | owner authorises a spender; OVERWRITES, 0 revokes (§7a) |
| `asset_transfer_from` | `asset, from, to, amount` | spender moves owner→to, gated by allowance AND balance (§7a) |

Read endpoints: `GET /exec/assets` (registry; `?issuer=`, `?holder=` filters — a wallet renders its whole
token list in ONE request, per the full-storage-per-poll rule) and `GET /exec/asset?id=`.

An asset created by a person and one created by a contract are indistinguishable afterwards. There is no
system-asset concept and no allowlist.

### Contract-issued assets, and why they need a `for`

A contract **cannot submit a blob**: a blob's sender is an L1 address derived from a pubkey, and a cid is a
32-hex hash, so no transaction can ever carry `sender == cid`. Taking the issuer from the sender therefore
made it impossible for a contract to *be* an issuer — which would have left `AMINT` unreachable in
production and the entire point of in-circuit derived ids ("an AMM owns its LP token") a dead letter. It
looked like it worked only because the test faked the sender.

So `asset_create` takes an optional `for: <cid>`, authorised to that contract's **deployer**. They already
control the code, so it grants no new power. What matters is the split it creates, and it is worth stating
as a rule:

| | create | renounce | mint | move the contract's holdings |
|---|---|---|---|---|
| the contract's **deployer** | ✅ | ✅ | ❌ | ❌ |
| the contract's **code** | ❌ | ❌ (needs an opcode) | ✅ `AMINT` | ✅ `ASEL`+`PAY` / `ABURN` |
| anyone else | ❌ | ❌ | ❌ | ❌ |

`asset_mint`, `asset_transfer` and `asset_burn` all act as `sender`, and the issuer is the *cid*, so the
deployer is refused by the ordinary issuer check — no special case was needed to keep them out. Initial
supply is credited to the **issuer**, not the sender: crediting the deployer would hand them free units of
a token the contract is supposed to own, which is the rug this layer exists to prevent.

Renouncing is the deployer's for the same reason creation is, and it is safe to grant because renouncing
only ever *removes* power. A contract can ALSO renounce **autonomously**, in-circuit, via the `ARENOUNCE`
opcode (§3): a launchpad sealing its token's supply at graduation emits `arenounce aid`, and the exec layer
applies `mintable=False` after checking self==issuer — the same authority rule as a blob renounce, so the
two paths cannot diverge. One-way and permanent, exactly like the blob form.

### 7a. Delegated spend (approve / allowance / transferFrom)

`allow[asset][owner][spender] → amount`, committed under `T_ASSET_ALLOW` and provable like a balance.
`asset_approve` sets it (ERC-20 semantics: it OVERWRITES rather than accumulates, 0 revokes, and there is no
balance check — an allowance is a ceiling, not a promise the tokens are there). `asset_transfer_from` spends
it, and passes **two independent gates**: the standing allowance and the owner's *live* balance, decrementing
the allowance by exactly what moved. Absence == zero throughout, so a revoked and a never-set allowance are
indistinguishable and both pruned — two nodes with the same authorizations commit the same root. Read via
`GET /exec/allowances` (`?owner=` for grants you made, `?spender=` for grants made to you).

The `spender` is any identity string — an address (a custodian or keeper spending on your behalf) or a cid.
Note what this does and does not enable: it is complete for account-to-account delegation, but a *contract*
cannot yet consume an allowance in-circuit — see §9 item 3 for why that (`APULL`) is deliberately left to
call-value escrow rather than built.

---

## 8. Settlement by validity proof — CLOSED

Asset calls are settled by the **bonded quorum** (the path that settles everything else) AND, now, by
**validity proof**. The gap this section used to describe — `settlement_proofs._run_call` carried only a
shadow `bridge`, so an `ASEL`+`PAY` looked to it like a native payout and it *refused* asset io — is closed.

The epoch prover now carries an **asset half of the shadow ledger** (`abal`/`assets`), symmetric to the
native `bridge`: `_run_call` escrows an asset-denominated call value, threads the contract's balances into
the VM, splits the io log into native payouts vs asset effects through the shared `runtimes.split_io`, and
stages those effects against the shadow. `verify_epoch`'s replay opts into `with_assets=True`. The AIR
needed **nothing** — it already proves the io log that carries every asset effect.

The rule that makes this sound: the VM/AIR enforces only *holder-side solvency* (a contract can't pay or
burn more than it holds). **Mint authority** — issuer-only, mintable-only, the supply cap — lives in
`stage_asset_effects`, and the shadow calls the **exact same function** the live apply path does
(`stage_asset_effects_pure`, extracted so the two can never diverge). So the prover can never prove a mint
the chain would reject. `tests/test_assets.py` pins this with the authority test: the VM emits a well-formed
`AMINT` for a victim's asset or a renounced one, and the prover **raises** because the shadow refuses it —
the assertion that fails the instant the two paths drift.

**No consensus/root impact.** The settlement proof's `post_root` binds contract STORAGE only; asset balances
live in the records half (`T_ASSET_BAL`/`T_ASSET_META`/`T_ASSET_ALLOW`) that this proof does not bind. The
shadow gates the proof (so it never proves a transition the chain reverts-and-refunds) but never enters any
root — exactly like the native `bridge` shadow always has.

The per-call `/exec/prove_call` + `/exec/verify_call` pair already handled assets and is the template this
followed: the proof binds `ACTX_ASSET` and `ACTX_SELF` as public columns (`selfd` is *derived from the cid*
on both sides, so a prover cannot choose what a contract thinks its own address is), and verify re-checks
every `ABAL` read and declared move against the node's ledger before reporting `state_match`.

---

## 9. Feature parity with modern token standards

These are not ERC-20 contracts, so the comparison is by *capability*, not by ABI. Measured against ERC-20
and the extensions people actually expect, here is where NADO assets stand — including, honestly, where they
do not.

**Present.** transfer · balanceOf · totalSupply · name / symbol / decimals (bounded: sym ≤ 12, name ≤ 64,
dec 0–18) · **mintable** (issuer-gated, opt-in, off by default) · **burnable** (holder-side) · **fixed
supply by default** with a hard cap (`ASSET_SUPPLY_CAP = 2^62`) · **renounce minting** (one-way, permanent) ·
**metadata URI** (a bounded logo/details pointer, issuer-updatable, committed in the root) · **approve /
allowance / transferFrom** (delegated spend — `asset_approve` + `asset_transfer_from`, committed under
`T_ASSET_ALLOW`, read via `/exec/allowances`). Every balance, allowance and the metadata are **provable
against the settled root** (§2) — stronger than an ERC-20, whose balances are only as good as one contract's
storage.

**Ahead of the standard**, because the ledger is native rather than a contract:

- **A contract holds assets directly** — no `WETH`-style wrapper. An AMM owns its LP token; a vault holds
  what it backs (`doc/reserve.md`).
- **Atomic call-value escrow** (§6) — you send tokens *with* a call, escrowed and refunded-on-revert in one
  step. This is the ERC-1363 "transferAndCall" idea, built in and atomic, and it removes the main reason
  `approve`/`transferFrom` exists (see below).
- **Contract-issued assets with in-circuit id derivation** (§2, §7) — `hash aid <- me seed`, no registry,
  no oracle. A launchpad can own the token it launches.
- **Atomic multi-asset settlement** (§6) — one call moving several assets commits all-or-nothing across both
  ledgers.

**Deliberately omitted — a decentralization property, not a gap** (§5): no freeze, no blacklist, no
clawback, no admin transfer, no pause. There is nowhere to add one — `stage_asset_effects` is the only
writer and the ledger has no privileged path. A holder's balance cannot be touched by anyone but the holder.
This is a stronger trust story than most tokens ship, and it is intended to stay that way.

**Remaining gaps, with a reasoned disposition** (not everything on this list should be built — where the
answer is "no", the reason is the deliverable):

1. **Proof settlement for asset calls** (§8) — **DONE.** The epoch prover carries an asset shadow and settles
   asset-touching calls by validity proof, gated by the same `stage_asset_effects_pure` the chain applies, so
   authority can never drift between apply and proof. Changed no committed root.
2. **`ARENOUNCE` opcode** (§3, §7) — **DONE.** A contract seals its own token's supply in-circuit; the exec
   layer applies it through the same authority check as a blob renounce, and the AIR constrains the new io
   (a differential prove/replay/forgery test pins the soundness). A coordinated update, since it is a VM
   opcode.
3. **`APULL` — a VM opcode letting a CONTRACT consume an allowance — deliberately NOT built.** The
   account-level `approve`/`transferFrom` above covers a person/keeper spending on another's behalf. The
   remaining case, a contract *pulling* pre-authorised tokens, is already served better by call-value escrow
   (§6): the user pushes tokens *with* the call, atomically and refunded-on-revert, so there is nothing to
   pre-authorise and no standing-approval attack surface. Adding a pull opcode would duplicate a stronger
   mechanism on consensus-critical code. If a genuine pull-across-transactions need appears (a keeper
   contract acting while the user is absent), the design is a straight parallel to `APAY`: `ASEL asset ;
   APULL owner amount`, staged against `allow[asset][owner][self]`.
4. **Snapshots / vote-checkpointing (ERC-20Votes-style) — deferred by design.** Checkpointing every balance
   at every block is a standing storage cost, and building it speculatively before a governance token exists
   would be the wrong commitment. When one is needed, the clean shape is an opt-in per-asset flag that
   records `(holder, block) → balance` deltas in a committed side-map, queried by `/exec/asset_balance_at`.
5. **Permit (EIP-2612) — not applicable, on purpose.** Permit exists so a third party can submit *your*
   approval without you paying gas. On NADO a signature already *is* the transaction, and `asset_approve` is
   an ordinary signed blob anyone may relay — so the mechanism permit adds is already the default. There is
   nothing to build.

Not planned, and mostly on purpose: fee-on-transfer and rebasing (transfers are exact, with no holder-side
hook — usually an anti-feature); ERC-1155-style multi-token ids (each asset is already one row in one
ledger, so the composability 1155 buys is native here); flash-mint.

## 9a. What this unlocks

A contract can **hold** assets, **receive** them as call value, **read** its own balance, **pay** them out
under a solvency rule, and **mint/burn its own** asset whose id it derives in-circuit — the complete
primitive set an AMM pool, a bonding-curve launchpad, and an LP token need. The wallet already issues and
moves assets and runs the Reserve vault. Still ahead: an **explorer** (asset pages, holders, supply) and the
**apps** — AMM, launchpad, router (`ROADMAP.md` phases 2–4).

---

## 10. Files

| what | where |
|---|---|
| opcodes, io kinds, pairing gate, replay | `execnode/zkvm.py` |
| AIR columns + constraints | `execnode/stark/vm_circuit.py` |
| assembler macros | `execnode/zkvmasm.py` |
| DSL wrappers | `execnode/zkpy.py` |
| ledger, blob ops, staged settlement | `execnode/state.py` |
| io → effects, address resolution | `execnode/runtimes.py` |
| root commitment | `execnode/exec_root.py` |
| read endpoints | `execnode/execnode.py` |
| tests | `tests/test_assets.py` |
