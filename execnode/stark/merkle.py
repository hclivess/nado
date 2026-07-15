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
    layer = [b.leaf(v) for v in values]
    layers = [layer]
    while len(layer) > 1:
        layer = [b.node(layer[i], layer[i + 1]) for i in range(0, len(layer), 2)]
        layers.append(layer)
    return layers[-1][0], layers


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
