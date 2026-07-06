"""
Arithmetisation of the shielded join-split (doc/privacy.md) — the AIR that turns the pool's checks into a
zero-knowledge STARK.

The workhorse is the SPONGE-HASH gadget: hashn(messages) laid out as a trace so that a STARK can prove it was
computed correctly WITHOUT revealing the (private) messages. Every join-split check is that gadget:
  * note commitment  cm = hashn([DOM_CM, value, owner, rho])
  * nullifier        nf = hashn([DOM_NF, nsk, rho])
  * owner            owner = hashn([DOM_OWNER, nsk])
  * Merkle node      hashn([DOM_NODE, left, right])   (a membership path is a chain of these)
Value conservation is a single linear boundary. Proving one hash preimage in ZK is the hard, novel part — it
composes upward into the full circuit (membership chain + shared nsk across owner/nullifier + conservation).

TRACE (columns s0, s1, ab):  s0/s1 = the width-2 sponge state entering each round; ab = the message being
absorbed for the current block (held constant within a block). One row per S-box round; ROUNDS rows per
absorbed message. PERIODIC public columns rc0/rc1 (round constants) and b (1 at each block boundary that has a
next message) drive it. Constraints per step:
  t0=(s0+rc0)^7, t1=(s1+rc1)^7 ;  r0=2·t0+1·t1, r1=1·t0+3·t1        (round-constants → x^7 → MDS)
  C1: s1' = r1
  C2: s0' = r0 + b·ab'            (absorb the new message at a block boundary)
  C3: (1-b)·(ab' - ab) = 0        (hold the message constant within a block)
Boundaries pin the PUBLIC parts (the domain tag, the capacity IV, and the hash output); the message elements
that must stay secret are free witness — that is the zero-knowledge.
"""
from execnode.stark import field as F, alghash, stark

R = alghash.ROUNDS
S0, S1, AB = 0, 1, 2                      # trace columns
MAX_DEGREE = alghash.ALPHA               # 7


def _next_pow2(x):
    """Smallest power of two >= x (trace/FRI evaluation domains are power-of-two sized)."""
    p = 1
    while p < x:
        p <<= 1
    return p


def build_trace(messages):
    """Full sponge trace for hashn(messages). Returns (trace, T, k, output)."""
    k = len(messages)
    T = _next_pow2(k * R + 1)
    trace = []
    state = [messages[0] % F.P, alghash.IV]      # entering round 0 of block 0 (absorbed m0 into [0, IV])
    ab = messages[0] % F.P
    midx = 0
    for r in range(T):
        trace.append([state[0], state[1], ab])
        t0 = alghash.sbox(F.add(state[0], alghash.RC[r % R][0]))
        t1 = alghash.sbox(F.add(state[1], alghash.RC[r % R][1]))
        r0 = F.add(F.mul(2, t0), F.mul(1, t1))
        r1 = F.add(F.mul(1, t0), F.mul(3, t1))
        if (r % R == R - 1) and (midx + 1 < k):   # block boundary with a next message -> absorb it
            midx += 1
            ab = messages[midx] % F.P
            state = [F.add(r0, ab), r1]
        else:
            state = [r0, r1]
    return trace, T, k, trace[k * R][S0]          # output = s0 after the last block's permutation


def _periodic(T, k):
    """Public periodic columns for a k-message sponge: rc0/rc1 (round constants, period R) and b — 1 exactly at
    the block boundaries that absorb a next message. Being public and fixed by k, the absorb schedule cannot be
    shifted by the prover; b gates C2/C3."""
    rc0 = [alghash.RC[r % R][0] for r in range(T)]
    rc1 = [alghash.RC[r % R][1] for r in range(T)]
    b = [1 if (r % R == R - 1 and 0 <= r // R < k - 1) else 0 for r in range(T)]
    return [rc0, rc1, b]


def _transitions():
    """The AIR's transition constraints C1–C3 (module docstring): both sponge lanes follow the round function,
    absorption is gated by the public b column, and ab is pinned within a block. Max constraint degree = ALPHA
    (the S-box); trace width stays 3."""
    def _round(cur, per):
        """Recompute one sponge round (round constants → x^ALPHA S-box → MDS) from the current row; C1 and C2
        both bind to this one shared evaluation, so the two lanes cannot diverge from the permutation."""
        t0 = F.pw(F.add(cur[S0], per[0]), alghash.ALPHA)
        t1 = F.pw(F.add(cur[S1], per[1]), alghash.ALPHA)
        return F.add(F.mul(2, t0), F.mul(1, t1)), F.add(F.mul(1, t0), F.mul(3, t1))
    def c1(cur, nxt, per):                          # s1' = r1
        """C1: the capacity lane s1 follows the permutation unconditionally — no message ever enters it."""
        _, r1 = _round(cur, per); return F.sub(nxt[S1], r1)
    def c2(cur, nxt, per):                          # s0' = r0 + b·ab'
        """C2: s0 follows the permutation plus b·ab' — the ONLY point where witness data enters the state."""
        r0, _ = _round(cur, per); return F.sub(nxt[S0], F.add(r0, F.mul(per[2], nxt[AB])))
    def c3(cur, nxt, per):                          # (1-b)(ab' - ab) = 0
        """C3: ab may change only at a block boundary, so each block absorbs one well-defined message."""
        return F.mul(F.sub(1, per[2]), F.sub(nxt[AB], cur[AB]))
    return [c1, c2, c3]


def prove_hash(messages, public_positions, num_queries=stark.NUM_QUERIES):
    """Prove hashn(messages) = output, revealing only the messages at `public_positions` (and the output).
    The other messages are secret (zero-knowledge). Returns (proof, output)."""
    trace, T, k, output = build_trace(messages)
    periodic = _periodic(T, k)
    bnd = [(0, S1, alghash.IV), (k * R, S0, output)]
    for j in public_positions:                      # pin the public messages (e.g. the domain tag at pos 0)
        bnd.append((j * R, AB, messages[j] % F.P))
        if j == 0:
            bnd.append((0, S0, messages[0] % F.P))
    proof = stark.prove(trace, _transitions(), bnd, periodic=periodic, max_degree=MAX_DEGREE, num_queries=num_queries)
    proof["k"] = k
    return proof, output


def verify_hash(proof, public_messages, output):
    """Verify a hashn proof. `public_messages` = {position: value} that must appear at those absorb slots."""
    k = proof["k"]
    T = proof["T"]
    periodic = _periodic(T, k)
    bnd = [(0, S1, alghash.IV), (k * R, S0, output % F.P)]
    for j, m in sorted(public_messages.items()):
        bnd.append((j * R, AB, m % F.P))
        if j == 0:
            bnd.append((0, S0, m % F.P))
    return stark.verify(proof, _transitions(), bnd, periodic=periodic, max_degree=MAX_DEGREE)
