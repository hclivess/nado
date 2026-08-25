# Account authentication — keep the address, change the keys

Design proposal, 2026-08-25 (revised the same day after reviewing Monad's
[Flexible and Upgradeable Account Authentication](https://forum.monad.xyz/t/flexible-and-upgradeable-account-authentication/526)
MIP — see §11). Not implemented. Status: **architecture for review**.

**Framing.** Account abstraction in its smallest useful form: an address stops being "the hash of one key"
and becomes an **account whose authentication policy is state**. The policy says which keys may *spend*
and which keys may *change the policy*; rotation and recovery are then not special mechanisms but
ordinary policy changes. The design abstracts authentication only — not programmability — and caps
the policy language hard, because on a 6-second block every signature verified is per-block CPU.

## 0. What is true today

An address *is* its key. `make_address(pubkey)` = the first 42 hex of the ML-DSA public key + a 4-hex
checksum (`ops/address_ops.py`), and **every** authorization path re-derives that binding:

| path | check |
|---|---|
| transaction (`validate_origin`, `ops/transaction_ops.py`) | `proof_sender(pubkey, sender)` — the key must hash to the sender — then ML-DSA verify over the txid |
| block winner signature (`verify_block_signature`, `ops/block_ops.py`) | `proof_sender(pubkey, block_creator)` |
| attestation / duty / reveal / slash / treasury txs | the same `validate_origin` |
| detached auth evidence (`resolve_sender_pubkey`) | the pubkey stored on the account doc by PUBKEY-ONCE |

PUBKEY-ONCE stores the full public key on the account doc at the address's first transaction
(`public_key`, revert-journaled in `pubkey_revert`); later transactions may omit it and the node
recovers it from state. That is a *cache of the one key the address was derived from*, not a binding
that can move.

Consequence: a new key is a new address, and a new address loses everything keyed by the old one —
bonded stake and its ramp (`bond_since`), fidelity and the recert streak, the presence lease, aliases,
treasury votes, exec-layer state (bridge balance, game positions, dividend accrual, `zk_addrs`), and
the messaging identity. There is no way to recover a compromised key today, and no way to rotate
proactively without starting over.

## 1. Goals and the one non-goal

Goals:
1. **Rotate the keys of an existing address** — proactively (hygiene, a new device) or reactively
   (compromise) — keeping the address and everything keyed by it.
2. **Recovery from a stolen hot key**, when the owner prepared for it.
3. No change to how addresses look, how *new* accounts derive them, or how anything references them
   (aliases, contracts, exec state, the wallet's HD derivation).

Not a goal: post-quantum migration (NADO is ML-DSA already — the strongest motivation in the Monad
MIP simply does not apply here), programmability, or multi-scheme support.

The non-goal, stated up front because every rotation design is measured against it:

> **A stolen key with no prior preparation cannot be reclaimed by any protocol rule.** The thief holds
> exactly what the owner holds. Any op the owner can sign, the thief can sign first, and a "cancel"
> the owner can sign, the thief can sign too. Delays only turn the race into a war of resubmission.
> The only asymmetry a protocol can enforce is one the owner created *before* the theft.

The policy formulation below is how that asymmetry is expressed: a **reconfiguration policy that no
single key satisfies**.

## 2. The auth config

An account may carry an `auth_config`:

```
auth_config = {
  "version":        <int>,                 # config_version: bumped on every effective change (replay guard)
  "authenticators": [ <pubkey>, ... ],     # ML-DSA public keys, indexed 0..n-1; n <= AUTH_MAX_KEYS
  "signing":        <policy>,              # who may spend / act for the address
  "reconfig":       <policy>,              # who may change this config
}
policy := ["ID", i]                        # authenticator i signed
        | ["THRESHOLD", k, [policy, ...]]  # at least k of the sub-policies hold
```

- **Absent config = legacy account** = `{authenticators: [derived key], signing: ID(0), reconfig: ID(0)}`.
  No migration, no root change for any existing account: the implicit default is *computed*, never
  stored, exactly as PUBKEY-ONCE's stored key is today. An address whose first transaction carries a
  config is born with it.
- **Bounds are consensus rules**: `AUTH_MAX_KEYS = 4`, `THRESHOLD` nesting depth ≤ 2, `k ≥ 1`. A policy
  is satisfied by a *set of valid signatures*; a transaction pays for every signature it presents, and
  the evaluator refuses more than `AUTH_MAX_KEYS` signatures outright. Single-key accounts (all of them
  today) cost exactly what they cost now: one verify.
- **Only ML-DSA.** One scheme, one verifier, one per-signature cost. Scheme agility is what the Monad
  design spends most of its complexity on; we have no need for it.

The two policies are the whole idea. `signing` is what a thief with the hot key gets. `reconfig` is
what it takes to change the keys — and if `reconfig` is not satisfiable by the hot key alone, the thief
can spend the liquid balance but **cannot take the account**. Recovery is not a separate mechanism: it
is whatever `reconfig` says.

The wallet ships two presets and never exposes the policy language:

| preset | authenticators | signing | reconfig | meaning |
|---|---|---|---|---|
| **single key** (default today) | `[hot]` | `ID(0)` | `ID(0)` | legacy behaviour |
| **protected** | `[hot, recovery]` | `ID(0)` | `THRESHOLD(2, [ID(0), ID(1)])` | spend with the hot key; changing keys needs hot **and** recovery |

"Protected" is the recommendation for anyone with bonded stake or a fidelity streak. The recovery key
is a **separate 24-word phrase**, shown once, never stored with the hot seed, and it can never spend.
A guardian variant — `reconfig = THRESHOLD(1, [ID(0), THRESHOLD(2, [ID(2), ID(3)])])` with two friends'
current keys as 2 and 3 — is expressible in the same language and needs no new code; whether to offer it
is a product decision (§10).

## 3. State

| where | what |
|---|---|
| account doc (in `accounts`, already inside the L1 state root) | `auth_config` (absent = legacy); `auth_pending = {config, effective, by}` — at most one pending change; `auth_freeze` — height until which self-initiated changes are refused |
| new dupsort sub-DB `auth_history` (in `SNAPSHOT_DBS`, inside the root) | `address -> (height, config_version, authenticators)` for every config that ever authorized the address — evidence against a **past** state (an equivocation proof for a block signed under the old keys must still verify after they moved). Bounded by `AUTH_HISTORY_KEEP` (older evidence is beyond the finality floor anyway) |
| revert journal `auth_revert` (outside the root, like `pubkey_revert`) | keyed by txid: the exact prior `(auth_config, auth_pending, auth_freeze)` and the history row added, so `rollback_one_block` is a byte-exact inverse — the block-4260 lesson |

## 4. The single authorization primitive

Every `proof_sender(pubkey, sender)` call site becomes:

```python
def authorized(sender, sigs, message, at_height=None) -> bool:
    """sigs = [(authenticator_index, signature), ...]. True iff the set of authenticators whose ML-DSA
    signature over `message` verifies satisfies sender's SIGNING policy (its config at at_height, if given,
    else the current one; legacy accounts use the implicit single-key config)."""
```

- A transaction carries `auth = [[i, sig], ...]`; a legacy single-signature transaction is exactly
  `auth = [[0, sig]]`, and the existing `signature` field is accepted as that for as long as we want
  (the wallet keeps emitting it for single-key accounts — zero wire change for today's users).
- The address-derived key is authenticator 0 of the implicit config **until the first reconfiguration**,
  after which it is whatever the config says — a rotated-away key is revoked, which is the point.
- `at_height` is used only by evidence verifiers (equivocation proofs, detached auth), answered from
  `auth_history`.
- PUBKEY-ONCE generalises: a transaction may omit public keys; the node resolves authenticator `i` from
  the config. First-ever transactions must carry their keys (nothing to resolve yet), as today.

That is the entire consensus-side surface: one predicate, one config record, one history table. Block
signatures, attestations, duty, reveals, slash proofs, treasury votes, HTLC/bridge/dividend claims all
go through it. The exec layer needs **nothing** — it consumes L1-validated blobs and keys its state by
address. A source-assertion test pins that no `proof_sender` caller survives.

## 5. Reconfiguration

One reserved recipient, `auth` (like `bond`, `register`, `msgkey`). Fee-paying, `chain_id`-bound,
ordinary landing rules. `data = {"config": <new auth_config>, "pop": {i: sig_i ...}, "action": ...}`,
all inside the signed body (`create_txid` commits everything but the keys).

**Validity of the new config** (checked at validation, so an invalid one never enters the pool):
- within bounds (§2); `version == current.version + 1` — the replay guard: a reconfiguration re-applied
  after a rollback under a different live config is refused, and two competing pending configs cannot
  both carry the same version;
- **proof of possession** for every authenticator that is new: `pop[i]` is authenticator i's signature
  over the txid. An unsatisfiable or mistyped policy can never be installed — an account cannot be
  bricked by accident;
- the transaction's `auth` set satisfies the **current `reconfig` policy** (not `signing`).

**Timing — decided by how much of `reconfig` is presented, not by a separate op:**

| `auth` satisfies | effect |
|---|---|
| the full `reconfig` policy | **effective at the block it lands.** With the "protected" preset that is hot + recovery: the owner who holds everything rotates now. |
| only `signing` (i.e. the hot key alone under "protected"; or the single key under "single key") | **pending** for `AUTH_DELAY` (1 day). Under "single key" this is proactive rotation: the delay lets the owner confirm the new device signs (the pop already proved it) before the old key stops. Under "protected" it is the *thief's* only move — and it is cancelable. |

**`action: "cancel"`** clears `auth_pending` (and nothing else). Accepted from any set of signatures
that satisfies `signing` **or** any single authenticator named in `reconfig` but not in `signing`
(the recovery key alone may cancel). A cancel by such an authenticator also sets
`auth_freeze = height + AUTH_FREEZE` (7 days): no *pending* (non-full-policy) reconfiguration may
land until then. This is what ends the war: once the owner has vetoed with a key the thief does not
have, the thief's only path is blocked, and the owner rotates at leisure with the full policy.

**Promotion** of a matured pending config is lazy and deterministic: the first transaction from the
account at/after `effective`, or the epoch-boundary sweep, installs it (bumping `version`, appending
`auth_history`). Until then the old config authorizes.

**A key that has reconfigured is not consumed.** The recovery phrase stays valid across rotations
(unlike the single-use recovery key in the first draft); replacing it is just another reconfiguration
under the full policy. The wallet still recommends a fresh recovery phrase after any recovery event.

## 6. What each subsystem sees

| subsystem | change |
|---|---|
| tx validation | `proof_sender` → `authorized`; `signature` accepted as `auth=[[0,sig]]`; PUBKEY-ONCE resolves authenticators from the config |
| block signatures, attestations, duty, RANDAO reveals | same predicate; a validator rotates its node key with a full-policy reconfiguration signed by the old `keys.dat`, swaps the file, and keeps producing under the same address, bond and ramp |
| slashing / equivocation proofs | verified with `at_height` from `auth_history`; a rotated-away key's past double-signs stay slashable |
| bonded / open registries, fidelity, aliases, treasury votes | keyed by address — untouched |
| exec layer (bridge, games, dividends, `zk_addrs`) | untouched |
| messaging (`msgkey`, prekeys) | separate identity KEM key; unaffected. Re-publishing prekeys after a compromise is wallet hygiene, not a rule |
| state root | account fields already in the root; `auth_history` is a new `SNAPSHOT_DBS` member — **a genesis-root change** (§9) |
| `/get_account` | returns `auth_config` (public keys and policy — nothing secret), `auth_pending`, `auth_freeze`, so wallets never scrape state (the "read-path" gap the Monad thread flagged) |
| wallet (browser) | the hot key rotates to the next HD child (`accountChildSeed`), so the seed phrase still recovers it — no key→address index is needed anywhere; a Security panel shows key age, preset, pending changes with loud warnings, and the "protected" upgrade flow |
| desktop wallet / node `keys.dat` | a `rotate-key` CLI that signs the reconfiguration, waits for effect, then swaps `keys.dat` (old file kept as `keys.dat.retired.<height>`) |

## 7. Threat analysis (with the "protected" preset)

| scenario | outcome |
|---|---|
| **hot key stolen, protected** | thief can spend the liquid balance (nothing anywhere prevents that) and can only *pend* a reconfiguration. Owner cancels with the recovery key (freezing 7 d) and rotates with hot + recovery. Bonded stake sits behind the 1-day unbond delay, so an `unbond`+`withdraw` by the thief is visible and beaten. Net: liquid balance at risk for the reaction window; stake, ramp, fidelity, address kept |
| **recovery phrase stolen, hot key safe** | the recovery key satisfies neither `signing` nor `reconfig` alone: it cannot spend and cannot even pend a change (it is not in `signing`). It can only *cancel*. Harmless beyond nuisance; the owner re-keys with hot + recovery, then installs a fresh recovery phrase |
| **hot key stolen, single-key preset** | unrecoverable by design (§1); the self-rotation war is a stalemate. The wallet says so plainly and nudges every account toward "protected" |
| both stolen | game over, as with any 2-of-2 |
| typo / unsatisfiable policy | proof of possession + bounds validation: cannot be installed |
| griefing / spam | fee-paying; one pending per account; only the account's own authenticators can act; `version` monotonic |
| cross-chain replay | `chain_id` in the signed body; `version` pins the config a change extends |
| reorg through a change | `auth_revert` restores the prior triple; the `auth_history` row is deleted (exact dupsort pair) |
| two valid pending changes racing (the Monad thread's open question) | cannot happen: one pending per account, and a second is refused, not queued; a full-policy change lands immediately and clears the pending one |
| rotated-away key signs a block later | `authorized` without `at_height` rejects it; with `at_height` (evidence) it verifies only for heights it was valid |

## 8. Constants (draft)

| constant | draft | why |
|---|---|---|
| `AUTH_MAX_KEYS` | 4 | hot, recovery, two guardians; every key is a potential verify per tx |
| policy depth | 2 | `THRESHOLD` of `THRESHOLD`s of `ID`s — enough for guardians, nothing more |
| `AUTH_DELAY` | `BOND_UNLOCK_DELAY` (14,400 blocks ≈ 1 day) | the same "network gets a day to notice" horizon as pulling stake; 3 blocks (Monad) is not a human reaction window |
| `AUTH_FREEZE` | 7 × 14,400 | long enough to rotate at leisure after a veto |
| `AUTH_HISTORY_KEEP` | 8 | evidence deeper than the finality floor is unactionable |
| fees | ordinary base fee for `auth` txs; never fee-exempt |

## 9. Rollout

1. `auth_history` is a new snapshot DB → a **genesis-root change**: ship at the next reroll, or behind
   a generation-keyed gate on the `auth` recipient (`H if CHAIN_GENERATION == 23 else 0`, the pattern in
   `doc/updates-and-rerolls.md`) with the DB empty before it — an empty dupsort DB contributes nothing
   to the root, so the gate guards the *ops*, not the storage.
2. Order: `authorized` + the no-`proof_sender`-survives assertion → config fields, bounds validation,
   `auth_revert`, a rotation case in `test_rollback_symmetry` → the `auth` recipient (install / pending /
   cancel / freeze / promotion) → `at_height` in block, attestation and slash paths → `/get_account`
   fields → wallet Security panel with the two presets → node `rotate-key` CLI.
3. Wallet default for new accounts: offer "protected" in the creation flow (one fee, effective
   immediately since the account's first config is installed with proof of possession of both keys).
   Existing accounts: a one-time prompt.

## 10. Open questions

- **Guardians as a third preset** (`THRESHOLD(1, [ID(0), THRESHOLD(2, [g1, g2])])`, pointing at other
  accounts' *current* hot keys): free in the language, but a guardian's key rotation silently
  invalidates the policy unless `ID` may reference an *account* rather than a raw key. Referencing
  accounts is cleaner (resolve their `signing` at verify time) and costs one extra state read per
  guardian signature — decide before the format is frozen.
- Whether a full-policy change should also bump anything downstream (it should not: continuity is the
  point; `bond_since` and fidelity untouched).
- Session keys for games (a short-lived authenticator allowed only `blob` calls to listed contracts) —
  the biggest UX win in reach and the most exposed to state bloat. Out of scope here; if ever, it must
  be `max_block`-bounded and never persisted past expiry.

## 11. Related work — Monad's "Flexible and Upgradeable Account Authentication"

The MIP reaches the same conclusions from the EVM side: authentication is state, the address is an
identifier, policy is `ID`/`THRESHOLD`, recovery is just the reconfiguration policy, proof of possession
is mandatory, and races between equal key-holders are settled by policy design, not by delay. §2 and §5
adopt its policy formulation and `config_version` directly — they are better than the first draft's
"one recovery key" special case. Where this design deliberately differs:

- **one scheme, hard bounds** — their multi-scheme `AuthConfig` and unbounded threshold trees are priced
  in gas; we have no gas model on L1 and a 6-second block, so the language is capped instead;
- **a human-scale delay and specified cancel/freeze semantics** — their 3-block activation and the
  unspecified "two pending configs" case are the gaps their own thread flagged;
- **no key→address index** — HD-derived rotation makes discovery unnecessary; the index is state growth
  and a privacy leak for a wallet convenience (their reviewers said the same);
- **no `ecrecover` problem** — our contracts never verify L1 signatures, so nothing downstream breaks;
- **their main motivation (PQ migration) does not apply** — the case for us rests on validator and
  streak recovery alone, which is why this stays scoped to two presets.
