"""
Append-only SEGMENT store for block bodies — replaces one-file-per-block (doc/storage.md).

Why: an archive node at 6s blocks creates ~5.3M block files/year — an inode per block, random
I/O for every sync batch, and rsync/backup pathology. Segments cap that at ~300 files/year
(64 MB each) with sequential reads for forward sync. Purely LOCAL storage layout: hashes, the
wire format and the consensus number<->hash index are untouched.

Layout: <home>/blocks/seg-<8-hex>.dat, records appended back to back:

    MAGIC "NBK1" (4B) | payload_len u32 BE | crc32 u32 BE | block_hash 32B raw | payload

crc32 covers hash32+payload. Records are SELF-DESCRIBING (they carry their block hash), so the
hash->locator index in LMDB (kv_ops `block_loc`) stays a DERIVED, rebuildable index — a full
segment scan can always reconstruct it (iter_records).

CRASH SAFETY (the same contract the old temp+fsync+os.replace file store gave):
  * append = write + flush + fsync BEFORE the locator is committed to LMDB. A crash between the
    two leaves a valid-but-unreferenced record (harmless garbage; the replay re-appends).
  * a crash MID-append leaves a torn record at the very tail of the ACTIVE segment only; init()
    scans the active segment's records and truncates the torn tail. No locator can reference it
    (locators are only written after a successful fsync).
  * a failed append (disk full) truncates back to the pre-write offset; if even that fails the
    store rolls to a fresh segment so later appends never build on a poisoned tail.

DELETION is by unreferencing: rollback/prune drop the LMDB locator (inside the caller's write
txn — atomic with the rest of the rollback, better than the old best-effort file unlink); the
record bytes become inert garbage. Whole segments are GC'd by rolling-mode pruning once their
live-locator count (kv_ops seg_live counters) reaches zero.

One writer thread is assumed per home (the core loop; genesis/migration run before it starts) —
appends are serialized by a per-home lock anyway. Reads come from the many HTTP threads through a
cached per-segment file object under a read lock — PORTABLE seek+read only (no os.pread: it does
not exist on Windows, and a node must run identically on every OS).
"""
import os
import struct
import threading
import zlib

from .data_ops import get_home

MAGIC = b"NBK1"
_HDR = struct.Struct(">4sII")          # magic, payload_len, crc32
HEADER_SIZE = _HDR.size + 32           # + 32B raw block hash
# Roll to a new segment once the active one crosses this. Env override for tests (tiny segments
# exercise rollover/GC without megabytes of data). Read once at import; a node never changes it live.
SEGMENT_TARGET_BYTES = int(os.environ.get("NADO_SEGMENT_BYTES", 64 << 20))

# Per-home store state: {home_dir: _Store}. Keyed like kv_ops._envs so multi-HOME tests isolate.
_stores = {}
_stores_lock = threading.Lock()


def segments_dir(home=None):
    """The block-store directory (shared with the legacy per-file layout during migration)."""
    return os.path.join(home or get_home(), "blocks")


def segment_path(seg: int, home=None) -> str:
    return os.path.join(segments_dir(home), f"seg-{seg:08x}.dat")


def _parse_records(f, upto=None):
    """Yield (offset, total_len, hash_hex, payload_off, payload_len) for every VALID record from
    offset 0; stop at EOF, a torn/invalid record, or `upto`. Does NOT verify crc (cheap structural
    walk); use read()/iter_records for verified payloads."""
    off = 0
    size = os.fstat(f.fileno()).st_size if upto is None else upto
    while off + HEADER_SIZE <= size:
        f.seek(off)
        head = f.read(HEADER_SIZE)
        if len(head) < HEADER_SIZE:
            return
        magic, plen, _crc = _HDR.unpack(head[:_HDR.size])
        if magic != MAGIC or off + HEADER_SIZE + plen > size:
            return                                     # torn/garbage tail
        yield off, HEADER_SIZE + plen, head[_HDR.size:].hex(), off + HEADER_SIZE, plen
        off += HEADER_SIZE + plen


class _Store:
    def __init__(self, home):
        self.home = home
        self.lock = threading.RLock()
        self.read_files = {}                          # seg -> open 'rb' file (seek+read under read_lock)
        self.read_lock = threading.Lock()
        d = segments_dir(home)
        os.makedirs(d, exist_ok=True)
        segs = []
        for name in os.listdir(d):
            if name.startswith("seg-") and name.endswith(".dat"):
                try:
                    segs.append(int(name[4:-4], 16))
                except ValueError:
                    continue
        self.active_seg = max(segs) if segs else 0
        self._repair_tail()
        self.active_f = open(segment_path(self.active_seg, home), "ab")
        # EXPLICIT end-seek: 'ab' guarantees writes land at EOF, but tell() right after open is 0 on
        # Windows (CRT) vs EOF on POSIX — seek makes the size bookkeeping identical everywhere.
        self.active_f.seek(0, os.SEEK_END)
        self.active_size = self.active_f.tell()

    def _repair_tail(self):
        """Truncate a torn record off the ACTIVE segment's tail (crash mid-append). Only the last
        record of the last-written segment can ever be torn (appends are sequential + fsynced), and
        no locator references it (locators commit only after the fsync)."""
        path = segment_path(self.active_seg, self.home)
        if not os.path.exists(path):
            return
        with open(path, "rb") as f:
            end = 0
            for off, total, _h, _po, _pl in _parse_records(f):
                end = off + total
            size = os.fstat(f.fileno()).st_size
        if end < size:
            with open(path, "r+b") as f:
                f.truncate(end)

    def _roll(self):
        try:
            self.active_f.close()
        except Exception:
            pass
        self.active_seg += 1
        self.active_f = open(segment_path(self.active_seg, self.home), "ab")
        self.active_f.seek(0, os.SEEK_END)            # Windows 'ab' tell()==0 quirk, see __init__
        self.active_size = self.active_f.tell()

    def append(self, block_hash_hex: str, payload: bytes):
        """Durably append one record; returns (seg, offset, total_len) AFTER fsync. On a write
        failure, truncate back to the pre-write offset (self-heal) or roll to a fresh segment —
        either way the store never builds on a torn tail. Raises on failure (caller retries)."""
        hraw = bytes.fromhex(block_hash_hex)
        assert len(hraw) == 32, "block hash must be 32 bytes hex"
        record = _HDR.pack(MAGIC, len(payload), zlib.crc32(hraw + payload)) + hraw + payload
        with self.lock:
            start = self.active_size
            try:
                self.active_f.write(record)
                self.active_f.flush()
                os.fsync(self.active_f.fileno())
            except Exception:
                try:                                   # drop the partial write so the tail stays clean
                    self.active_f.truncate(start)
                    self.active_f.seek(start)
                    self.active_size = start
                except Exception:
                    self._roll()                       # can't heal in place -> abandon this tail
                raise
            seg, off = self.active_seg, start
            self.active_size = start + len(record)
            if self.active_size >= SEGMENT_TARGET_BYTES:
                self._roll()
            return seg, off, len(record)

    def read(self, seg: int, off: int, total_len: int, expect_hash_hex: str):
        """Verified payload bytes for a locator, or None (missing segment, torn read, crc mismatch,
        or a locator pointing at a different block's record — every failure is a miss, never junk).
        Cached per-segment 'rb' file, seek+read under the read lock: portable across every OS
        (os.pread does not exist on Windows — the launch bug a Windows joiner hit live)."""
        try:
            with self.read_lock:
                f = self.read_files.get(seg)
                if f is None:
                    f = open(segment_path(seg, self.home), "rb")
                    self.read_files[seg] = f
                f.seek(off)
                raw = f.read(total_len)
        except (OSError, ValueError):                 # ValueError: read on a file closed by delete_segment
            return None
        if len(raw) != total_len or raw[:4] != MAGIC:
            return None
        _magic, plen, crc = _HDR.unpack(raw[:_HDR.size])
        if HEADER_SIZE + plen != total_len:
            return None
        hraw = raw[_HDR.size:HEADER_SIZE]
        payload = raw[HEADER_SIZE:]
        if hraw.hex() != expect_hash_hex or zlib.crc32(hraw + payload) != crc:
            return None
        return payload

    def delete_segment(self, seg: int) -> bool:
        """Unlink a fully-dead segment file (rolling-mode GC). Never the active one."""
        with self.lock:
            if seg == self.active_seg:
                return False
            with self.read_lock:
                f = self.read_files.pop(seg, None)
                if f is not None:
                    try:
                        f.close()                     # also required on Windows: can't unlink an open file
                    except OSError:
                        pass
            try:
                os.remove(segment_path(seg, self.home))
                return True
            except FileNotFoundError:
                return True
            except OSError:
                return False


def _store(home=None) -> _Store:
    home = home or get_home()
    st = _stores.get(home)
    if st is not None:
        return st
    with _stores_lock:
        st = _stores.get(home)
        if st is None:
            st = _stores[home] = _Store(home)
        return st


def init(home=None):
    """Open the store (idempotent): discovers the active segment + repairs a torn tail."""
    _store(home)


def append(block_hash_hex: str, payload: bytes, home=None):
    return _store(home).append(block_hash_hex, payload)


def read(seg: int, off: int, total_len: int, expect_hash_hex: str, home=None):
    return _store(home).read(seg, off, total_len, expect_hash_hex)


def delete_segment(seg: int, home=None) -> bool:
    return _store(home).delete_segment(seg)


def active_segment(home=None) -> int:
    return _store(home).active_seg


def iter_records(seg: int, home=None):
    """Yield (block_hash_hex, payload) for every crc-VALID record in a segment — the rebuild path
    that keeps the LMDB locator index a derived structure (and the migration verifier)."""
    path = segment_path(seg, home)
    with open(path, "rb") as f:
        for off, total, hash_hex, _poff, _plen in _parse_records(f):
            f.seek(off)
            raw = f.read(total)
            _m, _pl, crc = _HDR.unpack(raw[:_HDR.size])
            if zlib.crc32(raw[_HDR.size:]) == crc:
                yield hash_hex, raw[HEADER_SIZE:]
