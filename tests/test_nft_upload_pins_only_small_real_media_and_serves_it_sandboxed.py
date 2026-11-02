"""The NFT media upload (scripts/operator/nft_upload.py, nft.nadochain.com/upload) pins only small, real media, and the
site serves it back sandboxed (website/nginx-nft.nadochain.com.conf), 2026-11-01.

"Anyone may upload" on a public server: every limit has to hold before a byte is kept. Driven against a FAKE kubo API
(an aiohttp app on a loopback port), so nothing touches a real IPFS node. Pins:
  1. a PNG is pinned (kubo add with pin=true, CIDv1) and its cid returned;
  2. the type is the file's BYTES: SVG, HTML and an unknown blob are refused even when named .png / sent as image/png;
  3. more than 5 MB is refused, whatever Content-Length claims;
  4. the per-client hourly limit holds (keyed on X-Real-IP), and another client is unaffected;
  5. a full store refuses (507), and a dead IPFS node is a 503 — never a crash;
  6. the vhost: /upload is POST-only with a body ceiling, /ipfs/ is GET/HEAD-only and every media response carries a
     sandbox CSP and nosniff (an uploaded file may never run script on the site's origin);
  7. the page serves ipfs:// from this site's own /ipfs/ and caps uploads at the same 5 MB.

Run: python3 tests/test_nft_upload_pins_only_small_real_media_and_serves_it_sandboxed.py
"""
import asyncio
import os
import re
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-nft-upload-")      # NEVER the live node's home (rule 4)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "operator"))

import nft_upload as U
from aiohttp import web, FormData, ClientSession
from aiohttp.test_utils import TestServer

import _harness
_report = _harness.Report()
check = _report.check

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
HTML = b"<!doctype html><script>alert(1)</script>"


async def main():
    added = []
    kubo_up = {"v": True}

    async def k_add(request):
        if not kubo_up["v"]:
            raise web.HTTPServiceUnavailable()
        reader = await request.multipart()
        part = await reader.next()
        body = await part.read()
        added.append((dict(request.query), len(body)))
        return web.Response(text='{"Name":"media","Hash":"bafkfake%d","Size":"%d"}\n' % (len(added), len(body)))

    kapp = web.Application()
    kapp.router.add_post("/api/v0/add", k_add)
    ksrv = TestServer(kapp); await ksrv.start_server()
    kubo = str(ksrv.make_url("/api/v0"))

    size = {"v": 0}

    async def repo_size():
        if not kubo_up["v"]:
            raise OSError("connection refused")
        return size["v"]

    usrv = TestServer(U.make_app(kubo=kubo, repo_size=repo_size)); await usrv.start_server()
    url = str(usrv.make_url("/upload"))

    async def up(data, ip="203.0.113.7", name="a.png", ctype="image/png"):
        fd = FormData(); fd.add_field("file", data, filename=name, content_type=ctype)
        async with ClientSession() as s:
            async with s.post(url, data=fd, headers={"X-Real-IP": ip}) as r:
                return r.status, await r.json()

    st, j = await up(PNG)
    check("1. a PNG is pinned and its cid returned",
          st == 200 and j.get("cid", "").startswith("bafkfake") and j.get("mime") == "image/png"
          and added and added[-1][0].get("pin") == "true" and added[-1][0].get("cid-version") == "1", (st, j, added))
    n = len(added)
    for blob, label in ((SVG, "svg"), (HTML, "html"), (b"\x00\x01garbage" * 10, "unknown")):
        st, j = await up(blob, name="trick.png", ctype="image/png")
        check(f"2. {label} is refused by its bytes, whatever it is called", st == 415 and len(added) == n, (st, j))
    st, j = await up(PNG + b"\x00" * U.MAX_BYTES)
    check("3. more than 5 MB is refused", st == 413 and len(added) == n, (st, j))
    for _ in range(U.PER_IP_HOUR - 1):          # one PNG already counted for this client
        await up(PNG)
    st, j = await up(PNG)
    st2, _ = await up(PNG, ip="198.51.100.9")
    check("4. the hourly per-client limit holds, another client is unaffected", st == 429 and st2 == 200, (st, st2))
    size["v"] = U.STORE_CAP
    st, _ = await up(PNG, ip="198.51.100.10")
    check("5. a full store refuses", st == 507)
    size["v"] = 0; kubo_up["v"] = False
    st, j = await up(PNG, ip="198.51.100.11")
    check("5. a dead IPFS node is a 503, not a crash", st == 503, (st, j))
    await usrv.close(); await ksrv.close()


asyncio.run(main())

conf = open(os.path.join(ROOT, "website", "nginx-nft.nadochain.com.conf")).read()
upl = re.search(r"location = /upload \{(.*?)\}\s*\n", conf, re.S)
ipfs = re.search(r"location /ipfs/ \{(.*?)\}\s*\n\s*\n", conf, re.S)
check("6. /upload is POST-only with a body ceiling, proxied to the checking service only",
      upl and "limit_except POST { deny all; }" in upl.group(1) and "client_max_body_size 6m" in upl.group(1)
      and "127.0.0.1:9180/upload" in upl.group(1) and "5001" not in conf)
check("6. /ipfs/ is GET/HEAD-only and sandboxed with nosniff on every response",
      ipfs and "limit_except GET HEAD { deny all; }" in ipfs.group(1) and 'Content-Security-Policy "sandbox;' in ipfs.group(1)
      and "X-Content-Type-Options nosniff always" in ipfs.group(1) and "127.0.0.1:8089" in ipfs.group(1))
unit = open(os.path.join(ROOT, "deploy", "units", "nado-ipfs.service")).read()
check("6. the gateway serves only what this node pinned (Gateway.NoFetch), never any CID from the network",
      "ExecStartPre=/usr/local/bin/ipfs config --json Gateway.NoFetch true" in unit
      and unit.index("Gateway.NoFetch") < unit.index("ExecStart=/usr/local/bin/ipfs daemon"))
js = open(os.path.join(ROOT, "static", "nft.js"), encoding="utf-8").read()
check("7. the page serves ipfs:// from this site's /ipfs/ and caps uploads at 5 MB",
      'base() + "/ipfs/"' in js and "ipfs.io" not in js and "const MAX_UPLOAD = 5 * 1024 * 1024" in js
      and U.MAX_BYTES == 5 * 1024 * 1024)
_report.done()
