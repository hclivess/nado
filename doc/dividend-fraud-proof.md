# Dividend fraud-proof — from 2/3-bonded-quorum trust to 1-honest-challenger (Phase-2b)

> **Status: BUILDING** (alphanet). Upgrades the presence-dividend's per-address allocation from
> *trust the 2/3 bonded settlement quorum* to *trust any single honest challenger*, while keeping the L1
> happy path **O(1)**. Companion to [presence-dividend.md](presence-dividend.md) (the accrual) and the
> execution/settlement layer ([execution-layer.md](execution-layer.md)).

## 1. The gap this closes

The dividend **pool** accrues on L1 and is fully consensus-bound (integer-exact split → `DIVIDEND_POOL`,
enforced in incorporation, reversed on rollback). But the **per-address split** — who gets how much of the
pool — is computed **off-L1** by the execution node and made canonical by a **2/3 bonded-quorum** settlement
attestation (`settle` tx → `settlement_justified`). L1 verifies a claim's Merkle membership in the settled
root but **never re-derives the allocation**. The security audit (2026-07-03) flagged this as the one part of
the reward path that is *not* consensus-bound:

- **Supply is safe** regardless — every `dividend_withdraw` is capped at the live `DIVIDEND_POOL` balance and
  nullifier-guarded, so no inflation is possible.
- **But a ≥2/3 bonded coalition can *misallocate* the pool** (pay itself instead of the honest present set)
  and L1 cannot reject it. That trust equals the finality assumption — acceptable, but not *consensus-bound*.

We cannot close it by having L1 re-derive the split every epoch: that is O(present miners) per epoch, which
`presence-dividend.md` §3 forbids (the O(1)-per-block wall that keeps a phone able to validate). The
scalability-preserving answer is an **optimistic fraud proof**: settle cheaply by quorum, but let anyone
**challenge** a dishonest settlement with an O(present) proof that L1 checks *once*, on demand.

## 2. Three parts

### Part A — Deterministic accrual over finalized state (the precondition)

Today `accrue_dividend` runs once per *catch-up batch* using the **tip** present-weights and the current pool
**balance**. Two miners with different batch boundaries can produce different roots — it is not a pure
function of committed state, so "the correct root" isn't even well-defined, and nothing can be *proved* wrong.

Make accrual a pure function of **finalized L1 state**, computed **per epoch**:

```
for each finalized epoch e (processed in order):
    P_e      = Σ dividend_cut over e's blocks          # pool INFLOW during e (drawdown-immune; from reward splits)
    present  = get_open_registry(e)                     # lease valid at e, from the retained recert history
    W_e      = Σ open_shares(fidelity_i@e)  for i in present
    pot      = P_e + carry_in_e                         # carry_in_e = carry_out_{e-1}, an explicit chain
    share_i  = pot * open_shares(fidelity_i@e) // W_e   # floor, deterministic
    carry_out_e = pot - Σ share_i                       # sub-unit remainder, carried to e+1 (never lost)
    dividend[i] += share_i
```

Every honest exec node now computes the **identical** root at a given cursor. `get_open_weights` gains an
`?epoch=` parameter so the exec node (and the L1 challenge path) read the present set + weights **for a
specific historical epoch**, from the single L1 source of truth (`get_open_registry(e)`), not the tip.

Pool **inflow** `P_e` (not the pool *balance*) is the accrual driver — this is drawdown-immune by
construction and also removes the balance-watermark stranding bug (see [presence-dividend.md](presence-dividend.md)).

### Part B — Per-epoch receipts in the exec root (verifiable in isolation)

The exec `state_root` commits, per epoch, a **receipt**:

```
receipt_e = { epoch: e, pool_inflow: P_e, total_weight: W_e, carry_in, carry_out,
              shares_root: merkle_root({ addr -> share_i }) }
```

plus the existing cumulative per-address `div_bal` leaves (what a withdrawal proves against). A single epoch
is therefore **independently checkable**: given `receipt_e` and `carry_in_e` (itself = `carry_out` of the
committed `receipt_{e-1}`), the whole distribution for epoch `e` is reproducible in O(present@e) — no need to
replay history from genesis.

### Part C — The L1 challenge

`dividend_challenge` transaction. Anyone (with a small anti-grief bond) submits:

```
{ recipient: "dividend_challenge",
  settled_cursor: C,            # the settlement being disputed
  epoch: e,                     # the epoch receipt claimed wrong
  receipt: receipt_e,           # + Merkle proof that receipt_e is in the settled root at C
  # (optionally the single disputed addr; L1 recomputes the whole epoch e anyway — it is O(present@e)) }
```

L1 **re-derives epoch `e` from its own finalized state** — `P_e` from e's block reward splits, `present`/`W_e`
from `get_open_registry(e)`, `pot = P_e + carry_in`, `share_i` for each present `i` — and compares to
`receipt_e`. If any share (or `P_e`, `W_e`, `carry_out`) disagrees:

- the settlement at cursor `C` (and everything settled on top of it) is **voided** — its roots stop being
  `latest_settled`, so no claim can prove against them;
- the **settlers are slashed** (a fraction of each attesting validator's bond) and part is paid to the
  challenger (the rest burned), making a dishonest settlement strictly -EV;
- the exec network re-settles the *correct* root (which every honest node already has, per Part A).

Cost: **O(1)** on the happy path (no challenge). A challenge costs **O(present@e)** L1 work **once** — rare,
off the per-block path, and paid for by the challenger's bond + the slash it triggers.

## 3. Trust after this

- **Happy path:** quorum settles the deterministic root; O(1). Unchanged UX.
- **Adversarial path:** a dishonest 2/3 quorum root is **provably wrong** and **any single honest node** can
  void + slash it within the challenge window. The allocation is now **1-of-N-honest**, not 2/3-honest.
- **Supply** remains strictly pool-capped at claim (unchanged backstop).

## 4. Guardrails

- **Challenge window.** A settled root's leaves become *claimable* only after `CHALLENGE_WINDOW` blocks with no
  successful challenge (a soft-finality delay on dividend *withdrawals* only — accrual/settlement continue).
- **Challenger bond.** `dividend_challenge` posts a bond; a *failed* (incorrect) challenge forfeits it →
  no free griefing / L1-spam. A *successful* challenge is refunded + rewarded from the slash.
- **Determinism of inputs.** Re-derivation reads only finalized, retained state: the recert history (never
  pruned; rolling mode drops block *bodies*, not the recerts DB) and recent block reward splits (challenge
  window ≪ history-retention window, so those bodies are present).
- **Revert symmetry.** The challenge, void, slash, and bond flows all reverse exactly on rollback (same
  discipline as every other tx).
- **Boundary determinism.** "Present at epoch e" = a PoSW recert in `(e − POSW_LEASE_EPOCHS, e]`; weight uses
  fidelity as of `e`. Exec and L1 use the identical `get_open_registry(e)` / `open_shares` code — one source
  of truth, so they cannot disagree except on a genuine settlement fault.

## 5. Rollout (alphanet)

1. **A — deterministic accrual + `?epoch=` weights** (makes the root canonical; independently valuable).
2. **B — per-epoch receipts** committed in the exec root + withdrawal unchanged.
3. **C — `dividend_challenge` + slashing + void + challenge window**, with tests and an adversarial review of
   the slashing/griefing/replay paths before it goes live.

Each stage is tested and shipped independently; A alone already removes the timing non-determinism and makes
"the correct root" well-defined.
