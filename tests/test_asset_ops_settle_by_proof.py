"""The asset instructions settle by proof on the SHIPPED path — ASEL+PAY, ASEL+AMINT, ABURN, ABAL and ARENOUNCE —
records-bound, landing on the exec node's real root (zk audit 2026-09-26; gen 27's ZK_HARDEN_HEIGHT, 1 from gen 28
and deleted — the rule is unconditional).

Before it every settle proof refused asset io (review 2026-09-24): an asset op moves the asset ledger, which lives in
the RECORDS half, and an ABAL read came from the io log with nothing tying it to that ledger. So a span that touched an
asset could only ever settle by quorum. records_bind.PinnedAssets now re-derives each move from the proven io against
the pinned pre-state, with the live staging rules (state.stage_asset_effects_pure): issuer-only mint/renounce, the
supply cap, holdings, and every ABAL read against the running authenticated balance; the metadata leaf, positioned by a
digest of the metadata, is retired and re-placed when supply or mintability changes.

Pins, native kernels only, under the zk_harden rules:
  * a span running all five asset ops proves natively; its KV half verifies with L1's verify_settlement_sparse;
  * L1's derivation (PinnedAssets over records_pre + asset_meta_pre) and the prover's dry-run
    (settlement_proofs.span_payout_effects) produce the SAME effects, and they bind the proven records transition;
  * the composed root equals the exec node's real post-state root;
  * a forged or omitted metadata preimage, a tampered ABAL read, a tampered records_pre and a missing asset view are
    all refused;
  * a records-FROZEN span that only reads a balance proves too, and its asset io nets to nothing;
  * settle_proof_io_check admits asset io in a records-bound proof at every height.

Run: python3 tests/test_asset_ops_settle_by_proof.py            (native kernels required)
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-assetsettle-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
os.environ.pop("NADO_ALLOW_PYTHON_KERNELS", None)         # the SHIPPED path
import sys, copy, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.environ["HOME"])
from execnode import zkvm, zkvmasm, exec_root as ER, settlement_proofs as SP
from execnode.code_codec import contract_id
from execnode.state import ExecState, asset_id
from execnode.execnode import _apply_block
from execnode.stark import (settlement_sparse as SS, calls_commit as CC, stark, storage_tree as ST,
                            records_transition as RT, records_bind as RB)
from ops.transaction_ops import settle_proof_io_check

NQ, D = 16, 16
H = 7000
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def refused(fn):
    try:
        fn()
        return False
    except RB.Unbindable:
        return True


A = "ndoAAAA" + "A" * 41; C = "ndoCCCC" + "C" * 41
blk = lambda h, txs: {"block_number": h, "block_hash": "%064x" % (h * 7919), "block_timestamp": 0, "block_transactions": txs}
tx = lambda s, d, t: {"recipient": "blob", "sender": s, "txid": t, "data": dict(d)}
ARGS = "movi r0 0\n arg r1 r0\n movi r0 1\n arg r2 r0\n movi r0 2\n arg r3 r0\n"          # r1 asset, r2 to, r3 amount
TOKEN = {"pay": zkvmasm.assemble(ARGS + " apay r1 r2 r3\n ret r3"),
         "mint": zkvmasm.assemble(ARGS + " amint r1 r2 r3\n ret r3"),
         "burn": zkvmasm.assemble("movi r0 0\n arg r1 r0\n movi r0 1\n arg r3 r0\n aburn r1 r3\n ret r3"),
         "bal": zkvmasm.assemble("movi r0 0\n arg r1 r0\n abal r4 r1\n movi r5 1\n sstore r5 r4\n ret r4"),
         "seal": zkvmasm.assemble("movi r0 0\n arg r1 r0\n arenounce r1\n movi r2 1\n ret r2")}
cx = contract_id(A, TOKEN, "t")
aid = int(asset_id(cx, 1))

st = ExecState(os.path.join(os.environ["HOME"], "chain.json"))
loop = asyncio.new_event_loop()
run = lambda b: loop.run_until_complete(_apply_block(None, {"default": st}, st, b, verbose=bool(os.environ.get("VERBOSE"))))
run(blk(H - 2, [tx(A, {"op": "deploy", "code": TOKEN, "nonce": "t"}, "d1")]))
run(blk(H - 1, [tx(A, {"op": "asset_create", "for": cx, "seed": 1, "name": "Token", "sym": "TOK", "dec": 0,
                       "supply": 100, "mintable": True}, "a1")]))
check("the contract issued its asset and holds the supply", st.abal.get(str(aid), {}).get(cx) == 100, st.abal)
st0 = st.clone()
call = lambda m, args, t: tx(A, {"op": "call", "contract": cx, "method": m, "args": args}, t)
BLOCK = blk(H, [call("bal", [aid], "c1"),                   # ABAL reads 100
                call("pay", [aid, C, 10], "c2"),            # ASEL + PAY: 10 to C
                call("mint", [aid, C, 5], "c3"),            # ASEL + AMINT: 5 more to C (issuer = the contract)
                call("burn", [aid, 3], "c4"),               # ABURN 3 from the contract
                call("bal", [aid], "c5"),                   # ABAL reads 87
                call("seal", [aid], "c6")])                 # ARENOUNCE: minting sealed
run(BLOCK)
meta = st.assets[str(aid)]
check("the exec layer ran all five asset ops (holdings, supply, the seal, both reads)",
      st.abal[str(aid)] == {cx: 87, C: 15} and meta["supply"] == 102 and meta["mintable"] is False
      and st.contracts[cx]["storage"]["slots"].get("1") == 87, (st.abal, meta, st.contracts[cx]["storage"]))
real_root = ER.full_root_hex(ST.SparseStore(D, SS.sparse_projection(st.contracts, D, v2=True)).root(),
                             RT.records_store(st, D).root())
rec_hex = ST.digest_hex(RT.records_store(st0, D).root())
pre_rec = ST.digest_from_hex(rec_hex)
calls = CC.block_calls(BLOCK)

with stark.with_rules(stark.RULES_STRICT):
    try:
        proof = SS.prove_settlement_sparse(copy.deepcopy(st0.contracts), calls, cursor=H, rec_hex=rec_hex,
                                           beacons=dict(st0.beacons), block_hashes=dict(st0.block_hashes),
                                           pre_bridge=dict(st0.bridge), pre_abal=copy.deepcopy(st0.abal),
                                           pre_assets=copy.deepcopy(st0.assets), num_queries=NQ, depth=D)
        rec_tr = RT.prove_records_transition(st0, st, num_queries=NQ, depth=D)
        proof["records"], proof["rec_post"] = rec_tr, ST.digest_hex(tuple(rec_tr["roots"][-1]))
        proof["records_pre"] = ER.records_projection(st0)
        has_aio, aids = RB.proof_asset_ids(proof)
        proof["asset_meta_pre"] = {a: st0.assets[a] for a in aids if a in st0.assets}
        built = True
    except Exception as e:
        built = False
        check("the asset span proves natively", False, f"{type(e).__name__}: {str(e)[:300]}")
    if built:
        check("the proof's io names the asset", has_aio and aids == {str(aid)}, (has_aio, aids))
        r = SS.verify_settlement_sparse(proof, num_queries=NQ, depth=D)
        check("the KV half verifies with L1's verify_settlement_sparse", r[0] is True, r[1])
        pin = RB.pinned_pre_get(proof["records_pre"], pre_rec, depth=D)
        view = lambda meta_pre=None: RB.PinnedAssets(pin, proof["asset_meta_pre"] if meta_pre is None else meta_pre)
        try:
            derived = RB.pay_effects_from_proof(proof, view())
        except RB.Unbindable as e:
            derived = None
            check("L1 derives the honest span's asset moves", False, str(e))
        dry = SP.span_payout_effects(copy.deepcopy(st0.contracts), calls, cursor=H, beacons=dict(st0.beacons),
                                     block_hashes=dict(st0.block_hashes), pre_bridge=dict(st0.bridge),
                                     pre_abal=copy.deepcopy(st0.abal), pre_assets=copy.deepcopy(st0.assets))
        check("L1's derivation and the prover's dry-run produce the same effects", derived == dry, (derived, dry))
        net = {}
        for t, parts, dv in derived:
            if t == ER.T_ASSET_BAL:
                net[parts[1]] = net.get(parts[1], 0) + dv
        check("the derived balance moves are the contract -13 and C +15", net == {cx: -13, C: 15}, net)
        committed, derivable = RB.block_records_effects(BLOCK)
        eff = [(int(t), tuple(str(p) for p in parts), int(dv)) for (t, parts, dv) in list(committed) + list(derived)]
        post_rec = ST.digest_from_hex(proof["rec_post"])
        ok, why = RB.bind_and_verify_records(proof["records"], pre_rec, post_rec, pin, eff, depth=D, num_queries=NQ,
                                             nonneg=True)
        check("the derived asset moves bind the proven records transition (L1's check)", ok is True, why)
        check("the composed root equals the exec node's real post-state root",
              ER.full_root_hex(ST.digest_from_hex(r[3]), post_rec) == real_root)

        # --- what L1 refuses ---
        check("without a pinned asset view (the pre-gate derivation) the asset io is unbindable",
              refused(lambda: RB.pay_effects_from_proof(proof)))
        forged = copy.deepcopy(proof["asset_meta_pre"]); forged[str(aid)]["supply"] += 1000
        check("a forged metadata preimage (inflated supply) is refused: its leaf is not in the committed records",
              refused(lambda: RB.pay_effects_from_proof(proof, view(forged))))
        forged = copy.deepcopy(proof["asset_meta_pre"]); forged[str(aid)]["issuer"] = C
        check("a forged metadata preimage (another issuer) is refused",
              refused(lambda: RB.pay_effects_from_proof(proof, view(forged))))
        check("an omitted metadata preimage leaves the asset unknown and the span unbindable",
              refused(lambda: RB.pay_effects_from_proof(proof, view({}))))
        bad = copy.deepcopy(proof)
        for seg in bad["segments"]:
            for e in seg["io"]:
                if e[0] == zkvm.IO_ABAL:
                    e[2] = int(e[2]) + 1                 # a balance read the ledger does not support
                    break
        check("an ABAL read that disagrees with the pinned ledger is refused",
              refused(lambda: RB.pay_effects_from_proof(bad, view())))
        tampered = dict(proof["records_pre"]); k0 = next(iter(tampered)); tampered[k0] = int(tampered[k0]) + 1
        check("a records_pre that does not hash to the tip's records root is refused",
              refused(lambda: RB.pinned_pre_get(tampered, pre_rec, depth=D)))

        # --- the io gate ---
        def io_ok(bound, h):
            try:
                settle_proof_io_check(proof, bound, h)
                return True
            except AssertionError:
                return False
        check("a records-bound proof may carry asset io", io_ok(True, 1) and io_ok(True, 5000))
        check("height 0 keeps the verdict it always had", io_ok(True, 0))

    # --- a records-FROZEN span: only a balance read ---
    st1 = st.clone()
    BLOCK2 = blk(H + 1, [call("bal", [aid], "c7")])
    run(BLOCK2)
    check("a balance-only span leaves the records half where it was",
          ST.digest_hex(RT.records_store(st, D).root()) == ST.digest_hex(RT.records_store(st1, D).root()))
    rec1 = ST.digest_hex(RT.records_store(st1, D).root())
    try:
        p2 = SS.prove_settlement_sparse(copy.deepcopy(st1.contracts), CC.block_calls(BLOCK2), cursor=H + 1, rec_hex=rec1,
                                        beacons=dict(st1.beacons), block_hashes=dict(st1.block_hashes),
                                        pre_bridge=dict(st1.bridge), pre_abal=copy.deepcopy(st1.abal),
                                        pre_assets=copy.deepcopy(st1.assets), num_queries=NQ, depth=D)
        p2["records_pre"] = ER.records_projection(st1)
        p2["asset_meta_pre"] = {a: st1.assets[a] for a in RB.proof_asset_ids(p2)[1] if a in st1.assets}
        r2 = SS.verify_settlement_sparse(p2, num_queries=NQ, depth=D)
        check("the balance-only span proves and verifies records-frozen", r2[0] is True, r2[1])
        pin1 = RB.pinned_pre_get(p2["records_pre"], ST.digest_from_hex(rec1), depth=D)
        fx = RB.pay_effects_from_proof(p2, RB.PinnedAssets(pin1, p2["asset_meta_pre"]))
        check("its asset io nets to nothing, so a frozen proof may carry it",
              RB.net_records_updates(pin1, fx, D, nonneg=True) == [], fx)
        check("while the moving span's asset io does NOT net to nothing (a frozen proof of it is refused)",
              built and RB.net_records_updates(pin, derived, D, nonneg=True) != [])
    except Exception as e:
        check("the balance-only span proves natively", False, f"{type(e).__name__}: {str(e)[:300]}")

    # --- per-block segments: the asset ledger must carry from one block's segment to the next ---
    # The recursive prover used to hand every segment a fresh `{}` asset ledger; block H+1's ABAL reads what
    # block H left (87), so a two-block span proves only if the ledger is threaded across segments.
    try:
        p3 = SS.prove_settlement_sparse(copy.deepcopy(st0.contracts), calls + CC.block_calls(BLOCK2), cursor=H + 1,
                                        rec_hex=rec_hex, beacons=dict(st0.beacons), block_hashes=dict(st0.block_hashes),
                                        pre_bridge=dict(st0.bridge), pre_abal=copy.deepcopy(st0.abal),
                                        pre_assets=copy.deepcopy(st0.assets), num_queries=NQ, depth=D,
                                        recursive=True, fold=False)
        r3 = SS.verify_settlement_sparse(p3, num_queries=NQ, depth=D)
        check("a two-block asset span proves per block (ledger threaded across segments) and verifies",
              r3[0] is True and len(p3["segments"]) == 2, (r3[1], len(p3["segments"])))
        check("...landing on the exec node's real KV root",
              r3[3] == ST.digest_hex(ST.SparseStore(D, SS.sparse_projection(st.contracts, D, v2=True)).root()))
    except Exception as e:
        check("a two-block asset span proves per block", False, f"{type(e).__name__}: {str(e)[:300]}")
print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
