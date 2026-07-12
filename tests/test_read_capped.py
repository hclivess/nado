"""
read_capped must read the WHOLE body up to the cap. aiohttp's StreamReader.read(n) returns at most n bytes
and usually FEWER (one TCP segment), so a single .read(cap+1) truncated any multi-segment body — an 867 KB
snapshot chunk came back as its 32 KB first segment and failed the import sha256 check. This simulates
segmentation and proves read_capped now reassembles the full body (and still enforces the cap).

Also covers bounded_zstd_decompress: the ?compress=zstd peer wire's anti-bomb primitive. The one-shot
ZstdDecompressor(max_output_size=cap) IGNORES the cap when the frame declares its content size (nado's
compressor does), allocating the declared size up front — a tiny frame declaring gigabytes would OOM the
node. The streaming decompressor must abort past the cap regardless of the declared size.

Run: python3 tests/test_read_capped.py
"""
import os, sys, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import zstandard
from ops import codec
from ops.net_ops import read_capped, bounded_zstd_decompress, unpack_zstd_peer

class _Segmented:
    """Mimics aiohttp StreamReader: read(n) yields at most `seg` bytes at a time (one 'TCP segment')."""
    def __init__(self, data, seg):
        """Hold `data` to be served in segments of at most `seg` bytes."""
        self._d = data; self._p = 0; self._seg = seg
    async def read(self, n):
        """Return the next chunk: at most min(n, seg) bytes, like one TCP segment; b'' at EOF."""
        take = min(n, self._seg, len(self._d) - self._p)
        out = self._d[self._p:self._p + take]; self._p += take
        return out

class _Resp:
    def __init__(self, data, seg):
        """Fake aiohttp response whose .content is a _Segmented reader over `data`."""
        self.content = _Segmented(data, seg)

fails = 0
def check(name, cond):
    """Print PASS/FAIL for cond and count failures."""
    global fails
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond: fails += 1

async def main():
    """Prove read_capped reassembles multi-segment bodies, accepts exactly-at-cap, raises IOError over cap, and handles empty."""
    # the real failure: 867411-byte body delivered in 32585-byte segments must NOT truncate
    big = os.urandom(867411)
    got = await read_capped(_Resp(big, seg=32585), len(big))
    check("multi-segment body is fully reassembled (was truncated to the first segment)", got == big)

    # a body exactly at the cap is accepted
    exact = os.urandom(500)
    check("body exactly at cap accepted", await read_capped(_Resp(exact, seg=100), 500) == exact)

    # a body over the cap raises (anti-OOM) even across segments
    raised = False
    try:
        await read_capped(_Resp(os.urandom(1000), seg=100), 999)
    except IOError:
        raised = True
    check("over-cap body raises IOError", raised)

    # empty body
    check("empty body returns b''", await read_capped(_Resp(b"", seg=100), 100) == b"")

    # --- bounded_zstd_decompress: anti-bomb for the ?compress=zstd wire ---
    # a legit small zstd(codec) payload round-trips
    payload = {"a": 1, "b": [1, 2, 3], "s": "x" * 1000}
    frame = zstandard.ZstdCompressor(level=3).compress(codec.pack(payload))
    check("legit zstd(codec) round-trips", unpack_zstd_peer(frame) == payload)

    # THE BOMB: a frame declaring a large content size (here 64 MiB of zeros -> tiny frame) must be
    # refused by a smaller cap, EVEN THOUGH the one-shot max_output_size arg would honor the declaration.
    bomb = zstandard.ZstdCompressor(level=3).compress(b"\0" * (64 << 20))
    check("declared-content-size frame IS declared (else this test is vacuous)",
          zstandard.get_frame_parameters(bomb).content_size == (64 << 20))
    raised = False
    try:
        bounded_zstd_decompress(bomb, 8 << 20)
    except IOError:
        raised = True
    check("declared-size zstd bomb raises IOError past cap (streaming, not one-shot)", raised)

    # a frame exactly at the cap is accepted
    exact = zstandard.ZstdCompressor(level=3).compress(b"z" * 4096)
    check("zstd output exactly at cap accepted", bounded_zstd_decompress(exact, 4096) == b"z" * 4096)

asyncio.run(main())
print(f"\n{'ALL READ_CAPPED CHECKS PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
