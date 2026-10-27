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
ONE runtime — "zkvm", the PROVABLE VM (execnode/zkvm2.py, the 256-bit word; doc/stwo/g3-vm-word.md). The old
string/BLAKE2b stack VM was DELETED at the betanet-5 reboot: no legacy runtime, no history to replay. The
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


def runtime_name_ok(name):
    """EXEC_ROOT_V2_HEIGHT: a deploy/upgrade names its runtime EXACTLY — a registered name, as a string.
    `get()` maps a falsy name to the default and a non-string to None, which let "" deploy as the default
    runtime while the record stored "" (a contract the settlement prover then refused as non-zkvm). The
    chain (state.py) judges by this."""
    return isinstance(name, str) and name in _REGISTRY


ADDR_PERSON_V2 = b"NADOvmA1"      # the gen-29 address digest's BLAKE2s personalization (disjoint from the VM hash's)


# ONE DIGEST FORMAT (G9 slice 3b): the gen-28 field digest (blake2b mod the Goldilocks prime) and the `v2=` switch that
# chose it were deleted with the field VM. BLAKE_EXEC_HEIGHT (gen 28's gate) was 1 from gen 29 and covered the genesis, so
# every digest generation 29 ever computed is the 256-bit BLAKE2s one below, at every height.
def zkvm_addr_digest(addr):
    """Deterministic digest of an L1 address string — how addresses enter the zkVM: the full 256-bit BLAKE2s digest (an
    owner digest of >= 128 bits is what doc/stwo-migration.md 9.2 requires). Computed at the CALL BOUNDARY (never
    in-circuit): the digest is part of the public statement, and the digest->address registry (ExecState.zk_addrs)
    resolves payouts back to L1 addresses."""
    import hashlib
    from hashing import canonical_bytes
    return int.from_bytes(hashlib.blake2s(canonical_bytes(["zkvmaddr", addr]), digest_size=32,
                                          person=ADDR_PERSON_V2).digest(), "big")


def zkvm_statement(caller, args, registry=None):
    """Digest a (caller, args) statement into zkVM form, registering every address digest seen. Returns
    (caller_digest, args) or raises ValueError on a non-encodable arg (an int outside the 256-bit word). Shared by the
    runtime adapter and the settlement prover so the statement is byte-identical everywhere."""
    bound = 1 << 256
    reg = registry if registry is not None else {}
    cf = zkvm_addr_digest(caller)
    reg[str(cf)] = caller
    out = []
    for a in args:
        if isinstance(a, bool) or not isinstance(a, (int, str)):
            raise ValueError("zkvm args must be ints or address strings")
        if isinstance(a, int):
            if not (0 <= a < bound):
                raise ValueError("zkvm int arg out of field")
            out.append(a)
        else:
            d = zkvm_addr_digest(a)
            reg[str(d)] = a
            out.append(d)
    return cf, out


def split_io(io, reg):
    """Split a VM io log into (native `payouts`, asset `effects`), enforcing the ASEL pairing and resolving
    recipients through the digest→address registry `reg`. Returns `(payouts, effects)` or `None` on any
    pairing/resolution failure (a deterministic revert): a stray selection, an unresolvable BARE payee, an
    AMINT with no live selection, or a trailing selection.

    This is the ONE reader of a log's meaning, shared by the interpreter (`_ZkVM.run`) and the epoch prover's
    shadow (`settlement_proofs._run_call`), so the two can never disagree about what an io log settles.
    `payouts` are (address, amount) for native NADO; `effects` are ("pay"|"mint"|"burn"|"bal", asset_id,
    recipient_or_None, amount) staged against the asset ledger by stage_asset_effects_pure. An unresolvable
    ASSET recipient is left as None here and rejected by that staging (uniform with the native rule)."""
    from execnode import zkvm2                             # imported per-call like elsewhere in this module
    payouts, effects, sel = [], [], 0
    for kind, a, b in io:
        if sel and kind not in (zkvm2.IO_PAY, zkvm2.IO_AMINT):
            return None
        if kind == zkvm2.IO_ASEL:
            if a == 0:
                return None
            sel = a
        elif kind == zkvm2.IO_PAY:
            if sel:
                effects.append(("pay", str(sel), reg.get(str(a)), b))
                sel = 0
            elif b > 0:
                addr = reg.get(str(a))
                if addr is None:
                    return None                           # unresolvable payee -> deterministic revert
                payouts.append((addr, b))
        elif kind == zkvm2.IO_AMINT:
            if not sel:
                return None
            effects.append(("mint", str(sel), reg.get(str(a)), b))
            sel = 0
        elif kind == zkvm2.IO_ABURN:
            effects.append(("burn", str(a), None, b))
        elif kind == zkvm2.IO_ABAL:
            effects.append(("bal", str(a), None, b))
        elif kind == zkvm2.IO_ARENOUNCE:
            effects.append(("renounce", str(a), None, 0))   # seal the asset's mintability (issuer-checked)
    if sel:
        return None
    return payouts, effects


class _ZkVM:
    """The PROVABLE runtime: execnode/zkvm2.py behind the same interface.
    Storage is {"slots": {str(slot): value}} (flat field map — canonical in state_root leaves like any
    map). String args and the caller enter as field digests; PAY digests resolve back to L1 addresses
    through the registry, and an unresolvable payee reverts the call (deterministic on every node).
    Calls run natively here for liveness — the SAME semantics are what execnode/stark/vm_circuit.py
    proves, so a proven call and a replayed call can never disagree."""
    name = "zkvm"
    wants_registry = True         # state.py passes its persistent digest→address registry to run()

    def validate_code(self, code):
        """the zkvm2 deploy gate (the field VM's gate went with it in G9 slice 3b; the exec state passed v2 at every
        cursor since BLAKE_EXEC_HEIGHT was inlined)"""
        from execnode import zkvm2
        return zkvm2.validate_code(code)

    def run(self, code, method, caller, args, storage, value=0, cursor=0, timestamp=0, beacons=None,
            block_hashes=None, registry=None, asset=0, selfd=0, abal=None, meter=None, trace=None):
        """`trace` (a list; the gen-29 settlement prover, execnode/settle_b2.py): every zkvm2 run that executed at least
        one step appends {"ok", "io", "n_steps", "revert"} in call order — the witness the prover's replay consumes; a
        reverted run's io is the log up to its revert and `revert` its kind (zkvm2.REVERT_KINDS). None: nothing."""
        from execnode import zkvm2
        # THE VM IS zkvm2 AT EVERY CURSOR (BLAKE_EXEC_HEIGHT, gen 28's gate, 1 from gen 29, inlined in G9): 256-bit
        # digests and unreduced chain reads, the same format as the BLAKE2s exec root, so a contract's VM and its
        # root's format never disagree. (The old field VM, execnode/zkvm.py, was deleted in G9 slice 3b.)
        reg = registry if registry is not None else {}
        try:
            cf, fargs = zkvm_statement(caller, args, reg)
        except ValueError:
            return (False, None, storage, [], [])
        slots = {int(k): int(v) for k, v in (storage.get("slots") or {}).items()}
        m = meter if meter is not None else ({} if trace is not None else None)
        ok, ret, new_slots, io = zkvm2.run(code, method, cf, fargs, slots, value=value, cursor=cursor,
                                          timestamp=timestamp, beacons=dict(beacons or {}),
                                          block_hashes=dict(block_hashes or {}),
                                          asset=asset, selfd=selfd, abal=abal, meter=m)
        if trace is not None and "gas" in m:
            rv = m.get("revert") if not ok else None
            trace.append({"ok": bool(ok), "io": [tuple(e) for e in (rv["io"] if rv else io)], "n_steps": int(m["gas"]),
                          "revert": rv["kind"] if rv else None})
        if not ok:
            return (False, None, storage, [], [])
        # ASSET EFFECTS ride the SAME digest→address registry as payouts and revert on the same rule (see
        # split_io). The epoch prover's shadow (settlement_proofs._run_call) calls the identical split_io,
        # so the interpreter and the proof path can never disagree on what a log MEANS.
        split = split_io(io, reg)
        if split is None:
            return (False, None, storage, [], [])
        payouts, effects = split
        new_storage = {"slots": {str(k): v for k, v in sorted(new_slots.items())}}
        return (True, ret, new_storage, payouts, effects)


register(_ZkVM())
