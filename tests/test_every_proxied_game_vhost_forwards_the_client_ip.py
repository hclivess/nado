"""Every nginx vhost template that proxies to the node or the exec node forwards the client's IP (X-Real-IP +
X-Forwarded-For), so per-IP rate limits and anti-Sybil caps see the real client (website/nginx-*.nadochain.com.conf).

Audit 2026-09-24 #28 (nginx half), confirmed 2026-10-18: the 24 game vhosts proxied with only `Host`, so every player on
a game subdomain reached the node from 127.0.0.1 — one bucket for all of them, so one spammer throttled a whole game. (The
other half — loopback-plus-public-Host never counting as "local" — is nado.py _is_local_request.) The node resolves the
header only from its configured trusted_proxies (127.0.0.1, ::1 on the seed box), so forwarding it is safe.

Run: python3 tests/test_every_proxied_game_vhost_forwards_the_client_ip.py
"""
import _harness
_harness.isolate("nado-test-vhost-xff-", exec_state=False)
import glob, os, re

T = _harness.Report()
files = sorted(glob.glob(os.path.join(_harness.ROOT, "website", "nginx-*.conf")))
T.check("the vhost templates are found", len(files) >= 20, len(files))
def location_blocks(src):
    """(line, text) of every `location … { … }` block, braces balanced (a block may span lines)."""
    out, i = [], 0
    for m in re.finditer(r"\blocation\b[^{]*\{", src):
        depth, j = 1, m.end()
        while depth and j < len(src):
            depth += {"{": 1, "}": -1}.get(src[j], 0); j += 1
        out.append((src[:m.start()].count("\n") + 1, src[m.start():j]))
    return out


bad = []
for f in files:
    for line, blk in location_blocks(open(f, encoding="utf-8").read()):
        if re.search(r"proxy_pass http://127\.0\.0\.1:9[12]73", blk) and not (
                "X-Forwarded-For $proxy_add_x_forwarded_for" in blk and "X-Real-IP $remote_addr" in blk):
            bad.append(f"{os.path.basename(f)}:{line}")
T.check("every location that proxies to the node forwards the client IP", not bad, bad[:6])
T.done("ALL PASS — every proxied game vhost forwards the client IP")
