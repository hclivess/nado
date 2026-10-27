"""Every remaining fix from the 2026-09-24 zero-knowledge review, driven where the code allows it
(doc/security-review-2026-09-24-zk.md). The larger fixes have their own files:

  test_proof_query_full.py (findings 1, 2) · test_privacy_pause.py (3-5) · test_fold_hardening.py (7)
  (finding 4's bind_aux, the appnote deposit and the browser parity cross-checks went with their pools in G9 slice 5)

This file covers:
  * a node-local failure (a missing/stale native kernel, or memory) is RAISED through every verify layer, never
    returned as "invalid";
  * exit claims are bounded (no amount + k*P aliasing), from PROOF_QUERY_FULL_HEIGHT;
  * the Rust compose kernels return NEGATIVE error codes (a positive one was read as a column id);
  * the wallet's privacy guards are in place (pause, v2 key domain, pool-separated notes, local receive lookup).
The settle-proof cases (the settle branch's deferral, its PAY / io-attribution checks, the exec node's fold decision)
were retired in G9 with the Goldilocks settle proof: a BLAKE2s exec root settles by quorum attestation only.

Run: python3 tests/test_zk_review_2026_09_24.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-zk-review-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")   # never the live exec files
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
os.environ["NADO_ALLOW_PYTHON_KERNELS"] = "1"
import sys, traceback
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import protocol as P
from execnode.stark import stark, fri, field as F, native_guard as NG

import _harness
_report = _harness.Report()
check = _report.run

GATE = 1   # the rule holds from block 1 (gen 25's PROOF_QUERY_FULL_HEIGHT, deleted after the betanet-8 reroll); height 0 is below it
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
    assert NG.NativeMissing in NG.NODE_LOCAL_ERRORS and MemoryError in NG.NODE_LOCAL_ERRORS


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


# the settlement verifiers raise node local failures retired in G9: settlement_sparse and vm_circuit were deleted
# the settle branch defers instead of rejecting retired in G9: L1 no longer verifies a settle proof (it refuses one)


# ---- exit claims and settle io -----------------------------------------------------------------------------------
def t_exit_claims_are_bounded_from_the_gate():
    from ops.transaction_ops import exit_amount_check
    big = (1 << 61) + 5
    exit_amount_check(big, GATE - 1)                      # replay: the old rule accepted it here
    exit_amount_check((1 << 61) - 1, GATE)
    assert _raises(AssertionError, lambda: exit_amount_check(big, GATE)), "amount >= 2^61 must be refused"
    assert _raises(AssertionError, lambda: exit_amount_check(5 + F.P, GATE)), "amount + P must be refused"


# settle proofs carry no pay when frozen retired in G9: settle_proof_io_check was deleted with the L1 settle-proof verifier
# io attribution needs one segment per vm unit retired in G9: settlement_sparse._cid_io was deleted


# the wide spend key is four lanes / a wide transfer proves with a four-lane key / the browser binds the same aux string:
# retired in G9 slice 5 with the wide pool (znote, joinsplit3, static/stark/joinsplit3.js are deleted)


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


# the exec node never builds a fold the chain refuses retired in G9: the exec node's fold (SETTLE_FOLD) was deleted


# ---- the wallet --------------------------------------------------------------------------------------------------
def t_the_wallet_privacy_guards_are_in_place():
    """interface.js is DOM-bound, so this pins the guards by source; the provers themselves are driven by the JS
    cross-checks. Each line names what it prevents."""
    s = open(os.path.join(ROOT, "static", "interface.js")).read()
    for fn in ("async function doShield()", "async function doUnshield()", "async function doSendShielded()",
               "async function doReceiveShielded()"):
        i = s.index(fn)
        assert "if (shieldPaused()) return;" in s[i:i + 400], f"{fn} must stop on the pause (no legacy proof)"
    # G6: the wallet dropped the legacy and wide pools (both closed and empty); their key domains stay reserved, and the
    # Stwo key has its own (one pool's leak never opens another's notes)
    assert 'const DOMAIN_SHIELD_NSK_WIDE = "shield-nsk-v2";' in s, "the wide key's domain stays reserved"
    assert "blake2bHash([DOMAIN_SHIELD_NSK_STWO, state.wallet.privateKey])" in s, "the Stwo key comes from its own domain"
    assert "DOMAIN_SHIELD_NSK_WIDE, state" not in s and "DOMAIN_SHIELD_NSK, state" not in s, "no retired key is derived"
    assert "/exec/field_shielded?cm=" not in s, "receiving must not tell the relay which note"
    # a Stwo note is told from a wide one by its explicit tag (a Stwo cm is 64-hex like a wide one), and the balance
    # counts Stwo notes only — the property the three-way filter of 73ff9e69 kept
    assert 'return all.filter((n) => _notePool(n) === "stwo");' in s, "the balance must count one pool"
    assert 'n && n.pool === "stwo" ? "stwo"' in s, "a Stwo note is told from a wide one by its tag, not its shape"
    assert "st.proof_rules" not in s and "pr.shield_wide" not in s, "no retired prover's rules are read"

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("t_"):
            check(name[2:].replace("_", " "), fn)
    print("ALL PASS" if not _report.fails else f"{_report.fails} FAILURES")
    sys.exit(1 if _report.fails else 0)
