"""A NODE THAT CANNOT EVALUATE THE RULES AT ITS TIP DOES NOT PRODUCE — AND FILLS THE HOLE ITSELF.

The split of 2026-09-13: two rolling nodes re-anchored from a snapshot were left with a hole inside the
challenger-draw window (the restore path skips deep bodies on rolling nodes), kept producing, drew from
the blocks they had when an enrolment landed, and raced ahead on a state root nine complete nodes could
not reproduce. The correct majority froze behind their heavier tip. Weight can never resolve that: both
branches add the same weight per block, so the minority's lead is permanent.

What resolves it without an operator: the gap node STOPS PRODUCING (weight stops accruing on the bad
branch), the majority overtakes, and the ordinary heavier-donor reorg brings the node back. The same check
that stops production starts the repair, so the condition clears itself.

Both methods under test are bound from the real CoreClient, so this exercises the shipped code.

Run: python3 tests/test_rules_evaluable_gate.py
"""
import os, sys, tempfile, time

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_reg_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import loops.core_loop as CL                       # noqa: E402
from loops.core_loop import CoreClient, RULES_EVAL_RECHECK_S  # noqa: E402
from ops import transaction_ops as TO             # noqa: E402
from protocol import DEVICE_ATTEST_EK_PROVEN_HEIGHT, EPOCH_LENGTH  # noqa: E402

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


class _Quiet:
    def __getattr__(self, _):
        return lambda *a, **k: None


class Stub:
    def __init__(self, height):
        self.memserver = type("M", (), {})()
        self.memserver.latest_block = {"block_number": height}
        self.memserver.peers = ["p1"]
        self.memserver.port = 9173
        self.memserver.ip = None
        self.logger = _Quiet()
        self.rec_fail = []
        self.fills = []
        self._rules_evaluable_at_tip = CoreClient._rules_evaluable_at_tip.__get__(self)
        self._fill_window_gaps_now = CoreClient._fill_window_gaps_now.__get__(self)

    def _rec_fail(self, why, **d):
        self.rec_fail.append((why, d))

    def _fill_window_gaps(self, lo, hi):
        self.fills.append((lo, hi))


def with_draw(raising):
    """Swap the draw the gate calls: raise ProofUnavailable, or answer."""
    def fake(h):
        if raising:
            raise TO.ProofUnavailable(f"challenger draw needs block {h - 3000}")
        return {"a": 1, "b": 1, "c": 1}
    return fake


TIP = max(DEVICE_ATTEST_EK_PROVEN_HEIGHT, 60) + 7 * EPOCH_LENGTH

# ---------------------------------------------------------------- before the gate: always allowed
s = Stub(max(1, DEVICE_ATTEST_EK_PROVEN_HEIGHT - 5))
orig = TO._proven_challengers
TO._proven_challengers = with_draw(raising=True)
try:
    check(s._rules_evaluable_at_tip() is True, "below the proven-draw gate the rule does not apply")
    check(not s.fills, "...and nothing is fetched for it")
finally:
    TO._proven_challengers = orig

# ---------------------------------------------------------------- complete history: produce, memoised
s = Stub(TIP)
calls = [0]
def counting(h):
    calls[0] += 1
    return {"a": 1, "b": 1, "c": 1}
TO._proven_challengers = counting
try:
    check(s._rules_evaluable_at_tip() is True, "with the whole window the node may produce")
    s._rules_evaluable_at_tip(); s._rules_evaluable_at_tip()
    check(calls[0] == 1, f"a positive answer is memoised for the epoch (draw called {calls[0]}x)")
    check(not s.fills and not s.rec_fail, "...with no fill and no failure published")
finally:
    TO._proven_challengers = orig

# ---------------------------------------------------------------- a hole: no production, fill starts
s = Stub(TIP)
TO._proven_challengers = with_draw(raising=True)
try:
    check(s._rules_evaluable_at_tip() is False, "with a hole in the window the node does NOT produce")
    lo, hi = TO.proven_window(TIP + 1)
    check(s.fills == [(lo, hi)], f"...and it starts filling exactly the window the draw scans {s.fills}")
    check(any("not producing" in w for w, _ in s.rec_fail), "...and says so on /status recovery_fail")
    # the negative is re-asked only after RULES_EVAL_RECHECK_S, not on every pass
    n0 = len(s.fills)
    s._rules_evaluable_at_tip()
    check(len(s.fills) == n0, "a negative answer is not re-asked on the very next pass")
    s._rules_eval_memo = (s._rules_eval_memo[0], False, time.monotonic() - RULES_EVAL_RECHECK_S - 1)
    s._rules_evaluable_at_tip()
    check(len(s.fills) == n0 + 1, "...but IS re-asked once RULES_EVAL_RECHECK_S has passed")
    # the hole is filled -> the gate lifts
    TO._proven_challengers = with_draw(raising=False)
    s._rules_eval_memo = None
    check(s._rules_evaluable_at_tip() is True, "once the window is complete the gate lifts")
finally:
    TO._proven_challengers = orig

# ---------------------------------------------------------------- the refill worker, against fakes
# chain: heights 100..120, hole at 105..108; bodies keyed by hash "h<n>", parent "h<n-1>"
store = {f"h{n}": {"block_number": n, "block_hash": f"h{n}", "parent_hash": f"h{n-1}"} for n in range(100, 121)}
local = {n: store[f"h{n}"] for n in range(100, 121) if not 105 <= n <= 108}
index = {n: f"h{n}" for n in local}
saved, indexed, fetched_hashes = [], [], []

class FakeKV:
    @staticmethod
    def block_index_put_many(pairs): indexed.extend(pairs)
    @staticmethod
    def block_loc_get(h): return 1 if any(b["block_hash"] == h for b in local.values()) else None

def fake_gbn(n): return local.get(n)
def fake_get_block(h): return next((b for b in local.values() if b["block_hash"] == h), None)
def fake_save(body, logger=None): local[body["block_number"]] = body; saved.append(body["block_number"])
async def fake_fetch(src, port, bh, timeout=15):
    fetched_hashes.append((src, bh)); return store.get(bh)

import ops.block_ops as BO
saved_names = {}
for mod, name, val in ((BO, "get_block_number", fake_gbn), (CL, "get_block", fake_get_block),
                       (CL, "save_block", fake_save), (CL, "kv_ops", FakeKV),
                       (CL.snapshot_ops, "fetch_block", fake_fetch), (CL, "own_ips", lambda: set()),
                       (CL, "get_config", lambda: {})):
    saved_names[(mod, name)] = getattr(mod, name)
    setattr(mod, name, val)
import ops.peer_ops as PO
saved_names[(PO, "seed_peers")] = PO.seed_peers
PO.seed_peers = lambda: ["donor"]
try:
    s = Stub(120)
    s._window_fill_progress = {}
    res = s._fill_window_gaps_now(100, 121)
    check(res["gaps"] == 1 and res["fetched"] == 4 and res["unfilled"] == 0,
          f"the worker finds the hole and fetches exactly its 4 bodies ({res})")
    check(sorted(saved) == [105, 106, 107, 108], f"...saving 105..108 ({sorted(saved)})")
    check(all(n in local for n in range(100, 121)), "...so the window is complete afterwards")
    check(sorted(h for h, _ in indexed) == [105, 106, 107, 108],
          "...and every fetched block is index-put so get_block_number resolves it")
    check(fetched_hashes[0][1] == "h108", "it walks DOWN by parent_hash from the block above the hole")
    # a donor that serves a DIFFERENT block for the named hash is refused
    saved.clear(); indexed.clear()
    del local[106]; del local[107]
    async def lying(src, port, bh, timeout=15):
        b = dict(store[bh]); b["block_hash"] = "forged"; return b
    CL.snapshot_ops.fetch_block = lying
    res = s._fill_window_gaps_now(100, 121)
    check(res["fetched"] == 0 and 106 not in local and res["unfilled"] == 2,
          f"a body whose hash does not match the one our chain names is never saved ({res})")
finally:
    for (mod, name), val in saved_names.items():
        setattr(mod, name, val)

print(("\nFAILED: " + "; ".join(fails)) if fails else "\nall checks passed")
sys.exit(1 if fails else 0)
