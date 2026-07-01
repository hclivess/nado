"""Lean per-IP sliding-window rate limiter for the HTTP API (anti-spam / anti-DoS).

The open lane is fee-exempt (register/heartbeat cost no coins), so the lane CAP stops spam from
buying extra block share — but a flood could still bloat the mempool/state and take a node down.
This bounds the submission rate per source IP. Called from the single-threaded Tornado IOLoop
(async get/post), so no lock is needed. Memory is bounded by an opportunistic sweep.
"""
import time
from collections import deque, defaultdict

_buckets = defaultdict(deque)
_MAX_KEYS = 100_000

# IP-DIVERSITY registration cap: ip -> {address: last_seen_ts}. Tracks the DISTINCT OPEN-lane
# addresses each source IP has onboarded recently, so one device/IP can't script thousands of
# identities. NON-CONSENSUS on purpose: it is THIS relay's admission control at the point of entry,
# NOT a selection-weight rule — an IP can't be a consensus input (nodes see different IPs; it is
# spoofable and NAT/CGNAT-ambiguous), so weighting selection by IP would fork the chain. This is the
# sound layer to apply the "one IP shouldn't spawn unlimited miners" intuition.
_reg_by_ip = defaultdict(dict)


def allow_registration(ip: str, address: str, max_addrs: int, window: float = 3600.0) -> bool:
    """True if `ip` may onboard `address`: a source IP is allowed at most `max_addrs` DISTINCT
    registering addresses within `window` seconds. An address already seen from this IP is always
    allowed (re-submits/retries never count against the cap). False -> caller returns 429/403.

    Local + best-effort by design: a determined attacker can spread across relays or rotate IPs, and
    a legitimate CGNAT'd carrier shares one IP among many phones — so keep max_addrs GENEROUS (it only
    has to stop the naive '10k addresses from one box', not be a hard Sybil bound). The hard Sybil
    bound is still the structural OPEN_BPS lane cap; this just raises the cost of the cheap version."""
    if max_addrs <= 0:
        return True                                    # 0/negative disables the cap
    now = time.time()
    cutoff = now - window
    seen = _reg_by_ip[ip]
    for a in [a for a, t in seen.items() if t < cutoff]:
        del seen[a]
    if address in seen:
        seen[address] = now
        return True
    if len(seen) >= max_addrs:
        return False
    seen[address] = now
    if len(_reg_by_ip) > _MAX_KEYS:                    # opportunistic GC so the map can't grow unbounded
        for k in list(_reg_by_ip.keys()):
            d = _reg_by_ip[k]
            for a in [a for a, t in d.items() if t < cutoff]:
                del d[a]
            if not d:
                del _reg_by_ip[k]
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
