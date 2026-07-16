"""
ON-CHAIN SETTLE-WITH-PROOF (the trustless settlement path). A `settle` tx MAY carry a succinct recursion
validity proof; every node verifies it DETERMINISTICALLY at block-validation and, on success, records an
on-chain marker (kv_ops.settlement_proven) that settlement_ops.settlement_justified reads — so a proven root
is settled with NO bonded quorum and IDENTICALLY on every node (the old node-local verifier callback that
would have forked the chain is gone).

This file tests the CONSENSUS WIRING end-to-end: construct -> validate -> apply -> justified -> revert, plus
the exact-root binding, strict chain-extension, cursor binding, and that a bare (proofless) settle still works
as a quorum attestation. To keep it CI-fast it isolates the wiring from the ~15 GB W=106 STARK proving by
stubbing execnode.settlement_proofs.verify_settlement_o1 (whose SOUNDNESS — tampered io / layer-0 / pre-state
rejected — is covered by tests/test_settlement_proof.py and tests/test_settlement_o1.py). NADO_HEAVY=1 adds a
REAL W=106 recursion proof through the identical flow.

Run: python3 tests/test_settle_with_proof.py     (NADO_HEAVY=1 python3 … for the real-proof end-to-end)
"""
import os, sys, tempfile, traceback, logging, copy
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_swp_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

logger = logging.getLogger("swp"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import B_MIN, DEFAULT_NS, EXEC_GENESIS_ROOT
from ops import kv_ops
from ops.account_ops import create_account, reflect_transaction, get_bonded_registry
from ops.settlement_ops import settlement_justified, latest_settled
from ops.transaction_ops import construct_settle_tx, validate_transaction
from ops.key_ops import generate_keys
from execnode import settlement_proofs as SP     # patched below to isolate wiring from 15 GB proving

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()
def raises(fn):
    try: fn(); return False
    except Exception: return True

# --- verify_settlement_o1 STUB: returns the bundle's own declared post_root as "verified". This lets the
# test drive pre_root / cursor / post_root to exercise validate's chain + cursor + post bindings without the
# heavy STARK proving. A `_verify_ok=False` bundle flag simulates a proof that fails cryptographic verify. ---
_REAL_VERIFY = SP.verify_settlement_o1
def _stub_verify(bundle, num_queries=None, outer_queries=None):
    if not isinstance(bundle, dict) or not bundle.get("_verify_ok", True):
        return False, "stub: proof rejected", None
    return True, "stub ok", bundle.get("post_root")
SP.verify_settlement_o1 = _stub_verify

R0 = "aa" * 32          # first settled root (post of cursor 0)
R1 = "bb" * 32          # second settled root (post of cursor 1)
BH = 100                # block height we validate at

V = generate_keys(); create_account(V["address"], balance=B_MIN, bonded=4 * B_MIN)
REG = get_bonded_registry()


def _proof(pre, cursor, post, ok=True):
    return {"pre_root": pre, "cursor": int(cursor), "post_root": post, "_verify_ok": ok}


def _settle(cursor, root, proof, sender=V):
    return construct_settle_tx(sender, cursor, root, max_block=BH + 50, proof=proof)


def t1_valid_proof_settles_trustlessly():
    """A proof extending EXEC_GENESIS_ROOT validates, applies, and justifies the root with NO quorum."""
    tx = _settle(0, R0, _proof(EXEC_GENESIS_ROOT, 0, R0))
    assert validate_transaction(tx, logger, block_height=BH), "valid proof-settle must validate"
    assert not kv_ops.settlement_proven(DEFAULT_NS, 0, R0), "marker must not exist before apply"
    reflect_transaction(tx, logger, block_height=BH)
    assert kv_ops.settlement_proven(DEFAULT_NS, 0, R0), "apply must set the on-chain proof marker"
    assert settlement_justified(DEFAULT_NS, 0, R0, REG), "a proven root is justified with no quorum"
    assert latest_settled(DEFAULT_NS) == (0, R0), "latest_settled must point at the proven root"
    # bind: the marker is EXACT — a different root at the same cursor is NOT justified
    assert not settlement_justified(DEFAULT_NS, 0, "cc" * 32, REG), "only the proven root is justified"


def t2_post_root_must_equal_state_root():
    """If the tx claims a state_root the proof does not prove (post_root mismatch), validation rejects."""
    tx = _settle(5, R1, _proof(EXEC_GENESIS_ROOT, 5, "dd" * 32))   # proof proves a DIFFERENT post
    # (cursor 5 does not extend tip 0, but post-binding is checked too; make pre match tip to isolate post)
    tx2 = _settle(1, R1, _proof(R0, 1, "dd" * 32))                 # extends tip 0, but proves post != R1
    assert raises(lambda: validate_transaction(tx2, logger, BH)), "post_root != state_root must be rejected"


def t3_chain_break_rejected():
    """pre_root must extend the committed settled tip (here R0). A proof from any other pre-state is rejected."""
    tx = _settle(1, R1, _proof("ee" * 32, 1, R1))                  # pre_root is neither tip nor genesis
    assert raises(lambda: validate_transaction(tx, logger, BH)), "pre_root not extending the tip must reject"
    # and the genesis root is NOT accepted once a tip exists (must strictly extend)
    tx2 = _settle(1, R1, _proof(EXEC_GENESIS_ROOT, 1, R1))
    assert raises(lambda: validate_transaction(tx2, logger, BH)), "stale genesis pre_root must reject past tip 0"


def t4_cursor_binding():
    """The proof's cursor must equal the tx's exec_cursor."""
    tx = _settle(1, R1, _proof(R0, 7, R1))                         # proof says cursor 7, tx says 1
    assert raises(lambda: validate_transaction(tx, logger, BH)), "cursor mismatch must be rejected"


def t5_failed_crypto_verify_rejected():
    """If the recursion proof fails cryptographic verification, the tx is rejected (validate honors verify)."""
    tx = _settle(1, R1, _proof(R0, 1, R1, ok=False))
    assert raises(lambda: validate_transaction(tx, logger, BH)), "a proof that fails verify must be rejected"


def t6_chain_extends():
    """A second proof extending tip 0 (pre_root = R0) settles cursor 1 -> R1; latest_settled advances."""
    tx = _settle(1, R1, _proof(R0, 1, R1))
    assert validate_transaction(tx, logger, BH), "proof extending the tip must validate"
    reflect_transaction(tx, logger, block_height=BH)
    assert kv_ops.settlement_proven(DEFAULT_NS, 1, R1)
    assert latest_settled(DEFAULT_NS) == (1, R1), "tip must advance to the new proven root"


def t7_revert_symmetry():
    """Reverting a settle-with-proof clears the marker exactly (revert-safe): the root is no longer justified."""
    tx = _settle(2, "ff" * 32, _proof(R1, 2, "ff" * 32))
    validate_transaction(tx, logger, BH)
    reflect_transaction(tx, logger, block_height=BH)
    assert kv_ops.settlement_proven(DEFAULT_NS, 2, "ff" * 32)
    reflect_transaction(tx, logger, block_height=BH, revert=True)
    assert not kv_ops.settlement_proven(DEFAULT_NS, 2, "ff" * 32), "revert must clear the proof marker"
    assert latest_settled(DEFAULT_NS) == (1, R1), "after revert the tip falls back to the prior proven root"


def t8_bare_settle_still_quorum_only():
    """A proofless settle (the Phase-2a path) validates + applies as a plain attestation and sets NO proof
    marker — it justifies only through the bonded quorum, unchanged."""
    W = generate_keys(); create_account(W["address"], balance=B_MIN, bonded=4 * B_MIN)
    tx = construct_settle_tx(W, 3, "12" * 32, max_block=BH + 50)   # no proof
    assert "proof" not in (tx["data"]), "bare settle carries no proof"
    assert validate_transaction(tx, logger, BH), "bare settle must still validate"
    reflect_transaction(tx, logger, block_height=BH)
    assert not kv_ops.settlement_proven(DEFAULT_NS, 3, "12" * 32), "bare settle sets no proof marker"


def t9_non_bonded_proof_settle_rejected():
    """Only a bonded validator may settle — a proof does not bypass the bond requirement."""
    poor = generate_keys(); create_account(poor["address"], balance=B_MIN)   # not bonded
    tx = _settle(9, R1, _proof(R1, 9, R1), sender=poor)
    assert raises(lambda: validate_transaction(tx, logger, BH)), "non-bonded proof-settle must be rejected"


def t10_real_proof_end_to_end():
    """OPT-IN (NADO_HEAVY=1): a REAL W=106 recursion settlement bundle through the identical on-chain flow,
    verified at a reduced query strength (patched protocol constant) so it is feasible off the prover box."""
    if os.environ.get("NADO_HEAVY") != "1":
        print("SKIP  real W=106 proof end-to-end (set NADO_HEAVY=1; ~15 GB, minutes)")
        return
    SP.verify_settlement_o1 = _REAL_VERIFY                       # use the real verifier for this test
    import execnode.stark.fri as fri
    from execnode import zkvmasm
    saved = fri.NUM_QUERIES
    try:
        fri.NUM_QUERIES = 2                                     # reduce strength so validate's protocol read is light
        COUNTER = {"bump": zkvmasm.assemble("movi r1 0\n sload r2 r1\n movi r3 1\n add r2 r3\n sstore r1 r2\n ret r2")}
        cid = "c" * 32; caller = "ndoAAAA" + "A" * 41
        pre = {cid: {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}}
        calls = [{"cid": cid, "method": "bump", "caller": caller, "args": []} for _ in range(4)]
        bundle = SP.prove_settlement_o1(pre, calls, cursor=0, num_queries=2, max_rows=300,
                                        outer_queries=2, comp_points_per_proof=1)
        assert bundle["pre_root"] == EXEC_GENESIS_ROOT, "real epoch must start from the exec genesis root"
        U = generate_keys(); create_account(U["address"], balance=B_MIN, bonded=4 * B_MIN)
        tx = construct_settle_tx(U, 0, bundle["post_root"], max_block=BH + 50, proof=bundle)
        assert validate_transaction(tx, logger, BH), "real proof-settle must validate at protocol strength"
        reflect_transaction(tx, logger, block_height=BH)
        assert settlement_justified(DEFAULT_NS, 0, bundle["post_root"], get_bonded_registry())
    finally:
        fri.NUM_QUERIES = saved
        SP.verify_settlement_o1 = _stub_verify


if __name__ == "__main__":
    check("valid proof settles trustlessly (no quorum)", t1_valid_proof_settles_trustlessly)
    check("post_root must equal state_root", t2_post_root_must_equal_state_root)
    check("chain break (bad pre_root) rejected", t3_chain_break_rejected)
    check("cursor binding", t4_cursor_binding)
    check("failed crypto verify rejected", t5_failed_crypto_verify_rejected)
    check("chain extends (tip advances)", t6_chain_extends)
    check("revert symmetry (marker cleared)", t7_revert_symmetry)
    check("bare settle still quorum-only", t8_bare_settle_still_quorum_only)
    check("non-bonded proof-settle rejected", t9_non_bonded_proof_settle_rejected)
    check("real W=106 proof end-to-end (opt-in)", t10_real_proof_end_to_end)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
