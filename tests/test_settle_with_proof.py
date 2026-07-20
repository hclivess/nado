"""
ON-CHAIN SETTLE-WITH-PROOF (the trustless settlement path, alphanet-6 SPARSE scheme). A `settle` tx MAY carry
a sparse settlement proof {cursor, kv_pre, kv_post, rec, segments}; every node verifies it DETERMINISTICALLY at
block-validation — chained bound epochs over the KV half at the PROTOCOL tree depth, then the rnode compositions
rnode(kv_pre, rec) == committed settled tip and rnode(kv_post, rec) == the attested state_root — and, on success,
records the on-chain marker (kv_ops.settlement_proven) that settlement_ops.settlement_justified reads. The
records half is pinned UNCHANGED (the enforced restriction: record-moving epochs ride the bonded quorum until
record transitions are proven in-circuit — same tree, no scheme change).

This file tests the CONSENSUS WIRING end-to-end: construct -> validate -> apply -> justified -> revert, plus the
exact-root binding, strict chain-extension, cursor binding, the genesis (kv, rec) decomposition, and that a bare
(proofless) settle still works as a quorum attestation. To keep it CI-fast it stubs
settlement_sparse.verify_settlement_sparse (whose real soundness is covered by tests/test_settlement_sparse.py);
NADO_HEAVY=1 drives a REAL bound-epoch proof through the identical flow at a patched tree depth.

Run: python3 tests/test_settle_with_proof.py     (NADO_HEAVY=1 python3 … for the real-proof end-to-end)
"""
import os, sys, tempfile, traceback, logging
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_swp_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

logger = logging.getLogger("swp"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

import protocol
from protocol import B_MIN, DEFAULT_NS, EXEC_GENESIS_ROOT
from ops import kv_ops
from ops.account_ops import create_account, reflect_transaction, get_bonded_registry
from ops.settlement_ops import settlement_justified, latest_settled
from ops.transaction_ops import construct_settle_tx, validate_transaction
from ops.key_ops import generate_keys
from execnode import exec_root as ER
from execnode.state import ExecState
from execnode.stark import storage_tree as SST, settlement_sparse as SS

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()
def raises(fn):
    try: fn(); return False
    except Exception: return True

# --- verify_settlement_sparse STUB: trusts the proof's declared kv halves so the test can drive the chain /
# cursor / composition bindings without STARK proving. `_verify_ok=False` simulates a failed crypto verify. ---
_REAL_VERIFY = SS.verify_settlement_sparse
def _stub_verify(proof, num_queries=None, depth=None):
    if not isinstance(proof, dict) or not proof.get("_verify_ok", True):
        return False, "stub: proof rejected", None, None
    return True, "stub ok", proof.get("kv_pre"), proof.get("kv_post")
SS.verify_settlement_sparse = _stub_verify

# --- the GENESIS decomposition: EXEC_GENESIS_ROOT == rnode(empty KV half, empty-state RECORDS half) ---
KV_G = SST.digest_hex(SST.SparseStore(ER.DEPTH, {}).root())
REC_G = SST.digest_hex(SST.SparseStore(ER.DEPTH,
                                       ER.records_projection(ExecState(tempfile.mktemp(suffix=".json")))).root())
assert ER.full_root_hex(SST.digest_from_hex(KV_G), SST.digest_from_hex(REC_G)) == EXEC_GENESIS_ROOT, \
    "genesis (kv, rec) decomposition must compose to EXEC_GENESIS_ROOT"


def _kv(i):
    """An arbitrary (stub) KV half digest, distinct per i."""
    return SST.digest_hex((int(i), 0, 0, 0))


def _full(kv_hex, rec_hex=REC_G):
    return ER.full_root_hex(SST.digest_from_hex(kv_hex), SST.digest_from_hex(rec_hex))


R0 = _full(_kv(1))       # first settled root (post of cursor 0): kv moved, records unchanged
R1 = _full(_kv(2))       # second settled root (post of cursor 1)
BH = 100                 # block height we validate at

V = generate_keys(); create_account(V["address"], balance=B_MIN, bonded=4 * B_MIN)
REG = get_bonded_registry()


def _seed_span(lo, hi):
    """Persist the per-block EXEC SUMMARIES the DA binding reads for the span (lo, hi].

    The binding is a pure function of committed state (kv_ops.exec_summary_get) rather than of block
    BODIES, because bodies are prunable AND are wiped wholesale by a snapshot re-anchor — reading them made
    the check fork the fleet. Empty, records-inert blocks here: no calls, so each segment's honest
    calls_commitment is just the unextended chain start (alghash.IV)."""
    for h in range(int(lo) + 1, int(hi) + 1):
        kv_ops.exec_summary_put(h, True, {})


def _proof(kv_pre, cursor, kv_post, ok=True, rec=REC_G, prev=None):
    """A stub settlement proof. `prev` (the settled cursor this extends) seeds the span's exec summaries so
    the DA binding can be satisfied honestly instead of bypassed."""
    from execnode.stark import alghash
    if prev is not None:
        _seed_span(prev, cursor)
    return {"cursor": int(cursor), "kv_pre": kv_pre, "kv_post": kv_post, "rec": rec,
            "segments": [{"depth": ER.DEPTH, "cursor": int(cursor), "calls_commitment": alghash.IV}],
            "_verify_ok": ok}


def _settle(cursor, root, proof, sender=V, ns=DEFAULT_NS):
    return construct_settle_tx(sender, cursor, root, max_block=BH + 50, proof=proof, ns=ns)


def t1_first_settlement_must_be_quorum():
    """A proof may only EXTEND an already-settled tip — the FIRST settlement in a namespace must come from
    the bonded quorum.

    This is what bounds the exec-summary window the DA binding reads: a proof's span is always
    (settled_cursor, cursor], i.e. recent and small, never "from block 0". Block 0 is guaranteed pruned on
    every node, and a genesis-spanning proof was the concrete case that broke the previous attempt at a
    trustless path (a0453c5). Seeds the tip by QUORUM here, which the later tests then extend by proof."""
    tx = _settle(0, R0, _proof(KV_G, 0, _kv(1)))
    assert raises(lambda: validate_transaction(tx, logger, block_height=BH)), \
        "a proof-settle with no prior settled tip must be REJECTED"
    assert not kv_ops.settlement_proven(DEFAULT_NS, 0, R0), "and must set no marker"
    # Seed the tip the legitimate way: a bonded attestation, no proof. V holds every active settler share,
    # so its single attestation clears the 2/3 quorum.
    kv_ops.settlement_put(DEFAULT_NS, 0, V["address"], R0)
    assert settlement_justified(DEFAULT_NS, 0, R0, REG), "the quorum path must justify the first root"
    assert latest_settled(DEFAULT_NS) == (0, R0), "latest_settled must point at the quorum-settled root"
    assert not settlement_justified(DEFAULT_NS, 0, "cc" * 32, REG), "only the attested root is justified"


def t2_post_root_must_equal_state_root():
    """If the tx claims a state_root the proof does not prove (kv_post composes elsewhere), validation rejects."""
    tx = _settle(1, R1, _proof(_kv(1), 1, _kv(9)))                 # extends tip 0, but proves a different post
    assert raises(lambda: validate_transaction(tx, logger, BH)), "post_root != state_root must be rejected"


def t3_chain_break_rejected():
    """rnode(kv_pre, rec) must equal the committed settled tip (here R0); any other pre-state is rejected."""
    tx = _settle(1, R1, _proof(_kv(7), 1, _kv(2)))                 # pre composes to neither tip nor genesis
    assert raises(lambda: validate_transaction(tx, logger, BH)), "pre not extending the tip must reject"
    tx2 = _settle(1, R1, _proof(KV_G, 1, _kv(2)))                  # stale genesis pre once a tip exists
    assert raises(lambda: validate_transaction(tx2, logger, BH)), "stale genesis pre_root must reject past tip 0"
    # a records half OTHER than the tip's cannot smuggle a record change through the proof path
    other_rec = SST.digest_hex((99, 99, 99, 99))
    tx3 = _settle(1, _full(_kv(2), other_rec), _proof(_kv(1), 1, _kv(2), rec=other_rec))
    assert raises(lambda: validate_transaction(tx3, logger, BH)), "a moved records half must reject (pre != tip)"


def t4_cursor_binding():
    """The proof's cursor must equal the tx's exec_cursor."""
    tx = _settle(1, R1, _proof(_kv(1), 7, _kv(2)))                 # proof says cursor 7, tx says 1
    assert raises(lambda: validate_transaction(tx, logger, BH)), "cursor mismatch must be rejected"


def t5_failed_crypto_verify_rejected():
    """If the sparse settlement proof fails cryptographic verification, the tx is rejected."""
    tx = _settle(1, R1, _proof(_kv(1), 1, _kv(2), ok=False))
    assert raises(lambda: validate_transaction(tx, logger, BH)), "a proof that fails verify must be rejected"


def t6_chain_extends():
    """A proof extending tip 0 (kv_pre = kv of R0) settles cursor 1 -> R1 TRUSTLESSLY: latest_settled
    advances with NO bonded attestation at cursor 1 at all. This is the actual trustless-settlement claim."""
    assert not kv_ops.settlements_for_cursor(DEFAULT_NS, 1), \
        "cursor 1 must carry no quorum attestation — otherwise this proves nothing about the proof path"
    tx = _settle(1, R1, _proof(_kv(1), 1, _kv(2), prev=0))
    assert validate_transaction(tx, logger, BH), "proof extending the tip must validate"
    reflect_transaction(tx, logger, block_height=BH)
    assert kv_ops.settlement_proven(DEFAULT_NS, 1, R1)
    assert latest_settled(DEFAULT_NS) == (1, R1), "tip must advance to the new proven root"


def t7_revert_symmetry():
    """Reverting a settle-with-proof clears the marker exactly: the root is no longer justified."""
    R2 = _full(_kv(3))
    tx = _settle(2, R2, _proof(_kv(2), 2, _kv(3), prev=1))
    validate_transaction(tx, logger, BH)
    reflect_transaction(tx, logger, block_height=BH)
    assert kv_ops.settlement_proven(DEFAULT_NS, 2, R2)
    reflect_transaction(tx, logger, block_height=BH, revert=True)
    assert not kv_ops.settlement_proven(DEFAULT_NS, 2, R2), "revert must clear the proof marker"
    assert latest_settled(DEFAULT_NS) == (1, R1), "after revert the tip falls back to the prior proven root"


def t8_bare_settle_still_quorum_only():
    """A proofless settle (the Phase-2a path) validates + applies as a plain attestation and sets NO proof
    marker — it justifies only through the bonded quorum, unchanged."""
    W = generate_keys(); create_account(W["address"], balance=B_MIN, bonded=4 * B_MIN)
    tx = construct_settle_tx(W, 3, "12" * 32, max_block=BH + 50)   # no proof
    assert "proof" not in (tx["data"]), "bare settle carries no proof"
    assert validate_transaction(tx, logger, BH), "bare settle must still validate"
    reflect_transaction(tx, logger, block_height=BH)
    assert not kv_ops.settlement_proven(DEFAULT_NS, 3, "12" * 32), "bare settle sets no proof marker"


def t9_non_bonded_proof_settle_rejected():
    """Only a bonded validator may settle — a proof does not bypass the bond requirement."""
    poor = generate_keys(); create_account(poor["address"], balance=B_MIN)   # not bonded
    tx = _settle(9, R1, _proof(_kv(2), 9, _kv(2)), sender=poor)
    assert raises(lambda: validate_transaction(tx, logger, BH)), "non-bonded proof-settle must be rejected"


def t10_real_proof_end_to_end():
    """OPT-IN (NADO_HEAVY=1): a REAL sparse bound-epoch settlement through the identical on-chain flow, on a
    fresh namespace at a patched tree depth + genesis (feasible off the prover box). Every check is the real
    one: bound epoch verify, kv chaining, rnode compositions against the (patched) genesis."""
    if os.environ.get("NADO_HEAVY") != "1":
        print("SKIP  real bound-epoch proof end-to-end (set NADO_HEAVY=1; minutes)")
        return
    SS.verify_settlement_sparse = _REAL_VERIFY
    import execnode.stark.fri as fri
    from execnode.stark import stark as _stark
    from execnode import zkvmasm
    D8 = 8
    # The settle verify path pins its query strength to vm_circuit.stark.NUM_QUERIES (never the prover's word).
    # stark.py binds NUM_QUERIES BY VALUE at import (from ...fri import NUM_QUERIES), so patching only fri leaves
    # verify at 64 while the proof is built at 2 -> "wrong FRI query count". Patch BOTH so prove and the
    # protocol-pinned verify agree at the small test count.
    saved_q, saved_sq, saved_depth, saved_gen = fri.NUM_QUERIES, _stark.NUM_QUERIES, protocol.EXEC_TREE_DEPTH, protocol.EXEC_GENESIS_ROOT
    try:
        fri.NUM_QUERIES = 2
        _stark.NUM_QUERIES = 2
        protocol.EXEC_TREE_DEPTH = D8
        kv_g8 = SST.SparseStore(D8, {}).root()
        rec_g8 = SST.SparseStore(D8, ER.records_projection(ExecState(tempfile.mktemp(suffix=".json")))).root()
        rec_hex8 = SST.digest_hex(rec_g8)
        protocol.EXEC_GENESIS_ROOT = ER.full_root_hex(kv_g8, rec_g8)
        COUNTER = {"bump": zkvmasm.assemble("movi r1 0\n sload r2 r1\n movi r3 1\n add r2 r3\n sstore r1 r2\n ret r2")}
        cid = "c" * 32; caller = "ndoAAAA" + "A" * 41
        pre = {cid: {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}}
        calls = [{"cid": cid, "method": "bump", "caller": caller, "args": []}]
        proof = SS.prove_settlement_sparse(pre, calls, cursor=0, rec_hex=rec_hex8, num_queries=2, depth=D8)
        root = ER.full_root_hex(SST.digest_from_hex(proof["kv_post"]), rec_g8)
        assert ER.full_root_hex(SST.digest_from_hex(proof["kv_pre"]), rec_g8) == protocol.EXEC_GENESIS_ROOT
        U = generate_keys(); create_account(U["address"], balance=B_MIN, bonded=4 * B_MIN)
        tx = _settle(0, root, proof, sender=U, ns="proofns")
        assert validate_transaction(tx, logger, BH), "real sparse proof-settle must validate"
        reflect_transaction(tx, logger, block_height=BH)
        assert settlement_justified("proofns", 0, root, get_bonded_registry())
    finally:
        fri.NUM_QUERIES = saved_q
        _stark.NUM_QUERIES = saved_sq
        protocol.EXEC_TREE_DEPTH = saved_depth
        protocol.EXEC_GENESIS_ROOT = saved_gen
        SS.verify_settlement_sparse = _stub_verify


if __name__ == "__main__":
    check("first settlement must be quorum, not proof", t1_first_settlement_must_be_quorum)
    check("post_root must equal state_root", t2_post_root_must_equal_state_root)
    check("chain break / moved records half rejected", t3_chain_break_rejected)
    check("cursor binding", t4_cursor_binding)
    check("failed crypto verify rejected", t5_failed_crypto_verify_rejected)
    check("chain extends (tip advances)", t6_chain_extends)
    check("revert symmetry (marker cleared)", t7_revert_symmetry)
    check("bare settle still quorum-only", t8_bare_settle_still_quorum_only)
    check("non-bonded proof-settle rejected", t9_non_bonded_proof_settle_rejected)
    check("real sparse bound-epoch proof end-to-end (opt-in)", t10_real_proof_end_to_end)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
