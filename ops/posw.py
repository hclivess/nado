"""
Hash-based Proof of Sequential Work (PoSW) — a POST-QUANTUM, trusted-setup-free replacement for the
parallelizable registration hashcash (see doc/ip-spoofing-and-sybil.md, Appendix A).

It prices a new identity in REAL, non-parallelizable sequential time: the prover must walk a length-T hash
chain (each step depends on the previous, so GPU/ASIC parallelism gives only a bounded constant speedup),
while the verifier checks only a few Fiat-Shamir-selected segments + Merkle openings — so verification, and
rejecting a garbage proof, is O(k·S), not O(T). It assumes ONLY that blake2b is a decent hash (the same
assumption the chain already makes) — no unknown-order group, no elliptic curve, no quantum-vulnerable
primitive (unlike an algebraic VDF, which Shor breaks along with ECC).

Scheme (checkpointed sequential chain + Fiat-Shamir spot-checks):
  h_0 = H(challenge);  h_i = H(h_{i-1});  checkpoints c_m = h_{m·S}  for m in 0..C   (C = T // S)
  root R = Merkle(c_0 … c_C);  opened segments = {0} ∪ FiatShamir(H(R), k)
  verify: for each opened segment m, Merkle-check c_m and c_{m+1}, then recompute S steps c_m → c_{m+1};
          segment 0 also binds c_0 == H(challenge).

NOT YET WIRED INTO CONSENSUS. On adoption, (T, S, k) become fixed protocol.py constants and a byte-identical
prover ships in the browser client.
"""
import hashlib

from protocol import POSW_T, POSW_S, POSW_K   # authoritative consensus parameters


def _h(b: bytes) -> bytes:
    return hashlib.blake2b(b, digest_size=32).digest()


# --- indexed binary Merkle over the ordered checkpoints (position matters; duplicate last if odd) ---
def _merkle_layers(leaves):
    layers = [list(leaves)]
    cur = layers[0]
    while len(cur) > 1:
        cur = [_h(cur[i] + (cur[i + 1] if i + 1 < len(cur) else cur[i])) for i in range(0, len(cur), 2)]
        layers.append(cur)
    return layers


def _merkle_proof(layers, idx):
    proof = []
    for layer in layers[:-1]:
        sib = idx ^ 1
        proof.append(layer[sib] if sib < len(layer) else layer[idx])
        idx //= 2
    return proof


def _merkle_verify(leaf, idx, proof, root):
    h = leaf
    for sib in proof:
        h = _h(sib + h) if (idx & 1) else _h(h + sib)
        idx //= 2
    return h == root


def _fiat_shamir(root: bytes, C: int, k: int):
    return [int.from_bytes(_h(root + i.to_bytes(4, "big")), "big") % C for i in range(k)]


def prove(challenge: bytes, T: int = POSW_T, S: int = POSW_S, k: int = POSW_K) -> dict:
    """Compute the PoSW for `challenge`. Sequential and slow by design (walks the whole T-step chain)."""
    C = T // S
    checkpoints = [_h(challenge)]                       # c_0 = h_0
    h = checkpoints[0]
    for _m in range(1, C + 1):
        for _ in range(S):
            h = _h(h)
        checkpoints.append(h)                           # c_m = h_{m·S}
    layers = _merkle_layers(checkpoints)
    root = layers[-1][0]
    segs = sorted(set([0] + _fiat_shamir(root, C, k)))  # segment 0 always (binds c_0 = H(challenge))
    openings = [{
        "j": j,
        "cj": checkpoints[j].hex(),
        "cj1": checkpoints[j + 1].hex(),
        "pj": [p.hex() for p in _merkle_proof(layers, j)],
        "pj1": [p.hex() for p in _merkle_proof(layers, j + 1)],
    } for j in segs]
    return {"root": root.hex(), "openings": openings}


def verify(challenge: bytes, proof: dict, T: int = POSW_T, S: int = POSW_S, k: int = POSW_K) -> bool:
    """Cheap check (O(k·S)): the opened segments match Fiat-Shamir, their Merkle openings match the root,
    and each opened segment recomputes correctly. A bogus/short proof fails on the first opened segment."""
    try:
        C = T // S
        root = bytes.fromhex(proof["root"])
        expected = sorted(set([0] + _fiat_shamir(root, C, k)))
        opened = {int(o["j"]): o for o in proof["openings"]}
        if sorted(opened.keys()) != expected:
            return False
        h0 = _h(challenge)
        for j in expected:
            o = opened[j]
            cj, cj1 = bytes.fromhex(o["cj"]), bytes.fromhex(o["cj1"])
            pj = [bytes.fromhex(x) for x in o["pj"]]
            pj1 = [bytes.fromhex(x) for x in o["pj1"]]
            if not _merkle_verify(cj, j, pj, root):
                return False
            if not _merkle_verify(cj1, j + 1, pj1, root):
                return False
            if j == 0 and cj != h0:                     # bind the chain start to the challenge
                return False
            h = cj
            for _ in range(S):                          # recompute the S sequential steps of this segment
                h = _h(h)
            if h != cj1:
                return False
        return True
    except Exception:
        return False


def challenge_bytes(address: str, recent_block_hash: str) -> bytes:
    """Registration challenge — binds the proof to THIS identity and a recent block (un-precomputable,
    non-reusable). Both sides construct it identically."""
    return (str(address) + "|" + str(recent_block_hash)).encode()
