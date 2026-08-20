# Consensus mechanics every engineer here must know

Distilled from the 2026-08-19/20 incident chain: a settlement quorum frozen for 13k+ cursors, a
node living 7 hours in emergency sync, 37-second block applies on near-empty blocks, and a quorum
that re-froze *with every root agreeing*. Each section is a general mechanic, the failure that
proved it here, and the fix that now embodies it. Grep the named commits for the code.

---

## 1. Every layer that finalizes a hash must cross-check a peer pool

**Mechanic.** A deterministic replica computing a root in isolation has no way to know it diverged.
"Deterministic" is a property of the *code*; the *state* diverges anyway — through timing-dependent
writes, retention differences, replay gaps, rollback asymmetry. The L1 always knew this (block hash
pool, status pool, snapshot pool). Any layer added later inherits the same obligation the moment it
finalizes anything.

**Failure.** The exec (L2) layer computed dividend accrual in the poll epilogue — at *batch
boundaries*, which differ per node's fetch timing. Same blocks, different accrual interleaving,
different roots. No pool compared exec roots, no alarm fired, and the settlement quorum silently
starved for 13,000+ cursors before anyone looked.

**Embodied fix.** Canonical per-block accrual (roots became a pure function of the block sequence);
`SETTLE ROOT CONFLICT` alarm the moment two attesters disagree; `boundary_roots` + `/exec/roots` +
`_root_pool_probe` (EXEC ROOT OUT OF MAJORITY within ~one epoch); snapshot-digest pool alarm on L1.

**Rule.** New consensus-bearing layer ⇒ same-day: root pool, out-of-majority alarm, divergence
self-disqualification. Not later. Later is 13k cursors.

---

## 2. A quorum needs agreement on the voting POINT, not just the value

**Mechanic.** Votes only aggregate when they name the identical thing. If voters pick their own
checkpoint positions, honest voters with *identical state* still never form a quorum — their votes
land one tick apart and each stands alone.

**Failure.** After the roots were fixed, the quorum re-froze anyway: attesters settled at
free-running checkpoint cursors — measured f58d at cursor 84585 and 7174 at 84584 **with the same
root**, one apart, forever. Combined with stake concentration (10/4/1 shares after auto-bond
compounding), no coinciding pair reached the strict 2/3.

**Embodied fix.** Bare settle attestations quantize to the latest epoch-boundary cursor
(`ee3272db`): every exec derives the same `k×EPOCH_LENGTH` cursors by construction, so all
settlers meet on identical `(cursor, root)` pairs every epoch. First unanimous 15/15 justification
landed within one epoch of the deploy.

**Rule.** Any attestation scheme must define the checkpoint schedule *in protocol* (a pure function
of chain position), never leave it to node-local cadence.

---

## 3. Per-block cost must not scale with chain age

**Mechanic.** Anything the hot path recomputes over "all state so far" makes block N cost O(N),
and the chain's total work O(N²). It feels fine for months, then the fleet quietly slides from
comfortable to unable to keep pace — and the slide *looks like* network problems, host load,
anything but the real cause.

**Failure.** Every block verification recomputed `l1_state_root` — a merkle walk over the whole
consensus state (~100k rows at h84.5k). Measured 31% of ALL process CPU, ~3.5s per block, on
near-empty blocks. Six row families grow forever inside the root: RANDAO commits/reveals, FFG
attestations, `att:` meta rows, `divnull`, settlements, `epochw`.

**Embodied fix (mitigation).** Leaf-digest cache in `snapshot_ops.merkle_root` (`497cc816`): only
~a dozen rows change between walks, so unchanged rows cost a dict hit — 9× on the leaf phase,
bit-identical root. **The row growth itself is consensus-bound and remains**: retention windows
are a REQUIRED gen-22 reroll item (see SCHEDULED_CLEANUPS.md, "STATE-ROOT ROW GROWTH").

**Rule.** For every per-block computation ask: *what does its input set grow with?* If the answer
is "chain age", either make it incremental, cache the unchanged part, or bound the input set by
protocol retention — and re-ask at every feature that adds a row family to the root.

---

## 4. Amplifiers: how "slow" becomes "stuck"

Two mechanics turned a 3.5s cost into hour-long outages:

**4a. Derived-read caches need a herd lock.** A cache keyed on the global write generation
invalidates on *every* write txn. After each one, every API worker missed simultaneously and
recomputed the expensive derived value (the `latest_settled` walk) **in parallel** — a dozen
GIL-serialized copies starving the consensus thread to 37s/block. Fix (`e2396baf`): double-checked
lock; one compute per generation, the herd reads the cache. **Rule:** expensive derived read +
broad invalidation key ⇒ compute-once lock, always.

**4b. Sync-loop exits need hysteresis against a moving target.** The emergency loop's only exit
required momentarily holding the *exact* heaviest advertised tip. Each pass costs a round-trip +
fetch + verify, so against a chain producing every ~6-11s the check re-fails by 1-2 blocks
forever: 7h20m continuously in emergency, applying at chain speed the whole time — while casting
no FFG duty votes and starving the same process's API event loop (which froze the exec tail
behind it: one stuck loop, two layers down). Fix (`0a7b251a`): a clean-prefix BEHIND verdict
within `EMERGENCY_EXIT_LAG` blocks of the advertised tip is *propagation, not a fork* — leave,
restart the grace window. Fork evidence never takes the exit. **Rule:** any loop whose exit
condition compares against live, advancing state needs an explicit "close enough" band, or it
never exits.

---

## 5. Failures must name themselves

Every incident above took longer to *find* than to fix, for the same reason: the failing path was
silent. `str(TimeoutError)` is the empty string; a bare `except: pass` around the batch fetch; a
`/peers` refresh that failed quietly and left the fallback iterating an empty list for 15 minutes;
`test | tail` swallowing a failing exit code so a red test got pushed.

**Rule.** Log `type(e).__name__`, never bare `str(e)`. No `except: pass` on any path whose failure
changes behavior. Never pipe a test run whose exit code gates a commit. When a fallback yields
nothing, say so with the count of what it tried ("0 peers known" found the bug instantly).

---

## The one-line summary

Determinism is not consensus. Pool every finalized hash, schedule every voting point, bound every
per-block input set, band every moving-target exit, lock every broad-key cache, and make every
failure say its own name.
