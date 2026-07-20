"""
Pluggable contract-runtime registry for the execution node.

A RUNTIME is any object exposing:
    name                                              -> str
    validate_code(code)                               -> True | raises (rejected at deploy)
    run(code, method, caller, args, storage)          -> (ok, return_value, new_storage, payouts, effects)

`payouts` are native-NADO moves [(addr, amount)]; `effects` are asset-ledger intents
[(kind, asset_id, addr_or_None, amount)] for kind in pay/mint/burn/bal (doc/assets.md). The runtime only
NAMES them — solvency, issuer authority and the supply cap are the exec layer's to enforce, in
ExecState.stage_asset_effects, so one rule covers native execution and proof replay alike.

`effects` is OPTIONAL: a runtime that predates assets, or simply does not implement them, may return the
4-tuple `(ok, ret, new_storage, payouts)` and the exec layer reads that as "no asset effects"
(ExecState._rt_run). This seam exists so another engine can plug in; silently requiring every
implementation to grow a return value the day the built-in VM does would defeat the point.

The exec node's execution engine is SWAPPABLE without touching state.py or L1 consensus: a contract records
which runtime it was deployed under, and every call/view dispatches back to that runtime. NADO ships exactly
ONE runtime — "zkvm", the field-native PROVABLE VM (execnode/zkvm.py, doc/zk-execution-proofs.md). The old
string/BLAKE2b stack VM was DELETED at the alphanet-5 reboot: no legacy runtime, no history to replay. The
registry stays because it is the clean seam for a future engine, but any deploy without an explicit runtime
gets zkvm. Determinism is the only hard requirement — every exec node must compute byte-identical
new_storage from the same inputs, or the layer can't settle.
"""

DEFAULT_RUNTIME = "zkvm"

_REGISTRY = {}


def register(runtime):
    """Register a runtime under runtime.name (idempotent; re-register replaces)."""
    _REGISTRY[runtime.name] = runtime


def get(name):
    """The runtime registered under `name` (or the default when name is falsy); None if unknown."""
    return _REGISTRY.get(name or DEFAULT_RUNTIME)


def names():
    """All registered runtime names, sorted."""
    return sorted(_REGISTRY)


def zkvm_addr_digest(addr):
    """Deterministic field digest of an L1 address string — how addresses enter the field-native zkVM.
    Computed at the CALL BOUNDARY (never in-circuit): the digest is part of the public statement, so any
    hash works; the digest→address registry (ExecState.zk_addrs) resolves payouts back to L1 addresses."""
    from hashing import blake2b_hash
    from execnode.stark.field import P
    return int(blake2b_hash(["zkvmaddr", addr]), 16) % P


def zkvm_statement(caller, args, registry=None):
    """Digest a (caller, args) statement into zkVM field form, registering every address digest seen.
    Returns (caller_field, field_args) or raises ValueError on a non-encodable arg. Shared by the runtime
    adapter and the prove/verify endpoints so the statement is byte-identical everywhere."""
    from execnode.stark.field import P
    reg = registry if registry is not None else {}
    cf = zkvm_addr_digest(caller)
    reg[str(cf)] = caller
    out = []
    for a in args:
        if isinstance(a, bool) or not isinstance(a, (int, str)):
            raise ValueError("zkvm args must be ints or address strings")
        if isinstance(a, int):
            if not (0 <= a < P):
                raise ValueError("zkvm int arg out of field")
            out.append(a)
        else:
            d = zkvm_addr_digest(a)
            reg[str(d)] = a
            out.append(d)
    return cf, out


class _ZkVM:
    """The PROVABLE runtime (doc/zk-execution-proofs.md): execnode/zkvm.py behind the same interface.
    Storage is {"slots": {str(slot): value}} (flat field map — canonical in state_root leaves like any
    map). String args and the caller enter as field digests; PAY digests resolve back to L1 addresses
    through the registry, and an unresolvable payee reverts the call (deterministic on every node).
    Calls run natively here for liveness — the SAME semantics are what execnode/stark/vm_circuit.py
    proves, so a proven call and a replayed call can never disagree."""
    name = "zkvm"
    wants_registry = True         # state.py passes its persistent digest→address registry to run()

    def validate_code(self, code):
        from execnode import zkvm
        return zkvm.validate_code(code)

    def run(self, code, method, caller, args, storage, value=0, cursor=0, timestamp=0, beacons=None,
            block_hashes=None, registry=None, asset=0, selfd=0, abal=None):
        from execnode import zkvm
        from execnode.stark.field import P
        reg = registry if registry is not None else {}
        try:
            cf, fargs = zkvm_statement(caller, args, reg)
        except ValueError:
            return (False, None, storage, [], [])
        slots = {int(k): int(v) for k, v in (storage.get("slots") or {}).items()}
        ok, ret, new_slots, io = zkvm.run(code, method, cf, fargs, slots, value=value, cursor=cursor,
                                         timestamp=timestamp,
                                         beacons={e: v % P for e, v in (beacons or {}).items()},
                                         block_hashes={h: v % P for h, v in (block_hashes or {}).items()},
                                         asset=asset, selfd=selfd, abal=abal)
        if not ok:
            return (False, None, storage, [], [])
        # ASSET EFFECTS ride the SAME digest→address registry as payouts, and revert on the same rule: a
        # recipient the layer cannot name is not a recipient. The pairing (an ASEL binding the entry after
        # it) is re-derived here rather than trusted, because this loop is also what a foreign io log would
        # go through — see zkvm.replay_io, which enforces the identical rule for the verifying path.
        payouts, effects, sel = [], [], 0
        for kind, a, b in io:
            if sel and kind not in (zkvm.IO_PAY, zkvm.IO_AMINT):
                return (False, None, storage, [], [])
            if kind == zkvm.IO_ASEL:
                if a == 0:
                    return (False, None, storage, [], [])
                sel = a
            elif kind == zkvm.IO_PAY:
                if sel:
                    to = reg.get(str(a))
                    effects.append(("pay", str(sel), to, b))
                    sel = 0
                elif b > 0:
                    addr = reg.get(str(a))
                    if addr is None:
                        return (False, None, storage, [], [])   # unresolvable payee -> deterministic revert
                    payouts.append((addr, b))
            elif kind == zkvm.IO_AMINT:
                if not sel:
                    return (False, None, storage, [], [])
                effects.append(("mint", str(sel), reg.get(str(a)), b))
                sel = 0
            elif kind == zkvm.IO_ABURN:
                effects.append(("burn", str(a), None, b))
            elif kind == zkvm.IO_ABAL:
                effects.append(("bal", str(a), None, b))
        if sel:
            return (False, None, storage, [], [])
        new_storage = {"slots": {str(k): v for k, v in sorted(new_slots.items())}}
        return (True, ret, new_storage, payouts, effects)


register(_ZkVM())
