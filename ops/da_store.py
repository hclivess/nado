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

    def __init__(self, root):
        self.root = root
        os.makedirs(root, exist_ok=True)

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
        for i in range(n):
            sp = da.sample_proof(m, i)
            _atomic_write(os.path.join(d, f"{i}.shard"), sp["shard"])
            _atomic_write(os.path.join(d, f"{i}.proof"), json.dumps(sp["proof"]).encode())
        return meta

    # ---- distribution side ----------------------------------------------------------------------
    def accept(self, meta: dict, index: int, shard: bytes, proof) -> bool:
        """Store a single (shard, proof) received from a peer — ONLY if it verifies against the
        commitment. Lets a DA node hold a subset of shards for spread k-of-n availability. A shard that
        doesn't verify is rejected (returns False) and NOT written, so a donor can't poison the store."""
        c = meta["commitment"]
        if not da.verify_sample(c, index, shard, proof):
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
        da.reconstruct's over-determination check, so a corrupt local shard is caught, not decoded blind."""
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
        if da.verify_sample(c, index, shard, proof):
            known[int(index)] = shard
    if len(known) < meta["k"]:
        raise ValueError(f"need {meta['k']} valid shards, have {len(known)}")
    return da.reconstruct(meta, known)
