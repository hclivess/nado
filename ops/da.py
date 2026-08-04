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


def _leaf(index, shard: bytes, k, n, stripes, length) -> bytes:
    """Canonical Merkle leaf for shard `index`, binding BOTH the index and the whole manifest.

    The index makes a shard unswappable — a valid proof for index i cannot be replayed at index j (the
    merkle set is order-independent, so the index MUST live in the leaf content).

    THE MANIFEST IS BOUND FOR THE SAME REASON. It used to sit outside the commitment, so (k, n, stripes,
    length) arrived from an untrusted peer while STEERING the decode: a smaller `length` truncates to
    different bytes that still pass every per-shard check. The only defence available then was to decode
    and RE-ENCODE the whole blob and compare commitments — ~50 s on a 118 MiB settle proof, inside block
    validation, which is precisely why a peer could not resolve a DA-carried proof in time. Binding the
    manifest into every leaf makes a lied manifest change every leaf hash, so the SAME Merkle proof that
    already authenticates the shard now authenticates the manifest too, and the round-trip disappears.

    This CHANGES THE COMMITMENT for identical bytes; commitments are not comparable across the change."""
    return canonical_bytes(["da", int(index), shard.hex(), int(k), int(n), int(stripes), int(length)])
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


_ENC_MATRIX_CACHE = {}


def _enc_matrix(k, n):
    """The k->n systematic Reed-Solomon generator matrix over GF(P), CACHED per (k, n).

    The encode's interpolation points never vary: the data sits at x = 1..k and the shards are read off at
    x = 1..n. So the Lagrange basis coefficients L_i(x) are CONSTANTS — they do not depend on the data at
    all — and row x of this matrix is exactly [L_0(x), …, L_{k-1}(x)].

    They were being recomputed for every stripe, and each recomputation ran _inv() = pow(a, P-2, P), a full
    modular exponentiation, in the innermost loop: n·k = 32 modexps per stripe. A 118 MiB blob is ~17.7M
    symbols = ~4.4M stripes = ~141 MILLION modexps, and encode measured 15 s/MiB — about 30 minutes for one
    settlement proof. That is why a proof that passed its self-checks ("settle-with-proof BUILT", 13:35)
    produced no DA publish for as long as anyone watched.

    Same arithmetic, hoisted out of the loop: the encoded symbols are bit-identical (verified against the
    previous implementation over random inputs in tests/test_da_encode_matrix.py), so commitments and
    already-published blobs are unaffected."""
    key = (int(k), int(n))
    m = _ENC_MATRIX_CACHE.get(key)
    if m is None:
        m = []
        for x in range(1, n + 1):
            row = []
            for i in range(k):
                xi = i + 1
                num = den = 1
                for j in range(k):
                    if i == j:
                        continue
                    xj = j + 1
                    num = num * ((x - xj) % P) % P
                    den = den * ((xi - xj) % P) % P
                row.append(num * _inv(den) % P)
            m.append(row)
        _ENC_MATRIX_CACHE[key] = m
    return m


def _encode_stripe(data_syms, n):
    """k data symbols -> n shard symbols (systematic: the first k shards ARE the data). Any k of the n
    recover the degree-(k-1) polynomial, hence all symbols."""
    k = len(data_syms)
    M = _enc_matrix(k, n)
    ys = [s % P for s in data_syms]
    out = []
    for x in range(n):
        row = M[x]
        acc = 0
        for i in range(k):
            acc += row[i] * ys[i]
        out.append(acc % P)
    return out


def _pack(data):
    """bytes -> list of field symbols (7 bytes each, last zero-padded). Returns (symbols, original_length)."""
    syms = [int.from_bytes(data[i:i + SYMBOL_BYTES].ljust(SYMBOL_BYTES, b"\x00"), "big")
            for i in range(0, max(len(data), 1), SYMBOL_BYTES)]
    return syms, len(data)


def _unpack(syms, length):
    """Inverse of _pack: symbols -> bytes, truncated to the original length.

    A valid codeword's data symbols are always < 2**56 (7-byte packs from _pack), so composing 8 bytes
    and slicing the low 7 is lossless. A symbol >= 2**56 can ONLY come from a non-codeword (a corrupt or
    forged shard reconstructed with exactly k points, where the redundancy consistency check is skipped);
    silently dropping its high byte would return plausible-looking wrong bytes with no error. Raise instead
    so bad input is caught here rather than propagated as a valid-looking blob."""
    out = bytearray()
    for s in syms:
        s = int(s) % P
        if s >> (SYMBOL_BYTES * 8):   # any bit above the 56-bit data range -> not a real data symbol
            raise ValueError("da: reconstructed symbol out of 7-byte data range (corrupt shard set)")
        out += s.to_bytes(SYMBOL_BYTES, "big")
    return bytes(out[:length])


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
    # hash-based (PQ) Merkle commitment, index- AND manifest-bound (see _leaf)
    leaves = [_leaf(j, shards[j], k, n, stripes, length) for j in range(n)]
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
    # SORTED, so the k SYSTEMATIC shards (indices 0..k-1) are preferred over parity whenever they are
    # available, and so the choice no longer depends on dict insertion order (i.e. on the order shards
    # happened to arrive from the network). Any k shards reconstruct the same bytes, so this changes no
    # output — it only decides which arithmetic path below can be taken.
    idx_list = sorted(sym_by_idx)
    use, extra = idx_list[:k], (idx_list[k:] if verify else [])
    # SYSTEMATIC FAST PATH. _encode_stripe is systematic: shard j < k IS data symbol j. So when the chosen
    # k are exactly 0..k-1 the decode matrix below is the IDENTITY and the whole per-stripe matrix-vector
    # product is a no-op computed the expensive way — k*k modmuls per stripe, ~70 MILLION for a 118 MiB
    # proof, ~55 s of pure Python. That cost is what makes a peer unable to resolve a settle proof inside
    # block validation, which is why a proof-carrying settle cannot survive on a fleet where only one node
    # holds the data. Reconstruction from parity still takes the general path unchanged.
    systematic = (use == list(range(k)))

    # HOIST THE LAGRANGE BASIS OUT OF THE STRIPE LOOP — the same fix 08945e50 made on the encode side,
    # and for the same reason: the basis depends ONLY on the x-coordinates, and here those are the CHOSEN
    # SHARD INDICES, identical for every stripe. Only the y-values change. Rebuilding it per stripe meant
    # _lagrange_eval -> _inv(den) = pow(a, P-2, P), a full modular exponentiation, k*k times per stripe:
    # for a 118 MiB blob that is ~4.4M stripes x 16 = ~70 MILLION modexps.
    #
    # THIS WEDGED THE LIVE NODE, TWICE. h_da_get calls DaStore.get -> reconstruct SYNCHRONOUSLY on the
    # event loop, so a single /da/get for a 118 MiB proof froze the exec node completely — HTTP dead, no
    # log output, block application stopped, until it was restarted. py-spy caught it in the act:
    #     _inv (ops/da.py:30) <- _lagrange_eval <- reconstruct <- get <- h_da_get <- aiohttp
    # I had blamed the publish path for those wedges; it was the DECODE, triggered by fetching the blob.
    #
    # DECODE MATRIX: M[j][i] = L_i(x_j) for the k systematic outputs x_j = 1..k, over the k chosen points.
    # Same arithmetic, hoisted, so the reconstructed bytes are bit-identical (checked against the previous
    # implementation as an oracle in tests/test_da_reconstruct_matrix.py).
    xs = [idx + 1 for idx in use]
    dec = []
    if not systematic:
        for xj in range(1, k + 1):
            row = []
            for i, xi in enumerate(xs):
                num = den = 1
                for m, xm in enumerate(xs):
                    if m == i:
                        continue
                    num = num * ((xj - xm) % P) % P
                    den = den * ((xi - xm) % P) % P
                row.append(num * _inv(den) % P)
            dec.append(row)

    # The redundancy check re-evaluates the SYSTEMATIC polynomial (x-coords 1..k, also constant) at each
    # extra shard's position, so its basis is constant per extra index too.
    ext = {}
    for idx in extra:
        xe, row = idx + 1, []
        for i in range(k):
            xi = i + 1
            num = den = 1
            for m in range(k):
                if m == i:
                    continue
                xm = m + 1
                num = num * ((xe - xm) % P) % P
                den = den * ((xi - xm) % P) % P
            row.append(num * _inv(den) % P)
        ext[idx] = row

    out_syms = []
    for s in range(stripes):
        ys = [sym_by_idx[idx][s] % P for idx in use]
        # identity decode when the systematic shards were chosen — the data symbols ARE the shard symbols
        data = ys if systematic else [sum(dec[j][i] * ys[i] for i in range(k)) % P for j in range(k)]
        for idx, row in ext.items():
            if sum(row[i] * data[i] for i in range(k)) % P != sym_by_idx[idx][s] % P:
                raise ValueError(f"shard {idx} inconsistent with the k-of-n interpolation (corrupt shard)")
        out_syms.extend(data)
    return _unpack(out_syms, length)


def _meta_of(m):
    """(k, n, stripes, length) from a manifest/meta dict — the tuple bound into every leaf."""
    return int(m["k"]), int(m["n"]), int(m["stripes"]), int(m["length"])


def sample_proof(manifest, index: int):
    """Merkle proof that shard `index` belongs to the commitment — what a sampler downloads with the shard."""
    k, n, stripes, length = _meta_of(manifest)
    leaves = [_leaf(j, manifest["shards"][j], k, n, stripes, length) for j in range(n)]
    return {"index": index, "shard": manifest["shards"][index],
            "proof": merkle_proof(leaves, _leaf(index, manifest["shards"][index], k, n, stripes, length))}


def verify_sample(commitment, index: int, shard: bytes, proof, meta) -> bool:
    """A light client / phone check: does this (index, shard) hash into the committed set, UNDER THIS
    MANIFEST? (Availability sampling.)

    The index is bound into the leaf, so a shard proof cannot be replayed at another index. `meta` is bound
    too, so this ALSO authenticates (k, n, stripes, length): a peer that lies about the manifest — e.g. a
    shorter `length`, which would truncate the decode to different bytes that still pass every per-shard
    check — produces leaves that do not hash to the commitment, and is rejected here rather than after an
    expensive re-encode round-trip. `meta` is therefore an INPUT to be checked, never trusted."""
    try:
        k, n, stripes, length = _meta_of(meta)
    except (KeyError, TypeError, ValueError):
        return False
    return verify_merkle_proof(_leaf(index, shard, k, n, stripes, length), proof, commitment)
