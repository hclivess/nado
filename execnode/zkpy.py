"""
zkpy — a small Python DSL that compiles to zkasm (execnode/zkvmasm.py). You build an expression tree with
ordinary Python operators and the compiler does the REGISTER ALLOCATION for you, so the hand-written-asm bug
class this session kept hitting — a helper silently clobbering a register a caller still needed (blackjack's
r5, pets' att/dfn stat-select, holdem's _fd/_load/_eval7) — is structurally impossible: every temporary gets
a fresh register from a free-list and is released the moment it's consumed.

    from execnode.zkpy import Contract
    c = Contract()
    with c.method("bet") as m:               # r0 = arg 0, available as m.arg(0)
        stake = m.value()                    # the call's escrowed VALUE
        m.require(stake > 0)                 # branchless comparisons -> a 0/1 register
        pool = m.slot(PL, m.arg(0))          # storage load: slot = PL*2^32 + arg0
        pool.set(pool + stake)               # read-modify-write a storage cell
        m.ret(m.arg(0))
    code = c.build()                         # -> the same validated zkVM code object zkvmasm produces

What it gives you: field arithmetic (`+ - * // %`), comparisons (`> >= < <= == !=` — each lowers to the
LT/EQ + branchless-fixup idiom), `hash(a, b, ...)`, `select(cond, a, b)` (branchless mux), storage cells
(`m.slot(field, key)` with `.get()`/`.set()`), `m.require`, `m.pay`, `m.ret`, and raw `m.emit("…")` for the
handful of ops the DSL doesn't wrap yet (jumps/labels/loops — control flow stays explicit for now). It emits
zkasm text, so everything downstream (the assembler, the VM, the execution AIR) is unchanged — zkpy is a
front-end, not a new runtime. Register model: r0 preloads arg 0 (zkVM ABI); r4 is reserved (storage
addressing, see below); r7 is reserved (DIVMOD remainder); r1..r3, r5..r6 are the allocatable temp pool.
`arg(i)` for i>=1 loads via the ARG opcode into a temp.
"""
from execnode import zkvmasm

# r4 is RESERVED, not allocatable. `_Cell._addr()` builds every slot address in r4 unconditionally, so any
# live temp that happened to be allocated r4 was silently destroyed by the next storage access. The victim
# case was `cell.set(expr)` when `expr` was complex enough to land in r4: `set()` materialized the value,
# then `_addr()` overwrote it, and the emitted `sstore r4 r4` stored the slot ADDRESS as the value — no
# revert, no proof failure, just a wrong number (a select() over four cells reproduced it exactly). Keeping
# r4 out of the pool costs one temp and makes the collision structurally impossible, which is the whole
# premise of this module.
_ALLOC = [1, 2, 3, 5, 6]           # allocatable temps (r0 = arg0, r4 = slot address, r7 = divmod remainder)


class _Alloc:
    """A tiny register free-list. Values hold a register while live; freeing returns it to the pool."""
    def __init__(self):
        self.free = list(_ALLOC)

    def take(self):
        if not self.free:
            raise RuntimeError("zkpy: out of registers — split the expression or store an intermediate")
        return self.free.pop(0)

    def give(self, r):
        if r in _ALLOC and r not in self.free:
            self.free.append(r); self.free.sort()


class Val:
    """An expression node. `materialize(m)` emits code to compute it and returns (reg, owned): `owned` means
    the reg is a fresh temp the caller must free after use; a non-owned reg is a pinned/named register that
    must NOT be freed. Leaf temps are owned; args/named regs are not."""
    def __init__(self, kind, *a):
        self.kind = kind; self.a = a

    # operator overloads build the tree — no code emitted until materialize
    def __add__(self, o): return Val("add", self, _wrap(o))
    def __radd__(self, o): return Val("add", _wrap(o), self)
    def __sub__(self, o): return Val("sub", self, _wrap(o))
    def __rsub__(self, o): return Val("sub", _wrap(o), self)
    def __mul__(self, o): return Val("mul", self, _wrap(o))
    def __rmul__(self, o): return Val("mul", _wrap(o), self)
    def __floordiv__(self, o): return Val("div", self, _wrap(o))     # quotient (DIVMOD)
    def __mod__(self, o): return Val("mod", self, _wrap(o))          # remainder (rem macro)
    def __lt__(self, o): return Val("lt", self, _wrap(o))
    def __gt__(self, o): return Val("lt", _wrap(o), self)
    def __le__(self, o): return Val("le", self, _wrap(o))
    def __ge__(self, o): return Val("le", _wrap(o), self)
    def __eq__(self, o): return Val("eq", self, _wrap(o))
    def __ne__(self, o): return Val("ne", self, _wrap(o))
    def __invert__(self): return Val("notb", self)                  # ~x = boolean NOT (x must be 0/1)


def _wrap(o):
    return o if isinstance(o, Val) else Val("const", int(o))


class _Cell:
    """A storage cell m.slot(field, key): .get() reads it, .set(v) writes it. `field` is a compile-time int;
    `key` is a Val (or int)."""
    def __init__(self, m, field, key):
        self.m, self.field, self.key = m, field, _wrap(key)

    def _addr(self):
        # r4 = field*2^32 + key. If key is arg0 (r0) we can use the `slot` macro; else compute.
        kr, owned = self.key.materialize(self.m)
        self.m.emit(f"movi r4 {self.field << 32}")
        self.m.emit(f"add r4 {_r(kr)}")
        if owned:
            self.m.alloc.give(kr)
        return "r4"

    def get(self):
        return Val("sload", self)

    def set(self, v):
        vr, owned = _wrap(v).materialize(self.m)
        addr = self._addr()                                          # clobbers r4 — safe only because r4 is
                                                                     # reserved and vr can never live there
        self.m.emit(f"sstore {addr} {_r(vr)}")
        if owned:
            self.m.alloc.give(vr)


def _r(x):
    return x if isinstance(x, str) else f"r{x}"


# ---- materialization: the register allocator lowers a Val tree to zkasm --------------------------------
def _mat(self, m):
    k = self.kind
    if k == "reg":                              # a pinned/named register (r0, a stored temp) — not owned
        return self.a[0], False
    if k == "const":
        r = m.alloc.take(); m.emit(f"movi {_r(r)} {self.a[0] % (1 << 64)}"); return r, True
    if k == "arg":
        i = self.a[0]
        if i == 0:
            return 0, False                     # r0 preloads arg 0
        r = m.alloc.take(); m.emit(f"movi {_r(r)} {i}"); m.emit(f"arg {_r(r)} {_r(r)}"); return r, True
    if k == "ctx":
        r = m.alloc.take(); m.emit(f"ctx {_r(r)} {self.a[0]}"); return r, True
    if k == "sload":
        cell = self.a[0]; addr = cell._addr()   # r4
        r = m.alloc.take(); m.emit(f"sload {_r(r)} {addr}"); return r, True
    if k in ("bhash", "beacon"):
        hr, owned = self.a[0].materialize(m)
        r = m.alloc.take(); m.emit(f"{k} {_r(r)} {_r(hr)}")
        if owned:
            m.alloc.give(hr)
        return r, True
    if k == "hash":
        # hash d <- s1 s2 ... — materialize each element into a register, then absorb
        regs, owns = [], []
        for el in self.a:
            rr, ow = el.materialize(m); regs.append(rr); owns.append(ow)
        d = m.alloc.take()
        m.emit(f"hash {_r(d)} <- " + " ".join(_r(x) for x in regs))
        for rr, ow in zip(regs, owns):
            if ow:
                m.alloc.give(rr)
        return d, True
    if k == "lo32":
        r, owned = self.a[0].materialize(m)
        if not owned:                           # LO32 writes in place — copy a pinned source first
            d = m.alloc.take(); m.emit(f"mov {_r(d)} {_r(r)}"); r = d; owned = True
        m.emit(f"lo32 {_r(r)}"); return r, True
    if k == "notb":
        r, owned = self.a[0].materialize(m)
        if not owned:
            d = m.alloc.take(); m.emit(f"mov {_r(d)} {_r(r)}"); r = d; owned = True
        m.emit(f"notb {_r(r)}"); return r, True
    if k in ("add", "sub", "mul"):
        la, lo = self.a[0].materialize(m)
        if not lo:                              # binary ops write the DEST in place — own a copy of a pinned lhs
            d = m.alloc.take(); m.emit(f"mov {_r(d)} {_r(la)}"); la, lo = d, True
        rb, ro = self.a[1].materialize(m)
        m.emit(f"{k} {_r(la)} {_r(rb)}")
        if ro:
            m.alloc.give(rb)
        return la, True
    if k in ("div", "mod"):
        la, lo = self.a[0].materialize(m)
        if not lo:
            d = m.alloc.take(); m.emit(f"mov {_r(d)} {_r(la)}"); la, lo = d, True
        rb, ro = self.a[1].materialize(m)
        if k == "div":
            m.emit(f"divmod {_r(la)} {_r(rb)}")      # quotient stays in la; remainder -> r7
        else:
            m.emit(f"rem {_r(la)} {_r(rb)}")         # remainder -> la (the safe macro)
        if ro:
            m.alloc.give(rb)
        return la, True
    if k == "eq":
        la, lo = _own(self.a[0], m); rb, ro = self.a[1].materialize(m)
        m.emit(f"eq {_r(la)} {_r(rb)}")
        if ro:
            m.alloc.give(rb)
        return la, True
    if k == "ne":
        la, lo = _own(self.a[0], m); rb, ro = self.a[1].materialize(m)
        m.emit(f"eq {_r(la)} {_r(rb)}"); m.emit(f"notb {_r(la)}")
        if ro:
            m.alloc.give(rb)
        return la, True
    if k == "lt":
        la, lo = _own(self.a[0], m); rb, ro = self.a[1].materialize(m)
        m.emit(f"lt {_r(la)} {_r(rb)}")
        if ro:
            m.alloc.give(rb)
        return la, True
    if k == "le":                               # a <= b  ==  !(b < a)
        la, lo = _own(self.a[1], m); rb, ro = self.a[0].materialize(m)   # la=b, rb=a
        m.emit(f"lt {_r(la)} {_r(rb)}"); m.emit(f"notb {_r(la)}")
        if ro:
            m.alloc.give(rb)
        return la, True
    if k == "select":                           # cond ? t : f  = f + cond*(t-f), cond a 0/1 bit
        cond, co = self.a[0].materialize(m)
        t, to = self.a[1].materialize(m)
        f, fo = self.a[2].materialize(m)
        d = m.alloc.take()
        m.emit(f"mov {_r(d)} {_r(t)}"); m.emit(f"sub {_r(d)} {_r(f)}")   # t-f
        m.emit(f"mul {_r(d)} {_r(cond)}"); m.emit(f"add {_r(d)} {_r(f)}")
        for rr, ow in ((cond, co), (t, to), (f, fo)):
            if ow:
                m.alloc.give(rr)
        return d, True
    raise RuntimeError(f"zkpy: cannot materialize {k}")


def _own(node, m):
    """Materialize `node` into an OWNED register (copy if it's pinned) — for ops that write their dest."""
    r, owned = node.materialize(m)
    if not owned:
        d = m.alloc.take(); m.emit(f"mov {_r(d)} {_r(r)}"); return d, True
    return r, True


Val.materialize = _mat


def hash(*elements):
    """hash(a, b, …) -> the alghash sponge digest of the elements (each a Val or int)."""
    return Val("hash", *[_wrap(e) for e in elements])


def lo32(v):
    return Val("lo32", _wrap(v))


def select(cond, t, f):
    """Branchless mux: cond (a 0/1 Val) ? t : f."""
    return Val("select", _wrap(cond), _wrap(t), _wrap(f))


class _Method:
    def __init__(self, contract, name):
        self.contract, self.name = contract, name
        self.lines = []
        self.alloc = _Alloc()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if exc[0] is None:
            self.contract._src[self.name] = "\n".join(self.lines)
        return False

    def emit(self, line):
        self.lines.append(line)

    # leaves ----------------------------------------------------------------------------------------
    def arg(self, i):
        return Val("arg", i)

    def value(self):
        return Val("ctx", "value")

    def caller(self):
        return Val("ctx", "caller")

    def cursor(self):
        return Val("ctx", "cursor")

    def time(self):
        return Val("ctx", "time")

    def const(self, n):
        return Val("const", int(n))

    def slot(self, field, key):
        return _Cell(self, field, _wrap(key))

    def bhash(self, height):
        return Val("bhash", _wrap(height))

    def beacon(self, epoch):
        return Val("beacon", _wrap(epoch))

    # statements ------------------------------------------------------------------------------------
    def set(self, v, into):
        """Force-compute `v` into a NAMED temp you keep (returns a Val('reg')). Frees nothing — the register
        stays reserved until end of method; use for a value read many times."""
        r, owned = _wrap(v).materialize(self)
        if not owned:
            d = self.alloc.take(); self.emit(f"mov {_r(d)} {_r(r)}"); r = d
        return Val("reg", r)

    def require(self, cond):
        r, owned = _wrap(cond).materialize(self)
        self.emit(f"require {_r(r)}")
        if owned:
            self.alloc.give(r)

    def pay(self, to, amount):
        tr, to_owned = _wrap(to).materialize(self)
        ar, a_owned = _wrap(amount).materialize(self)
        self.emit(f"pay {_r(tr)} {_r(ar)}")
        if to_owned:
            self.alloc.give(tr)
        if a_owned:
            self.alloc.give(ar)

    def ret(self, v):
        r, owned = _wrap(v).materialize(self)
        self.emit(f"ret {_r(r)}")
        if owned:
            self.alloc.give(r)


class Contract:
    """Build a multi-method zkVM contract in zkpy, then `.build()` to the validated code object."""
    def __init__(self):
        self._src = {}

    def method(self, name):
        return _Method(self, name)

    def source(self):
        """The generated zkasm text per method (for inspection / golden tests)."""
        return dict(self._src)

    def build(self):
        return zkvmasm.assemble_contract(self._src)
