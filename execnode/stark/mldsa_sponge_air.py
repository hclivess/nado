"""
ML-DSA-44 verify AIR — sub-circuit 7: the SHAKE SPONGE (absorb / squeeze), composed from the proven
Keccak-f[1600] permutation AIR (mldsa_keccak_air).

A sponge is: pad the message, XOR each rate-sized block into the state's rate lanes and permute (absorb), then
read the rate lanes out, permuting between reads (squeeze). The permutation is already a proven AIR, so the
sponge is the CHAINING around it:

    state_0 = 0
    absorb block i:  state_i' = state_i XOR block_i (rate lanes only)   ->   state_{i+1} = keccak_f(state_i')
    squeeze:         out = rate lanes of state; permute for each further rate-sized chunk

WHAT THE CHAINING PROVES. Each permutation step is one `prove_permutation` proof whose PUBLIC input/output
states are pinned by boundaries. The sponge verifier re-derives every intermediate state itself from the
PUBLIC message + the proven outputs — the XOR-in of a public block into public rate lanes is a public
computation, so no extra circuit is needed for it — and checks that each proof's input state equals what the
previous step produced. That makes the whole chain verifier-authoritative: a prover cannot substitute a
different message, block boundary, or intermediate state.

Padding is FIPS 202 pad10*1 with the SHAKE domain separator 0x1F, and it is applied by the verifier (public,
derived from the message length), never taken on the prover's word.

Golden reference: hashlib.shake_128 / shake_256 (OpenSSL).
"""
from execnode.stark import mldsa_keccak_air as K

RATE_128 = 168                  # SHAKE128 rate in bytes (1344 bits)
RATE_256 = 136                  # SHAKE256 rate in bytes (1088 bits)
DS = 0x1F                       # SHAKE domain separator


def pad(data, rate_bytes):
    """FIPS 202 pad10*1 with the SHAKE domain byte — a PUBLIC function of the message and rate."""
    buf = bytearray(data)
    buf.append(DS)
    while len(buf) % rate_bytes != 0:
        buf.append(0)
    buf[-1] |= 0x80
    return bytes(buf)


def blocks(data, rate_bytes):
    """The padded message split into rate-sized blocks (public)."""
    p = pad(data, rate_bytes)
    return [p[i:i + rate_bytes] for i in range(0, len(p), rate_bytes)]


def _xor_block(state, block, rate_bytes):
    """XOR a rate-sized block into the state's rate lanes (public: both operands are public here)."""
    st = K._state_to_bytes(state)
    mixed = bytes(a ^ b for a, b in zip(st[:rate_bytes], block)) + st[rate_bytes:]
    return K._bytes_to_state(mixed)


def schedule(data, out_len, rate_bytes):
    """The full sponge SCHEDULE: the ordered list of permutation steps as (state_in, state_out), plus the
    output bytes. Every state here is derived from PUBLIC data, so a verifier can rebuild the whole list.
    Returns (steps, output)."""
    state = [0] * K.LANES
    steps = []
    for blk in blocks(data, rate_bytes):
        pre = _xor_block(state, blk, rate_bytes)
        post = K.keccak_f(pre)
        steps.append((pre, post))
        state = post
    out = b""
    while len(out) < out_len:
        out += K._state_to_bytes(state)[:rate_bytes]
        if len(out) < out_len:
            pre = list(state)
            state = K.keccak_f(pre)
            steps.append((pre, state))
    return steps, out[:out_len]


def shake(data, out_len, rate_bytes):
    """Reference sponge output (must equal hashlib)."""
    return schedule(data, out_len, rate_bytes)[1]


def shake128(data, out_len):
    return shake(data, out_len, RATE_128)


def shake256(data, out_len):
    return shake(data, out_len, RATE_256)


def prove(data, out_len, rate_bytes, num_queries=None, backend=None):
    """Prove a full SHAKE evaluation: one permutation proof per sponge step. Returns (proofs, output).

    NOTE ON COST: each step is a full 24-round Keccak-f proof, so an n-block absorb costs n proofs. This is why
    the design folds them (the K→1 recursion) rather than shipping them separately, and why ExpandA — which
    squeezes many blocks per polynomial — dominates the whole ML-DSA circuit."""
    from execnode.stark import stark
    nq = num_queries if num_queries is not None else stark.NUM_QUERIES
    steps, out = schedule(data, out_len, rate_bytes)
    proofs = []
    for (pre, _post) in steps:
        proof, _ = K.prove_permutation(pre, num_queries=nq, backend=backend)
        proofs.append(proof)
    return proofs, out


def verify(proofs, data, out_len, rate_bytes, num_queries=None, backend=None):
    """Verify a proven SHAKE evaluation against the PUBLIC message and claimed output.

    The verifier REBUILDS the entire schedule itself (padding, block splitting, the XOR-in of each block, and
    which states feed which permutation), then checks one proof per step against those pinned states. So the
    proofs only attest the permutations; the sponge structure — message, padding, block boundaries, chaining,
    and the squeezed output — is verifier-derived and cannot be influenced by the prover.
    Returns (ok, reason)."""
    from execnode.stark import stark
    try:
        nq = num_queries if num_queries is not None else stark.NUM_QUERIES
        steps, want = schedule(data, out_len, rate_bytes)
        if len(proofs) != len(steps):
            return False, f"expected {len(steps)} permutation proofs, got {len(proofs)}"
        for i, (proof, (pre, post)) in enumerate(zip(proofs, steps)):
            ok, why = K.verify_permutation(proof, pre, post, num_queries=nq, backend=backend)
            if not ok:
                return False, f"sponge step {i}: {why}"
        return True, f"ok ({len(steps)} permutation steps, output {len(want)}B)"
    except Exception as e:
        return False, f"malformed sponge proof: {e}"
