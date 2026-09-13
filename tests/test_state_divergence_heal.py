"""A STATE DIVERGENCE MUST NOT BE BLAMED ON THE DONOR.

`Block N state_root <theirs> != our as-of-parent L1 state <ours>` means we agree with the producer on
every block HASH through N-1 and disagree about what APPLYING them produced. state_root is inside the
block-hash preimage, so agreeing on a hash IS agreeing on the state it commits — the divergence entered
while applying our own tip, and no peer caused it or can serve a fix for it.

The sync leg treated it like any other refusal and called `_reject_heaviest_tip()`. That benches an honest
peer, picks the next one, gets the identical refusal, benches that one too — and never escalates, because
the only handler that understands this error sits on the REORG leg (`_adopt_branch`) and a BEHIND verdict
never reaches it. classify() reads block hashes, the hashes agree, so the verdict is BEHIND forever.

MEASURED LIVE 2026-09-13. This node — 38.242.201.206, which is `get.nadochain.com`, the wallet's DEFAULT
relay — sat wedged at block 69284 for 11 hours while the fleet reached 74400: 5,100 blocks behind,
oscillating build-69285 / refuse / roll back, with every recovery route silently unreachable and the
production relay serving stale state to every wallet.

    recovery      : {state: behind, ancestor: 69284, tip: 69284}    <- arithmetically true, useless
    last_block_reject: Block 69285 state_root 7de2431d... != our as-of-parent L1 state db2f2ee4...

Cause: DEVICE_BIND_DEVKEY_ALL_EPOCH stamped an extra account field on leased-class registration, gated at
an epoch the chain had already passed, on a node that was the only one running the code. Block 69284
carried an Android registration. But the CAUSE is not what this test pins — any state divergence produces
this wedge, and the next one will have a different cause.

Run: python3 tests/test_state_divergence_heal.py
"""
import os, sys, tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_sdh_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


STATE_ERR = ("Block 69285 state_root 7de2431d9aa8468d != our as-of-parent L1 state db2f2ee4846f92c0 — "
             "our state diverged from the producer; refusing to extend (would fork state while agreeing "
             "on the block body)")
FORGED_ERR = ("Block 66084 hash mismatch: content hashes to 5918016f35867199 but peer claims "
              "7880e716b8fa2610 — refusing (forged or corrupt block; would fork us)")


class FakeMemserver:
    def __init__(self, height, reject_error, floor=69120):
        self.latest_block = {"block_number": height, "block_hash": f"h{height}",
                             "parent_hash": f"h{height - 1}", "block_transactions": [{"txid": "t1"}]}
        self.last_block_reject = {"height": height + 1, "error": reject_error}
        self.terminate = False
        self.rollbacks = 0
        self.max_rollbacks = 40
        self.merged = []
        self._floor = floor

    def merge_transaction(self, tx, user_origin=False):
        self.merged.append(tx)


class FakeCore:
    """The two methods under test, lifted onto a stub so the test needs no chain database.

    They are bound from the real class, so this exercises the SHIPPED code, not a copy of it."""

    def __init__(self, memserver, rollback_impl):
        from loops.core_loop import CoreClient
        self.memserver = memserver
        self.logger = _QuietLogger()
        self.struck = 0
        self.rec_fail = []
        self._rollback_impl = rollback_impl
        self._state_diverged_reject = CoreClient._state_diverged_reject.__get__(self)
        self._heal_state_divergence = CoreClient._heal_state_divergence.__get__(self)

    def _reject_heaviest_tip(self):
        self.struck += 1

    def _rec_fail(self, why, **detail):
        self.rec_fail.append(why)


class _QuietLogger:
    def __getattr__(self, _):
        return lambda *a, **k: None


def run_with_rollback(core, impl):
    """Patch rollback_one_block for the duration of one heal call."""
    import loops.core_loop as CL
    original = CL.rollback_one_block
    CL.rollback_one_block = impl
    try:
        return core._heal_state_divergence()
    finally:
        CL.rollback_one_block = original


# ---------------------------------------------------------------- telling the two refusals apart
core = FakeCore(FakeMemserver(69284, STATE_ERR), None)
check(core._state_diverged_reject(),
      "a state-root refusal is recognised as OUR fault")

core = FakeCore(FakeMemserver(66083, FORGED_ERR), None)
check(not core._state_diverged_reject(),
      "a forged/corrupt block is NOT read as our fault (the donor still gets struck)")

core = FakeCore(FakeMemserver(100, ""), None)
check(not core._state_diverged_reject(), "no refusal recorded -> not a state divergence")

# ---------------------------------------------------------------- the heal reverts exactly one block
ms = FakeMemserver(69284, STATE_ERR)
core = FakeCore(ms, None)
rolled = []


def ok_rollback(logger, block, depth=1):
    rolled.append((block["block_number"], depth))
    n = block["block_number"] - 1
    return {"block_number": n, "block_hash": f"h{n}", "parent_hash": f"h{n - 1}",
            "block_transactions": []}


check(run_with_rollback(core, ok_rollback) is True, "the heal reports that it reverted a block")
check(rolled == [(69284, 1)], f"it reverts OUR TIP, once, at depth 1 (got {rolled})")
check(ms.latest_block["block_number"] == 69283, "the tip moves back to the agreed parent")
check(core.struck == 0, "NO peer is struck — the failure is ours, not the donor's")
check(ms.merged == [{"txid": "t1"}],
      f"revert symmetry: the reverted block's txs are re-mined, never dropped (got {ms.merged})")

# ---------------------------------------------------------------- it is bounded, and escalates
from loops.core_loop import STATE_HEAL_MAX_DEPTH  # noqa: E402

ms = FakeMemserver(69284, STATE_ERR)
core = FakeCore(ms, None)
attempts = 0
for _ in range(STATE_HEAL_MAX_DEPTH + 3):
    # every attempt re-diverges at the SAME height, which is the "deeper than one block" case
    ms.latest_block = {"block_number": 69284, "block_hash": "h69284", "parent_hash": "h69283",
                       "block_transactions": []}
    if run_with_rollback(core, ok_rollback):
        attempts += 1
check(attempts == STATE_HEAL_MAX_DEPTH,
      f"it rolls back at most STATE_HEAL_MAX_DEPTH times at one height (got {attempts})")

# THE WALK-DOWN. Shipped to production and caught there, not here: a rollback SUCCEEDS and lands on a new
# height, and keying the attempt counter on the current height reset it every single time. Every attempt
# logged "1/3" and the bound never bit — this node descended 16 blocks in 70 seconds toward its finality
# floor, one block per pass. The burst must be anchored where it STARTED and end only when the tip climbs
# back ABOVE that, because rolling further down is never evidence of progress.
ms = FakeMemserver(69284, STATE_ERR)
core = FakeCore(ms, None)
walked = 0
for _ in range(STATE_HEAL_MAX_DEPTH + 12):
    if run_with_rollback(core, ok_rollback):     # each call lands the tip one lower, as the real one does
        walked += 1
check(walked == STATE_HEAL_MAX_DEPTH,
      f"a DESCENDING divergence is bounded too — no walk to the finality floor (reverted {walked})")
check(ms.latest_block["block_number"] == 69284 - STATE_HEAL_MAX_DEPTH,
      f"...so the tip falls by at most the window (got {ms.latest_block['block_number']})")
check(any("re-anchor" in w for w in core.rec_fail),
      "then it escalates to the re-anchor ladder instead of walking down to the floor")
check(core.struck == 0, "still no peer struck while escalating")

# ---------------------------------------------------------------- the floor is still the floor
from rollback import FinalityViolation, MissingParentError  # noqa: E402

ms = FakeMemserver(69130, STATE_ERR)
core = FakeCore(ms, None)


def floor_refuses(logger, block, depth=1):
    raise FinalityViolation("would revert a hard-finalized block")


check(run_with_rollback(core, floor_refuses) is False,
      "a rollback the floor refuses is not reported as a heal")
check(ms.latest_block["block_number"] == 69130, "and the tip does not move")
check(core.struck == 0,
      "a finality refusal benches NOBODY — the chain we need must stay visible to the escalation")
check(any("hard floor" in w for w in core.rec_fail), "the refusal is published to /status recovery_fail")

ms = FakeMemserver(69284, STATE_ERR)
core = FakeCore(ms, None)


def no_parent(logger, block, depth=1):
    raise MissingParentError("parent not on disk")


check(run_with_rollback(core, no_parent) is False, "a missing parent is not reported as a heal")
check(any("resync" in w for w in core.rec_fail), "...and it asks for a resync")

print(("\nFAILED: " + "; ".join(fails)) if fails else "\nall checks passed")
sys.exit(1 if fails else 0)
