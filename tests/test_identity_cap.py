"""ops/ratelimit.allow_identity: one IP keeps at most `cap` identities registered through this relay over
a lease; progressive across ranges (~2x per /24, ~4x per /16); an identity already seen from the exact IP
always renews; entries and renewals share the budget (nado._ip_registration_rejection applies it to EVERY
register tx before the entries-only budget)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ops import ratelimit as rl


def main():
    rl._id_levels[:] = [rl.defaultdict(dict) for _ in range(4)]
    ip = "203.0.113.10"
    for i in range(5):
        assert rl.allow_identity(ip, f"a{i}", 5), i               # five identities fit
    assert not rl.allow_identity(ip, "a5", 5), "sixth identity from the same IP refused"
    assert rl.allow_identity(ip, "a0", 5), "an identity already seen from this IP always renews"
    # a neighbour in the same /24 sees the crowding at half weight: it still gets ~5 more of its own
    ip2 = "203.0.113.77"
    ok = sum(1 for i in range(10) if rl.allow_identity(ip2, f"b{i}", 5))
    assert 2 <= ok <= 5, ok                                         # progressive, not a hard /24 ban
    # a roaming single identity from a fresh network is never refused
    assert rl.allow_identity("198.51.100.5", "a0", 5)
    assert rl.allow_identity("2001:db8::1", "c0", 5)
    assert rl.allow_identity("10.0.0.1", "x", 0), "0 disables the cap"
    # registration (entry) budget keeps its own store
    assert rl.allow_registration(ip, "zz", 8)
    src = open(os.path.join(ROOT, "nado.py")).read()
    body = src[src.index("def _ip_registration_rejection"):src.index("async def health")]
    assert body.index("allow_identity(ip, _sender") < body.index("is_entry_registration("), \
        "identity cap must apply to every register tx BEFORE the entries-only budget"
    assert 'getattr(memserver, "max_identities_per_ip", 5)' in body
    assert '"max_identities_per_ip": 5' in open(os.path.join(ROOT, "config.py")).read()
    print("ALL OK")


if __name__ == "__main__":
    main()
