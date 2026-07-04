"""
Message-pool persistence: the off-chain E2E message pool is otherwise in-memory, so a plain node RESTART
silently dropped every undelivered DM + published prekey. save()/load() round-trip it across restarts and
reap TTL-expired messages on load.

Run: python3 tests/test_message_pool_persist.py
"""
import os, sys, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops.message_pool import MessagePool

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e: fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

path = os.path.join(tempfile.mkdtemp(), "message_pool.dat")


def _seed():
    p = MessagePool()
    p._seq = 5
    p.messages = {"mid1": {"env": {"v": 1, "sender": "ndoX", "tag": "aa", "ct": "ff", "ts": 123}, "recv": 123, "seq": 5}}
    p.prekeys = {"ndoY": {"bundle": {"address": "ndoY", "ik_pub": "beef"}, "ts": 100}}
    return p


def t1_round_trip():
    _seed().save(path)
    q = MessagePool()
    kept = q.load(path, now=200)                 # within TTL
    assert kept == 1, "message not restored"
    assert q.get_prekey("ndoY")["ik_pub"] == "beef", "prekey not restored"
    assert q._seq == 5, "cursor not restored"
    assert q.list_tags(since_seq=0)[0]["tag"] == "aa", "restored message not listable by tag"
check("save -> load restores messages + prekeys + cursor", t1_round_trip)


def t2_ttl_reaped_on_load():
    _seed().save(path)
    q = MessagePool()
    kept = q.load(path, now=123 + q.ttl + 1000)  # well past the 7-day TTL
    assert kept == 0, "TTL-expired message was not reaped on load"
    assert q.get_prekey("ndoY") is not None, "prekeys are directory state, not TTL'd"
check("load reaps TTL-expired messages (prekeys kept)", t2_ttl_reaped_on_load)


def t3_missing_and_corrupt_are_safe():
    q = MessagePool()
    assert q.load(os.path.join(tempfile.mkdtemp(), "nope.dat"), now=1) == 0, "missing file must be a no-op"
    bad = os.path.join(tempfile.mkdtemp(), "bad.dat")
    open(bad, "wb").write(b"\xff\x00not-msgpack")
    assert q.load(bad, now=1) == 0, "corrupt file must not raise / must leave an empty pool"
check("missing / corrupt pool file is a safe no-op", t3_missing_and_corrupt_are_safe)


print(f"\n{'ALL PASSED' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
