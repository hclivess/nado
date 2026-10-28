"""THE GEN-29 SETTLEMENT PROOF OF A SPAN, as a stateless replay (Goldilocks retirement G4; doc/stwo/g4-settlement-statement.md
section 5). A verifier that holds NO exec state checks that a span of L1 blocks takes the exec root from `pre_root` to
`post_root`, given:
  * the blocks themselves (L1 has them), and the chain inputs L1 derives itself (Chain: the dividend accrual inputs and
    BHASH/BEACON values and their availability) — never from the prover. The dividend carry at the span's start is NOT a
    chain input from protocol.EXEC_CARRY_ROOT_HEIGHT: it is a record of the pre root (exec_root_b2.CARRY_COUNTER), opened
    like any other (below the gate only the exec node's own bookkeeping knows it, and L1 refuses such spans);
  * a WITNESS from the prover: every exec-state entry the span read or wrote (an OPENING: its value, or absent), each
    authenticated by a compressed-tree proof against the pre root's half; the code of every contract it ran; the
    preimage of any sibling a delete must look inside (csmt_partial);
  * one Stwo proof (native/stwo_settle, vm_air.rs) that every contract call ran on zkvm2 and produced exactly its io log
    in its step count.

HOW. The verifier replays the span through THE SAME TRANSITION CODE the exec node runs (execnode/block_apply.py ->
ExecState.apply_blob and friends), on a WitnessState whose maps are backed by the openings. Two things differ from the
exec node, and only these:
  1. the maps hold only the opened entries. Reading anything else raises Unprovable — a BaseException, so no
     `except Exception` in the transition can swallow it and turn "the witness is missing a key" into "the tx skipped",
     which would let a prover omit an inconvenient entry and settle a root the chain never had;
  2. a contract call does not run the VM. The ORACLE takes the call's io log and step count from the witness, checks
     every io entry the VM reads against the state (SLOAD values, ABAL values, chain reads, asset overspends), applies
     its writes, and adds the call to the VM statement the Stwo proof must verify — with code, args and context the
     REPLAY computed, never the prover's.
The post root is the pre root with the replay's net leaf changes applied to a partial tree (csmt_partial).

THE PROVER is the same replay: it runs the real transition on a copy of the full state first (recording each VM run),
then replays on a WitnessState whose source is the real pre-state, which records exactly the openings the verifier will
need; it then proves the VM statement and checks the bundle with the verifier before returning it. So a span the
verifier cannot replay is found unprovable by the prover, before anything is submitted.

A REVERTING call is proven like any other (native/stwo_settle vm_air.rs, REVERTS): the witness carries its kind
(zkvm2.REVERT_KINDS) and its io log up to the revert; the oracle checks the reads, discards the writes, and judges the
four kinds the circuit cannot (Oracle._walk).

WHAT A SPAN CANNOT CARRY YET (Unprovable; the span settles by the quorum, as every span does today): below
protocol.EXEC_ADDR_ROOT_HEIGHT, a payee or asset recipient registered before the span (the digest registry is committed
only from that gate), and any span crossing it; any span crossing protocol.EXEC_CARRY_ROOT_HEIGHT (the carry's first
root inserts a record no witness opens); creating an asset (absence of an asset id is not provable: its leaf key
includes the metadata digest); the shielded pools, private calls and cross-namespace deliveries into this namespace
(their state is committed as digests, not per entry); non-integer contract storage (KVX records). Each is named in the
Unprovable message.

L1 imports this on ONE consensus path, behind protocol.STWO_SETTLE_HEIGHT (G8, dormant on generation 29): a settle
carrying `stwo` (ops/transaction_ops._stwo_settle_check) is verified by verify_span on L1's own blocks and on the Chain
L1 derives from its state (ops/settle_chain.py). Everything here is therefore consensus code from that gate on.
"""
import copy
import json
import os
import subprocess
import tempfile
import threading
from collections.abc import MutableMapping

from execnode import block_apply, csmt, runtimes, zkvm2
from execnode import exec_root_b2 as B2
from execnode.csmt_partial import Missing, PartialTree, opener_for
from execnode.exec_root_b2 import (T_ASSET_ALLOW, T_ASSET_BAL, T_ASSET_META, T_BRIDGE_BAL, T_BRIDGE_WD, T_DIGEST,
                                T_DIV_BAL, T_DIV_WD, T_UNSHIELD_WD, asset_meta_digest, leaf_digest, msg_outbox_leaf)
from execnode.state import ExecState

MASK = (1 << 256) - 1
NS = "default"


class Unprovable(BaseException):
    """The span cannot be settled from this witness (or at all, yet). NOT an Exception: the transition's own `except
    Exception` handlers must never catch it (module docstring, point 1)."""


class Refused(BaseException):
    """The witness contradicts itself or the chain: the bundle is invalid. Also a BaseException, for the same reason."""


class _Absent:
    """The marker for an entry that does not exist. It must never reach the transition as a VALUE: any arithmetic,
    comparison or truth test on it raises Unprovable (a BaseException), because an ordinary TypeError inside apply_blob
    would be caught there and turned into a skipped transaction — a skip the chain never made, i.e. a wrong root that
    verifies. Code here tests it by identity only."""
    __slots__ = ()

    def _leak(self, *a, **k):
        raise Unprovable("internal: an absent entry reached the transition as a value (a settle_b2 bug)")

    __add__ = __radd__ = __sub__ = __rsub__ = __lt__ = __le__ = __gt__ = __ge__ = __int__ = __index__ = _leak
    __bool__ = __len__ = __iter__ = __getitem__ = __contains__ = __str__ = __format__ = __float__ = _leak
    __eq__ = __ne__ = _leak
    __hash__ = object.__hash__

    def __repr__(self):
        return "ABSENT"

    def __deepcopy__(self, memo):
        return self


ABSENT = _Absent()


# ---- the families: every kind of exec-state entry, and the tree leaves it commits ---------------------------------------
def _amount_leaf(key, amt):
    v = int(amt)
    if v < 0 or v >= (1 << 256):
        raise Unprovable("an amount outside [0, 2^256) is committed as a tagged record")
    return [(key, B2.int_value(v))] if v else []


def _contract_leaves(p, c):
    out = [(B2.meta_key(p[0]), B2.meta_value(*B2.contract_meta(c)))]
    if c.get("code") is not None:
        out.append((B2.code_key(p[0]), B2.code_value(c["code"])))
    return out


def _slot_leaves(p, v):
    cid, slot = p
    try:
        s = int(slot)
    except (TypeError, ValueError):
        raise Unprovable(f"non-integer storage key {slot!r} (a KVX record)")
    if isinstance(v, bool) or not isinstance(v, int) or not (0 <= s < (1 << 256)) or not (0 <= v < (1 << 256)):
        raise Unprovable(f"storage {cid}[{slot}] is not a 256-bit integer slot (a KVX record)")
    return [(B2.slot_key(cid, s), B2.int_value(v))] if v else []


def _wd(tag):
    return lambda p, w: _amount_leaf(B2.record_key(tag, w["addr"], p[0]), w["amount"])


# name -> (half, leaves(path, value) -> [(leaf key, leaf bytes)], abs_key(path) -> the leaf whose absence proves the
# entry absent, or None when absence is not provable from one leaf)
FAMILIES = {
    "contracts": ("kv", _contract_leaves, lambda p: B2.meta_key(p[0])),
    "slots": ("kv", _slot_leaves, lambda p: B2.slot_key(p[0], int(p[1]))),
    "bridge": ("rec", lambda p, v: _amount_leaf(B2.record_key(T_BRIDGE_BAL, p[0]), v),
               lambda p: B2.record_key(T_BRIDGE_BAL, p[0])),
    "dividend": ("rec", lambda p, v: _amount_leaf(B2.record_key(T_DIV_BAL, p[0]), v),
                 lambda p: B2.record_key(T_DIV_BAL, p[0])),
    "abal": ("rec", lambda p, v: _amount_leaf(B2.record_key(T_ASSET_BAL, p[0], p[1]), v),
             lambda p: B2.record_key(T_ASSET_BAL, p[0], p[1])),
    "allow": ("rec", lambda p, v: _amount_leaf(B2.record_key(T_ASSET_ALLOW, p[0], p[1], p[2]), v),
              lambda p: B2.record_key(T_ASSET_ALLOW, p[0], p[1], p[2])),
    "assets": ("rec", lambda p, m: [(B2.record_key(T_ASSET_META, p[0], asset_meta_digest(m)), B2.ONE)], None),
    "wd": ("rec", _wd(T_BRIDGE_WD), None),
    "dwd": ("rec", _wd(T_DIV_WD), None),
    "uwd": ("rec", _wd(T_UNSHIELD_WD), None),
    "outbox": ("rec", lambda p, m: [(B2.record_key(T_DIGEST, "outbox", leaf_digest(msg_outbox_leaf(m))), B2.ONE)], None),
    "counter": ("rec", lambda p, v: _amount_leaf(B2.record_key(B2.T_COUNTER, p[0]), v),
                lambda p: B2.record_key(B2.T_COUNTER, p[0])),
    # the digest registry, committed from protocol.EXEC_ADDR_ROOT_HEIGHT (WitnessState.build picks it by the cursor)
    "addr": ("rec", lambda p, a: [(B2.record_key(B2.T_ADDR, p[0]), B2.addr_value(a))],
             lambda p: B2.record_key(B2.T_ADDR, p[0])),
}
# a NEW withdrawal / outbox entry is written without being read: its key is past the counter that numbers it, which the
# transition only ever increments, so no entry exists there (the blind-write rule, Store.write)
_NUMBERED_BY = {"wd": "wd_nonce", "dwd": "dw_nonce", "uwd": "uw_nonce", "outbox": "outbox_seq"}


def _contract_view(c):
    """the committed part of a contract record (what the meta and code leaves say), normalized as contract_meta reads it"""
    return {"code": c.get("code"), "deployer": c.get("deployer", ""), "upgradable": c.get("upgradable", True) is not False,
            "runtime": c.get("runtime", runtimes.DEFAULT_RUNTIME)}


class Store:
    """Every entry the replay touched: its PRE value (as opened) and its CURRENT value. `source(family, path)` supplies
    a pre value the first time an entry is touched (the prover: the real pre-state; the verifier: the openings)."""

    def __init__(self, source):
        self.source = source
        self.pre, self.cur = {}, {}
        self.blind = set()                               # entries written past their counter (never opened)

    def load(self, fam, path):
        k = (fam, path)
        if k not in self.cur:
            v = self.source(fam, path)
            self.pre[k] = copy.deepcopy(v) if v is not ABSENT else ABSENT
            if fam == "contracts" and v is not ABSENT:
                v = dict(v, storage={"slots": LeafMap(self, "slots", (path[0],))})
            self.cur[k] = v
        return self.cur[k]

    def write(self, fam, path, v):
        k = (fam, path)
        if k not in self.cur:
            ctr = _NUMBERED_BY.get(fam)
            if ctr is not None and int(path[0]) >= int(self.counter_pre(ctr)) + (0 if fam == "outbox" else 1):
                self.pre[k] = ABSENT                     # past the counter: provably new (see _NUMBERED_BY)
                self.cur[k] = ABSENT
                self.blind.add(k)
            else:
                self.load(fam, path)
        self.cur[k] = v

    def counter_pre(self, name):
        self.load("counter", (name,))
        v = self.pre[("counter", (name,))]
        return 0 if v is ABSENT else int(v)


class LeafMap(MutableMapping):
    """A dict over one family (under a fixed path prefix), whose entries come from the Store. Iteration and len() are
    not knowable from a witness and raise Unprovable."""

    def __init__(self, store, fam, prefix=()):
        self._s, self._f, self._p = store, fam, tuple(prefix)

    def _path(self, k):
        return self._p + (str(k),)

    def __getitem__(self, k):
        v = self._s.load(self._f, self._path(k))
        if v is ABSENT:
            raise KeyError(k)
        return v

    def __setitem__(self, k, v):
        self._s.write(self._f, self._path(k), v)

    def __delitem__(self, k):
        if self._s.load(self._f, self._path(k)) is ABSENT:
            raise KeyError(k)
        self._s.write(self._f, self._path(k), ABSENT)

    def __iter__(self):
        raise Unprovable(f"the transition iterates {self._f} (not knowable from a witness)")

    def __len__(self):
        raise Unprovable(f"the transition sizes {self._f} (not knowable from a witness)")

    def __bool__(self):
        # Only the ledger's PRUNING asks (asset_credit_dict / _allow_set: `if not row: drop the empty row`), and a row
        # dropped or kept commits the same leaves (zero is absent either way). Answering "non-empty" keeps the row,
        # which changes nothing in the root. Nothing else in the transition tests a ledger row's truth.
        return True

    def known(self):
        """the keys under this prefix the replay has touched"""
        n = len(self._p)
        return [k[1][n] for k in self._s.cur if k[0] == self._f and k[1][:n] == self._p and len(k[1]) == n + 1]


class Family:
    """The outer level of a nested ledger (abal: aid -> holder -> amount; allow: aid -> owner -> spender -> amount).
    Every aid has a row; dropping an empty row is root-neutral (LeafMap.__bool__), so pop() does nothing."""

    def __init__(self, store, fam, depth, prefix=()):
        self._s, self._f, self._d, self._p = store, fam, depth, tuple(prefix)

    def _row(self, k):
        p = self._p + (str(k),)
        return LeafMap(self._s, self._f, p) if self._d == 1 else Family(self._s, self._f, self._d - 1, p)

    def get(self, k, default=None):
        return self._row(k)

    __getitem__ = _row

    def setdefault(self, k, default=None):
        return self._row(k)

    def pop(self, k, default=None):
        return default

    def __bool__(self):
        return True

    def __contains__(self, k):
        raise Unprovable(f"the transition asks whether {self._f} has a row (not knowable from a witness)")

    def __iter__(self):
        raise Unprovable(f"the transition iterates {self._f} (not knowable from a witness)")

    def items(self):
        raise Unprovable(f"the transition iterates {self._f} (not knowable from a witness)")


class Overlay(MutableMapping):
    """A call's storage writes over the storage it started from; the call commits by becoming the contract's storage
    (state.py: `c["storage"] = new_storage`), or is dropped on revert, exactly like the runtime's copy."""

    def __init__(self, base):
        self.base, self.w = base, {}

    def __getitem__(self, k):
        k = str(k)
        if k in self.w:
            if self.w[k] is ABSENT:
                raise KeyError(k)
            return self.w[k]
        return self.base[k]

    def __setitem__(self, k, v):
        self.w[str(k)] = v

    def __delitem__(self, k):
        self[k]
        self.w[str(k)] = ABSENT

    def __iter__(self):
        raise Unprovable("the transition iterates a contract's storage (not knowable from a witness)")

    def __len__(self):
        raise Unprovable("the transition sizes a contract's storage (not knowable from a witness)")


class Forbidden:
    """State the witness does not carry: any use raises Unprovable naming it."""

    def __init__(self, what):
        object.__setattr__(self, "_what", what)

    def _no(self, *a, **k):
        raise Unprovable(f"the span touches {object.__getattribute__(self, '_what')}, which a witness cannot carry yet")

    __getattr__ = __getitem__ = __setitem__ = __contains__ = __iter__ = __len__ = __call__ = _no

    def __bool__(self):
        self._no()


class Registry(MutableMapping):
    """The digest -> address registry, as the SPAN builds it: an address registered at a call boundary inside the span
    resolves; one registered earlier is not knowable (the registry is not committed in the root), so resolving it raises
    Unprovable instead of answering None (which the runtime would turn into a revert the chain never made)."""

    def __init__(self):
        self.d = {}

    def __getitem__(self, k):
        if k not in self.d:
            raise Unprovable(f"a payee digest {str(k)[:16]}... registered before the span (the registry is not committed)")
        return self.d[k]

    def get(self, k, default=None):
        return self[k]

    def __setitem__(self, k, v):
        self.d[k] = v

    def __delitem__(self, k):
        del self.d[k]

    def __iter__(self):
        return iter(self.d)

    def __len__(self):
        return len(self.d)


def _counter(name):
    return property(lambda s: (lambda v: 0 if v is ABSENT else v)(s._store.load("counter", (name,))),
                    lambda s, v: s._store.write("counter", (name,), int(v) if int(v) else ABSENT))


def _carry_get(s):
    if s._carry_committed:                       # from EXEC_CARRY_ROOT_HEIGHT: the pre root's T_COUNTER "div_carry"
        v = s._store.load("counter", (B2.CARRY_COUNTER,))
        return 0 if v is ABSENT else v
    return s._carry_chain


def _carry_set(s, v):
    if s._carry_committed:
        s._store.write("counter", (B2.CARRY_COUNTER,), int(v) if int(v) else ABSENT)
    else:
        s._carry_chain = int(v)


class WitnessState(ExecState):
    """ExecState over a Store. Built by __new__ (no disk); every field the transition may touch is a witness map, a
    chain input, or Forbidden."""
    wd_nonce = _counter("wd_nonce")
    dw_nonce = _counter("dw_nonce")
    uw_nonce = _counter("uw_nonce")
    outbox_seq = _counter("outbox_seq")
    # THE DIVIDEND CARRY. From protocol.EXEC_CARRY_ROOT_HEIGHT it is a committed record, read and written through the
    # witness like the counters above: the accrual opens it against the pre root (a forged value fails the leaf check, an
    # omitted one is Unprovable), and its new value is a leaf change the post root must carry. Below the gate no root
    # commits it and it is Chain.div_carry, which only the exec node's own bookkeeping can supply (the prover, the shadow
    # run, the tests); L1 has no such input and refuses those spans (ops/settle_chain.l1_chain).
    # INVARIANT: never read Chain.div_carry for a span whose start commits the carry — the pre root is the authority.
    div_carry = property(_carry_get, _carry_set)

    @classmethod
    def build(cls, store, cursor, div_carry, oracle):
        st = cls.__new__(cls)
        st._store, st._oracle = store, oracle
        st.path = None
        st._mutate_lock = threading.RLock()
        st.contracts = LeafMap(store, "contracts")
        st.bridge = LeafMap(store, "bridge")
        st.dividend = LeafMap(store, "dividend")
        st.abal = Family(store, "abal", 1)
        st.allow = Family(store, "allow", 2)
        st.assets = LeafMap(store, "assets")
        st.withdrawals = LeafMap(store, "wd")
        st.dividend_withdrawals = LeafMap(store, "dwd")
        st.unshield_withdrawals = LeafMap(store, "uwd")
        st.outbox = LeafMap(store, "outbox")
        # from the gate the registry is a committed ledger like any other: an entry is opened, or proven absent, and a
        # digest the chain lacks resolves to None here too (the call reverts on both sides). Before it, only what the
        # span itself registers is knowable (Registry).
        st.zk_addrs = LeafMap(store, "addr") if B2.addr_root_at(cursor) else Registry()
        st.cursor, st.block_ts = int(cursor), 0
        st._carry_committed = B2.carry_root_at(cursor)
        if not st._carry_committed:
            if div_carry is None or isinstance(div_carry, bool) or not isinstance(div_carry, int) or div_carry < 0:
                raise Unprovable("the span starts below EXEC_CARRY_ROOT_HEIGHT and no dividend carry was supplied")
            st._carry_chain = int(div_carry)
        from protocol import EPOCH_LENGTH
        st.last_div_epoch = int(cursor) // EPOCH_LENGTH - 1 if int(cursor) >= 0 else -1
        st.beacons, st.block_hashes = {}, {}          # the oracle checks chain reads against Chain, never these
        for name in ("inbox", "stwo_pool", "randao_reveals",
                     "pool_value", "pool_fees", "stwo_value"):
            object.__setattr__(st, name, Forbidden(name))
        return st

    def _touch(self):
        pass

    # chain bookkeeping: L1-derived inputs the oracle checks against Chain directly
    def record_reveal(self, target_epoch, secret):
        pass

    def advance_beacons(self, cursor):
        pass

    def record_block_hash(self, height, block_hash):
        pass

    def _rt_run(self, rt, code, method, caller, args, storage, **kw):
        return self._oracle.run(self, rt, code, method, caller, args, storage, **kw)


# ---- the VM oracle --------------------------------------------------------------------------------------------------
class Oracle:
    """Stands in for runtimes._ZkVM.run in the replay. `runs` are the VM runs in call order ({"ok", "io", "n_steps"});
    `chain` checks chain reads. Collects the VM statement (one entry per run) for the Stwo proof."""

    def __init__(self, runs, chain):
        self.runs, self.chain, self.i = list(runs), chain, 0
        self.calls = []                  # (prog as [(op id, d, s, imm)], args, ctx[4], actx[4], io, n_steps)

    def run(self, st, rt, code, method, caller, args, storage, value=0, cursor=0, timestamp=0, beacons=None,
            block_hashes=None, registry=None, asset=0, selfd=0, abal=None, meter=None):
        # BLAKE_EXEC_HEIGHT (gen 28's gate, 1 from gen 29, inlined in G9): every cursor's zkvm call is a zkvm2 call
        if getattr(rt, "name", None) != "zkvm":
            raise Unprovable("a call on a runtime other than the gen-29 zkvm2")
        reg = registry if registry is not None else {}
        try:
            cf, fargs = runtimes.zkvm_statement(caller, args, reg)
        except ValueError:
            return (False, None, storage, [], [])      # runtimes.run: refused before the VM, no steps
        if method not in code or len(fargs) > zkvm2.MAX_ARGS:
            return (False, None, storage, [], [])      # zkvm2.run: refused before the first step, no steps metered
        if self.i >= len(self.runs):
            raise Refused("the witness has fewer VM runs than the span makes calls")
        r = self.runs[self.i]
        self.i += 1
        if meter is not None:
            meter["gas"] = int(r["n_steps"])
        io = [tuple(int(x) for x in e) for e in r["io"]]
        n = int(r["n_steps"])
        kind = None if r["ok"] else r.get("revert")
        if not r["ok"] and not (isinstance(kind, int) and 0 <= kind < len(zkvm2.REVERT_KINDS)):
            raise Refused("a reverted VM run without a revert kind")
        if not (1 <= n <= zkvm2.GAS_LIMIT) or (kind == zkvm2.REVERT_KINDS.index("OOG") and n != zkvm2.GAS_LIMIT):
            raise Refused("a VM run's step count is outside [1, GAS_LIMIT] (or an out-of-gas run short of it)")
        slots_in = storage.get("slots") if isinstance(storage, dict) else None
        if slots_in is None:
            slots_in = {}                                # runtimes.run: `storage.get("slots") or {}`, no truth test here
        new = Overlay(slots_in)                          # a reverted run's writes are dropped with this overlay
        self._walk(st, io, new, abal, int(selfd) & MASK, cursor, kind)
        prog = [(zkvm2.OP[ins[0]], int(ins[1]), int(ins[2]), int(ins[3]) & MASK) for ins in code[method]]
        ctx = [cf & MASK, int(value) & MASK, int(cursor) & MASK, int(timestamp) & MASK]
        actx = [int(asset) & MASK, int(selfd) & MASK, 0, 0]
        self.calls.append((prog, [int(a) & MASK for a in fargs], ctx, actx, io, n, kind))
        if kind is not None:
            return (False, None, storage, [], [])        # zkvm2.run's revert: the storage the call started with
        split = runtimes.split_io(io, reg)
        if split is None:
            return (False, None, storage, [], [])
        payouts, effects = split
        ret = io[-1][1]
        return (True, ret, {"slots": new}, payouts, effects)

    def _walk(self, st, io, slots, abal, selfd, cursor, revert=None):
        """zkvm2.run's io-visible rules, entry by entry (the Stwo proof binds every other step to these entries). A
        REVERTED run (`revert`, a zkvm2.REVERT_KINDS index) has no RET; for the four kinds the circuit cannot judge, its
        last entry is the reverting step's own and must fail here exactly as zkvm2 fails it: an asset PAY or ABURN beyond
        the holding, a BHASH or BEACON the chain does not hold for this height."""
        asel, apend = 0, {}
        RK = zkvm2.REVERT_KINDS

        def have(a):
            return int((abal or {}).get(a, 0)) + apend.get(a, 0)

        def aspend(a, amt):
            if amt > have(a):
                raise Refused("a VM run spends more of an asset than the contract holds (zkvm2 would revert)")
            apend[a] = apend.get(a, 0) - amt

        judged = revert is not None and RK[revert] in ("PAY", "ABURN", "BHASH", "BEACON")
        if revert is None:
            if not io or io[-1][0] != zkvm2.IO_RET or any(e[0] == zkvm2.IO_RET for e in io[:-1]):
                raise Refused("a VM run's io log does not end in exactly one RET")
        elif any(e[0] == zkvm2.IO_RET for e in io) or (judged and not io):
            raise Refused("a reverted VM run's io log returns, or lacks its reverting entry")
        last = io[-1] if judged else None
        for kind, a, b in (io[:-1] if judged else io):
            if not all(0 <= x <= MASK for x in (kind, a, b)):
                raise Refused("an io entry outside the 256-bit word")
            if asel and kind not in (zkvm2.IO_PAY, zkvm2.IO_AMINT):
                raise Refused("an asset selection not spent by the very next entry")
            if kind == zkvm2.IO_SLOAD:
                if int(slots.get(str(a), 0)) != b:
                    raise Refused("an SLOAD value that is not the state's")
            elif kind == zkvm2.IO_SSTORE:
                if b == 0:
                    slots.pop(str(a), None)
                else:
                    slots[str(a)] = b
            elif kind == zkvm2.IO_PAY:
                if asel:
                    if not (selfd and a == selfd):
                        aspend(asel, b)
                    asel = 0
            elif kind in (zkvm2.IO_BHASH, zkvm2.IO_BEACON):
                if self.chain.read(kind, a, int(cursor)) != b:
                    raise Refused("a chain read (BHASH/BEACON) that is not the chain's, or not available yet")
            elif kind == zkvm2.IO_ASEL:
                if a == 0:
                    raise Refused("ASEL of asset 0")
                asel = a
            elif kind == zkvm2.IO_AMINT:
                if selfd and a == selfd:
                    apend[asel] = apend.get(asel, 0) + b
                asel = 0
            elif kind == zkvm2.IO_ABURN:
                aspend(a, b)
            elif kind == zkvm2.IO_ABAL:
                if (int((abal or {}).get(a, 0)) + apend.get(a, 0)) & MASK != b:
                    raise Refused("an ABAL value that is not the ledger's")
            elif kind in (zkvm2.IO_ARENOUNCE, zkvm2.IO_RET):
                pass
            else:
                raise Refused(f"an io entry of unknown kind {kind}")
        if last is not None:
            kind, a, b = last
            k = RK[revert]
            if k == "PAY":
                # zkvm2: PAY under a selection spends it unless the payee is the contract itself; only that can revert
                if kind != zkvm2.IO_PAY or not asel or (selfd and a == selfd) or not b > have(asel):
                    raise Refused("a PAY revert that is not an overspend of the selected asset")
            elif k == "ABURN":
                if kind != zkvm2.IO_ABURN or asel or not b > have(a):
                    raise Refused("an ABURN revert that is not an overspend")
            else:
                want = zkvm2.IO_BHASH if k == "BHASH" else zkvm2.IO_BEACON
                if kind != want or b != 0 or asel or self.chain.read(kind, a, int(cursor)) is not None:
                    raise Refused("a BHASH/BEACON revert for a value the chain holds at this height")


# ---- the chain inputs ------------------------------------------------------------------------------------------------
class Chain:
    """What L1 supplies itself. `accrual(E) -> (inflow, weights)`; `div_carry` at the span's start, consulted ONLY for a
    span starting below protocol.EXEC_CARRY_ROOT_HEIGHT (from it the carry is the pre root's record, WitnessState.div_carry;
    L1 passes None); `read(kind, key, height) -> value or None` (None: not readable by a call in block `height`, so the VM
    would have reverted)."""

    def __init__(self, accrual, div_carry, read):
        self.accrual, self.div_carry, self.read = accrual, div_carry, read


# ---- the replay (prover and verifier alike) ----------------------------------------------------------------------------
def _replay(store, blocks, cursor, chain, runs):
    """Apply `blocks` (in order, starting after `cursor`) to a WitnessState over `store`. Returns (state, oracle)."""
    from protocol import EPOCH_LENGTH
    if blocks and B2.addr_root_at(int(blocks[-1]["block_number"])) and not B2.addr_root_at(int(cursor)):
        # the first root at EXEC_ADDR_ROOT_HEIGHT inserts the WHOLE registry, which no witness carries. Refusing here is
        # load-bearing for the verifier: replayed without that insert, the span would compute a root the chain never
        # had, and a prover could claim exactly that root.
        raise Unprovable("the span crosses EXEC_ADDR_ROOT_HEIGHT (the registry's first root)")
    if blocks and B2.carry_root_at(int(blocks[-1]["block_number"])) and not B2.carry_root_at(int(cursor)):
        # the same for the carry: the first root at EXEC_CARRY_ROOT_HEIGHT inserts the div_carry record, which the pre
        # root does not hold and no witness can open. Replayed without it, the span would compute a root the chain never
        # had. Load-bearing for the verifier, like the registry's refusal above.
        raise Unprovable("the span crosses EXEC_CARRY_ROOT_HEIGHT (the carry's first root)")
    oracle = Oracle(runs, chain)
    st = WitnessState.build(store, cursor, chain.div_carry, oracle)
    states = {NS: st}
    prev = int(cursor)
    for block in blocks:
        h = int(block["block_number"])
        if h != prev + 1:
            raise Refused(f"block {h} does not follow {prev}")
        prev = h
        if "block_transactions" not in block:
            raise Unprovable(f"block {h} has no body (pruned)")
        for tx in block["block_transactions"]:
            d = tx.get("data")
            if isinstance(d, dict) and d.get("op") in ("field_transfer", "private_call"):
                raise Unprovable(f"block {h} carries a {d.get('op')} (a pool op riding DA)")
        while st.last_div_epoch < h // EPOCH_LENGTH - 1:        # canonical accrual before the block (execnode._accrue_owed)
            E = st.last_div_epoch + 1
            inflow, weights = chain.accrual(E)
            st.accrue_dividend_epoch(inflow, weights, epoch=E)
            st.last_div_epoch = E
        # (no stark.rules_at around the apply: the proof rules only steered the Goldilocks verifier, deleted in G9 slice 4)
        block_apply.begin(states, h)
        block_apply.dispatch(states, st, block, {}, set(), verbose=bool(os.environ.get("NADO_SETTLE_DEBUG")))
        block_apply.close(states, h, block.get("block_hash"))
    if oracle.i != len(oracle.runs):
        raise Refused("the witness has more VM runs than the span makes calls")
    return st, oracle


def _final_value(store, k):
    """the current value of an entry, as its family commits it (a contract: its committed record, not its storage)"""
    v = store.cur[k]
    if v is ABSENT:
        return ABSENT
    if k[0] == "contracts":
        return _contract_view(v)
    return v


def _slot_finals(store, cid, c):
    """{slot: final value or ABSENT} for every slot of `cid` the replay touched, read through the contract's final
    storage. A pre-existing contract's storage must still descend from its witness map: one replaced wholesale would
    drop slots the replay never saw."""
    slots = (c.get("storage") or {}).get("slots") if c is not ABSENT else None
    chain, m = [], slots
    while isinstance(m, Overlay):
        chain.append(m)
        m = m.base
    base_is_witness = isinstance(m, LeafMap) and m._f == "slots" and m._p == (cid,)
    existed = store.pre.get(("contracts", (cid,)), ABSENT) is not ABSENT
    if existed and not base_is_witness and c is not ABSENT:
        raise Unprovable(f"contract {cid}'s storage was replaced wholesale")
    keys = set(LeafMap(store, "slots", (cid,)).known())
    for o in chain:
        keys |= set(o.w)
    if isinstance(m, dict):
        keys |= set(m)
    out = {}
    for k in keys:
        if c is ABSENT:
            out[k] = ABSENT
            continue
        v = slots.get(k, ABSENT) if slots is not None else ABSENT
        out[k] = ABSENT if (v is ABSENT or v == 0) else v
    return out


def _changes(store):
    """-> ({leaf key: new bytes or None} per half, the set of leaf keys every opening and change depends on, per half)"""
    ch = {"kv": {}, "rec": {}}
    need = {"kv": set(), "rec": set()}

    def diff(fam, path, pre, post):
        half, leaves, abs_key = FAMILIES[fam]
        a = dict(leaves(path, pre)) if pre is not ABSENT else {}
        b = dict(leaves(path, post)) if post is not ABSENT else {}
        need[half] |= set(a) | set(b)
        if pre is ABSENT and abs_key is not None:
            need[half].add(abs_key(path))
        for lk in set(a) | set(b):
            if a.get(lk) != b.get(lk):
                if lk in ch[half] and ch[half][lk] != b.get(lk):
                    raise Refused("two entries write one leaf")
                ch[half][lk] = b.get(lk)

    contracts = set()
    for k in list(store.cur):
        fam, path = k
        if fam == "slots":
            contracts.add(path[0])
            continue
        pre = store.pre[k]
        post = _final_value(store, k)
        diff(fam, path, _contract_view(pre) if (fam == "contracts" and pre is not ABSENT) else pre, post)
        if fam == "contracts":
            contracts.add(path[0])
    for cid in sorted(contracts):
        c = store.cur.get(("contracts", (cid,)), ABSENT)
        for slot, post in _slot_finals(store, cid, c).items():
            pre = store.pre.get(("slots", (cid, slot)), ABSENT)
            diff("slots", (cid, slot), pre, post)
    return ch, need


# ---- the VM statement and the Stwo proof -----------------------------------------------------------------------------
def vm_statement_text(calls):
    """the statement as native/stwo_settle's vm::parse_statement reads it; identical programs share one PROG"""
    progs, pidx, lines = [], {}, []
    h = "%064x".__mod__
    for prog, *_ in calls:
        key = tuple(prog)
        if key not in pidx:
            pidx[key] = len(progs)
            progs.append(prog)
    for p in progs:
        lines.append(f"PROG {len(p)}")
        lines += [f"I {o} {d} {s} {h(i)}" for o, d, s, i in p]
    for prog, args, ctx, actx, io, n, revert in calls:
        lines.append(f"CALL {pidx[tuple(prog)]} {n}" + (f" REVERT {revert}" if revert is not None else ""))
        lines.append("ARGS " + " ".join(h(a) for a in args))
        lines.append("CTX " + " ".join(h(x) for x in ctx))
        lines.append("ACTX " + " ".join(h(x) for x in actx))
        lines += [f"IO {k} {h(a)} {h(b)}" for k, a, b in io]
    return "\n".join(lines) + "\n"


def _vm_settle(binary, mode, text, proof_bytes=None):
    with tempfile.TemporaryDirectory(prefix="nado-vm-settle-") as d:
        sp, pp = os.path.join(d, "stmt.txt"), os.path.join(d, "proof.bin")
        with open(sp, "w") as f:
            f.write(text)
        if proof_bytes is not None:
            with open(pp, "wb") as f:
                f.write(proof_bytes)
        r = subprocess.run([binary, mode, sp, pp], capture_output=True, text=True, timeout=3600)
        out = r.stdout.strip().splitlines()
        last = out[-1] if out else (r.stderr.strip()[-300:] or "no output")
        if mode == "prove":
            if r.returncode != 0 or not last.startswith("PROVED"):
                raise RuntimeError(f"vm_settle prove: {last}")
            with open(pp, "rb") as f:
                return f.read()
        if r.returncode != 0:
            raise RuntimeError(f"vm_settle verify: {last}")   # a broken invocation is not a verdict
        return last


def _vm_verify(text, proof_bytes, binary=None):
    """"OK" or "REFUSED <why>": the node's native verifier (execnode/stwo_settle_native.py, a stable build of
    native/stwo_settle) when this machine has it; else, only when the caller names one, the prover's vm_settle binary
    (tests and the shadow run). A node with neither raises NativeMissing: a fact about the machine, never a verdict."""
    from execnode import stwo_settle_native as N
    from execnode.native_guard import NativeMissing
    try:
        ok, why = N.verify(text, proof_bytes)
        return "OK" if ok else f"REFUSED {why}"
    except NativeMissing:
        if binary is None:
            raise
        return _vm_settle(binary, "verify", text, proof_bytes)


# ---- the bundle (JSON) ---------------------------------------------------------------------------------------------------
def _enc(v):
    return None if v is ABSENT else v


def _dec(v):
    return ABSENT if v is None else v


def _proof_json(p):
    sibs, term = p
    t = ["empty"] if term[0] == "empty" else ["leaf", term[1].hex(), term[2].hex()]
    return {"s": [s.hex() for s in sibs], "t": t}


def _proof_from_json(j):
    sibs = [bytes.fromhex(s) for s in j["s"]]
    t = j["t"]
    term = ("empty",) if t == ["empty"] else ("leaf", bytes.fromhex(t[1]), bytes.fromhex(t[2]))
    return sibs, term


def _open_json(pre):
    return {"leaf": lambda p: ["leaf", p[1].hex(), p[2].hex()], "node": lambda p: ["node", p[1].hex(), p[2].hex()]}[pre[0]](pre)


def _open_from_json(j):
    return (j[0], bytes.fromhex(j[1]), bytes.fromhex(j[2]))


# ---- PROVE ---------------------------------------------------------------------------------------------------------------
def span_post_root(pre_root: bytes, changes, proof_value, opens=None, on_open=None):
    """(post root, the openings used) of one tree half after `changes` ({key: value or None}), from the pre root and the
    changed keys' proofs: `proof_value(key) -> (value at the pre root, proof)`. THE ONE construction prove_span and
    verify_span share: the prover passes `on_open` (it holds the full tree) and records what it opened, the verifier
    passes those `opens`. Built from the CHANGED keys only — the verifier merges no other proof — so every subtree a delete
    collapses into is one the prover had to open, and recorded. Two hand-kept copies of this loop once disagreed (the
    prover also merged read-only keys' proofs; shadow span 8160 -> 8220, 2026-10-27, "a delete needs a sibling opened").
    May raise Missing (an opening the witness lacks) or ValueError (a bad proof or opening)."""
    pt = PartialTree(pre_root, opens=opens, on_open=on_open)
    for k in sorted(set(changes)):
        v, proof = proof_value(k)
        pt.add_proof(k, v, proof)
    pt.apply(changes)
    return pt.root(), pt.opens


def prove_span(pre_state, blocks, chain, binary):
    """-> bundle (a JSON-able dict) proving `blocks` applied to `pre_state` (an ExecState at the span's start; not
    modified). Raises Unprovable naming why a span cannot be proven."""
    real = pre_state.clone()
    trace = []
    real._rt_run = lambda rt, *a, **kw: ExecState._rt_run(rt, *a, trace=trace, **kw)
    states = {NS: real}
    from protocol import EPOCH_LENGTH
    for block in blocks:
        h = int(block["block_number"])
        while real.last_div_epoch < h // EPOCH_LENGTH - 1:
            E = real.last_div_epoch + 1
            inflow, weights = chain.accrual(E)
            real.accrue_dividend_epoch(inflow, weights, epoch=E)
            real.last_div_epoch = E
        # (no stark.rules_at around the apply: the proof rules only steered the Goldilocks verifier, deleted in G9 slice 4)
        block_apply.begin(states, h)
        block_apply.dispatch(states, real, block, {}, set(), verbose=False)
        block_apply.close(states, h, block.get("block_hash"))
    post_root = B2.state_root_hex(real.contracts, real)

    src = pre_state.clone()
    kv_tree = csmt.Tree(B2.kv_projection(src.contracts))
    rec_tree = csmt.Tree(B2.records_projection(src))

    def source(fam, path):
        return _real_entry(src, fam, path)
    store = Store(source)
    _replay(store, blocks, pre_state.cursor, chain, trace)
    changes, need = _changes(store)
    trees = {"kv": kv_tree, "rec": rec_tree}
    roots, proofs, opens = {}, {}, {}
    for half in ("kv", "rec"):
        t = trees[half]
        keys = sorted(need[half] | set(changes[half]))
        proofs[half] = {k.hex(): _proof_json(t.prove(k)) for k in keys}
        # INVARIANT: the same span_post_root verify_span calls (see its docstring for why it must be one function)
        roots[half], used = span_post_root(t.root(), changes[half], lambda k, t=t: (t.get(k), t.prove(k)),
                                           on_open=opener_for(t))
        opens[half] = {h.hex(): _open_json(p) for h, p in used.items()}
    if B2.full_root(roots["kv"], roots["rec"]).hex() != post_root:
        raise RuntimeError("the witness replay's root is not the transition's (a bug in settle_b2, not the span)")
    bundle = {
        "v": 1, "cursor": int(pre_state.cursor), "post_cursor": int(blocks[-1]["block_number"]) if blocks else int(pre_state.cursor),
        "kv_pre": kv_tree.root().hex(), "rec_pre": rec_tree.root().hex(), "post_root": post_root,
        "openings": [[f, list(p), _enc(_jsonable(store.pre[(f, p)]))] for (f, p) in sorted(store.pre, key=_okey)
                     if (f, p) not in store.blind],
        "proofs": proofs, "opens": opens,
        "runs": [{"ok": r["ok"], "io": [list(e) for e in r["io"]], "n_steps": r["n_steps"], "revert": r.get("revert")}
                 for r in trace],
    }
    # the Stwo proof of every VM run, over the statement the VERIFIER will rebuild (verify_span recomputes it)
    stmt = _statement_of(bundle, blocks, chain)
    bundle["vm_proof"] = _vm_settle(binary, "prove", stmt).hex() if stmt is not None else None
    ok, why, root = verify_span(int(pre_state.cursor), B2.full_root(kv_tree.root(), rec_tree.root()).hex(), blocks, chain,
                                bundle, binary)
    if not ok or root != post_root:
        raise RuntimeError(f"the prover's own bundle does not verify: {why}")
    return bundle


def _okey(k):
    return (k[0], tuple(str(x) for x in k[1]))


def _jsonable(v):
    if v is ABSENT:
        return ABSENT
    return json.loads(json.dumps(v))


def _real_entry(st, fam, path):
    """the PRE value of one entry in a full ExecState, normalized exactly as the verifier reconstructs it from leaves"""
    def amt(x):
        x = int(x or 0)
        return x if x else ABSENT
    if fam == "contracts":
        c = st.contracts.get(path[0])
        return ABSENT if c is None else copy.deepcopy(_contract_view(c))
    if fam == "slots":
        c = st.contracts.get(path[0])
        v = ((c or {}).get("storage") or {}).get("slots", {}).get(path[1]) if c else None
        return amt(v) if v is None or isinstance(v, int) else v
    if fam == "bridge":
        return amt(st.bridge.get(path[0]))
    if fam == "dividend":
        return amt(st.dividend.get(path[0]))
    if fam == "abal":
        return amt(st.abal.get(path[0], {}).get(path[1]))
    if fam == "allow":
        return amt(st.allow.get(path[0], {}).get(path[1], {}).get(path[2]))
    if fam == "counter":
        return amt(getattr(st, path[0], 0))
    if fam == "addr":
        a = st.zk_addrs.get(path[0])
        return ABSENT if a is None else a
    m = {"assets": st.assets, "wd": st.withdrawals, "dwd": st.dividend_withdrawals, "uwd": st.unshield_withdrawals,
         "outbox": st.outbox}[fam]
    v = m.get(path[0])
    if v is None:
        raise Unprovable(f"the span reads a missing {fam} entry {path[0]!r} (absence is not provable for it)")
    return copy.deepcopy(v)


# ---- VERIFY --------------------------------------------------------------------------------------------------------------
def _statement_of(bundle, blocks, chain):
    """replay the bundle's witness and return the VM statement text (None: the span runs no contract call)"""
    store = _verifier_store(bundle)
    _st, oracle = _replay(store, blocks, int(bundle["cursor"]), chain, bundle["runs"])
    return vm_statement_text(oracle.calls) if oracle.calls else None


def _verifier_store(bundle):
    """the Store over the bundle's openings, each checked against the pre halves' proofs; Refused on any mismatch"""
    truth = {"kv": {}, "rec": {}}
    roots = {"kv": bytes.fromhex(bundle["kv_pre"]), "rec": bytes.fromhex(bundle["rec_pre"])}
    for half in ("kv", "rec"):
        for khex, pj in bundle["proofs"][half].items():
            k = bytes.fromhex(khex)
            sibs, term = _proof_from_json(pj)
            val = term[2] if (term[0] == "leaf" and term[1] == k) else None
            if not csmt.verify(roots[half], k, val, (sibs, term)):
                raise Refused(f"a {half} proof does not verify against the pre root")
            truth[half][k] = val
    opened = {}
    for fam, path, v in bundle["openings"]:
        if fam not in FAMILIES:
            raise Refused(f"an opening of unknown family {fam!r}")
        half, leaves, abs_key = FAMILIES[fam]
        path = tuple(str(x) for x in path)
        v = _dec(v)
        t = truth[half]
        if v is ABSENT:
            if abs_key is None:
                raise Refused(f"an opening claims a {fam} entry absent, which no leaf can show")
            if t.get(abs_key(path), b"?") is not None:
                raise Refused(f"an opening claims {fam} {path} absent; the tree disagrees or has no proof")
        else:
            if fam in ("bridge", "dividend", "abal", "allow", "counter") and (isinstance(v, bool) or not isinstance(v, int) or v <= 0):
                raise Refused(f"a {fam} opening is not a positive integer (zero is absent)")
            if fam == "slots" and (isinstance(v, bool) or not isinstance(v, int) or v <= 0):
                raise Refused("a slot opening is not a positive integer (zero is absent)")
            if fam == "addr" and not isinstance(v, str):
                raise Refused("a registry opening is not an address string")
            if fam == "contracts" and not (isinstance(v, dict) and set(v) == {"code", "deployer", "upgradable", "runtime"}
                                           and isinstance(v["code"], dict) and isinstance(v["upgradable"], bool)):
                raise Refused("a malformed contract opening")
            lv = leaves(path, v)
            if not lv or any(t.get(lk, b"?") != lb for lk, lb in lv):
                raise Refused(f"an opening of {fam} {path} does not match the tree")
        if (fam, path) in opened:
            raise Refused(f"{fam} {path} opened twice")
        opened[(fam, path)] = v

    def source(fam, path):
        if (fam, path) not in opened:
            raise Unprovable(f"the span touches {fam} {path}, which the witness does not open")
        return copy.deepcopy(opened[(fam, path)])
    store = Store(source)
    store.truth = truth
    return store


def verify_span(cursor, pre_root, blocks, chain, bundle, binary=None):
    """(ok, reason, post_root hex) for the span `blocks` after `cursor` from `pre_root`, under `chain`'s inputs.
    ok False with a reason on any refusal; Unprovable is also a refusal here (the bundle does not prove the span).
    The VM proof is checked by the native verifier (_vm_verify; `binary` only as the fallback a prover or a test has).
    NativeMissing (no verifier on this machine) propagates: it is not a verdict."""
    try:
        if not isinstance(bundle, dict) or bundle.get("v") != 1 or int(bundle.get("cursor", -2)) != int(cursor):
            return False, "malformed bundle or wrong cursor", None
        if B2.full_root(bytes.fromhex(bundle["kv_pre"]), bytes.fromhex(bundle["rec_pre"])).hex() != pre_root:
            return False, "the pre halves do not compose to the pre root", None
        store = _verifier_store(bundle)
        _st, oracle = _replay(store, blocks, int(cursor), chain, bundle["runs"])
        changes, need = _changes(store)
        roots = {}
        for half in ("kv", "rec"):
            pre = bytes.fromhex(bundle["kv_pre" if half == "kv" else "rec_pre"])
            opens = {bytes.fromhex(h): _open_from_json(p) for h, p in bundle["opens"][half].items()}
            missing = [k for k in changes[half] if k.hex() not in bundle["proofs"][half]]
            if missing:
                return False, f"no {half} proof for a changed leaf", None
            # INVARIANT: the same span_post_root prove_span calls
            roots[half], _ = span_post_root(pre, changes[half], lambda k, half=half: (
                store.truth[half][k], _proof_from_json(bundle["proofs"][half][k.hex()])), opens=opens)
        post = B2.full_root(roots["kv"], roots["rec"]).hex()
        if oracle.calls:
            pb = bundle.get("vm_proof")
            if not isinstance(pb, str):
                return False, "no VM proof for a span with contract calls", None
            verdict = _vm_verify(vm_statement_text(oracle.calls), bytes.fromhex(pb), binary)
            if verdict != "OK":
                return False, f"the VM proof: {verdict}", None
        elif bundle.get("vm_proof") is not None:
            return False, "a VM proof for a span with no contract call", None
        if post != bundle.get("post_root"):
            return False, "the replayed post root is not the bundle's", None
        return True, "ok", post
    except Unprovable as e:
        return False, f"unprovable from this witness: {e}", None
    except Refused as e:
        return False, f"refused: {e}", None
    except Missing as e:
        return False, f"the witness does not reveal enough of the tree: {e}", None
    except (ValueError, KeyError, TypeError, IndexError) as e:
        return False, f"malformed bundle: {type(e).__name__}: {e}", None


# ---- THE SHADOW RUN (G8's two weeks of off-chain proofs, doc/stwo-migration.md 9.5) ----------------------------------------
def reference_chain(pre_state, blocks, accrual):
    """The Chain a from-genesis exec node would give a call in each block: its beacons and block hashes as they stand when
    the block opens, from a replay of `blocks` on a copy of `pre_state` (the exec node's own bookkeeping), and `accrual`.
    For the shadow run and the tests; L1's verifier derives the same from its own state (doc section 5, next steps)."""
    from protocol import EPOCH_LENGTH
    ref = pre_state.clone()
    seen = {}
    states = {NS: ref}
    for b in blocks:
        h = int(b["block_number"])
        while ref.last_div_epoch < h // EPOCH_LENGTH - 1:
            E = ref.last_div_epoch + 1
            ref.accrue_dividend_epoch(*accrual(E), epoch=E)
            ref.last_div_epoch = E
        seen[h] = (dict(ref.beacons), dict(ref.block_hashes))
        # (no stark.rules_at around the apply: the proof rules only steered the Goldilocks verifier, deleted in G9 slice 4)
        block_apply.begin(states, h)
        block_apply.dispatch(states, ref, b, {}, set(), verbose=False)
        block_apply.close(states, h, b.get("block_hash"))

    def read(kind, key, h):
        bc, bh = seen[h]
        v = (bc if kind == zkvm2.IO_BEACON else bh).get(key)
        return None if v is None else int(v) & MASK
    ch = Chain(accrual, pre_state.div_carry, read)
    ch.seen = seen          # what the exec node held as each block opened: ops/settle_chain.compare_with_reference reads it
    return ch


def shadow_span(pre_state, blocks, want_root, accrual, binary, l1_inputs=None):
    """Prove `blocks` from `pre_state` (an ExecState at a settled cursor) and verify the proof as L1 would, then compare
    the verified post root with `want_root`, the exec node's own root after the span. -> a JSON-able record:
    {"from", "to", "blocks", "calls", "reverts", "steps", "result": "proven" | "unprovable" | "refused" | "mismatch",
     "reason", "prove_s", "verify_s", "witness_bytes", "vm_proof_bytes", "chain_eq", "chain_diff"}. "proven" means the
    verifier accepted AND its root is the exec node's; anything else names why. Never raises on a span (an internal error
    is "error").
    `l1_inputs` (G8): L1's own chain inputs for the span (ops/settle_chain.l1_inputs_doc, served by /settle_chain_inputs).
    With it, "chain_eq" says whether the Chain L1 derives from its state equals reference_chain (the exec node's own
    bookkeeping) for every read a call in the span could make, the carry and the accruals ("chain_diff": where not) —
    so the shadow weeks prove the derivation the settle branch verifies with, not only the prover. None: not checked."""
    import time
    rec = {"from": int(pre_state.cursor), "to": int(blocks[-1]["block_number"]) if blocks else int(pre_state.cursor),
           "blocks": len(blocks), "calls": None, "reverts": None, "steps": None, "result": None, "reason": "",
           "prove_s": None, "verify_s": None, "witness_bytes": None, "vm_proof_bytes": None,
           "chain_eq": None, "chain_diff": None}
    try:
        chain = reference_chain(pre_state, blocks, accrual)
        if l1_inputs is not None:
            from ops import settle_chain as SC
            try:
                diff = SC.compare_with_reference(chain, SC.chain_from_doc(l1_inputs), blocks)
            except SC.SpanRefused as e:
                diff = [f"L1 refuses the span's chain inputs: {e}"]
            rec.update(chain_eq=not diff, chain_diff=diff[:10] or None)
        t = time.time()
        try:
            bundle = prove_span(pre_state, blocks, chain, binary)
        except Unprovable as e:
            rec.update(result="unprovable", reason=str(e), prove_s=round(time.time() - t, 2))
            return rec
        rec["prove_s"] = round(time.time() - t, 2)
        runs = bundle["runs"]
        rec.update(calls=len(runs), reverts=sum(1 for r in runs if not r["ok"]), steps=sum(r["n_steps"] for r in runs),
                   witness_bytes=len(json.dumps({k: v for k, v in bundle.items() if k != "vm_proof"})),
                   vm_proof_bytes=len(bundle["vm_proof"]) // 2 if bundle.get("vm_proof") else 0)
        t = time.time()
        ok, why, post = verify_span(int(pre_state.cursor), pre_state.state_root(), blocks, chain, bundle, binary)
        rec["verify_s"] = round(time.time() - t, 3)
        if not ok:
            rec.update(result="refused", reason=why)
        elif post != want_root:
            rec.update(result="mismatch", reason=f"verified root {post[:16]}... is not the exec node's {str(want_root)[:16]}...")
        else:
            rec["result"] = "proven"
        return rec
    except (Exception, Refused) as e:            # a bug here must not stop the shadow run; it is reported, loudly
        rec.update(result="error", reason=f"{type(e).__name__}: {e}")
        return rec
