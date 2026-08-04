"""
The root and its RECORDS half must be read at the same instant, or the proof self-check compares two
roots that were never simultaneously true.

WHY THIS EXISTS. state_root = rnode(kv half, RECORDS half). A settle-with-proof pins one (cursor, root)
pair and then spends MINUTES proving it. Settling runs DETACHED from the block-application tail
(e1000cbd) — deliberately, so the tail keeps applying blocks at full speed while the proof builds.

The capture site said:

    # Capture (cursor, root) ONCE — the tail loop is single-task, so st does not advance during the
    # (possibly minutes-long) proving await below
    cur, root = st.cursor, st.state_root()

That was true BEFORE settling was detached. Afterwards the tail advances `st` throughout: through the
~one-HTTP-round-trip-per-block span walk, and through the whole prove. Meanwhile the proof builder
recomputed the records half from that same live `st`:

    rec_root = SST.SparseStore(EXEC_TREE_DEPTH, ER.records_projection(st)).root()

So `root` was the full root at cursor C and `rec_root` was the records half at some later cursor, and

    post_full = full_root_hex(kv_post, rec_root)  ==  root

could only hold by luck.

OBSERVED LIVE 2026-08-04:

    settle-with-proof ns=default self-check failed (span 19154->19184 not conforming) — falling back to quorum

19154 and 19184 are both in epoch 319, so the dividend gate guarantees no dividend moved the records
across that span. The records still differed — because they were read at a different TIME, not a
different epoch. That is the tell: a "not conforming" span that the conformance rules say conforms.

THE FIX: ExecState.settle_snapshot() returns (cursor, root, records_root, mut_gen) under the mutate lock,
and the proof builder uses the records root it was handed instead of recomputing one.

Run: python3 tests/test_settle_snapshot_atomic.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_snapatomic_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


from execnode import exec_root as ER            # noqa: E402
from execnode.stark import storage_tree as SST  # noqa: E402
from execnode.state import ExecState            # noqa: E402

st = ExecState(os.path.join(os.environ["HOME"], "exec_state.json"))
st.bridge["alice"] = 100
st.dividend["bob"] = 7
st._touch()

# ---- the capture is internally consistent ----------------------------------------------------------
cur, root, rec_root, gen = st.settle_snapshot()
kv_store, rec_store = st._sparse_stores()
check("settle_snapshot returns the CURRENT cursor", cur == st.cursor)
check("settle_snapshot's root equals state_root()", root == st.state_root())
check("settle_snapshot's records root equals the live records half", rec_root == rec_store.root())
check("root really is rnode(kv, records) of the captured halves",
      ER.full_root_hex(kv_store.root(), rec_root) == root)

# ---- THE CORE PROPERTY: the captured pair survives later mutation ------------------------------------
# This is the whole bug. Advance the state the way the detached tail does, then check that the captured
# records root still reconstructs the captured root — and that a FRESHLY recomputed one does not.
st.bridge["carol"] = 55                        # the tail applies a block that moves a balance
st._touch()

fresh_rec = SST.SparseStore(ER.DEPTH, ER.records_projection(st)).root()
check("the records half genuinely moved (the test is exercising the hazard)", fresh_rec != rec_root)
check("the CAPTURED records root still reconstructs the CAPTURED root",
      ER.full_root_hex(kv_store.root(), rec_root) == root)
check("a FRESHLY recomputed records root does NOT reconstruct the captured root — the shipped bug",
      ER.full_root_hex(kv_store.root(), fresh_rec) != root)

# ---- mut_gen exposes that drift ---------------------------------------------------------------------
cur2, root2, rec2, gen2 = st.settle_snapshot()
check("mut_gen advances when the state is mutated", gen2 > gen)
check("a re-capture after mutation yields a different root", root2 != root)
check("...and its own records root reconstructs ITS root",
      ER.full_root_hex(st._sparse_stores()[0].root(), rec2) == root2)

# ---- an untouched state is stable -------------------------------------------------------------------
a = st.settle_snapshot()
b = st.settle_snapshot()
check("two captures with no mutation between them are identical", a == b)

# ---- the builder must actually accept and prefer the passed-in root ----------------------------------
import inspect                                                    # noqa: E402
import execnode.execnode as E                                     # noqa: E402
sig = inspect.signature(E._build_settlement_proof)
check("_build_settlement_proof takes the captured records root", "rec_root_at_cur" in sig.parameters)
src = open(E.__file__).read()
check("the capture site uses settle_snapshot", "st.settle_snapshot()" in src)
check("the builder prefers the passed-in records root",
      "rec_root_at_cur if rec_root_at_cur is not None" in src)
# The stale claim is QUOTED in the replacement comment (that is how the correction explains itself), so
# its mere presence proves nothing. What must be true is that it is no longer asserted as CURRENT.
check("the single-task claim is now marked as no longer true",
      "That was true when settling was AWAITED from the tail" in src)

print()
print("ALL PASS — the root and its records half are captured together and survive the tail advancing"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
