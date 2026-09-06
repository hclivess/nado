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
_last_gc = [0.0]      # time-gate for the over-cap sweep (see allow)

# (The progressive per-IP registration budget and the per-IP identity cap that lived here were RETIRED at gen 25:
#  an open-lane identity now costs an attested device — doc/device-attestation.md.)


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
    # opportunistic GC so the map can't grow unbounded — TIME-GATED (audit): once over the cap, the
    # ungated sweep ran the full O(100k) scan on EVERY request until the map shrank, so the exact
    # condition it defends against (an IP-diverse scan) turned each request into a full-map walk.
    if len(_buckets) > _MAX_KEYS and now - _last_gc[0] >= 60:
        _last_gc[0] = now
        for k in list(_buckets.keys()):
            d = _buckets[k]
            while d and d[0] < cutoff:
                d.popleft()
            if not d:
                del _buckets[k]
    return True
