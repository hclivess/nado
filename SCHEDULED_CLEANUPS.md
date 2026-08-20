# Scheduled cleanups — code that becomes deletable at a known chain height

Compatibility gates, activation branches and migration shims that are **correct today and dead later**.
Each entry names the height at which it may go, and — more importantly — **why it cannot go before that**,
because in every case the early cleanup is the tempting one.

Grep `SCHEDULED-CLEANUP` in the tree to find the corresponding code.

**Rule for this file:** an entry is removed only when the code is. If a genesis reroll happens, re-read
every entry — epoch/height numbering restarts and an activation constant that was 2 days out can land
weeks into the new chain, silently leaving the old behaviour live until then.

---


## STATE-ROOT ROW GROWTH — retention windows STILL OWED (missed the gen-22 reroll; consensus change)

Not a code deletion — a design debt with a deadline. The per-block `l1_state_root` walk covers every
row of the consensus state, and six row families grow FOREVER: `att:` meta rows (21.8k @ h84.5k),
RANDAO `commits` (21.9k) + `reveals` (17.8k), FFG `attestations`, `divnull` (4.4k), `settlements`
(3.4k), and `epochw` (~10KB/epoch). Measured 2026-08-20: the walk was 31% of ALL process CPU
(~3.5s/block at ~100k rows — total chain work is O(chain²)); fork churn multiplies it (each rejected
same-height block re-verifies = another walk, p90 34s). The leaf-digest cache (snapshot_ops.merkle_root)
bought an ~9x on unchanged rows, but the row COUNT still grows without bound — at 10x chain length even
the cached walk and the LMDB iteration dominate again.

**The fix is consensus-changing** (rows leaving the root change the root). The gen-22 reroll
(2026-08-20) shipped WITHOUT it — rows restarted from zero, buying weeks of headroom, but the
quadratic clock is re-armed. It now lands either at gen-23 genesis or via a CHAIN_ID-tied
coordinated activation on betanet-4: retention windows from a defined point — e.g. commits/reveals/att older than the
unbonding horizon, attestations older than hard finality, settled cursors older than the settle horizon,
epochw beyond the dividend-replay window — and the walk shrinks to O(retention), permanently. Designing
these windows is a REQUIRED reroll-checklist item next to the games redeploy; rerolling without them
re-arms the same quadratic clock.
