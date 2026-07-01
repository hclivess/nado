# Aliases — send to a name, not a hash

A human-readable **alias** maps to an owner **address**, so a user can send to `alice` instead of the
49-char `ndo…` address. It is a first-class, on-chain, consensus-critical feature (not a client-side
address book).

## Names
- 3–32 chars, lowercase `[a-z0-9_-]`, must **start with a letter**.
- Must **not** be a reserved word (`bond`, `register`, `alias`, …) and must **not** start with `ndo`
  (so an alias can never be mistaken for an address).
- Global, first-come namespace.

Constants: `ALIAS_MIN_LEN = 3`, `ALIAS_MAX_LEN = 32`, `ALIAS_REGISTRATION_FEE = 10_000_000` (0.001 NADO).

## The three ops (reserved recipient `alias`)
An alias op is an ordinary signed tx whose `recipient` is the reserved name **`alias`**, `amount` is 0,
and whose `data` carries the operation:

| op | `data` | who | fee | effect |
|----|--------|-----|-----|--------|
| `register` | `{op, name}` | anyone (name must be free) | `ALIAS_REGISTRATION_FEE` (anti-squat) | sender becomes owner |
| `transfer` | `{op, name, to}` | the current owner | `MIN_TX_FEE` | owner → `to` |
| `unregister` | `{op, name}` | the current owner | `MIN_TX_FEE` | name freed |

Validation (`ops/alias_ops.validate_alias_op`) and application (`apply_alias`) are in
`ops/alias_ops.py`; the fee is destroyed like any other. In-block uniqueness (`reserved_uniqueness_key`)
allows **one alias op per name per block**.

## Sending to an alias (resolution)
An **ordinary transfer whose recipient is a registered alias** credits the alias's **current owner** at
apply time (`account_ops.reflect_transaction` resolves it; `validate_transaction` accepts a registered
alias as recipient, and rejects an unregistered/invalid one). A plain address or reserved word is not an
alias and is credited/handled as before.

## Revert-symmetry (no side record)
Rollback restores the exact prior mapping without any extra bookkeeping, because the prior state is
derivable from the tx: `register` only succeeds on a **free** name (revert = delete); the tx `sender` is
always the **prior owner** for `transfer` (revert = put back to sender) and `unregister` (revert = put
back to sender). Reverts are **LIFO**, so a send-to-alias reverting alongside a transfer/unregister sees
the same registry state it saw on apply → resolution is consistent.

## Storage & API
- KV: an `aliases` sub-DB (`name → owner`), with `alias_get / alias_put / alias_del / aliases_of`.
- Endpoints: **`/resolve_alias?name=`** → `{name, owner}` (owner `null` if unregistered);
  **`/get_aliases_of?address=`** → `{address, aliases[]}`.
- Client builder: `transaction_ops.construct_alias_tx(keydict, op, name, target_block, fee, to=None)`.

## Clients
The **browser light-miner** accepts an alias name in the Send field (resolves + shows `alias (→ ndo…)`
for confirmation) and has an **Aliases** card (Receive tab) to register / transfer / unregister and list
the names you own. `tests/test_alias.py` covers register, dup-reject, resolution, transfer, owner-only,
unregister, name validation, and revert of all three ops.
