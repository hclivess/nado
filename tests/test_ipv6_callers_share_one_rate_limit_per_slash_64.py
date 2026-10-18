"""IPv6 callers share one rate-limit bucket per /64 (ops/ratelimit.py _bucket_key), so rotating the interface ID of an
address cannot buy fresh limits — audit 2026-09-24 (lower), confirmed 2026-10-18: the limiter keyed on the full address,
2^64 buckets for one machine. IPv4, IPv4-mapped IPv6 and prefixed keys ("stwo_relay|<ip>") behave as before.

Run: python3 tests/test_ipv6_callers_share_one_rate_limit_per_slash_64.py
"""
import _harness
_harness.isolate("nado-test-ratelimit-v6-", exec_state=False)
from ops import ratelimit as R

T = _harness.Report()
k = R._bucket_key
T.check("two addresses in one /64 share a bucket", k("2001:db8:1:2::1") == k("2001:db8:1:2:ffff:ffff:ffff:ffff"))
T.check("...and different /64s do not", k("2001:db8:1:2::1") != k("2001:db8:1:3::1"))
T.check("a prefixed key keeps its prefix and buckets the address", k("stwo_relay|2001:db8:1:2::9") == "stwo_relay|2001:db8:1:2::/64")
T.check("bracketed IPv6 is read too", k("x|[2001:db8:1:2::9]") == "x|2001:db8:1:2::/64")
T.check("IPv4 is unchanged", k("203.0.113.7") == "203.0.113.7" and k("p|203.0.113.7") == "p|203.0.113.7")
T.check("IPv4-mapped IPv6 counts as its IPv4", k("::ffff:203.0.113.7") == "203.0.113.7")
T.check("a key that is no address is unchanged", k("stwo_relay|nobody") == "stwo_relay|nobody")
for i in range(3):
    R.allow(f"2001:db8:9:9::{i + 1}", 3, 60)
T.check("rotating the interface ID inside one /64 hits the same limit", not R.allow("2001:db8:9:9::abcd", 3, 60))
T.check("...while another /64 still has its own", R.allow("2001:db8:9:a::1", 3, 60))
T.done("ALL PASS — IPv6 callers share one rate limit per /64")
