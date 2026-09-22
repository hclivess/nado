"""A ROLLBACK NEVER RUNS ON A STALE VERDICT, AND THE SAME BLOCK REFUSED THREE TIMES IS OUR PROBLEM.

2026-09-13, 185.238.249.208. The node was identical to the fleet through 78077 and differed only at its own
tip, 78078. It acted on a cached verdict that said ancestor 77979 — stale by ~100 blocks, because the node
had kept syncing after the measurement — rolled back 99 shared, correct blocks, failed to re-apply what it
had just reverted, restored its own branch, benched an honest donor, and did it all again. For an hour.
Nothing escalated, because a failed application returned False ("the donor flow finishes the job") on
every pass.

Two rules, both bound from the real CoreClient so this exercises the shipped code:

  * _fork_state stays TIME-keyed (keying it on the tip made the verdict flap and a 4-node mesh never
    converged); _fresh_ancestor_for_adoption re-measures once, at the moment a rollback is about to run,
    whenever the verdict in hand is about another tip.
  * _note_adopt_validation_failure escalates after ADOPT_FAIL_ESCALATE_AFTER consecutive failures to apply
    THE SAME block at ONE tip; a different block or a moved tip starts over.

Run: python3 tests/test_adopt_escalation_and_stale_verdict.py
"""
import os, sys, tempfile, time

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_aesv_")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)   # leave no /tmp home behind (9,600 leaked by 2026-09-22)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import loops.core_loop as CL                                       # noqa: E402
from loops.core_loop import CoreClient, ADOPT_FAIL_ESCALATE_AFTER  # noqa: E402
from ops import fork_resolution as FR                              # noqa: E402

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
        self.memserver.latest_block = {"block_number": height, "block_hash": f"h{height}"}
        self.memserver.peers = ["p1", "p2"]
        self.memserver.ip = None
        self.logger = _Quiet()
        self.rec_fail = []
        self._note_adopt_validation_failure = CoreClient._note_adopt_validation_failure.__get__(self)
        self._fresh_ancestor_for_adoption = CoreClient._fresh_ancestor_for_adoption.__get__(self)
        self._fork_state = CoreClient._fork_state.__get__(self)
        self._fork_verdict = CoreClient._fork_verdict.__get__(self)

    def _memo_probe(self, peer, h, tip):
        return (f"h{h}", 0)

    def _rec_fail(self, why, **d):
        self.rec_fail.append(why)


# ---------------------------------------------------------------- escalation: same block, same tip
s = Stub(78078)
hits = [s._note_adopt_validation_failure("blk-A") for _ in range(ADOPT_FAIL_ESCALATE_AFTER)]
check(hits[:-1] == [False] * (ADOPT_FAIL_ESCALATE_AFTER - 1) and hits[-1] is True,
      f"the {ADOPT_FAIL_ESCALATE_AFTER}th consecutive failure of the SAME block escalates ({hits})")
check(s._note_adopt_validation_failure("blk-A") is False,
      "...and the count starts over after escalating (the ladder got a clean slate)")

s = Stub(78078)
s._note_adopt_validation_failure("blk-A"); s._note_adopt_validation_failure("blk-A")
check(s._note_adopt_validation_failure("blk-B") is False,
      "a DIFFERENT block failing is a moving branch, not our state — the count restarts")

s = Stub(78078)
s._note_adopt_validation_failure("blk-A"); s._note_adopt_validation_failure("blk-A")
s.memserver.latest_block = {"block_number": 78079, "block_hash": "h78079"}
check(s._note_adopt_validation_failure("blk-A") is False,
      "a moved tip resets the count — a fresh tip is a fresh question")

# ---------------------------------------------------------------- freshness, only where a rollback starts
calls = []
def fake_resolve(**kw):
    calls.append(kw["tip"])
    return {"state": FR.REORG, "ancestor": kw["tip"] - 1, "tip": kw["tip"], "finalized": 0, "probes": 1}

saved = (FR.resolve, CL.get_config, CL.own_ips)
FR.resolve = fake_resolve
CL.get_config = lambda: {"ip": None}
CL.own_ips = lambda: set()
import ops.peer_ops as PO
saved_pp = (PO.seed_peers, PO.probe_block_hash_signed)
PO.seed_peers = lambda: []
PO.probe_block_hash_signed = lambda *a, **k: None
import ops.block_ops as BO, ops.account_ops as AO
saved_b = (BO.get_block_hash_by_number, AO.get_finalized_height, AO.get_hard_finality)
BO.get_block_hash_by_number = lambda n: f"h{n}"
AO.get_finalized_height = lambda: 0
AO.get_hard_finality = lambda: 0
try:
    s = Stub(78000)
    s._fork_state()
    check(calls == [78000], "the first ask measures at our tip")
    s.memserver.latest_block = {"block_number": 78100, "block_hash": "h78100"}
    s._fork_state()
    check(calls == [78000], "the cheap status read is still served from the TTL cache after the tip moved "
                            "(keying it on the tip made the verdict flap)")

    # the verdict in hand is about 78000; we are at 78100; a rollback is about to run
    anc = s._fresh_ancestor_for_adoption(77999)
    check(calls == [78000, 78100], "...but ADOPTION re-measures once, at the current tip, before rolling")
    check(anc == 78099, f"...and uses the FRESH ancestor, not the stale one (got {anc})")

    anc2 = s._fresh_ancestor_for_adoption(78099)
    check(calls == [78000, 78100], "a verdict already about our tip is used as-is — no extra probes")
    check(anc2 == 78099, "...and returned unchanged")

    # the fresh measurement no longer says REORG -> do not roll back at all
    FR.resolve = lambda **kw: {"state": FR.BEHIND, "ancestor": kw["tip"], "tip": kw["tip"], "finalized": 0, "probes": 1}
    s.memserver.latest_block = {"block_number": 78200, "block_hash": "h78200"}
    check(s._fresh_ancestor_for_adoption(78099) is None,
          "when the fresh verdict is not a reorg, adoption gets None and rolls nothing back")
    check(any("verdict changed" in w for w in s.rec_fail), "...and says so on /status recovery_fail")
finally:
    FR.resolve, CL.get_config, CL.own_ips = saved
    PO.seed_peers, PO.probe_block_hash_signed = saved_pp
    BO.get_block_hash_by_number, AO.get_finalized_height, AO.get_hard_finality = saved_b

print(("\nFAILED: " + "; ".join(fails)) if fails else "\nall checks passed")
sys.exit(1 if fails else 0)
