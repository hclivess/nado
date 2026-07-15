"""
AUTHORITATIVE in-circuit STARK verification + the K→1 collapse (execnode/stark/recursive_verify.py). Proves
K=3 REAL chained x^2 STARK segments (segment i+1 starts where segment i ended), collapses them into ONE
recursion bundle, and checks that verifying the bundle — from the proofs' small PUBLIC PARTS only — is
equivalent to stark.verify of every segment: honest K=3 verifies; the WRONG AIR (x^3) is rejected by the
composition half; a fold whose roots don't match the segments is rejected; a tampered layer-0 seam value (the
comp↔fold agreement point) is rejected by the fold's in-circuit membership; and lying about a segment's seed
boundary is rejected. Single-phase demo AIR; the mechanism is identical for the execution AIR (more plumbing
for its two-phase LogUp challenges).
(Run: python3 tests/test_recursive_verify.py — a few slow alghash2 proofs.)
"""
import os, sys, copy, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import field as F, stark, backend as B, recursive_verify as RV

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

P = F.P
SEED = 123456789 % P
TRANS_X2 = [lambda c, n, p: F.sub(n[0], F.mul(c[0], c[0]))]            # x_nxt = x_cur^2
TRANS_X3 = [lambda c, n, p: F.sub(n[0], F.mul(F.mul(c[0], c[0]), c[0]))]  # wrong AIR: x_nxt = x_cur^3
K, Tn, NQ, NQO = 3, 8, 2, 4


def _chain_proofs():
    """K chained segments: segment i's trace starts at seed_i and ends at seed_{i+1}."""
    proofs, bnds, seed = [], [], SEED
    for _ in range(K):
        colv = [seed]
        for _ in range(Tn - 1):
            colv.append(F.mul(colv[-1], colv[-1]))
        trace = [[v] for v in colv]
        bl = [(0, 0, seed)]
        proof = stark.prove(trace, TRANS_X2, bl, max_degree=2, num_queries=NQ, backend=B.RECURSION)
        assert stark.verify(proof, TRANS_X2, bl, max_degree=2, num_queries=NQ, backend=B.RECURSION)[0]
        proofs.append(proof); bnds.append(bl)
        seed = F.mul(colv[-1], colv[-1])               # next segment continues the chain
    return proofs, bnds


# Prove the K inner STARKs + the ONE recursion bundle ONCE; every case below only re-runs verification —
# and verification reads ONLY the public parts (no openings, no Merkle paths).
_PROOFS, _BNDS = _chain_proofs()
_BUNDLE = RV.prove(_PROOFS, TRANS_X2, _BNDS, num_queries_outer=NQO)
_PUBLICS = [RV.public_part(p) for p in _PROOFS]


def t_k_to_1_verifies():
    ok, why = RV.verify(_PUBLICS, TRANS_X2, _BNDS, _BUNDLE, num_queries_outer=NQO)
    assert ok, f"honest K={K} chain must verify from public parts in ONE bundle: {why}"


def t_wrong_air_rejected():
    ok, why = RV.verify(_PUBLICS, TRANS_X3, _BNDS, _BUNDLE, num_queries_outer=NQO)   # claim a DIFFERENT AIR
    assert not ok, "verifying against the wrong AIR must be rejected by the composition half"


def t_fold_wrong_statement_rejected():
    """The fold must be FOR these segments in this order: the verifier builds the fold schedule from the
    public parts, so verifying the bundle against a permuted segment list must fail in-circuit."""
    ok, _ = RV.verify(list(reversed(_PUBLICS)), TRANS_X2, list(reversed(_BNDS)), _BUNDLE,
                      num_queries_outer=NQO)
    assert not ok, "a fold over different (reordered) segments must be rejected"


def t_bundle_declared_public_has_no_authority():
    """The bundle's OWN copy of the fold statement is dead weight — the verifier rebuilds it from the proofs'
    public parts. Corrupting the copy must change nothing (that is what verifier-authoritative means)."""
    bad = copy.deepcopy(_BUNDLE)
    bad["fold_public"]["publics"][0]["roots"][0] = ("00" * 8,)
    ok, why = RV.verify(_PUBLICS, TRANS_X2, _BNDS, bad, num_queries_outer=NQO)
    assert ok, f"the prover's declared statement must carry no authority: {why}"


def t_tampered_seam_rejected():
    """The layer-0 seam value is DECLARED by the prover but pinned as a fold boundary whose SELLO constraint
    ties it to the Merkle-authenticated leaf — lying about it must break the in-circuit membership."""
    bad = copy.deepcopy(_PUBLICS)
    bad[1]["layer0"][0] = (bad[1]["layer0"][0] + 1) % P
    ok, _ = RV.verify(bad, TRANS_X2, _BNDS, _BUNDLE, num_queries_outer=NQO)
    assert not ok, "a declared layer-0 value != the committed one must be rejected (seam integrity)"


def t_wrong_seed_rejected():
    """Claiming segment 1 started from a different seed: comp's boundary values change, the recomputed
    composition no longer meets the (authenticated) layer-0 target."""
    bad = [list(bl) for bl in _BNDS]
    bad[1] = [(0, 0, (SEED + 1) % P)]
    ok, _ = RV.verify(_PUBLICS, TRANS_X2, bad, _BUNDLE, num_queries_outer=NQO)
    assert not ok, "a lied segment seed must be rejected by the composition half"


if __name__ == "__main__":
    check(f"K→1: {K} chained proofs verify in ONE bundle (public parts only)", t_k_to_1_verifies)
    check("wrong AIR rejected by composition half", t_wrong_air_rejected)
    check("fold against a reordered/wrong statement rejected", t_fold_wrong_statement_rejected)
    check("bundle's declared public has NO authority (verifier rebuilds it)", t_bundle_declared_public_has_no_authority)
    check("tampered layer-0 seam value rejected by in-circuit membership", t_tampered_seam_rejected)
    check("lied segment seed rejected", t_wrong_seed_rejected)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
