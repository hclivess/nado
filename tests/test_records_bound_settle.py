"""
RECORDS-BOUND SETTLEMENT, END TO END — a span that MOVED records settles by proof, as canon.

Until now a settle-with-proof covered only the KV half: the L1 composition pinned the SAME records half
into the pre and post root, so any span carrying a bridge deposit, a faucet donation or a treasury payout
fell back to the bonded quorum however good its proof was. records_bind could derive those effects but had
nothing to derive FROM at validation time — the prune-safe exec summary carried no records transactions,
only an `inert` boolean saying THAT records moved.

SETTLE_PROOF_RECORDS closes both halves of that:
  * incorporate_block commits each block's records EFFECTS into its exec summary, so a verifier derives
    them without ever touching a prunable body;
  * the settle branch accepts a proof whose records half MOVED, provided it carries a records transition
    proving exactly the effects THIS NODE committed.

This exercises the whole path with the flag on — summary -> settle tx -> validate_transaction (the rule
every end node runs) -> settlement_justified — plus the four ways it must refuse. The refusals are the
point: a records-bound settlement that can be steered by the prover is strictly worse than the frozen
scheme it replaces, because the frozen one at least fails closed.

Run: python3 tests/test_records_bound_settle.py
"""
import os
import sys
import time
import tempfile
import logging

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_recsettle_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logging.getLogger("rbs").addHandler(logging.NullHandler())
logger = logging.getLogger("rbs")
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
                            records_bind as RB, records_transition as RT, fri as _fri, stark as _stark)

fails = 0
_t0 = time.time()


def check(name, ok):
    global fails
    print(f"[{time.time()-_t0:6.0f}s] " + ("PASS  " if ok else "FAIL  ") + name, flush=True)
    if not ok:
        fails += 1


def raises(fn):
    """validate_transaction signals rejection by RAISING (bare asserts), never by returning False."""
    try:
        fn()
        return False
    except Exception:
        return True


NS = DEFAULT_NS
BH = 5 * EPOCH_LENGTH
D8 = 8
NQ = 2
CID = "c" * 32
CALLER = "ndo" + "A" * 46
DEPOSITOR = "d" * 46
DEPOSIT = 500_0000                      # raw; a bridge deposit credits T_BRIDGE_BAL[sender] by this

_saved = (_fri.NUM_QUERIES, _stark.NUM_QUERIES, protocol.EXEC_TREE_DEPTH, protocol.EXEC_GENESIS_ROOT,
          protocol.SETTLE_PROOF_TRUSTLESS, protocol.SETTLE_PROOF_RECORDS)
try:
    _fri.NUM_QUERIES = NQ
    _stark.NUM_QUERIES = NQ
    protocol.EXEC_TREE_DEPTH = D8
    protocol.SETTLE_PROOF_RECORDS = True          # the flag under test; rides a reroll in production

    def _fresh_state():
        return ExecState(os.path.join(tempfile.mkdtemp(), "s.json"))

    st0 = _fresh_state()
    COUNTER = {"bump": zkvmasm.assemble(
        "movi r1 0\n sload r2 r1\n movi r3 1\n add r2 r3\n sstore r1 r2\n ret r2")}
    # CID is deployed (empty slots) in the proof's pre-state, so the genesis tip it extends must carry its
    # code leaf — contract CODE is now committed in the KV half (exec_state_bind.code_key), so a deployed
    # contract is no longer invisible until its first slot write. Project the genesis contract set into kv_g8.
    GEN_CONTRACTS = {CID: {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}}
    kv_g8 = SST.SparseStore(D8, SS.sparse_projection(GEN_CONTRACTS, D8)).root()
    rec_g8 = RT.records_store(st0, D8).root()
    rec_hex8 = SST.digest_hex(rec_g8)
    protocol.EXEC_GENESIS_ROOT = ER.full_root_hex(kv_g8, rec_g8)

    print("\nspan: 1 block carrying a contract call (KV half) AND a bridge deposit (RECORDS half)\n")

    # --- 1) quorum-settle genesis (a proof may only EXTEND a committed tip) ------------------------
    V = generate_keys()
    create_account(V["address"], balance=B_MIN, bonded=4 * B_MIN)
    tx0 = construct_settle_tx(V, 0, protocol.EXEC_GENESIS_ROOT, BH, ns=NS)
    check("genesis tip settles by quorum", validate_transaction(tx0, logger, BH))
    reflect_transaction(tx0, logger, block_height=BH)

    # --- 2) a block that moves BOTH halves, and the summary incorporate_block would commit ---------
    H = 1
    BLOCK = {"block_number": H, "block_hash": f"{H:064x}", "block_transactions": [
        {"recipient": "blob", "sender": CALLER,
         "data": {"op": "call", "contract": CID, "method": "bump", "args": [], "ns": NS}},
        {"recipient": "bridge", "sender": DEPOSITOR, "amount": DEPOSIT},
    ]}
    inert, calls_by_ns = CC.block_summary(BLOCK)
    eff, derivable = RB.block_records_effects(BLOCK)
    check("the block is NON-inert (it moves records) yet DERIVABLE", (not inert) and derivable)
    check("the committed effect is the bridge deposit, keyed by the depositor",
          eff == [(ER.T_BRIDGE_BAL, (DEPOSITOR,), DEPOSIT)])
    with kv_ops.write_txn():
        kv_ops.exec_summary_put(H, inert, calls_by_ns, records=eff, derivable=derivable)
    check("the summary now CARRIES the records effects (the old blocker)",
          bool((kv_ops.exec_summary_get(H) or {}).get("rec")))

    # --- 3) the exec node's real post-state, both halves -------------------------------------------
    st = _fresh_state()
    st.contracts[CID] = {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}
    st.cursor = H
    st.block_ts = chain_clock(H)
    st.apply_blob({"op": "call", "contract": CID, "method": "bump", "args": []}, CALLER, "n1")
    st.credit_deposit(DEPOSITOR, DEPOSIT)                     # what execnode's block tail does
    real_root = ER.full_root_hex(SST.SparseStore(D8, SS.sparse_projection(st.contracts, D8)).root(),
                                 RT.records_store(st, D8).root())

    # --- 4) build the proof: KV segments + a bound RECORDS transition ------------------------------
    pre = {CID: {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}}
    calls = CC.block_calls(BLOCK, NS)
    proof = SS.prove_settlement_sparse(pre, calls, cursor=H, rec_hex=rec_hex8, num_queries=NQ, depth=D8)
    rec_tr = RT.prove_records_transition(st0, st, num_queries=NQ, depth=D8)
    proof["records"] = rec_tr
    proof["rec_post"] = SST.digest_hex(tuple(rec_tr["roots"][-1]))
    proof["records_pre"] = ER.records_projection(st0)         # pinned against rec_hex by the verifier
    check("the proof's composed post-root equals the exec node's real root",
          ER.full_root_hex(SST.digest_from_hex(proof["kv_post"]),
                           SST.digest_from_hex(proof["rec_post"])) == real_root)
    check("the records half really MOVED (otherwise this proves nothing)",
          proof["rec_post"] != rec_hex8)

    # --- 5) THE POINT: every end node's rule accepts it, and it becomes canon ----------------------
    V2 = generate_keys()
    create_account(V2["address"], balance=B_MIN, bonded=B_MIN)
    txp = construct_settle_tx(V2, H, real_root, BH, ns=NS, proof=proof)
    check("a span that MOVED records passes the FULL L1 validation", validate_transaction(txp, logger, BH))
    reflect_transaction(txp, logger, block_height=BH)
    protocol.SETTLE_PROOF_TRUSTLESS = True
    check("it is CANON, trustlessly (no bonded quorum)",
          settlement_justified(NS, H, real_root, get_bonded_registry()))
    check("the settled tip advanced", latest_settled(NS) == (H, real_root))

    # --- 6) the refusals ---------------------------------------------------------------------------
    def _fresh_settler():
        k = generate_keys()
        create_account(k["address"], balance=B_MIN, bonded=B_MIN)
        return k

    # (a) a FORGED pre-state. The binding needs each touched record's pre value; if the prover could
    #     supply those freely it would choose the arithmetic, and the settled root with it.
    bad = dict(proof, records_pre={12345: 999})
    check("a records pre-state that does not hash to the committed root is REFUSED",
          raises(lambda: validate_transaction(
              construct_settle_tx(_fresh_settler(), H, real_root, BH, ns=NS, proof=bad), logger, BH)))

    # (b) a records half moved with NO committed effect authorising it.
    with kv_ops.write_txn():
        kv_ops.exec_summary_put(H, inert, calls_by_ns, records=[], derivable=True)
    check("moving the records half with an EMPTY committed effect set is REFUSED",
          raises(lambda: validate_transaction(
              construct_settle_tx(_fresh_settler(), H, real_root, BH, ns=NS, proof=proof), logger, BH)))

    # (c) effects that disagree with the proven transition (here: twice the real deposit).
    with kv_ops.write_txn():
        kv_ops.exec_summary_put(H, inert, calls_by_ns,
                                records=[(ER.T_BRIDGE_BAL, (DEPOSITOR,), DEPOSIT * 2)], derivable=True)
    check("committed effects that disagree with the proven transition are REFUSED",
          raises(lambda: validate_transaction(
              construct_settle_tx(_fresh_settler(), H, real_root, BH, ns=NS, proof=proof), logger, BH)))

    # (d) a block whose records movement this node CANNOT derive must fall back to quorum, even though
    #     the proof itself is fine. derivable=False is recorded explicitly for exactly this.
    with kv_ops.write_txn():
        kv_ops.exec_summary_put(H, inert, calls_by_ns, records=None, derivable=False)
    check("a NON-DERIVABLE records movement refuses the proof path (quorum only)",
          raises(lambda: validate_transaction(
              construct_settle_tx(_fresh_settler(), H, real_root, BH, ns=NS, proof=proof), logger, BH)))

    # (e) and a value>0 call is one of those WHEN value-call escrow is not being derived: its escrow is
    #     refunded on revert, so absent that flag the net effect is not a function of the calldata. Gen 17
    #     (SETTLE_PROOF_RECORDS_VALUE_CALLS) flipped the default to derive it ("the proof is the verdict"), so
    #     this sub-case pins the flag OFF to keep exercising the non-derivable fallback it is about.
    vblock = {"block_number": 2, "block_hash": "02" * 32, "block_transactions": [
        {"recipient": "blob", "sender": CALLER,
         "data": {"op": "call", "contract": CID, "method": "bump", "args": [], "value": 5, "ns": NS}}]}
    _saved_vc = protocol.SETTLE_PROOF_RECORDS_VALUE_CALLS
    try:
        protocol.SETTLE_PROOF_RECORDS_VALUE_CALLS = False
        _e2, _d2 = RB.block_records_effects(vblock)
    finally:
        protocol.SETTLE_PROOF_RECORDS_VALUE_CALLS = _saved_vc
    check("a value>0 call is correctly marked NON-derivable (value-call escrow off)", _d2 is False and _e2 is None)
finally:
    (_fri.NUM_QUERIES, _stark.NUM_QUERIES, protocol.EXEC_TREE_DEPTH, protocol.EXEC_GENESIS_ROOT,
     protocol.SETTLE_PROOF_TRUSTLESS, protocol.SETTLE_PROOF_RECORDS) = _saved

print()
print("ALL PASS — a span that moved records settles by proof, and cannot be steered by the prover"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
