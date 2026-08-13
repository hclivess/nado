# Scheduled cleanups — code that becomes deletable at a known chain height

Compatibility gates, activation branches and migration shims that are **correct today and dead later**.
Each entry names the height at which it may go, and — more importantly — **why it cannot go before that**,
because in every case the early cleanup is the tempting one.

Grep `SCHEDULED-CLEANUP` in the tree to find the corresponding code.

**Rule for this file:** an entry is removed only when the code is. If a genesis reroll happens, re-read
every entry — epoch/height numbering restarts and an activation constant that was 2 days out can land
weeks into the new chain, silently leaving the old behaviour live until then.

---

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
