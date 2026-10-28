"""L1 DERIVES THE SETTLEMENT CHAIN INPUTS THE EXEC NODE READS (G8; ops/settle_chain.py).

A Stwo settlement is judged with inputs the prover may not supply: what a contract call in block h may read through BHASH
and BEACON, and the dividend accrual inputs. (The dividend carry at the span's start used to be a third, read from exec
summaries; from protocol.EXEC_CARRY_ROOT_HEIGHT it is the pre root's record, pinned to its reroll value 1 here — the
carry's own property is tests/test_a_stwo_settlement_of_a_span_replays_the_exec_transition_and_refuses_forgeries.py.)
The exec node answers them from its own bookkeeping (ExecState.record_block_hash / advance_beacons / accrue_dividend_epoch, which
settle_b2.reference_chain replays); L1 answers them from its own state. A from-genesis exec node and an L1 database are
built from the SAME blocks here, with the exec node's retention windows shrunk (a 100-entry block-hash ring, beacons kept
3 epochs) so the pruning rules run inside 900 blocks, and reveal-less epochs so a beacon waits for later reveals. Then:
  1. for EVERY block h and every key a call could name (all epochs from -1 to two past the final one, every held block
     height and the window's edges), L1's answer equals the exec node's, and so does every epoch's accrual inputs — all
     read through ops/settle_chain.l1_chain, i.e. from kv_ops — and L1 never supplies a carry (Chain.div_carry is None);
  2. the same holds through the shadow run's path: l1_inputs_doc -> chain_from_doc compared by compare_with_reference
     against settle_b2.reference_chain, on every 60-block span, and settle_b2.shadow_span records it as chain_eq; and
     the comparison is not vacuous: it reports a wrong accrual inflow, a dropped reveal and a wrong block hash;
  3. what L1 cannot answer is never a default: a span starting below EXEC_CARRY_ROOT_HEIGHT is REFUSED (SpanRefused, an
     AssertionError every node reaches identically, from the span's start alone — no exec summary is read); a block hash this node lacks is ChainUnavailable, a BaseException that
     passes through block_apply.dispatch's per-tx `except Exception` (so "this node lacks a hash" can never become "the
     call was skipped") and through settle_b2.verify_span.
The live gen-29 chain's version of property 1 (blocks 0..10533 of betanet-10, the real L1 replayed through replay_chain)
is in the G8 commit message; tools/settle_b2_shadow.py's chain_eq keeps checking it on every live span.
Run: python3 tests/test_l1_derives_the_settlement_chain_inputs_the_exec_node_reads.py
"""
import os
import _harness
HOME = _harness.isolate("nado-test-settle-chain-")
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(os.path.join(HOME, "nado", d), exist_ok=True)
import copy

from genesis import create_indexers
create_indexers()

from execnode import block_apply, settle_b2 as S2, state as ST, zkvm2
from execnode.state import ExecState
from ops import kv_ops, settle_chain as SC
from protocol import EPOCH_LENGTH as L

_harness.pinned(EXEC_CARRY_ROOT_HEIGHT=1).__enter__()        # its reroll value: the carry committed from cursor 1
T = _harness.Report()
A = "ndo" + "A" * 45
B = "ndo" + "B" * 45
ST._BLOCKHASH_RING = 100            # the exec node's windows, shrunk so their pruning runs inside the test chain; L1's
ST._BEACON_RETENTION_EPOCHS = 3     # derivation reads the SAME module constants (settle_chain._retention)
N = 25 * L
NO_REVEAL = {4, 5, 9} | set(range(12, 21))             # target epochs nobody reveals for: their beacons wait for a later epoch's reveals


def make_blocks():
    out = []
    for h in range(N + 1):
        txs = []
        if h >= 1 and h % L == 1:
            E = h // L + 1
            if E >= 2 and E not in NO_REVEAL:
                txs.append({"recipient": "duty", "sender": A,
                            "data": {"reveal": {"target_epoch": E, "secret": "d%d" % h}}})
                txs.append({"recipient": "reveal", "sender": B, "data": {"target_epoch": E, "secret": "r%d" % h}})
                txs.append({"recipient": "reveal", "sender": B, "data": {"target_epoch": E, "secret": "r%d" % h}})  # a dup
        out.append({"block_number": h, "block_hash": "%064x" % (0xfeed0000 + 7919 * h), "block_transactions": txs})
    return out


def accrual(E):
    return ({0: 4000, 1: 1001, 3: 777}.get(E, 5 * E), {A: 3, B: 1} if E % 4 else {})


BLOCKS = make_blocks()

# ---- L1's state, written the way L1 writes it: block index, reveals as account_ops applies them, divinflow, committed
#      epoch weights. NO exec summary is written: the carry is not an L1 input any more (ops/settle_chain THE CARRY)
for b in BLOCKS:
    h = b["block_number"]
    kv_ops.block_index_put(h, b["block_hash"])
    for tx in b["block_transactions"]:
        d = tx["data"]
        r = d.get("reveal") if tx["recipient"] == "duty" else d
        kv_ops.reveal_put(r["target_epoch"], r["secret"])
for E in range(N // L):
    inflow, w = accrual(E)
    if inflow:
        kv_ops.dividend_inflow_add(E, inflow)
    kv_ops.epoch_weights_commit(E, w)

# ---- the exec node from genesis, recording what each block could read as it opens
st = ExecState(os.path.join(HOME, "st.json"))
states = {"default": st}
fails, n_reads = [], 0
held_ever = set()
first4 = None
for b in BLOCKS:
    h = b["block_number"]
    chain = SC.l1_chain(h - 1) if h >= 2 else None          # sc = 0 is below the carry gate (3a)
    if chain is not None and chain.div_carry is not None:
        fails.append(("carry is an L1 input", h - 1, chain.div_carry))
    while st.last_div_epoch < h // L - 1:
        E = st.last_div_epoch + 1
        if chain is not None and tuple(chain.accrual(E)) != accrual(E):
            fails.append(("accrual", E))
        st.accrue_dividend_epoch(*accrual(E), epoch=E)
        st.last_div_epoch = E
    if chain is not None:
        F = (h - 1) // L
        for e in sorted(set(range(-1, F + 3)) | set(st.beacons)):
            want = st.beacons.get(e)
            n_reads += 1
            if chain.read(zkvm2.IO_BEACON, e, h) != (None if want is None else int(want) & S2.MASK):
                fails.append(("beacon", h, e))
        held_ever |= set(st.block_hashes)
        for k in sorted(held_ever | {h, h + 1, -1}):
            want = st.block_hashes.get(k)
            n_reads += 1
            if chain.read(zkvm2.IO_BHASH, k, h) != (None if want is None else int(want) & S2.MASK):
                fails.append(("bhash", h, k))
    block_apply.begin(states, h)
    block_apply.dispatch(states, st, b, {}, set(), verbose=False)
    block_apply.close(states, h, b["block_hash"])
    if first4 is None and 4 in st.beacons:
        first4 = (h, st.beacons[4])
T.check("1a. the exec node's windows were exercised: the block-hash ring pruned to 100 and old beacons dropped",
        len(st.block_hashes) == 100 and min(st.block_hashes) == N - 99 and min(st.beacons) == N // L - 3,
        (len(st.block_hashes), min(st.block_hashes), sorted(st.beacons)))
T.check("1b. reveal-less epochs 4 and 5: beacon 4 was cached only once epoch 6 was final, from epoch 6's reveals",
        first4 is not None and first4[0] == 6 * L and first4[1] == ExecState.exec_beacon_int(4, kv_ops.reveals_for_epoch(6)),
        first4)
T.check(f"1c. for every block 1..{N}, every BEACON epoch and every block height a call could read ({n_reads} reads) "
        "and every epoch's accrual, L1's derivation equals the exec node's, and L1 supplies no carry",
        not fails and n_reads > 10000, fails[:5])

# ---- 2. the shadow run's path, on every 60-block span from a stash-like pre-state (the exec state AT the span's start)
st2 = ExecState(os.path.join(HOME, "st2.json"))
states2 = {"default": st2}


def apply2(b):
    h = b["block_number"]
    while st2.last_div_epoch < h // L - 1:
        E = st2.last_div_epoch + 1
        st2.accrue_dividend_epoch(*accrual(E), epoch=E)
        st2.last_div_epoch = E
    block_apply.begin(states2, h)
    block_apply.dispatch(states2, st2, b, {}, set(), verbose=False)
    block_apply.close(states2, h, b["block_hash"])


apply2(BLOCKS[0])
diffs, spans = [], 0
for i in range(0, N, L):
    span = BLOCKS[i + 1:i + 1 + L]
    pre = st2.clone()
    ref = S2.reference_chain(pre, span, accrual)
    doc = SC.l1_inputs_doc(pre.cursor, span[-1]["block_number"])
    diffs += SC.compare_with_reference(ref, SC.chain_from_doc(doc), span)
    if pre.cursor >= 1:
        diffs += SC.compare_with_reference(ref, SC.l1_chain(pre.cursor), span)
    elif doc["refused"] is None:
        diffs.append("the span from cursor 0 (below the carry gate) is not marked refused in the document")
    spans += 1
    for b in span:
        apply2(b)
T.check(f"2a. on all {spans} spans, the Chain built from /settle_chain_inputs' document and from kv_ops both equal "
        "reference_chain", not diffs and spans == N // L, diffs[:5])
rec = S2.shadow_span(pre, span, st2.state_root(), accrual, None, l1_inputs=doc)
T.check("2f. the shadow run reports it: the last span is proven with chain_eq true", rec["result"] == "proven"
        and rec["chain_eq"] is True and rec["chain_diff"] is None, rec)
_bad = copy.deepcopy(doc)
_E = next(iter(_bad["accrual"]))
_bad["accrual"][_E][0] += 1
rec = S2.shadow_span(pre, span, st2.state_root(), accrual, None, l1_inputs=_bad)
T.check("2g. ...and chain_eq false, naming the difference, when L1's inputs differ", rec["chain_eq"] is False
        and any("accrual" in x for x in rec["chain_diff"] or ()), rec)
rec = S2.shadow_span(pre, span, st2.state_root(), accrual, None)
T.check("2h. ...and chain_eq None (not checked, never 'equal') without L1's inputs", rec["chain_eq"] is None, rec)
# the last span again, with each input broken in turn: the comparison must SEE it (a check that never fails proves nothing)
T.check("2b. ...and the honest document compares equal", SC.compare_with_reference(ref, SC.chain_from_doc(doc), span) == [])
bad = copy.deepcopy(doc)
bad["accrual"][_E][0] += 1
T.check("2c. compare_with_reference reports a wrong accrual inflow",
        any("accrual" in x for x in SC.compare_with_reference(ref, SC.chain_from_doc(bad), span)))
bad = copy.deepcopy(doc)
e_rev = max(int(e) for e, v in bad["reveals"].items() if v)
bad["reveals"][str(e_rev)] = bad["reveals"][str(e_rev)][1:]
T.check("2d. ...a dropped reveal", any("BEACON" in x for x in SC.compare_with_reference(ref, SC.chain_from_doc(bad), span)))
bad = copy.deepcopy(doc)
bad["hashes"][-1] = "%064x" % 1
T.check("2e. ...and a wrong block hash", any("BHASH" in x for x in SC.compare_with_reference(ref, SC.chain_from_doc(bad), span)))

# ---- 3. what L1 cannot answer
with _harness.pinned(EXEC_CARRY_ROOT_HEIGHT=5 * L + 4):
    try:
        SC.l1_chain(5 * L + 3)                                     # one below the gate: no committed carry to start from
        refused = None
    except SC.SpanRefused as e:
        refused = e
    T.check("3a. a span starting below EXEC_CARRY_ROOT_HEIGHT is REFUSED (an AssertionError), never given a default carry",
            isinstance(refused, AssertionError) and "EXEC_CARRY_ROOT_HEIGHT" in str(refused), refused)
    T.check("3b. ...and from the gate it is judged, with no carry from L1 (no exec summary exists in this database)",
            SC.carry_refusal(5 * L + 4) is None and SC.l1_chain(5 * L + 4).div_carry is None
            and kv_ops.exec_summary_get(6 * L) is None)
    T.check("3b'. the shadow document says the same", SC.l1_inputs_doc(5 * L + 3, 6 * L)["refused"] is not None
            and SC.l1_inputs_doc(5 * L + 4, 6 * L)["refused"] is None)
chain = SC.chain_for_span(N - L, inflow_of=lambda E: 0, weights_of=lambda E: {}, reveals_of=lambda e: (),
                          hash_at=lambda k: None)
blk = {"block_number": N, "block_hash": "%064x" % 5, "block_transactions": [
    {"recipient": "blob", "sender": A, "txid": "t1", "data": {"op": "call", "contract": "x", "method": "m", "args": []}}]}


class _Reader(ExecState):
    def apply_blob(self, *a, **k):
        chain.read(zkvm2.IO_BHASH, N - 3, N)        # a call reading a block hash this node does not hold


rd = _Reader(os.path.join(HOME, "rd.json"))
try:
    block_apply.dispatch({"default": rd}, rd, blk, {}, set(), verbose=False)
    passed = None
except SC.ChainUnavailable as e:
    passed = e
T.check("3c. a block hash this node lacks is ChainUnavailable, and it passes through block_apply.dispatch's per-tx guard "
        "(it can never become a skipped call)", isinstance(passed, SC.ChainUnavailable) and not isinstance(passed, Exception),
        passed)
T.done()
