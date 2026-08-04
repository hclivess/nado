"""Reconstructing from the SYSTEMATIC shards must be identical to — and far cheaper than — interpolating.

WHY THIS EXISTS. ops/da.py encodes systematically: shard j < k IS data symbol j. Reconstruction ignored
that and always ran the general Lagrange path, so recovering a blob from shards {0..k-1} multiplied by an
IDENTITY matrix the expensive way: k*k modmuls per stripe, ~70 MILLION for a 118 MiB settle proof, ~55 s
of pure Python.

THAT COST IS A CONSENSUS PROBLEM, not just a slow function. A settle proof rides DA and L1 resolves it
DURING BLOCK VALIDATION (_fetch_da_proof). A node that needs ~55 s to decode cannot validate inside the
block cadence, so it defers; observed live 2026-08-04 the fleet simply never held a proof-carrying block:

    block 23471 built locally WITH the proof settle -> reorged out; canonical 23471 (hash d59dd7f4…,
    identical on all nodes) carries ZERO settle txs, and a BARE settle landed at 23482 instead.

THE PROPERTY UNDER TEST IS EQUALITY, NOT SPEED. Any k shards must recover the same bytes, so the fast path
may only be taken when it provably computes the same thing. The general path stays the oracle here.

Run: python3 tests/test_da_systematic_fastpath.py
"""
import os
import sys
import tempfile
import time

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_dafast_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops import da

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


K, N = 4, 8
rnd = __import__("random").Random(20260804)
data = bytes(rnd.getrandbits(8) for _ in range(200_000))
man = da.encode(data, K, N)
meta = {"k": man["k"], "stripes": man["stripes"], "length": man["length"]}
shards = man["shards"]

# ---- THE FAST PATH MUST BE EXACTLY THE GENERAL PATH ---------------------------------------------------
sys_set = {i: shards[i] for i in range(K)}                  # 0,1,2,3 -> systematic, fast path
par_set = {i: shards[i] for i in (0, 1, 2, 5)}              # includes parity -> general path
alt_set = {i: shards[i] for i in (4, 5, 6, 7)}              # all parity -> general path

out_sys = da.reconstruct(meta, dict(sys_set))
check("systematic shards reconstruct the original bytes exactly", out_sys == data)
check("a parity-containing set reconstructs the same bytes", da.reconstruct(meta, dict(par_set)) == data)
check("an all-parity set reconstructs the same bytes", da.reconstruct(meta, dict(alt_set)) == data)

# ---- SHARD CHOICE MUST NOT DEPEND ON ARRIVAL ORDER ----------------------------------------------------
# `use` was previously idx_list[:k] over dict INSERTION order, so which shards were used depended on the
# order they came back from the network. Sorted selection makes it deterministic AND prefers systematic.
shuffled = {i: shards[i] for i in (3, 0, 2, 1)}
check("shards supplied out of order still reconstruct correctly", da.reconstruct(meta, shuffled) == data)
check("...and reaching the fast path does not depend on arrival order",
      da.reconstruct(meta, shuffled) == out_sys)

# ---- REDUNDANCY CHECKING SURVIVES THE FAST PATH -------------------------------------------------------
# The fast path skips the DECODE matmul, not the extra-shard consistency check. A corrupt extra shard must
# still raise rather than silently yield wrong bytes.
extra_ok = {i: shards[i] for i in range(K + 1)}             # k systematic + one parity witness
check("k systematic + a consistent extra shard still reconstructs", da.reconstruct(meta, extra_ok) == data)

bad = bytearray(shards[K])
bad[0] ^= 0xFF
corrupt = {i: shards[i] for i in range(K)}
corrupt[K] = bytes(bad)
raised = False
try:
    da.reconstruct(meta, corrupt)
except ValueError:
    raised = True
check("a CORRUPT extra shard is still detected on the fast path (not silently ignored)", raised)

# ---- THE BYTE PATH MUST REFUSE WHAT THE SYMBOL PATH REFUSED ------------------------------------------
# _systematic_bytes never forms a field element, so it has to make _unpack's validity check itself: a word
# >= 2**56 is not a data symbol, and silently dropping its high byte would return plausible-looking wrong
# bytes with no error. The high byte of every 8-byte word must therefore be zero.
hi = {i: bytearray(shards[i]) for i in range(K)}
hi[0][0] = 0x01                                    # set the high byte of shard 0's first word
raised_hi = False
try:
    da.reconstruct(meta, {i: bytes(hi[i]) for i in range(K)})
except ValueError:
    raised_hi = True
check("a word out of the 7-byte data range still raises on the byte path", raised_hi)

short = {i: shards[i] for i in range(K)}
short[0] = shards[0][:-8]                          # one word missing
raised_short = False
try:
    da.reconstruct(meta, short)
except ValueError:
    raised_short = True
check("a shard shorter than the manifest's stripe count raises", raised_short)

# and the byte path is genuinely what ran (identical bytes to the interpolating path, checked above)
check("the byte path and the interpolating path agree exactly",
      da.reconstruct(meta, {i: shards[i] for i in range(K)}) == da.reconstruct(meta, dict(par_set)))

# ---- fewer than k is still an error -------------------------------------------------------------------
short = False
try:
    da.reconstruct(meta, {0: shards[0], 1: shards[1]})
except ValueError:
    short = True
check("fewer than k shards still raises", short)

# ---- THE POINT: IT MUST ACTUALLY BE CHEAPER -----------------------------------------------------------
big = bytes(rnd.getrandbits(8) for _ in range(1_200_000))
bman = da.encode(big, K, N)
bmeta = {"k": bman["k"], "stripes": bman["stripes"], "length": bman["length"]}

t0 = time.time()
r_fast = da.reconstruct(bmeta, {i: bman["shards"][i] for i in range(K)})
t_fast = time.time() - t0

t0 = time.time()
r_gen = da.reconstruct(bmeta, {i: bman["shards"][i] for i in (0, 1, 2, 5)})
t_gen = time.time() - t0

check("both paths return the original bytes on a larger blob", r_fast == big and r_gen == big)
mb = len(big) / (1024 * 1024)
print(f"      systematic {t_fast:.3f}s ({t_fast/mb:.3f} s/MiB) · general {t_gen:.3f}s ({t_gen/mb:.3f} s/MiB)"
      f" · speedup {t_gen/max(t_fast,1e-9):.1f}x")
check("the systematic path is materially cheaper than interpolation", t_fast < t_gen)

# ---- the shipped code must actually contain it --------------------------------------------------------
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ops", "da.py")).read()
check("reconstruct prefers systematic shards deterministically", "idx_list = sorted(sym_by_idx)" in src)
check("the systematic set with no extras takes the pure BYTE path (no field elements formed)",
      "if systematic and not extra:" in src and "_systematic_bytes" in src)
check("...built from extended slices, not per-symbol conversions",
      "del ba[0::_WORD]" in src and "out[base + t::step]" in src)
check("reconstruct takes an identity shortcut when they were chosen",
      "systematic = (use == list(range(k)))" in src and "data = ys if systematic else" in src)
check("the Lagrange decode matrix is not even built on the fast path", "if not systematic:" in src)

print()
print("ALL PASS — same bytes, and a peer can now decode a settle proof inside a block"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
