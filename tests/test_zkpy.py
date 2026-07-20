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


def t_store_of_deep_expr_not_clobbered():
    """REGRESSION: `_Cell._addr()` used to build every slot address in the hardcoded r4, which silently
    destroyed any live temp the allocator had put there — `cell.set(expr)` emitted `sstore r4 r4` and
    stored the slot ADDRESS instead of the value, with ok=True and a valid proof. Found while authoring the
    Autogame step function. Slot addresses are now allocated from the same free-list as every other
    temporary, so no register needs reserving and the collision is structurally impossible."""
    c = zkpy.Contract()
    with c.method("f") as m:
        a, b, t, f = m.slot(1, 0), m.slot(2, 0), m.slot(3, 0), m.slot(4, 0)
        out = m.slot(5, 0)
        out.set(select(a.get() < b.get(), t.get(), f.get()))
        m.ret(out.get())
    code = c.build()
    for aa, bb, exp in ((1, 9, 777), (9, 1, 111), (5, 5, 111)):
        st = {1 << 32: aa, 2 << 32: bb, 3 << 32: 777, 4 << 32: 111}
        ok, ret, storage, _ = zkvm.run(code, "f", 12345, [0], dict(st))
        assert ok and ret == exp, f"select({aa}<{bb}) returned {ret}, want {exp}"
        assert storage.get(5 << 32) == exp, f"stored {storage.get(5 << 32)}, want {exp}"

    # and the general form: every allocatable temp must survive a storage access
    c2 = zkpy.Contract()
    with c2.method("g") as m:
        cells = [m.slot(10 + i, 0) for i in range(5)]
        acc = cells[0].get() + cells[1].get() * cells[2].get() + cells[3].get() - cells[4].get()
        m.slot(20, 0).set(acc)
        m.ret(m.slot(20, 0).get())
    code2 = c2.build()
    vals = [7, 3, 5, 11, 4]
    st = {(10 + i) << 32: v for i, v in enumerate(vals)}
    ok, ret, _, _ = zkvm.run(code2, "g", 12345, [0], dict(st))
    want = vals[0] + vals[1] * vals[2] + vals[3] - vals[4]
    assert ok and ret == want, f"deep store returned {ret}, want {want}"


def t_select_normalizes_cond():
    """select() lowers to f + cond*(t-f), an identity that only holds for cond in {0,1}. Any other value
    used to produce a silent garbage blend; NEZ now normalises it, so 'non-zero is true' as everywhere
    else in the VM."""
    c = zkpy.Contract()
    with c.method("f") as m:
        m.ret(select(m.arg(0), m.const(777), m.const(111)))
    code = c.build()
    for cond, exp in ((0, 111), (1, 777), (2, 777), (99, 777), (10 ** 9, 777)):
        ok, ret, _, _ = _run(code, "f", [cond])
        assert ok and ret == exp, f"select(cond={cond}) = {ret}, want {exp}"


def t_control_flow_balance_guard():
    """Labels and jumps must sit where no ANONYMOUS temp is live: the allocator is a linear scan, so a
    backward jump arriving with a different free-list would silently reuse a live register.

    Today that state is unreachable through the public API — Val trees are lazy, so nothing is allocated
    until a statement materialises it, and every statement frees what it took. The guard therefore asserts
    an invariant that currently holds BY CONSTRUCTION, and exists so that a future statement type which
    leaves a temp live fails loudly at build time instead of miscompiling a loop. This test drives the
    allocator directly to prove the guard actually fires."""
    c = zkpy.Contract()
    with c.method("bad") as m:
        stray = m.alloc.take()                  # simulate a statement that left a temporary live
        try:
            m.label("loop")
        except RuntimeError as e:
            assert "temporaries still live" in str(e), e
        else:
            raise AssertionError("label() accepted a branch across a live temporary")
        try:
            m.jmp("loop")
        except RuntimeError:
            pass
        else:
            raise AssertionError("jmp() accepted a branch across a live temporary")
        m.alloc.give(stray)
        m.label("loop")                         # balanced again -> accepted
        m.ret(m.const(0))

    # named temps are exempt: they are pinned for the whole method on purpose, which is exactly how
    # loop-carried state is meant to survive a branch
    c2 = zkpy.Contract()
    with c2.method("good") as m:
        acc = m.set(m.slot(1, 0).get(), None)
        m.label("loop")
        m.jnz(m.const(0), "loop")
        m.ret(acc)
    c2.build()


def t_loop_counts_down():
    """A real loop: sum i for i in 1..n, with loop-carried state in named temps. This is the shape the
    Autogame step loop uses, so it has to be provably safe."""
    c = zkpy.Contract()
    with c.method("sum") as m:
        n = m.set(m.arg(0), None)
        acc = m.set(m.const(0), None)
        m.label("top")
        m.jnz(n == 0, "done")
        m.emit(f"add {_reg(acc)} {_reg(n)}")
        m.emit(f"movi r6 1")
        m.emit(f"sub {_reg(n)} r6")
        m.jmp("top")
        m.label("done")
        m.ret(acc)
    code = c.build()
    for n in (0, 1, 5, 12):
        ok, ret, _, _ = _run(code, "sum", [n])
        assert ok and ret == n * (n + 1) // 2, f"sum({n}) = {ret}, want {n*(n+1)//2}"


def _reg(v):
    return f"r{v.a[0]}"


if __name__ == "__main__":
    check("zkpy contract compiles + validates", t_compiles)
    check("bet: divmod + storage RMW + require reverts", t_bet)
    check("roll: lo32(hash)%6 differential (40 seeds)", t_roll_differential)
    check("select: branchless mux", t_select)
    check("named temp read 3× never clobbered", t_named_temp_not_clobbered)
    check("deep expression: automatic allocation, no collision", t_alloc_is_automatic)
    check("store of a deep expr survives slot addressing", t_store_of_deep_expr_not_clobbered)
    check("select normalizes a non-boolean cond", t_select_normalizes_cond)
    check("control flow: label/jmp reject live temporaries", t_control_flow_balance_guard)
    check("loop with named loop-carried state", t_loop_counts_down)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
