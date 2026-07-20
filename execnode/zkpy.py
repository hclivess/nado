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
front-end, not a new runtime. Register model: r0 preloads arg 0 (zkVM ABI); r7 is reserved (DIVMOD
remainder); r1..r6 are the allocatable temp pool — including slot addresses, which are allocated like any
other temporary. `arg(i)` for i>=1 loads via the ARG opcode into a temp.

CONTROL FLOW. Jumps and labels are explicit (`m.label`, `m.jmp`, `m.jnz`). The allocator is a linear scan
that knows nothing about branches, so every label/jump is a BALANCE POINT: it asserts that no anonymous
temporary is live, because a backward jump arriving with a different free-list than the label was compiled
under would silently reuse a live register. That state is currently unreachable through the public API —
Val trees are lazy and every statement frees what it took — so the assertion documents and *enforces* an
invariant that holds by construction, and will fail loudly the day a statement type stops honouring it.
Loop-carried values belong in `m.set()` named temps (pinned for the whole method) or in storage.

THE ONE REMAINING SHARP EDGE is raw `m.emit("…")`: it bypasses the allocator entirely, so any register it
names can collide with an allocated temp. Use it for opcodes the DSL doesn't wrap yet, keep it to registers
you obtained from `m.set()`, and prefer adding a wrapper here over sprinkling raw asm at the call site.
"""
from execnode import zkvmasm

_ALLOC = [1, 2, 3, 4, 5, 6]        # allocatable temp registers (r0 = arg0, r7 = divmod remainder)


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
    """A storage cell: .get() reads it, .set(v) writes it.

    Two addressing modes:
      * m.slot(field, key) — the flat convention, address = field*2^32 + key, with `field` a compile-time
        int. The frontend can compute the same address without hashing, so these slots are enumerable.
      * m.at(addr)         — the address IS `addr`, for hash-keyed cells (per-(run, leg), per-(user, id)…)
        where the key space is too large to enumerate. `field` is None in this mode.
    """
    def __init__(self, m, field, key):
        self.m, self.field, self.key = m, field, _wrap(key)

    def _addr(self):
        """Compute `field*2^32 + key` into a FRESHLY ALLOCATED register; returns (reg, owned).

        This used to hardcode r4, which silently destroyed any live temp the allocator had placed there —
        `cell.set(expr)` emitted `sstore r4 r4` and stored the slot address instead of the value. Taking
        the address register from the same free-list as everything else is what actually makes the
        collision impossible; no register needs reserving, and the allocator stays the single authority
        on who owns what."""
        kr, owned = self.key.materialize(self.m)
        if self.field is None:                                       # m.at(): the value IS the address
            if owned:
                return kr, True
            d = self.m.alloc.take()
            self.m.emit(f"mov {_r(d)} {_r(kr)}")                     # own a copy of a pinned register
            return d, True
        d = self.m.alloc.take()
        self.m.emit(f"slot {_r(d)} {self.field} {_r(kr)}")           # macro: MOVI d field<<32 ; ADD d kr
        if owned:
            self.m.alloc.give(kr)
        return d, True

    def get(self):
        return Val("sload", self)

    def set(self, v):
        vr, owned = _wrap(v).materialize(self.m)                     # value FIRST: it must survive addressing
        addr, a_owned = self._addr()
        self.m.emit(f"sstore {_r(addr)} {_r(vr)}")
        if a_owned:
            self.m.alloc.give(addr)
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
    if k == "actx":
        r = m.alloc.take(); m.emit(f"actx {_r(r)} {self.a[0]}"); return r, True
    if k == "sload":
        cell = self.a[0]
        addr, a_owned = cell._addr()
        r = m.alloc.take()
        m.emit(f"sload {_r(r)} {_r(addr)}")
        if a_owned:
            m.alloc.give(addr)                  # the address dies here; only the loaded value survives
        return r, True
    if k in ("bhash", "beacon", "abal"):
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
    if k == "select":                           # cond ? t : f  = f + cond*(t-f)
        # NEZ first: the identity only holds for a 0/1 cond, and any other value silently yielded a
        # garbage blend rather than t or f. Normalising costs one row and makes select total — "non-zero
        # is true", the same rule REQUIRE and JNZ already use. It is a no-op on a real 0/1 comparison.
        cond, co = _own(self.a[0], m)
        m.emit(f"nez {_r(cond)}")
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
        self.named = set()          # registers pinned by m.set() — live for the whole method, by design

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

    def at(self, addr):
        """A storage cell addressed directly by `addr` — for hash-keyed slots, e.g.
        m.at(hash(TAG, runId, leg)). Not enumerable by the storage view, so pair it with a view method."""
        return _Cell(self, None, _wrap(addr))

    def bhash(self, height):
        return Val("bhash", _wrap(height))

    def beacon(self, epoch):
        return Val("beacon", _wrap(epoch))

    # assets (doc/assets.md) ------------------------------------------------------------------------
    def in_asset(self):
        """The asset id escrowed WITH this call — 0 when the caller sent native NADO. Pair with
        m.value() (the amount, which is the same context field for both)."""
        return Val("actx", "asset")

    def me(self):
        """This contract's own address digest — what an issuer-derived asset id is bound to."""
        return Val("actx", "self")

    def abal(self, asset):
        """This contract's balance of `asset` (0 for one it has never held)."""
        return Val("abal", _wrap(asset))

    # statements ------------------------------------------------------------------------------------
    def set(self, v, into):
        """Force-compute `v` into a NAMED temp you keep (returns a Val('reg')). Frees nothing — the register
        stays reserved until end of method; use for a value read many times."""
        r, owned = _wrap(v).materialize(self)
        if not owned:
            d = self.alloc.take(); self.emit(f"mov {_r(d)} {_r(r)}"); r = d
        self.named.add(r)
        return Val("reg", r)

    # control flow ------------------------------------------------------------------------------------
    def _balanced(self, what):
        """Assert no ANONYMOUS temporary is live. Every label and jump must sit at such a point, or the
        allocator's linear scan and the actual execution order disagree — see the CONTROL FLOW note up
        top. Named temps (m.set) are exempt: they are pinned for the whole method on purpose."""
        live = [r for r in _ALLOC if r not in self.alloc.free and r not in self.named]
        if live:
            raise RuntimeError(
                f"zkpy: {what} with temporaries still live in {', '.join('r%d' % r for r in live)} — a "
                "branch may not cross a half-computed expression. Park the value in an m.set() named temp "
                "or a storage cell first.")

    def label(self, name):
        self._balanced(f"label @{name}")
        self.emit(f"{name}:")

    def jmp(self, name):
        self._balanced(f"jmp @{name}")
        self.emit(f"jmp @{name}")

    def jnz(self, cond, name):
        """Jump to @name when `cond` is non-zero."""
        r, owned = _wrap(cond).materialize(self)
        self.emit(f"jnz {_r(r)} @{name}")
        if owned:
            self.alloc.give(r)
        self._balanced(f"jnz @{name}")

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

    def _asset_move(self, op, asset, to, amount):
        """apay/amint share one shape: three operands materialized, then the atomic ASEL+spend macro. The
        registers are freed only AFTER both instructions are emitted — the pair is one statement, and a
        register reused between the ASEL and the spend would select one asset and move another."""
        sr, s_owned = _wrap(asset).materialize(self)
        tr, t_owned = _wrap(to).materialize(self)
        ar, a_owned = _wrap(amount).materialize(self)
        self.emit(f"{op} {_r(sr)} {_r(tr)} {_r(ar)}")
        for r, owned in ((sr, s_owned), (tr, t_owned), (ar, a_owned)):
            if owned:
                self.alloc.give(r)

    def apay(self, asset, to, amount):
        """Move `amount` of `asset` out of this contract's holding to `to`. Reverts the call if the contract
        does not hold that much — the same solvency rule PAY has for native NADO."""
        self._asset_move("apay", asset, to, amount)

    def amint(self, asset, to, amount):
        """Mint `amount` of `asset` to `to`. Only the asset's ISSUER may mint, and only while the asset is
        still mintable; the exec layer checks both and reverts the call otherwise."""
        self._asset_move("amint", asset, to, amount)

    def aburn(self, asset, amount):
        """Burn `amount` of `asset` from this contract's own holding (supply falls; nobody receives it)."""
        sr, s_owned = _wrap(asset).materialize(self)
        ar, a_owned = _wrap(amount).materialize(self)
        self.emit(f"aburn {_r(sr)} {_r(ar)}")
        if s_owned:
            self.alloc.give(sr)
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
