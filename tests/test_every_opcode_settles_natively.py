"""Every opcode a settle proof may carry settles by proof on the SHIPPED path — prove_settlement_sparse on the native
arena, verified by L1's verify_settlement_sparse — landing on exactly the chain's state (zk audit 2026-09-26).

tests/test_every_opcode_is_provable.py proves each opcode per call through vm_circuit with the Python kernels, which a
node refuses; this runs the same programs (tests/opcode_programs.py) the way the exec node proves them, native kernels
only. Excluded, by rule rather than by gap: PAY and the asset ops (a settle proof refuses asset io, and PAY only
settles records-bound — tests/test_pay_binding.py, test_zk_review_2026_09_24.py), BHASH/BEACON (bound to the
finalized chain on L1 — chain_reads), and CTX's `value` (it needs an exec bridge escrow; CTX itself is covered).

Run: python3 tests/test_every_opcode_settles_natively.py            (native kernels required)
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-opsettle-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
os.environ.pop("NADO_ALLOW_PYTHON_KERNELS", None)         # the SHIPPED path
import sys, copy, asyncio
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
os.chdir(os.environ["HOME"])
from execnode import zkvm
from execnode.code_codec import contract_id
from execnode.state import ExecState
from execnode.stark import settlement_sparse as SS, calls_commit as CC, stark, storage_tree as ST
from opcode_programs import CASES

NQ, DEPTH, H = 16, 16, 300_000
EXCLUDED = {"PAY", "ASEL", "AMINT", "ABURN", "ABAL", "ARENOUNCE", "BHASH", "BEACON"}
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


A = "ndoAAAA" + "A" * 41; B = "ndoBBBB" + "B" * 41
tx = lambda s, d, t: {"recipient": "blob", "sender": s, "txid": t, "data": dict(d)}
blk = lambda h, txs: {"block_number": h, "block_hash": "ab" * 32, "block_timestamp": 0, "block_transactions": txs}
cases = [(n, c, x) for (n, c, x) in CASES
         if not ({ins[0] for p in c.values() for ins in p} & EXCLUDED) and "abal" not in x and "asset" not in x]
from execnode import zkvmasm
cases.append(("ACTX with no asset (reads 0 and self)", {"go": zkvmasm.assemble("actx r1 asset\n actx r2 self\n add r1 r2\n ret r1")}, {}))
covered = {ins[0] for (_n, c, _x) in cases for p in c.values() for ins in p}

from execnode.execnode import _apply_block
st = ExecState(os.path.join(os.environ["HOME"], "chain.json"))
loop = asyncio.new_event_loop()
deploys, calls = [], []
for i, (name, code, extra) in enumerate(cases):
    deploys.append(tx(A, {"op": "deploy", "code": code, "nonce": f"n{i}"}, f"d{i}"))
    calls.append(tx(B, {"op": "call", "contract": contract_id(A, code, f"n{i}"), "method": "go",
                        "args": list(extra.get("args_f", []))}, f"c{i}"))
assert loop.run_until_complete(_apply_block(None, {"default": st}, st, blk(H - 1, deploys), verbose=False))
for i, (name, code, extra) in enumerate(cases):                      # prefilled storage the programs read
    for k, v in (extra.get("slots") or {}).items():
        st.contracts[contract_id(A, code, f"n{i}")]["storage"].setdefault("slots", {})[str(k)] = v
pre = copy.deepcopy(st.contracts)
assert loop.run_until_complete(_apply_block(None, {"default": st}, st, blk(H, calls), verbose=False))
entries = CC.block_calls(blk(H, calls))
chain_post = ST.digest_hex(SS.sparse_root(st.contracts, DEPTH, v2=True))
check(f"{len(cases)} programs covering {len(covered)} opcodes run on the exec layer", len(cases) >= 20)

with stark.with_rules(stark.RULES_STRICT):
    try:
        P = SS.prove_settlement_sparse(pre, entries, cursor=H, rec_hex=ST.digest_hex(ST.SparseStore(DEPTH, {}).root()),
                                       num_queries=NQ, depth=DEPTH)
        r = SS.verify_settlement_sparse(P, num_queries=NQ, depth=DEPTH)
        check("the span proves natively and verifies with L1's entry point", r[0] is True, r[1])
        check("... landing on exactly the chain's post state", r[3] == chain_post, (r[3], chain_post))
    except Exception as e:
        check("the span proves natively and verifies with L1's entry point", False, f"{type(e).__name__}: {str(e)[:200]}")
missing = sorted(set(zkvm.OPS) - covered - EXCLUDED, key=zkvm.OPS.index)
check("every settle-eligible opcode is in the span", not missing, missing)
print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
