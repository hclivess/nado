"""
Bulk state-snapshot sync over P2P.

Instead of replaying every block from genesis (O(chain height), unbounded as the
network ages), a joining/behind node downloads a verified snapshot of account
state at a recent checkpoint height C and then replays only the short C..tip tail.

The snapshot is the FULL consensus state at height C — every kv_ops.SNAPSHOT_DBS sub-DB
(account docs incl. registered/fidelity, totals, meta replay-guards + finalized floor,
recerts/recert_by_epoch, bond_since, commits/reveals, attestations, unbonds, aliases,
htlcs, settlements, treasury). Carrying the WHOLE state (not just balances) is what lets
a snapshot-synced node derive the SAME producer set and validate the C+1..tip tail. It is
split into deterministic chunks so it can be fetched in parallel, and carries a `state_root`
(a blake2b Merkle root over the (db,key,value) entries) so *any* peer re-derives the
identical root from its own DB — which is what lets a joiner accept a snapshot only when a
quorum agrees on its hash (or, for a lone donor, only a trusted operator seed).

The block + tx HISTORY indexes are intentionally NOT part of the snapshot — they are
explorer/history only and are rebuilt by replaying the tail. Snapshots verify against the
chain by anchoring to the block hash at C and replaying the tail through normal validation.
"""
import hashlib
import os
import shutil

from ops import codec
from protocol import INDEX_RETENTION_NUM, INDEX_RETENTION_HASH

from ops.data_ops import get_home
from ops import kv_ops
from ops import segment_store

# how many state entries (db, key, value triples) go into one transferable chunk
CHUNK_ROWS = int(os.environ.get("NADO_SNAPSHOT_CHUNK_ROWS", "25000"))
# checkpoints are captured at heights that are multiples of this (a checkpoint is only ADVERTISED once
# finalized, so it is always reorg-safe — no separate finality margin needed). Smaller = joiners see a
# fresher checkpoint sooner (shorter tail replay) at the cost of more frequent captures.
CHECKPOINT_INTERVAL = int(os.environ.get("NADO_SNAPSHOT_INTERVAL", "1000"))
# Minimum RESPONDING peers before a snapshot vote can be trusted (agree_snapshot's default, and the number
# the health line warns below). Two independent donors is the floor at which a super-majority means anything
# — with one, "agreement" is just that donor's word. Single source of truth so the gate and the operator
# warning can never drift apart.
SNAPSHOT_MIN_PEERS = 2


def _blake2b(data: bytes) -> str:
    """32-byte blake2b hex digest — the ONE hash used for state roots and manifest hashes, so every node
    derives identical commitments"""
    return hashlib.blake2b(data, digest_size=32).hexdigest()


def _leaf(triple) -> bytes:
    """canonical, length-framed encoding of one state entry (db_name:str, key:bytes, value:bytes) so no
    db/key/value byte pattern can collide with another entry's field boundary."""
    name, key, value = triple
    return codec.pack([name, key, value])


def merkle_root(triples) -> str:
    """deterministic blake2b Merkle root over the FULL consensus state. `triples` MUST already be in
    canonical sorted order (caller sorts). Every honest node re-derives the identical root from its own DB."""
    leaves = [hashlib.blake2b(_leaf(t), digest_size=32).digest() for t in triples]
    if not leaves:
        return _blake2b(b"")
    while len(leaves) > 1:
        if len(leaves) % 2:
            leaves.append(leaves[-1])  # duplicate last for odd counts
        leaves = [hashlib.blake2b(leaves[i] + leaves[i + 1], digest_size=32).digest()
                  for i in range(0, len(leaves), 2)]
    return leaves[0].hex()


def read_state(home=None):
    """The FULL consensus state as a canonical sorted list of (db_name, key_bytes, value_bytes) triples —
    every kv_ops.SNAPSHOT_DBS sub-DB: account docs (incl. registered/fidelity), totals, the deterministic
    meta replay-guards + finalized floor, recerts/recert_by_epoch (open-lane lease), bond_since (bonded
    ramp), commits/reveals (RANDAO beacon), attestations (FFG), unbonds, aliases, htlcs, settlements,
    treasury. This is exactly what a snapshot-synced node needs to derive the SAME producer set and validate
    the C+1..tip tail. Block + tx HISTORY indexes are excluded (the tail replay rebuilds them)."""
    kv_ops.init_env(home)
    triples = []
    # ONE MVCC snapshot across ALL sub-DBs (all_db_pairs) — a per-sub-DB txn could tear the state if a block
    # commits mid-walk, yielding a root for no committed height. CANONICALIZE empty accounts: skip any
    # all-default (absent-equivalent) account row — a zero doc reads identically to a missing one, so dropping
    # it makes the state_root INVARIANT to read-created-account residue (an betanet-7 h76000 seed-split cause).
    for name, k, v in kv_ops.all_db_pairs(kv_ops.SNAPSHOT_DBS):
        if name == "accounts" and kv_ops.account_value_is_default(v):
            continue
        triples.append((name, k, v))
    triples.sort(key=lambda t: (t[0], t[1], t[2]))
    return triples


# State carried in the snapshot for TRANSFER (a joiner's deep hash-lookbacks, block-body recovery, and
# operational metadata) but DELIBERATELY EXCLUDED from the consensus STATE ROOT, because it is NODE-LOCAL /
# PATH-DEPENDENT rather than a pure function of the canonical block sequence. The state root is committed
# into every block hash, so ANY input that two honest nodes applying the same blocks can legitimately differ
# on will fork the root and trip the fatal state-root gate. Two distinct sources of such divergence:
#
#   (1) ROOT_EXCLUDED_DBS — whole sub-DBs. block_by_num/block_by_hash are written on block ARRIVAL
#       (save_block), so their contents depend on a node's height, history-retention/pruning, and
#       orphan/fork bodies accumulated across reorgs. Including them made the root diverge between nodes
#       that agree on every block — the betanet-8 fresh-sync wedge (a catching-up node computed a different
#       as-of-parent root than the producer, tripping the gate at ~h62).
#         treasury_proposals — a WRITE-ONLY display index (the /treasury tab), NOT read by any consensus
#           path (treasury_execute takes its spend from the tx's own `data`, and quorum from treasury_votes).
#           treasury_proposal_put is first-writer-wins with NO _del, and the treasury_vote revert removes
#           only the vote — so a reorg that orphans a proposal's first vote leaves a GHOST proposal row on
#           the node that applied-then-reverted, which a forward-only/fresh-sync node lacks. That is the
#           exact execsum/divinflow rollback-asymmetry fork class; excluding it from the root (still carried
#           in the snapshot for display) makes the ghost harmless. If it is ever promoted to a consensus
#           read, it MUST first be made revert-symmetric (proposal_del + refcount) before re-inclusion.
#
#   (2) ROOT_EXCLUDED_META_KEYS — individual rows in the `meta` sub-DB that are NOT block-tx-derived:
#         finalized_height — the FFG finality floor, advanced by PEER CORROBORATION (a producer at tip
#           H>=FINALITY_DEPTH persists H-FINALITY_DEPTH; a catching-up node that does not yet consider its
#           tip corroborated leaves it at 0). Two nodes at the same tip can hold different values.
#         pruned_below     — the block-body prune watermark, advanced by LOCAL retention/pruning progress.
#       These pollute the root the moment finality first advances: at tip FINALITY_DEPTH the producer
#       commits finalized_height=1 while a fresh synchronizer still has 0, so the next block's as-of-parent
#       root differs and the gate correctly refuses it (observed exactly at block FINALITY_DEPTH+2 = 47).
#       They remain in the snapshot (a joiner needs the finality floor and prune watermark) — just not in
#       the committed root. Every meta row NOT listed here (replay guards, chain markers) IS block-derived
#       and stays in the root.
#
# Blocks are already secured by their own hash chain, and finality/pruning by their own monotonic rules;
# none of this belongs in the state commitment.
ROOT_EXCLUDED_DBS = frozenset(("block_by_num", "block_by_hash", "treasury_proposals"))
#         index_pruned_below_num / index_pruned_below_hash — the number<->hash INDEX prune watermarks,
#           advanced by LOCAL retention progress exactly like pruned_below. Omitting them forked the fleet
#           on 2026-08-14: the index prune first fires when finality crosses INDEX_RETENTION_HASH (10 000),
#           so at block 10047 every ROLLING node wrote index_pruned_below_hash into meta, its committed root
#           moved, and every ARCHIVE node — which never prunes and so never writes the row — computed the
#           old root and correctly refused to extend. A node's disk-retention policy must never be able to
#           move the consensus root; that is the whole reason this list exists.
ROOT_EXCLUDED_META_KEYS = frozenset((b"finalized_height", b"pruned_below",
                                     b"index_pruned_below_num", b"index_pruned_below_hash"))

#   (3) ROOT_EXCLUDED_META_PREFIXES — families of `meta` rows whose PRESENCE is retention / rollback-path
#       dependent rather than a pure function of the applied block sequence — the same exclusion class as
#       block storage, just living in the meta sub-DB.
#         execsum:<h> — the per-block exec-call summary. incorporate_block writes execsum:<h> AND prunes the
#           one falling out of the retention window (exec_summary_del(h - EXEC_SUMMARY_RETENTION)); but
#           rollback_one_block only deletes the block's OWN height and never restores the retention-dropped
#           row. So a node that has rolled back holds a DIFFERENT execsum set than a forward-only node at the
#           same tip — which forked the root and wedged the fleet (betanet-8 h4260: an emergency-mode
#           rollback storm dropped execsum:3301..3305 on the catching-up nodes; their l1_state_root diverged
#           from the canonical forward-only chain and the FATAL gate correctly refused them, forever). The
#           summaries stay CARRIED in the snapshot (settle-with-proof binding needs the window) — only the
#           root COMMITMENT drops them, so their retention/rollback path can never fork consensus.
#         tvprevE:<txid> / tvprevW:<txid> — the treasury re-vote REVERT JOURNAL (kv_ops.treasury_vote_prev_*):
#           the prior (existed?, weight) a re-vote overwrote, stashed to make the overwrite revertible. Like
#           every other revert journal (bond_since_revert/hb_revert/msgkey_revert/gc_revert live in _LOCAL_DBS),
#           it is rollback bookkeeping — written on apply, deleted only on revert — so a non-reverted vote
#           leaves it forever. It is deterministic (all nodes agree), so it is not a FORK, but it does not
#           belong in the consensus commitment and grows the root unbounded (2 rows/vote). Excluded here.
ROOT_EXCLUDED_META_PREFIXES = (b"execsum:", b"tvprevE:", b"tvprevW:")


def _root_triples(triples):
    """the consensus subset of a full read_state() list — everything the state root commits (block storage
    and node-local / retention-dependent meta rows excluded; see ROOT_EXCLUDED_DBS / ROOT_EXCLUDED_META_KEYS
    / ROOT_EXCLUDED_META_PREFIXES). Order-preserving, so a pre-sorted input stays sorted."""
    return [t for t in triples
            if t[0] not in ROOT_EXCLUDED_DBS
            and not (t[0] == "meta" and t[1] in ROOT_EXCLUDED_META_KEYS)
            and not (t[0] == "meta" and t[1].startswith(ROOT_EXCLUDED_META_PREFIXES))]


# state-root cache: a SINGLE ((env_path, home, write_generation), root) tuple, held as one reference so a
# reader can never pair a stale key with a newer root under concurrent replacement (GIL-atomic load/store).
# Same pattern, and the same justification, as account_ops._bonded_reg_cache.
_root_cache = [None]


def l1_state_root(home=None):
    """The canonical L1 consensus state root: merkle over read_state() MINUS the block-storage DBs. This is
    the value committed into every block hash (construct_block/verify_block) and into a snapshot manifest, so
    it MUST be a pure function of the applied block sequence — hence the block-store exclusion.

    MEMOISED on the write generation. Being a pure function of COMMITTED state is exactly what makes this
    safe: an unchanged write generation cannot have changed the root, so the cached value is bit-identical,
    not an approximation. The walk plus merkle is ~17 us/row and every leaf hash is pure-Python blake2b
    under the GIL — 4 ms at today's 1.5k rows, but ~165 ms at 11k and ~2 s at 100k, and the block we
    PRODUCE pays it twice (construct_block, then verify_block). The cache removes the second call and makes
    /state_health and _record_reject's per_db_roots free between blocks. It cannot skip the once-per-block
    computation, because incorporate_block bumps the generation.

    Bypassed inside a write txn: mid-transaction reads see uncommitted rows, so caching one would poison
    every later reader (get_bonded_registry takes the same escape hatch)."""
    if kv_ops.in_write_txn():
        return merkle_root(_root_triples(read_state(home)))
    key = (kv_ops.env_path(home), home, kv_ops.write_generation())
    entry = _root_cache[0]
    if entry is not None and entry[0] == key:
        return entry[1]
    root = merkle_root(_root_triples(read_state(home)))
    _root_cache[0] = (key, root)
    return root


def state_fingerprint(home=None):
    """(l1_state_root, {sub_db: (merkle_root, row_count)}) derived from ONE read_state() walk — a single
    MVCC snapshot, so the overall root and its per-DB breakdown are guaranteed consistent with EACH OTHER.
    Pure DIAGNOSTIC (no consensus path): comparing the map between two nodes at the same tip localizes a
    state divergence to the exact sub-DB in one shot (the betanet-8 h4260 wedge needed a replay harness for
    this). Computing root and breakdown from separate walks would let a block commit between them and produce
    a root that doesn't correspond to its own breakdown — a self-inconsistent diagnostic."""
    triples = _root_triples(read_state(home))
    by = {}
    for name, key, value in triples:
        by.setdefault(name, []).append((name, key, value))
    return merkle_root(triples), {name: (merkle_root(rows), len(rows)) for name, rows in by.items()}


def per_db_roots(home=None):
    """{sub_db: (merkle_root, row_count)} — the breakdown half of state_fingerprint (one walk)."""
    return state_fingerprint(home)[1]


def _pack_chunks(triples):
    """split sorted state triples into deterministic msgpack chunks; returns (chunk_bytes_list, chunk_meta_list)"""
    chunk_bytes, chunk_meta = [], []
    for cid, start in enumerate(range(0, len(triples), CHUNK_ROWS)):
        part = triples[start:start + CHUNK_ROWS]
        packed = codec.pack([[n, k, v] for (n, k, v) in part])
        chunk_bytes.append(packed)
        chunk_meta.append({
            "id": cid,
            "sha256": hashlib.sha256(packed).hexdigest(),
            "bytes": len(packed),
            "rows": len(part),
        })
    return chunk_bytes, chunk_meta


# TRANSFER-PAYLOAD CANONICALIZATION. Excluding a row from the state ROOT is NOT enough to make the
# SNAPSHOT identity agree: the payload still carries it, so it feeds entry_count (hashed into
# manifest_hash), the chunk bytes/sha256, and state_digest. Four honest nodes at the same checkpoint
# advertised four different snapshot_hashes for identical state_root because of exactly this — two had
# finalized_height, two did not, and their execsum: sets differed. agree_snapshot then cannot converge.
# These rows are node-local or retention/rollback-path dependent, so they must be ABSENT from the payload
# identity entirely; the importer reconstructs what it needs deterministically (see import_snapshot).
# treasury_proposals is written first-writer-wins with NO _del, and the treasury_vote revert removes only
# the vote — so a node that applied-then-reverted a proposal's first vote keeps a GHOST row a forward-only
# node never had. It is already root-excluded for that reason, but it still rode in the payload, shifting
# entry_count and state_digest and splitting snapshot identity between honest nodes. Unlike the execsum
# case that split NEVER heals: nothing ever deletes the ghost. block_by_num/block_by_hash stay CARRIED —
# a joiner needs them for deep hash-lookbacks, and their index writes are exact inverses that no path prunes.
SNAPSHOT_PAYLOAD_EXCLUDED_DBS = frozenset(("treasury_proposals",))
SNAPSHOT_PAYLOAD_EXCLUDED_META_KEYS = frozenset((b"finalized_height", b"pruned_below"))
# execsum: is deliberately NOT excluded. Block VALIDITY depends on it — validate_transaction resolves
# every summary in a settle-with-proof span and fails closed on a miss — so a joiner that lacked the
# pre-checkpoint window would REJECT a settle-with-proof block its peers ACCEPT: a validity fork between
# honest nodes, which the state-root gate cannot catch because they never agree the block is legal.
# Anything block validity depends on must be either committed in the root or GUARANTEED PRESENT on every
# node. It cannot be in the root (a joiner can never reconstruct pre-checkpoint summaries — it never had
# those bodies — so root inclusion would wedge every snapshot-synced node permanently), therefore it must
# travel in the payload. That is only safe because execsum is now a pure function of the applied blocks:
# incorporate journals the retention-pruned row and rollback restores it, so two nodes at the same height
# hold the identical window. Before that fix it diverged, which is why it was briefly excluded here.
SNAPSHOT_PAYLOAD_EXCLUDED_META_PREFIXES = (b"tvprevE:", b"tvprevW:")


def _index_row_in_window(name, key, value, checkpoint_height):
    """Is this number<->hash index row inside the carried window for a snapshot of `checkpoint_height`?

    THE STANDARD (protocol.INDEX_RETENTION_NUM / INDEX_RETENTION_HASH, doc/index-pruning.md). These two
    sub-DBs are the only stores that grow forever in every mode — 144 B/block, ~7 GiB per decade — and they
    could not be pruned as a node policy because every carried row feeds state_digest: two nodes retaining
    different depths emit different snapshot_hash values for the SAME checkpoint and fail quorum. So the
    depth is fixed by a rule keyed on the one height every node already agrees on, the checkpoint height C
    the snapshot is OF. The window is a pure function of C, so every honest node builds a byte-identical
    payload — which is what makes local pruning below it unobservable, and therefore allowed.

    Rows AT OR BELOW C only. A row above C cannot exist in an honest snapshot of C, and admitting one would
    let a donor smuggle a forged future anchor past the filter that exists to stop exactly that.

    Non-index rows are not this function's business and are passed through by the caller."""
    if checkpoint_height is None:                     # unbounded (tests / callers with no checkpoint)
        return True
    if name == "block_by_num":
        height = int.from_bytes(key, "big")           # key IS the height (8B BE)
        lo = checkpoint_height - INDEX_RETENTION_NUM
    elif name == "block_by_hash":
        height = int.from_bytes(value, "big")         # key is the hash; the VALUE is the height
        lo = checkpoint_height - INDEX_RETENTION_HASH
    else:
        return True
    return lo <= height <= checkpoint_height


def _payload_triples(triples, checkpoint_height=None):
    """The canonical TRANSFER payload: read_state() minus the rows two honest nodes can legitimately differ
    on, and minus number<->hash index rows outside the retention window for `checkpoint_height`.
    Order-preserving. Everything dropped here is already outside the state root, so state_root is
    unchanged whether it is computed over the full list or this one.

    `checkpoint_height` is threaded through BOTH sides on purpose. On export it bounds what we send; on
    IMPORT it re-derives the same window from the manifest's own snapshot_height, so a donor that ships
    out-of-window index rows has them dropped rather than trusted — the same reason finalized_height and
    execsum rows are re-filtered here instead of being taken on faith."""
    return [t for t in triples
            if t[0] not in SNAPSHOT_PAYLOAD_EXCLUDED_DBS
            and not (t[0] == "meta"
                     and (t[1] in SNAPSHOT_PAYLOAD_EXCLUDED_META_KEYS
                          or t[1].startswith(SNAPSHOT_PAYLOAD_EXCLUDED_META_PREFIXES)))
            and _index_row_in_window(t[0], t[1], t[2], checkpoint_height)]


def state_digest(triples, checkpoint_height=None):
    """blake2b over the FULL canonical (db, key, value) triple list — every row a snapshot carries, INCLUDING
    the ones _root_triples excludes from the consensus root. This is the payload authenticator: it rides in
    manifest_hash, so the quorum-agreed snapshot_hash commits to every transferred byte, while staying
    INVARIANT to how the payload is split into chunks (unlike the chunk sha256 list it replaces, which was
    keyed by the NADO_SNAPSHOT_CHUNK_ROWS env). Order is the caller's canonical sort."""
    h = hashlib.blake2b(digest_size=32)
    for t in _payload_triples(triples, checkpoint_height):
        h.update(hashlib.blake2b(_leaf(t), digest_size=32).digest())
    return h.hexdigest()


def build_snapshot(snapshot_height, block_hash, protocol, version, home=None):
    """build a manifest + chunk payloads committing the FULL consensus state at the given checkpoint height.
    Returns (manifest_dict, list_of_chunk_bytes). Pure function of the state DB."""
    home = home or get_home()
    triples = read_state(home)
    # ROOT excludes block storage (deterministic consensus subset); CHUNKS still carry everything so a
    # joiner's deep hash-lookbacks resolve. The two roles are intentionally different — see ROOT_EXCLUDED_DBS.
    # state_root over the consensus subset of the FULL state; everything else (what we TRANSFER and what
    # identifies it) over the canonical payload, so two honest nodes at the same checkpoint emit the
    # identical entry_count / chunks / state_digest / snapshot_hash.
    state_root = merkle_root(_root_triples(triples))
    payload = _payload_triples(triples, snapshot_height)
    chunk_bytes, chunk_meta = _pack_chunks(payload)

    manifest = {
        "snapshot_height": snapshot_height,
        "block_hash": block_hash,
        "state_root": state_root,
        # PAYLOAD DIGEST over the FULL triple list — including every row the state_root EXCLUDES
        # (block storage, finalized_height/pruned_below, execsum:, tvprev*). Chunking-invariant (it
        # hashes the canonical rows, not the transport split), so it authenticates the whole payload
        # without re-introducing the CHUNK_ROWS-sensitivity that chunk_count/sha256 had. See
        # manifest_hash + import_snapshot: without this, a donor matching an honest snapshot_hash could
        # substitute arbitrary EXCLUDED rows (a forged finalized_height permanently wedges rollback; a
        # forged block_by_num row forges the epoch-beacon anchor) — entry_count alone is only a count.
        "state_digest": state_digest(payload, snapshot_height),
        "entry_count": len(payload),
        "chunk_count": len(chunk_meta),
        "chunks": chunk_meta,
        "payload": "canonical-v1",   # transfer-payload format (see _payload_triples)
        "protocol": protocol,
        "version": version,
    }
    manifest["snapshot_hash"] = manifest_hash(manifest)
    return manifest, chunk_bytes


def manifest_hash(manifest) -> str:
    """blake2b over the CONSENSUS-RELEVANT manifest identity (excludes the snapshot_hash field itself).

    `version` is DELIBERATELY NOT hashed: it is a git-describe BUILD string (…-gSHA, plus `-dirty` on any
    uncommitted tree), not a property of the snapshot PAYLOAD. Two nodes with byte-identical state — same
    state_root, entry_count, and per-chunk sha256 — but a different build (most commonly one clean and one
    `-dirty`) were producing DIFFERENT snapshot_hashes, which split agree_snapshot's vote so a fresh node
    could never reach a bootstrap quorum despite the snapshots being equal. The payload fields (state_root +
    chunk sha256s) already pin the bytes exactly; `protocol` STAYS as the real compatibility gate (snapshots
    from different protocol eras are genuinely incompatible). Regenerate on-disk manifests after changing this
    (their stored snapshot_hash must match the new formula) — no chain purge / CHAIN_GENERATION bump: the L1
    state root is untouched, this is snapshot-TRANSFER identity only.

    `chunk_count` and `chunks` (the per-chunk sha256 list) are ALSO excluded, for the same reason: chunking
    is a TRANSPORT detail keyed by `CHUNK_ROWS` (an `os.environ` value, NADO_SNAPSHOT_CHUNK_ROWS), so two
    nodes with byte-identical state but a different chunk size would split the payload into different
    boundaries → different chunk_count / sha256s → different snapshot_hash → the same agree_snapshot quorum
    split as `version`. `state_root` + `entry_count` already pin the payload bytes exactly (import_snapshot
    reassembles all chunks and re-derives state_root against the manifest), and each chunk's sha256 still
    guards DOWNLOAD integrity via verify_chunk — it just no longer participates in the consensus identity."""
    core = {k: manifest[k] for k in (
        "snapshot_height", "block_hash", "state_root", "state_digest", "entry_count", "protocol")
        if k in manifest}
    # _canonical (above) sorts keys recursively -> deterministic serialization across peers/python
    # versions; codec.pack itself does NOT sort (see ops/codec.py), so the _canonical call is load-bearing.
    packed = codec.pack(_canonical(core))
    return _blake2b(packed)


def _canonical(obj):
    """recursively sort dict keys so serialization is identical everywhere"""
    if isinstance(obj, dict):
        return {k: _canonical(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [_canonical(x) for x in obj]
    return obj


def verify_chunk(chunk_bytes, meta) -> bool:
    """per-chunk integrity gate: downloaded bytes are UNTRUSTED until they match the sha256 pinned in the
    (hash-verified) manifest — a donor can't substitute chunk content without failing here"""
    return hashlib.sha256(chunk_bytes).hexdigest() == meta["sha256"]


def import_snapshot(manifest, chunk_bytes_list, home=None, logger=None):
    """Verify the chunks against the manifest, recompute the state_root locally, assert it equals the
    manifest, then atomically replace the ENTIRE consensus state (kv_ops.SNAPSHOT_DBS). Block + tx history
    indexes are left untouched — the caller replays the C+1..tip tail, which rebuilds them.

    Returns True on success. A donor cannot feed corrupted state without failing the recomputed state_root
    (consensus rows) or the recomputed state_digest (EVERY row, including the root-excluded ones — block
    storage, finalized_height/pruned_below, execsum:, tvprev*), and it can only write into the allowed
    SNAPSHOT_DBS sub-DBs. Both are bound into snapshot_hash, which the peer quorum agreed on."""
    home = home or get_home()

    # 1) manifest self-consistency
    if manifest.get("snapshot_hash") != manifest_hash(manifest):
        _log(logger, "error", "snapshot manifest hash mismatch")
        return False
    if len(chunk_bytes_list) != manifest["chunk_count"]:
        _log(logger, "error", "snapshot chunk count mismatch")
        return False

    # 2) per-chunk integrity + reassembly into (db, key, value) triples, restricted to allowed sub-DBs
    allowed = set(kv_ops.SNAPSHOT_DBS)
    triples = []
    for meta, cb in zip(manifest["chunks"], chunk_bytes_list):
        if not verify_chunk(cb, meta):
            _log(logger, "error", f"snapshot chunk {meta['id']} sha256 mismatch")
            return False
        for row in codec.unpack(cb):
            if (not isinstance(row, (list, tuple)) or len(row) != 3 or row[0] not in allowed
                    or not isinstance(row[1], (bytes, bytearray))
                    or not isinstance(row[2], (bytes, bytearray))):
                _log(logger, "error", "snapshot chunk holds a malformed / out-of-scope state entry")
                return False
            triples.append((row[0], bytes(row[1]), bytes(row[2])))

    # 3) CANONICALIZE the received payload, then verify. Dropping the excluded rows here (rather than
    # trusting the donor to have omitted them) means an injected finalized_height / execsum row can never
    # reach our DB NOR shift entry_count/state_digest — it is simply not part of the identity.
    # Re-derive the index window from the manifest's own snapshot_height, exactly as the donor should
    # have. A donor shipping rows outside it has them dropped here, so they can neither enter our DB nor
    # shift entry_count/state_digest — the same posture already applied to finalized_height and execsum.
    _C = int(manifest.get("snapshot_height") or 0) or None
    triples = _payload_triples(triples, _C)
    triples.sort(key=lambda t: (t[0], t[1], t[2]))
    if len(triples) != manifest["entry_count"]:
        _log(logger, "error", "snapshot entry_count mismatch")
        return False
    if merkle_root(_root_triples(triples)) != manifest["state_root"]:
        _log(logger, "error", "snapshot state_root mismatch after reassembly")
        return False
    # PAYLOAD AUTHENTICATION: state_root covers only the CONSENSUS subset, so without this a donor matching
    # the quorum-agreed snapshot_hash could substitute any EXCLUDED row (a forged finalized_height wedges
    # rollback permanently; a forged block_by_num forges the epoch-beacon anchor). entry_count is a count,
    # not a digest, so an in-place value edit keeps it exact. state_digest covers every transferred row.
    if manifest.get("state_digest") != state_digest(triples, _C):
        _log(logger, "error", "snapshot state_digest mismatch after reassembly (payload tampered)")
        return False

    # The NODE-LOCAL rows are not transferred (see _payload_triples). Reconstruct the one the joiner
    # actually needs, deterministically: a checkpoint is only ever advertised once FINALIZED, so
    # finalized_height == snapshot_height is correct by construction and identical on every importer — no
    # donor input, so no forged-floor wedge is possible. pruned_below stays absent (local pruning advances
    # it). The execsum WINDOW *is* transferred, because settle-with-proof block validity depends on it and
    # a joiner cannot rebuild pre-checkpoint summaries from bodies it never had.
    _h = int(manifest.get("snapshot_height") or 0)
    triples.append(("meta", b"finalized_height", codec.pack(_h)))
    triples.sort(key=lambda t: (t[0], t[1], t[2]))

    # 4) atomically replace the WHOLE consensus state (all SNAPSHOT_DBS) in ONE write txn
    kv_ops.init_env(home)
    with kv_ops.write_txn() as txn:
        kv_ops.restore_snapshot_state(triples, txn)
    _log(logger, "info",
         f"Imported snapshot height {manifest['snapshot_height']} "
         f"({manifest['entry_count']} state entries, state_root {manifest['state_root'][:16]}...)")
    return True


def agree_snapshot(statuses, min_peers=SNAPSHOT_MIN_PEERS, threshold=0.8, seed_ips=None):
    """Decide whether a super-majority of peers agree on one snapshot.

    statuses: list of peer /status dicts (None for unreachable peers).
    Returns {snapshot_height, snapshot_hash, votes, responders} for the agreed
    snapshot, or None. This is the Sybil-resistance gate: a joining node only
    accepts a (height, hash) that >= `threshold` of responding peers advertise,
    so a single malicious peer can't feed it a forged state. Pure function."""
    votes = {}
    responders = 0
    for s in statuses:
        if not s:
            continue
        responders += 1
        h = s.get("snapshot_hash")
        height = s.get("snapshot_height")
        if h and height is not None:
            votes[(height, h)] = votes.get((height, h), 0) + 1
    if responders < min_peers or not votes:
        return None
    # SEED ANCHORING. The vote above is a per-IP headcount, so a bootstrapping node with a thin peer set is
    # decided by whoever shows up: two Sybils advertising the same forged (height, hash) satisfy both
    # responders >= 2 and 0.8, and state_digest does not help because the attacker's payload is authentic to
    # its OWN forged state. Require an operator seed among the agreeing voters when any seed responded at
    # all — that binds the checkpoint to an identity the operator chose, without making seeds mandatory for
    # a fleet that has none reachable (in which case we fall back to the headcount, as before).
    try:
        from ops.peer_ops import seed_peers
        seeds = set(seed_peers() or ())
    except Exception:
        seeds = set()
    seed_votes = {}
    if seeds and seed_ips:
        for ip, st in zip(seed_ips, statuses):
            if st and ip in seeds:
                k = (st.get("snapshot_height"), st.get("snapshot_hash"))
                if k[0] is not None and k[1]:
                    seed_votes[k] = seed_votes.get(k, 0) + 1
    if seed_votes:
        votes = {k: v for k, v in votes.items() if k in seed_votes}   # only seed-corroborated candidates
        if not votes:
            return None
        # Recompute the DENOMINATOR over the surviving candidates. Dividing a filtered numerator by the
        # full responder count made the threshold near-unsatisfiable: a seed that has merely crossed a
        # CHECKPOINT_INTERVAL boundary advertises (H+1000, Y) while four healthy peers advertise (H, X),
        # so 4/5 = 0.8 (pass) became 1/5 = 0.2 (fail) and snapshot bootstrap died fleet-wide until the
        # seed resynced. Seed anchoring must narrow WHICH candidates are eligible, not silently raise the bar.
        # BE HONEST ABOUT THE SEMANTIC: once filtered, the threshold below is effectively vacuous — if a seed
        # advertises a snapshot we take it. That IS the weak-subjectivity rule (the operator-chosen seed is
        # the trust anchor, not an anonymous majority), and it is safe: a seed that is merely out of step
        # offers a valid checkpoint on the same chain, costing only a longer tail replay. The headcount
        # remains the rule only when NO seed responded.
        responders = sum(votes.values())
    (best_height, best_hash), count = max(votes.items(), key=lambda kv: kv[1])
    if count / responders >= threshold:
        return {"snapshot_height": best_height, "snapshot_hash": best_hash,
                "votes": count, "responders": responders}
    return None


async def fetch_block(target, port, block_hash, timeout=15):
    """fetch a single block dict from a peer by hash, or None"""
    import aiohttp
    from ops.net_ops import read_capped, unpack_zstd_peer, MAX_PEER_BODY
    from config import hostport
    url = f"http://{hostport(target, port)}/get_block?hash={block_hash}&compress=zstd"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get(url) as r:
                if r.status != 200:
                    return None
                block = unpack_zstd_peer(await read_capped(r, MAX_PEER_BODY))   # bomb-capped zstd wire
                return block if isinstance(block, dict) else None
    except Exception:
        return None


async def fetch_snapshot(target, port, logger=None, concurrency=8, timeout=120):
    """download a peer's snapshot manifest then all chunks in parallel.
    Returns (manifest, chunk_bytes_list) or (None, None) on failure."""
    import aiohttp
    from ops.net_ops import read_capped, unpack_zstd_peer, MAX_PEER_BODY, MAX_SNAPSHOT_TOTAL, MAX_SNAPSHOT_ACCOUNTS
    from config import hostport
    base = f"http://{hostport(target, port)}"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get(f"{base}/get_snapshot_manifest?compress=zstd") as r:
                if r.status != 200:
                    _log(logger, "info", f"No snapshot manifest from {target} (HTTP {r.status})")
                    return None, None
                manifest = unpack_zstd_peer(await read_capped(r, MAX_PEER_BODY))

            # VALIDATE the manifest BEFORE allocating anything sized by its (untrusted) fields. A lone donor
            # under weak-subjectivity could otherwise advertise a huge chunk_count/entry_count and OOM us
            # before the per-chunk sha256 / state_root checks (which only run later, in import_snapshot) fire.
            # The manifest body is already byte-capped above; verify its self-hash so the chunk meta (bytes,
            # rows) is trustworthy, then bound the totals we are about to allocate/download.
            if not isinstance(manifest, dict) or manifest.get("snapshot_hash") != manifest_hash(manifest):
                _log(logger, "warning", f"Snapshot manifest from {target} failed self-hash — rejecting")
                return None, None
            chunk_meta = manifest.get("chunks")
            # entry_count = number of (db, key, value) state triples; each chunk's "rows" must sum to it.
            # (The full-consensus-state snapshot supersedes the old accounts-only "account_count" field.)
            cc, ec = manifest.get("chunk_count"), manifest.get("entry_count")
            # chunk_count / chunks[] are NOT covered by manifest_hash (only state_root+state_digest+
            # entry_count pin the payload bytes), so a source echoing the honest snapshot_hash can still
            # serve an arbitrary chunk array. Require every chunk to carry >=1 row: with sum(rows)==ec that
            # forces cc <= ec <= MAX_SNAPSHOT_ACCOUNTS, so a padded chunk_count (e.g. 4M empty chunks → OOM
            # on `[None]*cc` + gather) cannot get past this gate before allocation.
            if not (isinstance(chunk_meta, list) and isinstance(cc, int) and cc == len(chunk_meta)
                    and isinstance(ec, int) and 0 <= ec <= MAX_SNAPSHOT_ACCOUNTS
                    and all(int(m.get("rows", 0)) > 0 for m in chunk_meta)
                    and sum(int(m.get("rows", 0)) for m in chunk_meta) == ec):
                _log(logger, "warning", f"Snapshot manifest from {target} has inconsistent counts — rejecting")
                return None, None
            total = sum(int(m.get("bytes", 0)) for m in chunk_meta)
            if not (0 <= total <= MAX_SNAPSHOT_TOTAL):
                _log(logger, "warning", f"Snapshot from {target} exceeds size ceiling ({total} bytes) — rejecting")
                return None, None

            chunks = [None] * cc
            height = manifest["snapshot_height"]     # pin chunks to the manifest we just fetched
            sem = __import__("asyncio").Semaphore(concurrency)

            async def _one(cid):
                """fetch chunk `cid` under the concurrency semaphore, read-capped to chunk_meta[cid]['bytes']
                (trusted because the manifest passed its self-hash) — the donor can't over-feed us"""
                async with sem:
                    async with session.get(f"{base}/get_snapshot_chunk?id={cid}&height={height}") as cr:
                        if cr.status != 200:
                            raise IOError(f"chunk {cid} HTTP {cr.status}")
                        # chunk_meta[cid]['bytes'] is NOT self-hash-covered, but the per-read cap + the total
                        # bytes ceiling (<= MAX_SNAPSHOT_TOTAL, checked above) still bound what the donor feeds
                        # us; the imported state is re-derived and root-checked regardless.
                        chunks[cid] = await read_capped(cr, int(chunk_meta[cid].get("bytes", 0)))

            await __import__("asyncio").gather(*(_one(i) for i in range(cc)))
            return manifest, chunks
    except Exception as e:
        _log(logger, "error", f"Failed to fetch snapshot from {target}: {e}")
        return None, None


def _log(logger, level, msg):
    """log at `level` if a logger was passed (falling back to .info for unknown levels); silent no-op
    without one, so library callers and tests need not wire up logging"""
    if logger:
        getattr(logger, level, logger.info)(msg)


# --------------------------------------------------------------------------------------------------
# PERSISTENT STATE CHECKPOINTS (rolling-node sync).
#
# A node captures a snapshot of its account state at each checkpoint height C at the MOMENT it
# incorporates block C — so accounts.db == state@C by construction (no historical-state derivation,
# nothing to get wrong). The snapshot (manifest + chunks) is written under snapshots/<C>/ and is
# advertised in /status ONLY once C is finalized (reorg-safe), so a joiner can bulk-import verified
# state@C and then replay only the short C+1..tip tail. Every honest node produces the identical
# deterministic checkpoint, which is what lets a joiner accept one on a super-majority quorum.
# --------------------------------------------------------------------------------------------------

def _snap_dir(home=None):
    """root of the persisted checkpoints (snapshots/<height>/ per checkpoint)"""
    return f"{home or get_home()}/snapshots"


def _ckpt_path(height, home=None):
    """directory of the checkpoint at `height`; int() sanitizes a peer-supplied height (no path traversal)"""
    return f"{_snap_dir(home)}/{int(height)}"


def list_checkpoint_heights(home=None):
    """persisted checkpoint heights on disk, ascending (ignores in-progress .tmp dirs)"""
    d = _snap_dir(home)
    if not os.path.isdir(d):
        return []
    heights = []
    for name in os.listdir(d):
        if name.endswith(".tmp"):
            continue
        try:
            heights.append(int(name))
        except ValueError:
            pass
    return sorted(heights)


def _prune_old_checkpoints(keep, home=None):
    """drop all but the newest `keep` checkpoints — every node deterministically re-captures the same
    ones, so old checkpoints are pure disk weight, not history worth keeping. keep<=0 disables pruning."""
    if keep <= 0:
        return
    for h in list_checkpoint_heights(home)[:-keep]:
        shutil.rmtree(_ckpt_path(h, home), ignore_errors=True)


def persist_checkpoint(height, block_hash, protocol, version, home=None, keep=2):
    """Build a snapshot of the CURRENT account state (== state@height when called at the incorporation
    of block `height`) and atomically persist manifest + chunks under snapshots/<height>/. Keeps the
    newest `keep` checkpoints. Returns the manifest. Correct by construction — never derives past state."""
    home = home or get_home()
    manifest, chunk_bytes = build_snapshot(height, block_hash, protocol, version, home=home)
    final = _ckpt_path(height, home)
    tmp = final + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    with open(f"{tmp}/manifest.json", "wb") as f:
        f.write(codec.pack(manifest))
    for cid, cb in enumerate(chunk_bytes):
        with open(f"{tmp}/chunk_{cid}.bin", "wb") as f:
            f.write(cb)
    shutil.rmtree(final, ignore_errors=True)
    os.rename(tmp, final)                      # atomic publish (a partial write never becomes visible)
    _prune_old_checkpoints(keep, home)
    return manifest


def _checkpoint_is_canonical(height, home=None):
    """True iff the persisted checkpoint at `height` anchors to the block the CURRENT canonical chain
    has at that height (number->hash index compare). Only the boot-time sweep needs this: at runtime
    every persisted checkpoint is canonical BY CONSTRUCTION (see latest_final_checkpoint_height)."""
    manifest = load_checkpoint_manifest(height, home)
    if not isinstance(manifest, dict):
        return False
    return kv_ops.hash_by_number(height) == manifest.get("block_hash")


def latest_final_checkpoint_height(finalized_height, home=None):
    """the highest persisted checkpoint at/below finalized_height (safe to advertise/serve), or None.
    Canonical BY CONSTRUCTION — no runtime re-check needed: capture happens on the just-incorporated
    block, rollback drops reverted checkpoints (drop_checkpoints_above), a re-anchor wipes them all
    (adopt_new_identity), and sweep_noncanonical_checkpoints cleans pre-invariant disks at boot."""
    finals = [h for h in list_checkpoint_heights(home) if h <= int(finalized_height)]
    return finals[-1] if finals else None


def drop_all_checkpoints(home=None):
    """delete every persisted checkpoint, returning how many were dropped (identity-change wipe:
    checkpoints captured on an abandoned identity are statements about a dead chain)."""
    heights = list_checkpoint_heights(home)
    for h in heights:
        shutil.rmtree(_ckpt_path(h, home), ignore_errors=True)
    return len(heights)


def sweep_noncanonical_checkpoints(home=None):
    """BOOT hygiene: drop any persisted checkpoint whose anchor is not this node's canonical block at
    that height. With adopt_new_identity wiping checkpoints on every re-anchor and rollback dropping
    reverted ones, no new non-canonical checkpoint can come into existence — this cleans disks that
    predate that invariant. (A poisoned advertised checkpoint wedges a fresh joiner at birth: it
    bootstraps onto a chain no donor can extend — observed live at height 13000.) Returns the count."""
    dropped = 0
    for h in list_checkpoint_heights(home):
        if not _checkpoint_is_canonical(h, home):
            shutil.rmtree(_ckpt_path(h, home), ignore_errors=True)
            dropped += 1
    return dropped


def adopt_new_identity(logger=None, home=None):
    """LOCAL IDENTITY CHANGE — the root-cause invariant. When a node abandons its chain for another
    (snapshot re-anchor), every artifact DERIVED from the abandoned chain must die with it, atomically
    and by construction — not via per-artifact cleanup patches. import_snapshot has already replaced
    the carried consensus state wholesale (restore_snapshot_state drops + repopulates SNAPSHOT_DBS);
    this retires everything else that could still speak for the dead chain:
      - the non-carried LMDB sub-DBs (tx history, block locators, GC reverts) — the set is COMPUTED
        as all-minus-carried, so future sub-DBs are stale-safe by default,
      - the block-body segment store (orphaned fork bodies were the "donor knows my tip" bait),
      - our own persisted checkpoints (captured on the abandoned identity — the exact poison that
        wedged a fresh joiner at 13000).
    After this returns, the node's disk makes no statement the new identity does not vouch for."""
    kv_ops.wipe_non_carried_dbs()
    segment_store.reset(home)
    dropped = drop_all_checkpoints(home)
    if logger:
        logger.warning("Adopted new chain identity: wiped tx history, block bodies, local indexes and "
                       f"{dropped} checkpoint(s) of the abandoned chain")


def load_checkpoint_manifest(height, home=None):
    """the persisted manifest of checkpoint `height` (served over /get_snapshot_manifest and advertised in
    /status), or None if absent. Fetchers re-verify its self-hash, so no trust rides on this read."""
    p = f"{_ckpt_path(height, home)}/manifest.json"
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as f:
        return codec.unpack(f.read())


def migrate_checkpoint_hashes(logger=None, home=None):
    """One-time, idempotent boot migration: rewrite each on-disk checkpoint manifest whose stored
    `snapshot_hash` no longer equals manifest_hash() under the CURRENT formula (e.g. after `version` was
    dropped from the hashed identity). CHEAP — the payload + chunks are unchanged, only the stored hash
    field is corrected — so a node that just updated to a new manifest_hash keeps SERVING its existing
    checkpoints (and reaching agree_snapshot quorum with peers) instead of having them rejected by the
    self-hash gate (import_snapshot / snapshot_manifest) until the next CHECKPOINT_INTERVAL rebuild. Never
    fatal: a bad manifest is skipped; a stale checkpoint costs a donor slot, never a block."""
    fixed = dropped = 0
    try:
        heights = list_checkpoint_heights(home)
    except Exception:
        return 0
    for h in heights:
        try:
            m = load_checkpoint_manifest(h, home)
            if not isinstance(m, dict):
                continue
            # FORMAT CHECK FIRST. A pre-canonical manifest can still be SELF-CONSISTENT (its stored hash
            # matches manifest_hash, which does not cover the payload format), so checking the hash first
            # and `continue`-ing would leave it in place forever — observed live: a peer kept advertising a
            # pre-canonical checkpoint after the upgrade, which is exactly the identity no other node
            # reproduces. Drop on format, THEN consider re-stamping.
            if not m.get("state_digest") or m.get("payload") != "canonical-v1":
                shutil.rmtree(_ckpt_path(h, home), ignore_errors=True)
                dropped += 1
                continue
            correct = manifest_hash(m)          # reads only the core keys — independent of m's stored hash/version
            if m.get("snapshot_hash") == correct:
                continue
            m["snapshot_hash"] = correct
            path = f"{_ckpt_path(h, home)}/manifest.json"
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(codec.pack(m))
            os.replace(tmp, path)               # atomic: a partial rewrite never becomes visible
            fixed += 1
        except Exception:
            continue
    if (fixed or dropped) and logger:
        logger.warning(f"Checkpoint manifest migration: {fixed} re-stamped to the current snapshot-identity "
                       f"formula, {dropped} dropped (predate the payload digest; will rebuild)")
    return fixed


def load_checkpoint_chunk(height, cid, home=None):
    """raw bytes of one persisted chunk (served verbatim to joiners over /get_snapshot_chunk), or None if
    missing. int() on the peer-supplied cid (like height in _ckpt_path) forecloses path traversal."""
    p = f"{_ckpt_path(height, home)}/chunk_{int(cid)}.bin"
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as f:
        return f.read()


def drop_checkpoints_above(height, home=None):
    """On rollback: discard checkpoints whose height exceeds the new tip — they may reflect a state
    that is being reverted. (Advertised checkpoints are always finalized, so this only ever removes
    not-yet-final ones, keeping the on-disk set consistent with the chain.)"""
    for h in list_checkpoint_heights(home):
        if h > int(height):
            shutil.rmtree(_ckpt_path(h, home), ignore_errors=True)
