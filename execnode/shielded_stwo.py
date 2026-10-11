"""
The Stwo shielded pool (doc/stwo-migration.md §5.1) — the pool whose join-split is proved by the Stwo circuit
(native/stwo_js) instead of joinsplit3. NOT LIVE: nothing in the exec layer constructs it until STWO_POOL_HEIGHT, and
until its first note the exec root does not see it ("empty is absent", exec_root.records_projection).

THE HASH IS THE CIRCUIT'S, BYTE FOR BYTE. H = BLAKE2s-256 of ONE 64-byte block: sixteen little-endian u32 words, the
first a domain tag where the circuit has one —
    owner = H(21, nsk[0..8])                       nsk: a 256-bit spend key, eight u32 words
    cm    = H(22, lo(v), hi(v), owner[0..8], lo(rho), hi(rho))
    nf    = H(23, nsk[0..8], lo(rho), hi(rho))
    node  = H(left[0..8], right[0..8])             no tag: fixed arity, as the circuit's membership rows
and an empty leaf is the all-zero digest, an empty level node(empty, empty). Digests travel as 64-hex (the 32 bytes
in word order). tests/test_stwo_pool_hashes_match_the_circuit.py pins these against vectors the prototype's Rust
reference functions printed; a change here without the circuit is a pool nobody can spend from.

The tree has ONE depth, 48, from its first note — no 12 -> 48 switch like the wide pool's, because this pool never
existed at height 0.
"""
import hashlib
import re
import struct

DEPTH = 48
# ANCHORS (review 2026-10-11, integration): a spend may name the root after any of the last ANCHOR_WINDOW appends, OR the
# root a block CLOSED on, for every block that appended within the last ANCHOR_BLOCKS blocks. The block-closing roots are
# the ones that matter: a wallet proves against the FINALIZED pool, so its root is a block-closing root ~finality_depth
# old before proving even starts. A window counted only in APPENDS was flushed by 128 one-raw deposits (~1.3e-5 NADO,
# blocks have no tx-count cap), failing every spend in flight; no count-based window survives that, so the bound is in
# blocks. 1024 blocks is ~2 h at 6.8 s: finality (45) + proving + DA + TX_INCLUSION_DELAY with a wide margin.
ANCHOR_WINDOW = 128
ANCHOR_BLOCKS = 1024
DOM_OWNER, DOM_CM, DOM_NF = 21, 22, 23
_MASK64 = (1 << 64) - 1
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")


def is_digest(s):
    """THE ONE SPELLING OF A DIGEST ON THE WIRE AND IN THE POOL: exactly 64 lowercase hex characters.
    INVARIANT (review 2026-10-11, reproduced): bytes.fromhex skips ASCII whitespace, so `nf[:62] + "  "` decoded to 31
    bytes, ctypes handed the verifier the bytes object's buffer and its trailing NUL made byte 32 — the SAME nullifier
    as the canonical string whenever the real one ends in 0x00, but a different member of the spent set: one note spent
    once per spelling. Every digest a spend names (root, nf, cm_out1, cm_out2) and every owner and commitment the pool
    stores passes this before anything is decoded, verified or mutated. Never relax it to `.lower()` + fromhex."""
    return isinstance(s, str) and _DIGEST_RE.fullmatch(s) is not None


def _words(d):
    """A 64-hex digest (or 32 bytes) -> its eight little-endian u32 words."""
    b = bytes.fromhex(d) if isinstance(d, str) else bytes(d)
    if len(b) != 32:
        raise ValueError("a digest is 32 bytes")
    return list(struct.unpack("<8I", b))


def _h(words16):
    if len(words16) != 16:
        raise ValueError("one BLAKE2s block is sixteen u32 words")
    return hashlib.blake2s(struct.pack("<16I", *[int(w) & 0xFFFFFFFF for w in words16]), digest_size=32).hexdigest()


def _u64(x):
    x = int(x)
    if not 0 <= x <= _MASK64:
        raise ValueError("a value or rho is a u64")
    return [x & 0xFFFFFFFF, x >> 32]


def owner_of(nsk):
    """nsk: 32 bytes / 64-hex (the spend key, eight u32 words)."""
    return _h([DOM_OWNER, *_words(nsk), *([0] * 7)])


def commit(value, owner, rho):
    return _h([DOM_CM, *_u64(value), *_words(owner), *_u64(rho), 0, 0, 0])


def nullifier(nsk, rho):
    return _h([DOM_NF, *_words(nsk), *_u64(rho), *([0] * 5)])


def node(left, right):
    return _h([*_words(left), *_words(right)])


def wire_u64(v):
    """A u64 as a JSON int or an ASCII decimal string; nothing else (a bool is not a number here)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v and v.isascii() and v.isdigit():
        return int(v)
    return None


def parse_transfer(bundle, max_value):
    """THE ONE READING OF A `stwo_js` BUNDLE, stateless: (None, spend) or ("<why refused>", None), where spend is
    {root, nf, cm1, cm2, proof (bytes), unshield, fee, addr} — addr "" for a private transfer, whatever the bundle says,
    because the proof of a transfer is bound to the empty destination. Every check here depends on the bundle alone:
    shape, the one spelling of each digest (is_digest), the proof as lowercase hex, unshield/fee as u64s within
    `max_value`, and an unshield's destination a spendable non-reserved address.
    INVARIANT: ExecState._apply_stwo_transfer and the node's spend relay (ops/stwo_relay.py) BOTH read a bundle through
    this function and nothing else, so the relay can never vouch for (and pay the L1 fee of) a bundle the exec layer
    reads differently. A second reading — e.g. the relay lowering a digest — is the exact class of bug is_digest's
    docstring records. The returned strings start "skip field-transfer:" because they are the exec layer's log lines."""
    stark_b = bundle.get("stark") if isinstance(bundle, dict) else None
    js = stark_b.get("stwo_js") if isinstance(stark_b, dict) else None
    if not isinstance(js, dict):
        return "skip field-transfer: malformed stwo_js bundle", None
    # INVARIANT: digests in their ONE spelling (is_digest) — never lowered, never fromhex'd loosely. A whitespace or
    # upper-case spelling of a spent nullifier was a fresh set member over the same verified bytes.
    digs = [js.get(k) for k in ("root", "nf", "cm_out1", "cm_out2")]
    if not all(is_digest(d) for d in digs):
        return "skip field-transfer: root, nf, cm_out1 and cm_out2 must be 64 lowercase hex", None
    root, nf, cm1, cm2 = digs
    p = js.get("proof")
    if not (isinstance(p, str) and p and len(p) % 2 == 0 and all(c in "0123456789abcdef" for c in p)):
        return "skip field-transfer: the proof is not lowercase hex", None
    unshield, fee = wire_u64(js.get("unshield", 0)), wire_u64(js.get("fee"))
    if unshield is None or fee is None:
        return "skip field-transfer: unshield and fee must be integers", None
    addr = ""
    if unshield:
        from ops.address_ops import validate_address
        addr = bundle.get("withdraw_addr")
        if not isinstance(addr, str) or not addr or not validate_address(addr, allow_reserved=False):
            return "skip field-transfer: withdraw_addr is not a spendable account", None
    if not (0 <= unshield <= max_value) or not (0 <= fee <= max_value):
        return "skip field-transfer: unshield/fee out of range", None
    return None, {"root": root, "nf": nf, "cm1": cm1, "cm2": cm2, "proof": bytes.fromhex(p), "unshield": unshield,
                  "fee": fee, "addr": addr}


EMPTY_LEAF = "00" * 32
_EMPTY = [EMPTY_LEAF]
for _ in range(DEPTH):
    _EMPTY.append(node(_EMPTY[-1], _EMPTY[-1]))
EMPTY_ROOT = _EMPTY[DEPTH]


class _Frontier:
    """Incremental append-only Merkle tree: O(DEPTH) per append, the root without the leaves."""

    def __init__(self):
        self.n = 0
        self.left = [None] * DEPTH          # left[i]: the pending left sibling at level i

    def append(self, leaf):
        i, cur, n = 0, leaf, self.n
        while n & 1:
            cur = node(self.left[i], cur)
            n >>= 1
            i += 1
        self.left[i] = cur
        self.n += 1

    def root(self):
        if self.n == 0:
            return EMPTY_ROOT
        cur, n = None, self.n
        for i in range(DEPTH):
            if n & 1:
                cur = node(self.left[i], cur if cur is not None else _EMPTY[i])
            elif cur is not None:
                cur = node(cur, _EMPTY[i])
            n >>= 1
        return cur


def tree_root(leaves):
    f = _Frontier()
    for x in leaves:
        f.append(x)
    return f.root()


def tree_path(leaves, pos):
    """(siblings, dirs) for leaf `pos` — dirs[i] = 1 when the node is the RIGHT child at level i, the circuit's rule."""
    level, i, sibs, dirs = list(leaves), int(pos), [], []
    for d in range(DEPTH):
        sib = i ^ 1
        sibs.append(level[sib] if sib < len(level) else _EMPTY[d])
        dirs.append(i & 1)
        level = [node(level[2 * k], level[2 * k + 1] if 2 * k + 1 < len(level) else _EMPTY[d])
                 for k in range((len(level) + 1) // 2)]
        i >>= 1
    return sibs, dirs


class StwoShieldedPool:
    """Commitments (append-only), the nullifier set, and the roots a spend may anchor to (ANCHORS above).

    `marks` are [height, note count] for each recent block that appended: the count the block closed on. They are state
    (snapshot + exec root, `marks_digest`) because they are not derivable from the commitments; every mark names a real
    prefix of the committed leaves, so a root they admit is always the root of real notes."""

    def __init__(self, commitments=None, nullifiers=None, marks=None):
        cms = list(commitments or [])
        for cm in cms:
            if not is_digest(cm):
                raise ValueError("a commitment is 64 lowercase hex")
        if len(set(cms)) != len(cms):
            raise ValueError("duplicate commitment in the pool")
        marks = [[int(h), int(n)] for h, n in (marks or [])]
        for a, b in zip(marks, marks[1:]):
            if not (a[0] < b[0] and a[1] < b[1]):
                raise ValueError("pool marks must rise in height and in note count")
        if marks and not (1 <= marks[0][1] and marks[-1][1] <= len(cms)):
            raise ValueError("a pool mark names a note count the pool does not hold")
        self.nullifiers = {str(nf) for nf in (nullifiers or [])}
        self.commitments, self._cms, self.marks = cms, set(cms), marks
        # REBUILT THROUGH THE FRONTIER, ONCE (review 2026-10-11): O(n) node hashes + a root per kept anchor. Appending
        # through append() cost a 48-hash root PER NOTE on every _restore, i.e. every clone of the provisional view —
        # 17 s at 20,000 notes. The anchors are the same list append() keeps (tests pin the equality).
        self._f = _Frontier()
        n, want = len(cms), {c for _, c in marks}
        first = n + 1 - ANCHOR_WINDOW                    # the oldest prefix length the append window keeps
        self.anchors = [EMPTY_ROOT] if first <= 0 else []
        self._mark_roots = {}
        for k, cm in enumerate(cms, 1):
            self._f.append(cm)
            if k >= first or k in want:
                r = self._f.root()
                if k >= first:
                    self.anchors.append(r)
                if k in want:
                    self._mark_roots[k] = r
        self._root = self._f.root() if n else EMPTY_ROOT

    def root(self):
        return self._root

    def room_for(self, k):
        """Whether `k` more commitments fit (the depth-48 tree's capacity) — checked BEFORE a mutation starts."""
        return self._f.n + int(k) <= (1 << DEPTH)

    def has_commitment(self, cm):
        return cm in self._cms                           # a set: the list scan was O(n) per deposit and per spend

    def append(self, cm, height=None):
        """Append one commitment. `height` is the block applying it (ExecState.applying_height()); every consensus
        caller passes it — only tooling and tests building a bare tree omit it, and such a pool has no block marks."""
        # canonical only (is_digest): a commitment has one spelling, so duplicate checks are exact
        if not is_digest(cm):
            raise ValueError("a commitment is 64 lowercase hex")
        if not self.room_for(1):
            raise ValueError("the pool is full")
        self.commitments.append(cm)
        self._cms.add(cm)
        self._f.append(cm)
        self._root = r = self._f.root()
        self.anchors.append(r)
        del self.anchors[:-ANCHOR_WINDOW]
        if height is not None:
            h, n = int(height), len(self.commitments)
            if self.marks and self.marks[-1][0] == h:
                self._mark_roots.pop(self.marks[-1][1], None)
                self.marks[-1][1] = n
            elif self.marks and self.marks[-1][0] > h:
                raise ValueError("a pool append below the last block that appended")
            else:
                self.marks.append([h, n])
            self._mark_roots[n] = r
            # Pruning is a pure function of the append history (it runs only here), so every node holds the same marks;
            # knows_root filters by age anyway, so a mark kept a little past its window is never accepted.
            while self.marks and self.marks[0][0] < h - ANCHOR_BLOCKS:
                self._mark_roots.pop(self.marks.pop(0)[1], None)

    def knows_root(self, root, height=None):
        """Whether a spend applied at block `height` may anchor to `root`: the append window, or a block-closing root
        no older than ANCHOR_BLOCKS. height=None (tooling) accepts any kept mark."""
        root = str(root)
        if root in self.anchors:
            return True
        lo = None if height is None else int(height) - ANCHOR_BLOCKS
        return any(self._mark_roots.get(c) == root for h, c in self.marks if lo is None or h >= lo)

    def has_nullifier(self, nf):
        return str(nf).lower() in self.nullifiers

    def spend(self, nf):
        if not is_digest(nf):                          # one spelling per nullifier (is_digest)
            raise ValueError("a nullifier is 64 lowercase hex")
        if nf in self.nullifiers:
            raise ValueError("nullifier already spent")
        self.nullifiers.add(nf)

    def nullifier_digest(self):
        """One digest of the spent set, order-independent (sorted) — what the exec root's record carries."""
        return hashlib.blake2b(("stwo_nfset|" + "|".join(sorted(self.nullifiers))).encode(), digest_size=32).hexdigest()

    def marks_digest(self):
        """The block marks as the exec root carries them: they decide which anchors a spend may name, so a node that
        adopted a snapshot with different marks would accept a different set of spends — the root must show it."""
        return hashlib.blake2b(("stwo_marks|" + "|".join(f"{h}:{n}" for h, n in self.marks)).encode(),
                               digest_size=32).hexdigest()

    def to_dict(self):
        return {"commitments": list(self.commitments), "nullifiers": sorted(self.nullifiers),
                **({"marks": [list(m) for m in self.marks]} if self.marks else {})}

    @classmethod
    def from_dict(cls, d):
        return cls(d.get("commitments") or [], d.get("nullifiers") or [], d.get("marks") or [])
