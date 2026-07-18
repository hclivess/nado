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

    # CANONICAL FILTER (fork-stale regression): a checkpoint whose anchor is not the canonical block
    # at its height (missing or mismatched number->hash row) must never be advertised — a donor that
    # re-anchored off its old fork otherwise baits fresh joiners onto a dead chain no one can extend
    # (observed live: dead-fork checkpoint 13000 advertised while the canonical chain stood at 49k).
    assert snapshot_ops.latest_final_checkpoint_height(9) is None, "unanchored checkpoint advertised"
    kv_ops.block_index_put(5, "x" * 64)    # canonical block at 5 is a DIFFERENT block
    assert snapshot_ops.latest_final_checkpoint_height(9) is None, "fork-stale checkpoint advertised"
    kv_ops.block_index_del(5, "x" * 64)
    kv_ops.block_index_put(5, "a" * 64)    # the anchor IS canonical at 5 -> advertised once finalized

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


print(f"\n{'ALL SNAPSHOT-CHECKPOINT CHECKS PASSED' if fails == 0 else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
