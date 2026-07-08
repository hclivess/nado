"""
Data availability: Reed-Solomon erasure coding + a hash-based (PQ) Merkle commitment + sample verification.

The DA primitive for rolling mode / execution-layer blobs (doc/rolling-mode-and-da.md §4.2): encode a blob into
`n` shards of which ANY `k` reconstruct the whole (so no single node must hold everything), commit to the shard
set with a **blake2b Merkle root — NOT KZG** (post-quantum: hash-based only), and let a light client verify an
individual sampled shard against that commitment. If enough random samples are available, the whole is (whp)
reconstructable — phones sample instead of storing.

Reference implementation: a systematic Reed-Solomon over the Mersenne prime P = 2^61-1 via Lagrange
interpolation. Correct and deterministic (integer-only, no floats); O(n·k^2) per stripe — fine for DA-sized
shard counts. A production node would swap the interpolation for an FFT-based codec behind the same interface.
"""
from hashing import canonical_bytes, merkle_root, merkle_proof, verify_merkle_proof

P = (1 << 61) - 1          # Mersenne prime; a field element fits in 8 bytes (61 < 64 bits)


def _leaf(index, shard: bytes) -> bytes:
    """Canonical Merkle leaf for shard `index`. Binding the index makes a shard unswappable — a valid
    proof for index i cannot be replayed at index j (the merkle set is order-independent, so the index
    MUST live in the leaf content)."""
    return canonical_bytes(["da", int(index), shard.hex()])
SYMBOL_BYTES = 7           # 7 data bytes per field element (56 bits < 61) — the input packing granule
_WORD = 8                  # on-wire bytes per field element (big-endian, fixed width)


def _inv(a):
    """Modular inverse in GF(P) via Fermat (P prime)."""
    return pow(a % P, P - 2, P)


def _lagrange_eval(points, x):
    """Evaluate the polynomial interpolating `points` = [(xi, yi), …] at `x`, in GF(P). Integer-only."""
    x %= P
    total = 0
    for i, (xi, yi) in enumerate(points):
        num = den = 1
        for j, (xj, _) in enumerate(points):
            if i == j:
                continue
            num = num * ((x - xj) % P) % P
            den = den * ((xi - xj) % P) % P
        total = (total + yi % P * num % P * _inv(den)) % P
    return total


def _encode_stripe(data_syms, n):
    """k data symbols -> n shard symbols (systematic: the first k shards ARE the data). Any k of the n
    recover the degree-(k-1) polynomial, hence all symbols."""
    pts = [(i + 1, data_syms[i] % P) for i in range(len(data_syms))]   # interpolate through x = 1..k
    return [_lagrange_eval(pts, x) for x in range(1, n + 1)]           # evaluate at x = 1..n


def _decode_stripe(known, k):
    """known = {shard_index(0-based): symbol}; needs >= k entries. Recover the k data symbols (x = 1..k)."""
    pts = [(idx + 1, sym % P) for idx, sym in list(known.items())[:k]]
    if len(pts) < k:
        raise ValueError(f"need >= {k} shards to reconstruct, have {len(pts)}")
    return [_lagrange_eval(pts, x) for x in range(1, k + 1)]


def _pack(data):
    """bytes -> list of field symbols (7 bytes each, last zero-padded). Returns (symbols, original_length)."""
    syms = [int.from_bytes(data[i:i + SYMBOL_BYTES].ljust(SYMBOL_BYTES, b"\x00"), "big")
            for i in range(0, max(len(data), 1), SYMBOL_BYTES)]
    return syms, len(data)


def _unpack(syms, length):
    """Inverse of _pack: symbols -> bytes, truncated to the original length."""
    out = b"".join(int(s % P).to_bytes(SYMBOL_BYTES + 1, "big")[-SYMBOL_BYTES:] for s in syms)
    return out[:length]


def _shard_bytes(shard_syms):
    return b"".join(int(s % P).to_bytes(_WORD, "big") for s in shard_syms)


def _shard_syms(shard_bytes):
    return [int.from_bytes(shard_bytes[i:i + _WORD], "big") for i in range(0, len(shard_bytes), _WORD)]


def encode(data: bytes, k: int, n: int):
    """Erasure-encode `data` into `n` shards, any `k` of which reconstruct it, plus a hash-based Merkle
    commitment over the shard set. Returns a manifest dict:
        {commitment, k, n, stripes, length, shards:[bytes,…], shard_hashes:[hex,…]}
    `commitment` is what goes in the block header; a sampler checks one shard against it with sample_proof."""
    if not (0 < k <= n):
        raise ValueError("require 0 < k <= n")
    syms, length = _pack(data)
    while len(syms) % k:                          # pad the last stripe with zero symbols
        syms.append(0)
    stripes = len(syms) // k
    # shard j gets the j-th symbol of every stripe
    shard_syms = [[] for _ in range(n)]
    for s in range(stripes):
        enc = _encode_stripe(syms[s * k:(s + 1) * k], n)
        for j in range(n):
            shard_syms[j].append(enc[j])
    shards = [_shard_bytes(ss) for ss in shard_syms]
    leaves = [_leaf(j, shards[j]) for j in range(n)]   # hash-based (PQ) Merkle commitment, index-bound
    return {"commitment": merkle_root(leaves), "k": k, "n": n, "stripes": stripes,
            "length": length, "shards": shards}


def reconstruct(manifest_meta, known_shards: dict, verify: bool = True):
    """Reconstruct the original bytes from ANY k shards. manifest_meta carries {k, stripes, length};
    known_shards = {index(0-based): shard_bytes}. Raises if fewer than k shards are supplied.

    When MORE than k shards are supplied and verify=True (default), each extra shard is checked for
    consistency against the k-shard interpolation — a single corrupt/malicious shard is DETECTED (raises)
    instead of silently producing wrong bytes. (Callers should still `verify_sample` each shard against the
    commitment; this is a cheap belt-and-suspenders when redundancy is available.)"""
    k = manifest_meta["k"]; stripes = manifest_meta["stripes"]; length = manifest_meta["length"]
    if len(known_shards) < k:
        raise ValueError(f"need >= {k} shards, have {len(known_shards)}")
    sym_by_idx = {idx: _shard_syms(b) for idx, b in known_shards.items()}
    idx_list = list(sym_by_idx)
    use, extra = idx_list[:k], (idx_list[k:] if verify else [])
    out_syms = []
    for s in range(stripes):
        pts = [(idx + 1, sym_by_idx[idx][s] % P) for idx in use]
        data = [_lagrange_eval(pts, x) for x in range(1, k + 1)]
        if extra:
            dpts = [(i + 1, data[i]) for i in range(k)]
            for idx in extra:
                if _lagrange_eval(dpts, idx + 1) != sym_by_idx[idx][s] % P:
                    raise ValueError(f"shard {idx} inconsistent with the k-of-n interpolation (corrupt shard)")
        out_syms.extend(data)
    return _unpack(out_syms, length)


def sample_proof(manifest, index: int):
    """Merkle proof that shard `index` belongs to the commitment — what a sampler downloads with the shard."""
    leaves = [_leaf(j, manifest["shards"][j]) for j in range(manifest["n"])]
    return {"index": index, "shard": manifest["shards"][index],
            "proof": merkle_proof(leaves, _leaf(index, manifest["shards"][index]))}


def verify_sample(commitment, index: int, shard: bytes, proof) -> bool:
    """A light client / phone check: does this (index, shard) hash into the committed set? (Availability
    sampling.) The index is bound into the leaf, so a shard proof cannot be replayed at another index."""
    return verify_merkle_proof(_leaf(index, shard), proof, commitment)
