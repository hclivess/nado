"""MessagePool (off-chain messaging, doc/messaging.md) — validation + lifecycle, no chain/crypto needed.

is_registered / verify_sig are injected, so we stub them; PoW is real (we mine a small nonce).
Run: PYTHONPATH=/root/nado python tests/test_message_pool.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops.message_pool import (MessagePool, pow_ok, pow_preimage, message_id,
                              MSG_POW_BITS, MSG_TTL_SECONDS)
from hashing import blake2b_hash

YES = lambda *a: True
NO = lambda *a: False


def mine(env, bits=MSG_POW_BITS):
    """Find a `pow` nonce so the envelope clears the hashcash difficulty."""
    i = 0
    while True:
        env["pow"] = f"{i:x}"
        if pow_ok(env, bits):
            return env
        i += 1


def make_env(sender="ndoAAAA", tag="deadbeef", ct="ciphertext", ts=1000, **over):
    """Build a message envelope with the given overrides and mine its PoW nonce."""
    env = {"v": 1, "sender": sender, "public_key": "PK", "tag": tag, "hdr": "H",
           "nonce": "N", "ct": ct, "ts": ts, "pow": "0", "sig": "SIG"}
    env.update(over)
    return mine(env)


def check(cond, msg):
    """Assert cond, prefixing msg with FAIL for readable output."""
    assert cond, "FAIL: " + msg


def main():
    """Exercise MessagePool end to end: add/dedup/tags, every gate rejection, TTL gc, cap eviction, prekey bundles, PoW."""
    now = 1000

    # --- happy path: valid, registered, signed ---
    p = MessagePool()
    ok, why, mid = p.add_message(make_env(), now, YES, YES)
    check(ok and why == "ok" and mid, "valid message rejected: " + why)
    check(p.get_message(mid) is not None, "get_message miss after add")
    check(p.cursor() == 1, "cursor should be 1")

    # --- dedup: re-adding the same envelope is a benign no-op, no new seq ---
    ok, why, mid2 = p.add_message(p.get_message(mid), now, YES, YES)
    check(ok and why == "duplicate" and mid2 == mid, "dedup broken")
    check(p.cursor() == 1, "duplicate must not advance the cursor")

    # --- tag listing + cursor semantics ---
    _, _, mid_b = p.add_message(make_env(tag="cafe", ct="two"), now, YES, YES)
    tags = p.list_tags(since_seq=0)
    check(len(tags) == 2, f"expected 2 tags, got {len(tags)}")
    check(tags[0]["seq"] < tags[1]["seq"], "tags must be ordered by seq")
    fresh = p.list_tags(since_seq=1)
    check(len(fresh) == 1 and fresh[0]["id"] == mid_b, "since-cursor should return only the newer one")

    # --- gate rejections ---
    for label, kw, reg, sig, want in [
        ("unregistered", {}, NO, YES, "sender not registered"),
        ("bad signature", {}, YES, NO, "bad signature"),
        ("ts future", {"ts": now + 999999}, YES, YES, "ts in the future"),
        ("ts ancient", {"ts": now - MSG_TTL_SECONDS - 10}, YES, YES, "ts too old"),
    ]:
        ok, why, _ = p.add_message(make_env(ct=label, **kw), now, reg, sig)
        check((not ok) and why == want, f"{label}: expected '{want}', got ok={ok} why='{why}'")

    # --- missing field ---
    bad = make_env(ct="nofield"); del bad["sig"]
    ok, why, _ = p.add_message(bad, now, YES, YES)
    check((not ok) and why == "missing field", f"missing-field not caught: {why}")

    # --- too big ---
    ok, why, _ = p.add_message(make_env(ct="x" * 20000), now, YES, YES)
    check((not ok) and why == "too big", f"oversize not caught: {why}")

    # --- insufficient pow (tamper pow after mining) ---
    e = make_env(ct="lowpow"); e["pow"] = "not-a-valid-nonce-zzz"
    while pow_ok(e):                       # ensure it really fails the difficulty
        e["pow"] += "z"
    ok, why, _ = p.add_message(e, now, YES, YES)
    check((not ok) and why == "insufficient pow", f"bad pow not caught: {why}")

    # --- TTL gc ---
    p2 = MessagePool()
    _, _, m = p2.add_message(make_env(ts=now), now, YES, YES)
    check(p2.gc(now + 10) == 0, "nothing should expire immediately")
    check(p2.gc(now + MSG_TTL_SECONDS + 1) == 1, "message past TTL should be reaped")
    check(p2.get_message(m) is None, "reaped message still fetchable")

    # --- size-cap eviction (oldest-first) ---
    p3 = MessagePool(max_count=3)
    ids = [p3.add_message(make_env(ct=f"c{i}", ts=now + i), now + i, YES, YES)[2] for i in range(5)]
    check(len(p3.messages) == 3, f"cap not enforced: {len(p3.messages)}")
    check(p3.get_message(ids[0]) is None and p3.get_message(ids[4]) is not None, "wrong eviction order")

    # --- prekey bundle: add, get, newest-wins, stale-reject ---
    p4 = MessagePool()
    b1 = {"address": "ndoZZ", "public_key": "PK", "ik_pub": "IK", "spk_pub": "S1",
          "spk_ts": 100, "ts": 100, "sig": "SIG"}
    b2 = dict(b1, spk_pub="S2", spk_ts=200)
    b0 = dict(b1, spk_pub="S0", spk_ts=50)
    check(p4.add_prekey(b1, YES, YES)[0], "prekey add failed")
    check(p4.get_prekey("ndoZZ")["spk_pub"] == "S1", "prekey get wrong")
    check(p4.add_prekey(b2, YES, YES)[0] and p4.get_prekey("ndoZZ")["spk_pub"] == "S2", "newest should win")
    p4.add_prekey(b0, YES, YES)
    check(p4.get_prekey("ndoZZ")["spk_pub"] == "S2", "stale bundle must not overwrite newer")
    check(p4.add_prekey(b1, NO, YES) == (False, "not registered"), "unregistered prekey must be rejected")

    # --- pow_ok sanity: a mined nonce clears it, a hash with < bits leading zeros does not ---
    check(pow_ok(make_env()), "mined env should pass pow")

    print("ALL MESSAGE-POOL CHECKS PASSED")


if __name__ == "__main__":
    main()
