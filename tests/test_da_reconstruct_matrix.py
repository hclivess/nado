"""
DA reconstruct must stay BIT-IDENTICAL while getting fast enough not to freeze the node.

WHY THIS EXISTS. 08945e50 hoisted the loop-invariant Lagrange basis out of the ENCODE path (15.08 ->
0.428 s/MiB, 35x). The DECODE path had the identical flaw and was left alone — and it is the one that
actually took the node down.

`reconstruct` rebuilt the basis for EVERY stripe, calling _inv(a) = pow(a, P-2, P) — a full modular
exponentiation — k*k times per stripe. For a 118 MiB blob: ~4.4M stripes x 16 = ~70 MILLION modexps. But
the basis depends only on the x-coordinates, and in a reconstruct those are the CHOSEN SHARD INDICES,
identical for every stripe. Only the y-values change.

OBSERVED LIVE 2026-08-04, twice. h_da_get called DaStore.get -> reconstruct SYNCHRONOUSLY on the event
loop, so one /da/get for a settle proof froze the exec node outright: HTTP dead, no log output, block
application stopped, RSS ~2 GB, until it was restarted. py-spy caught it mid-wedge:

    _inv (ops/da.py:30)
    _lagrange_eval (ops/da.py:44)
    reconstruct (ops/da.py:176)
    get (ops/da_store.py:121)
    h_da_get (execnode/execnode.py:1348)

Both wedges had been attributed to the PUBLISH path. They were the decode, triggered by fetching the blob
back. The publish fix (45b0b524) was independently right — the double serialization was real waste — but
it was not what was freezing the node.

TWO CHANGES: the basis is hoisted here, and h_da_get now runs the decode in a thread. The second matters
on its own — /da/get is reachable by any peer, so a decode on the event loop is a trivial remote DoS
regardless of how fast the arithmetic gets.

Erasure decoding is consensus-visible (a settle proof is reconstructed from it and verified against a
commitment), so the new path is checked against the ORIGINAL implementation, reproduced verbatim.

Run: python3 tests/test_da_reconstruct_matrix.py
"""
import os
import sys
import tempfile
import time

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_dadec_")
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


# ---- the ORIGINAL decode, verbatim, as the oracle ---------------------------------------------------
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


def reconstruct_ref(meta, known_shards, verify=True):
    k = meta["k"]; stripes = meta["stripes"]; length = meta["length"]
    sym_by_idx = {idx: da._shard_syms(b) for idx, b in known_shards.items()}
    idx_list = list(sym_by_idx)
    use, extra = idx_list[:k], (idx_list[k:] if verify else [])
    out = []
    for s in range(stripes):
        pts = [(idx + 1, sym_by_idx[idx][s] % P) for idx in use]
        data = [_lagrange_eval_ref(pts, x) for x in range(1, k + 1)]
        if extra:
            dpts = [(i + 1, data[i]) for i in range(k)]
            for idx in extra:
                if _lagrange_eval_ref(dpts, idx + 1) != sym_by_idx[idx][s] % P:
                    raise ValueError("inconsistent")
        out.extend(data)
    return da._unpack(out, length)


# ---- BIT-IDENTITY across shard subsets and (k,n) ------------------------------------------------------
same = True
for (k, n) in [(4, 8), (2, 4), (3, 6), (5, 7)]:
    blob = os.urandom(40 * 1024)
    m = da.encode(blob, k, n)
    meta = {"k": k, "stripes": m["stripes"], "length": m["length"]}
    subsets = [list(range(k)), list(range(n - k, n)), [0] + list(range(n - k + 1, n))]
    for pick in subsets:
        ks = {i: m["shards"][i] for i in pick}
        if reconstruct_ref(meta, dict(ks)) != da.reconstruct(meta, dict(ks)):
            same = False
check("reconstruct is bit-identical to the original across (k,n) and shard subsets", same)

# ---- systematic and parity-only sets both round-trip to the ORIGINAL bytes ----------------------------
blob = os.urandom(200 * 1024)
m = da.encode(blob, 4, 8)
meta = {"k": 4, "stripes": m["stripes"], "length": m["length"]}
ok = True
for pick in ([0, 1, 2, 3], [4, 5, 6, 7], [0, 2, 5, 7], [1, 3, 4, 6]):
    if da.reconstruct(meta, {i: m["shards"][i] for i in pick}) != blob:
        ok = False
check("round-trips to the original bytes from ANY k shards", ok)

# ---- the redundancy check still DETECTS a corrupt shard ----------------------------------------------
bad = bytearray(m["shards"][5])
bad[16] ^= 0xFF
caught = False
try:
    da.reconstruct(meta, {0: m["shards"][0], 1: m["shards"][1], 2: m["shards"][2],
                          3: m["shards"][3], 5: bytes(bad)})
except ValueError:
    caught = True
check("a corrupt EXTRA shard is still detected (redundancy check intact)", caught)

check("verify=False skips the extra-shard check, as before",
      da.reconstruct(meta, {0: m["shards"][0], 1: m["shards"][1], 2: m["shards"][2],
                            3: m["shards"][3], 5: bytes(bad)}, verify=False) == blob)

# ---- THE POINT: fast enough that a 118 MiB proof cannot freeze a node ---------------------------------
big = os.urandom(1024 * 1024)
mb = da.encode(big, 4, 8)
metab = {"k": 4, "stripes": mb["stripes"], "length": mb["length"]}
t = time.time()
da.reconstruct(metab, {i: mb["shards"][i] for i in range(4)})
sec_per_mib = time.time() - t
print(f"    decode throughput: {sec_per_mib:.3f} s/MiB  (118 MiB: {118*sec_per_mib:.0f}s)")
check("decode is under 1 s/MiB", sec_per_mib < 1.0)
check("a 118 MiB proof decodes in under 2 minutes", 118 * sec_per_mib < 120)

# ---- and the handler must not run it on the event loop -----------------------------------------------
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "execnode", "execnode.py")).read()
check("h_da_get runs the decode in a thread, not on the event loop",
      "await asyncio.to_thread(DA.get," in src)

print()
print("ALL PASS — same bytes, and a /da/get can no longer freeze the node"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
