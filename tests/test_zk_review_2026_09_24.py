"""Every remaining fix from the 2026-09-24 zero-knowledge review, driven where the code allows it
(doc/security-review-2026-09-24-zk.md). The larger fixes have their own files:

  test_proof_query_full.py (findings 1, 2) · test_privacy_pause.py (3-5) · test_appnote_deposit_vin.py (3) ·
  test_fold_hardening.py (7) · test_shielded_wide.py (4: bind_aux) · joinsplit{2,3}_js_crosscheck.sh (browser parity)

This file covers:
  * a node-local failure (a missing/stale native kernel, or memory) is RAISED through every verify layer, never
    returned as "invalid" — and the settle branch turns it into ProofUnavailable (defer, not reject);
  * exit claims are bounded (no amount + k*P aliasing), from PROOF_QUERY_FULL_HEIGHT;
  * a settle proof carries no PAY when records-frozen, and no asset io at all from the gate;
  * io attribution requires exactly one RET segment per VM unit;
  * the wide spend key is four lanes (algebra and a real proof), and the browser binds the same aux string;
  * the Rust compose kernels return NEGATIVE error codes (a positive one was read as a column id);
  * the exec node never builds a fold the chain would refuse;
  * the wallet's privacy guards are in place (pause, v2 key domain, pool-separated notes, local receive lookup).

Run: python3 tests/test_zk_review_2026_09_24.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-zk-review-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")   # never the live exec files
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
os.environ["NADO_ALLOW_PYTHON_KERNELS"] = "1"
import sys, json, subprocess, traceback
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import protocol as P
from execnode.stark import stark, fri, field as F, native_guard as NG

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

GATE = int(P.PROOF_QUERY_FULL_HEIGHT)
TRANS = [lambda c, n, p: F.sub(n[0], F.add(c[0], 1))]
BND = [(0, 0, 0)]


def _honest():
    return stark.prove([[i] for i in range(16)], TRANS, BND, max_degree=2, num_queries=8)


def _raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    return False


# ---- node-local failures are not verdicts ------------------------------------------------------------------------
def t_a_missing_kernel_inside_fri_is_raised_not_returned():
    pf = _honest()
    from execnode.stark import merkle
    real = merkle.verify
    def boom(*a, **k):
        raise NG.NativeMissing("simulated stale crate")
    merkle.verify = boom
    try:
        # through stark.verify: fri.verify needs the STARK's transcript to reach its Merkle checks at all
        assert _raises(NG.NativeMissing, lambda: stark.verify(pf, TRANS, BND, max_degree=2, num_queries=8)), \
            "stark.verify (or the fri.verify inside it) turned a node-local failure into a verdict"
    finally:
        merkle.verify = real


def t_memory_errors_inside_fri_are_raised_too():
    pf = _honest()
    from execnode.stark import merkle
    real = merkle.verify
    def oom(*a, **k):
        raise MemoryError()
    merkle.verify = oom
    try:
        assert _raises(MemoryError, lambda: stark.verify(pf, TRANS, BND, max_degree=2, num_queries=8)), \
            "a MemoryError inside verification became a verdict (the 2026-09-23 S5 fix was incomplete in fri)"
    finally:
        merkle.verify = real


def t_the_settlement_verifiers_raise_node_local_failures():
    from execnode.stark import settlement_sparse as SS, vm_circuit as V
    real = V.verify_epoch_calls
    def boom(*a, **k):
        raise NG.NativeMissing("simulated")
    V.verify_epoch_calls = boom
    try:
        seg = {"depth": 256, "proof": {}, "calls": [], "io": [], "cursor": 1, "pre_contracts": {}}
        assert _raises(NG.NativeMissing, lambda: SS.verify_bound_epoch(seg)), "verify_bound_epoch swallowed it"
        assert _raises(NG.NativeMissing, lambda: SS.verify_settlement_sparse({"segments": [seg]}, depth=256)), \
            "verify_settlement_sparse swallowed it"
    finally:
        V.verify_epoch_calls = real
    assert NG.NativeMissing in NG.NODE_LOCAL_ERRORS and MemoryError in NG.NODE_LOCAL_ERRORS


def t_the_settle_branch_defers_instead_of_rejecting():
    """The L1 settle branch cannot run without a chain; pin that both in-process verify calls convert the node-local
    failure into ProofUnavailable (defer) rather than letting it become a rejection."""
    src = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
    assert src.count("raise ProofUnavailable(f\"this node cannot verify settle proofs yet:") == 2


# ---- exit claims and settle io -----------------------------------------------------------------------------------
def t_exit_claims_are_bounded_from_the_gate():
    from ops.transaction_ops import exit_amount_check
    big = (1 << 61) + 5
    exit_amount_check(big, GATE - 1)                      # replay: the old rule accepted it here
    exit_amount_check((1 << 61) - 1, GATE)
    assert _raises(AssertionError, lambda: exit_amount_check(big, GATE)), "amount >= 2^61 must be refused"
    assert _raises(AssertionError, lambda: exit_amount_check(5 + F.P, GATE)), "amount + P must be refused"


def t_settle_proofs_carry_no_pay_when_frozen_and_no_asset_io_from_the_gate():
    from ops.transaction_ops import settle_proof_io_check
    from execnode import zkvm as Z
    pay = {"segments": [{"io": [[Z.IO_PAY, 1, 2]]}]}
    assert _raises(AssertionError, lambda: settle_proof_io_check(pay, False, GATE - 1)), "frozen proof with a PAY"
    settle_proof_io_check(pay, True, GATE - 1)            # a records-bound proof derives the payout instead
    for kind in Z.IO_ASSET_KINDS:
        prf = {"segments": [{"io": [[Z.IO_SSTORE, 1, 2], [kind, 3, 4]]}]}
        settle_proof_io_check(prf, True, GATE - 1)        # below the gate: replay unchanged
        assert _raises(AssertionError, lambda: settle_proof_io_check(prf, True, GATE)), f"asset io kind {kind}"
        assert _raises(AssertionError, lambda: settle_proof_io_check(prf, False, GATE)), f"asset io kind {kind}"
    settle_proof_io_check({"segments": [{"io": [[Z.IO_SSTORE, 1, 2], [Z.IO_RET, 0, 0]]}]}, False, GATE)


def t_io_attribution_needs_one_segment_per_vm_unit():
    from execnode.stark import settlement_sparse as SS, exec_state_bind as ESB
    from execnode import zkvm as Z
    real = ESB.vm_units
    ESB.vm_units = lambda pre, calls, cursor, ts: [("c" * 32, {})]
    try:
        ok_bundle = {"pre_contracts": {}, "calls": [], "cursor": 1, "io": [[Z.IO_SSTORE, 1, 2], [Z.IO_RET, 0, 0]]}
        assert SS._cid_io(ok_bundle) == [("c" * 32, Z.IO_SSTORE, 1, 2), ("c" * 32, Z.IO_RET, 0, 0)]
        extra = dict(ok_bundle, io=ok_bundle["io"] + [[Z.IO_SSTORE, 9, 9], [Z.IO_RET, 0, 0]])
        assert _raises(ValueError, lambda: SS._cid_io(extra)), "io past the last VM unit was silently dropped"
        short = dict(ok_bundle, io=[[Z.IO_SSTORE, 1, 2]])
        assert _raises(ValueError, lambda: SS._cid_io(short)), "a VM unit with no RET segment"
    finally:
        ESB.vm_units = real


# ---- the wide spend key ------------------------------------------------------------------------------------------
def t_the_wide_spend_key_is_four_lanes():
    from execnode.stark import znote as Z
    assert Z.nsk_lanes(7) == (7, 0, 0, 0) and Z.owner_of(7) == Z.owner_of((7, 0, 0, 0))
    k = (11, 22, 33, 44)
    assert Z.owner_of(k) != Z.owner_of(11), "the upper lanes must enter the owner"
    assert Z.nullifier(k, 5) != Z.nullifier(11, 5), "the upper lanes must enter the nullifier"
    assert _raises(ValueError, lambda: Z.nsk_lanes((1, 2, 3))), "three lanes is not a key"


def t_a_wide_transfer_proves_and_verifies_with_a_four_lane_key():
    from execnode.stark import znote as Z, joinsplit3 as J3
    from execnode import shielded_wide as SW
    k = (0x1111, 0x2222, 0x3333, 0x4444)
    pool = SW.WideShieldedPool()
    oa = Z.owner_of(k)
    cm = Z.commit(1000, oa, 7); pool.append(cm)
    sibs, dirs = SW.tree_path(pool.commitments, 0)
    proof, root, nf, cm1, cm2 = J3.prove_transfer(k, 1000, 7, sibs, dirs, 600, oa, 11, 400, oa, 12, 0, 0)
    assert nf == Z.nullifier(k, 7)
    ok, why = J3.verify_transfer(proof, root, nf, cm1, cm2, 0, 0, pool.knows_root)
    assert ok, why
    assert proof["W"] == J3.NCOLS_TOTAL == 39


def t_the_browser_binds_the_same_aux_string_as_python():
    from execnode.stark import joinsplit3 as J3
    cases = [("ndo" + "A" * 45, -100, 0), (None, 0, 0), ("x", -5, 7)]
    js = ("import { bindAux } from '%s/static/stark/joinsplit3.js';"
          "const cases = %s; console.log(JSON.stringify(cases.map(([a, v, f]) => bindAux(a, BigInt(v), BigInt(f)))));"
          % (ROOT, json.dumps([[a, v, f] for a, v, f in cases])))
    out = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-400:]
    assert json.loads(out.stdout) == [J3.bind_aux(a, v, f) for a, v, f in cases]


# ---- native kernels and the fold decision ------------------------------------------------------------------------
def t_the_compose_kernels_return_negative_error_codes():
    from execnode.stark import stark_native as SN
    if not SN.available():
        print("      (native prover unavailable: skipped)"); return
    import ctypes
    lib = SN._LIB
    fn = lib.sp_compose_ext
    fn.restype = ctypes.c_int64
    types = list(fn.argtypes or [])
    assert len(types) == 22, f"sp_compose_ext takes 22 arguments, the binding declares {len(types)}"
    args = [None if t is ctypes.c_void_p else 0 for t in types]      # null pointers: the degree check runs first
    args[20] = 99                                         # degree != EXT_DEGREE: the kernel's first check
    rc = fn(*args)
    assert rc < 0, f"a validation failure returned {rc}, which the wrapper would read as a column id"


def t_the_exec_node_never_builds_a_fold_the_chain_refuses():
    from execnode.stark import recursive_verify as RV
    assert not RV.fold_refused_at(P.REVIEW_R2_HEIGHT)
    assert RV.fold_refused_at(P.PROOF_TRACE_LDT_HEIGHT) and RV.fold_refused_at(GATE)
    src = open(os.path.join(ROOT, "execnode", "execnode.py")).read()
    assert "_RVf.fold_refused_at(int(cur) + 1)" in src


# ---- the wallet --------------------------------------------------------------------------------------------------
def t_the_wallet_privacy_guards_are_in_place():
    """interface.js is DOM-bound, so this pins the guards by source; the provers themselves are driven by the JS
    cross-checks. Each line names what it prevents."""
    s = open(os.path.join(ROOT, "static", "interface.js")).read()
    for fn in ("async function doShield()", "async function doUnshield()", "async function doSendShielded()",
               "async function doReceiveShielded()"):
        i = s.index(fn)
        assert "if (shieldPaused()) return;" in s[i:i + 400], f"{fn} must stop on the pause (no legacy proof)"
    assert 'const DOMAIN_SHIELD_NSK_WIDE = "shield-nsk-v2";' in s, "the wide key needs its own domain"
    assert "blake2bHash([DOMAIN_SHIELD_NSK_WIDE, state.wallet.privateKey])" in s
    assert "alghash2.ownerOf(shieldNskWide())" in s, "the wide owner must come from the wide key"
    assert "/exec/field_shielded?cm=" not in s, "receiving must not tell the relay which note"
    assert "return all.filter((n) => _notePoolIsWide(n) === wide);" in s, "the balance must count one pool"
    assert "J.bindAux(wit.withdraw_addr, wit.public_value, wit.fee)" in s, "the wide prover must bind value and fee"
    assert "fullQuery: at(\"full_query\")" in s, "the wallet must follow the full-query rule"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("t_"):
            check(name[2:].replace("_", " "), fn)
    print("ALL PASS" if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
