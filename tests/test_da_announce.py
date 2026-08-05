"""DA announce: peers must PREFETCH a settle proof before the tx that references it arrives.

WHY THIS EXISTS. A settle proof is ~118 MiB. Before the announce path, the first time a peer heard of a
commitment was when the settle tx arrived, so the whole transfer + decode + verify (~36 s measured) had to
fit inside validate_transaction's 8 s `_fetch_da_proof` budget. It never did: every peer raised
ProofUnavailable and held ZERO in its pool, so a proof-carrying settle could not be admitted anywhere but
the publisher. Announcing moves the transfer OFF the validation path.

What is pinned here:
  1. announce RETURNS IMMEDIATELY — it must not await the 118 MiB pull, or it just relocates the stall.
  2. it is IDEMPOTENT — every peer announces to every peer, so a re-announce must not start a second pull.
  3. it REFUSES a malformed commitment (the string reaches DaStore._dir).
  4. the in-flight marker is CLEARED on failure, or one failed fetch blocks that commitment forever.
  5. push is NOT a substitute: a k=4 shard of a 118 MiB proof, hex-encoded, exceeds MAX_BODY_BYTES.
"""
import asyncio
import re
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SRC = (ROOT / "execnode" / "execnode.py").read_text()

_fail = []


def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        _fail.append(name)


# ---- 1. the endpoint exists, is wired, and is announced by the publisher ------------------------------
check("h_da_announce is defined", "async def h_da_announce(request):" in SRC)
check("POST /da/announce is routed", 'web.post("/da/announce", h_da_announce)' in SRC)
check("publisher announces right after DA.put", "await da_announce(session, proof_da)" in SRC)

# The announce must happen BEFORE the settle tx is submitted — otherwise peers start pulling only after
# they have already rejected the tx, which is the bug this fixes.
# Anchor on the tx CONSTRUCTION, not on the log text: the string "SETTLE-WITH-DA-PROOF" appears only in
# comments (the log line is assembled from fragments), so matching it either failed outright or pointed
# at a comment ~1500 lines earlier. construct_settle_tx is the unambiguous "the tx now exists" boundary.
_pub = SRC.index("proof PUBLISHED to DA")
_ann = SRC.index("await da_announce(session, proof_da)")
_sub = SRC.index("tx = construct_settle_tx(keys, cur, root, target")
check("announce happens before the settle tx is even built", _pub < _ann < _sub)

# ---- 2. announce must not await the transfer ---------------------------------------------------------
_body = SRC[SRC.index("async def h_da_announce"):SRC.index("async def h_da_get")]
check("the pull is backgrounded, not awaited", "asyncio.create_task(_pull())" in _body)
# da_fetch IS awaited — inside the nested _pull() coroutine, which is the point. What must never happen is
# the HANDLER awaiting it before returning, so check the handler body with the nested function excised.
# (Naively grepping the whole slice for "await da_fetch" fails against correct code: _pull is textually
# inside the handler.)
_outer = _body[:_body.index("    async def _pull():")] + _body[_body.index("    asyncio.create_task"):]
check("the handler itself never awaits da_fetch", "await da_fetch" not in _outer)
check("the handler returns a response, not the blob", "return web.json_response" in _outer)

# ---- 3. guards --------------------------------------------------------------------------------------
check("dedupes on in-flight + already-held", "if DA.have(c) or c in _DA_PREFETCHING:" in _body)
check("rejects path characters in the commitment",
      '"/" in c' in _body and '"\\\\" in c' in _body and 'c in (".", "..")' in _body)
check("bounds the commitment length", "len(c) > 128" in _body)
check("clears the in-flight marker in finally",
      "finally:" in _body and "_DA_PREFETCHING.discard(c)" in _body)

# ---- 4. behavioural: simulate the handler's control flow ---------------------------------------------
# Exercised without aiohttp/network: the invariants above are about ordering and bookkeeping, so drive
# the same logic over a stub and assert the marker lifecycle.
PREFETCHING = set()
pulls = []


async def announce(commitment, have=False, fetch_ok=True):
    """Mirror of h_da_announce's control flow (guards -> dedupe -> background pull -> finally-clear)."""
    if not commitment or len(commitment) > 128 or "/" in commitment or "\\" in commitment \
            or commitment in (".", ".."):
        return {"ok": False}
    if have or commitment in PREFETCHING:
        return {"ok": True, "already": True}
    PREFETCHING.add(commitment)

    async def _pull():
        try:
            await asyncio.sleep(0.05)          # stands in for the 118 MiB transfer
            if not fetch_ok:
                raise RuntimeError("no peer had k shards")
            pulls.append(commitment)
        except Exception:
            pass
        finally:
            PREFETCHING.discard(commitment)

    asyncio.create_task(_pull())
    return {"ok": True, "already": False}


async def main():
    import time
    t0 = time.monotonic()
    r1 = await announce("c" * 64)
    elapsed = time.monotonic() - t0
    check("announce returns before the pull completes (<10 ms)", elapsed < 0.01)
    check("first announce starts a pull", r1 == {"ok": True, "already": False})

    r2 = await announce("c" * 64)
    check("re-announce while in flight does NOT start a second pull", r2.get("already") is True)
    check("exactly one pull in flight", len(PREFETCHING) == 1)

    await asyncio.sleep(0.15)
    check("the pull completed and cached", pulls == ["c" * 64])
    check("marker cleared after success", PREFETCHING == set())

    r3 = await announce("c" * 64, have=True)
    check("announce for an already-held blob is a no-op", r3.get("already") is True)

    # A failed fetch must not wedge that commitment forever.
    await announce("d" * 64, fetch_ok=False)
    await asyncio.sleep(0.15)
    check("marker cleared after FAILURE too", "d" * 64 not in PREFETCHING)
    r4 = await announce("d" * 64)
    check("a failed commitment can be retried", r4 == {"ok": True, "already": False})
    await asyncio.sleep(0.15)

    for bad in ("", "../etc/passwd", "a/b", "a\\b", ".", "..", "x" * 129):
        check(f"rejects malformed commitment {bad[:16]!r}", (await announce(bad))["ok"] is False)


asyncio.run(main())

# ---- 5. why push cannot replace this -----------------------------------------------------------------
# /da/accept carries ONE shard hex-encoded in a body capped at MAX_BODY_BYTES. Confirm the arithmetic
# that rules it out, so nobody "simplifies" announce back into a push.
MAX_BODY = 16 * 1024 * 1024
PROOF = 118.57 * 1024 * 1024
shard_raw = PROOF / 4                      # k = 4
shard_hex = shard_raw * 2                  # /da/accept takes shard.hex()
check("a settle-proof shard does not fit the POST cap (push is impossible)", shard_hex > MAX_BODY)
print(f"      shard {shard_raw/1048576:.1f} MiB raw / {shard_hex/1048576:.1f} MiB hex "
      f"vs {MAX_BODY/1048576:.0f} MiB cap")

print()
if _fail:
    print(f"{len(_fail)} FAILED: " + ", ".join(_fail))
    sys.exit(1)
print("ALL PASS")
