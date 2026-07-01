"""
IP-diversity registration cap (ops/ratelimit.allow_registration): a source IP may onboard at most
`max_addrs` DISTINCT OPEN-lane addresses per window; already-seen addresses are always allowed; the
cap is per-IP and disable-able. Non-consensus relay admission control (anti-Sybil at the entry point).

Run: python3 tests/test_ip_registration_cap.py
"""
import os, sys, traceback, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops.ratelimit import allow_registration

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def t1_distinct_cap_per_ip():
    ip = "10.0.0.1"
    for i in range(5):
        assert allow_registration(ip, f"addr{i}", max_addrs=5), f"addr{i} within cap should pass"
    assert not allow_registration(ip, "addr5", max_addrs=5), "6th distinct address must be rejected"

def t2_known_address_always_allowed():
    ip = "10.0.0.2"
    assert allow_registration(ip, "a", max_addrs=1)
    assert not allow_registration(ip, "b", max_addrs=1), "2nd distinct rejected at cap 1"
    # re-submitting an ALREADY-seen address never counts against the cap (retries/heartbeats)
    assert allow_registration(ip, "a", max_addrs=1), "known address must always pass"
    assert allow_registration(ip, "a", max_addrs=1)

def t3_per_ip_isolation():
    assert allow_registration("10.0.0.3", "x", max_addrs=1)
    assert not allow_registration("10.0.0.3", "y", max_addrs=1)
    assert allow_registration("10.0.0.4", "y", max_addrs=1), "a different IP has its own budget"

def t4_zero_disables():
    ip = "10.0.0.5"
    for i in range(1000):
        assert allow_registration(ip, f"z{i}", max_addrs=0), "cap 0 disables the limit"

def t5_window_expiry():
    ip = "10.0.0.6"
    assert allow_registration(ip, "old", max_addrs=1, window=0.05)
    assert not allow_registration(ip, "new", max_addrs=1, window=0.05), "still within window"
    time.sleep(0.06)
    assert allow_registration(ip, "new", max_addrs=1, window=0.05), "prior entry expired -> slot frees"

for name, fn in list(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)

print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
