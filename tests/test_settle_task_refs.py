"""
A detached settle task must be kept ALIVE by a strong reference.

WHY THIS EXISTS. asyncio keeps only a WEAK reference to a running task. The documented consequence (see
asyncio.create_task) is that a task whose last strong reference is dropped may be garbage-collected
mid-await — silently. No result, no exception, no done-callback: it simply stops existing.

The exec node settles DETACHED from the block-application tail (e1000cbd), because awaiting a minutes-long
prove from the tail freezes block application. The detachment was written as:

    _t = asyncio.ensure_future(maybe_settle(session))     # local, overwritten on the NEXT poll
    _t.add_done_callback(_settle_task_done)

Polls happen every few seconds; a settle that starts a prove sits on it for ~240s. So for essentially all
of its life that task's only strong reference was a local variable that had already been reassigned dozens
of times. add_done_callback does NOT keep a task alive either.

OBSERVED LIVE 2026-08-04. A prove completed —

    [settle-prove] cursor=18943 calls=0 net_updates=0 | ... | total 239.9s

— and then nothing followed it. No DA publish, no self-check failure, no "settle task failed", no settle.
Zero proof-carrying settles had EVER been produced despite proves completing. A task that is collected
mid-await produces exactly that signature: silence on every branch, because no branch ever runs.

THE FIX is the documented one: hold the task in a module-level set and discard it on completion.

Run: python3 tests/test_settle_task_refs.py
"""
import asyncio
import gc
import os
import sys
import tempfile
import weakref

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_taskref_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


# ---- the hazard, reproduced ------------------------------------------------------------------------
async def hazard_unreferenced():
    """The OLD shape: the only strong ref is a local that gets overwritten every 'poll'."""
    started = asyncio.Event()
    finished = []

    async def work():
        started.set()
        await asyncio.sleep(0.2)          # stands in for the 240s prove
        finished.append(True)

    t = asyncio.ensure_future(work())
    ref = weakref.ref(t)
    await started.wait()
    t = None                              # <- the next poll reassigns the local
    del t
    for _ in range(3):
        gc.collect()
        await asyncio.sleep(0)
    alive = ref() is not None
    await asyncio.sleep(0.4)
    return alive, finished


async def fixed_referenced():
    """The SHIPPED shape: a module-level set holds the task until it completes."""
    holder = set()
    started = asyncio.Event()
    finished = []

    async def work():
        started.set()
        await asyncio.sleep(0.2)
        finished.append(True)

    t = asyncio.ensure_future(work())
    holder.add(t)
    t.add_done_callback(holder.discard)
    ref = weakref.ref(t)
    await started.wait()
    t = None
    del t
    for _ in range(3):
        gc.collect()
        await asyncio.sleep(0)
    alive = ref() is not None
    await asyncio.sleep(0.4)
    return alive, finished, holder


async def main():
    alive_haz, fin_haz = await hazard_unreferenced()
    alive_fix, fin_fix, holder = await fixed_referenced()

    # The event loop DOES hold a strong ref to a task that is scheduled to run, so an unreferenced task is
    # not guaranteed to vanish on every CPython version — the point is that the FIXED shape is guaranteed
    # to survive, which is the property we actually need.
    check("the referenced task is still alive after gc while awaiting", alive_fix)
    check("the referenced task runs to completion", fin_fix == [True])
    check("the holder releases the task once it finishes", len(holder) == 0)

    # The hazard case is observational, not asserted: the event loop holds its own strong ref to a task
    # that is currently SCHEDULED, so an unreferenced task does not vanish deterministically on every
    # CPython build. That is exactly why this bug was survivable-looking for so long. What we assert is the
    # property we control — the fixed shape survives gc unconditionally.
    print("    (observational) unreferenced task alive after gc: %s, completed: %s"
          % (alive_haz, fin_haz == [True]))

    # The shipped module must actually have the holder set wired up.
    import execnode.execnode as E
    check("execnode exposes the strong-reference holder", isinstance(getattr(E, "_settle_tasks", None), set))

    src = open(E.__file__).read()
    check("the detachment site adds the task to the holder", "_settle_tasks.add(_t)" in src)
    check("...and discards it on completion", "_settle_tasks.discard" in src)
    check("the stale 'detaching cannot pile tasks up' claim is gone",
          "detaching cannot pile tasks up" not in src)
    check("a completed prove now announces itself", "settle-with-proof BUILT" in src)


asyncio.run(main())
print()
print("ALL PASS — a detached settle task cannot be collected mid-prove"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
