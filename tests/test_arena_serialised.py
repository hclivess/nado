"""The native prover's arena is ONE global in Rust. Every prove must hold the lock that says so.

_LOCK has existed in stark_native.py since the arena landed, carrying the comment

    _LOCK = threading.Lock()  # the arena is a single global in Rust — one prove at a time

and NOTHING EVER ACQUIRED IT. The invariant held by accident: exactly one prove could be in flight, because
the only prover was the KV settle prove and the exec node serialised it with _settle_proving.

IT STOPPED HOLDING THE MOMENT A SECOND PROVER APPEARED. The records half runs its own prove_transition, and
once that moved into a worker thread (it had to — run inline it blocked the event loop and hung the node)
the two proves drove the SAME arena concurrently. Whichever called sp_reset second cleared the other's
retained columns; the first then asked for a column that no longer existed, and the arena returned -1:

    records half FAILED … RuntimeError: sp_commit_col failed

That is what every records-bearing span logged after the alphanet-16 cutover. It failed CLOSED — the spans
rode the bonded quorum and the chain stayed healthy — but no call-bearing span could prove, which was the
entire point of the reroll.

WHY A DECLARED-BUT-UNUSED LOCK IS WORSE THAN NO LOCK: it reads as an enforced invariant. Anyone adding a
second prover sees the comment, assumes serialisation, and ships. These checks make the enforcement real.

Run: python3 tests/test_arena_serialised.py
"""
import ast
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SRC_PATH = os.path.join(ROOT, "execnode", "stark", "stark_native.py")
SRC = open(SRC_PATH).read()

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


def _prove_fn():
    for n in ast.walk(ast.parse(SRC)):
        if isinstance(n, ast.FunctionDef) and n.name == "prove":
            return n
    raise AssertionError("stark_native.prove not found")


def t_the_lock_is_actually_acquired():
    """It was declared and never used — the whole defect."""
    assert "_LOCK.acquire()" in SRC, "the arena lock must be ACQUIRED, not merely declared"
    assert "_LOCK.release()" in SRC, "and released"


def t_every_arena_call_is_inside_the_lock():
    """reset / lde_column / commit_col / commit_rows / read / open_at / free all touch the single global
    arena. If any runs outside the held region, a concurrent prove can clear its columns."""
    fn = _prove_fn()
    acquire_line = next((n.lineno for n in ast.walk(fn)
                         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                         and n.func.attr == "acquire"), None)
    assert acquire_line, "prove() must acquire the arena lock"
    arena = {"reset", "lde_column", "commit_col", "commit_rows", "free", "read", "open_at",
             "compose", "compose_ext", "fri_prove_native"}
    outside = [(n.func.id, n.lineno) for n in ast.walk(fn)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id in arena and n.lineno < acquire_line]
    assert not outside, f"arena calls before the lock is taken: {outside}"


def t_release_is_in_a_finally():
    """A raise anywhere inside the arena region must still release, or ONE failed prove wedges every later
    prove on the node — a far worse failure than the one being fixed."""
    fn = _prove_fn()
    tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try) and n.finalbody]
    assert tries, "the arena region must be wrapped in try/finally"
    rel = [n for t in tries for n in ast.walk(ast.Module(body=t.finalbody, type_ignores=[]))
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "release"]
    assert rel, "the lock must be released in the finally block, not on the success path only"


def t_the_lock_still_documents_why():
    i = SRC.index("_LOCK = threading.Lock()")
    assert "single global" in SRC[i:i + 200], \
        "keep the comment that states the invariant — it is what makes the lock's purpose checkable"


for nm, fn in [("the lock is actually acquired", t_the_lock_is_actually_acquired),
               ("every arena call is inside the lock", t_every_arena_call_is_inside_the_lock),
               ("release is in a finally", t_release_is_in_a_finally),
               ("the lock still documents the invariant", t_the_lock_still_documents_why)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
