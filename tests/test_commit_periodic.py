"""
COMMITTED periodic columns (stark.prove/verify commit_periodic=) — the succinct-verify enabler. A dense
periodic column normally costs the verifier an O(T) poly_eval PER QUERY (stark._per_evaluator dense branch).
Committing it instead (Merkle root + one opening per query) makes that O(log N) — the last O(epoch) term in the
settlement verifier (the exec AIR's program/io/args tables).

Differential validation (money-path discipline): the committed path must give the SAME accept/reject as the
public path on the same trace, commit_periodic=None must be byte-identical to omitting it, and the committed
cells/roots must be tamper-evident. The committed root equals the honest table's LDE commit — so a caller CAN
bind it to the public statement (the O(1) binding is a chain proof against io_commitment; the recompute here is
just the correctness cross-check).

Run: python3 tests/test_commit_periodic.py
"""
import os, sys, copy, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import stark, field as F, backend as B, merkle

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

T, NQ = 8, 4
# one genuinely-DENSE periodic column (every row distinct ⇒ exercises the O(T) dense-eval path)
PER = [[(i * i * 7 + 3) % F.P for i in range(T)]]
TRACE = [[PER[0][i]] for i in range(T)]                 # trace col0 == the periodic column, every row


def transitions():
    # cur[0] must equal the periodic value at this row (holds on rows 0..T-2 under the transition vanishing set)
    return [lambda cur, nxt, per: F.sub(cur[0], per[0])]


def _prove(**kw):
    return stark.prove(TRACE, transitions(), [], periodic=PER, max_degree=2, num_queries=NQ, **kw)


def _verify(proof, **kw):
    return stark.verify(proof, transitions(), [], periodic=PER, max_degree=2, num_queries=NQ, **kw)


def t_public_and_committed_both_accept():
    ok, why = _verify(_prove())
    assert ok, f"public periodic must verify: {why}"
    p = _prove(commit_periodic=[0])
    assert "per_roots" in p and len(p["per_roots"]) == 1, "committed proof must carry one per-root"
    ok, why = _verify(p, commit_periodic=[0])
    assert ok, f"committed periodic must verify: {why}"


def t_default_byte_identical():
    """commit_periodic=None must be byte-identical to omitting it (the live shielded-pool/exec proofs path)."""
    a = _prove()
    b = _prove(commit_periodic=None)
    assert repr(a) == repr(b), "commit_periodic=None must not perturb the proof"
    assert "per_roots" not in a, "no committed columns ⇒ no per_roots key"


def t_tampered_committed_cell_rejected():
    p = _prove(commit_periodic=[0])
    bad = copy.deepcopy(p)
    bad["openings"][0]["per"][0]["val"] = (int(bad["openings"][0]["per"][0]["val"]) + 1) % F.P
    ok, _ = _verify(bad, commit_periodic=[0])
    assert not ok, "a tampered committed periodic cell must be rejected (opening fails)"


def t_wrong_root_rejected():
    """A verifier-supplied per-root that isn't the committed one rejects the proof (this is the hook the caller
    uses to BIND the committed column to the public statement — a wrong table ⇒ wrong root ⇒ reject)."""
    b = B.DEFAULT
    p = _prove(commit_periodic=[0])
    N, OFF = p["N"], stark.OFF
    other = stark._coset_evaluate(F.interpolate(stark._per_expand([(v + 1) % F.P for v in PER[0]], T)), N, OFF)
    wrong_root, _ = merkle.commit(other, b)             # a DIFFERENT table's LDE commit
    assert wrong_root != p["per_roots"][0], "sanity: the fabricated root must differ"
    ok, _ = _verify(p, commit_periodic=[0], periodic_roots=[wrong_root])
    assert not ok, "a per-root that doesn't match the committed column must be rejected"


def t_committed_root_binds_to_table():
    """The committed per-root == an honest commit of the table's LDE ⇒ a caller can bind it to the public
    statement. (Recompute is O(T) here for the cross-check; the production O(1) binding is a chain proof.)"""
    b = B.DEFAULT
    p = _prove(commit_periodic=[0])
    N, OFF = p["N"], stark.OFF
    lde = stark._coset_evaluate(F.interpolate(stark._per_expand(PER[0], T)), N, OFF)
    root, _ = merkle.commit(lde, b)
    assert root == p["per_roots"][0], "committed per-root must equal the honest table LDE commit"
    ok, why = _verify(p, commit_periodic=[0], periodic_roots=[root])
    assert ok, f"binding the recomputed root must still verify: {why}"


if __name__ == "__main__":
    check("public + committed periodic both accept", t_public_and_committed_both_accept)
    check("commit_periodic=None byte-identical to omitting it", t_default_byte_identical)
    check("tampered committed cell rejected", t_tampered_committed_cell_rejected)
    check("wrong periodic root rejected (the binding hook)", t_wrong_root_rejected)
    check("committed root == honest table LDE commit (bindable)", t_committed_root_binds_to_table)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
