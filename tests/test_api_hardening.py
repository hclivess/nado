"""
API hardening (ops/net_ops.py + nado.py wiring):
  1. client_ip_from — X-Forwarded-For is trusted ONLY behind a configured proxy (no rate-limit/Sybil spoofing)
  2. force_sync target validation — check_ip rejects non-routable/internal forced_ip (SSRF)
  3. unpack_tx — size-bounded msgpack/JSON decode (oversized body + collection-bomb rejected)

Run: python3 tests/test_api_hardening.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import msgpack
from ops.net_ops import client_ip_from, unpack_tx, MAX_TX_BODY

fails = 0
def check(name, fn):
    global fails
    try: fn(); print("PASS  " + name)
    except Exception as e:
        fails += 1; print("FAIL  " + name + ": " + str(e)); traceback.print_exc()

# ---- 1. client_ip_from (trusted-proxy XFF) --------------------------------------------------------
def t1_untrusted_peer_ignores_xff():
    # the anti-spoof property: a direct client sending a forged XFF is NOT believed
    assert client_ip_from("9.9.9.9", "1.2.3.4", frozenset()) == "9.9.9.9"          # no trusted set
    assert client_ip_from("9.9.9.9", "1.2.3.4", frozenset({"10.0.0.1"})) == "9.9.9.9"  # peer not the proxy

def t1_trusted_proxy_uses_xff():
    trusted = frozenset({"10.0.0.1"})
    assert client_ip_from("10.0.0.1", "1.2.3.4", trusted) == "1.2.3.4"
    assert client_ip_from("10.0.0.1", "", trusted) == "10.0.0.1"                    # no XFF -> the peer

def t1_walks_past_chained_proxies():
    trusted = frozenset({"10.0.0.1", "10.0.0.2"})
    # client, then two trusted proxy hops appended on the right -> real client is the leftmost untrusted
    assert client_ip_from("10.0.0.2", "1.2.3.4, 10.0.0.1, 10.0.0.2", trusted) == "1.2.3.4"
    # all hops trusted (spoofed) -> fall back to the peer, never a trusted IP
    assert client_ip_from("10.0.0.1", "10.0.0.1, 10.0.0.2", trusted) == "10.0.0.1"

# ---- 3. unpack_tx (size-bounded decode) -----------------------------------------------------------
def t3_legit_tx_roundtrips_both_encodings():
    tx = {"sender": "ndo" + "a" * 46, "recipient": "register", "amount": 0, "fee": 0,
          "target_block": 100, "posw": {"segments": list(range(200)), "openings": ["ab" * 32] * 20}}
    assert unpack_tx(msgpack.packb(tx), "application/msgpack") == tx
    import json
    assert unpack_tx(json.dumps(tx).encode(), "application/json") == tx

def t3_oversized_body_rejected():
    big = b"\xa0" + b"x" * (MAX_TX_BODY + 10)     # > 1 MiB
    try:
        unpack_tx(big, "application/msgpack"); raise SystemExit("should have raised")
    except SystemExit: raise
    except Exception: pass

def t3_collection_bomb_rejected():
    # a small-BYTES msgpack (~200 KB, under the body cap) that declares 200k array elements -> max_array_len
    bomb = msgpack.packb([0] * 200_000)
    assert len(bomb) < MAX_TX_BODY, "bomb must be under the body cap so we test max_array_len, not the length"
    try:
        unpack_tx(bomb, "application/msgpack"); raise SystemExit("should have raised")
    except SystemExit: raise
    except Exception: pass

def t3_empty_body_rejected():
    try:
        unpack_tx(None, "application/msgpack"); raise SystemExit("should have raised")
    except SystemExit: raise
    except Exception: pass

# ---- 2. force_sync target validation (the guard force_sync now applies) ----------------------------
def t2_check_ip_rejects_ssrf_targets():
    os.environ.pop("NADO_TESTNET", None)              # mainnet semantics for this assertion
    from ops import peer_ops
    peer_ops.get_config = lambda: {"ip": "203.0.113.99"}   # stub: don't need a real config/home
    ci = peer_ops.check_ip
    for bad in ("169.254.169.254", "10.0.0.5", "127.0.0.1", "192.168.1.1", "not-an-ip", ""):
        assert ci(bad) is False, bad + " must be rejected as a force-sync target"
    assert ci("8.8.8.8") is True, "a global routable IP must be accepted"

for n, f in sorted((n, f) for n, f in list(globals().items()) if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(n, f)
print("\n" + ("ALL PASSED" if not fails else str(fails) + " FAILED"))
sys.exit(1 if fails else 0)
