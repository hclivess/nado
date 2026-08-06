"""A commit that is not RUNNING is not a fix — the node must restart itself into it.

THE GAP. ops/self_update restarts services only after IT applied a fast-forward. When the operator commits
locally and pushes — which is how this fleet is developed — local HEAD already equals origin/main, /update
answers "up_to_date", and nothing restarts. The running processes stay on the old code indefinitely.

code_is_stale() detected exactly this the whole time and produced only a health WARNING, "RESTART to apply".
That warning was on screen for 34 minutes while a finality stall its own fix had already repaired kept
going, and again while nado-exec ran an hour behind the row-commit fix that made records proofs 4x cheaper.
nado-exec is the service that matters most here: it hosts the prover, and it is the one an operator is
least likely to restart by hand.

WHAT MUST NOT HAPPEN, which is what these checks are mostly about:
  • restarting with a DIRTY working tree — the repo dir is a live dev checkout, and loading a half-finished
    edit into a money node is far worse than running one commit behind;
  • restart LOOPING when the restart does not take (unit masked, crash loop, exec fail-stopped on a stale
    native crate) — it must act at most once per head;
  • firing on a checkout observed mid-`git merge`, before HEAD has moved.

These are called, not grepped, with _restart_services monkeypatched so nothing is actually restarted.

Run: python3 tests/test_stale_checkout_restart.py
"""
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ops import self_update as SU  # noqa: E402

fails = 0
restarts = []


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


def setup(running, repo, dirty=False):
    """Point the module at a synthetic (running, repo, dirty) world and clear its memory."""
    del restarts[:]
    SU._stale_since[0] = None
    SU._stale_acted[0] = None
    SU.running_head = lambda: running
    SU.repo_head = lambda: repo
    SU.working_tree_dirty = lambda: dirty
    SU._restart_services = lambda: (restarts.append(True) or ["nado", "nado-exec", "forum"])


def t_current_checkout_does_nothing():
    setup("aaaaaaaaaaaa", "aaaaaaaaaaaa")
    r = SU.apply_stale_checkout(now=0)
    assert r["status"] == "current", r
    assert not restarts, "a current node must never restart"


def t_stale_restarts_after_the_settle_period():
    setup("aaaaaaaaaaaa", "bbbbbbbbbbbb")
    r = SU.apply_stale_checkout(now=0)
    assert r["status"] == "observing", f"first sighting must only observe: {r}"
    assert not restarts, "must not restart on the first observation"
    r = SU.apply_stale_checkout(now=SU._STALE_MIN_AGE + 1)
    assert r["status"] == "restarting", r
    assert restarts, "a persistently stale checkout must restart"


def t_it_restarts_the_exec_node():
    """The whole point of the request: nado-exec must be in the restarted set."""
    setup("aaaaaaaaaaaa", "bbbbbbbbbbbb")
    SU.apply_stale_checkout(now=0)
    r = SU.apply_stale_checkout(now=SU._STALE_MIN_AGE + 1)
    assert "nado-exec" in (r.get("services") or []), f"nado-exec must be restarted, got {r.get('services')}"
    assert "nado-exec" in SU._SERVICES, "and it must be in the service list the updater restarts"


def t_a_dirty_tree_is_never_restarted():
    setup("aaaaaaaaaaaa", "bbbbbbbbbbbb", dirty=True)
    for t in (0, SU._STALE_MIN_AGE + 1, 10 * SU._STALE_MIN_AGE):
        r = SU.apply_stale_checkout(now=t)
        assert r["status"] == "dirty", f"a dirty tree must refuse, got {r}"
    assert not restarts, "NEVER load a half-finished edit into a live node"


def t_it_acts_at_most_once_per_head():
    """If the restart does not take, re-arming forever turns one stuck unit into a restart storm."""
    setup("aaaaaaaaaaaa", "bbbbbbbbbbbb")
    SU.apply_stale_checkout(now=0)
    SU.apply_stale_checkout(now=SU._STALE_MIN_AGE + 1)
    assert len(restarts) == 1
    for t in (SU._STALE_MIN_AGE + 2, 1000, 10000):     # still stale: the restart did not take
        r = SU.apply_stale_checkout(now=t)
        assert r["status"] == "already_restarted", r
    assert len(restarts) == 1, "one restart per head, no storm"


def t_a_new_head_re_arms():
    """Acting once per HEAD, not once per process — a second push must still be applied."""
    setup("aaaaaaaaaaaa", "bbbbbbbbbbbb")
    SU.apply_stale_checkout(now=0)
    SU.apply_stale_checkout(now=SU._STALE_MIN_AGE + 1)
    assert len(restarts) == 1
    SU.repo_head = lambda: "cccccccccccc"              # a newer commit landed
    SU.apply_stale_checkout(now=1000)
    r = SU.apply_stale_checkout(now=1000 + SU._STALE_MIN_AGE + 1)
    assert r["status"] == "restarting", r
    assert len(restarts) == 2, "a NEW head must re-arm"


def t_unknown_hashes_do_nothing():
    """A non-git deploy is a different defect, reported elsewhere. It must not restart-loop here."""
    for run, repo in ((None, "bbbbbbbbbbbb"), ("aaaaaaaaaaaa", None), (None, None)):
        setup(run, repo)
        r = SU.apply_stale_checkout(now=10 * SU._STALE_MIN_AGE)
        assert r["status"] == "current", f"unknown hashes must be inert, got {r}"
        assert not restarts


def t_it_never_raises():
    """It is called from the health loop; observability must not be able to take the node down."""
    setup("aaaaaaaaaaaa", "bbbbbbbbbbbb")

    def boom():
        raise RuntimeError("git exploded")

    SU.repo_head = boom
    r = SU.apply_stale_checkout(now=0)
    assert r["status"] == "error" and "RuntimeError" in r["reason"], r


for nm, fn in [("a current checkout does nothing", t_current_checkout_does_nothing),
               ("stale restarts after the settle period", t_stale_restarts_after_the_settle_period),
               ("it restarts the EXEC node", t_it_restarts_the_exec_node),
               ("a dirty tree is never restarted", t_a_dirty_tree_is_never_restarted),
               ("it acts at most once per head", t_it_acts_at_most_once_per_head),
               ("a new head re-arms", t_a_new_head_re_arms),
               ("unknown hashes do nothing", t_unknown_hashes_do_nothing),
               ("it never raises", t_it_never_raises)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
