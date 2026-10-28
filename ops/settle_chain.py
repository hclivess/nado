"""THE CHAIN INPUTS OF A STWO SPAN SETTLEMENT, FROM L1'S OWN STATE (G8, doc/stwo/g4-settlement-statement.md section 5).

execnode/settle_b2.verify_span replays a span on a witness, and three things in that replay are not the prover's to
supply: the dividend accrual inputs and what a contract call in block h may read through BHASH and BEACON. (The dividend
carry at the span's start was a third, read from exec summaries; from protocol.EXEC_CARRY_ROOT_HEIGHT it is a record of
the span's pre root instead — THE CARRY below.) settle_b2.reference_chain answers them from a replay of the exec node's own bookkeeping
(ExecState.advance_beacons / record_block_hash / accrue_dividend_epoch); this module answers them from L1 state, and the
two must be EQUAL for every span and every (kind, key, height) a call could read — a difference is a root L1 refuses that
every exec node holds, or worse, accepts one none holds. tests/test_l1_derives_the_settlement_chain_inputs_the_exec_node_reads.py
pins the equality on a real exec replay; tools/settle_b2_shadow.py checks it on every live span it proves.

The rules, each the closed form of the exec node's bookkeeping for a FROM-GENESIS node (execnode/state.py; the gen-29
exec node applies block 0 from cursor -1, so its rings start there):

  BHASH, key k, read by a call in block h: block_apply.close(k) records k's hash after block k, and the ring keeps the
    newest _BLOCKHASH_RING ENTRIES (a count, pruned oldest-first), so when block h opens the ring holds exactly
    max(0, h - _BLOCKHASH_RING) <= k <= h - 1. The value is int(L1 block hash at k, 16).
  BEACON, epoch e, read by a call in block h: when block h opens the exec node has run advance_beacons(h - 1), with
    F = (h - 1) // EPOCH_LENGTH its final epoch. beacon_floor is 2 (advance_beacons(0) from genesis: cur_epoch 0 + 2),
    the cache is a GAP-FREE prefix (the loop resumes at the first missing epoch and stops at the first one not final at
    F), and epochs below F - _BEACON_RETENTION_EPOCHS are pruned once that is positive. So e is readable iff
    lo <= e <= F (lo = max(2, F - _BEACON_RETENTION_EPOCHS) when that is positive, else 2) and every epoch in [lo, e] is
    final at F under ExecState.exec_beacon_at. An epoch x <= F - BEACON_EXTEND_MAX is always final (the extension search
    ends inside F), so only [max(lo, F - BEACON_EXTEND_MAX + 1), e] needs checking: O(BEACON_EXTEND_MAX) per read, never
    a scan of the chain. The value is ExecState.exec_beacon_at(e, kv_ops.reveals_for_epoch, F). Reveals for epoch x land
    only in epoch x - 1's window (transaction_ops._validate_reveal_fields), so for x <= F every one of them is in a
    block before block h and L1's set equals the exec node's (both record every reveal and duty-carried reveal a block
    holds, deduplicated per epoch).
  ACCRUAL of epoch E: (kv_ops.dividend_inflow_get(E), the weights) where the weights are what /get_open_weights?epoch=E
    serves the exec node: the COMMITTED row kv_ops.epoch_weights_get(E) when there is one, else
    dividend_ops.weights_at_epoch(E) — refused when idle-GC has pruned the recert rows it replays (the endpoint answers
    410 there and the exec node holds its cursor).
  THE CARRY at the span's start cursor sc is NOT an L1 input. From protocol.EXEC_CARRY_ROOT_HEIGHT the exec root commits
    ExecState.div_carry (exec_root_b2.CARRY_COUNTER), so settle_b2 opens it against the span's pre root; Chain.div_carry
    is None. A span starting below the gate is REFUSED (l1_chain: SpanRefused), a pure function of sc. Until 2026-10-28
    L1 read it from the `dc` of the boundary block's exec summary, which loops/core_loop._accrual_effects chains from the
    previous boundary's `dc` and writes only when the boundary block's records are derivable. MEASURED on betanet-10:
    boundary 10860 carried a collect_dividend, wrote no `dc`, and every later boundary found no carry-in (silently: that
    early return logs nothing), so from 10860 on no span could have been verified — and the summaries below the
    retention window (EXEC_SUMMARY_RETENTION) are pruned anyway, which is why a probe of 60..11040 also found none.
    INVARIANT: L1 never derives the carry from per-block bookkeeping again; one non-derivable block ended it for good.

FAILURE CLASSES, and why they differ:
  * SpanRefused (an AssertionError): the answer is a pure function of COMMITTED state, identical on every node — refusing
    is a verdict every node reaches.
  * ChainUnavailable (a BaseException): THIS node lacks something another may hold (a pruned or re-anchored block body,
    an unindexed block hash). The settle branch turns it into ProofUnavailable (defer, never reject). A BaseException on
    purpose: it is raised inside the replay, where block_apply.dispatch's per-tx `except Exception` would otherwise turn
    "this node lacks a block hash" into "the call was skipped", a different root, and a rejection that forks the fleet
    along the axis of who pruned what (the settle_b2.Unprovable rule, for the same reason).

Pure functions over injected getters (the tests drive them with a real exec replay's data); l1_chain() wires them to
kv_ops. Nothing here writes, and nothing here reads a wall clock or the network.
"""
from protocol import BEACON_EXTEND_MAX, EPOCH_LENGTH

MASK = (1 << 256) - 1


class SpanRefused(AssertionError):
    """A committed chain input the span needs does not exist: every node refuses identically."""


class ChainUnavailable(BaseException):
    """This node does not hold an input another node may hold: defer the judgement (ProofUnavailable), never reject."""


def _retention():
    # the exec node's own constants, read where they are defined so the two can never drift (state.py keeps the prune and
    # window_canonical on these same names for the same reason)
    from execnode import state as _S
    return int(_S._BLOCKHASH_RING), int(_S._BEACON_RETENTION_EPOCHS), int(_S._GENESIS_BEACON_FLOOR)


def bhash_window(h):
    """(lo, hi) inclusive: the L1 heights whose hash a call in block h may read (lo > hi: none)."""
    ring, _r, _f = _retention()
    h = int(h)
    return max(0, h - ring), h - 1


def bhash_read(key, h, hash_at):
    """The BHASH value a call in block h reads for L1 height `key`, or None (the VM reverts). `hash_at(k)` -> hex hash of
    L1 block k, or None when this node has none (ChainUnavailable: the window says the exec node holds it)."""
    lo, hi = bhash_window(h)
    k = int(key)
    if not lo <= k <= hi:
        return None
    hx = hash_at(k)
    if not isinstance(hx, str) or not hx:
        raise ChainUnavailable(f"the L1 block hash at {k} (a BHASH read in block {h}) is not indexed on this node")
    return int(hx, 16) & MASK


def beacon_read(epoch, h, reveals_of):
    """The BEACON value a call in block h reads for `epoch`, or None (not readable there: the VM reverts).
    `reveals_of(e)` -> the revealed secrets of epoch e (any iterable; order is irrelevant to the beacon)."""
    from execnode.state import ExecState
    _ring, retention, floor = _retention()
    h, e = int(h), int(epoch)
    if h < 1:
        return None                     # block 0 opens before any advance_beacons: nothing cached
    F = (h - 1) // EPOCH_LENGTH
    keep = F - retention
    lo = max(floor, keep) if keep > 0 else floor
    if e < lo or e > F:
        return None
    memo = {}

    def at(x):
        if x not in memo:
            memo[x] = ExecState.exec_beacon_at(x, reveals_of, F)
        return memo[x]
    # GAP-FREE: the cache stops at the first epoch not final at F; below F - BEACON_EXTEND_MAX + 1 every epoch is final
    for x in range(max(lo, F - BEACON_EXTEND_MAX + 1), e + 1):
        if at(x) is None:
            return None
    v = at(e)
    return None if v is None else int(v) & MASK


def carry_refusal(sc):
    """None when a span starting after cursor `sc` can be judged (its pre root commits the dividend carry), else why L1
    refuses it: below protocol.EXEC_CARRY_ROOT_HEIGHT L1 holds no carry to replay the span with (THE CARRY above)."""
    from execnode import exec_root_b2 as B2
    if B2.carry_root_at(int(sc)):
        return None
    return (f"the span starts at cursor {int(sc)}, below EXEC_CARRY_ROOT_HEIGHT: its pre root does not commit the dividend "
            f"carry, and L1 derives no carry of its own")


def chain_for_span(sc, *, inflow_of, weights_of, reveals_of, hash_at):
    """settle_b2.Chain for a span starting after cursor `sc`, from the injected L1 getters."""
    from execnode.settle_b2 import Chain
    acc, rv = {}, {}

    def accrual(E):
        E = int(E)
        if E not in acc:
            w = weights_of(E)
            if not isinstance(w, dict):
                raise SpanRefused(f"no dividend weights for epoch {E}")
            acc[E] = (int(inflow_of(E) or 0), dict(w))
        inflow, w = acc[E]
        return inflow, dict(w)

    def reveals(e):
        if e not in rv:
            rv[e] = tuple(reveals_of(e) or ())
        return rv[e]

    def read(kind, key, h):
        from execnode import zkvm2
        if kind == zkvm2.IO_BHASH:
            return bhash_read(key, h, hash_at)
        if kind == zkvm2.IO_BEACON:
            return beacon_read(key, h, reveals)
        return None
    # div_carry None: the carry is the span's pre-root record (settle_b2.WitnessState.div_carry), never an L1 input
    return Chain(accrual, None, read)


def l1_weights_at(E):
    """The weights /get_open_weights?epoch=E serves the exec node (nado.get_open_weights): the committed row first, else
    the reconstruction — refused where the endpoint refuses (recert rows pruned below the reconstruction's floor)."""
    from ops import kv_ops
    committed = kv_ops.epoch_weights_get(int(E))
    if committed is not None:
        return committed
    from protocol import saturation_lookback_at
    if max(0, int(E) - saturation_lookback_at(int(E))) < kv_ops.meta_get_int("gc_rows_below", 0):
        raise SpanRefused(f"epoch {E}'s weights cannot be reconstructed: recert history pruned")
    from ops.dividend_ops import weights_at_epoch
    return weights_at_epoch(int(E))


def l1_chain(sc):
    """settle_b2.Chain for a span after cursor `sc`, from this node's committed L1 state. SpanRefused below
    EXEC_CARRY_ROOT_HEIGHT (carry_refusal): a verdict from sc alone, identical on every node."""
    from ops import kv_ops
    why = carry_refusal(sc)
    if why is not None:
        raise SpanRefused(why)
    return chain_for_span(sc, inflow_of=kv_ops.dividend_inflow_get, weights_of=l1_weights_at,
                          reveals_of=kv_ops.reveals_for_epoch, hash_at=kv_ops.hash_by_number)


def l1_span_blocks(sc, cursor):
    """L1's own blocks sc+1..cursor, in order, from this node's store — never from the transaction. A missing body
    (pruned, or wiped by a snapshot re-anchor) is ChainUnavailable: another node may hold it."""
    from ops.block_ops import get_block_number
    out = []
    for h in range(int(sc) + 1, int(cursor) + 1):
        b = get_block_number(h)
        if not isinstance(b, dict) or "block_transactions" not in b or int(b.get("block_number", -1)) != h:
            raise ChainUnavailable(f"block {h} of the span is not held on this node")
        out.append(b)
    return out


# ---- THE SHADOW CHECK (tools/settle_b2_shadow.py): L1's inputs as a document, and their comparison with the exec node's ----
def l1_inputs_doc(sc, cursor):
    """Everything l1_chain(sc) reads for the span (sc, cursor], as a JSON-able document (served read-only by
    /settle_chain_inputs, so the shadow run can derive the Chain from L1's state without opening L1's database):
    every epoch's reveals a call in the span could read a beacon from, the accrual inputs of every epoch the span accrues,
    and the L1 block hashes of every BHASH window in the span. `refused` is carry_refusal(sc): why l1_chain would refuse
    the span (below EXEC_CARRY_ROOT_HEIGHT), or None. `div_carry` stays in the document, always None (the carry is the
    pre root's record): a shadow tool reading the old field sees "no L1 carry", which is now the truth."""
    from ops import kv_ops
    sc, cursor = int(sc), int(cursor)
    ring, retention, floor = _retention()
    carry, refused = None, carry_refusal(sc)
    f_lo, f_hi = max(0, sc) // EPOCH_LENGTH, max(0, cursor - 1) // EPOCH_LENGTH
    e_lo = max(floor, f_lo - retention)
    accrual = {}
    for E in range(sc // EPOCH_LENGTH, cursor // EPOCH_LENGTH):
        try:
            accrual[str(E)] = [int(kv_ops.dividend_inflow_get(E) or 0), l1_weights_at(E)]
        except SpanRefused as e:
            accrual[str(E)] = {"refused": str(e)}
    lo = max(0, sc + 1 - ring)
    return {"sc": sc, "cursor": cursor, "div_carry": carry, "refused": refused,
            "reveals": {str(e): sorted(kv_ops.reveals_for_epoch(e)) for e in range(e_lo, f_hi + 1)},
            "accrual": accrual, "hash_lo": lo,
            "hashes": [kv_ops.hash_by_number(k) for k in range(lo, cursor)]}


def chain_from_doc(doc):
    """settle_b2.Chain from l1_inputs_doc's document — the same pure functions l1_chain runs, over the served data."""
    hashes, lo = doc["hashes"], int(doc["hash_lo"])

    def weights_of(E):
        a = doc["accrual"].get(str(E))
        if not isinstance(a, list):
            raise SpanRefused((a or {}).get("refused") or f"epoch {E} is outside the served span")
        return a[1]

    def inflow_of(E):
        return doc["accrual"][str(E)][0]
    # NOT refused on doc["refused"] (a span below EXEC_CARRY_ROOT_HEIGHT): the shadow run still compares every read and
    # accrual with the exec node's below the gate; the refusal itself is l1_chain's, keyed on sc alone
    return chain_for_span(int(doc["sc"]), inflow_of=inflow_of, weights_of=weights_of,
                          reveals_of=lambda e: doc["reveals"].get(str(e), ()),
                          hash_at=lambda k: hashes[k - lo] if lo <= k < lo + len(hashes) else None)


def compare_with_reference(ref, l1, blocks):
    """The places where `l1` (an L1-derived Chain) and `ref` (settle_b2.reference_chain, whose `seen` holds the exec
    node's beacons and block hashes as each block opened) disagree over the span `blocks` -> a list of strings, empty when
    they are equal for every (kind, key, height) a call in the span could read and every accrual the span runs. (The carry
    is not compared: it is no L1 input, it is the pre root's record, which the replay authenticates.)
    Beacons: every epoch from -1 to two past the block's final epoch, and every epoch the exec node holds. Block hashes:
    the window's bounds and size at each height, and each held hash's value once (a recorded hash never changes)."""
    from execnode import zkvm2
    out = []

    def r(chain, kind, key, h):
        try:
            return chain.read(kind, key, h)
        except ChainUnavailable as e:
            return f"unavailable: {e}"
    if blocks:
        sc, cur = int(blocks[0]["block_number"]) - 1, int(blocks[-1]["block_number"])
        for E in range(sc // EPOCH_LENGTH, cur // EPOCH_LENGTH):          # the epochs the span accrues
            try:
                if tuple(l1.accrual(E)) != tuple(ref.accrual(E)):
                    out.append(f"accrual of epoch {E}: L1 and exec disagree")
            except SpanRefused as e:
                out.append(f"accrual of epoch {E}: L1 refused ({e})")
    seen_vals = set()
    for b in blocks:
        h = int(b["block_number"])
        bc, bh = ref.seen[h]
        F = (h - 1) // EPOCH_LENGTH if h >= 1 else -1
        for e in sorted(set(range(-1, F + 3)) | set(bc)):
            want = None if bc.get(e) is None else int(bc[e]) & MASK
            got = r(l1, zkvm2.IO_BEACON, e, h)
            if got != want:
                out.append(f"BEACON epoch {e} at block {h}: L1 {got} vs exec {want}")
        lo, hi = bhash_window(h)
        if bh and not (min(bh) == lo and max(bh) == hi and len(bh) == hi - lo + 1):
            out.append(f"BHASH window at block {h}: L1 [{lo}, {hi}] vs exec [{min(bh)}, {max(bh)}] ({len(bh)} held)")
        elif not bh and lo <= hi:
            out.append(f"BHASH window at block {h}: L1 [{lo}, {hi}] vs exec none")
        for k in (lo - 1, hi + 1, h):
            if r(l1, zkvm2.IO_BHASH, k, h) != (None if bh.get(k) is None else int(bh[k]) & MASK):
                out.append(f"BHASH {k} at block {h}: L1 and exec disagree")
        for k, v in bh.items():
            if k not in seen_vals:
                seen_vals.add(k)
                if r(l1, zkvm2.IO_BHASH, k, h) != int(v) & MASK:
                    out.append(f"BHASH {k}: L1's block hash is not the exec node's")
        if len(out) > 50:
            out.append("... (stopped at 50)")
            break
    return out
