"""
DA store — disk-backed storage, distribution and serving for erasure-coded data availability (ops/da.py).

Shared infrastructure for the two things NADO's DA needs to carry:
  (a) rollup BLOB data under rolling-mode pruning — reconstruct a pruned blob from erasure-coded shards;
  (b) shielded-transfer PROOF DA — the ~1-4 MB STARK proofs that are far too big for a 16 KiB L1 blob, so
      only the transfer STATEMENT + the proof's `commitment` ride on-chain and the proof lives here.

Model: a publisher erasure-codes data into n shards with an index-bound (PQ) Merkle commitment; any k of
the n reconstruct it. Every (shard, merkle-proof) pair SELF-VERIFIES against the commitment, so shards can
be spread across many independent DA nodes and a consumer fetches k-of-n from anyone, trustlessly. The
commitment is the only thing that has to be agreed on-chain. Storage is a rolling window: once a
commitment's effect is settled + snapshotted, prune() drops it (phones never touch any of this — it is a
full/exec/DA-node concern).
"""
import os
import json
import shutil
import threading

from ops import da


def _atomic_write(path, data: bytes):
    """Crash-safe write: write to a temp sibling then rename ('~tmp' is outside the hex commitment charset)."""
    tmp = path + "~tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


_META_KEYS = ("commitment", "k", "n", "stripes", "length")


class DaStore:
    """A directory of erasure-coded objects keyed by commitment. Layout per object:
        {root}/{commitment}/meta.json      -> {commitment,k,n,stripes,length}
        {root}/{commitment}/{i}.shard      -> shard i bytes
        {root}/{commitment}/{i}.proof      -> merkle proof for shard i (binds it to the commitment)
    A node may hold ALL n shards (a publisher / archival DA node) or just a subset (spread for k-of-n)."""

    def __init__(self, root, retain=None):
        # `retain` = the ROLLING WINDOW this class's own docstring promises: keep at most this many objects,
        # newest first, and drop the rest on every put(). None = unbounded (tests, and any caller that wants
        # to manage the window itself).
        #
        # WHY IT EXISTS. prune() was written for exactly this and, until 2026-08-06, was called from ONE
        # place in the whole tree: tests/test_da_store.py. Production never pruned, so the store grew
        # without bound. MEASURED on the betanet-15 node that day: exec_da held 41 GB in 109 objects
        # (1,916 files) — every settle proof published during the 2026-08-04/05 transport work, at ~390 MB
        # each (a ~120 MiB proof erasure-coded k=4/n=8). It was 99.8% of the node's 41 GB footprint; the
        # blocks themselves were 75 MB. A snapshot node had quietly become an archival one.
        #
        # A COUNT is the right bound rather than an age: it caps disk at retain x blob size regardless of
        # settle cadence, and it degrades safely — the newest objects, the only ones a peer can still be
        # fetching, are exactly the ones kept. Nothing needs the old ones: SETTLE_PROOF_DEPTH_GATED means a
        # proof is verified near the tip and deep blocks accept without re-fetching it.
        self.root = root
        self.retain = int(retain) if retain else None
        os.makedirs(root, exist_ok=True)
        self._pins = None                      # commitment -> L1 height it is kept until; loaded lazily (pins.json)
        # put() (and its sweep) runs in a worker thread for /da/publish while the exec tail pins on the event loop:
        # every pin read or write holds this, or a sweep iterating the pins mid-insert raises out of a publish.
        self._pin_lock = threading.RLock()

    # ---- pins: objects an on-chain exec op still needs ---------------------------------------------
    # THE EVICTION ROUTE TO THE EXEC STALL (audit 2026-09-25). The window above is a COUNT over every object, and
    # /da/publish and /da/announce are open (the relay proxies /da/ publicly): 24 junk publishes pushed a field
    # transfer's proof out of every store before a lagging exec node had applied its block, and that node then
    # stalled on it for good — or, under the exec DA deadline (execnode._da_deadline_passed), refused an op the
    # rest of the fleet had applied. So the exec tail PINS every proof it resolves for an on-chain op, until its own
    # cursor passes the op's height + a window; sweep() never counts or evicts a pinned object. Pins are bounded
    # (`cap`, oldest-expiring dropped first) so a flood of on-chain references cannot hold unbounded disk. Storage
    # policy only — no verdict reads a pin — so it needs no gate. Keep sweep() honouring pinned() (regression site).
    def _pins_path(self):
        return os.path.join(self.root, "pins.json")

    def _load_pins(self):
        if self._pins is None:
            try:
                raw = json.loads(open(self._pins_path(), "rb").read())
                self._pins = {str(c): int(u) for c, u in raw} if isinstance(raw, list) else {}
            except (OSError, ValueError, TypeError):
                self._pins = {}
        return self._pins

    def _save_pins(self):
        # a sorted list of pairs, never a dict: the file is local state, but it has no reason to depend on order
        _atomic_write(self._pins_path(), json.dumps(sorted(self._load_pins().items())).encode())

    def pinned(self):
        """The commitments sweep() must keep."""
        with self._pin_lock:
            return set(self._load_pins())

    def pin(self, commitment, until, cap=None):
        """Keep `commitment` out of the rolling window until the exec tail has applied past height `until`.
        Re-pinning keeps the later expiry. Never raises: a pin is an optimisation of availability, and a failed write
        must not fail the block application that asked for it."""
        try:
            self._dir(commitment)                                    # same path guard as every other entry point
        except (ValueError, TypeError):
            return
        with self._pin_lock:
            self._pin_locked(str(commitment), until, cap)

    def _pin_locked(self, c, until, cap):
        try:
            pins = self._load_pins()
            u = int(until)
            if pins.get(c, -1) >= u:
                return
            pins[c] = u
            if cap and len(pins) > int(cap):
                for old, _u in sorted(pins.items(), key=lambda kv: (kv[1], kv[0]))[:len(pins) - int(cap)]:
                    del pins[old]
            self._save_pins()
        except (OSError, ValueError, TypeError):
            pass

    def expire_pins(self, height):
        """Drop every pin whose window ended below `height` (the exec tail's applied height). Writes only on change."""
        with self._pin_lock:
            return self._expire_locked(height)

    def _expire_locked(self, height):
        try:
            pins = self._load_pins()
            gone = [c for c, u in pins.items() if u < int(height)]
            if gone:
                for c in gone:
                    del pins[c]
                self._save_pins()
            return len(gone)
        except (OSError, ValueError, TypeError):
            return 0

    def sweep(self, keep=None):
        """Drop all but the `keep` most recently written UNPINNED objects (pinned ones are kept on top of the
        window). Returns the number removed. Idempotent, and never raises on a concurrent writer — a directory that
        vanishes underneath us is already gone."""
        keep = self.retain if keep is None else int(keep)
        if not keep:
            return 0
        try:
            entries = []
            # A PINNED object is neither counted nor evicted (see pin()): the window bounds the objects nothing on
            # chain still needs, so a flood of publishes can no longer push out a proof an exec op is waiting on.
            keep_always = self.pinned()
            for name in os.listdir(self.root):
                d = os.path.join(self.root, name)
                if name in keep_always:
                    continue
                if os.path.isdir(d):
                    try:
                        entries.append((os.path.getmtime(d), name))
                    except OSError:
                        continue
            if len(entries) <= keep:
                return 0
            entries.sort(reverse=True)                 # newest first — those are the fetchable ones
            dropped = 0
            for _mt, name in entries[keep:]:
                shutil.rmtree(os.path.join(self.root, name), ignore_errors=True)
                dropped += 1
            return dropped
        except OSError:
            return 0

    def _dir(self, commitment):
        c = str(commitment)
        if not c or "/" in c or "\\" in c or c in (".", ".."):   # commitment is hex; refuse path traversal
            raise ValueError("bad commitment")
        return os.path.join(self.root, c)

    # ---- publisher side -------------------------------------------------------------------------
    def put(self, data: bytes, k: int = 4, n: int = 8) -> dict:
        """Erasure-code `data` (k-of-n) and persist meta + every (shard, proof). Returns the PUBLIC
        manifest {commitment,k,n,stripes,length} (no shard bytes) — what a publisher puts on-chain."""
        m = da.encode(data, k, n)
        d = self._dir(m["commitment"])
        os.makedirs(d, exist_ok=True)
        meta = {kk: m[kk] for kk in _META_KEYS}
        _atomic_write(os.path.join(d, "meta.json"), json.dumps(meta).encode())
        # KEEP THE ORIGINAL BYTES. get() otherwise reconstructs from shards AND re-encodes the result to
        # round-trip the commitment — a full decode plus a full encode. Measured on a 118 MiB settle proof:
        # 118 s for a /da/get of a blob this very process had encoded moments earlier.
        #
        # That is not merely wasteful, it BLOCKED SETTLEMENT: validate_transaction resolves a DA-carried
        # proof with an 8 s budget (_fetch_da_proof), so the publisher timed out fetching its OWN proof and
        # the settle was deferred as "not available via DA yet" — observed live 2026-08-04 at cursor 21214.
        #
        # Sound because the path is keyed by the commitment: _dir(m["commitment"]) is derived from the very
        # bytes we hashed here, so a blob found there IS the preimage of that commitment. Shards ACCEPTED
        # from a peer never write this file, so that path still reconstructs and re-verifies as before.
        _atomic_write(os.path.join(d, "blob.bin"), data)
        for i in range(n):
            sp = da.sample_proof(m, i)
            _atomic_write(os.path.join(d, f"{i}.shard"), sp["shard"])
            _atomic_write(os.path.join(d, f"{i}.proof"), json.dumps(sp["proof"]).encode())
        # ROLLING WINDOW, ENFORCED HERE so no caller can forget it — which is what let the store reach 41 GB.
        # Swept AFTER the write, so the object just published is always among the newest and never its own
        # victim.
        self.sweep()
        return meta

    # ---- distribution side ----------------------------------------------------------------------
    def accept(self, meta: dict, index: int, shard: bytes, proof) -> bool:
        """Store a single (shard, proof) received from a peer — ONLY if it verifies against the
        commitment. Lets a DA node hold a subset of shards for spread k-of-n availability. A shard that
        doesn't verify is rejected (returns False) and NOT written, so a donor can't poison the store."""
        c = meta["commitment"]
        # The manifest is bound into every leaf, so this one check now also refuses a donor whose
        # k/n/stripes/length disagree with the commitment — the meta written to meta.json below is
        # therefore authenticated, not merely asserted.
        if not da.verify_sample(c, index, shard, proof, meta):
            return False
        d = self._dir(c)
        os.makedirs(d, exist_ok=True)
        mp = os.path.join(d, "meta.json")
        if not os.path.exists(mp):
            _atomic_write(mp, json.dumps({kk: meta[kk] for kk in _META_KEYS}).encode())
        _atomic_write(os.path.join(d, f"{int(index)}.shard"), shard)
        _atomic_write(os.path.join(d, f"{int(index)}.proof"), json.dumps(proof).encode())
        return True

    # ---- serving / reading ----------------------------------------------------------------------
    def meta(self, commitment):
        """The stored manifest {commitment,k,n,stripes,length}, or None if this node has never seen it."""
        p = os.path.join(self._dir(commitment), "meta.json")
        return json.loads(open(p, "rb").read()) if os.path.exists(p) else None

    def have(self, commitment):
        """Sorted list of shard indices this node currently holds for `commitment`."""
        d = self._dir(commitment)
        if not os.path.isdir(d):
            return []
        return sorted(int(f[:-6]) for f in os.listdir(d) if f.endswith(".shard"))

    def shard(self, commitment, index):
        """(shard_bytes, proof) for serving to a peer, or None if not held. The proof lets the peer
        verify the shard against the commitment without trusting this node."""
        d = self._dir(commitment)
        sp = os.path.join(d, f"{int(index)}.shard")
        pp = os.path.join(d, f"{int(index)}.proof")
        if not (os.path.exists(sp) and os.path.exists(pp)):
            return None
        return open(sp, "rb").read(), json.loads(open(pp, "rb").read())

    def get(self, commitment):
        """Reconstruct the original bytes from locally-held shards (need >= k). None if too few. Uses
        da.reconstruct's over-determination check, so a corrupt local shard is caught, not decoded blind.

        A blob this node PUBLISHED is returned straight from disk — see put(): the directory is keyed by
        the commitment we computed from those exact bytes, so no decode or re-encode is needed to know they
        are the preimage. Shards accepted from a peer have no such file and take the reconstruct path."""
        _blob = os.path.join(self._dir(commitment), "blob.bin")
        if os.path.exists(_blob):
            try:
                return open(_blob, "rb").read()
            except OSError:
                pass                      # unreadable cache: fall through and reconstruct from shards
        meta = self.meta(commitment)
        if not meta:
            return None
        idxs = self.have(commitment)
        if len(idxs) < meta["k"]:
            return None
        known = {}
        for i in idxs:
            r = self.shard(commitment, i)
            if r:
                known[i] = r[0]
        try:
            data = da.reconstruct(meta, known)
            # meta (k/n/stripes/length) may have been stored from an untrusted peer's `accept`; round-trip the
            # result against the commitment so a lied manifest can't yield wrong-but-passing bytes.
            if da.encode(data, int(meta["k"]), int(meta["n"]))["commitment"] != commitment:
                return None
            return data
        except Exception:
            return None

    def prune(self, commitment):
        """Drop everything for a settled/expired commitment (rolling-window DA). Idempotent."""
        d = self._dir(commitment)
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)


def reconstruct_from(meta: dict, pairs) -> bytes:
    """Trustlessly reconstruct from k-of-n (index, shard, proof) tuples fetched from ANY DA nodes: verify
    each against the commitment first, then decode from the valid ones. Raises if fewer than k verify —
    so a set salted with bad shards can't corrupt the result, it just needs k GOOD ones."""
    c = meta["commitment"]
    known = {}
    for index, shard, proof in pairs:
        # `meta` is UNTRUSTED (it came from a peer alongside the shards) and it STEERS the decode, so it is
        # passed in and checked against the commitment rather than believed: the manifest is bound into
        # every leaf, so a lied k/n/stripes/length fails here with the shard.
        if da.verify_sample(c, index, shard, proof, meta):
            known[int(index)] = shard
    if len(known) < meta["k"]:
        raise ValueError(f"need {meta['k']} valid shards, have {len(known)}")
    # verify=False is not a weakening HERE: every shard in `known` has just been checked against the
    # commitment above, which binds both its bytes and the manifest. da.reconstruct's extra-shard
    # interpolation check is documented as belt-and-suspenders for callers that did NOT do that, and
    # keeping it would force the field-element path for the sake of a weaker test than the one already
    # passed — the byte-level systematic path cannot run while an extra shard is pending a consistency check.
    return da.reconstruct(meta, known, verify=False)
