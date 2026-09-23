"""
Bind a state-transition proof to the EPOCH's writes (state-root binding, doc/zk-recursion.md §5b piece (b)).

state_transition.py proves that a set of (key, old, new) updates turns pre_root into post_root. On its own that
could be ANY set of updates; this binds them to the epoch's ACTUAL storage writes so the transition provably IS
the epoch's transition. The epoch's public io log (SLOAD/SSTORE per call — execnode/zkvm.replay_io) determines
the NET change of every touched (cid, slot): its old value (the pre-state) and its final value (last write).
`net_updates` derives exactly that ordered set; `bind_and_verify` requires the transition to prove that set and
nothing else, then verifies it. The io itself is proven correct by the epoch STARK, so binding the transition to
the io binds it to a real execution.

This is the VERIFIER-side binding (native, O(#io) — the cost of reading the calldata, which L1 pays anyway); an
in-circuit LogUp that folds the derivation into the proof (so verify is O(1)) is the succinctness step on top.
Key(cid, slot) maps a contract slot to a sparse-tree position deterministically.
"""
from execnode.stark import field as F, alghash2 as A2
from hashing import blake2b_hash

DOM_KVPOS = 7                                    # alghash2 domain tag for slot positions (disjoint from 1..6)
DOM_KVCODE = 9                                    # alghash2 domain tag for a contract's CODE-commitment position
                                                 # (disjoint from DOM_KVPOS=7 and the records tree's DOM_REC=8, so
                                                 # a code leaf can never share a position with a storage slot)


def cid_limbs(cid):
    """A contract id as 5×52-bit field limbs — the alghash2-friendly encoding of its 256-bit id. FIVE limbs so
    the sponge input [DOM_KVPOS, limbs…, slot] is 7 elements = ONE alghash2 chunk (RATE 8), which lets the
    in-circuit derivation be a SINGLE permutation. Deterministic; a hex cid decodes directly, anything else is
    blake2b-folded first so any id maps into the field cleanly."""
    try:
        n = int(str(cid), 16)
    except ValueError:
        n = int(blake2b_hash(["cid", str(cid)]), 16)
    return [(n >> (52 * i)) & ((1 << 52) - 1) for i in range(5)]      # 5·52 = 260 ≥ 256 bits, each < p


def elements(cid, slot):
    """The alghash2 sponge inputs for (cid, slot) — one chunk (7 elements)."""
    return [DOM_KVPOS, *cid_limbs(cid), int(slot) % F.P]


def slot_key(cid, slot, depth):
    """Deterministic sparse-tree position for a contract slot, via ALGHASH2 (128-bit, arithmetization-friendly):
    key = the digest of hashn([DOM_KVPOS, cid limbs…, slot]) (4 lanes packed big-endian) truncated to `depth`
    bits, so the (cid, slot) → position map is provable IN-CIRCUIT (slot_key_air, one permutation). A real
    deployment uses depth ~ 256 so distinct (cid, slot) never share a leaf."""
    d = A2.hashn(elements(cid, slot))            # CAPACITY-tuple (128-bit)
    acc = 0
    for lane in d:
        acc = (acc << 64) | int(lane)
    return acc & ((1 << depth) - 1)


def code_elements(cid):
    """The alghash2 sponge inputs for a contract's CODE-commitment position — one chunk (6 elements: the
    domain tag + the 5 cid limbs). Distinct domain tag from `elements`, so a code position and a slot position
    for the same cid never coincide."""
    return [DOM_KVCODE, *cid_limbs(cid)]


def code_key(cid, depth):
    """Deterministic sparse-tree position for a contract's CODE commitment, the KV-half analogue of slot_key.
    Same construction (alghash2 hashn digest truncated to `depth` bits) under a separate domain tag."""
    d = A2.hashn(code_elements(cid))
    acc = 0
    for lane in d:
        acc = (acc << 64) | int(lane)
    return acc & ((1 << depth) - 1)


DOM_KVMETA = 10                                  # alghash2 domain tag for a contract's META-commitment position
                                                 # (deployer, lock flag, runtime) — EXEC_ROOT_V2_HEIGHT (S1/C5);
                                                 # disjoint from DOM_KVPOS=7, DOM_REC=8 and DOM_KVCODE=9

EVENT_OPS = ("deploy", "upgrade", "lock", "transfer_contract")   # the blob ops that change code or meta leaves


def root_v2(height):
    """Whether the exec root, the DA leaves and the settlement binding at `height` use the EXEC_ROOT_V2 layout.
    A pure function of the height so a replay lands on the same root. Read through the module attribute so a
    test can move the gate; the live value never moves (tests/test_gate_reroll_transfer.py)."""
    import protocol
    return int(height) >= int(protocol.EXEC_ROOT_V2_HEIGHT)


def meta_key(cid, depth):
    """Sparse-tree position of a contract's META commitment: the same construction as code_key under its own
    domain tag, so it can never coincide with a slot or code leaf of any contract."""
    d = A2.hashn([DOM_KVMETA, *cid_limbs(cid)])
    acc = 0
    for lane in d:
        acc = (acc << 64) | int(lane)
    return acc & ((1 << depth) - 1)


def meta_commitment(deployer, upgradable, runtime):
    """A NONZERO field element committing to who may upgrade a contract, whether anyone still may, and which
    runtime runs it — the three facts an in-span upgrade's admission depends on and that bootstrap used to
    adopt from any peer (C5). Canonical bytes, so every node commits the same element; forced into [1, P)
    like code_commitment because 0 means ABSENT in the sparse tree."""
    n = int(blake2b_hash(["meta", str(deployer if deployer is not None else ""), 1 if upgradable else 0,
                          str(runtime if runtime is not None else "")]), 16)
    return 1 + (n % (F.P - 1))


def contract_meta(c):
    """(deployer, upgradable, runtime) of a contract record, with the defaults the exec layer applies: a legacy
    record with no flag is upgradable; no runtime is the default runtime."""
    return (c.get("deployer", ""), c.get("upgradable", True) is not False, c.get("runtime", "zkvm"))


def apply_event(contracts, ev):
    """Apply ONE code event (a block_calls entry with op in EVENT_OPS) to `contracts`, in place, under EXACTLY
    the chain's admission rules at EXEC_ROOT_V2_HEIGHT (execnode/state.py: deploy / upgrade / lock /
    transfer_contract; a refused event is a no-op there and here). Returns (admitted, cid, before) where
    `before` is a deep copy of the record as it stood (None for a fresh deploy).

    THE VERIFIER'S ONLY SOURCE OF TRUTH for what a code event did. It runs over events the calls_commitment
    authenticated against the on-chain calldata and a pre-state pinned to the settled root, so nothing the
    prover says enters the derivation. A deploy's constructor is NOT run here: vm_units turns it into a
    proven VM call. Any rule added to the chain's four ops must be added here in the same commit."""
    import copy
    from execnode import runtimes
    from execnode.code_codec import FIXED_CIDS, contract_id
    op, sender = ev.get("op"), ev.get("caller")
    if op == "deploy":
        code = ev.get("code")
        rt_name = ev.get("runtime", runtimes.DEFAULT_RUNTIME)
        if not isinstance(code, dict) or not runtimes.runtime_name_ok(rt_name):
            return False, None, None
        try:
            runtimes.get(rt_name).validate_code(code)
        except Exception:
            return False, None, None                        # the chain's outer except: "skip"
        at = ev.get("at")
        if at is not None:
            if FIXED_CIDS.get(at) != sender:
                return False, None, None
            cid = at
        else:
            cid = contract_id(sender, code, ev.get("nonce"))
        if cid in contracts:
            return False, cid, None
        contracts[cid] = {"code": code, "storage": {"slots": {}}, "deployer": sender, "runtime": rt_name,
                          "upgradable": bool(ev.get("upgradable", True))}
        return True, cid, None
    cid = ev.get("cid")
    c = contracts.get(cid) if isinstance(cid, str) else None
    if not c or c.get("deployer") != sender:
        return False, cid, None
    before = copy.deepcopy(c)
    if op == "upgrade":
        code = ev.get("code")
        if c.get("upgradable", True) is False or not isinstance(code, dict):
            return False, cid, None
        rt_name = ev.get("runtime")
        if rt_name is None:
            rt_name = c.get("runtime", runtimes.DEFAULT_RUNTIME)
        if not runtimes.runtime_name_ok(rt_name):
            return False, cid, None
        try:
            runtimes.get(rt_name).validate_code(code)
        except Exception:
            return False, cid, None
        c["code"] = code
        c["runtime"] = rt_name
        return True, cid, before
    if op == "lock":
        c["upgradable"] = False
        return True, cid, before
    if op == "transfer_contract":
        to = ev.get("to")
        if not isinstance(to, str) or not to:
            return False, cid, None
        c["deployer"] = to
        return True, cid, before
    return False, cid, None


def event_updates(pre_contracts, entries, depth):
    """The code- and meta-leaf updates a span's CODE EVENTS cause, as [(key, old, new), ...] NETTED per leaf
    in first-touch order (a deploy then an upgrade of one cid is one code update 0 -> final), over a deep copy
    of `pre_contracts`. `entries` is the span's ordered block_calls list; calls are ignored. Both the prover
    (prove_bound_epoch) and the verifier (verify_bound_epoch) derive the transition's leading updates from
    this, so the transition proves exactly what the events did and nothing the prover chose."""
    import copy
    contracts = copy.deepcopy(pre_contracts)
    order, first, cur = [], {}, {}

    def _touch(key, old, new):
        if key not in first:
            first[key] = old; order.append(key)
        cur[key] = new

    for ev in entries:
        if ev.get("op") not in EVENT_OPS:
            continue
        admitted, cid, before = apply_event(contracts, ev)
        if not admitted:
            continue
        after = contracts[cid]
        pc = code_commitment(before["code"]) if before else 0
        pm = meta_commitment(*contract_meta(before)) if before else 0
        nc, nm = code_commitment(after["code"]), meta_commitment(*contract_meta(after))
        if pc != nc:
            _touch(code_key(cid, depth), pc, nc)
        if pm != nm:
            _touch(meta_key(cid, depth), pm, nm)
    return [(k, first[k], cur[k]) for k in order if first[k] != cur[k]]


def vm_units(pre_contracts, entries, cursor=0, timestamp=0):
    """The VM executions a span's ordered entries stand for, as [(cid, pub_call), ...] with `pub_call` in the
    form _epoch_pub_statement hands the AIR (code, method, caller, args, value, cursor, timestamp, asset,
    selfd), walking the code events over a deep copy of `pre_contracts` as it goes — so a call after an
    in-span upgrade is judged against the code the upgrade left, and an admitted deploy whose code has a
    `constructor` contributes one unit (caller = the deployer, no args, no value; the chain runs it exactly
    so). A refused event, or a deploy without a constructor, contributes none. Raises ValueError on a call
    to an unknown or non-zkvm contract, as the pub statement always did."""
    import copy
    from execnode import runtimes
    contracts = copy.deepcopy(pre_contracts)
    units = []
    for e in entries:
        if e.get("op") in EVENT_OPS:
            admitted, cid, _before = apply_event(contracts, e)
            if admitted and e.get("op") == "deploy" and "constructor" in contracts[cid]["code"]:
                units.append((cid, {"code": contracts[cid]["code"], "method": "constructor",
                                    "caller": e.get("caller"), "args": [], "value": 0,
                                    "cursor": int(e.get("cursor", cursor)), "timestamp": int(e.get("timestamp", timestamp)),
                                    "asset": 0, "selfd": runtimes.zkvm_addr_digest(cid)}))
            continue
        c = contracts.get(e["cid"])
        if not c or c.get("runtime") != "zkvm":
            raise ValueError("unknown contract")
        # `selfd` is DERIVED from the cid, never carried in the bundle: the verifier recomputes the callee's
        # own digest from public data, so a prover cannot choose what ACTX_SELF reads.
        # PER-CALL context (the block the call executed in), falling back to the epoch-wide cursor/ts — must
        # match _run_call's prove-time context, else verify_epoch_calls rebuilds a different statement than was
        # proven. A multi-block span carries a distinct cursor per call (block_calls stamps height).
        units.append((e["cid"], {"code": c["code"], "method": e["method"], "caller": e.get("caller", "epoch"),
                                 "args": e.get("args", []), "value": int(e.get("value", 0)),
                                 "cursor": int(e.get("cursor", cursor)), "timestamp": int(e.get("timestamp", timestamp)),
                                 "asset": int(e.get("asset", 0)), "selfd": runtimes.zkvm_addr_digest(e["cid"])}))
    return units


def code_commitment(code):
    """A NONZERO field element committing to a contract's code map {method: bytecode}. The KV half is a sparse
    tree in which value 0 means ABSENT, so the commitment is forced into [1, P): a code digest that reduced to
    0 mod P must not make the leaf vanish. Deterministic + canonical (sorted method order via canonical_bytes),
    so every node commits the SAME element for the same code — which is exactly what lets the settle proof's
    pre-state pin authenticate the code: fabricated code yields a different leaf and fails the tip extension."""
    from hashing import canonical_bytes
    n = int(blake2b_hash(["code", canonical_bytes(code).hex()]), 16)
    return 1 + (n % (F.P - 1))


def net_updates(pre_get, cid_io, depth):
    """Derive the ordered NET updates an epoch makes to storage, from its io. `pre_get(cid, slot) -> value` is
    the pre-state read; `cid_io` is the epoch's io as [(cid, kind, slot, value), ...] in execution order
    (IO_SLOAD=1 read, IO_SSTORE=2 write, value 0 = delete). Returns [(key, old, new), ...] — one entry per
    (cid, slot) whose FINAL value differs from its pre-state, in first-touch order, with old = pre-state value,
    new = final value, key = slot_key(cid, slot, depth). SLOADs are consistency-checked against the running
    value (as replay_io does), so a lied read is caught here too."""
    order, cur, pre = [], {}, {}
    for (cid, kind, slot, value) in cid_io:
        ck = (str(cid), int(slot))
        if ck not in cur:
            pv = int(pre_get(cid, slot)) % F.P
            cur[ck] = pv; pre[ck] = pv
            order.append(ck)
        if kind == 1:                                    # IO_SLOAD — must match the running value
            if cur[ck] != int(value) % F.P:
                raise ValueError(f"io read of {ck} = {value} contradicts current {cur[ck]}")
        elif kind == 2:                                  # IO_SSTORE — 0 clears the slot
            cur[ck] = int(value) % F.P
        # other io kinds (PAY/BHASH/BEACON/RET) do not touch storage
    updates = []
    for ck in order:
        if cur[ck] != pre[ck]:                           # only slots whose NET value changed are updates
            cid, slot = ck
            updates.append((slot_key(cid, slot, depth), pre[ck], cur[ck]))
    return updates


def bind_and_verify(tr, pre_root, post_root, pre_get, cid_io, depth, num_queries=None, outer_queries=None,
                    lead_updates=()):
    """Verify a state transition AND that its updates are EXACTLY the epoch's net writes. (1) derive the net
    updates from the (proven) io; (2) require tr.updates == that set, in order; (3) verify the transition proves
    pre_root → post_root (state_transition.verify_transition). All three ⇒ the transition is THIS epoch's, not an
    arbitrary one. Returns (ok, reason).

    `lead_updates` (EXEC_ROOT_V2_HEIGHT): the code- and meta-leaf updates the VERIFIER derived from the span's
    bound code events (event_updates), required FIRST in tr.updates, before the storage writes. The verifier
    passes its own derivation; the prover built the transition in the same order (prove_bound_epoch)."""
    from execnode.stark import state_transition as SX
    try:
        want = [(int(k), int(o) % F.P, int(n) % F.P) for (k, o, n) in lead_updates] + net_updates(pre_get, cid_io, depth)
        got = [(int(k), int(o) % F.P, int(n) % F.P) for (k, o, n) in tr.get("updates", [])]
        want = [(int(k), int(o) % F.P, int(n) % F.P) for (k, o, n) in want]
        if got != want:
            return False, f"transition updates do not match the epoch's net writes ({len(got)} vs {len(want)})"
        return SX.verify_transition(tr, pre_root, post_root, num_queries=num_queries, outer_queries=outer_queries)
    except Exception as e:
        return False, f"binding failed: {e}"
