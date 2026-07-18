# Registration-difficulty v3 — the visibility-fork postmortem (2026-07-18, protocol 4)

## What happened

After the alphanet-6 fleet converged on the snapshot re-anchor sync model, nodes began
bootstrapping from **state snapshots** and pruning historical block bodies. Registration-PoSW
difficulty v2 counted `register` txs by **scanning block bodies** and silently returned `0`
for any epoch a node did not hold — so the required multiplier became a function of each
node's **local retention**, not of the chain.

Measured live:

| node | visible recent-window registers | required multiplier |
|------|--------------------------------:|--------------------:|
| full-history fleet node | ~57 | **2×** (accepted proofs verify at exactly 2×) |
| freshly snapshot-booted node | 9 | **1×** |

`posw.verify` is exact-T (over- or under-work both fail), so each side rejected the other's
honest registers; every register-bearing block split them. A re-anchored node re-truncates
its own visibility on arrival, so it forked again within minutes — seven re-anchor loops in
one day — and **every new node joining by snapshot inherits the incompatibility.**

## The fix (v3)

Counts come from the `recert_by_epoch` **consensus state index**, never from body scans:

- **snapshot-carried + state_root-validated** at import (`ops/snapshot_ops`) — a
  snapshot-booted node holds exactly the counts a from-genesis node derived;
- maintained **revert-symmetrically** by `apply_register` (put on apply, del on rollback);
- the **one-register-per-(sender, epoch)** validation guard makes the DUPSORT pair-collapse
  unreachable, so rows == register txs exactly.

The requirement is a pure function of the **applied chain**, independent of body retention.
Windows still end strictly before the anchor epoch, so every counted row is settled before
the anchor block exists (no prove-time/land-time race).

v1's sin was different: an **unvalidated** index carrying pre-reroll junk plus a
still-filling window. Both stay cured here — the carriage is state_root-validated and the
anchor epoch is still excluded.

## Deployment

**Protocol 4 flag day** (no compatibility, per policy): protocol-3 nodes are shed at the
handshake and rejoin via the update wave (`/update`). Miners' in-flight proofs minted at the
old node-local multiplier bounce once and re-mint at the uniform v3 requirement — `register`
is fee-exempt, so this self-heals within a lease period.

Related hardening shipped the same day: fork-choice inputs (re-anchor donor selection and
the production gate) ignore foreign-protocol peers entirely — a protocol-2 straggler's
heavier dead fork can no longer steal a re-anchor or suppress block production.

## The invariant to keep

> A consensus-validity rule may depend only on data whose presence and value are **provably
> identical on every honest node**: committed state (validated by state roots) or finalized
> chain content every node is guaranteed to hold. Local indexes, local retention depth, and
> partially-filled windows are all forks waiting to happen.
