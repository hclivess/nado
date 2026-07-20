"""
The node's health self-report (loops/message_loop.MessageClient.health_report).

WHY THIS EXISTS: on 2026-07-20 the chain stopped finalizing for about an hour and a half — every block's
exec summary was failing, so no height got a settle binding — and this report said **NODE HEALTHY** the
entire time. Peers were linked, blocks were arriving on schedule, the tip was in the majority, ports were
open, sync mode was normal. Every component it checked was genuinely fine; it simply did not check whether
the chain was still FINALIZING, which was the one thing that had stopped. Worse, the fix for the crash had
been committed to the checkout 34 minutes before anyone noticed, while the process kept running the broken
code, and nothing reported that either (`update_available` only compares against origin as of the last
fetch, so a locally-committed repair is invisible to it).

So this pins the two checks added afterwards, and above all `t_the_2026_07_20_incident_is_not_healthy`,
which asserts the exact shape of that outage does not roll up to "healthy".

Run: python3 tests/test_health_report.py
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from loops.message_loop import MessageClient

fails = 0


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


class _Mem:
    """Just the attributes health_report reads — a healthy node by default, so each test perturbs ONE
    thing and the roll-up change is attributable to it."""
    def __init__(self, **kw):
        self.peers = ["p"] * 12
        self.unreachable = {}
        self.since_last_block = 6
        self.block_time = 6
        self.latest_block = {"block_number": 21900, "block_hash": "aa"}
        self.can_mine = True
        self.emergency_mode = False
        self.mode = "produce"
        self.finalized_height = 21855          # 45 behind == exactly finality_depth
        self.finality_depth = 45
        self.terminate = True
        self.__dict__.update(kw)


class _Cons:
    def __init__(self, majority="aa", pct=100, members=12):
        self.majority_block_hash = majority
        self.block_hash_pool_percentage = pct
        self.block_hash_pool = {i: "aa" for i in range(members)}


class _Clock:
    """A monotonic clock the test drives. health_report measures how long finality has been FROZEN, so it
    keeps a little state across calls — which means a freeze test has to reuse ONE client and advance time
    by hand rather than build a fresh one per call."""
    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def __getattr__(self, k):
        import time as _t
        return getattr(_t, k)


def client(mem=None, cons=None):
    c = MessageClient.__new__(MessageClient)          # no thread, no sockets
    c.memserver = mem or _Mem()
    c.consensus = cons or _Cons()
    return c


def report(mem=None, cons=None):
    return client(mem, cons).health_report()


def worst_of(rep):
    levels = [lvl for lvl, _ in rep.values()]
    return "down" if "down" in levels else ("warn" if "warn" in levels else "ok")


# ---- finality --------------------------------------------------------------------------------------
def t_healthy_finality_is_ok():
    rep = report()
    assert rep["Finality"][0] == "ok", rep["Finality"]
    assert worst_of(rep) == "ok", rep


def t_finality_lag_escalates():
    """Lag alone still escalates, for the case where a node comes up already far behind."""
    for fin, want in ((21900 - 45, "ok"), (21900 - 90, "ok"),      # <= 2x depth
                      (21900 - 91, "warn"), (21900 - 180, "warn"),  # <= 4x depth
                      (21900 - 181, "down"), (21900 - 900, "down")):
        lvl = report(_Mem(finalized_height=fin))["Finality"][0]
        assert lvl == want, f"lag {21900 - fin}: expected {want}, got {lvl}"


def t_a_frozen_floor_is_caught_early():
    """The real signal. Finality stops while the tip keeps moving — flagged in MINUTES, while the lag is
    still far too small for any depth multiple to notice."""
    import loops.message_loop as ML
    clock, real = _Clock(), ML.time
    ML.time = clock
    try:
        mem = _Mem(finalized_height=21855)
        c = client(mem)
        assert c.health_report()["Finality"][0] == "ok"
        # the tip advances; the floor does not
        for elapsed, want in ((60, "ok"), (150, "warn"), (400, "down")):
            clock.t = 1000.0 + elapsed
            mem.latest_block = {"block_number": 21900 + elapsed // 6, "block_hash": "aa"}
            got = c.health_report()["Finality"]
            assert got[0] == want, f"frozen {elapsed}s: expected {want}, got {got}"
        assert "FROZEN" in c.health_report()["Finality"][1]
        # and it CLEARS the moment the floor moves again
        mem.finalized_height = 21900
        assert c.health_report()["Finality"][0] == "ok", "recovery not detected"
    finally:
        ML.time = real


def t_syncing_does_not_cry_wolf():
    """A node catching up legitimately runs a huge finality gap; that must not read as a dead chain."""
    rep = report(_Mem(finalized_height=0, emergency_mode=True))
    assert rep["Finality"][0] == "warn", rep["Finality"]
    assert "syncing" in rep["Finality"][1]
    # but the SAME gap outside emergency sync is a real failure
    assert report(_Mem(finalized_height=0))["Finality"][0] == "down"


def t_the_2026_07_20_incident_is_not_healthy():
    """THE REGRESSION. Reproduce the outage exactly: everything the old report looked at was fine, and
    finality was frozen 109 blocks back under a depth-45 rule. Before the Finality component existed this
    rolled up to NODE HEALTHY, which is how it survived 90 minutes."""
    import loops.message_loop as ML
    clock, real = _Clock(), ML.time
    ML.time = clock
    try:
        mem = _Mem(peers=["p"] * 12, unreachable={}, since_last_block=6,
                   latest_block={"block_number": 21905, "block_hash": "aa"},
                   can_mine=True, emergency_mode=False, mode="produce",
                   finalized_height=21796)                # frozen at 21796 — 109 behind
        c = client(mem)
        c.health_report()                                 # first look: starts the freeze clock
        clock.t += 90 * 60                                # ...and it stayed there for ninety minutes
        rep = c.health_report()
    finally:
        ML.time = real
    # every pre-existing component really was green — that is the whole point
    for name in ("Peers", "Blocks", "Consensus", "Ports", "Sync"):
        assert rep[name][0] == "ok", f"{name} was {rep[name]} — the incident shape is not reproduced"
    assert rep["Finality"][0] == "down", rep["Finality"]
    assert worst_of(rep) == "down", "the frozen chain still rolls up as healthy"


# ---- running code ----------------------------------------------------------------------------------
def t_stale_code_is_flagged(monkey=None):
    from ops import self_update
    orig_run, orig_repo = self_update.running_head, self_update.repo_head
    try:
        self_update.running_head = lambda: "aaaaaaaaaaaa"
        self_update.repo_head = lambda *a, **k: "bbbbbbbbbbbb"
        rep = report()
        assert rep["Code"][0] == "warn", rep["Code"]
        assert "RESTART" in rep["Code"][1], rep["Code"]
        assert worst_of(rep) == "warn"
        # matching hashes are fine
        self_update.repo_head = lambda *a, **k: "aaaaaaaaaaaa"
        assert report()["Code"][0] == "ok"
        # and a non-git deploy is a DIFFERENT defect (updatability reports it) — not this one's business
        self_update.running_head = lambda: None
        assert report()["Code"][0] == "ok"
    finally:
        self_update.running_head, self_update.repo_head = orig_run, orig_repo


def t_health_never_raises():
    """Observability must not be able to take the loop down — the report is emitted every 10s forever."""
    from ops import self_update
    orig = self_update.code_is_stale
    try:
        def boom():
            raise RuntimeError("git exploded")
        self_update.code_is_stale = boom
        rep = report()
        assert "Code" in rep and rep["Code"][0] == "ok", rep["Code"]
    finally:
        self_update.code_is_stale = orig


def t_code_is_stale_agrees_with_the_hashes():
    from ops import self_update
    orig_run, orig_repo = self_update.running_head, self_update.repo_head
    try:
        self_update.running_head = lambda: "aaaaaaaaaaaa"
        self_update.repo_head = lambda *a, **k: "aaaaaaaaaaaa"
        assert self_update.code_is_stale() is False
        self_update.repo_head = lambda *a, **k: "cccccccccccc"
        assert self_update.code_is_stale() is True
        self_update.repo_head = lambda *a, **k: None
        assert self_update.code_is_stale() is False, "unknown must not be reported as stale"
    finally:
        self_update.running_head, self_update.repo_head = orig_run, orig_repo


if __name__ == "__main__":
    check("healthy finality is ok", t_healthy_finality_is_ok)
    check("finality lag escalates", t_finality_lag_escalates)
    check("a frozen floor is caught early", t_a_frozen_floor_is_caught_early)
    check("syncing does not cry wolf", t_syncing_does_not_cry_wolf)
    check("THE 2026-07-20 incident is not healthy", t_the_2026_07_20_incident_is_not_healthy)
    check("stale code is flagged", t_stale_code_is_flagged)
    check("health never raises", t_health_never_raises)
    check("code_is_stale agrees with the hashes", t_code_is_stale_agrees_with_the_hashes)
    print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
    sys.exit(1 if fails else 0)
