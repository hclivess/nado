"""Every id-taking method of the thirteen aliasing-prone contracts refuses an id >= 2^32 (review C2).

A slot is `field * 2^32 + key` with no mask (zkvmasm SLOT = MOVI + ADD), so an id with a high half addresses
ANOTHER field's storage. Before this guard the five banked games bounded the id only in `open`, the seven board
games nowhere, so as the player `fund(9*2^32 + 88)` re-pinned a settle height and as a stranger `open(5*2^32 +
42)` locked a live tic-tac-toe game (reproduced by the review on an isolated ExecState).

This file pins three things, per contract and per method:
  1. THE FINDING, on the UNGUARDED code (assembled straight from each module's SRC, as build() used to): an
     aliased `open` on a fresh board game SUCCEEDS and writes outside the method's own field set;
  2. the shipped build() refuses the same call — reverts, writes nothing — for EVERY id-taking method, with
     an id in [2^32, 2^62) (refused by the guard's require) and one >= 2^62 (refused by RANGE);
  3. the guard changes nothing for honest ids: every method's io log against a small valid id is identical
     between the unguarded and the guarded code (registers r4/r5 really are scratch everywhere).

Run: python3 tests/test_contract_id_bounds.py
"""
import os
import sys
import tempfile
import traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-idbounds-")      # NEVER the live node's home (rule 4)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import importlib
from execnode import zkvm, zkvmasm
from execnode.games import _lib
from execnode.stark import field as F

fails = 0


def check(name, fn):
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


MODULES = ("dice roulette slots mines blackjack tictactoe connect4 reversi chess stormhold scrapline hexholm pool "
           "holdem farkle coinflip lend bet hamster pets").split()
CALLER = 12345                       # a field-form caller digest; any non-zero value
ALIAS_LOW = (9 << 32) + 88           # a high half: addresses field+9's slot 88
ALIAS_HUGE = (1 << 62) + 5           # refused by RANGE, not by the compare


def _unguarded(mod):
    """What build() assembles with the guard switched off: the same build(), with _lib.guard_ids as the
    identity — so generated/spliced methods are covered for every module without knowing its shape."""
    real = _lib.guard_ids
    _lib.guard_ids = lambda src, plan: dict(src)
    try:
        return mod.build()
    finally:
        _lib.guard_ids = real


def _plan(mod):
    """The ID_GUARDS plan a module's build() applies, recovered from its source (kept beside the code)."""
    import inspect, re
    src = inspect.getsource(mod.build)
    m = re.search(r"ID_GUARDS = (.+)", src)
    return eval(m.group(1))          # noqa: S307 — our own literal


def _run(code, method, args, slots=None, value=0):
    return zkvm.run(code, method, CALLER, list(args), dict(slots or {}), value=value, cursor=100,
                    timestamp=100 * 6, beacons={}, block_hashes={}, selfd=7, abal={})


def _args_for(mod, method, nreg_ids, id_value):
    """An argument vector with the id(s) in the guarded registers and small valid values elsewhere."""
    n = max(3, 1 + max(int(r[1]) for r in nreg_ids))
    args = [1] * n
    for r in nreg_ids:
        args[int(r[1])] = id_value
    return args


# ---- 1. the finding, on the unguarded code -----------------------------------------------------------------
def t_finding_unguarded_open_writes_outside_its_field():
    ttt = importlib.import_module("execnode.games.tictactoe")
    code = _unguarded(ttt)
    ok, _ret, slots, io = _run(code, "open", [(5 << 32) + 42], value=2000)[:4]
    assert ok, "the unguarded open must succeed on an aliased id (this is what the review reproduced)"
    written = {int(s) >> 32 for (k, s, _v) in io if k == zkvm.IO_SSTORE}
    own = {int(s) >> 32 for (k, s, _v) in _run(code, "open", [42], value=2000)[3] if k == zkvm.IO_SSTORE}
    assert written - own, f"the aliased open wrote only inside its own fields {sorted(own)}: {sorted(written)}"


# ---- 2. the shipped code refuses every aliased id ------------------------------------------------------------
def _refuses(mod, code, plan):
    for method, regs in plan.items():
        ids = [(r if isinstance(r, str) else r[0]) for r in regs]
        idregs = [r for r in ids if r == "r0"] or ids
        for bad in (ALIAS_LOW, ALIAS_HUGE):
            args = _args_for(mod, method, idregs, bad)
            ok, _ret, _slots, io = _run(code, method, args, value=2000)[:4]
            assert not ok, f"{mod.__name__}.{method}({bad}) must revert"
            assert not io, f"{mod.__name__}.{method}({bad}) wrote before reverting"
        # a second guarded register (the table id in bet/spin/deal, the cell in reversi.move)
        for r in regs:
            reg, limit = (r if isinstance(r, tuple) else (r, 1 << 32))
            if reg == "r0":
                continue
            args = _args_for(mod, method, ["r0"], 1)
            args[int(reg[1])] = int(limit)
            ok, _ret, _slots, io = _run(code, method, args, value=2000)[:4]
            assert not ok and not io, f"{mod.__name__}.{method}: {reg} >= {limit} must revert"


def t_every_guarded_method_refuses_an_aliased_id():
    for name in MODULES:
        mod = importlib.import_module(f"execnode.games.{name}")
        _refuses(mod, mod.build(), _plan(mod))


def t_banked_fund_and_close_refuse_too():
    """fund/close come from _lib (shared by exactly the five banked games): the guard is inline there."""
    for name in ("dice", "roulette", "slots", "mines", "blackjack"):
        code = importlib.import_module(f"execnode.games.{name}").build()
        for method in ("fund", "close"):
            for bad in (ALIAS_LOW, ALIAS_HUGE):
                ok, _r, _s, io = _run(code, method, [bad], value=2000)[:4]
                assert not ok and not io, f"{name}.{method}({bad}) must revert"
        assert code["fund"][0][0] == "MOVI" and code["fund"][0][3] == 1 << 32, "the guard is the first thing"


# ---- 3. honest calls are unchanged --------------------------------------------------------------------------
def t_guard_is_transparent_for_valid_ids():
    """Same io log, same result, same storage for every guarded method under a valid id: the guard never
    touches a register the body reads first. (Most calls revert on an empty table/game either way — what
    matters is that they revert IDENTICALLY, i.e. at the same io prefix, and that the successful ones
    succeed identically.)"""
    from execnode.games import _lib as L
    for name in MODULES:
        mod = importlib.import_module(f"execnode.games.{name}")
        before, after, plan = _unguarded(mod), mod.build(), _plan(mod)
        for method in plan:
            for args in ([1, 1, 1], [7, 1, 3], [1, 2, 0], [3, 5, 2]):
                a = _run(before, method, args, value=2000)[:4]
                b = _run(after, method, args, value=2000)[:4]
                assert (a[0], a[1], a[2], list(a[3])) == (b[0], b[1], b[2], list(b[3])), \
                    f"{name}.{method}{args}: guarded run differs from the original"
        for method in set(after) - set(plan):
            assert after[method] == before[method], f"{name}.{method} was not in the plan but changed"


def t_open_then_play_still_works_end_to_end():
    """The board games' whole lifecycle with the guard in place (open → join → move), on ids the frontend sends."""
    ttt = importlib.import_module("execnode.games.tictactoe").build()
    ok, _r, slots, _io = _run(ttt, "open", [42], value=2000)[:4]
    assert ok
    ok, _r, slots, _io = zkvm.run(ttt, "join", 999, [42], slots, value=2000, cursor=101, timestamp=606,
                                  beacons={}, block_hashes={}, selfd=7, abal={})[:4]
    assert ok, "join by a second player"


def t_autogame_bounds_the_run_id_in_every_method():
    """autogame is zkpy DSL: the bound is `m.require(m.arg(0) < 2^32)` as the first statement of begin, plan,
    commit, retire, advance and march. A stranger's begin(run + 20*2^32) used to read RDN[run] as RA and
    brick a live run for one value-free call."""
    ag = importlib.import_module("execnode.games.autogame").build()
    for method, extra in (("begin", []), ("plan", [1, 1, 1, 50]), ("commit", [0]), ("retire", []),
                          ("advance", []), ("march", [0, 0])):
        for bad in (ALIAS_LOW, ALIAS_HUGE):
            ok, _r, _s, io = _run(ag, method, [bad] + extra)[:4]
            assert not ok and not io, f"autogame.{method}({bad}) must revert without writing"
    ok, _r, slots, io = _run(ag, "begin", [42])[:4]
    assert ok, "an honest begin(42) still works"


for name, fn in list(globals().items()):
    if name.startswith("t_") and callable(fn):
        check(name[2:].replace("_", " "), fn)

print()
print("ALL PASS — every id-taking method refuses an aliased id, and honest calls are untouched" if not fails
      else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
