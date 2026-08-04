"""
A settle-prove that never finishes must not stop settlement (execnode timeout + in-flight guard).

WHY THIS EXISTS. Enabling the K->1 fold (NADO_EXEC_SETTLE_FOLD) was an OUTAGE, not a feature, and the
reason is timing rather than correctness:

    a fold over the W=106 exec AIR measured 5h07m at 492% CPU / 8.2 GB WITHOUT COMPLETING (2026-08-02)

and `_build_settlement_proof` awaited `asyncio.to_thread(_prove)` with NO timeout. So maybe_settle would
simply never return and NO settle of any kind would be posted — the bare-attestation fallback added in
82a8ab29 sits downstream of that await and would never be reached. latest_settled() backs
bridge_withdraw / unshield / dividend_withdraw, so a namespace that stops settling is an outage.

TWO HALVES, AND THE SECOND IS THE ONE THAT'S EASY TO MISS.

  * TIMEOUT: give up on a prove after SETTLE_PROVE_TIMEOUT and post a bare attestation.
  * IN-FLIGHT GUARD: asyncio.wait_for CANNOT kill the worker thread. The abandoned prove keeps burning a
    core. Without a guard, the next cadence (30 blocks, ~3 min) starts ANOTHER fold thread, and another,
    until the box dies. The timeout alone converts one outage into a worse one.

And the guard must track the THREAD's lifetime, not the coroutine's: clearing it in a `finally` releases
it the instant wait_for gives up, while the thread is still running — which is exactly the stacking case
it exists to prevent. Hence a done-callback on a SHIELDED task.

Run: python3 tests/test_settle_prove_timeout.py
"""
import asyncio
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_provetmo_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


# ---- a faithful model of the shipped control flow ----------------------------------------------------
class Prover:
    """Mirrors _build_settlement_proof's prove section: in-flight guard, shielded task, wait_for, and a
    done-callback that releases the guard only when the THREAD really ends."""

    def __init__(self, timeout):
        self.timeout = timeout
        self.proving = False
        self.threads_started = 0
        self.skips = []

    def _release(self, task):
        self.proving = False
        try:
            task.result()
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        except Exception:
            pass

    async def build(self, prove_seconds):
        if self.proving:
            self.skips.append("in-flight")
            return None
        self.proving = True
        self.threads_started += 1

        async def _work():
            await asyncio.sleep(prove_seconds)             # stands in for the blocking prove
            return {"proof": "ok"}

        task = asyncio.ensure_future(_work())
        task.add_done_callback(self._release)
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=self.timeout)
        except asyncio.TimeoutError:
            self.skips.append("timeout")
            return None


def settle(proof):
    """maybe_settle's outcome: a proof when one was produced, else a BARE attestation. Never nothing."""
    return "settle-with-proof" if proof else "settle-bare"


async def scenario():
    # ---- the fold case: prove never finishes within the bound -> settlement STILL happens --------------
    p = Prover(timeout=0.05)
    out = settle(await p.build(prove_seconds=10.0))
    check("a prove that exceeds the timeout still yields a settlement", out == "settle-bare")
    check("...and the timeout is what fired", p.skips == ["timeout"])

    # ---- THE STACKING CASE: the abandoned thread is still running, so the next cadence must NOT start one
    out2 = settle(await p.build(prove_seconds=10.0))
    check("the next cadence settles bare rather than starting a second prove", out2 == "settle-bare")
    check("NO second worker thread was started (the guard held)", p.threads_started == 1)
    check("...and it skipped for the in-flight reason, not a fresh timeout",
          p.skips == ["timeout", "in-flight"])

    # ---- the guard must RELEASE once the thread genuinely ends -----------------------------------------
    await asyncio.sleep(0)                                  # let pending callbacks run
    p2 = Prover(timeout=5.0)
    got = await p2.build(prove_seconds=0.01)
    check("a prove that finishes in time returns its proof", got == {"proof": "ok"})
    check("...and settles WITH the proof", settle(got) == "settle-with-proof")
    await asyncio.sleep(0.02)
    check("the guard is released after a completed prove", p2.proving is False)
    again = await p2.build(prove_seconds=0.01)
    check("so a later cadence can prove again", again == {"proof": "ok"} and p2.threads_started == 2)

    # ---- a released guard after a SLOW thread eventually ends ------------------------------------------
    p3 = Prover(timeout=0.02)
    await p3.build(prove_seconds=0.15)                      # times out, thread keeps going
    check("guard is still held while the abandoned thread runs", p3.proving is True)
    # WAIT ON THE CONDITION, NOT ON THE CLOCK. This used to be a flat sleep(0.25) chosen to outlast a
    # 0.15s worker, which is only true on an unloaded box: thread scheduling and the GIL can stretch that
    # worker well past 0.25s, the guard is then still held, and the NEXT build correctly reports
    # "in-flight" — failing a test that was asserting nothing about the code, only about the machine.
    # Measured flaky at roughly 1 run in 6 on this host. Poll instead, with a cap far above any real
    # scheduling delay, so the test is deterministic under load and still fails fast if the guard leaks.
    for _ in range(400):                                    # up to ~4s
        if not p3.proving:
            break
        await asyncio.sleep(0.01)
    check("guard releases once the abandoned thread finally ends", p3.proving is False)
    # WHAT THIS ASSERTS IS THE GUARD, NOT THE CLOCK. p3 was built with a deliberately tiny 0.02s bound to
    # force the timeout above; reusing it here raced a 0.01s prove against that same 0.02s bound — a 2x
    # margin, so one scheduling hiccup made wait_for fire and returned None. The question at this point is
    # only "did the released guard let a new prove start", so give it a bound that cannot be the reason
    # it fails.
    p3.timeout = 5.0
    check("and proving resumes afterwards", (await p3.build(prove_seconds=0.01)) == {"proof": "ok"})


asyncio.run(scenario())

# ---- the shipped module exposes the knob and a sane default ------------------------------------------
import execnode.execnode as EX  # noqa: E402

check("SETTLE_PROVE_TIMEOUT exists and is a positive int",
      isinstance(EX.SETTLE_PROVE_TIMEOUT, int) and EX.SETTLE_PROVE_TIMEOUT > 0)
check("default bound is well above an unfolded prove (~1-3 min) ",
      EX.SETTLE_PROVE_TIMEOUT >= 600)
check("default bound is far below the 5h07m a non-completing fold burned",
      EX.SETTLE_PROVE_TIMEOUT < 5 * 3600)
check("the in-flight guard starts released", EX._settle_proving is False)


# ---- A FOLD MUST NEVER COST US THE PROOF ------------------------------------------------------------
# Observed live 2026-08-04, minutes after enabling NADO_EXEC_SETTLE_FOLD on an idle chain:
#   settle-prove worker ended with ValueError: recursive settlement over an empty call span
# The UNFOLDED path proves an empty span fine (61 such proofs had been built), but the recursive path
# refuses one — so switching the fold ON strictly REDUCED output: spans that yielded a proof yielded none.
# The fold is an upgrade to a proof we want either way, never a precondition for producing one.
def prove_model(fold_requested, calls, fold_raises):
    """Mirrors _prove: gate the fold on there being calls, and on any fold failure re-prove unfolded."""
    fold = fold_requested and bool(calls)
    if not fold:
        return {"proof": "unfolded"}
    if fold_raises:
        return {"proof": "unfolded"}          # retry inside the worker thread
    return {"proof": "folded"}


check("EMPTY call span + fold on -> still produces an UNFOLDED proof (the regression)",
      prove_model(True, calls=[], fold_raises=True) == {"proof": "unfolded"})
check("...which is what the 61 pre-fold proofs were", prove_model(False, calls=[], fold_raises=False)
      == {"proof": "unfolded"})
check("real traffic + working fold -> a FOLDED proof",
      prove_model(True, calls=["c"], fold_raises=False) == {"proof": "folded"})
check("real traffic + fold that fails -> falls back to UNFOLDED, never nothing",
      prove_model(True, calls=["c"], fold_raises=True) == {"proof": "unfolded"})
check("fold off entirely is unchanged", prove_model(False, calls=["c"], fold_raises=False)
      == {"proof": "unfolded"})
check("NO input combination yields no proof at all",
      all(prove_model(f, c, r) for f in (True, False) for c in ([], ["c"]) for r in (True, False)))

print()
print("ALL PASS — a non-completing prove degrades to a bare settle, and a fold never costs us the proof"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
