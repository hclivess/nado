# Registration-rate PoSW difficulty — how expensive a flood gets

> **Status: IMPLEMENTED & CONSENSUS-BOUND.** The sequential Proof-of-Work required to `register` an OPEN-lane
> identity **scales with recent registration volume**, so a sudden flood of identities gets progressively more
> expensive. It is enforced in `validate_transaction` (`ops/reg_difficulty.py`), not client-side: every node
> recomputes the requirement from the committed recert index and **rejects an under-worked registration** — a
> node that "removes the difficulty code" just produces proofs every honest node throws away. Companion to
> [ip-spoofing-and-sybil.md](ip-spoofing-and-sybil.md).

## 1. The rule in one line

```
required_steps = POSW_T × multiplier(anchor_epoch)          # POSW_T = 1,000,000 base sequential hashes
```

The `multiplier` is a pure function of the committed recert index, keyed off the **finalized PoSW anchor epoch**
(`target_block − POSW_ANCHOR_OFFSET`, already finality-deep), so it is deterministic and identical on every node.

```
recent   = registrations in the last POSW_DIFF_WINDOW epochs        (the current rate)
trail    = registrations in the last POSW_DIFF_TRAIL epochs         (the "normal" reference)
baseline = max(POSW_DIFF_FLOOR, trail × POSW_DIFF_WINDOW / POSW_DIFF_TRAIL)
multiplier = min(POSW_DIFF_MAX_MULT, max(1, recent // baseline))
```

## 2. Parameters (`protocol.py`)

| Constant | Value | Meaning |
|---|---:|---|
| `POSW_T` | 1,000,000 | base sequential-hash steps (≈ 1–3 s on a phone) |
| `POSW_DIFF_WINDOW` | 20 epochs (~2.5 h) | the "recent rate" window |
| `POSW_DIFF_TRAIL` | 400 epochs (~2 days) | the trailing-average baseline window |
| `POSW_DIFF_FLOOR` | 20 regs/window | minimum baseline (a small network is never over-sensitive) |
| `POSW_DIFF_MAX_MULT` | 16× | hard cap (bounds the cost to an honest user) |

## 3. How hard it gets — at a glance

At a small/normal network the baseline is the floor (**20 registrations per ~2.5 h window**). The multiplier
then steps up as the recent rate exceeds it:

| Recent registrations (per ~2.5 h) | Multiplier | Required steps | ≈ time to register¹ |
|---:|:---:|---:|---:|
| 0 – 39 | **1×** | 1,000,000 | ~1–3 s |
| 40 – 59 | **2×** | 2,000,000 | ~2–6 s |
| 60 – 79 | **3×** | 3,000,000 | ~3–9 s |
| 80 – 99 | **4×** | 4,000,000 | ~4–12 s |
| 100 – 119 | **5×** | 5,000,000 | ~5–15 s |
| 140 – 159 | **7×** | 7,000,000 | ~7–21 s |
| 200 – 219 | **10×** | 10,000,000 | ~10–30 s |
| 300 – 319 | **15×** | 15,000,000 | ~15–45 s |
| **320 +** | **16× (cap)** | 16,000,000 | ~16–48 s |

¹ Range spans a slow phone (~350k hashes/s) to a fast device (~1M+/s). The wallet shows a **device-calibrated
ETA** and a live "~N s left" while proving (from `/posw_difficulty` + a rolling per-device rate estimate).

### Multiplier vs. recent registrations (baseline = 20)

```
 multiplier
  16× |                                             ┌────────────  (cap)
      |                                        ┌────┘
  12× |                                   ┌────┘
      |                              ┌────┘
   8× |                        ┌─────┘
      |                   ┌────┘
   4× |            ┌──────┘
      |      ┌─────┘
   1× |──────┘
      +----+----+----+----+----+----+----+----+----+----→ recent registrations
      0   40   80  120  160  200  240  280  320      (per ~2.5 h window)
```

## 4. The flood-cost picture

Because every identity in a burst pays the **elevated** multiplier, the *total* sequential work to spin up a
flood grows super-linearly while the burst is hot. Registering **N identities in one window** (once the rate has
pushed the multiplier to `m`) costs `N × m × POSW_T` sequential hashes — and the sequential proof is
**non-parallelizable per identity**, so more machines don't make each proof faster:

| Identities in the burst | Multiplier reached | Total sequential work | ≈ single-core time² |
|---:|:---:|---:|---:|
| 20 | 1× | 20 M | ~20–60 s |
| 100 | 5× | 500 M | ~8–24 min |
| 320 | 16× (cap) | 5.1 B | ~1.4–4 h |
| 1,000 | 16× (cap) | 16 B | ~4.4–13 h |

² Per-identity proofs *are* parallelizable across cores/machines; this column is the single-core lower bound to
show the scale. The point is not to make a flood impossible but **progressively, visibly expensive** — layered on
top of the two hard bounds that already cap the payoff:

- the **structural 20% (`OPEN_BPS`) cap** — a zero-capital Sybil swarm can never pull more than the open lane's
  30% of blocks, no matter how many identities it mints ([reward-capture-theorem.md](reward-capture-theorem.md));
- the **renewable lease** — each identity must redo the PoSW every `POSW_LEASE_EPOCHS` (~1 day) to stay present,
  so a farm's cost is *size × time*, not a one-off.

## 5. Self-scaling with network size (important)

`baseline` is a **trailing average**, not a fixed number. A large, healthy network that legitimately does
thousands of renewals per window raises its own baseline, so its members stay at **1×** — the difficulty only
bites when the *recent* rate spikes **above that network's own normal**. So the thresholds in §3 are the
small-network case (floor = 20); a bigger network's step-up points scale up with it. Conversely, a genuinely
sustained higher rate becomes the new normal over ~2 days (`POSW_DIFF_TRAIL`) and the multiplier relaxes — the
throttle targets *sudden bursts*, which is exactly the Sybil-flood signature.

## 6. Where it lives

- `protocol.py` — the constants above.
- `ops/reg_difficulty.py` — `difficulty_multiplier()` / `required_posw_t()` (pure, deterministic).
- `ops/kv_ops.py` — `recert_count_in_window()` (the committed volume).
- `ops/transaction_ops.py` — the `register` branch verifies the PoSW against `required_posw_t(anchor_epoch)`.
- `nado.py` — `/posw_difficulty` (the wallet reads it to prove at the right level + show the ETA).
- `tests/test_reg_difficulty.py` — 1× normal, ramps under a flood, caps.
