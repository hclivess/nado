"""An update kick that lands on a busy or rate-limited check is retried, not dropped (ops/self_update.queue_recheck).

MEASURED 2026-09-27: after a push, 185.238.249.208 answered a wave kick with `busy` (another check held the lock, and
that check had fetched before the push landed). Nothing retried: its peer hint went into the one-hour cooldown, and it
was still on the previous commit 12 minutes later with update_available false and nothing blocking. Pins, with
check_and_update scripted and the clock fast-forwarded: busy and rate_limited each queue ONE deferred check (after the
rate-limit window, or _BUSY_RETRY_S); a deferred check that is busy again re-queues, at most _RECHECK_MAX times; at most
one re-check is pending at once; any other answer queues nothing; and the /update handler and the peer-hint check both
route their result through it.

Run: python3 tests/test_update_kick_never_lost.py
"""
import os, sys, tempfile, time, threading
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-kick-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ops import self_update as SU

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


slept, calls = [], []
real_sleep = time.sleep
SU.time.sleep = lambda s: slept.append(s)           # the deferred thread's waits are recorded, not waited


def run(script):
    """Feed check_and_update the given answers in order; return the triggers it was called with."""
    del calls[:]; del slept[:]
    answers = list(script)
    SU.check_and_update = lambda trigger: (calls.append(trigger), answers.pop(0) if answers else {"status": "up_to_date"})[1]
    SU._recheck_pending = False


def settle():
    for _ in range(200):
        if not SU._recheck_pending and not [t for t in threading.enumerate() if t.name == "update_recheck"]:
            return
        real_sleep(0.01)


run([{"status": "updated"}])
check("a busy kick queues a deferred check", SU.queue_recheck({"status": "busy"}) is True)
settle()
check("...which runs after _BUSY_RETRY_S and lands the update", calls == ["deferred"] and slept[:1] == [SU._BUSY_RETRY_S],
      (calls, slept))

run([{"status": "up_to_date"}])
SU.queue_recheck({"status": "rate_limited", "retry_in_s": 14})
settle()
check("a rate-limited kick waits out the window, then checks", calls == ["deferred"] and slept[:1] == [15], (calls, slept))

run([{"status": "busy"}, {"status": "busy"}, {"status": "updated"}])
SU.queue_recheck({"status": "busy"})
settle()
check("a deferred check that is busy again re-queues until it gets through", calls == ["deferred"] * 3, calls)

run([{"status": "busy"}] * 50)
SU.queue_recheck({"status": "busy"})
settle()
check("...but at most _RECHECK_MAX times", len(calls) == SU._RECHECK_MAX, len(calls))

run([])
for st in ("updated", "up_to_date", "blocked", "disabled"):
    check(f"'{st}' queues nothing", SU.queue_recheck({"status": st}) is False)
check("a malformed answer queues nothing", SU.queue_recheck(None) is False and SU.queue_recheck("busy") is False)

run([{"status": "up_to_date"}])
SU._recheck_pending = True                          # one already waiting
check("at most one re-check is pending at once", SU.queue_recheck({"status": "busy"}) is False)
SU._recheck_pending = False

src = open(os.path.join(ROOT, "nado.py")).read()
i = src.index("async def update_node(request):")
body = src[i:i + 2500]
check("/update routes its answer through queue_recheck", "self_update.queue_recheck(result)" in body)
check("the peer-hint check does too", "queue_recheck(check_and_update(\"peer-hint\"))" in open(os.path.join(ROOT, "ops", "self_update.py")).read())

print("ALL PASS — an update kick is retried, never dropped" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
