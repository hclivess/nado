"""
Binary Merkle commitment over a vector of field elements — the polynomial-commitment primitive FRI/STARK
stands on (doc/privacy.md). Post-quantum: the ONLY assumption is that BLAKE2b is collision-resistant, the same
trust NADO already places in it everywhere else. Vectors are always a power of two (STARK evaluation domains),
so no odd-node padding is ever needed.
"""
from hashing import blake2b_hash


def _leaf(x):
    """Domain-separated leaf hash of one field element."""
    return blake2b_hash(["stark-leaf", str(int(x))])


def _node(a, b):
    """Domain-separated inner-node hash of two child digests."""
    return blake2b_hash(["stark-node", a, b])


def commit(values):
    """Return (root, layers). layers[0] = leaf hashes, layers[-1] = [root]."""
    n = len(values)
    if n & (n - 1):
        raise ValueError("Merkle vector length must be a power of two")
    layer = [_leaf(v) for v in values]
    layers = [layer]
    while len(layer) > 1:
        layer = [_node(layer[i], layer[i + 1]) for i in range(0, len(layer), 2)]
        layers.append(layer)
    return layers[-1][0], layers


def open_at(layers, index):
    """Authentication path (sibling hashes, bottom-up) for the leaf at `index`."""
    path, idx = [], index
    for layer in layers[:-1]:
        path.append(layer[idx ^ 1])
        idx //= 2
    return path


def verify(root, index, value, path):
    """Recompute the root from (index, value, path) bottom-up; True iff it equals `root`."""
    h, idx = _leaf(value), index
    for sib in path:
        h = _node(h, sib) if idx % 2 == 0 else _node(sib, h)
        idx //= 2
    return h == root
