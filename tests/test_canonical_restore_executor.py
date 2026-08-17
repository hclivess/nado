"""END-TO-END dry run of the re-anchor canonical restore against a REAL (throwaway) LMDB + segment store.

The planner (ops/canonical_restore) is pure and tested exhaustively; this exercises the EXECUTOR
(loops/core_loop._restore_canonical_chain) — the part that touches kv_ops, save_block and the donor — because
that path is only ever otherwise run during a live wedge recovery, on a node that is already in trouble.
A crash there wedges the recovery; a wrong step there loses history. So it runs here first.

ISOLATION. Everything derives from get_home() == ~/nado, so this test sets HOME to a scratch dir BEFORE
importing anything from the node — the live LMDB is never opened (importing node modules against the live
data dir wedged prod once; see memory). Run only via the wrapper at the bottom, which re-execs with HOME set.

Scenario (the 01:47 incident shape, scaled down): our chain 'a' 0..150 with bodies for all of it; canonical
is 'a' up to 100 then 'b' 101..300; the donor holds the whole canonical chain; the imported index is windowed
to [200, 300] so the fork point sits BELOW the window (undetermined range) — the hardest shape. Expected:
  * bodies 0..100 KEPT (never re-fetched), fork bodies 101..150 unreferenced,
  * canonical 101..300 fetched from the donor (rollback window synchronously, rest in the deep fill),
  * index rows for 0..199 re-put so get_block_number resolves the whole chain,
  * earliest = 0 once the deep fill finishes.

Run: python3 tests/test_canonical_restore_executor.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time

if os.environ.get("_CR_EXEC_CHILD") != "1":
    tmp = tempfile.mkdtemp(prefix="cr_exec_")
    env = dict(os.environ, HOME=tmp, _CR_EXEC_CHILD="1", NADO_ALLOW_PYTHON_KERNELS="1",
               PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, os.path.abspath(__file__)], env=env)
    sys.exit(r.returncode)

# ---- child: HOME is a scratch dir from here on -------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs(os.path.expanduser("~/nado/index"), exist_ok=True)
os.makedirs(os.path.expanduser("~/nado/blocks"), exist_ok=True)

from ops import kv_ops, segment_store, snapshot_ops                    # noqa: E402
from ops.block_ops import save_block, get_block_number, get_block      # noqa: E402
from ops import canonical_restore as CR                                # noqa: E402
import loops.core_loop as core                                          # noqa: E402

FAILS = []


def check(name, fn):
    try:
        fn()
        print("PASS  " + name)
    except AssertionError as e:
        print("FAIL  " + name + " — " + str(e))
        FAILS.append(name)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"FAIL  {name} — {type(e).__name__}: {e}")
        FAILS.append(name)


class _Log:
    def __getattr__(self, _n):
        return lambda *a, **k: None


def mk_block(chain, h, parent_hash):
    """A body whose block_hash is deterministic per (chain, h). Genesis is exempt from the hash-consistency
    check in save_block; other blocks skip it because we omit the hashed field set on purpose (the check
    only runs when ALL hashed fields are present) — this test is about storage/plan, not block hashing."""
    return {"block_number": h, "block_hash": f"{chain}{h:08x}".ljust(64, "0"), "parent_hash": parent_hash,
            "block_transactions": [], "chain_id": "test"}


def build_chain(letter, lo, hi, base_parent):
    out, ph = [], base_parent
    for h in range(lo, hi + 1):
        b = mk_block(letter, h, ph)
        out.append(b)
        ph = b["block_hash"]
    return out


# our chain a: 0..150 ; canonical: a 0..100 + b 101..300
A = build_chain("a", 0, 150, "0" * 64)
canon = A[:101] + build_chain("b", 101, 300, A[100]["block_hash"])
DONOR = {b["block_hash"]: b for b in canon}                              # the donor holds all of canonical

# ---- seed OUR pre-reanchor disk: bodies + index for chain a ----------------------------------------
for b in A:
    save_block(b, logger=_Log())
kv_ops.block_index_put_many([(b["block_number"], b["block_hash"]) for b in A])
old_index = dict(kv_ops.block_by_num_items())
assert len(old_index) == 151

# ---- simulate import: index replaced by the donor's WINDOWED payload [200, 300] --------------------
def _wipe_index(txn):
    for name in ("block_by_num", "block_by_hash"):
        txn.drop(kv_ops._dbs()[name], delete=False)
kv_ops._write(_wipe_index)
kv_ops.block_index_put_many([(b["block_number"], b["block_hash"]) for b in canon if b["block_number"] >= 200])
snapshot_ops.adopt_new_identity(logger=_Log())                            # must KEEP block_loc now
anchor = canon[300]
save_block(anchor, logger=_Log())

# ---- a fake node with just what the executor touches --------------------------------------------------
class _MS:
    archive = True
    port = 0
    earliest_block = A[0]
    peers = []

class _Node:
    memserver = _MS()
    logger = _Log()

node = _Node()
# bind the real methods
for m in ("_restore_canonical_chain", "_start_deep_fill", "_start_tx_reindex", "_maybe_advance_earliest"):
    setattr(_Node, m, getattr(core.CoreClient, m))

# donor = DONOR dict, served through the same fetch_block the executor calls
async def _fake_fetch(source, port, block_hash):
    return DONOR.get(block_hash)
snapshot_ops.fetch_block = _fake_fetch
core.snapshot_ops.fetch_block = _fake_fetch


def t_adopt_new_identity_kept_our_bodies():
    for b in A:
        assert kv_ops.block_loc_get(b["block_hash"]) is not None, f"body {b['block_number']} was wiped"


oldest = {}
def t_executor_runs_and_returns_a_contiguous_earliest():
    oldest["b"] = node._restore_canonical_chain(old_index, anchor, "donor")
    assert isinstance(oldest["b"], dict), "executor returned no block"


def t_history_below_the_fork_point_was_kept_not_refetched():
    for b in A[:101]:
        assert kv_ops.block_loc_get(b["block_hash"]) is not None, f"canonical block {b['block_number']} lost"


def t_fork_bodies_were_unreferenced():
    for b in A[101:]:
        assert kv_ops.block_loc_get(b["block_hash"]) is None, f"fork body {b['block_number']} still referenced"


def t_deep_index_rows_were_re_put():
    for h in (0, 50, 100, 150, 199):
        got = kv_ops.hash_by_number(h)
        want = canon[h]["block_hash"]
        assert got == want, f"index at {h}: {got!r} != canonical {want!r}"


def t_deep_fill_completes_and_earliest_reaches_genesis():
    th = getattr(node, "_deep_fill_thread", None)
    assert th is not None, "no deep fill started on an archive node"
    th.join(timeout=60)
    assert not th.is_alive(), "deep fill did not finish"
    # every canonical body present, whole chain resolvable by height
    for h in range(0, 301):
        assert get_block_number(h), f"canonical block {h} unresolvable after restore"
    node.memserver.earliest_block = oldest["b"]
    node._maybe_advance_earliest()
    assert int(node.memserver.earliest_block["block_number"]) == 0, \
        f"earliest is {node.memserver.earliest_block['block_number']}, not 0"


def t_tx_reindex_ran_and_cleaned_its_marker():
    th = getattr(node, "_tx_reindex_thread", None)
    if th:
        th.join(timeout=60)
    assert not os.path.exists(os.path.expanduser("~/nado/index/tx_reindex.json")), \
        "reindex marker left behind after a complete run"


for name, fn in [(n, f) for n, f in list(globals().items()) if n.startswith("t_")]:
    check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "EXECUTOR RESTORES THE CANONICAL CHAIN ON REAL STORES")
sys.exit(1 if FAILS else 0)
