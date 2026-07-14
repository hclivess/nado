"""
zkpy — the Python→zkasm compiler. Proves the generated code is CORRECT (runs identically to a python
reference) and that its whole reason to exist holds: register allocation is automatic, so the clobber bug
class that plagued the hand-written ports can't occur in zkpy-authored contracts.

Run: python3 tests/test_zkpy.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode import zkpy, zkvm, runtimes
from execnode.zkpy import hash as zhash, lo32, select
from execnode.stark import alghash

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def _code():
    c = zkpy.Contract()
    PL = 3
    with c.method("bet") as m:                       # bet(g, target)[stake]: pool[g] += stake*99//target
        stake = m.value()
        m.require(stake > 0)
        m.require(m.arg(1) >= 2)
        payout = stake * 99 // m.arg(1)
        cell = m.slot(PL, m.arg(0))
        cell.set(cell.get() + payout)
        m.ret(cell.get())
    with c.method("roll") as m:                      # roll(seed) = lo32(hash(seed)) % 6
        m.ret(lo32(zhash(m.arg(0))) % 6)
    with c.method("mux") as m:                       # mux(cond,a,b) = cond==1 ? a : b (branchless)
        m.ret(select(m.arg(0) == m.const(1), m.arg(1), m.arg(2)))
    with c.method("acc") as m:                       # exercises a value reused many times (named temp)
        v = m.set(m.arg(0) * m.arg(0), into="v")     # v = a^2
        m.ret(v + v + v)                             # 3·a^2 — v read three times, must not be clobbered
    return c, PL


def _run(code, meth, args, **kw):
    cf, fa = runtimes.zkvm_statement("z", args, {})
    return zkvm.run(code, meth, cf, fa, kw.pop("slots", {}), **kw)


def t_compiles():
    c, _ = _code()
    code = c.build()                                 # assembles + validates like any zkVM code object
    assert set(c.source()) == {"bet", "roll", "mux", "acc"}

def t_bet():
    c, PL = _code(); code = c.build()
    ok, ret, ns, _io = _run(code, "bet", [7, 50], value=100_000)
    assert ok and ret == 100_000 * 99 // 50
    assert ns[PL * (1 << 32) + 7] == 100_000 * 99 // 50, "storage read-modify-write"
    assert not _run(code, "bet", [7, 50], value=0)[0], "zero stake reverts"
    assert not _run(code, "bet", [7, 1], value=100)[0], "target < 2 reverts"

def t_roll_differential():
    c, _ = _code(); code = c.build()
    for s in range(40):
        ok, ret, _, _ = _run(code, "roll", [s])
        assert ok and ret == (alghash.hashn([s]) & 0xFFFFFFFF) % 6, f"roll {s}"

def t_select():
    c, _ = _code(); code = c.build()
    for cond in (0, 1, 2, 7):
        ok, ret, _, _ = _run(code, "mux", [cond, 111, 222])
        assert ok and ret == (111 if cond == 1 else 222)

def t_named_temp_not_clobbered():
    c, _ = _code(); code = c.build()
    for a in (3, 10, 99):
        ok, ret, _, _ = _run(code, "acc", [a])
        assert ok and ret == 3 * a * a, f"acc({a}) = {ret} != {3*a*a}"

def t_alloc_is_automatic():
    # a deep expression uses many temporaries; the allocator must place them without collision
    c = zkpy.Contract()
    with c.method("f") as m:
        a, b, cc = m.arg(0), m.arg(1), m.arg(2)
        m.ret((a + b) * (b + cc) + (a * cc) - (a + b + cc))     # 6 live-ish subexpressions
    code = c.build()
    for args in ([2, 3, 4], [10, 0, 5], [7, 7, 7]):
        a, b, cc = args
        ok, ret, _, _ = _run(code, "f", args)
        assert ok and ret == (a + b) * (b + cc) + (a * cc) - (a + b + cc), (args, ret)


if __name__ == "__main__":
    check("zkpy contract compiles + validates", t_compiles)
    check("bet: divmod + storage RMW + require reverts", t_bet)
    check("roll: lo32(hash)%6 differential (40 seeds)", t_roll_differential)
    check("select: branchless mux", t_select)
    check("named temp read 3× never clobbered", t_named_temp_not_clobbered)
    check("deep expression: automatic allocation, no collision", t_alloc_is_automatic)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
