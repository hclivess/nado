"""A settle span whose calls execute NOP proves and verifies on the SHIPPED (native) proving path, under the zk_harden
rules (execnode/stark/settlement_sparse.py prove_settlement_sparse / verify_settlement_sparse — the exec node's and L1's own entry points; zk audit 2026-09-26 ZKVM-2).

The per-call test (test_nop_is_a_provable_step) proves through vm_circuit directly with the Python kernels; the exec
node proves settlements through prove_bound_epoch on the native arena, which is where "NOP is provable" has to be true.
Pins, with the native kernels only (this test must NOT set NADO_ALLOW_PYTHON_KERNELS): a span deploying a contract and
calling a method that executes NOPs proves under the hardened rules, verifies, and lands on exactly the chain's post
state. (The hardening is on from block 1 — gen 27's ZK_HARDEN_HEIGHT, 1 from gen 28 and deleted — so the pre-gate rule
set under which the span was unprovable no longer exists and is not pinned.)

Run: python3 tests/test_nop_settles_by_proof.py            (native kernels required)
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-nopsettle-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
os.environ.pop("NADO_ALLOW_PYTHON_KERNELS", None)         # the SHIPPED path: native kernels or a loud failure
import sys, copy, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.environ["HOME"])
from execnode import zkvmasm
from execnode.code_codec import contract_id
from execnode.state import ExecState
from execnode.stark import settlement_sparse as SS, calls_commit as CC, stark, storage_tree as ST

NQ, DEPTH, H = 16, 16, 300_000
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


A = "ndoAAAA" + "A" * 41; B = "ndoBBBB" + "B" * 41
NOPPY = {"go": [["NOP", 0, 0, 0], ["MOVI", 1, 0, 0], ["SLOAD", 2, 1, 0], ["NOP", 0, 0, 0], ["MOVI", 3, 0, 1],
                ["ADD", 2, 3, 0], ["NOP", 0, 0, 0], ["SSTORE", 1, 2, 0], ["RET", 0, 2, 0]]}
tx = lambda s, d, t: {"recipient": "blob", "sender": s, "txid": t, "data": dict(d)}
blk = lambda h, txs: {"block_number": h, "block_hash": "ab" * 32, "block_timestamp": 0, "block_transactions": txs}


def chain(blocks, st=None):
    from execnode.execnode import _apply_block
    st = st or ExecState(os.path.join(os.environ["HOME"], f"s{id(blocks)}.json"))
    loop = asyncio.new_event_loop()
    for b in blocks:
        assert loop.run_until_complete(_apply_block(None, {"default": st}, st, b, verbose=False)) is True
    return st


cid = contract_id(A, NOPPY, "n1")
st = chain([blk(H - 1, [tx(A, {"op": "deploy", "code": NOPPY, "nonce": "n1"}, "d1")])])
pre = copy.deepcopy(st.contracts)
span = [tx(B, {"op": "call", "contract": cid, "method": "go", "args": []}, "c1"),
        tx(B, {"op": "call", "contract": cid, "method": "go", "args": []}, "c2")]
chain([blk(H, span)], st)
check("the exec layer ran both NOP calls", st.contracts[cid]["storage"]["slots"].get("0") in (2, "2"), st.contracts[cid]["storage"])
chain_root = SS.sparse_root(st.contracts, DEPTH, v2=True)
entries = CC.block_calls(blk(H, span))


def attempt(rules):
    with stark.with_rules(rules):
        try:
            # the exec node's own entry point (execnode.py _prove): row-committed on an arena-covered backend
            P = SS.prove_settlement_sparse(pre, entries, cursor=H, rec_hex=ST.digest_hex(ST.SparseStore(DEPTH, {}).root()),
                                           num_queries=NQ, depth=DEPTH)
        except Exception as e:
            return None, f"{type(e).__name__}: {str(e)[:140]}"
        ok, why, kv_pre, kv_post = SS.verify_settlement_sparse(P, num_queries=NQ, depth=DEPTH)[:4]   # L1's entry point
        return (ok, why, kv_post), None


(v, err) = attempt(stark.RULES_STRICT)
check("hardened rules, native path: the NOP span proves", err is None, err)
if v:
    ok, why, post = v
    check("... verifies", ok is True, why)
    check("... and lands on exactly the chain's post state", post == ST.digest_hex(chain_root), (post, ST.digest_hex(chain_root)))
print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
