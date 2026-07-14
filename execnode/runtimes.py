"""
Pluggable contract-runtime registry for the execution node.

A RUNTIME is any object exposing:
    name                                              -> str
    validate_code(code)                               -> True | raises (rejected at deploy)
    run(code, method, caller, args, storage)          -> (ok: bool, return_value, new_storage: dict)

The exec node's execution engine is SWAPPABLE without touching state.py or L1 consensus: a contract records
which runtime it was deployed under, and every call/view dispatches back to that runtime. The default
runtime "stackvm" wraps execnode/vm.py. To add another engine (a WASM VM, an EVM, a domain-specific DSL,
or a STARK-proved runtime later), implement the interface above and register() it; deployers select it with
{"op":"deploy","runtime":"<name>", ...}. Determinism is the only hard requirement — every exec node must
compute byte-identical new_storage from the same inputs, or the layer can't settle.
"""

DEFAULT_RUNTIME = "stackvm"

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


class _StackVM:
    """The default runtime: NADO's minimal deterministic stack VM (execnode/vm.py)."""
    name = "stackvm"

    def validate_code(self, code):
        from execnode import vm
        return vm.validate_code(code)

    def run(self, code, method, caller, args, storage, value=0, cursor=0, timestamp=0, beacons=None, block_hashes=None):
        from execnode import vm
        return vm.run(code, method, caller, args, storage, value=value, cursor=cursor, timestamp=timestamp, beacons=beacons, block_hashes=block_hashes)


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
            block_hashes=None, registry=None):
        from execnode import zkvm
        from execnode.stark.field import P
        reg = registry if registry is not None else {}
        try:
            cf, fargs = zkvm_statement(caller, args, reg)
        except ValueError:
            return (False, None, storage, [])
        slots = {int(k): int(v) for k, v in (storage.get("slots") or {}).items()}
        ok, ret, new_slots, io = zkvm.run(code, method, cf, fargs, slots, value=value, cursor=cursor,
                                         timestamp=timestamp,
                                         beacons={e: v % P for e, v in (beacons or {}).items()},
                                         block_hashes={h: v % P for h, v in (block_hashes or {}).items()})
        if not ok:
            return (False, None, storage, [])
        payouts = []
        for kind, a, b in io:
            if kind == zkvm.IO_PAY and b > 0:
                addr = reg.get(str(a))
                if addr is None:
                    return (False, None, storage, [])     # unresolvable payee -> deterministic revert
                payouts.append((addr, b))
        new_storage = {"slots": {str(k): v for k, v in sorted(new_slots.items())}}
        return (True, ret, new_storage, payouts)


register(_StackVM())
register(_ZkVM())
