"""
REGRESSION (critical soundness, deep-audit finding 2026-07-27): the sparse settlement verifier bound the KV
state transition to the PROVER-SUPPLIED bundle["cid_io"], never re-derived from / checked against the
exec-proof-authenticated bundle["io"]. A bonded settler could append a fabricated (cid, IO_SSTORE, slot, value)
to cid_io — absent from io — prove a transition over it, and settle an ARBITRARY forged root (overwrite any
contract's storage, drain escrow). verify_settlement_sparse / verify_bound_epoch now re-derive
cid_io = _cid_io(bundle) from the authenticated io+calls and ignore the bundle's field.

This test forges exactly that attack and asserts it is REJECTED, while the honest bundle is ACCEPTED.

Run: python3 tests/test_settle_cid_io_binding.py
"""
import os, sys, copy, tempfile, traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_cidio_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
from genesis import create_indexers
create_indexers()

from execnode import zkvmasm, zkvm
from execnode.stark import settlement_sparse as SS, storage_tree as ST, state_transition as SX, exec_state_bind as ESB

fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1

D = 16                                    # toy sparse depth
NQ = 2
CID = "c" * 32
ALICE = "ndoAAAA" + "A" * 41
COUNTER = {"bump": zkvmasm.assemble("movi r1 0\n sload r2 r1\n movi r3 1\n add r2 r3\n sstore r1 r2\n ret r2")}


def _pre():
    return {CID: {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}}


CALLS = [{"cid": CID, "method": "bump", "caller": ALICE, "args": []}]

# --- honest bound epoch ---
_HONEST = SS.prove_bound_epoch(_pre(), CALLS, cursor=100, num_queries=NQ, depth=D)


def t_honest_verifies():
    ok, why, post = SS.verify_bound_epoch(_HONEST, num_queries=NQ)
    check(f"honest bound epoch verifies ({why})", ok)
    check("honest post == bundle post", post == _HONEST["sparse_post_root"])


def _forge(honest, forged_slot=777, forged_value=10**6):
    """Append a fabricated IO_SSTORE to cid_io (absent from io), re-prove the transition, forge the post-root —
    the exact deep-audit attack. Returns the tampered bundle."""
    bad = copy.deepcopy(honest)
    pre_get = lambda cid, slot: ((bad["pre_contracts"].get(cid) or {}).get("storage") or {}).get("slots", {}).get(str(int(slot)), 0)
    forged_cid_io = list(bad["cid_io"]) + [(CID, zkvm.IO_SSTORE, forged_slot, forged_value)]
    pre_store = ST.SparseStore(D, SS.sparse_projection(bad["pre_contracts"], D))
    net = ESB.net_updates(pre_get, forged_cid_io, D)
    tr = SX.prove_transition(pre_store, [(k, n) for (k, _o, n) in net], num_queries=NQ)   # mutates pre_store
    bad["cid_io"] = forged_cid_io
    bad["transition"] = tr
    bad["sparse_post_root"] = pre_store.root()               # attacker-chosen forged root (encodes the fake write)
    return bad


def t_forged_cid_io_rejected():
    """io/calls/pre_contracts/sparse_pre_root/proof/calls_commitment untouched; only cid_io+transition+post forged.
    Before the fix this returned ok with the forged root; now it MUST be rejected because verify re-derives cid_io
    from the authenticated io (which lacks the fabricated write) -> net_updates != the forged transition."""
    bad = _forge(_HONEST)
    # the forged post-root genuinely differs from the honest one (the attack produced a different state)
    check("forged post-root differs from honest (attack is non-trivial)",
          tuple(bad["sparse_post_root"]) != tuple(_HONEST["sparse_post_root"]))
    ok, why, _ = SS.verify_bound_epoch(bad, num_queries=NQ)
    check(f"forged cid_io REJECTED by verify_bound_epoch ({why})", not ok)


def t_forged_rejected_through_settlement_wrapper():
    """The same forgery packaged as a settlement bundle must be rejected by verify_settlement_sparse (the live
    L1 entry) too — both the K-path and the non-fold sparse path re-derive cid_io."""
    bad = _forge(_HONEST)
    proof = {"cursor": 100, "rec": ST.digest_hex(ST.SparseStore(D, {}).root()),
             "kv_pre": ST.digest_hex(tuple(int(x) for x in bad["sparse_pre_root"])),
             "kv_post": ST.digest_hex(tuple(int(x) for x in bad["sparse_post_root"])),
             "segments": [bad]}
    ok, why, _kp, _kq = SS.verify_settlement_sparse(proof, num_queries=NQ, depth=D)
    check(f"forged settlement REJECTED by verify_settlement_sparse ({why})", not ok)


if __name__ == "__main__":
    t_honest_verifies()
    t_forged_cid_io_rejected()
    t_forged_rejected_through_settlement_wrapper()
    print("\nALL PASS — cid_io is bound to the exec proof; the forged-root attack is rejected" if fails == 0
          else f"\n{fails} FAILURES")
    sys.exit(1 if fails else 0)
