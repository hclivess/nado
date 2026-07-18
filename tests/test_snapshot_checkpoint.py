"""
Persistent state-checkpoint unit checks (rolling-node sync).

Proves the core correctness the old lazy-build path never exercised:
- a checkpoint captures the CURRENT account state (state@C by construction),
- it is advertised only once finalized (advertise-when-final),
- it round-trips off disk with an intact manifest hash,
- importing it restores EXACTLY the checkpointed state even over a diverged/corrupt DB,
- a tampered chunk is rejected (sha256 + re-derived state_root gate),
- drop_checkpoints_above prunes reverted checkpoints.
"""
import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_snapckpt_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers", "snapshots"):
    os.makedirs(os.path.expanduser(f"~/nado/{d}"), exist_ok=True)

import logging
logger = logging.getLogger("snap"); logger.addHandler(logging.NullHandler())

from genesis import create_indexers
create_indexers()

from ops import snapshot_ops, kv_ops
from ops.account_ops import create_account, get_account, change_balance

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def t1():
    """Prove a checkpoint captures current state, is advertised only once finalized, round-trips off disk with an intact manifest (incl. the entry_count regression), and its import restores EXACT state over a diverged DB."""
    create_account("alice", balance=1000, produced=5, bonded=200)
    create_account("bob", balance=42, bonded=0)

    # capture checkpoint @5 == current state
    snapshot_ops.persist_checkpoint(height=5, block_hash="a" * 64, protocol=2, version="v")
    assert snapshot_ops.list_checkpoint_heights() == [5]

    # advertise-when-final: NOT offered until finalized_height >= 5 (reorg safety)
    assert snapshot_ops.latest_final_checkpoint_height(4) is None, "checkpoint advertised before final"
    assert snapshot_ops.latest_final_checkpoint_height(9) == 5

    # manifest round-trips off disk with intact hash (donor->wire->joiner determinism)
    manifest = snapshot_ops.load_checkpoint_manifest(5)
    assert manifest["snapshot_height"] == 5
    assert manifest["snapshot_hash"] == snapshot_ops.manifest_hash(manifest), "manifest hash round-trip"
    chunks = [snapshot_ops.load_checkpoint_chunk(5, i) for i in range(manifest["chunk_count"])]
    assert all(c is not None for c in chunks), "missing chunk on disk"

    # REGRESSION: the fetch-side manifest validation (ops.snapshot_ops.fetch_snapshot) must ACCEPT a freshly
    # built manifest. It once read a stale `account_count` after the full-state rewrite renamed it to
    # `entry_count`, so it rejected EVERY real manifest with "inconsistent counts" and no node could snapshot.
    ec = manifest.get("entry_count")
    assert isinstance(ec, int) and ec == sum(int(c["rows"]) for c in manifest["chunks"]), \
        "fetch-side count check would REJECT a valid manifest (entry_count vs chunk rows mismatch)"
    assert manifest["chunk_count"] == len(manifest["chunks"]), "chunk_count vs chunks length mismatch"

    # a JOINER whose DB has diverged (mutated) must end up with the EXACT checkpointed state
    with kv_ops.write_txn():
        change_balance("alice", 999_999, logger=logger)
    assert get_account("alice")["balance"] == 1_000 + 999_999
    assert snapshot_ops.import_snapshot(manifest, chunks, logger=logger), "import failed"
    a, b = get_account("alice"), get_account("bob")
    assert (a["balance"], a["produced"], a["bonded"]) == (1000, 5, 200), f"alice not restored: {a}"
    assert (b["balance"], b["produced"], b["bonded"]) == (42, 0, 0), f"bob not restored: {b}"
check("capture -> advertise-when-final -> import restores EXACT state (over a diverged DB)", t1)


def t2():
    """Prove a tampered chunk is rejected by the sha256/state_root gate BEFORE any state is written."""
    manifest = snapshot_ops.load_checkpoint_manifest(5)
    chunks = [snapshot_ops.load_checkpoint_chunk(5, i) for i in range(manifest["chunk_count"])]
    bad = bytearray(chunks[0]); bad[len(bad) // 2] ^= 0xFF
    assert not snapshot_ops.import_snapshot(manifest, [bytes(bad)] + chunks[1:], logger=logger), \
        "tampered chunk was NOT rejected"
    # state must be untouched (rejection happens before the write txn)
    assert get_account("alice")["balance"] == 1000, "tampered import mutated state"
check("tampered chunk rejected before any write (sha256 / state_root gate)", t2)


def t3():
    """Prove drop_checkpoints_above prunes checkpoints above the new tip after a rollback."""
    snapshot_ops.persist_checkpoint(height=10, block_hash="b" * 64, protocol=2, version="v")
    assert snapshot_ops.list_checkpoint_heights() == [5, 10]
    snapshot_ops.drop_checkpoints_above(7)      # a rollback to tip 7
    assert snapshot_ops.list_checkpoint_heights() == [5], "reverted checkpoint not dropped"
    # re-anchor hygiene: the post-reanchor sweep drops EVERY checkpoint (all were captured on the
    # abandoned identity); fresh canonical ones re-capture at the next interval boundaries
    assert snapshot_ops.drop_all_checkpoints() == 1
    assert snapshot_ops.list_checkpoint_heights() == [], "pre-reanchor checkpoint survived the sweep"
check("drop_checkpoints_above prunes checkpoints above the new tip", t3)


def t4():
    """Prove full producer-selection state (registered/fidelity, recert lease, bonded) survives checkpoint export/import, so a snapshot-synced open-lane miner cannot fork."""
    # CRITICAL fix: the FULL producer-selection state must survive a snapshot, else a snapshot-synced
    # OPEN-LANE miner derives a different registry and forks on tail replay. Carry registered/fidelity
    # (open lane) + the recert_by_epoch lease. bonded ramp (bond_since) rides along the same way.
    create_account("miner", balance=0, registered=1, fidelity=7, bonded=500)
    with kv_ops.write_txn():
        kv_ops.recert_put("miner", 3)          # an open-lane presence lease at epoch 3
    assert kv_ops.recert_addresses_after(-1) == {"miner"}
    snapshot_ops.persist_checkpoint(height=15, block_hash="c" * 64, protocol=2, version="v")
    m = snapshot_ops.load_checkpoint_manifest(15)
    ch = [snapshot_ops.load_checkpoint_chunk(15, i) for i in range(m["chunk_count"])]
    # wipe the open-lane state, then import and confirm it is fully reconstructed
    with kv_ops.write_txn():
        kv_ops.account_set("miner", "registered", 0)
        kv_ops.account_set("miner", "fidelity", 0)
        kv_ops.recert_del("miner", 3)
    assert kv_ops.recert_addresses_after(-1) == set()
    assert snapshot_ops.import_snapshot(m, ch, logger=logger)
    acc = get_account("miner")
    assert acc["registered"] == 1 and acc["fidelity"] == 7 and acc["bonded"] == 500, f"producer state lost: {acc}"
    assert kv_ops.recert_addresses_after(-1) == {"miner"}, "recert lease not carried -> open-lane fork"
check("producer-selection state (registered/fidelity + recert lease) survives the snapshot", t4)


def t5():
    """Prove the BOOT SWEEP drops every checkpoint that does not anchor to the canonical chain
    (pre-invariant poison — the live 13000 wedge) and keeps the ones that do."""
    # add a canonical checkpoint and a fork-stale one (the keep=2 capture prune drops t4's @15),
    # then sweep: only the canonical one may remain.
    snapshot_ops.persist_checkpoint(height=20, block_hash="d" * 64, protocol=2, version="v")
    snapshot_ops.persist_checkpoint(height=30, block_hash="e" * 64, protocol=2, version="v")
    kv_ops.block_index_put(20, "d" * 64)      # canonical block at 20 == this checkpoint's anchor
    kv_ops.block_index_put(30, "x" * 64)      # canonical block at 30 is a DIFFERENT block (fork-stale)
    assert snapshot_ops.list_checkpoint_heights() == [20, 30]
    assert snapshot_ops.sweep_noncanonical_checkpoints() == 1, "sweep count wrong"
    assert snapshot_ops.list_checkpoint_heights() == [20], "sweep kept poison or dropped the canonical one"
check("boot sweep drops fork-stale checkpoints, keeps canonical ones", t5)


def t6():
    """Prove adopt_new_identity retires EVERYTHING the abandoned chain wrote that a snapshot does not
    carry — tx history rows, block bodies + locators, GC reverts, own checkpoints — while the carried
    consensus state (accounts) survives, and the block store still works afterwards."""
    from ops import segment_store
    # artifacts of the "abandoned" chain: a tx-history row, a GC revert, a block body + locator
    with kv_ops.write_txn() as txn:
        txn.put(b"deadbeef", b"x", db=kv_ops._dbs()["tx"])
        txn.put(b"gcrev", b"y", db=kv_ops._dbs()["gc_revert"])
    seg, off, ln = segment_store.append("ab" * 32, b"orphaned-fork-body")
    with kv_ops.write_txn():
        kv_ops.block_loc_put("ab" * 32, seg, off, ln)
    assert kv_ops.block_loc_get("ab" * 32) is not None
    assert snapshot_ops.list_checkpoint_heights() == [20]      # survivor from t5

    snapshot_ops.adopt_new_identity(logger=logger)

    # everything non-carried is GONE
    assert kv_ops.block_loc_get("ab" * 32) is None, "block locator survived the identity change"
    with kv_ops.write_txn() as txn:
        assert txn.get(b"deadbeef", db=kv_ops._dbs()["tx"]) is None, "tx history survived"
        assert txn.get(b"gcrev", db=kv_ops._dbs()["gc_revert"]) is None, "gc revert survived"
    assert snapshot_ops.list_checkpoint_heights() == [], "own checkpoints survived"
    assert segment_store.active_segment() == 0
    import os as _os
    segdir = segment_store.segments_dir()
    assert [n for n in _os.listdir(segdir) if n.startswith("seg-")] == ["seg-00000000.dat"], \
        "old segment files survived the identity change"
    # carried consensus state is untouched (import_snapshot owns replacing it)...
    assert get_account("alice")["balance"] == 1000, "carried state was harmed by the wipe"
    # ...and the store keeps working on the new identity
    seg2, _off2, _ln2 = segment_store.append("cd" * 32, b"first-new-identity-body")
    assert seg2 == 0
check("adopt_new_identity wipes all non-carried artifacts, keeps carried state, store survives", t6)


print(f"\n{'ALL SNAPSHOT-CHECKPOINT CHECKS PASSED' if fails == 0 else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
