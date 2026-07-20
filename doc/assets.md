# Assets — a second value type on the exec layer

> **Status: BUILT (ledger + opcodes + proofs), with two named gaps.** The asset ledger, the five zkVM
> opcodes, the blob ops, state-root commitment and the execution AIR are implemented and tested
> (`tests/test_assets.py`, 16 checks including one real proof). **Not** yet built: settlement BY PROOF for
> asset calls (§8), and the wallet UI (§9). Both are called out explicitly below rather than glossed.

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

Cost paid: `ExecState` gained two fields, the root gained two record tags, and the VM gained five opcodes.

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

## 3. The five opcodes

Appended to `zkvm.OPS` (ids are frozen once contracts deploy against them; appending never shifts an
existing id).

| op | form | effect | io entry |
|---|---|---|---|
| `ASEL` | `asel rs` | select asset `rs` for the **next** instruction | `(IO_ASEL, asset, 0)` |
| `AMINT` | `amint rd rs` | mint `rs` of the selected asset to digest `rd` | `(IO_AMINT, to, amt)` |
| `ABURN` | `aburn rd rs` | burn `rs` of asset `rd` from **self** | `(IO_ABURN, asset, amt)` |
| `ABAL` | `abal rd rs` | `rd` = self's balance of asset `rs` | `(IO_ABAL, asset, bal)` |
| `ACTX` | `actx rd i` | `i=0` → the asset escrowed with this call, `i=1` → self's digest | — (context) |

`PAY` is unchanged, and gains a meaning: **`PAY` immediately after an `ASEL` moves that asset instead of
NADO.** A bare `PAY` is native NADO exactly as before, so all 21 existing contracts are untouched.

### zkasm, and why only macros are exposed

```
apay  <asset> <to> <amt>      ; ASEL asset ; PAY to amt
amint <asset> <to> <amt>      ; ASEL asset ; AMINT to amt
aburn <asset> <amt>
abal  d <asset>
actx  d asset|self
```

zkpy: `m.apay(...)`, `m.amint(...)`, `m.aburn(...)`, `m.abal(a)`, `m.in_asset()`, `m.me()`.

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
  the ledger's `issuer` field — *not* against the derivation. Ids are public, so a hostile contract can
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
| `asset_create` | `seed, name, sym, dec, supply, mintable`, opt `for` | sender is the issuer; initial supply credited to the issuer. `for: <cid>` makes a CONTRACT the issuer — see below |
| `asset_transfer` | `asset, to, amount` | |
| `asset_mint` | `asset, to, amount` | issuer only, mintable only |
| `asset_burn` | `asset, amount` | from sender's own holding |
| `asset_renounce` | `asset` | issuer only, permanent |

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
only ever *removes* power. The gap that remains: a contract cannot renounce **autonomously** — a launchpad
sealing its token's supply at graduation needs an `ARENOUNCE` opcode, which does not exist yet.

---

## 8. Settlement — the honest gap

Asset calls are settled today by the **bonded quorum**, the same path that settles everything else.

They are **not** yet settleable **by validity proof**. `settlement_proofs._run_call` carries a shadow
`bridge` and nothing else, and to that loop an `ASEL`+`PAY` pair is indistinguishable from a native
payout — proving it would move NADO where the contract moved a token. So it **raises** on asset io rather
than proving something false. That refusal is tested.

Closing it means giving the epoch prover an asset half: a shadow `abal`, the issuer/mintable checks
inside `_run_call`, and `verify_epoch`'s replay opting into `with_assets=True`. The AIR needs nothing more
— it already proves the io log that carries every asset effect, which is why the differential test
(interpreter == proof == replay) passes for a call using all five opcodes.

The `/exec/prove_call` + `/exec/verify_call` pair **does** handle assets: the proof binds `ACTX_ASSET` and
`ACTX_SELF` as public columns (`selfd` is *derived from the cid* on both sides, so a prover cannot choose
what a contract thinks its own address is), and verify re-checks every `ABAL` read and every declared move
against the node's ledger before reporting `state_match`.

---

## 9. What this unlocks, and what is still missing

Built and usable now: a contract can **hold** assets, **receive** them as call value, **read** its own
balance, **pay** them out under a solvency rule, and **mint/burn its own** asset whose id it derives
in-circuit from its own digest. That is the complete primitive set an AMM pool, a bonding-curve launchpad,
and an LP token need.

Still missing before any of that is a product:

- **Wallet UI** — asset list, balances, send/receive. The blob ops and read endpoints exist; nothing in
  `static/interface.html` uses them yet.
- **Explorer** — asset pages, holders, supply.
- **Proof settlement for asset calls** (§8).
- **The apps themselves** — AMM, launchpad, router (`ROADMAP.md` phases 2–4).

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
