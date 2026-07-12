"""
Append-only segment block store (ops/segment_store.py + kv_ops block_loc + block_ops wiring):
  1. round-trip: save_block -> get_block/load_block_from_hash, with the DERIVED child_hash
  2. crash safety: a torn tail record is truncated on init; a valid-but-unreferenced record is inert
  3. corruption: a flipped byte in a record = clean miss, never junk
  4. rollover: appends roll to new segment files past NADO_SEGMENT_BYTES
  5. re-save (replay) repoints the locator, last write wins
  6. rollback atomicity: unindex_block inside an ABORTED txn restores locator + index
  7. migration: legacy flat + sharded *.block files fold into segments and read back identically

Run: python3 tests/test_segment_store.py
"""
import os, sys, tempfile, traceback, logging
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_segstore_")
os.environ["NADO_SEGMENT_BYTES"] = "2048"   # tiny segments -> rollover under test data sizes
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

logger = logging.getLogger("segstore"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from ops import kv_ops, segment_store
from ops.block_ops import save_block, get_block, load_block_from_hash, unindex_block, migrate_block_store, \
    block_content_hash, construct_block
from ops.data_ops import get_home

HOME = get_home()
fails = 0


def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def make_block(number, parent_hash="00" * 32, txs=()):
    """A real, hash-consistent block dict (construct_block computes the canonical hash)."""
    return construct_block(block_timestamp=1000 + number, block_number=number, parent_hash=parent_hash,
                           creator="ndo" + "ab" * 23, transaction_pool=list(txs), block_reward=0)


def t1_roundtrip_and_derived_child():
    b1 = make_block(1)
    b2 = make_block(2, parent_hash=b1["block_hash"])
    assert save_block(b1, logger) and save_block(b2, logger)
    kv_ops.block_index_put(1, b1["block_hash"])
    kv_ops.block_index_put(2, b2["block_hash"])
    r1 = get_block(b1["block_hash"])
    assert r1 and r1["block_hash"] == b1["block_hash"], "round-trip failed"
    assert block_content_hash(r1) == b1["block_hash"], "content survives byte-exact"
    # child_hash DERIVED from the number->hash index, not stored
    assert r1["child_hash"] == b2["block_hash"], "child must derive from the index"
    assert get_block(b2["block_hash"])["child_hash"] is None, "tip has no child"
    assert load_block_from_hash(b1["block_hash"], logger)["child_hash"] == b2["block_hash"]
    assert get_block("f" * 64) is False, "unknown hash is a clean miss"
    assert get_block("../../etc/passwd") is False, "malformed hash refused"


def t2_torn_tail_truncated_on_init():
    """A crash mid-append leaves a torn record at the active tail; a fresh store init truncates it,
    and every previously-referenced record still reads back."""
    b = make_block(3)
    save_block(b, logger)
    seg = segment_store.active_segment()
    path = segment_store.segment_path(seg)
    good_size = os.path.getsize(path)
    with open(path, "ab") as f:                      # simulate a torn append (header claims more than exists)
        f.write(segment_store.MAGIC + (99999).to_bytes(4, "big") + b"\x00" * 40)
    segment_store._stores.clear()                    # force re-init (fresh process)
    segment_store.init()
    assert os.path.getsize(path) == good_size, "torn tail must be truncated back to the last valid record"
    assert get_block(b["block_hash"])["block_hash"] == b["block_hash"], "existing records survive the repair"


def t3_corrupt_record_is_clean_miss():
    b = make_block(4)
    save_block(b, logger)
    loc = kv_ops.block_loc_get(b["block_hash"])
    path = segment_store.segment_path(loc[0])
    with open(path, "r+b") as f:                     # flip one payload byte -> crc must fail
        f.seek(loc[1] + segment_store.HEADER_SIZE + 5)
        orig = f.read(1)
        f.seek(loc[1] + segment_store.HEADER_SIZE + 5)
        f.write(bytes([orig[0] ^ 0xFF]))
    segment_store._stores.clear(); segment_store.init()
    assert get_block(b["block_hash"]) is False, "corrupt record must be a miss, never junk"
    # heal it back for later tests
    with open(path, "r+b") as f:
        f.seek(loc[1] + segment_store.HEADER_SIZE + 5)
        f.write(orig)
    assert get_block(b["block_hash"]) is not False, "restored record reads again"


def t4_rollover_and_live_counts():
    start_seg = segment_store.active_segment()
    blocks = [make_block(100 + i, txs=[]) for i in range(30)]
    for b in blocks:
        save_block(b, logger)
    assert segment_store.active_segment() > start_seg, "appends must roll past NADO_SEGMENT_BYTES"
    live = kv_ops.seg_live_counts()
    assert sum(live.values()) >= 30, "every save must be counted live in some segment"
    for b in blocks:
        assert get_block(b["block_hash"]) is not False, "reads span segment boundaries"


def t5_resave_repoints_last_write_wins():
    b = make_block(5)
    save_block(b, logger)
    loc1 = kv_ops.block_loc_get(b["block_hash"])
    before = sum(kv_ops.seg_live_counts().values())
    b_resigned = dict(b)
    b_resigned["block_timestamp"] = 999999           # non-hashed field differs (e.g. a re-fetched copy)
    save_block(b_resigned, logger)
    loc2 = kv_ops.block_loc_get(b["block_hash"])
    assert loc1 != loc2, "re-save must append a fresh record and repoint"
    assert get_block(b["block_hash"])["block_timestamp"] == 999999, "last write wins"
    after = sum(kv_ops.seg_live_counts().values())
    assert after == before, f"re-save must not change the total live count (old-- new++), {before}->{after}"


def t6_unindex_atomic_with_txn_abort():
    """unindex_block joins the caller's write txn: an ABORTED rollback must restore BOTH the
    number<->hash mapping and the body locator (the old file unlink could not be undone)."""
    b = make_block(6)
    save_block(b, logger)
    kv_ops.block_index_put(6, b["block_hash"])
    try:
        with kv_ops.write_txn():
            unindex_block(b, logger)
            assert kv_ops.block_loc_get(b["block_hash"]) is None, "locator gone inside the txn"
            raise RuntimeError("abort the rollback")
    except RuntimeError:
        pass
    assert kv_ops.block_loc_get(b["block_hash"]) is not None, "aborted txn must restore the locator"
    assert kv_ops.hash_by_number(6) == b["block_hash"], "aborted txn must restore the index"
    # and a COMMITTED unindex removes both
    with kv_ops.write_txn():
        unindex_block(b, logger)
    assert kv_ops.block_loc_get(b["block_hash"]) is None and kv_ops.hash_by_number(6) is None
    assert get_block(b["block_hash"]) is False, "an unreferenced orphan can never be served"


def t7_migration_from_legacy_files():
    """Legacy flat AND sharded *.block files fold into segments, read back identically, files removed."""
    from ops.block_ops import _pack_block
    legacy = []
    for i in range(3):
        b = make_block(200 + i)
        legacy.append(b)
    flat = f"{HOME}/blocks/{legacy[0]['block_hash']}.block"
    with open(flat, "wb") as f:
        f.write(_pack_block(legacy[0]))
    for b in legacy[1:]:
        shard = f"{HOME}/blocks/{b['block_hash'][:3]}"
        os.makedirs(shard, exist_ok=True)
        with open(f"{shard}/{b['block_hash']}.block", "wb") as f:
            f.write(_pack_block(b))
    moved = migrate_block_store(logger)
    assert moved == 3, f"expected 3 files migrated, got {moved}"
    for b in legacy:
        got = get_block(b["block_hash"])
        assert got and block_content_hash(got) == b["block_hash"], "migrated body reads back byte-exact"
    assert not os.path.exists(flat), "legacy flat file removed"
    assert migrate_block_store(logger) == 0, "second run is a no-op (idempotent)"


for name, fn in sorted((n, f) for n, f in list(globals().items())
                       if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)

print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
