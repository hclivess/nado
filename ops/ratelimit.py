"""Lean per-IP sliding-window rate limiter for the HTTP API (anti-spam / anti-DoS).

The open lane is fee-exempt (register/heartbeat cost no coins), so the lane CAP stops spam from
buying extra block share — but a flood could still bloat the mempool/state and take a node down.
This bounds the submission rate per source IP. Called from the single-threaded Tornado IOLoop
(async get/post), so no lock is needed. Memory is bounded by an opportunistic sweep.
"""
import ipaddress
import time
from collections import deque, defaultdict

_buckets = defaultdict(deque)
_MAX_KEYS = 100_000

# PROGRESSIVE IP-DIVERSITY registration cap. NON-CONSENSUS on purpose: it is THIS relay's admission
# control at the point of entry, NOT a selection-weight rule — an IP can't be a consensus input (nodes
# see different IPs; it is spoofable and NAT/CGNAT-ambiguous), so weighting selection by IP would fork
# the chain. This is the sound layer to apply the "one IP shouldn't spawn unlimited miners" intuition.
#
# Instead of a flat per-exact-IP count, an address's "crowding cost" scales with how CLOSE its IP is,
# in the address space, to other recently-registered IPs — so a datacenter that orders 50 machines in
# one /24 (each a unique /32) is still bounded as a range, while genuinely distinct networks are not
# penalised. A same-EXACT-IP peer costs the most; each broader shared prefix costs half as much; an IP
# sharing no prefix costs nothing. Weights are integers (x8) so the comparison stays exact/deterministic.
#   IPv4 prefixes: /32 (exact), /24, /16, /8      IPv6: /128, /64 (one customer), /48, /32
_LEVELS_V4 = (32, 24, 16, 8)
_LEVELS_V6 = (128, 64, 48, 32)
_LEVEL_WEIGHTS = (8, 4, 2, 1)   # exact, then halving per broader prefix (the "step")
# One dict per level: prefix_string -> {address: last_seen_ts}. An address is recorded under ALL of its
# IP's prefixes, so counts nest (level-0 subset of level-1 ...), and exclusive-by-closest-level counts
# are recovered by subtraction.
_reg_levels = [defaultdict(dict), defaultdict(dict), defaultdict(dict), defaultdict(dict)]


def _prefixes(ip: str):
    """The four network-prefix keys (most→least specific) an IP is grouped under. Non-IP inputs fall
    back to the raw string at every level (treated as their own exact group)."""
    try:
        levels = _LEVELS_V4 if ipaddress.ip_address(ip).version == 4 else _LEVELS_V6
    except ValueError:
        return (ip, ip, ip, ip)
    return tuple(f"{ipaddress.ip_network(f'{ip}/{p}', strict=False).network_address}/{p}" for p in levels)


def allow_registration(ip: str, address: str, max_addrs: int, window: float = 3600.0) -> bool:
    """True if `ip` may onboard `address`. `max_addrs` is the crowding budget expressed as
    'equivalent same-EXACT-IP addresses': a same-/32 peer costs 1.0 of it, a same-/24 (diff /32) peer
    0.5, same-/16 0.25, same-/8 0.125, unrelated 0. So the effective per-range limit is progressive —
    ~max_addrs per exact IP, ~2x per /24, ~4x per /16, ~8x per /8. An address already seen from this
    exact IP is always allowed (retries/heartbeats never count). False -> caller returns 429/403.

    Best-effort by design: an attacker can still spread across relays or rent scattered IPs, and a
    CGNAT'd carrier shares ranges among real phones — so keep max_addrs GENEROUS. The HARD Sybil bound
    remains the structural OPEN_BPS lane cap; this only raises the cost of the cheap single-range version."""
    if max_addrs <= 0:
        return True                                        # 0/negative disables the cap
    now = time.time()
    cutoff = now - window
    pfx = _prefixes(ip)
    seen_sets = []
    for i, key in enumerate(pfx):
        bucket = _reg_levels[i][key]
        for a in [a for a, t in bucket.items() if t < cutoff]:
            del bucket[a]
        seen_sets.append(set(bucket.keys()))
    # already onboarded from this EXACT IP -> always allow, refresh timestamps
    already = address in seen_sets[0]
    # exclusive peer counts by closest shared level (nested sets -> subtract), excluding self
    excl = [seen_sets[0] - {address},
            seen_sets[1] - seen_sets[0],
            seen_sets[2] - seen_sets[1],
            seen_sets[3] - seen_sets[2]]
    crowding = sum(_LEVEL_WEIGHTS[i] * len(excl[i]) for i in range(4))
    if not already and crowding >= max_addrs * _LEVEL_WEIGHTS[0]:
        return False
    for i, key in enumerate(pfx):                          # record under every prefix level
        _reg_levels[i][key][address] = now
    if len(_reg_levels[0]) > _MAX_KEYS:                    # opportunistic GC so the maps can't grow unbounded
        for lvl in _reg_levels:
            for k in list(lvl.keys()):
                d = lvl[k]
                for a in [a for a, t in d.items() if t < cutoff]:
                    del d[a]
                if not d:
                    del lvl[k]
    return True


def allow(ip: str, limit: int, window: float = 60.0) -> bool:
    """True if `ip` has made fewer than `limit` calls in the last `window` seconds (and records this
    one). False (caller should return HTTP 429) once over the limit."""
    now = time.time()
    cutoff = now - window
    dq = _buckets[ip]
    while dq and dq[0] < cutoff:
        dq.popleft()
    if len(dq) >= limit:
        return False
    dq.append(now)
    if len(_buckets) > _MAX_KEYS:                      # opportunistic GC so the map can't grow unbounded
        for k in list(_buckets.keys()):
            d = _buckets[k]
            while d and d[0] < cutoff:
                d.popleft()
            if not d:
                del _buckets[k]
    return True
