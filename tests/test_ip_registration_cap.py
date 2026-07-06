"""
PROGRESSIVE IP-diversity registration cap (ops/ratelimit.allow_registration): an address's crowding
cost scales with how close its IP is to other recently-registered IPs — same EXACT IP costs the most,
each broader shared prefix (/24, /16, /8) costs half as much, an unrelated network costs nothing. So a
datacenter's /24 gets a bounded shared budget while genuinely distinct networks aren't penalised.
Non-consensus relay admission control (anti-Sybil at the entry point).

Run: python3 tests/test_ip_registration_cap.py
"""
import os, sys, traceback, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import ratelimit
from ops.ratelimit import allow_registration

# fresh state so import-time residue can't contaminate; each test uses its own /8 to stay independent.
for lvl in ratelimit._reg_levels:
    lvl.clear()

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def t1_same_exact_ip_hard_cap():
    """Prove max_addrs distinct addresses pass from one exact IP and the next is rejected."""
    ip = "11.0.0.1"                                  # /8 = 11 (unique to this test)
    for i in range(5):
        assert allow_registration(ip, f"a{i}", max_addrs=5), f"a{i} within cap should pass"
    assert not allow_registration(ip, "a5", max_addrs=5), "6th distinct from the exact IP is rejected"

def t2_known_address_always_allowed():
    """Prove an already-seen address always passes (retry/heartbeat) even when the IP is at its cap."""
    ip = "12.0.0.1"
    assert allow_registration(ip, "a", max_addrs=1)
    assert not allow_registration(ip, "b", max_addrs=1), "2nd distinct from exact IP rejected at cap 1"
    assert allow_registration(ip, "a", max_addrs=1), "already-seen address always passes (retry/heartbeat)"

def t3_same_24_costs_half_progressive():
    """Prove distinct /32s in one /24 cost half each, giving ~2x the exact-IP budget before the range caps."""
    # distinct /32s inside ONE /24 each cost 0.5 -> ~2x the exact-IP budget before the range is capped.
    cap = 2                                          # exact-IP budget 2 -> ~4 distinct /32 in a /24
    for k in range(1, 5):                            # 13.0.0.1 .. 13.0.0.4 (4 distinct /32, same /24)
        assert allow_registration(f"13.0.0.{k}", f"h{k}", max_addrs=cap), f"13.0.0.{k} should fit (~2x)"
    assert not allow_registration("13.0.0.5", "h5", max_addrs=cap), "5th distinct /32 in the /24 is capped"

def t4_different_8_no_crowding():
    """Prove IPs in different /8s share no prefix, incur zero crowding, and always pass even at cap 1."""
    # genuinely distinct networks (different /8) share no prefix -> zero crowding -> never penalise.
    for oct1 in (21, 22, 23, 24, 25):
        assert allow_registration(f"{oct1}.0.0.1", f"u{oct1}", max_addrs=1), \
            f"{oct1}.0.0.1 in its own /8 must pass even at cap 1"

def t5_same_16_looser_than_exact():
    """Prove a same-/16 (different /24) peer costs only 1/4 weight while a repeat exact IP still hits the cap."""
    cap = 1                                          # threshold 8; same-/16(diff /24) peer costs 2
    assert allow_registration("30.0.1.1", "a", max_addrs=cap)
    # same /16, different /24 -> costs 2 (< 8) -> still allowed at cap 1 (progressive, 1/4 weight)
    assert allow_registration("30.0.2.1", "b", max_addrs=cap), "same /16 diff /24 peer costs only 1/4"
    # but a 2nd from the SAME exact IP costs the full 8 -> capped at 1
    assert not allow_registration("30.0.1.1", "c", max_addrs=cap), "2nd from the exact IP is capped at 1"

def t6_zero_disables():
    """Prove max_addrs=0 disables the limit entirely (500 addresses from one IP all pass)."""
    for i in range(500):
        assert allow_registration("40.0.0.1", f"z{i}", max_addrs=0), "cap 0 disables the limit"

def t7_window_expiry():
    """Prove entries expire after the sliding window, freeing the slot for a new address."""
    ip = "50.0.0.1"
    assert allow_registration(ip, "old", max_addrs=1, window=0.05)
    assert not allow_registration(ip, "new", max_addrs=1, window=0.05), "still within window"
    time.sleep(0.06)
    assert allow_registration(ip, "new", max_addrs=1, window=0.05), "prior entry expired -> slot frees"

def t8_ipv6_grouped_by_64():
    """Prove IPv6 crowding groups by /64 (same-/64 peers cost half) while a different /32 is unrelated and free."""
    cap = 1                                          # threshold 8; same-/64 peer costs 4 (half)
    assert allow_registration("2001:db8:abcd:1::1", "v1", max_addrs=cap)
    assert allow_registration("2001:db8:abcd:1::2", "v2", max_addrs=cap), "2nd in same /64 costs half -> fits"
    assert not allow_registration("2001:db8:abcd:1::3", "v3", max_addrs=cap), "3rd same-/64 peer: crowding 8 >= 8"
    assert allow_registration("2001:dead:beef:1::1", "v4", max_addrs=cap), "different /32 is unrelated -> free"

for name, fn in list(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)

print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
