"""A settle proof cannot omit an in-span deploy through a phantom pre-state record, from ZK_HARDEN_HEIGHT
(execnode/stark/settlement_sparse.py _exported_shape; zk audit 2026-09-26 SETTLE-1).

sparse_projection skips any record whose runtime is not "zkvm", so a phantom record at the cid of a contract deployed
inside the span changed no pin leaf; the verifier's own event replay then saw the cid as taken and treated the deploy
as refused, and the proof verified to a root WITHOUT the deploy (reproduced end to end: a trustless settle omitting
it). Pins: under the hardened rules the honest bundle verifies and the phantom one is refused; under the pre-gate rules
behaviour is unchanged (history replays).

Run: NADO_ALLOW_PYTHON_KERNELS=1 python3 tests/test_settle_pre_contracts_exported.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-phantom-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import sys, copy, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.environ["HOME"])
from execnode import zkvmasm, settlement_proofs as SP
from execnode.code_codec import contract_id
from execnode.state import ExecState
from execnode.stark import (settlement_sparse as SS, exec_state_bind as ESB, calls_commit as CC, stark,
                            storage_tree as ST, state_transition as SX)

NQ, DEPTH, H = 8, 16, 300_000
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


ALICE = "ndoAAAA" + "A" * 41; BOB = "ndoBBBB" + "B" * 41
BUMP1 = {"bump": zkvmasm.assemble("movi r1 0\n sload r2 r1\n movi r3 1\n add r2 r3\n sstore r1 r2\n ret r2")}
CTOR = {"constructor": zkvmasm.assemble("movi r1 3\n movi r2 42\n sstore r1 r2\n ret r2"),
        "get": zkvmasm.assemble("movi r1 3\n sload r2 r1\n ret r2")}
tx = lambda s, d, t: {"recipient": "blob", "sender": s, "txid": t, "data": dict(d)}
block = lambda h, txs: {"block_number": h, "block_hash": "ab" * 32, "block_timestamp": 0, "block_transactions": txs}


def chain(blocks, st=None):
    from execnode.execnode import _apply_block
    st = st or ExecState(os.path.join(os.environ["HOME"], f"s{id(blocks)}.json"))
    loop = asyncio.new_event_loop()
    for b in blocks:
        assert loop.run_until_complete(_apply_block(None, {"default": st}, st, b, verbose=False)) is True
    return st


cid1 = contract_id(ALICE, BUMP1, "n1"); cid2 = contract_id(ALICE, CTOR, "n2")
st = chain([block(H - 1, [tx(ALICE, {"op": "deploy", "code": BUMP1, "nonce": "n1"}, "p1")])])
pre = copy.deepcopy(st.contracts)
span = [tx(ALICE, {"op": "deploy", "code": CTOR, "nonce": "n2"}, "s1"),
        tx(BOB, {"op": "call", "contract": cid1, "method": "bump", "args": []}, "s2")]
chain([block(H, span)], st)
entries = CC.block_calls(block(H, span))


def run(rules):
    with stark.with_rules(rules):
        honest = SS.prove_bound_epoch(pre, entries, cursor=H, num_queries=NQ, depth=DEPTH)
        okh, whyh, _ = SS.verify_bound_epoch(honest, num_queries=NQ)
        ph = copy.deepcopy(pre)
        ph[cid2] = {"code": {"x": []}, "storage": {"slots": {}}, "deployer": ALICE}      # no "runtime": invisible to the pin
        forged = SP.prove_epoch(ph, entries, H, num_queries=NQ)
        forged["pre_contracts"][cid2] = ph[cid2]
        cid_io = SS._cid_io(forged)
        store = ST.SparseStore(DEPTH, SS.sparse_projection(forged["pre_contracts"], DEPTH, v2=True))
        spre = store.root()
        lead = ESB.event_updates(forged["pre_contracts"], entries, DEPTH)
        pg = lambda c, s: ((forged["pre_contracts"].get(c) or {}).get("storage") or {}).get("slots", {}).get(str(int(s)), 0)
        net = ESB.net_updates(pg, cid_io, DEPTH)
        tr = SX.prove_transition(store, [(k, n) for (k, _o, n) in lead] + [(k, n) for (k, _o, n) in net], num_queries=NQ)
        forged.update(sparse_pre_root=spre, sparse_post_root=store.root(), transition=tr, cid_io=cid_io, depth=DEPTH,
                      calls_commitment=CC.calls_commitment(forged["calls"], H, 0))
        okf, whyf, _ = SS.verify_bound_epoch(forged, num_queries=NQ)
        return (okh, whyh), (okf, whyf)


(hs, fs) = run(stark.RULES_STRICT)
check("hardened rules: the honest bundle verifies", hs[0] is True, hs)
check("hardened rules: the phantom-record bundle is refused", fs[0] is False and "exported zkVM records" in str(fs[1]), fs)
(hp, fp) = run(stark.RULES_PRE_HARDEN)
check("pre-gate rules: the honest bundle verifies", hp[0] is True, hp)
check("pre-gate rules: the old behaviour stands, so history replays", fp[0] is True, fp)
ok, why = SS._exported_shape({cid1: {"code": {"a": [1]}, "storage": {"slots": {}}, "runtime": "zkvm",
                                     "deployer": ALICE, "upgradable": True}}, True)
check("an exporter-shaped record passes the shape check", ok, why)

print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
