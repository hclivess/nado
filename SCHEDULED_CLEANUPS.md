# Scheduled cleanups — code that becomes deletable at a known chain height

Compatibility gates, activation branches and migration shims that are **correct today and dead later**.
Each entry names the height at which it may go, and — more importantly — **why it cannot go before that**,
because in every case the early cleanup is the tempting one.

Grep `SCHEDULED-CLEANUP` in the tree to find the corresponding code.

**Rule for this file:** an entry is removed only when the code is. If a genesis reroll happens, re-read
every entry — epoch/height numbering restarts and an activation constant that was 2 days out can land
weeks into the new chain, silently leaving the old behaviour live until then.

---


## STATE-ROOT REPAIR WINDOW — `[10047, 16000)` · deletable after the next genesis reroll, NOT at 16000

`loops/core_loop.incorporate_block` suspends the state-root EQUALITY COMPARISON across
`protocol.STATE_ROOT_UNENFORCED_FROM .. STATE_ROOT_ENFORCED_AGAIN_AT`. Everything else on that path stays
enforced — hash chain, producer signature, cumulative weight, tx validity, per-tx state transitions.

**Why it exists.** The index-prune watermarks briefly fed the L1 state root, so the roots committed over
that span encode how far one node had pruned its own disk. No other node can reproduce that value — an
archive node never held one at all — which makes those roots unverifiable *by construction*. Enforcing
them wedges every honest node permanently; the fleet was split at exactly h10047 until this landed.

**Why it cannot go at 16000, which is the tempting reading.** The window is not about the LIVE tip — the
chain passed 16000 within hours and full enforcement resumed there. It is about REPLAY: any node syncing
from genesis still walks 10047..15999 and still meets those unverifiable roots. Delete the branch and a
from-genesis sync becomes impossible on betanet-3, which is the one situation nobody tests until it is
needed. A snapshot-booted node skips the span entirely and is unaffected either way.

**Deletable when** betanet-3 is rerolled (the span stops existing) — or when from-genesis sync of this
chain is formally unsupported. Delete both constants and the `_unenforced` branch together; leaving the
constants behind invites someone to "re-enable" a window whose blocks are gone.

## 1. `FIDELITY_MIN_GAP_ACTIVATION_EPOCH` — the fidelity anti-farm gate

| | |
|---|---|
| **Added** | 2026-08-13 (`a1faab61`) |
| **Activates** | epoch **862** — block **51 720** |
| **Deletable at** | epoch **10 862** — block **651 720** (~42 days after activation) |
| **Code** | `protocol.py`, `ops/account_ops.py` (`apply_register`), `ops/dividend_ops.py` (`fidelity_at_epoch`) |
| **Test** | `tests/test_fidelity_min_gap.py` |

**What it does.** Fidelity was awarded per *recert*, and the only spacing rule anywhere was "one register
per epoch" — 6 minutes. So the ramp reached `FIDELITY_CAP = 30` in 3 hours instead of ~30 days, worth a 5×
multiplier on open-lane producer selection and on the presence dividend, for a fee-exempt transaction. The
gate requires a continuous recert to be ≥ `FIDELITY_MIN_GAP_EPOCHS` (192) from the previous one to earn
the ramp; a closer recert still renews the lease.

**Why it cannot be deleted at activation.** This is the trap, and it is a false-slashing bug, not a
cosmetic one. `dividend_ops.fidelity_at_epoch` replays an address's **entire** recert history — including
recerts from *before* the activation epoch — to reconstruct its weight as of a past epoch. Delete the
branch and that replay applies the spacing rule to pre-activation recerts, reconstructing weights that
were never applied. A dividend fraud proof checks exactly that reconstruction, so the "cleanup" slashes
honest settlers.

**Why that height.** The gate is dead once no pre-activation recert row can still be replayed. Rows are
retained for `RECERT_HISTORY_EPOCHS = 10 000` (the GC trims below `E - SATURATION_LOOKBACK_EPOCHS` =
7 440, so 10 000 is the conservative bound). Hence activation + 10 000.

**How to do it, when the time comes.** Make the spacing unconditional: drop the
`epoch >= FIDELITY_MIN_GAP_ACTIVATION_EPOCH` condition in **both** `apply_register` and
`fidelity_at_epoch` — they must never diverge — remove the constant, and update
`tests/test_fidelity_min_gap.py` (its "pre-activation tight recerts keep the OLD ramp" check goes away
with it).

**On a reroll, do it immediately instead.** A fresh chain has no pre-activation history, which is the only
thing the gate exists for. Making the rule unconditional is then strictly correct — and re-picking an
activation number would leave the exploit open for the first ~3.5 days of the new chain.

## STATE-ROOT ROW GROWTH — retention design REQUIRED at the gen-22 reroll (consensus change)

Not a code deletion — a design debt with a deadline. The per-block `l1_state_root` walk covers every
row of the consensus state, and six row families grow FOREVER: `att:` meta rows (21.8k @ h84.5k),
RANDAO `commits` (21.9k) + `reveals` (17.8k), FFG `attestations`, `divnull` (4.4k), `settlements`
(3.4k), and `epochw` (~10KB/epoch). Measured 2026-08-20: the walk was 31% of ALL process CPU
(~3.5s/block at ~100k rows — total chain work is O(chain²)); fork churn multiplies it (each rejected
same-height block re-verifies = another walk, p90 34s). The leaf-digest cache (snapshot_ops.merkle_root)
bought an ~9x on unchanged rows, but the row COUNT still grows without bound — at 10x chain length even
the cached walk and the LMDB iteration dominate again.

**The fix is consensus-changing** (rows leaving the root change the root), so it lands at the reroll,
free: gen-22 genesis defines retention windows from block 0 — e.g. commits/reveals/att older than the
unbonding horizon, attestations older than hard finality, settled cursors older than the settle horizon,
epochw beyond the dividend-replay window — and the walk shrinks to O(retention), permanently. Designing
these windows is a REQUIRED reroll-checklist item next to the games redeploy; rerolling without them
re-arms the same quadratic clock.
