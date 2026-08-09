"""
END-TO-END proof of the settle-with-proof PRODUCER path (execnode._build_settlement_proof's design):
a proof assembled the way the exec node's prover loop assembles it — from calls_commit.block_calls over
the DA calldata, extending an L1-quorum-settled tip — passes the FULL L1 validate_transaction (sparse
verify + records-frozen + epoch-boundary + no-PAY + prune-safe summary DA-binding) and then, with
protocol.SETTLE_PROOF_TRUSTLESS on, JUSTIFIES the exec root. This is the one path the prover loop relies
on; it is run at reduced STARK params (like test_settle_with_proof t10; ~1 min).

Run: python3 tests/test_settle_prover_sim.py
"""
import os, sys, tempfile, logging

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_settleprove_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logging.getLogger("sps").addHandler(logging.NullHandler())
logger = logging.getLogger("sps")
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
from execnode.stark import storage_tree as SST, settlement_sparse as SS, calls_commit as CC, fri as _fri, stark as _stark

fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok: fails += 1

NS = DEFAULT_NS
BH = 5 * EPOCH_LENGTH                     # a comfortable block height for validation
D8 = 8

# reduced params + patched genesis (feasible off the prover box), like t10
_saved = (_fri.NUM_QUERIES, _stark.NUM_QUERIES, protocol.EXEC_TREE_DEPTH, protocol.EXEC_GENESIS_ROOT,
          protocol.SETTLE_PROOF_TRUSTLESS)
try:
    _fri.NUM_QUERIES = 2; _stark.NUM_QUERIES = 2; protocol.EXEC_TREE_DEPTH = D8
    COUNTER = {"bump": zkvmasm.assemble("movi r1 0\n sload r2 r1\n movi r3 1\n add r2 r3\n sstore r1 r2\n ret r2")}
    CID = "c" * 32; CALLER = "ndo" + "A" * 46
    # CID is deployed (empty slots) in the proof's pre-state, so the genesis tip it extends must carry its code
    # leaf — contract CODE is now committed in the KV half (exec_state_bind.code_key), so a deployed contract
    # is no longer invisible until its first slot write. Project the genesis contract set into kv_g8.
    GEN_CONTRACTS = {CID: {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}}
    kv_g8 = SST.SparseStore(D8, SS.sparse_projection(GEN_CONTRACTS, D8)).root()
    rec_g8 = SST.SparseStore(D8, ER.records_projection(ExecState(tempfile.mktemp(suffix=".json")))).root()
    rec_hex8 = SST.digest_hex(rec_g8)
    protocol.EXEC_GENESIS_ROOT = ER.full_root_hex(kv_g8, rec_g8)

    # --- 1) QUORUM-settle the genesis tip at cursor 0 (the first settlement must be by quorum) ---
    V = generate_keys(); create_account(V["address"], balance=B_MIN, bonded=4 * B_MIN)
    tx0 = construct_settle_tx(V, 0, protocol.EXEC_GENESIS_ROOT, BH, ns=NS)
    check("quorum genesis settle validates", validate_transaction(tx0, logger, BH))
    reflect_transaction(tx0, logger, block_height=BH)
    check("genesis tip is justified by quorum", settlement_justified(NS, 0, protocol.EXEC_GENESIS_ROOT, get_bonded_registry()))
    check("latest_settled tip is (0, genesis)", latest_settled(NS) == (0, protocol.EXEC_GENESIS_ROOT))

    # --- 2) the exec node's view: apply the bump call at cursor 1 (block_ts = chain_clock(1)) -> real root ---
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json"))
    st.contracts[CID] = {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}
    st.cursor = 1; st.block_ts = chain_clock(1)
    st.apply_blob({"op": "call", "contract": CID, "method": "bump", "args": []}, CALLER, "n1")
    real_root = ER.full_root_hex(SST.SparseStore(D8, SS.sparse_projection(st.contracts, D8)).root(), rec_g8)

    # --- 3) persist the block-1 exec summary the DA binding reads (what incorporate_block writes) ---
    block1 = {"block_number": 1, "block_hash": "ab" * 32, "block_transactions": [
        {"recipient": "blob", "sender": CALLER,
         "data": {"op": "call", "contract": CID, "method": "bump", "args": [], "ns": NS}}]}
    calls = CC.block_calls(block1, NS)
    from execnode.stark.calls_commit import block_summary
    _inert, _calls_by_ns = block_summary(block1)           # exactly what incorporate_block derives + stores
    with kv_ops.write_txn():
        kv_ops.exec_summary_put(1, _inert, _calls_by_ns)

    # --- 4) build the settle-with-proof exactly as the prover loop does, and SELF-CHECK ---
    pre = {CID: {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}}
    proof = SS.prove_settlement_sparse(pre, calls, cursor=1, rec_hex=rec_hex8, num_queries=2, depth=D8)
    composed_post = ER.full_root_hex(SST.digest_from_hex(proof["kv_post"]), rec_g8)
    check("SELF-CHECK: proof reproduces the exec node's real root", composed_post == real_root)
    check("SELF-CHECK: proof pre extends the justified tip", ER.full_root_hex(SST.digest_from_hex(proof["kv_pre"]), rec_g8) == protocol.EXEC_GENESIS_ROOT)

    # --- 5) the FULL L1 validation must accept it (summary DA-binding, records-frozen, no PAY, epoch, verify) ---
    V2 = generate_keys(); create_account(V2["address"], balance=B_MIN, bonded=B_MIN)   # bonded (settle requires it)
    txp = construct_settle_tx(V2, 1, real_root, BH, ns=NS, proof=proof)
    check("settle-with-proof passes the FULL L1 validation", validate_transaction(txp, logger, BH))

    # --- 6) apply it, then with the trustless flag ON the proof JUSTIFIES the root ---
    reflect_transaction(txp, logger, block_height=BH)
    check("apply recorded the proof marker", kv_ops.settlement_proven(NS, 1, real_root))
    protocol.SETTLE_PROOF_TRUSTLESS = True
    check("flag ON: the settle-with-proof JUSTIFIES the exec root (trustless, marker honoured)",
          settlement_justified(NS, 1, real_root, get_bonded_registry()))
    # (flag-OFF => quorum-only is proven in tests/test_settle_trustless_flag.py; not re-derived here.)
finally:
    (_fri.NUM_QUERIES, _stark.NUM_QUERIES, protocol.EXEC_TREE_DEPTH, protocol.EXEC_GENESIS_ROOT,
     protocol.SETTLE_PROOF_TRUSTLESS) = _saved

print("\nALL PASS — the prover-loop proof is accepted and settles trustlessly" if fails == 0 else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
