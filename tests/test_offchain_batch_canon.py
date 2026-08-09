"""
A BATCH OF OFF-CHAIN WORK BECOMES CANON — the network path, not the library path.

tests/test_offchain_bulk_reuptake.py proves a burst of off-chain transactions MERGES into one settlement
that reaches the honest root. That is a statement about this process only. It says nothing about whether
the rest of the network would accept the thing, and a settlement nobody else accepts is not a settlement.

This runs the burst through the path a real batch actually travels:

    off-chain calls across N blocks
      -> ONE `settle` transaction carrying the merged proof   (construct_settle_tx)
      -> the mempool / block, like any other transaction
      -> validate_transaction                                 <- the rule EVERY end node runs
      -> settlement_justified                                 <- it is now canon, with NO bonded quorum

validate_transaction is the point of the test. It is not a convenience wrapper around
verify_settlement_sparse: it additionally enforces the summary DA-binding (the proof's calls must match the
calldata actually on chain, so a prover cannot settle work nobody published), the records-frozen
precondition, the no-PAY rule, the epoch-boundary refusal and the protocol query strength — none of which
a direct library call exercises. A proof can pass verify_settlement_sparse and still be rejected by every
node on the network, and that gap is exactly where "works on my node" hides.

The negative case matters as much as the positive one: a batch that quietly drops one off-chain
transaction must NOT be able to justify the honest root. Otherwise "settled" would mean "some prover said
so", which is the property the whole validity-proof line exists to avoid.

Reduced STARK params + a toy tree depth, like test_settle_prover_sim — this is about the ACCEPTANCE path,
and cryptographic strength is pinned at protocol constants and covered by the recursion suite.

Run: python3 tests/test_offchain_batch_canon.py
"""
import os
import sys
import tempfile
import logging

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_batchcanon_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logging.getLogger("obc").addHandler(logging.NullHandler())
logger = logging.getLogger("obc")
from genesis import create_indexers
create_indexers()

import protocol
from protocol import B_MIN, DEFAULT_NS, chain_clock, EPOCH_LENGTH
from ops import kv_ops
from ops.account_ops import create_account, reflect_transaction, get_bonded_registry
from ops.settlement_ops import settlement_justified, latest_settled
from ops.transaction_ops import construct_settle_tx, validate_transaction
from ops.key_ops import generate_keys
from execnode import exec_root as ER, zkvmasm
from execnode.state import ExecState
from execnode.stark import (storage_tree as SST, settlement_sparse as SS, calls_commit as CC,
                            fri as _fri, stark as _stark)

fails = 0


import time as _time
_t0 = _time.time()


def check(name, ok):
    global fails
    print(f"[{_time.time()-_t0:6.0f}s] " + ("PASS  " if ok else "FAIL  ") + name, flush=True)
    if not ok:
        fails += 1


def raises(fn):
    """True if fn() rejects. validate_transaction signals rejection by RAISING (bare asserts), never by
    returning False, so a negative case must catch rather than negate."""
    try:
        fn()
        return False
    except Exception:
        return True


NS = DEFAULT_NS
BH = 5 * EPOCH_LENGTH
D8 = 8
CID = "c" * 32
CALLER = "ndo" + "A" * 46

# The burst. Spread across BLOCKS because the DA binding and recursive segmentation are BLOCK-ALIGNED:
# one segment per block, each bound to that block's stored exec summary. A single fat block would be one
# segment and would not exercise the chaining the network actually has to check.
FIRST, BLOCKS, PER_BLOCK = 1, 3, 2
HEIGHTS = list(range(FIRST, FIRST + BLOCKS))
N = BLOCKS * PER_BLOCK

_saved = (_fri.NUM_QUERIES, _stark.NUM_QUERIES, protocol.EXEC_TREE_DEPTH, protocol.EXEC_GENESIS_ROOT,
          protocol.SETTLE_PROOF_TRUSTLESS)
try:
    _fri.NUM_QUERIES = 2
    _stark.NUM_QUERIES = 2
    protocol.EXEC_TREE_DEPTH = D8
    COUNTER = {"bump": zkvmasm.assemble(
        "movi r1 0\n sload r2 r1\n movi r3 1\n add r2 r3\n sstore r1 r2\n ret r2")}
    # The proof's pre-state has CID deployed (empty slots), so the genesis tip it extends must carry its code
    # leaf — contract CODE is now committed in the KV half (exec_state_bind.code_key), so a deployed contract
    # is no longer invisible until its first slot write. Project the genesis contract set into kv_g8.
    GEN_CONTRACTS = {CID: {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}}
    kv_g8 = SST.SparseStore(D8, SS.sparse_projection(GEN_CONTRACTS, D8)).root()
    rec_g8 = SST.SparseStore(D8, ER.records_projection(ExecState(tempfile.mktemp(suffix=".json")))).root()
    rec_hex8 = SST.digest_hex(rec_g8)
    protocol.EXEC_GENESIS_ROOT = ER.full_root_hex(kv_g8, rec_g8)

    print(f"\noff-chain burst: {N} calls across {BLOCKS} blocks ({PER_BLOCK}/block)\n")

    # --- 1) the first settlement must be by quorum; settle the genesis tip at cursor 0 ---
    V = generate_keys()
    create_account(V["address"], balance=B_MIN, bonded=4 * B_MIN)
    tx0 = construct_settle_tx(V, 0, protocol.EXEC_GENESIS_ROOT, BH, ns=NS)
    check("genesis tip settles by quorum (a proof may only EXTEND a committed tip)",
          validate_transaction(tx0, logger, BH))
    reflect_transaction(tx0, logger, block_height=BH)
    check("genesis tip is justified", latest_settled(NS) == (0, protocol.EXEC_GENESIS_ROOT))

    # --- 2) the exec node runs the burst; and each block's summary is stored, as incorporate_block does ---
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json"))
    st.contracts[CID] = {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}
    all_calls = []
    for h in HEIGHTS:
        st.cursor = h
        st.block_ts = chain_clock(h)
        txs = []
        for i in range(PER_BLOCK):
            st.apply_blob({"op": "call", "contract": CID, "method": "bump", "args": []}, CALLER, f"n{h}-{i}")
            txs.append({"recipient": "blob", "sender": CALLER,
                        "data": {"op": "call", "contract": CID, "method": "bump", "args": [], "ns": NS}})
        block = {"block_number": h, "block_hash": f"{h:064x}", "block_transactions": txs}
        all_calls += CC.block_calls(block, NS)
        _inert, _calls_by_ns = CC.block_summary(block)
        with kv_ops.write_txn():
            kv_ops.exec_summary_put(h, _inert, _calls_by_ns)
    print(f"[{_time.time()-_t0:6.0f}s] .. burst applied, summaries stored; proving", flush=True)
    real_root = ER.full_root_hex(SST.SparseStore(D8, SS.sparse_projection(st.contracts, D8)).root(), rec_g8)
    check(f"the burst produced {N} on-chain calls to settle", len(all_calls) == N)

    # --- 3) ONE merged settlement over the whole span ---
    pre = {CID: {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}}
    span_end = HEIGHTS[-1]
    proof = SS.prove_settlement_sparse(pre, all_calls, cursor=span_end, rec_hex=rec_hex8,
                                       num_queries=2, depth=D8, recursive=True, fold=False)
    check(f"the merged settlement carries one segment per block ({BLOCKS})",
          len(proof["segments"]) == BLOCKS)
    composed = ER.full_root_hex(SST.digest_from_hex(proof["kv_post"]), rec_g8)
    check("SELF-CHECK: the merged proof reproduces the exec node's real root", composed == real_root)

    # --- 4) THE POINT: the rule every end node runs must accept it ---
    V2 = generate_keys()
    create_account(V2["address"], balance=B_MIN, bonded=B_MIN)
    print(f"[{_time.time()-_t0:6.0f}s] .. merged proof built; running FULL L1 validation", flush=True)
    txp = construct_settle_tx(V2, span_end, real_root, BH, ns=NS, proof=proof)
    check(f"a settle tx carrying {N} off-chain txs passes the FULL L1 validation "
          "(DA-binding + records-frozen + no-PAY + epoch + verify)",
          validate_transaction(txp, logger, BH))

    # --- 5) NEGATIVE, and it must run BEFORE the honest settle is applied ---
    # A batch built over the same blocks minus the final call. It is internally valid — it proves the work
    # it actually ran — but it reaches a DIFFERENT root, so it must not be passable off as this span's
    # result. Two things this ordering gets right, both learned by getting them wrong:
    #   * a DIFFERENT validator signs it. `settlement_exists(ns, cursor, sender)` is one-settle-per
    #     (ns, validator, cursor), so reusing V2 is rejected by that rule BEFORE the proof is ever looked
    #     at — the test would pass while proving nothing about the proof.
    #   * it runs while the tip is still genesis. After the honest settle the tip has moved, and the short
    #     proof would be rejected for not extending the tip — a real rule, but not the one under test.
    print(f"[{_time.time()-_t0:6.0f}s] .. building the NEGATIVE (dropped-tx) batch", flush=True)
    short = SS.prove_settlement_sparse(pre, all_calls[:-1], cursor=span_end, rec_hex=rec_hex8,
                                       num_queries=2, depth=D8, recursive=True, fold=False)
    short_root = ER.full_root_hex(SST.digest_from_hex(short["kv_post"]), rec_g8)
    check("a batch missing one off-chain tx reaches a DIFFERENT root", short_root != real_root)
    V3 = generate_keys()
    create_account(V3["address"], balance=B_MIN, bonded=B_MIN)
    txbad = construct_settle_tx(V3, span_end, real_root, BH, ns=NS, proof=short)
    # validate_transaction signals rejection by RAISING (bare asserts), so `not validate(...)` would
    # propagate instead of evaluating False.
    check("...and claiming the honest root with it is REJECTED by every node's validation",
          raises(lambda: validate_transaction(txbad, logger, BH)))

    # --- 6) the honest batch becomes CANON with no bonded quorum ---
    reflect_transaction(txp, logger, block_height=BH)
    check("apply recorded the proof marker", kv_ops.settlement_proven(NS, span_end, real_root))
    protocol.SETTLE_PROOF_TRUSTLESS = True
    check(f"the batch of {N} off-chain txs is now CANON, trustlessly (no quorum)",
          settlement_justified(NS, span_end, real_root, get_bonded_registry()))
    check("the settled tip advanced to the end of the span",
          latest_settled(NS) == (span_end, real_root))
finally:
    (_fri.NUM_QUERIES, _stark.NUM_QUERIES, protocol.EXEC_TREE_DEPTH, protocol.EXEC_GENESIS_ROOT,
     protocol.SETTLE_PROOF_TRUSTLESS) = _saved

print()
print(f"ALL PASS — {N} off-chain transactions settled as ONE transaction the whole network accepts"
      if fails == 0 else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
