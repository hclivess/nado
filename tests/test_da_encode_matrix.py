"""
The DA encode must stay BIT-IDENTICAL while getting ~1000x faster.

WHY THIS EXISTS. A settlement proof is ~118 MiB and cannot ride on chain (8 MiB submit cap), so it is
published k-of-n to DA and the settle tx carries only the commitment. That is the entire trustless-
settlement transport. It had never once completed.

Measured 2026-08-04: ops.da.encode runs at ~15 s/MiB.

    0.25 MiB -> 5.13s      1.00 MiB -> 15.08s
    extrapolated 118 MiB -> ~1779 s  (~30 minutes)

So when a proof finally passed its self-checks —

    13:35:11 [execnode] settle-with-proof BUILT ns=default span 19507->19537 — self-checks passed

— nothing followed it, because DA.put was erasure-coding for half an hour.

THE CAUSE was not the language. _encode_stripe called _lagrange_eval, which calls _inv(a) = pow(a, P-2, P)
— a full modular exponentiation — in its innermost loop, once per (output point, term), for EVERY stripe:
n·k = 32 modexps per stripe, ~4.4M stripes for a 118 MiB blob, ~141 MILLION modexps.

But the encode's interpolation points are FIXED — data at x = 1..k, shards read at x = 1..n — so the
Lagrange basis coefficients are CONSTANTS. The whole encode is one fixed n×k matrix multiply that was
being re-derived per stripe.

THIS TEST IS THE SAFETY PROPERTY. Erasure coding is consensus-visible: the commitment goes in a settle tx
and peers reconstruct from the shards. If the hoist changed even one symbol, every published blob would
fail to verify. So the new path is checked against the ORIGINAL implementation, reproduced here verbatim,
over random data and every (k, n) the node uses.

Run: python3 tests/test_da_encode_matrix.py
"""
import os
import random
import sys
import tempfile
import time

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_daenc_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


from ops import da  # noqa: E402

P = da.P


# ---- the ORIGINAL implementation, verbatim, as the oracle ------------------------------------------
def _inv_ref(a):
    return pow(a % P, P - 2, P)


def _lagrange_eval_ref(points, x):
    x %= P
    total = 0
    for i, (xi, yi) in enumerate(points):
        num = den = 1
        for j, (xj, _) in enumerate(points):
            if i == j:
                continue
            num = num * ((x - xj) % P) % P
            den = den * ((xi - xj) % P) % P
        total = (total + yi % P * num % P * _inv_ref(den)) % P
    return total


def _encode_stripe_ref(data_syms, n):
    pts = [(i + 1, data_syms[i] % P) for i in range(len(data_syms))]
    return [_lagrange_eval_ref(pts, x) for x in range(1, n + 1)]


# ---- BIT-IDENTITY on the stripe primitive -----------------------------------------------------------
rnd = random.Random(20260804)
same = True
for (k, n) in [(4, 8), (2, 4), (3, 6), (1, 2), (8, 16), (5, 7)]:
    for _ in range(200):
        syms = [rnd.randrange(P) for _ in range(k)]
        if _encode_stripe_ref(syms, n) != da._encode_stripe(syms, n):
            same = False
            break
check("_encode_stripe is bit-identical to the original across every (k,n) and random symbols", same)

# edge symbols, where a modular slip would show
edge = True
for (k, n) in [(4, 8), (3, 5)]:
    for syms in ([0] * k, [P - 1] * k, [1] * k, list(range(k))):
        if _encode_stripe_ref(syms, n) != da._encode_stripe(syms, n):
            edge = False
check("...including 0, 1, P-1 and small-integer symbol vectors", edge)

# ---- BIT-IDENTITY end to end: commitment and shards -------------------------------------------------
def encode_ref(data, k, n):
    syms, length = da._pack(data)
    while len(syms) % k:
        syms.append(0)
    stripes = len(syms) // k
    shard_syms = [[] for _ in range(n)]
    for s in range(stripes):
        enc = _encode_stripe_ref(syms[s * k:(s + 1) * k], n)
        for j in range(n):
            shard_syms[j].append(enc[j])
    shards = [da._shard_bytes(ss) for ss in shard_syms]
    from hashing import merkle_root
    leaves = [da._leaf(j, shards[j]) for j in range(n)]
    return {"commitment": merkle_root(leaves), "k": k, "n": n, "stripes": stripes,
            "length": length, "shards": shards}


blob = os.urandom(200 * 1024)
ref = encode_ref(blob, 4, 8)
new = da.encode(blob, 4, 8)
check("the COMMITMENT is unchanged (published blobs stay verifiable)",
      ref["commitment"] == new["commitment"])
check("every shard is byte-identical", ref["shards"] == new["shards"])
check("stripes/length/k/n unchanged",
      (ref["stripes"], ref["length"], ref["k"], ref["n"]) ==
      (new["stripes"], new["length"], new["k"], new["n"]))

# ---- it still round-trips through the real decode path ----------------------------------------------
meta = {"k": new["k"], "stripes": new["stripes"], "length": new["length"]}
for pick in ([0, 1, 2, 3], [4, 5, 6, 7], [0, 2, 5, 7]):
    got = da.reconstruct(meta, {i: new["shards"][i] for i in pick})
    if got != blob:
        check(f"round-trip from shards {pick}", False)
        break
else:
    check("reconstructs from ANY k shards (systematic and parity-only sets)", True)

# ---- sample proofs still verify against the commitment ----------------------------------------------
ok_samples = True
for i in range(new["n"]):
    sp = da.sample_proof(new, i)
    if not da.verify_sample(new["commitment"], i, sp["shard"], sp["proof"]):
        ok_samples = False
check("every shard's sample proof verifies against the commitment", ok_samples)

# ---- THE POINT: it must actually be fast now --------------------------------------------------------
mib = 1.0
data = os.urandom(int(mib * 1024 * 1024))
t = time.time()
da.encode(data, 4, 8)
sec_per_mib = (time.time() - t) / mib
print(f"    encode throughput: {sec_per_mib:.3f} s/MiB "
      f"(was ~15.1 s/MiB; 118 MiB: {118*sec_per_mib:.0f}s vs ~1779s)")
check("encode is at least 20x faster than the 15.1 s/MiB baseline", sec_per_mib < 15.1 / 20)
check("a 118 MiB proof now encodes in under 3 minutes", 118 * sec_per_mib < 180)

# ---- the matrix is genuinely cached, not rebuilt per stripe -----------------------------------------
da._ENC_MATRIX_CACHE.clear()
da._enc_matrix(4, 8)
n_after = len(da._ENC_MATRIX_CACHE)
da._enc_matrix(4, 8)
check("the generator matrix is cached per (k,n)", len(da._ENC_MATRIX_CACHE) == n_after == 1)

print()
print("ALL PASS — same bytes, same commitment, ~1000x less work"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
