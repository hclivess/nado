"""Watchtower core (dex-bridge phase 4): the pure functions that decide what the tower posts.
Fabricated decode_view storage + a real claim-tx witness scan (built with otc_btc_leg, no bitcoind needed:
extract_secret reads the serialized tx directly). Run: python3 tests/test_otc_watchtower.py"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import otc_watchtower as W                                        # noqa: E402
import otc_btc_leg as B                                           # noqa: E402
from coincurve import PrivateKey                                  # noqa: E402
from execnode.games.otc import preimage_limbs as ref_limbs        # noqa: E402

passed = failed = 0
def ok(c, m):
    global passed, failed
    if c: passed += 1
    else: failed += 1; print("  FAIL:", m)

s = hashlib.sha256(b"tower-secret").hexdigest()
H = hashlib.sha256(bytes.fromhex(s)).hexdigest()
sto = {"mk": {"1": 1, "2": 1, "3": 1, "4": 1, "5": 1},
       "kind": {"1": 1, "2": 2, "3": 3, "4": 1, "5": 2},
       "st":   {"1": 2, "2": 2, "3": 1, "4": 1, "5": 1},           # 1,2 filled · 3,4 open · 5 open
       "esc":  {"1": 9, "2": 9, "3": 9, "4": 9, "5": 0},           # 5 = unfilled BID, nothing to refund
       "expn": {"1": 500, "2": 200, "3": 200, "4": 500, "5": 200},
       "hsha": {"1": H, "2": "zz-not-hex", "3": H, "4": H, "5": H},
       "wch":  {"1": "btc", "2": "btc", "3": "btc", "4": "btc", "5": "btc"},
       "bnty": {"2": 100, "5": 50},                                # 5: an open row that still holds a bounty
       "pheld": {}}
orders = W.parse_orders(sto)
ok(len(orders) == 5, "parse_orders")
ok(W.expire_candidates(orders, 300) == [2, 5, 3], "expire: bounty-bearing first (100, 50, 0); a row holding only a bounty is still worth sweeping")
ok(W.expire_candidates(orders, 100) == [], "expire: nothing before any deadline")
ok(W.watch_candidates(orders, 300) == [(1, H)], "watch: filled HTLC inside the window, well-formed hashlock only")
ok(W.watch_candidates(orders, 600) == [], "watch: nothing past the window (refund territory)")

# a REAL claim tx (built by the leg library) reveals s; the tower's scanner finds it and rebuilds the limbs
alice, bob = PrivateKey(), PrivateKey()
sc = B.htlc_script(bytes.fromhex(H), alice.public_key.format(True), bob.public_key.format(True), 900)
claim = B.claim_tx(sc, bytes.fromhex(s), alice.to_hex(), "aa" * 32, 0, 10_000_000,
                   B.p2wpkh_script(alice.public_key.format(True)))
found = W.scan_txs(["00" * 60, claim], W.watch_candidates(orders, 300))
ok(found == {1: s}, "scan: the claim witness yields the watched order's secret")
ok(W.preimage_limbs(s) == ref_limbs(s), "limbs match the contract module's definition exactly")
ok(W.scan_txs(["00" * 60], [(1, H)]) == {}, "scan: no secret, no relay")

# ---- the Solana scan: a claim carries the preimage in its instruction data (tag 1 + 32 bytes) ------------
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58(b):
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\x00"))) + (out or "1")


ok(W._b58decode(b58(bytes(range(32)))) == bytes(range(32)), "base58 round-trips a 32-byte address")
ok(W._b58decode("11" + b58(b"\x00\x00" + b"z" * 30)[2:]) is not None, "leading zeros survive")

claim_data = b58(bytes([1]) + bytes.fromhex(s))
calls = []


def fake_rpc(url, method, params):
    calls.append((method, params))
    if method == "getSignaturesForAddress":
        return [{"signature": "SIGNEW", "err": None}, {"signature": "SIGOLD", "err": None},
                {"signature": "SIGBAD", "err": {"InstructionError": [0, "Custom"]}}]
    return {"transaction": {"message": {"instructions": [
        {"data": b58(bytes([2]))},                       # a refund carries no preimage
        {"data": claim_data if params[0] == "SIGNEW" else b58(bytes([1]) + b"\x11" * 32)}]}}}


W._sol_rpc, real_rpc = fake_rpc, W._sol_rpc
st = {}
got = W.sol_claim_secrets("http://rpc", "PROG", [(1, H), (7, "ab" * 32)], st)
ok(got == {1: s}, "solana scan: the watched hashlock's preimage is found, an unrelated one is not")
ok(st.get("sol_until") == "SIGNEW", "solana scan: the newest signature is remembered, so the next pass reads only what is new")
calls.clear()
W.sol_claim_secrets("http://rpc", "PROG", [(1, H)], st)
ok(calls[0][1][1].get("until") == "SIGNEW", "solana scan: that cursor is actually sent as `until`")
ok(not any(c[1][0] == "SIGBAD" for c in calls if c[0] == "getTransaction"), "solana scan: a failed transaction is never read")
W._sol_rpc = real_rpc

print(f"\n[tower] {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
