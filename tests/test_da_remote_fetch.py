"""A node with NO local DA store must still resolve a DA-carried settle proof — trustlessly, or not at all.

WHY THIS EXISTS. Settlement proofs are ~118 MiB, far past any tx cap, so the tx carries only a commitment
and L1 resolves the bytes DURING block validation. _fetch_da_proof asked ONLY http://127.0.0.1:9273, and
this fleet runs L1 with no exec node anywhere except the publisher — measured live 2026-08-04:

    185.184.192.210:9273 -> http=000 (no listener); the only :9273 that answers is the publisher itself.

So every peer failed to resolve, could not validate a block carrying the settle, and the block lost every
reorg: block 23471 was built locally WITH a proof settle and reorged out, and canonical 23471 (d59dd7f4…,
byte-identical on all four nodes) carries ZERO settle txs.

THE FALLBACK MUST NOT BUY AVAILABILITY WITH SAFETY. Two rules are under test:

  1. Bytes from a remote are authenticated against the ON-CHAIN commitment via the shard path
     (/da/meta + /da/shard + verify_sample), NEVER via raw /da/get. Unauthenticated bytes that merely fail
     to PARSE reach the reject branch — "retrievable but not a proof: that IS a judgement we can make" — so
     a hostile DA server could make an honest block be REJECTED. That is a fork along the axis of who
     served what.
  2. Every failure returns None, which means UNRESOLVED (the caller defers). None of these paths may raise
     or return wrong bytes.

A lied manifest is the sharp case: (k, n, stripes, length) STEER the decode — a shorter `length` truncates
to different bytes that still pass a shard-only check — so the manifest is bound into every leaf and is
rejected by the same proof that authenticates the shard.

Run: python3 tests/test_da_remote_fetch.py
"""
import json
import os
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_darf_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops import da
from ops import transaction_ops as TO
from ops import peer_ops as PO

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


BLOB = json.dumps({"cursor": 23323, "openings": list(range(400))}).encode()
MAN = da.encode(BLOB, 4, 8)
COMMIT = MAN["commitment"]
META = {kk: MAN[kk] for kk in ("commitment", "k", "n", "stripes", "length")}

MODE = {"how": "honest"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/da/get":
            self._send(404, {"error": "no"})      # must never be used by the trustless path
            return
        if u.path == "/da/meta":
            m = dict(META)
            if MODE["how"] == "lied_manifest":
                m["length"] = m["length"] - 1     # steers the decode to different bytes
            self._send(200, m)
            return
        if u.path == "/da/shard":
            i = int(q.get("i", ["0"])[0])
            sp = da.sample_proof(MAN, i)
            shard = sp["shard"]
            if MODE["how"] == "garbage_shards":
                shard = bytes(len(shard))         # right length, wrong bytes
            self._send(200, {"index": i, "shard": shard.hex(), "proof": sp["proof"]})
            return
        self._send(404, {"error": "no"})


s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()
srv = HTTPServer(("127.0.0.1", PORT), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()

# Point the fetch at the stand-in server, and make "the peer set" be exactly it. The real exec node owns
# 9273 on a live box, so the port must be redirected rather than assumed free.
TO.DA_PORT = PORT
PO.seed_peers = lambda: ["127.0.0.1"]
PO.known_peer_ips = lambda: []

# ---- 1. THE HONEST CASE: a node with no local DA store still resolves the proof -----------------------
got = TO._fetch_da_proof(COMMIT, timeout=20)
check("a node with NO local DA store resolves the proof from a remote DA node", got == BLOB)

# ---- 2. A LIED MANIFEST IS REJECTED, AND AS 'UNRESOLVED' ----------------------------------------------
MODE["how"] = "lied_manifest"
got = TO._fetch_da_proof(COMMIT, timeout=20)
check("a lied manifest does not resolve", got != BLOB)
check("...and it DEFERS (None), it does not return wrong bytes", got is None)

# ---- 3. GARBAGE SHARDS ARE REJECTED, AND AS 'UNRESOLVED' ----------------------------------------------
MODE["how"] = "garbage_shards"
got = TO._fetch_da_proof(COMMIT, timeout=20)
check("shards that do not hash into the commitment do not resolve", got is None)

# ---- 4. AN UNKNOWN COMMITMENT DEFERS ------------------------------------------------------------------
MODE["how"] = "honest"
check("an unknown commitment defers rather than raising",
      TO._fetch_da_proof("00" * 32, timeout=8) is None)

# ---- 5. NO SOURCES AT ALL STILL DEFERS ----------------------------------------------------------------
PO.seed_peers = lambda: []
check("no reachable DA source defers rather than raising", TO._fetch_da_proof(COMMIT, timeout=5) is None)
PO.seed_peers = lambda: ["127.0.0.1"]

# ---- the shipped code must take the trustless path, not /da/get --------------------------------------
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "ops", "transaction_ops.py")).read()
check("the remote path uses /da/meta + /da/shard", "/da/meta?c=" in src and "/da/shard?c=" in src)
check("...and reconstructs through reconstruct_from, which verifies every shard",
      "_rf(_meta, _pairs)" in src)
check("...pinning the commitment we asked for rather than the peer's claim",
      'dict(_meta, commitment=str(commitment))' in src)
check("the whole attempt is bounded by ONE deadline",
      "_deadline = _t.time() + timeout" in src)
check("remote /da/get is NOT used for resolution",
      src.count("/da/get?c=") == 1 and "127.0.0.1:{DA_PORT}/da/get" in src)

srv.shutdown()
print()
print("ALL PASS — a peer with no DA store resolves proofs trustlessly, and every failure is a DEFER"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
