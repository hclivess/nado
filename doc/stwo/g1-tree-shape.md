# G1: the exec-root tree shape, measured (doc/stwo-migration.md 9.5)

Measured 2026-10-19 on the relay host. Route A was chosen 2026-10-18 (doc/stwo-migration.md section 7, item 3); this
records G1's entry measurement for the decision G1 still owes: the shape of the BLAKE2s exec-root tree, which is frozen
at the generation-29 reroll (section 7, item 6).

## Machine

12 vCPU AMD EPYC (QEMU, 2.0 GHz, AVX2, no AVX-512), 47 GiB RAM, load average 6 to 9 during the runs (other services on
the host). Every prove is single-threaded (Stwo built without `parallel`).

## 1. What the live chain touches per settlement span

A settlement span is at most 30 blocks (`SETTLE_EVERY = min(SETTLE_PROOF_MAX_SPAN, EPOCH_LENGTH // 2)`).

**Calls, from block bodies.** Every blob transaction in the 60,000 blocks before 274,127 (about 4.7 days), read with
GETs of the relay's public `/get_block`: 74 contract calls, 2,396 `collect_dividend` records ops, 3 upgrades. Of 2,000
thirty-block windows, 1,956 had no call; the busiest had 5 (autogame `march` x3, `plan`, `advance`). Most called:
the prediction market (`void` 29, `create_market` 15), `faucet.reward` 16.

**State, from the exec node's own checkpoints.** The exec node writes `exec_state.json~ckpt~default~<height>.json`
every 500-10,000 blocks. Copies were diffed (plain JSON; no node module imported):

| interval | blocks | contract slots changed | record rows changed (dividend, bridge, withdrawals) |
|---|---|---|---|
| 180,000 - 230,000 | 50,000 | 254 | 107 |
| 230,000 - 270,000 | 40,000 | 198 | 102 |
| 270,000 - 272,001 | 2,001 | 0 | 67 |
| 272,001 - 274,000 | 4 x 500 | 0 | 61 - 66 each |

A diff counts a row once however often it changed, so these are lower bounds on writes but exact for distinct leaves.

**Live size.** 2,089 contract storage slots at 274,000 across 27 contracts (1,519 in the prediction market; 15
contracts hold none), plus 80 dividend, 12 bridge and 239 `zk_addrs` rows.

**Busiest span, today.** An epoch boundary re-accrues the dividend rows (about 80), plus at most 5 calls of a few slots
each: **about 130 touched leaves** is a generous figure for the heaviest span the chain has produced.

## 2. Stwo BLAKE2s proving rate

Upstream Stwo at the pin `native/stwo_js` uses (`826591c`, the `stwo-examples` BLAKE2s component: scheduler, 10 round
components, XOR lookup tables), proving 2^k independent BLAKE2s compressions, at the node's `PcsConfig` (log blowup 2,
160 queries, 20 pow bits: `native/stwo_js` `node_config()`, `security_bits()` = 340):

| compressions | prove | verify | proof (size_estimate) | peak RSS |
|---|---|---|---|---|
| 256 | 2.63 s | 13.2 ms | 2.19 MB | 1.04 GB |
| 1,024 | 3.07 s | 13.7 ms | 2.18 MB | 1.13 GB |
| 4,096 | 4.37 s | 13.9 ms | 2.19 MB | 1.50 GB |
| 16,384 | 10.66 s | 13.8 ms | 2.25 MB | 3.00 GB |
| 65,536 | 24.73 s | 14.9 ms | 2.41 MB | 9.35 GB |

About 2.5 s is fixed (the 2^16-row XOR tables). Above that the marginal cost is about 0.33 ms and 0.13 MB of memory per
compression. Verify time and proof size barely move: memory is the limit, then time.

**What this does not measure.** The path wiring (sibling order by key bits, the old/new root pair, the LogUp link from
each compression's output to the next one's input) is not built; this is the hash alone, which is the dominant cost.
The G2/G4 prototype measures the full path update; nothing below depends on the wiring being free, only on it not
reversing a 13x ratio.

## 3. The two shapes at those rates

One path update proves the old and the new root over the same siblings: 2 x depth compressions. In a depth-256 sparse
tree K random keys share only the top log2(K) levels, which saves under 3 % at K = 130, so it is ignored.

| touched leaves per span | depth-256 sparse (512 per update) | compressed, depth ~20 (40 per update) |
|---|---|---|
| 130 (today's busiest) | ~66,500 compressions: ~25 s, ~9.4 GB | ~5,200: ~4.5 s, ~1.5 GB |
| 1,000 | ~512,000: one proof would need ~70 GB, more than this host has | ~40,000: ~17 s, ~6 GB |
| 10,000 | out of reach without splitting | ~400,000: needs splitting |

"Depth ~20" is a compressed sparse tree (a leaf sits at the shortest prefix of its key that no other key shares) sized
for a million live leaves; today's 2,100 slots would sit about 12 levels deep. Its path length varies with the keys
around it, so the circuit proves a path up to a fixed maximum depth with a selector per level.

## 4. Recommendation

**The compressed sparse tree.** It is about 13x cheaper per update at today's size, stays provable on one machine to
roughly 8x today's busiest span where depth-256 already needs 9 GB, and the gap widens with use.

What it costs, all frozen at the reroll with the root:
- a leaf's position depends on the keys around it, not on its key alone, so an exit proof and the settle statement carry
  the path's length and the prefix it stops at; the node's path verifier checks both;
- an insert can split a leaf into an internal node, and a delete can collapse one: the update rules are code the
  depth-256 tree does not need, and they get their own forgery tests in G2 (a forged split, a forged collapse, a path
  that stops early) before any gate uses them;
- the carry recomputes the root in the new shape on two machines, as G2's exit test already requires.

Kept as is: BLAKE2s, one compression per internal node (two 32-byte children = one 64-byte block), leaves
`H(dom, pos, value)`.

**Decided 2026-10-19 by the operator: the compressed sparse tree** (section 7, item 6). G2 builds on it.
