# Getting a settle-with-proof onto the chain

> ## RESOLVED 2026-08-06 — see §6. A proof landed.
>
> Block **43153** carries a settle with `proof=True` for `exec_cursor 42876`. The block is **126.6 MiB**,
> all four nodes agree on its hash, it is final at depth 71, and `/get_settled` returns the proven root.
> **The exec root advanced on a STARK validity proof rather than a bonded quorum.**
>
> §§1–5 below are kept as written because the reasoning is still worth reading, but **§1's central
> conclusion was wrong** and it is what blocked this for months: "the proof can never ride inside a block
> at any FRI parameters" rested on "a full block ~256 KiB", which was never a consensus rule — it was
> `transaction_pool_max_bytes`, a MEMPOOL CULL BUDGET, quoted from a comment. **Nothing in consensus
> bounds transaction or block size**; `ops/block_ops.py` has no size rule at all. Every limit in the path
> was an HTTP/DoS knob, and the one that actually rejected a large settle was
> `ops/net_ops.MAX_TX_BODY = 1 MiB` — aiohttp's default — which was ALSO smaller than the
> `SETTLE_INLINE_MAX = 7 MiB` that called itself "a protocol fact, not a knob". Both were raised and the
> proof went inline.
>
> The lesson worth keeping: a measured number quoted from a comment is not a measured constraint. §1's
> table is accurate; the row it reasoned from was not a rule.

## 1. The measurements

| quantity | value | how |
|---|---|---|
| settle tx, protocol params | **97.30 MiB** | logged live by the exec node |
| dominant term | `segment.proof.openings` | field-by-field breakdown |
| scaling | **0.381 MiB per FRI query**, linear | 0.892 MiB @ NQ=2, 3.166 @ 8, 24.385 @ 64 |
| FRI params | `BLOWUP=2`, `NUM_QUERIES=320`, `GRIND_BITS=18` | `execnode/stark/fri.py` |
| security | `320 × 0.4 + 18 ≈ 146 bits provable` (Johnson) | fri.py's own accounting |
| `pre_contracts` share | ~1.6 MiB of 97 (**<2%**) | measured against 25 live contracts |
| a full block | **~256 KiB** | `transaction_pool_max_bytes` comment; a produced block logged 71,163 B |
| L1 submit cap | 8 MiB (was aiohttp's 1 MiB default) | raised 2026-08-03 |
| settle cadence, as configured | **~2 per minute** | 58 settles in 30 min, live |
| segments per settle | **1** for the whole span (fold off) | logged: "span→586: 1 segment(s)" |

Two things follow immediately, and both killed a candidate fix:

* **The payload is O(queries), not O(state).** `verify_bound_epoch_replay` (in-circuit membership instead
  of shipping `pre_contracts`) would save under 2%. It is not the fix.
* **The binding constraint is the BLOCK, not the HTTP cap.** 97 MiB is ~380× a block. The best
  query/blowup reparameterisation — blowup 16 at ~64 queries for the same 146 bits — still gives 24 MiB,
  ~95× a block. A 4–6× reduction cannot close a 380× gap, so **the proof can never ride inside a block at
  any FRI parameters.**

## 2. Why the obvious cadence makes it hopeless, and why that is fixable

At the configured cadence the exec node settles roughly every 30 seconds, so proofs would be produced at

    97.30 MiB × 2/min  =  194 MiB/min  ≈  280 GiB/day

which no small network can carry on any transport, DA included.

But proof size is **independent of span**: with the fold off, `prove_settlement_sparse` emits ONE bound
epoch for the entire span, and the size is dominated by FRI queries rather than by the number of calls
(ROADMAP's own measurement: proof size constant while calls go 1→8). So a settle covering 240 blocks costs
the same ~97 MiB as one covering 2.

Settling at the protocol maximum span instead of every poll is therefore a pure win, and a large one:

| cadence | proofs/day | at 97 MiB | at 24 MiB (blowup 16) |
|---|---|---|---|
| every ~2 blocks (today) | ~2880 | 280 GiB/day | 69 GiB/day |
| every `SETTLE_PROOF_MAX_SPAN` (240 blocks ≈ 24 min) | ~60 | **5.8 GiB/day** | **1.4 GiB/day** |

1.4 GiB/day is an ordinary DA workload. That is the difference between "infeasible" and "engineering".

## 3. The transport — and why it is not merely a transport question

The proof cannot go in a block, so the obvious move is DA: publish it via `/da/publish` and carry only the
commitment. The machinery exists and the shielded `field_transfer` path already submits exactly this way.

**But that precedent does not transfer, and the reason is the crux of this whole document.**

* **L1 never fetches DA.** The only `proof_da` reference anywhere in L1 code (`ops/transaction_ops.py`)
  validates the *string shape* of the field — "must be a safe commitment string" — and nothing more. The
  EXEC layer resolves and verifies it later, stalling the block if it is unavailable
  (`_apply_block`: "Returns False (applying NOTHING) if a field_transfer proof is unavailable via DA").
* That is sound for `field_transfer` because the shielded pool is an **exec-layer** object: L1 does not
  need it to be valid in order to validate a block.
* The **settled root is not** an exec-layer object. `settled_header_commitment` puts the justified
  `(exec_cursor, exec_root)` into the **L1 BLOCK HEADER**, and `block_content_hash` includes `exec_root`
  and `exec_cursor` in the hash preimage. Every L1 block commits to it.

So if the proof lives in DA and L1 does not fetch it, **L1 commits a settled root in its own header
without ever verifying the proof that justifies it** — the root then rests entirely on the bonded quorum,
and "trustless settlement" is trustless only to whoever independently re-verified out of band.

**Therefore §3 and §4 are the same decision, not sequential steps.** Choosing DA transport IS choosing what
L1 verifies.

## 4. The actual open problem: WHEN the proof is verified

`validate_transactions_in_block` runs inside `verify_block`, **strictly before incorporation, for every
block a node incorporates — including historical blocks during a fresh sync.** So a naive DA reference
means a joining node must fetch and verify one ~97 MiB proof per settle across the whole chain. That is the
real obstacle, and it is about verification timing, not size.

Restated with §3 folded in, the three candidates are:

0. **L1 fetches from DA during block validation.** Keeps the proof authoritative at L1.
   *Objection:* this puts a NETWORK FETCH inside consensus validation. A node could no longer validate a
   block from local data, a DA outage stalls the chain rather than degrading it, and the ~97 MiB fetch sits
   on the critical path of every block containing a settle — including all of them during a fresh sync.
   Nothing in L1 works this way today, by design.

1. **Depth-gate the re-verification.** — **CHOSEN (operator decision, 2026-08-03); implemented as
   `protocol.SETTLE_PROOF_DEPTH_GATED`, tested in `tests/test_settle_depth_gate.py`.** Verify a settle proof only while its block is within
   `FINALITY_DEPTH` (45) of the tip; below that, accept it on accumulated weight, exactly as the chain
   already treats deep history for snapshot bootstrap ("classic weak-subjectivity checkpoint").
   *Objection:* a full-syncing node then no longer independently verifies historical settlements — it
   inherits them. That is a real reduction in what a from-genesis sync proves, and it should be a
   deliberate decision rather than a side effect.

2. **Lean on the quorum path for history.** A settlement can be justified by bonded quorum OR by proof.
   Historical settles carry quorum attestations regardless, so a fresh syncer could rely on those and treat
   the proof as tip-time evidence only. *Objection:* this quietly makes the proof decorative for anyone who
   was not online at the time, which is most of the security argument for having it.

3. **Recursion to a genuinely succinct proof.** The K→1 fold is the intended answer and would make all of
   this moot. *Objection:* measured 2026-08-02, a fold over the W=106 exec AIR ran **5h07m at 492% CPU and
   8.2 GB without completing**. It needs to reduce size by ~1000×, not 4×, and it currently cannot produce
   at all.

## 4b. The FRI blowup lever, measured — and rejected

`fri_blowup` is not a tunable. `stark.py` sets `blowup = 2·next_pow2(max_degree)`, `N = blowup·T` and
`deg_bound = next_pow2(max_degree)·T`, so `fri_blowup = N/deg_bound = 2` is a **structural identity**
(`stark_native.py` pins it for exactly that reason). Raising it to 16 means an **8× larger LDE domain**,
paid in NTT and Merkle work on every column.

**The prove-time measurement that originally justified this section has been WITHDRAWN.** It reported
53.3 s → 374.4 s ("3.0× smaller for 7.0× slower") on 2026-08-03 — one day before
`7afb5728 settle prover: default to an arena-covered backend — one wrong default put it all in Python`.
It timed the **Python** prover, which no node runs and which the Rust-only guard now treats as a hard
failure. Re-measured on the native arena, the prove-cost picture is not merely smaller, it is different in
kind (blowup 8 is roughly free on prove time). Those numbers are deleted rather than corrected in place,
because a stale figure with a plausible story attached is what produced two rounds of wrong conclusions
here. See [fri-parameters.md](fri-parameters.md) §4 for the native measurements.

**The rejection stands anyway, on the argument that never depended on prove time.** At protocol strength
the lever turns ~97 MiB into ~32 MiB. 32 MiB is still ~128× a block, so **DA is required either way** —
and at the max-span cadence the difference is 5.7 vs 1.9 GiB/day, which no operator would notice. A
smaller proof that still cannot go in a block does not change the architecture, so the lever is not worth
a consensus change regardless of what it costs the prover. **Dropped.**

**This has now been proposed twice**, and both times the argument leaned on prove-cost numbers that turned
out to be Python artifacts. [fri-parameters.md](fri-parameters.md) was written on 2026-08-12 without
citing this section and recommended blowup 8 on the strength of a benchmark over a single-column toy
trace — which sizes the FRI term in isolation and cannot say what share of a settle prove it is. If it
comes up a third time: the size argument is the only one that matters, and it has already been answered.

**The busy-span measurement now exists** ([fri-parameters.md](fri-parameters.md) §4a, 30 blocks / 248 real
exec calls, native, process-isolated) and it goes the *other* way from both rejections: blowup 8 costs
**1.27× prove** for **0.47× size** and **0.55× verify**, at ~2× prover memory. The prove-cost objection in
this section is therefore dead as well as mis-measured. What survives is only this: 32 MiB and 97 MiB are
handled identically, so the size cut does not change the architecture. Anyone re-opening this needs to
answer *that*, not produce another timing table.

## 5. Recommendation

Sequence, cheapest first:

1. **DONE** — settle at the max span rather than every poll. Pure win, no consensus change, 48× less proof
   data.
2. ~~Raise the FRI blowup~~ — **rejected on measurement**, see §4b: 3× smaller for 7× slower, and DA is
   needed regardless.
3. **Publish to DA, commitment on chain.** Machinery exists. This is now the next step.
4. **DECIDED** — §4 option 1, depth-gated verification. The cryptographic check runs while a block is
   within `FINALITY_DEPTH` of the known tip; deeper blocks are accepted on accumulated weight. A
   from-genesis sync therefore INHERITS historical settlements rather than proving them, which is the same
   weak subjectivity already accepted for snapshot bootstrap. Structure (cursor match, tip extension, root
   composition, DA binding, records binding) is **never** gated, so a fabricated settle is still refused at
   any depth.

   Depth comes from the sync layer, not from local state: every measure derived from what a node has
   applied is ~0 during a sequential sync, because its own tip IS the block it is applying. A fetched sync
   batch proves chain exists above its tail, so the batch tail height is the lower bound used
   (`_fetch_sync_batch` records it; `validate_transactions_in_block` compares against it).

   Still open before the prover can be switched on: the DA transport itself (step 3), now unblocked by this
   decision.

Until (1)–(3) land, `NADO_EXEC_SETTLE_PROVE` should stay off: it costs minutes of proving per tick to build
a transaction that is rejected on size.

---

## 6. What actually happened (2026-08-06) — six blockers, not one

Every earlier attempt diagnosed **one** cause, fixed it, and still saw nothing land. That was not bad
diagnosis; there were genuinely six independent failures stacked, each individually fatal. Fixing any one
of them changed nothing observable, which is exactly why the problem looked intractable.

In the order they had to fall:

### 6.1 Peers could not verify a proof at all — the deepest cause

All three peers were missing `libgoldilocks.so`. Since betanet-14 there is **no Python fallback**
(`native_guard.require` raises `NativeMissing`), so no peer could verify a settle proof under **any**
circumstances — any size, DA or inline, however well it propagated.

Found by pushing a real settle tx at a peer and **reading the 403 body** instead of inferring from the
status code:

```
HTTP 403 {"result": false, "message": "Could not merge remote transaction:
 Settle proof invalid: segment 0: epoch proof invalid: malformed proof:
 NativeMissing: native crate 'goldilocks' is REQUIRED but its library is missing"}
```

Cause: `ops/self_update._rebuild_native_if_changed` skipped any crate whose sources had not changed in that
update, reasoning "its .so is still valid". That holds only if a .so was ever built. **A box that has never
built a crate has unchanged sources forever**, so it was skipped on every wave, permanently. Worse, the
rebuild ran only on the *update* path, so a node already on the correct commit answered `up_to_date` and
never built it either.

The failure is invisible from outside: L1 keeps producing blocks and `/status` stays 200 while the node
silently cannot do the one job in question. **Being current in git is not the same as being able to run.**
Fixed in `2a40c96b`, `c7459c16`, `dc8e8747`.

### 6.2 The fold's prover trace was linear in K

`prove_hetero` folded all K inner FRI proofs in ONE recursion proof whose trace grows ~65,536 rows per
folded proof (96 segments × 1088 rows at K=2 — queries × FRI layers × two paths × path levels × 16-row
sponge blocks). Measured: K=2 → T=131,072, K=4 → 262,144, K=8 → 524,288, and only 20.3% of that is
power-of-two padding, so there was nothing to trim.

The "O(1) settlement crypto" in `doc/zk-recursion.md` is the **verifier's** cost — one bundle instead of K
proofs. The **prover's** trace was never O(1). Folding through `recursion_depth.fold_tree` (`f583027d`)
bounds each node by the fan-in instead of by K: T=131,072 at every K.

### 6.3 DA cannot work on a one-provider fleet

This box is the **only** node in the fleet running `nado-exec`; the three peers run only `nado`, so
`:9273` is dead on all of them. Erasure coding k=4/n=8 buys nothing when there is exactly one provider: a
peer had to pull the whole ~120 MiB from us inside `_fetch_da_proof`'s 8 s budget. It never arrived.

A `/da/announce` prefetch endpoint (`f62678d4`) was added to move the transfer off the validation path,
and it is sound, but it is moot here for the same reason — peers have no DA store to prefetch *into*. It
announced to 0 peers on the first real proof.

### 6.4 The size caps were knobs, and the binding one was not the documented one

See the banner above. `MAX_TX_BODY` (1 MiB) was the real limit, not the 8 MiB app cap. All of it is now
keyed to `protocol.MAX_INLINE_TX_BYTES` (`6f7b6a41`): tx body, `client_max_size`, `MAX_PEER_BODY`,
`SYNC_BATCH_BYTES`, `_ZSTD_WIRE_MAX`, `transaction_pool_max_bytes`, `SETTLE_INLINE_MAX`.

### 6.5 Gossip timeouts sized for kilobyte transactions

`send_transaction` used a flat `ClientTimeout(total=5)` and `post_txs_by_id` 15 s. A 120 MiB body needs
~24 MB/s sustained *and* a verdict inside the same window — while the peer verifies the proof before
answering (~22–114 s). Both transports therefore timed out, so the tx sat in our pool alone; and since
every node deterministically builds the **winner's** candidate, a peer's candidate (without our tx) won
every time. Fixed in `25460038`: push scales with body size, pull raised to 300 s.

### 6.6 The landing runway was shorter than the transfer

A settle is an **exact-landing** tx. `SETTLE_PROOF_TX_MARGIN` was 60 blocks (~6 min), sized when the tx
carried only a DA commitment. Measured propagation of the real 120 MiB tx to all three peers was **~8
minutes**, so the target block passed while the transfer was healthy and in flight. Raised to 180 blocks
with grace 900 s and hold 1200 s (`1af768de`).

### 6.7 The evidence

| step | evidence |
|---|---|
| proof built | `settle-prove cursor=42876` → `BUILT`, self-checks passed |
| carried inline | `1 segment(s), tx 120.31 MiB` — no DA involved |
| a peer verified it | `200 {"message":"Success","result":true}` in **114.5 s** |
| reached every node | all four pools held `cursor=42876 proof=True` |
| landed | block 43153, 1 tx, `recipient=settle proof=True`, 126.6 MiB block |
| fleet agrees | all four nodes: `75bfd859494b1db3527c4e54…` |
| final | depth 71 > `FINALITY_DEPTH` 45 |
| state moved | `/get_settled` root == the proven root |

### 6.8 Verifying a landing — the scanner lied once

A block-scanner with a short per-block HTTP timeout **silently misses the landing**. Mine used 6 s and
swallowed the fetch of the very 126 MiB block it was hunting, reporting "0 settle txs" while the proof was
on chain. Use a long timeout, print fetch failures instead of hiding them, and confirm three ways: the
block's own tx list, `/get_settled`, and the same block hash on every peer. `/status` can also return
non-JSON while a node verifies a large proof — never let a failed parse look like a real value.

## 7a. The two remaining gates are ONE problem — measured 2026-08-06

Counting why spans were not proven, over a two-hour window (05:00–07:10):

| reason | count |
|---|---|
| **the RECORDS half moved across the span** | **14** |
| a previous settle-prove still running | 3 |
| no stashed pre-state (after an exec restart) | 1 |
| proofs actually BUILT | 2 |
| bare settles | 13 |

So the dominant blocker is the **records gate**, not the revert gap — 78% of skips. `SETTLE_PROOF_RECORDS`
is already `True`; its coverage is deliberately partial, and `records_bind.block_records_effects` says
exactly which part is missing:

> `derivable` is False when the block moves records in a way this module cannot yet re-derive — a
> bridge_withdraw, a shield, an xmsg, or **a value>0 call (whose escrow is conditional on the VM not
> reverting, so its NET effect is not a function of the calldata alone)**.

and at the call site:

> The escrow (sender → cid, two `T_BRIDGE_BAL` positions) happens BEFORE the VM runs and is REFUNDED when
> the call reverts, so the net records effect depends on the execution outcome, not on the calldata.
> **Deriving it needs the exec proof's own verdict, which is a later step.**

**That is the same problem as §7's revert gap, wearing a second hat.** Both reduce to: *the system cannot
represent the outcome of a call that reverted.*

* The prover refuses to prove a reverting execution (`vm_circuit.prove_epoch_calls` raises), so a span
  containing one yields no proof.
* The records derivation refuses a value-carrying call because it cannot know whether the escrow was
  refunded — which is the same verdict.

And the two are in direct tension on a live chain: **the fold needs calls, but every value-carrying call
makes its span unprovable.** Verified empirically — all 6 successful game calls carried `value=20000000`,
and there are zero zero-value calls on this chain. Presence-dividend accrual compounds it by moving
records every epoch with no transaction at all.

**Why there is no cheaper shortcut — checked, not assumed.** The obvious cheap fix is "the node already
ran the VM at incorporate time, so just commit the verdict alongside the call leaves". It does not work,
and the reason is structural:

* `block_summary` / `block_records_effects` are called from `loops/core_loop.incorporate_block` — the **L1**
  path — and what they return "feeds the L1 state root", so it must be a deterministic function of
  committed data that every node computes identically.
* **The L1 never executes contracts.** The exec layer is a separate process that tails L1. At incorporate
  time the L1 has the block body and nothing else, which is exactly why derivation is restricted to
  calldata.
* Letting the exec node supply the verdict would put exec-layer output into the L1 state root, breaking the
  layering that keeps L1 validation independent of the exec layer.

So `records_bind`'s "deriving it needs the exec proof's own verdict" is not a deferral of convenience — a
proof is the *only* sound way for L1 to learn what a call did.

**A CHEAPER UNLOCK THAN A CIRCUIT REDESIGN — proposed 2026-08-06, not yet implemented.**

First, why the circuit route is expensive. `zkvm.ZkVMRevert` states the design invariant outright:

> The interpreter reverts exactly where the AIR constraints would have no satisfying witness, so
> **'provable' and 'executes successfully' are the same set of calls.**

So "make the AIR prove a reverting execution" is not an extension — a revert is *defined* as the absence of
a satisfying witness. Proving one means encoding failure as a first-class outcome, i.e. redesigning the
circuit.

But that same invariant hands us the verdict for free:

> **If provable ⇒ successful, then the existence of a valid proof over a span IS the verdict: every call in
> that span executed successfully.**

A value call that succeeds keeps its escrow (sender → cid, no refund), and *that* is a pure function of the
calldata. So `records_bind` could derive a value call's effect as "escrow applied, no refund" and mark the
block derivable, with soundness resting on: if any call had reverted, no proof could exist, so no proof
would ever be presented against that derivation. The derivation is computed and committed at incorporate
time and only *consulted* when a proof is being validated, so a span that never gets a proof simply rides
the quorum as it does today.

**VERIFIED 2026-08-06 — and the proposal as first written had a HOLE. It needs a prerequisite.**

*Point 3 holds.* The only consumer of `derivable` is `calls_commit.verify_calls_bound_to_summaries`
(`rd` must be present and 1), and it runs **only** when a settle proof is being validated — the branch is
guarded by `records_out is not None`, i.e. "the caller intends to prove the records half". Nothing reads it
otherwise, so a span that never gets a proof rides the quorum untouched, exactly as the argument requires.

*Point 1 FAILS as originally argued.* I claimed a skipped call would fail closed because its `post_root`
"cannot match the committed root". It can. The check in `validate_transaction` is

```python
assert post_full == root, "Settle proof post_root must equal state_root"
```

and `root` is the settle **transaction's own claim**. L1 does not independently recompute the exec root —
verifying the proof is precisely what replaces re-execution. So a prover that proves a call the live chain
SKIPPED (sender could not cover the escrow; the VM never ran) produces a self-consistent (proof, root) pair
that L1 accepts, while every honest exec node computed a different root. That is a divergence, not a
refusal.

**What actually prevents it today is the records gate itself.** By refusing any block with a value>0 call,
it also blocks the skip-divergence. The two are entangled: removing the gate naively would open the hole it
was incidentally closing.

**Therefore the prerequisite:** `settlement_proofs._run_call` must mirror the live escrow rule before the
gate can be relaxed — check `bridge[sender] >= value`, debit the sender, credit the cid, and treat a
shortfall the way the chain does. Today it only does the credit:

```python
bridge[cid] = bridge.get(cid, 0) + value      # no sender debit, no affordability check
```

while `execnode/state.py` does `if self.bridge.get(sender, 0) < value: return "skip: ..."` then debits. The
prover already receives `pre_bridge`, so it has everything it needs. With that in place a skipped call
makes the prove FAIL rather than succeed on a state the chain never had, and "provable ⇒ what the chain
did" is restored — which is the property the whole argument rests on.

*Point 2 (the asset-denominated `abal` escrow) is unexamined* and needs the same treatment: the live path
checks `asset_balance(in_asset, sender) < value` and debits, while the prover calls
`asset_credit_dict(abal, in_asset, cid, value)` with no sender-side check.

**Revised order of work:** (i) make `_run_call`'s escrow mirror the live rule, native and asset, with a
test that a span containing an unaffordable call fails to prove; (ii) only then relax `records_bind` to
derive value-call effects; (iii) the "proof is the verdict" argument then carries the revert case as well.
Still no circuit work and no reroll — but (i) is not optional, and shipping (ii) without it would be a
soundness regression.

**The circuit route, for completeness, in the order the code itself implies:**

1. The exec AIR proves a **reverting** execution, exposing the per-call verdict as part of the proven
   public statement (not as a prover-supplied flag — that would be forgeable).
2. `records_bind` then derives a value-call's effect as *escrow, minus refund iff the verdict says
   reverted* — the missing "exec proof's own verdict" it already names.
3. Both gates close together, and spans containing ordinary contract activity become provable.

Until step 1 exists, proof-carrying settlement covers only spans with **no value-carrying calls and no
records movement**, which is why measured coverage is 2 proofs against 13 bare settles.

## 7. Still open

* **A skip/revert anywhere in a span makes it unprovable — folded or not.** A call the chain SKIPS (sender
  cannot cover the escrow, `execnode/state.py`) or that REVERTS is a no-op on chain: escrow refunded, no
  state moves. The prover cannot represent one — `settlement_proofs._run_call` raises, and so does
  `vm_circuit.prove_epoch_calls` ("a call reverted — nothing to prove"). On a busy chain most spans will
  contain one, so proof-carrying settlement degrades to bare attestations exactly when it matters.
  `calls_commit.block_calls` already documents the intended semantics — "ALL `op=='call'` blobs are
  included, even ones that will skip/revert in the VM … the proof's state transition treats a skip/revert
  as a no-op (matching live apply)" — so **the implementation contradicts its own design**.
  Routes: (a) the AIR proves a reverting execution; (b) reverted calls are excluded from the proven set in
  a way the **verifier can re-derive** — a prover-supplied "this reverted" flag would be forgeable;
  (c) narrow the span to the clean prefix, which needs `ExecState.settle_snapshot` to re-capture `root`
  and `rec_root` **at the narrowed cursor** (lowering `cur` alone makes the settle claim a post-root from a
  different cursor). `2d4bcccf` adds a pre-flight so such a span is skipped in seconds instead of after
  ~1000 s of proving.
* **`test_settlement_aggregate` times out (>2400 s), and that says nothing about the tree fold.** The test
  uses ONE storage entry ⇒ 1 merkle-update + 1 slot_key ⇒ **K=2**, and `prove_hetero` builds a tree only
  when `len(fri_proofs) > fan_in` (2 > 2 is false). So it takes the monolithic path and its timeout is the
  pre-existing monolithic cost, unchanged by the tree work. Production differs: K ≈ 2× net_updates (14 for
  a span with 7), so the tree does apply there — it has simply never been reachable, because spans with
  calls are exactly the ones the records gate refuses. Tree coverage today comes from
  `tests/test_settle_fold_tree.py` (K=4, 9 checks, exit 0).
* **THE FOLD DOES NOT SHRINK THE PROOF — it makes it BIGGER.** Established 2026-08-06 from the code, not
  from a prove. `prove_settlement_sparse` builds `out = {..., "segments": segments}` and then, when folding,
  *adds* `out["recursive"] = RV.prove(exec_proofs, ...)`. Nothing strips `seg["proof"]`; line 344 appends it
  to `exec_proofs` **and** leaves it in the segment. The verifier's own docstring says what is actually
  replaced:

  > when `proof["recursive"]` is present … the K per-segment **exec-proof verifications** are REPLACED by
  > ONE recursion bundle … the sparse transition binding + calls commitment + pre-state pin + kv chain still
  > run per segment.

  So the fold trades **verification cost** (K exec verifications → 1 bundle verification) for **extra
  bytes**. A folded settle carries the segment exec proofs *plus* the bundle.

  This contradicts `execnode.py`'s own claim on `SETTLE_FOLD` — "on the arena it is the only route to a
  proof small enough to settle on chain". That is not what the code does, and it is not what solved the
  size problem: the **inline pivot** did (§6.4). The fold's real value is L1 verification cost.

  It also explains why the size was never observed to drop: there was nothing to observe. The unfolded
  proof measures 120.31 MiB, and the doc's own linear rule (§1: 0.381 MiB per FRI query) predicts
  320 × 0.381 ≈ 122 MiB — so size tracks the FRI query count, and the fold's outer proof runs at the SAME
  protocol strength (`oq = num_queries`, settlement_sparse.py:313). Folding adds a second ~O(queries)
  object rather than replacing the first.

* **THE "UNEXPLOITED SIZE WIN" — RE-DERIVED AFTER §9, AND NO LONGER WORTH BUILDING.** The idea: if the
  bundle *authoritatively re-verifies* every segment's exec proof — which its docstring claims — the wire
  need not carry the full per-segment exec proofs, only what the verifier still reads
  (`RV.public_part(seg["proof"])`, plus `proof["T"]`, `proof["W"]`, `proof["blocks"]` for
  `epoch_statement`). The feasibility check passed: `public_part`'s own docstring says it is "the SMALL
  public part … NO trace openings, NO Merkle paths".

  **But the premise was the old proof format.** Openings were 118.97 of 124.43 MiB — **95.6%** — so
  stripping them looked like a ~20× win. After `1affffac` moved to row-commit, openings are **2.14 of
  7.60 MiB (28%)** and **FRI is 5.46 MiB (72%)**. So the ceiling on this optimisation fell from ~20× to
  ~1.4×, and it applies only when a `recursive` bundle is present — which needs K>1 segments, which needs
  calls in more than one block, which the records gate refuses today. **It would optimise proofs that
  cannot currently be produced at all.**

  Verdict: do not build it now. Revisit only after the records gate lifts, and note that by then the term
  to attack is **FRI**, not the openings. Recorded rather than dropped, because the reasoning is sound and
  only the arithmetic changed.

* **The landed proof was UNFOLDED** (`calls=0`). The folded proof's SIZE has still never been measured
  against the 120.31 MiB unfolded baseline — that is the entire point of the fold.
* **`prove_transition` dominates a span WITH calls**: measured `calls=1 net_updates=7` → 782–884 s, i.e.
  ~126 s per state update, while `prove_epoch` FELL to 8.9 s. Untouched constant factors: `max_degree=8`
  ⇒ blowup 8 ⇒ N=8T; the ext-field arena penalty (~2.8×, the Rust arena is base-field only); allocator
  churn (~4/8 samples in libc, RSS 1.2→2.8 GB); 20.3% power-of-two padding. **`ee5020bc` gated the fold
  off at K=1** — the bundle had only ever wrapped a single proof, so it bought no verification win for a
  full extra STARK prove. That gate is **not yet verified live**: every span proven since carries
  `calls=0`, and `execnode.py:621` already sets `_fold = … and bool(calls)`, so the gate has not been
  reached. It can only be exercised once the records gate lets a span with calls through.
* **Cost of the inline pivot**: blocks carrying a proof are large, so gossip and sync move real bytes. That
  is a deliberate betanet trade — a proof that lands beats a smaller one that cannot.

## 8. The sparse root was the constant term — measured and removed (2026-08-06)

With `prove_transition` at 0 s (every proven span so far has `calls=0` ⇒ `net_updates=0`), four consecutive
proves gave a stable and unexpected breakdown:

| cursor | prove_epoch | sparse_projection | prove_transition | total |
|--------|------------:|------------------:|-----------------:|------:|
| 44431  | 85.4 s | 256.2 s | 0.0 s | 341.7 s |
| 44619  | 88.0 s | 221.4 s | 0.0 s | 309.4 s |
| 44929  | 70.9 s | 237.9 s | 0.0 s | 308.7 s |
| 45173  | 63.0 s | 271.2 s | 0.0 s | 334.3 s |

`sparse_projection` is **72–81% of every prove**, and it does no proving at all — it is
`settlement_sparse.prove_bound_epoch` building a `SparseStore` over the state and taking its root.

**Where the time goes.** Production state is 25 zkVM contracts / **9,016 slots** at depth 256. Offline on
this box the root alone measures **65.1–69.7 s**. That is `9,016 × 256 = 2,308,096` alghash2 permutations;
a permutation benchmarks at **24 µs**, which predicts 68.5 s — the model and the measurement agree, so
there is nothing else hiding in the stage.

**The permutation was already native, and it is not slow.** The first hypothesis — `rnode()` falling back
to Python — was wrong: `rnode` calls `permute()`, which does adopt the Rust `permute12` export. A raw
`ctypes` call into `permute12` with a preallocated buffer still costs 24.25 µs against `rnode`'s 27.50 µs,
so **marshalling is ~3 µs and the other 24 µs is real arithmetic**: ROUNDS=54 over WIDTH=12 with a dense
12×12 MDS is ~10,400 Goldilocks multiplications per permutation. There is no constant factor to reclaim
here without changing the hash — which is a consensus change.

**So the fix had to be doing fewer of them.** With 9,016 keys spread over a 2^256 space, every key is alone
in its subtree from about level 14 upward, so ~240 of each key's 256 levels are a *singleton fold* against
the canonical empty roots — **99.6% of the work**, and a pure function of `(depth, key, value, level)`.
`SparseStore._memo` could not help: `settlement_sparse` builds a **fresh store on every prove and on every
verify**, so the per-instance memo never survived to the next one.

`storage_tree._FOLD_CACHE` is a module-level memo of that pure function, keyed `(depth, key, value)` and
holding the chain's **high-water mark** `(level, digest)` so a higher level resumes and a lower one
recomputes. Measured on the same production state:

| | time |
|---|---:|
| cold root (9,016 slots, depth 256) | 65.10 s |
| warm root, unchanged state | **0.46 s** (141×) |
| root after 40 changed slots (a realistic span) | **0.58 s** |

Roots are bit-identical cold, warm and after a delta; authentication paths still fold to the root; entries
do not leak across depths. `tests/test_fold_cache.py` (8 checks) pins all of that, because a memo that
returned a wrong digest would silently change the settled state root and fork L2.

The same code runs in the **verifier** (`verify_bound_epoch` rebuilds the store), so a peer validating a
settle proof gets the same reduction on its second and later verifications.

**Confirmed live.** Cursor 45450, 10:34 — `prove_epoch=115.5s sparse_projection=2.0s
prove_transition=0.0s | total 117.5s`, landed on L1 at 10:37:58 with root `a35c2195c1a9e802`.

**What this left.** `prove_epoch` became the whole prove, measured with **zero calls**. That turned out to
have the same root cause as the proof's size — see §9.

## 9. The 120 MiB was ONE producer-side default (2026-08-06)

Chasing `prove_epoch` on an empty span led somewhere better than expected. The empty trace is only
T=512, W=167, blowup 8 ⇒ N=8192 — far too small to justify 63–115 s. The cost was not the polynomial work
at all; it was the **commit mode**.

`prove_settlement_sparse` defaulted its non-recursive branch to **ALGHASH2 in COLUMN mode**. In column mode
the prover builds one Merkle tree per column and every one of the `NUM_QUERIES=320` FRI queries opens
**every** column with its own authentication path — `W=167 × 2 (cur+nxt) = 334 paths per query`.
`row_commit` instead commits ONE recursion-Merkle tree over LDE **rows** per phase, so a query carries
**2** paths. The recursive path already proved this way (`backend=_bk.RECURSION, row_commit=True`); only the
non-recursive branch — the one that has produced every settle proof on this chain — was left behind.

Measured on production state (25 zkVM contracts, 9,016 slots), empty span, full
`prove_settlement_sparse` → `verify_settlement_sparse` round trip:

| | prove | size | verify | result |
|---|---:|---:|---:|---|
| ALGHASH2 column (old default) | 140.9 s | 126.56 MiB | 19.6 s | `(True, 'ok')` |
| RECURSION row (new default) | **7.3 s** | **9.73 MiB** | **6.4 s** | `(True, 'ok')` |

**13× smaller, 19× faster to prove, 3× faster to verify** — and `kv_pre`/`kv_post` are **byte-identical**
between the two forms (`63350d91c923b70d…` both ways), which is the only thing consensus sees. A separate
size-only run isolates where it goes: openings were **118.97 of 124.43 MiB (95.6%)** in column mode against
2.14 of 7.60 MiB in row mode, and a single opening is **389,845 bytes** against **7,008**.

**Why it needs no verifier change, and is not a consensus change.** Both knobs are recovered *from the
proof*, not from the caller: `verify_bound_epoch` does `row_commit = "row_roots" in bundle["proof"]`, and
`vm_circuit` honours `proof["backend"]`. L1 calls `verify_settlement_sparse(proof, depth=…)` and passes
**neither** (`ops/transaction_ops.py:1251`). So old-format and new-format proofs are interchangeable on the
wire, and switching is a producer-side choice — the same argument that justified defaulting to ALGHASH2 in
the first place. `row_commit` does require the RECURSION backend (`stark.py:377`), so the two move together:
`row_commit=None` now means "match the backend" rather than a bare `False` that silently gave up the win.

**This recontextualises §1 and §6.4.** The doc's rule of thumb — size ≈ 0.381 MiB per FRI query — was
measuring column mode. Size tracks `queries × columns × path length`, and only the first of those three was
ever treated as the lever. §4b rejected lowering the FRI blowup on soundness grounds; this needs no such
trade, because it removes redundancy rather than security. It also means the transport work in §6 (a
192 MiB `MAX_TX_BODY`, size-scaled gossip timeouts, a 180-block runway) now has ~12× the headroom it was
sized for, and the DA path is no longer near any limit.
* **Cost of the inline pivot**: blocks carrying a proof are large, so gossip and sync move real bytes. That
  is a deliberate betanet trade — a proof that lands beats a smaller one that cannot. After §9 a proof is
  9.73 MiB, so this cost is now small.

## 10. Which gate actually refuses a span — counted, not guessed (2026-08-06)

Size and prove time are solved (§8, §9). What still stops proof-carrying settlement is that most spans are
*refused before proving*. Counting one full day of `settle-with-proof SKIPPED` lines:

| refusal | count |
|---|---:|
| span crosses a dividend epoch boundary | 55 |
| the RECORDS half moved across the span | 36 |
| a previous settle-prove is still running (HELD) | 33 |
| no stashed pre-state | 17 |
| span exceeds `SETTLE_PROOF_MAX_SPAN` | 5 |

**The top two are ONE gate, not two.** A dividend accrues at every epoch-boundary block and moves records,
so any span containing a boundary is unprovable for exactly the reason the records gate names. The epoch
check simply fires first, being cheap. Together they are **91 of 146** refusals.

**This kills the obvious cadence fix.** Aligning settles to epoch boundaries does not help: the boundary
block itself can never be inside a proven span, and every span that contains a call still trips the records
gate because every call on this chain carries value (all 25 game contracts; zero zero-value calls). The
only thing that lifts this is `SETTLE_PROOF_RECORDS_VALUE_CALLS`, which needs a reroll — see §7a.

**"No stashed pre-state" was ours, and is fixed.** All 17 came from restarts: the stash of pre-states the
prover extends was in-memory only, so every deploy blinded the prover for a full settle cadence. `17c04c61`
persists it beside the state file (bounded to `_SETTLED_HISTORY_KEEP`, swept by both existing generation
wipes) and restores it at startup. Confirmed live: *"settle stash: restored 6 pre-state(s) from disk"*.
This was the largest class removable **without** a reroll.

**HELD (33)** is a consequence of prove time, and §8+§9 took a prove from 309–342 s to a few seconds, so it
should largely disappear on its own. Worth re-counting rather than assuming.

## 11. The pipeline after §8–§10, confirmed on chain (2026-08-06)

Two proof-carrying settles landed under the new format, both verified three ways (block tx list,
`/get_settled`, identical block hash on all four nodes):

| block | cursor | proof | block size | node agreement |
|---|---:|---|---:|---|
| 46766 | 46538 | yes | 9.74 MiB | `b3eb1d0620f7c40a393cb267e967c0ae` ×4 |
| 47078 | 46967 | yes | 9.74 MiB | `d013d2034fbadd40b4f414f3024f3858` ×4 |

against the first-ever proof block at **126.6 MiB**. A prove is now **8.9–15.3 s** end to end
(`prove_epoch` 8–12 s, `sparse_projection` 0.9–3.3 s, `prove_transition` 0 s) versus **309–342 s**.

**Peers verify it, observed rather than argued.** Pushing the pending tx to each peer returned
`{"message": "Already present", "result": true}` — gossip had beaten the manual push and each node had
*admitted* it, which requires `validate_transaction` → `verify_settlement_sparse`. Every peer's own
`/transaction_pool` held it. Proof header: `backend=recursion row_roots=True T=512 W=167 N=8192`.

### 11.1 Two things the speed-up exposed

**The landing margin was sized for the old proof.** A settle is an EXACT-LANDING tx (`protocol.py:115` —
it "lands at exactly max_block"), so `SETTLE_PROOF_TX_MARGIN` is not slack: it is how long settlement is
FROZEN, because the exec node must hold every bare settle until the proven span lands. Measured cost at
180 blocks: submitted 12:35, next settle 12:55 — **~20 minutes frozen for one proof**. Re-measured
propagation on a live 8.92 MiB proof by polling each peer's own pool (`/tmp/proppropagate.py`):
`.131 +3.4 s`, `.210 +4.2 s`, `.141 +31.7 s` — **~42 s end to end**, against the ~480 s the 180 was sized
for. At 6.0 s/block, **60 blocks = ~6 min = 8.6× the worst case**, and cursor 46967 then landed at
**exactly** its 47078 target. Not lower: an exact-landing tx must be held by whoever produces *that
specific block*, and production is ~18 distinct producers per 66 blocks while only 3 peers are pollable.

**The in-flight hold only fired on the cheap path.** It reads `if proof is None and (…)`, so it suppressed
a redundant *bare* settle but never a redundant *proof* — the loop proved first, then skipped the hold.
Invisible while a prove took 300+ s (`_settle_proving` covered the window). At ~12 s it was immediate:
three proves and three 8.92 MiB transactions in **96 seconds** (cursors 46892/46893/46897), all for the
same root, of which only one can ever land. Fixed by gating the prove on `_settle_pending` **and** adding
that condition to the bare-settle hold — without the second half, the pass that notices a landing falls
through to a bare settle and halves the proof rate. Post-fix the ratio is 1:1 (2 built → 2 submitted, 0
"a previous settle-prove is still running", against 25 → 19 with 33 such lines over the day).

The pre-fix duplicates then drained by themselves: because the margin is applied to the **tip at submit**
rather than the cursor, the newest tx lands first, and blocks 47119/47122/47127 — the older duplicates'
targets — carry no settle at all.
