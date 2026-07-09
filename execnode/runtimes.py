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

    def run(self, code, method, caller, args, storage, value=0, cursor=0, beacons=None):
        from execnode import vm
        return vm.run(code, method, caller, args, storage, value=value, cursor=cursor, beacons=beacons)


register(_StackVM())
