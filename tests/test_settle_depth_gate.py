"""
DEPTH-GATED settle-proof verification (doc/settle-proof-transport.md §4, option 1).

A settle proof is ~97 MiB against a ~256 KiB block, so it cannot ride in the block and must be fetched.
Re-verifying one per settle across all of history would make joining cost hundreds of GiB, so the
cryptographic check is gated to blocks still within FINALITY_DEPTH of the known tip.

This test exists to make the CONSEQUENCE explicit rather than implicit. The interesting case is not that a
valid proof still validates — it is that a **deliberately corrupted** proof is REJECTED near the tip and
ACCEPTED when deep. That is precisely what was traded away, and a test that only checked the happy path
would let the trade look free.

The safety argument the gate rests on is also asserted here: the gate must relax ONLY the expensive
cryptographic check. Every structural rule — cursor match, tip extension, root composition — must still
refuse a fabricated settle at any depth, so a deep block cannot smuggle in an arbitrary root.

Run: python3 tests/test_settle_depth_gate.py
"""
import os
import sys
import copy
import time
import tempfile
import logging

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_depthgate_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logging.getLogger("dg").addHandler(logging.NullHandler())
logger = logging.getLogger("dg")
from genesis import create_indexers
create_indexers()

import protocol
from protocol import B_MIN, DEFAULT_NS, chain_clock, EPOCH_LENGTH
from ops import kv_ops
from ops.account_ops import create_account, reflect_transaction
from ops.settlement_ops import latest_settled
from ops.transaction_ops import construct_settle_tx, validate_transaction
from ops.key_ops import generate_keys
from execnode import exec_root as ER, zkvmasm
from execnode.state import ExecState
from execnode.stark import (storage_tree as SST, settlement_sparse as SS, calls_commit as CC,
                            fri as _fri, stark as _stark)

fails = 0
_t0 = time.time()


def check(name, ok):
    global fails
    print(f"[{time.time()-_t0:6.0f}s] " + ("PASS  " if ok else "FAIL  ") + name, flush=True)
    if not ok:
        fails += 1


def raises(fn):
    try:
        fn()
        return False
    except Exception:
        return True


NS, BH, D8, NQ = DEFAULT_NS, 5 * EPOCH_LENGTH, 8, 2
CID, CALLER = "c" * 32, "ndo" + "A" * 46

_saved = (_fri.NUM_QUERIES, _stark.NUM_QUERIES, protocol.EXEC_TREE_DEPTH, protocol.EXEC_GENESIS_ROOT,
          protocol.SETTLE_PROOF_DEPTH_GATED)
try:
    _fri.NUM_QUERIES = NQ
    _stark.NUM_QUERIES = NQ
    protocol.EXEC_TREE_DEPTH = D8
    st0 = ExecState(os.path.join(tempfile.mkdtemp(), "s.json"))
    COUNTER = {"bump": zkvmasm.assemble(
        "movi r1 0\n sload r2 r1\n movi r3 1\n add r2 r3\n sstore r1 r2\n ret r2")}
    # The proof's pre-state has CID already deployed (empty slots), so the genesis tip it extends must too —
    # a contract's CODE is now committed in the KV half (exec_state_bind.code_key), so a deployed contract is
    # no longer invisible until its first slot write. Project the genesis contract set into kv_g8.
    GEN_CONTRACTS = {CID: {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}}
    kv_g8 = SST.SparseStore(D8, SS.sparse_projection(GEN_CONTRACTS, D8)).root()
    rec_g8 = SST.SparseStore(D8, ER.records_projection(st0)).root()
    rec_hex8 = SST.digest_hex(rec_g8)
    protocol.EXEC_GENESIS_ROOT = ER.full_root_hex(kv_g8, rec_g8)

    # quorum-settle genesis so a proof has a tip to extend
    V = generate_keys()
    create_account(V["address"], balance=B_MIN, bonded=4 * B_MIN)
    reflect_transaction(construct_settle_tx(V, 0, protocol.EXEC_GENESIS_ROOT, BH, ns=NS), logger,
                        block_height=BH)
    check("genesis tip settled by quorum", latest_settled(NS) == (0, protocol.EXEC_GENESIS_ROOT))

    # one block of exec work, its summary, and the honest proof over it
    H = 1
    BLOCK = {"block_number": H, "block_hash": f"{H:064x}", "block_transactions": [
        {"recipient": "blob", "sender": CALLER,
         "data": {"op": "call", "contract": CID, "method": "bump", "args": [], "ns": NS}}]}
    _inert, _calls = CC.block_summary(BLOCK)
    with kv_ops.write_txn():
        kv_ops.exec_summary_put(H, _inert, _calls)
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s2.json"))
    st.contracts[CID] = {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}
    st.cursor, st.block_ts = H, chain_clock(H)
    st.apply_blob({"op": "call", "contract": CID, "method": "bump", "args": []}, CALLER, "n1")
    real_root = ER.full_root_hex(SST.SparseStore(D8, SS.sparse_projection(st.contracts, D8)).root(), rec_g8)
    pre = {CID: {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}}
    proof = SS.prove_settlement_sparse(pre, CC.block_calls(BLOCK, NS), cursor=H, rec_hex=rec_hex8,
                                       num_queries=NQ, depth=D8)

    def settler():
        k = generate_keys()
        create_account(k["address"], balance=B_MIN, bonded=B_MIN)
        return k

    # --- an HONEST proof validates in both regimes ---------------------------------------------------
    check("honest proof validates NEAR THE TIP (strict: proof is verified)",
          validate_transaction(construct_settle_tx(settler(), H, real_root, BH, ns=NS, proof=proof),
                               logger, BH, deep=False))
    check("honest proof validates when DEEP (relaxed: verification skipped)",
          validate_transaction(construct_settle_tx(settler(), H, real_root, BH, ns=NS, proof=proof),
                               logger, BH, deep=True))

    # --- THE TRADE, made explicit: a CORRUPTED proof is caught only near the tip ----------------------
    bad = copy.deepcopy(proof)
    seg = bad["segments"][0]
    seg["proof"]["openings"] = seg["proof"]["openings"][:-1] or [[0]]     # break the FRI openings
    check("corrupted proof is REJECTED near the tip",
          raises(lambda: validate_transaction(
              construct_settle_tx(settler(), H, real_root, BH, ns=NS, proof=bad), logger, BH, deep=False)))
    check("corrupted proof is ACCEPTED when deep — this is exactly what was traded away",
          validate_transaction(construct_settle_tx(settler(), H, real_root, BH, ns=NS, proof=bad),
                               logger, BH, deep=True))

    # --- the gate must relax ONLY the crypto: structure still refuses a fabricated settle -------------
    wrong_cursor = copy.deepcopy(proof)
    wrong_cursor["cursor"] = H + 7
    check("a cursor mismatch is refused even when DEEP (structure is not gated)",
          raises(lambda: validate_transaction(
              construct_settle_tx(settler(), H, real_root, BH, ns=NS, proof=wrong_cursor),
              logger, BH, deep=True)))

    fabricated = copy.deepcopy(proof)
    fabricated["kv_post"] = SST.digest_hex((7, 7, 7, 7))
    check("a settle claiming a root its own proof does not compose to is refused when DEEP",
          raises(lambda: validate_transaction(
              construct_settle_tx(settler(), H, real_root, BH, ns=NS, proof=fabricated),
              logger, BH, deep=True)))

    # --- and the gate is switchable: with it OFF, depth buys nothing ----------------------------------
    protocol.SETTLE_PROOF_DEPTH_GATED = False
    check("with SETTLE_PROOF_DEPTH_GATED False, a corrupted proof is refused even when deep",
          raises(lambda: validate_transaction(
              construct_settle_tx(settler(), H, real_root, BH, ns=NS, proof=bad), logger, BH, deep=True)))
finally:
    (_fri.NUM_QUERIES, _stark.NUM_QUERIES, protocol.EXEC_TREE_DEPTH, protocol.EXEC_GENESIS_ROOT,
     protocol.SETTLE_PROOF_DEPTH_GATED) = _saved

print()
print("ALL PASS — verification is depth-gated, structure is not, and the cost is asserted not assumed"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
