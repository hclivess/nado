"""ASSET SETTLEMENT, END TO END THROUGH L1 — a span running the asset instructions passes validate_transaction (the rule
every node runs) and becomes canon; whenever the prover steers it, it is refused (zk audit 2026-09-26; gen 27's
ZK_HARDEN_HEIGHT, 1 from gen 28 and deleted — the rule is unconditional).

tests/test_asset_ops_settle_by_proof.py pins the derivation (records_bind.PinnedAssets) against the real exec layer.
This one pins the WIRING in the settle branch of ops/transaction_ops.py: settle_proof_io_check admits asset io; the
asset ledger is pinned from `records_pre` against the tip's records root; the moves derived from the
proven io join the records binding of a records-bound proof; a records-FROZEN proof (a span that only reads balances)
passes only if its asset io nets to nothing; and a forged or missing metadata preimage or pre-state refuses the tx.

Run: python3 tests/test_asset_settle_l1.py
"""
import os
import sys
import copy
import time
import tempfile
import logging

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_assetsettle_")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_TESTNET"] = "1"
# NUM_QUERIES is lowered IN-PROCESS; the settle branch otherwise verifies in a child interpreter at protocol strength.
os.environ["NADO_PROOF_VERIFY_INPROC"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logging.getLogger("asl1").addHandler(logging.NullHandler())
logger = logging.getLogger("asl1")
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
from execnode.state import ExecState, asset_id
from execnode.stark import (storage_tree as SST, settlement_sparse as SS, calls_commit as CC,
                            records_bind as RB, records_transition as RT, fri as _fri, stark as _stark)

fails = 0
_t0 = time.time()


def check(name, ok):
    global fails
    print(f"[{time.time()-_t0:6.0f}s] " + ("PASS  " if ok else "FAIL  ") + name, flush=True)
    if not ok:
        fails += 1


def accepts(fn):
    """A positive validation that reports WHY it failed instead of crashing the run."""
    try:
        return bool(fn())
    except Exception as e:
        print(f"         refused: {type(e).__name__}: {str(e)[:200]}")
        return False


def raises(fn, why):
    """validate_transaction signals rejection by RAISING (bare asserts), never by returning False. A refusal counts
    only for the RIGHT reason — `why` must appear in it — or a proof broken some other way would pass the check."""
    try:
        fn()
        return False
    except Exception as e:
        if why not in str(e):
            print(f"         refused for another reason: {type(e).__name__}: {str(e)[:200]}")
        return why in str(e)


NS = DEFAULT_NS
BH = 5 * EPOCH_LENGTH
D8, NQ = 8, 2
CID = "c" * 32
CALLER = "ndo" + "A" * 46
C = "ndo" + "C" * 46
ARGS = "movi r0 0\n arg r1 r0\n movi r0 1\n arg r2 r0\n movi r0 2\n arg r3 r0\n"
TOKEN = {"pay": zkvmasm.assemble(ARGS + " apay r1 r2 r3\n ret r3"),
         "mint": zkvmasm.assemble(ARGS + " amint r1 r2 r3\n ret r3"),
         "burn": zkvmasm.assemble("movi r0 0\n arg r1 r0\n movi r0 1\n arg r3 r0\n aburn r1 r3\n ret r3"),
         "bal": zkvmasm.assemble("movi r0 0\n arg r1 r0\n abal r4 r1\n movi r5 1\n sstore r5 r4\n ret r4"),
         "seal": zkvmasm.assemble("movi r0 0\n arg r1 r0\n arenounce r1\n movi r2 1\n ret r2"),
         # receives an asset-denominated call value (a method must read ACTX to be sent one)
         "deposit": zkvmasm.assemble("actx r1 asset\n ctx r2 value\n movi r3 2\n sstore r3 r2\n ret r2")}
AID = str(asset_id(CID, 1))
META = {"issuer": CID, "seed": 1, "name": "Token", "sym": "TOK", "dec": 0, "supply": 100, "mintable": True, "uri": ""}

_saved = (_fri.NUM_QUERIES, _stark.NUM_QUERIES, protocol.EXEC_TREE_DEPTH, protocol.EXEC_GENESIS_ROOT,
          protocol.SETTLE_PROOF_TRUSTLESS, protocol.SETTLE_PROOF_RECORDS)
try:
    _fri.NUM_QUERIES = NQ
    _stark.NUM_QUERIES = NQ
    protocol.EXEC_TREE_DEPTH = D8
    protocol.SETTLE_PROOF_RECORDS = True

    def _state(contracts, abal, assets, cursor):
        s = ExecState(os.path.join(tempfile.mkdtemp(), "s.json"))
        s.contracts, s.abal, s.assets = copy.deepcopy(contracts), copy.deepcopy(abal), copy.deepcopy(assets)
        s.cursor, s.block_ts = cursor, chain_clock(max(cursor, 0))
        return s

    GEN = {CID: {"code": TOKEN, "storage": {"slots": {}}, "runtime": "zkvm"}}
    st0 = _state(GEN, {AID: {CID: 100}}, {AID: META}, 0)
    kv_g = SST.SparseStore(D8, SS.sparse_projection(GEN, D8, v2=True)).root()
    rec_g = RT.records_store(st0, D8).root()
    protocol.EXEC_GENESIS_ROOT = ER.full_root_hex(kv_g, rec_g)

    V = generate_keys()
    create_account(V["address"], balance=B_MIN, bonded=4 * B_MIN)
    tx0 = construct_settle_tx(V, 0, protocol.EXEC_GENESIS_ROOT, BH, ns=NS)
    check("genesis tip (a contract issuing TOK, holding 100) settles by quorum", accepts(lambda: validate_transaction(tx0, logger, BH)))
    reflect_transaction(tx0, logger, block_height=BH)

    def _settler():
        k = generate_keys()
        create_account(k["address"], balance=B_MIN, bonded=B_MIN)
        return k

    def _call(m, args):
        return {"recipient": "blob", "sender": CALLER, "data": {"op": "call", "contract": CID, "method": m,
                                                                  "args": args, "ns": NS}}

    # --- span 1: every asset op; the records half moves -------------------------------------------------
    H = 1
    BLOCK = {"block_number": H, "block_hash": f"{H:064x}", "block_transactions": [
        _call("bal", [int(AID)]), _call("pay", [int(AID), C, 10]), _call("mint", [int(AID), C, 5]),
        _call("burn", [int(AID), 3]), _call("bal", [int(AID)]), _call("seal", [int(AID)])]}
    inert, calls_by_ns = CC.block_summary(BLOCK)
    eff, derivable = RB.block_records_effects(BLOCK)
    with kv_ops.write_txn():
        kv_ops.exec_summary_put(H, inert, calls_by_ns, records=eff, derivable=derivable)
    st1 = _state(GEN, st0.abal, st0.assets, H)
    for i, t in enumerate(BLOCK["block_transactions"]):
        st1.apply_blob(dict(t["data"]), CALLER, f"n{i}")
    check("the exec layer applied all five asset ops",
          st1.abal[AID] == {CID: 87, C: 15} and st1.assets[AID]["supply"] == 102 and not st1.assets[AID]["mintable"])
    root1 = ER.full_root_hex(SST.SparseStore(D8, SS.sparse_projection(st1.contracts, D8, v2=True)).root(),
                             RT.records_store(st1, D8).root())
    calls = CC.block_calls(BLOCK, NS)

    def _proof(pre_st, post_st, calls, cursor, bound):
        rec = SST.digest_hex(RT.records_store(pre_st, D8).root())
        with SS.stark.rules_at(BH):
            p = SS.prove_settlement_sparse(copy.deepcopy(pre_st.contracts), calls, cursor=cursor, rec_hex=rec,
                                           num_queries=NQ, depth=D8, pre_abal=copy.deepcopy(pre_st.abal),
                                           pre_assets=copy.deepcopy(pre_st.assets))
        if bound:
            tr = RT.prove_records_transition(pre_st, post_st, num_queries=NQ, depth=D8)
            p["records"], p["rec_post"] = tr, SST.digest_hex(tuple(tr["roots"][-1]))
        p["records_pre"] = ER.records_projection(pre_st)
        p["asset_meta_pre"] = {a: pre_st.assets[a] for a in RB.proof_asset_ids(p)[1] if a in pre_st.assets}
        return p

    proof = _proof(st0, st1, calls, H, True)
    check("the proof's composed post-root equals the exec node's real root",
          ER.full_root_hex(SST.digest_from_hex(proof["kv_post"]), SST.digest_from_hex(proof["rec_post"])) == root1)

    bad = copy.deepcopy(proof); bad["asset_meta_pre"][AID]["supply"] = 10 ** 9
    check("a forged metadata preimage (supply) is REFUSED",
          raises(lambda: validate_transaction(construct_settle_tx(_settler(), H, root1, BH, ns=NS, proof=bad), logger, BH),
                 "not in the committed records"))
    bad = copy.deepcopy(proof); bad.pop("asset_meta_pre")
    check("a missing metadata preimage is REFUSED",
          raises(lambda: validate_transaction(construct_settle_tx(_settler(), H, root1, BH, ns=NS, proof=bad), logger, BH),
                 "no such asset"))
    bad = copy.deepcopy(proof); bad["records_pre"] = {12345: 999}
    check("a records pre-state that does not hash to the tip's records root is REFUSED",
          raises(lambda: validate_transaction(construct_settle_tx(_settler(), H, root1, BH, ns=NS, proof=bad), logger, BH),
                 "does not hash to the committed records root"))

    V2 = _settler()
    txp = construct_settle_tx(V2, H, root1, BH, ns=NS, proof=proof)
    check("the asset span passes the FULL L1 validation", accepts(lambda: validate_transaction(txp, logger, BH)))
    reflect_transaction(txp, logger, block_height=BH)
    protocol.SETTLE_PROOF_TRUSTLESS = True
    check("...and it is CANON, trustlessly", settlement_justified(NS, H, root1, get_bonded_registry()))
    check("the settled tip advanced", latest_settled(NS) == (H, root1))

    # --- span 2: a balance read only; the records half does not move (a FROZEN proof) ---------------------
    H2 = 2
    BLOCK2 = {"block_number": H2, "block_hash": f"{H2:064x}", "block_transactions": [_call("bal", [int(AID)])]}
    inert2, cbn2 = CC.block_summary(BLOCK2)
    eff2, der2 = RB.block_records_effects(BLOCK2)
    with kv_ops.write_txn():
        kv_ops.exec_summary_put(H2, inert2, cbn2, records=eff2, derivable=der2)
    st2 = _state(st1.contracts, st1.abal, st1.assets, H2)
    st2.apply_blob(dict(BLOCK2["block_transactions"][0]["data"]), CALLER, "m0")
    root2 = ER.full_root_hex(SST.SparseStore(D8, SS.sparse_projection(st2.contracts, D8, v2=True)).root(),
                             RT.records_store(st2, D8).root())
    p2 = _proof(st1, st2, CC.block_calls(BLOCK2, NS), H2, False)
    check("the balance-only proof is records-frozen", "records" not in p2 and p2["rec"] == SST.digest_hex(RT.records_store(st2, D8).root()))
    bad = copy.deepcopy(p2); bad.pop("records_pre")
    check("a frozen proof with asset io but no pinned pre-state is REFUSED",
          raises(lambda: validate_transaction(construct_settle_tx(_settler(), H2, root2, BH, ns=NS, proof=bad), logger, BH),
                 "asset io without a pinned pre-state"))
    tx2 = construct_settle_tx(_settler(), H2, root2, BH, ns=NS, proof=p2)
    check("a frozen proof whose asset io nets to nothing passes the FULL L1 validation",
          accepts(lambda: validate_transaction(tx2, logger, BH)))
    reflect_transaction(tx2, logger, block_height=BH)

    # --- span 3: an ASSET-VALUED call (C sends 4 TOK into the contract), then an ABAL that must see it ---------
    # The escrow is calldata, committed into the exec summary by block_records_effects.
    H3 = 3
    dep = {"recipient": "blob", "sender": C, "data": {"op": "call", "contract": CID, "method": "deposit", "args": [],
                                                       "value": 4, "asset": AID, "ns": NS}}
    BLOCK3 = {"block_number": H3, "block_hash": f"{H3:064x}", "block_transactions": [dep, _call("bal", [int(AID)])]}
    inert3, cbn3 = CC.block_summary(BLOCK3)
    eff3, der3 = RB.block_records_effects(BLOCK3)
    check("the asset call value is a DERIVABLE records effect: 4 TOK from C to the contract",
          der3 is True and sorted(eff3) == sorted([(ER.T_ASSET_BAL, (AID, C), -4), (ER.T_ASSET_BAL, (AID, CID), 4)]))
    with kv_ops.write_txn():
        kv_ops.exec_summary_put(H3, inert3, cbn3, records=eff3, derivable=der3)
    st3 = _state(st2.contracts, st2.abal, st2.assets, H3)
    st3.apply_blob(dict(dep["data"]), C, "q0")
    st3.apply_blob(dict(BLOCK3["block_transactions"][1]["data"]), CALLER, "q1")
    check("the exec layer escrowed it and the contract's ABAL saw 91",
          st3.abal[AID] == {CID: 91, C: 11} and st3.contracts[CID]["storage"]["slots"].get("1") == 91
          and st3.contracts[CID]["storage"]["slots"].get("2") == 4)
    root3 = ER.full_root_hex(SST.SparseStore(D8, SS.sparse_projection(st3.contracts, D8, v2=True)).root(),
                             RT.records_store(st3, D8).root())
    p3 = _proof(st2, st3, CC.block_calls(BLOCK3, NS), H3, True)
    check("the asset-valued call's proof names its asset", RB.proof_asset_ids(p3) == (True, {AID}))
    bad = copy.deepcopy(p3); bad["asset_meta_pre"] = {}
    check("an asset-valued call with no metadata preimage is REFUSED",
          raises(lambda: validate_transaction(construct_settle_tx(_settler(), H3, root3, BH, ns=NS, proof=bad), logger, BH),
                 "names no known asset"))
    tx3 = construct_settle_tx(_settler(), H3, root3, BH, ns=NS, proof=p3)
    check("a span with an asset-valued call passes the FULL L1 validation", accepts(lambda: validate_transaction(tx3, logger, BH)))
    reflect_transaction(tx3, logger, block_height=BH)
    check("...and it is CANON on the exec node's real root", latest_settled(NS) == (H3, root3))

    # for a spelling the live apply would not resolve, the block stays non-derivable (quorum)
    odd = copy.deepcopy(BLOCK3); odd["block_transactions"][0]["data"]["asset"] = "0" + AID
    check("a non-canonical asset spelling (live resolves no asset) is non-derivable",
          RB.block_records_effects(odd) == (None, False))
    shadow = RB.PinnedAssets(lambda t, p: 0, {})
    check("an escrow of an asset the proof does not authenticate is refused",
          raises(lambda: shadow.escrow(C, CID, AID, 4), "names no known asset"))
finally:
    (_fri.NUM_QUERIES, _stark.NUM_QUERIES, protocol.EXEC_TREE_DEPTH, protocol.EXEC_GENESIS_ROOT,
     protocol.SETTLE_PROOF_TRUSTLESS, protocol.SETTLE_PROOF_RECORDS) = _saved

print()
print("ALL PASS — asset instructions settle by proof through L1, and cannot be steered"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
