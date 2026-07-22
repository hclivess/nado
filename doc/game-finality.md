# Game finality — the four states a move passes through

Every on-chain game action (a bet, a commit, a settle) climbs the same ladder from "the player clicked"
to "no power on earth can change this." A game that treats a lower rung as if it were a higher one either
**feels frozen** (waits for finality when provisional would do) or **lies** (shows a win that a reorg can
still take back). This note names the rungs, says what each one actually guarantees, and gives the one
rule that decides which rung a given piece of UI should gate on.

The whole reason NADO games feel instant is that **reads are provisional by default** while **value is only
irreversible at finality** — the split below is what lets both be true at once.

## The ladder

| State | What it means | When | Can still change? | Who observes it |
|---|---|---|---|---|
| **mempool** | The node accepted the signed tx into its pool (`submit_transaction` → `result:true`). Not in any block. | ~instant on submit | **Yes** — pool wipe, eviction, reorg, or `max_block` expiry all drop it with no trace | the submitter (the sign returned ok) |
| **provisional** | The tx is in an *unfinalized* block; the exec node's provisional clone (finalized state + the unfinalized L1 tail, `?provisional=1`) reflects its effect. | ~1 block (~6s) after inclusion | **Yes** — a reorg of the unfinalized tail can revert it; the tx re-lands (a visible retry), never silent | every game client (this is the default read) |
| **final** | The containing L1 block is FFG-finalized (past the finality window, `FINALITY_DEPTH`). The *finalized* exec state — not the clone — reflects it. | ~`FINALITY_DEPTH` blocks | **No** (barring a consensus-level failure) | any node, from the finalized state; cross-node agreement |
| **anchored** | The exec node has posted a `settle` attestation of `(cursor, state_root)` to L1, so the state transition is committed and independently re-derivable/provable from the L1 blob order. | after finality, on the settle cadence | **No** — and now *verifiable* by anyone: recompute the root from L1 and it matches | anyone auditing, without trusting a node |

`mempool → provisional` is transport latency (inclusion delay: a tx carries `min_block = tip + TX_INCLUSION_DELAY`,
so it *cannot* be mined for a couple of blocks — see `construct_blob_tx`). `provisional → final` is the
finality window. `final → anchored` is the exec settle/proof cadence (`execnode` SETTLE; verified in
`_verify_settled`). Each gap is real time; **no amount of retrying compresses it**, and re-submitting a tx
that is merely climbing the ladder just spams a duplicate that cannot land any sooner.

## Randomness has the same ladder — one rung offset

A beacon/`BLOCKHASH` game pins its result to a *future* block hash nobody can predict at bet time. That input
hash climbs the ladder too, and the RESULT can be no more settled than its input:

- The client can **preview** the outcome the instant the input block is **provisional** — the provisional
  clone records unfinalized tail block hashes, so `BLOCKHASH(h)` resolves there ~immediately. This is why a
  leg animates the moment the dice block appears.
- But the **authoritative** result is only stable once the input block is **final**: `BLOCKHASH` /
  `BEACON` read *finalized* L1 inputs (`record_block_hash` is documented finalized-only; a beacon is final
  once the cursor enters its epoch). A provisional preview that a tail-reorg changes is a *visible* re-roll
  of a public, on-chain-validated value — never silent unfairness — which is exactly why previewing on
  provisional is safe for public randomness but **not** for hidden information (hole cards read a pre-final
  hash could show a different hand at showdown; those use finalized reads).

## The rule: gate each piece of UI on the *lowest* rung that is safe for it

Snappy is a feature. Default to the earliest rung a given decision can tolerate:

- **Optimistic UI / "sent"** → **mempool**. The moment the sign returns ok, say so and let the player move
  on. Cost of being wrong: a rare visible "it dropped, retrying," which the pending-guards already handle.
- **Progressing your own flow** (open the next input, animate, drain a queue) → **provisional**. The client
  already reads provisional state; this is the default and what makes the march continue "the second
  anything is in flight." A queued next-leg commit waits for the previous leg to be **provisionally**
  settled — it reverts before then (the chain still shows the leg open), so provisional is its *floor*, not
  caution. It must NOT wait for finality.
- **Paying value OUT irreversibly** (a withdrawal, crediting a leaderboard the faucet pays on, anything you
  cannot claw back) → **final**, and where an auditor must be convinced without a node, **anchored**.

The failure mode this note exists to prevent, stated plainly: **do not assume a transaction is settled the
moment it enters the mempool.** The state that makes it *look* settled within a block is *provisional*, and
true settlement lags. Build flow-gating on provisional; reserve finality/anchoring for value that must never
reverse; and never "retry harder" to beat a gap that is physics.

## How the SDK exposes the rungs

`static/nadodapp.js` is where games read these without re-implementing them:

- **mempool** — `dapp.busy(phase,…)` is armed from the click; `dapp.accepted(phase,…)` is true once the
  sign returned ok and the tx was submitted (the earliest "it's really on its way").
- **provisional** — every `dapp.storage()` / `dapp.refresh()` read is provisional (`?provisional=1`), and
  `dapp.blockHashes(h, {fast:true})` fetches the pre-final tail hash. A game's `settleInflight(landedFn)`
  check reads this provisional state — so "landed" here means *provisionally applied*.
- **final / anchored** — a finalized read (no `?provisional`) and the exec settle attestation; used only for
  value-out decisions.

Auto-settlement (`dapp.autoCollect`) and its manual counterpart (`dapp.settleNow`) fire a permissionless
settle as soon as its input is **provisional**, and are scoped so an unrelated pending action never starves a
settle that is provisionally ready — the settle for one leg must not wait behind the next leg's commit.
