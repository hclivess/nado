"""
Binary Merkle commitment over a vector of field elements — the polynomial-commitment primitive FRI/STARK
stands on (doc/privacy.md). Post-quantum: the only assumption is that the leaf/node hash is collision
resistant. The hash is supplied by a BACKEND (execnode/stark/backend.py) — BLAKE2b by default (byte-identical
to the original), or the wide-sponge `alghash2` for proofs that must be verified inside a STARK (recursion,
doc/zk-recursion.md). Vectors are always a power of two (STARK evaluation domains).
"""
from execnode.stark import backend as _backend


def commit(values, backend=None):
    """Return (root, layers). layers[0] = leaf digests, layers[-1] = [root]."""
    b = backend or _backend.DEFAULT
    n = len(values)
    if n & (n - 1):
        raise ValueError("Merkle vector length must be a power of two")
    bname = getattr(b, "name", None)
    if bname == "alghash2":                          # native whole-tree build (shielded/exec hot path)
        from execnode.stark import alghash2
        r = alghash2.merkle_commit(values)
        if r is not None:
            return r
    elif bname == "recursion":                       # native rleaf/rnode whole-tree (recursion/fold hot path)
        from execnode.stark import alghash2
        r = alghash2.rmerkle_commit(values)
        if r is not None:
            return r
    layer = [b.leaf(v) for v in values]
    layers = [layer]
    while len(layer) > 1:
        layer = [b.node(layer[i], layer[i + 1]) for i in range(0, len(layer), 2)]
        layers.append(layer)
    return layers[-1][0], layers


def commit_digests(digests, backend=None):
    """Tree over PRECOMPUTED leaf digests (row-commitment: the caller hashed each whole trace row already).
    Only b.node is used. Returns (root, layers) with the same structure as commit."""
    b = backend or _backend.DEFAULT
    n = len(digests)
    if n & (n - 1):
        raise ValueError("Merkle vector length must be a power of two")
    layer = list(digests)
    layers = [layer]
    while len(layer) > 1:
        layer = [b.node(layer[i], layer[i + 1]) for i in range(0, len(layer), 2)]
        layers.append(layer)
    return layers[-1][0], layers


def verify_digest(root, index, leaf_digest, path, backend=None):
    """Like verify, but starting from a PRECOMPUTED leaf digest (row-commitment openings)."""
    b = backend or _backend.DEFAULT
    h, idx = leaf_digest, index
    for sib in path:
        h = b.node(h, sib) if idx % 2 == 0 else b.node(sib, h)
        idx //= 2
    return h == root


def open_at(layers, index):
    """Authentication path (sibling digests, bottom-up) for the leaf at `index`."""
    path, idx = [], index
    for layer in layers[:-1]:
        path.append(layer[idx ^ 1])
        idx //= 2
    return path


def verify(root, index, value, path, backend=None):
    """Recompute the root from (index, value, path) bottom-up; True iff it equals `root`."""
    b = backend or _backend.DEFAULT
    h, idx = b.leaf(value), index
    for sib in path:
        h = b.node(h, sib) if idx % 2 == 0 else b.node(sib, h)
        idx //= 2
    return h == root
