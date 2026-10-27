# Fast finality: what NADO takes from Solana's Alpenglow (design, 2026-10-27)

Agreed 2026-10-21: adopt the voting half of Alpenglow (Votor) after the move to Stwo, not its leader per slot. This doc
is the measurement-backed design that agreement asked for. Nothing here is built; the decision is the operator's.
Redesign is on the table (operator, 2026-10-27: "we can always redesign anything for a better way"), so the question is
the best finality for NADO, not how to bolt Votor on.

## 1. What NADO has today (measured 2026-10-27, betanet-10, heights ~7400)

- **Blocks are not signed.** A block is a pure function of (parent, height, mempool) and carries hashes and roots only.
  A node may attach a detached "winner" signature to a block it built, but it is off the consensus path, an unsigned
  block is valid, and stored blocks do not keep it.
- **Accountability lives in the duty votes.** Each epoch (60 blocks) a 128-seat committee, sampled by stake from the
  epoch's beacon (`DUTY_COMMITTEE_SEATS`), posts signed duty transactions. Each attests the epoch's checkpoint block
  (`attest: {target_epoch, target_hash}`). A checkpoint is justified when attesting seats exceed 2/3; it is finalized
  when it and its child are both justified (`ops/attestation_ops.py`). A double or surround vote is slashable.
- **Two floors.** The rollback floor (`finalized_height`) trails the tip by `finality_depth` = 45 blocks; the stake-backed
  floor (`hard_finality`, from FFG) trails further.

| measured | value |
|---|---|
| block interval (last 360 blocks) | median 6.0 s, mean 6.1 s, p90 7 s |
| duty votes per epoch (last 6 epochs) | 11 to 14, from 17 distinct voters |
| one duty vote on the wire | median 5.5 KB (ML-DSA-44 signature 2,420 B, plus key and fields); max 8.1 KB |
| rollback floor behind the tip | 45 blocks, about 4.6 min |
| stake-backed (FFG) floor behind the tip | median 105.5 blocks (about 10.7 min), max 133 |
| HTTP round-trip, this host to fleet nodes | 25 to 75 ms median; one IPv6 node 1.1 s at p90 |
| nodes at the newest height that disagreed on its hash | 1 of 298 samples (10 min, every 2 s, all 7 nodes) |
| nodes at the newest height at any instant | 57% median (the rest still receiving it) |
| among nodes at the tip, all building the same next block | 65% of samples |

The method: `/status` of all 7 fleet nodes every 2 s for 10 minutes (read-only), and `/get_block` over the last 360
blocks.

## 2. What Votor does, and what of it fits

Votor: stake votes on each slot's block; at least 80% in one round finalizes at once, at least 60% finalizes after a
second round. The thresholds are chosen so a block can finalize in ONE round, which is worth a lot when blocks are
150 to 400 ms apart. The price is the fault model: Alpenglow is safe with at most 20% Byzantine stake (plus up to 20%
offline), where a classic 2/3 quorum tolerates up to 1/3 Byzantine.

What fits NADO: stake votes directly on the block, and a certificate any node can count. NADO is better placed than Solana
for this, because there is no proposer to equivocate: every honest node builds and votes for the identical block, and
the measured disagreement at the tip is 1 sample in 298.

What does not fit:
- **The leader per slot**: NADO has none, by design.
- **Rotor** (block broadcast): NADO gossips transactions, not blocks.
- **The 80%/60% thresholds.** A second voting round costs NADO one round-trip, tens to a few hundred milliseconds,
  against 6-second blocks. Saving that round is not worth giving up a third of the fault tolerance.

## 3. Proposal: chained 2/3 votes every 10th block, by the committee, off-chain

PER-BLOCK FINALITY IS TOO EXPENSIVE, and storing the votes off-chain does not fix it: every vote still reaches every
node. ML-DSA-44's 2,420-byte signature is the floor for each vote (it cannot be aggregated). Traffic per node:

| variant | per node per day, 17 voters (today) | at 128 voters | finality |
|---|---|---|---|
| A: every block, 2 rounds, votes as transactions (5.5 KB) | 2.6 GB | 19.8 GB | ~1 s |
| B: every block, 2 rounds, bare votes (2.5 KB) | 1.2 GB | 9 GB | ~1 s |
| C: every 10th block, 2 rounds, bare | 120 MB | 900 MB | under 1 min |
| **D: every 10th block, 1 round, chained (as FFG), bare** | **60 MB** | **450 MB** | **~2 min** |
| today: 1 vote per epoch (60 blocks), as transactions | 17 MB | 165 MB | ~10.7 min |

(Blocks per day at 6.0 s: 14,400. Operator, 2026-10-27, on variant A: "unacceptable".)

Recommended: D.
1. **Who votes:** the epoch's 128-seat committee, weighted by seats, as FFG counts today. The load is bounded by the seat
   count, not the validator count.
2. **What:** every 10th block is a vote point. A seat holder signs one bare message, `VOTE(h, hash, prev)`, where `prev`
   is the vote point it voted before (FFG's source-target link, at 10-block spacing). A vote point is justified when
   more than 2/3 of seats vote for it, and final when it and the next vote point are both justified, linked. That is
   the classic 1/3 Byzantine bound, with no leader.
3. **Votes are gossip, not transactions,** and nothing is kept once the point is final. They are signed, so two
   conflicting votes from one seat are portable evidence for today's slash transaction.
4. **The on-chain record is unchanged:** the epoch checkpoint attestations stay, so a joining node, a wallet or the
   settlement verifier still checks stake-backed finality from chain data alone. Fast finality raises the rollback
   floor; FFG remains the record and the fallback.
5. **Liveness:** with no certificate (a partition, under 2/3 of seats online), the depth floor and FFG advance as today.

Result: finality in about 2 minutes instead of 10.7, for 60 MB a day per node today.

**Smaller signatures would cut it further.** FN-DSA-512 (Falcon), already built in native/pqsig and waiting for FIPS 206,
signs in 666 bytes (protocol SIG_SCHEME_SIZES), a bare vote of about 0.75 KB instead of 2.5. With it, variant C
(under a minute) costs about 36 MB a day and D about 18 MB.

## 4. Costs and open points, to measure in the build

- **Seat concentration.** With 17 voters, a few hold most of the 128 seats. Two-thirds of seats can mean very few
  operators. That is today's situation too, but per-block finality makes it bite every 6 s. The design needs the seat
  distribution next to it.
- **Mempool agreement only affects speed.** Votes are on the block actually built, so different mempools cost a block
  that one or two nodes then reorg away from, not a safety issue. 1 in 298 measured.
- **Vote verification CPU.** Measured 85 us per ML-DSA-44 verify through the node's native path, so 256 votes per block
  take about 22 ms. It still has to run off the event loop, as transaction verification does.
- **Gate.** A consensus change: `FAST_FINALITY_HEIGHT = <h> if CHAIN_GENERATION == 29 else 1`, a loopback testnet run
  under both rule sets, and the split scenarios of `scripts/testnet/test_fork_resolution.py`. No reroll needed.
- **Hard finality is uncrossable.** A wrong certificate would freeze a node on a dead branch. So certificates are
  counted only from the epoch's committee, frozen at the epoch's start (the registry snapshot), and a 2/3 certificate
  for two different blocks at one height is itself slashing evidence for at least 1/3 of seats.

## 5. Decision (operator, 2026-10-27): NOT ADOPTED, it does not scale

"if it doesn't scale it's shit." Vote-based fast finality costs traffic linear in the number of voters at every vote
point, because ML-DSA signatures cannot be aggregated: 60 MB a day per node today grows to 450 MB at 128 voters, and
per-block votes to gigabytes. Today's epoch checkpoint votes stay as they are: one vote per seat per epoch, bounded by
the 128-seat committee, constant in the validator count.

The only route that would scale is a constant-size certificate: one proof that more than 2/3 of seats signed, verified
in place of the signatures. With post-quantum signatures that means proving ML-DSA (or FN-DSA) verification inside a
STARK, NADO's open in-circuit gap (memory: ML-DSA verify-AIR plan). If that lands, revisit this doc. Not adopted
either way: a leader per slot, Rotor, Votor's 80%/60% thresholds, and signature-free consensus.
