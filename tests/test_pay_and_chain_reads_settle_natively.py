"""PAY, BHASH and BEACON settle by proof on the SHIPPED path, records-bound, landing on the exec node's real root
(settlement_sparse.prove_settlement_sparse on the native arena + records_transition, verified as L1 does).

tests/test_every_opcode_settles_natively.py proves 53 opcodes through the KV half; these three need the rest of a
real settle: PAY moves records (a call escrows value, the contract pays it out, so the records half MOVES and the
proof must be records-bound, with the payout derived from the proof's own io — records_bind.pay_effects_from_proof),
and BHASH/BEACON are chain reads L1 binds to the finalized chain (settlement_sparse.chain_reads). Pins, native kernels
only, under the zk_harden rules: the span proves; the KV half verifies with L1's verify_settlement_sparse; the payout
the proof implies, plus the effects the chain committed for the block, bind the proven records transition
(bind_and_verify_records over a pinned pre-state); the chain reads carry exactly the exec layer's block hash and
beacon; and the composed root equals the exec node's real post-state root.

Run: python3 tests/test_pay_and_chain_reads_settle_natively.py            (native kernels required)
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-paysettle-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
os.environ.pop("NADO_ALLOW_PYTHON_KERNELS", None)         # the SHIPPED path
import sys, copy, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.environ["HOME"])
from execnode import zkvm, zkvmasm, exec_root as ER
from execnode.code_codec import contract_id
from execnode.state import ExecState
from execnode.execnode import _apply_block
from execnode.stark import (settlement_sparse as SS, calls_commit as CC, stark, storage_tree as ST,
                            records_transition as RT, records_bind as RB, field as F)

NQ, D = 16, 16
E0 = 4999                                 # the epoch whose beacon the contract reads (available from its first block)
H = (E0 + 1) * 60 + 5
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


A = "ndoAAAA" + "A" * 41; B = "ndoBBBB" + "B" * 41; C = "ndoCCCC" + "C" * 41
blk = lambda h, txs: {"block_number": h, "block_hash": "%064x" % (h * 7919), "block_timestamp": 0, "block_transactions": txs}
tx = lambda s, d, t: {"recipient": "blob", "sender": s, "txid": t, "data": dict(d)}
PAYC = {"go": zkvmasm.assemble("movi r3 0\n arg r1 r3\n ctx r2 value\n pay r1 r2\n ret r2")}   # pays args[0] the escrow
READS = {"go": zkvmasm.assemble(f"movi r1 {H - 1}\n bhash r2 r1\n movi r3 {E0}\n beacon r4 r3\n"
                                f" movi r5 1\n sstore r5 r2\n movi r5 2\n sstore r5 r4\n ret r2")}
cp, cr = contract_id(A, PAYC, "p"), contract_id(A, READS, "r")

st = ExecState(os.path.join(os.environ["HOME"], "chain.json"))
loop = asyncio.new_event_loop()
run = lambda b: loop.run_until_complete(_apply_block(None, {"default": st}, st, b, verbose=bool(os.environ.get("VERBOSE"))))
# the beacon epoch carries a RANDAO reveal: from protocol.BEACON_EXTEND_HEIGHT an epoch with none waits for a later
# epoch's reveals (ExecState.exec_beacon_at), and this test is about PAY and the chain reads, not about empty epochs
st.record_reveal(E0, "pay-and-chain-reads-reveal")
for _e in (E0 - 2, E0 - 1, E0):                  # witness whole epochs first: a node that starts mid-flight marks
    run(blk(_e * 60, []))                          # earlier beacons unavailable (ExecState.advance_beacons, beacon_floor)
run(blk(H - 2, [{"recipient": "bridge", "sender": B, "txid": "dep", "amount": 1000, "data": {}}]))
run(blk(H - 1, [tx(A, {"op": "deploy", "code": PAYC, "nonce": "p"}, "d1"),
                tx(A, {"op": "deploy", "code": READS, "nonce": "r"}, "d2")]))
st0 = st.clone()
BLOCK = blk(H, [tx(B, {"op": "call", "contract": cp, "method": "go", "args": [C], "value": 10}, "c1"),
                tx(B, {"op": "call", "contract": cr, "method": "go", "args": []}, "c2")])
run(BLOCK)
slots = st.contracts[cr]["storage"]["slots"]
check("the exec layer ran the PAY call (B escrows 10, the contract pays C) and both chain reads",
      st.bridge.get(B) == 990 and st.bridge.get(C) == 10 and str(1) in slots and str(2) in slots, (st.bridge, slots))
real_root = ER.full_root_hex(ST.SparseStore(D, SS.sparse_projection(st.contracts, D, v2=True)).root(),
                             RT.records_store(st, D).root())
rec_hex = ST.digest_hex(RT.records_store(st0, D).root())

with stark.with_rules(stark.RULES_STRICT):
    try:
        proof = SS.prove_settlement_sparse(copy.deepcopy(st0.contracts), CC.block_calls(BLOCK), cursor=H, rec_hex=rec_hex,
                                           beacons=dict(st0.beacons), block_hashes=dict(st0.block_hashes),
                                           pre_bridge=dict(st0.bridge), num_queries=NQ, depth=D)
        rec_tr = RT.prove_records_transition(st0, st, num_queries=NQ, depth=D)
        proof["records"], proof["rec_post"] = rec_tr, ST.digest_hex(tuple(rec_tr["roots"][-1]))
        proof["records_pre"] = ER.records_projection(st0)
        built = True
    except Exception as e:
        built = False
        check("the records-bound span proves natively", False, f"{type(e).__name__}: {str(e)[:200]}")
    if built:
        r = SS.verify_settlement_sparse(proof, num_queries=NQ, depth=D)
        check("the KV half verifies with L1's verify_settlement_sparse", r[0] is True, r[1])
        committed, derivable = RB.block_records_effects(BLOCK)
        pay = RB.pay_effects_from_proof(proof)
        check("the proof implies the payout: 10 out of the contract's escrow, 10 to C",
              sorted((p[1][0], p[2]) for p in pay) == sorted([(cp, -10), (C, 10)]), pay)
        eff = [(int(t), tuple(str(p) for p in parts), int(dv)) for (t, parts, dv) in list(committed) + list(pay)]
        pre_rec, post_rec = ST.digest_from_hex(rec_hex), ST.digest_from_hex(proof["rec_post"])
        ok, why = RB.bind_and_verify_records(proof["records"], pre_rec, post_rec,
                                             RB.pinned_pre_get(proof["records_pre"], pre_rec, depth=D), eff, depth=D, num_queries=NQ,
                                             nonneg=True)
        check("committed effects + the proven payout bind the records transition (L1's check)", ok is True, why)
        reads = SS.chain_reads(proof)
        want = [(zkvm.IO_BHASH, H - 1, int(st0.block_hashes[H - 1]) % F.P), (zkvm.IO_BEACON, E0, int(st0.beacons[E0]) % F.P)]
        check("the proof's chain reads are exactly the exec layer's block hash and beacon",
              sorted(map(tuple, reads)) == sorted(want), (reads, want))
        check("the composed root equals the exec node's real post-state root",
              ER.full_root_hex(ST.digest_from_hex(r[3]), post_rec) == real_root)
        check("the records half really moved", proof["rec_post"] != rec_hex)
print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
