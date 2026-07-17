"""
THE settled exec root (execnode/exec_root.py) — the frozen alphanet-6 scheme: rnode(kv_root, records_root),
both depth-256 alghash2 sparse trees; amounts as values, digests in positions; exits verify ONE sparse record
against the settled 64-hex root.

Checks: the empty-state root is deterministic (the EXEC_GENESIS_ROOT constant); a bridge-withdrawal exit proof
round-trips through the exact L1 verifier and every tamper (amount/addr/nonce/kv-half/path) is rejected; an
outbox message verifies the same way; incremental apply_projection equals a cold rebuild.

Run: python3 tests/test_exec_root.py   (native hashing only — fast)
"""
import os, sys, copy, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode import exec_root as ER
from execnode.state import ExecState
from execnode.stark import storage_tree as ST, field as F

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def _empty_state():
    return ExecState(os.path.join(tempfile.mkdtemp(), "s.json"))


def t_empty_root_deterministic():
    a = ER.state_root_hex({}, _empty_state())
    b = ER.state_root_hex({}, _empty_state())
    assert a == b and len(a) == 64 and all(c in "0123456789abcdef" for c in a)
    print(f"      EXEC_GENESIS_ROOT (alphanet-6) = {a}")


def t_withdrawal_exit_roundtrip():
    st = _empty_state()
    addr, amount, nonce = "ndo" + "a" * 46, 123456789, "n-1"
    st.withdrawals[nonce] = {"addr": addr, "amount": amount}
    kv = ST.SparseStore(ER.DEPTH, ER.kv_projection({}))
    rec = ST.SparseStore(ER.DEPTH, ER.records_projection(st))
    settled = ER.full_root_hex(kv.root(), rec.root())
    pos = ER.record_key(ER.T_BRIDGE_WD, addr, nonce)
    proof = ER.record_proof(kv.root(), rec, pos)
    assert ER.verify_withdrawal(settled, addr, amount, nonce, proof), "honest exit must verify"
    # every tamper rejected
    assert not ER.verify_withdrawal(settled, addr, amount + 1, nonce, proof), "wrong amount"
    assert not ER.verify_withdrawal(settled, "ndo" + "b" * 46, amount, nonce, proof), "wrong addr"
    assert not ER.verify_withdrawal(settled, addr, amount, "n-2", proof), "wrong nonce"
    bad = copy.deepcopy(proof); bad["kv"] = "0" * 64
    assert not ER.verify_withdrawal(settled, addr, amount, nonce, bad), "wrong kv half"
    bad2 = copy.deepcopy(proof)
    bad2["path"]["s"]["0"] = [format(1, "016x")] * ST.DIGEST
    assert not ER.verify_withdrawal(settled, addr, amount, nonce, bad2), "tampered path"
    assert not ER.verify_withdrawal(settled, addr, amount, nonce, {"kv": proof["kv"]}), "missing path"
    # a record proven against a DIFFERENT settled root fails
    st.withdrawals["n-2"] = {"addr": addr, "amount": 5}
    rec2 = ST.SparseStore(ER.DEPTH, ER.records_projection(st))
    other = ER.full_root_hex(kv.root(), rec2.root())
    assert other != settled and not ER.verify_withdrawal(other, addr, amount, nonce, proof), "stale proof vs new root"


def t_outbox_msg_roundtrip():
    st = _empty_state()
    msg = {"seq": 0, "from": "ndo" + "c" * 46, "to_ns": "other", "data": {"x": 1}}
    st.outbox["0"] = msg
    kv = ST.SparseStore(ER.DEPTH, ER.kv_projection({}))
    rec = ST.SparseStore(ER.DEPTH, ER.records_projection(st))
    settled = ER.full_root_hex(kv.root(), rec.root())
    pos = ER.record_key(ER.T_DIGEST, "outbox", ER.leaf_digest(ER.msg_outbox_leaf(msg)))
    proof = ER.record_proof(kv.root(), rec, pos)
    assert ER.verify_outbox_msg(settled, 0, msg["from"], "other", {"x": 1}, proof), "honest xmsg must verify"
    assert not ER.verify_outbox_msg(settled, 0, msg["from"], "other", {"x": 2}, proof), "tampered payload"
    assert not ER.verify_outbox_msg(settled, 1, msg["from"], "other", {"x": 1}, proof), "wrong seq"


def t_incremental_equals_cold():
    st = _empty_state()
    st.bridge["ndo" + "d" * 46] = 777
    kv_p, rec_p = ER.kv_projection({}), ER.records_projection(st)
    kv = ST.SparseStore(ER.DEPTH, kv_p)
    rec = ST.SparseStore(ER.DEPTH, rec_p)
    r0 = ER.full_root_hex(kv.root(), rec.root())
    # mutate: new withdrawal + changed balance + removed nothing; diff-apply must equal a cold rebuild
    st.withdrawals["w1"] = {"addr": "ndo" + "e" * 46, "amount": 42}
    st.bridge["ndo" + "d" * 46] = 778
    ER.apply_projection(rec, ER.records_projection(st))
    cold = ST.SparseStore(ER.DEPTH, ER.records_projection(st))
    assert ST._eq(rec.root(), cold.root()), "apply_projection must equal a cold rebuild"
    assert ER.full_root_hex(kv.root(), rec.root()) != r0, "root must move with the state"


if __name__ == "__main__":
    check("empty-state root deterministic (the genesis constant)", t_empty_root_deterministic)
    check("withdrawal exit round-trip + every tamper rejected", t_withdrawal_exit_roundtrip)
    check("outbox message (xmsg) round-trip + tamper rejected", t_outbox_msg_roundtrip)
    check("apply_projection incremental == cold rebuild", t_incremental_equals_cold)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
