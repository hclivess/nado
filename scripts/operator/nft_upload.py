"""NFT media upload — the objkt-style "choose a file" behind nft.nadochain.com/upload (2026-11-01).

An artist picks a file in the Create form; this service checks it and adds it, PINNED, to the IPFS node on this machine
(nado-ipfs.service, kubo): the local copy is what keeps the file alive, and the node serves it to the IPFS network so
any gateway can fetch it. The page then puts `ipfs://<cid>` in the NFT's asset uri. Media is served back through the
same node's gateway at nft.nadochain.com/ipfs/<cid> (nginx, sandboxed).

WHY A SERVICE IN FRONT OF IPFS, not nginx straight to kubo's /api/v0/add: kubo cannot cap what is pinned to it, and
"anyone may upload" on a public server needs every limit enforced before a byte is kept —
  * size     at most MAX_BYTES (5 MB — the operator's limit), checked on the stream, never buffered past it;
  * type     the file's own BYTES must be an image / video / audio / 3D model format (MAGIC below). HTML, SVG, PDF,
             archives and everything unknown are refused: a document served from nft.nadochain.com could run script
             on that origin (the gateway also sends a sandbox CSP — two locks, not one);
  * rate     PER_IP_HOUR uploads per client per hour and DAY_TOTAL per day for everyone (the client IP is nginx's
             X-Real-IP, the TRUE client behind Cloudflare via conf.d/cloudflare_realip.conf);
  * storage  the IPFS repo stays under STORE_CAP (the disk had 68 GB free when this was written).
kubo's API listens on 127.0.0.1 only and is never exposed; this service listens on 127.0.0.1 only and is reached
through the nft vhost's `location = /upload`.

MODERATION: `python3 scripts/operator/nft_upload.py unpin <cid>` unpins a reported file and garbage-collects it from
this node (it can still exist on other IPFS nodes that chose to keep it; nothing here can reach those).

Run: python3 scripts/operator/nft_upload.py serve [--port 9180]   (deploy/units/nado-nft-upload.service)
"""
import argparse
import asyncio
import json
import sys
import time

MAX_BYTES = 5 * 1024 * 1024
PER_IP_HOUR = 20
DAY_TOTAL = 500
STORE_CAP = 40 * 1024 ** 3
KUBO = "http://127.0.0.1:5001/api/v0"


def sniff(head: bytes):
    """The media type the file's first bytes PROVE, or None. Never the client's Content-Type or file name: both are
    the uploader's claim, and the bytes are what a browser will interpret."""
    h = head
    if h.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if h.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP":
        return "image/webp"
    if h[:4] == b"RIFF" and h[8:12] == b"WAVE":
        return "audio/wav"
    if h[4:8] == b"ftyp":
        brand = h[8:12]
        if brand in (b"avif", b"avis"):
            return "image/avif"
        if brand in (b"isom", b"iso2", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"M4V ", b"dash", b"qt  "):
            return "video/mp4"
        if brand in (b"M4A ",):
            return "audio/mp4"
        return None
    if h.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if h.startswith(b"OggS"):
        return "audio/ogg"
    if h.startswith(b"fLaC"):
        return "audio/flac"
    if h.startswith(b"ID3") or h[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    if h.startswith(b"glTF"):
        return "model/gltf-binary"
    return None


class Limits:
    """In-memory sliding counters (a restart forgets them — a bound on abuse, not an accounting system)."""

    def __init__(self, now=time.time):
        self.now, self.by_ip, self.day = now, {}, []

    def allow(self, ip):
        t = self.now()
        self.day = [x for x in self.day if t - x < 86400]
        hits = [x for x in self.by_ip.get(ip, []) if t - x < 3600]
        self.by_ip[ip] = hits
        if len(hits) >= PER_IP_HOUR:
            return "too many uploads from your address this hour — try again later"
        if len(self.day) >= DAY_TOTAL:
            return "the upload limit for today is reached — try again tomorrow"
        return None

    def record(self, ip):
        t = self.now()
        self.by_ip.setdefault(ip, []).append(t)
        self.day.append(t)


def make_app(kubo=KUBO, limits=None, repo_size=None):
    from aiohttp import web, ClientSession, ClientTimeout, FormData
    limits = limits or Limits()

    async def _repo_size():
        if repo_size is not None:
            return await repo_size()
        async with ClientSession(timeout=ClientTimeout(total=20)) as s:
            async with s.post(kubo + "/repo/stat?size-only=true") as r:
                return int((await r.json()).get("RepoSize", 0))

    def refuse(code, msg):
        return web.json_response({"error": msg}, status=code)

    async def upload(request):
        ip = request.headers.get("X-Real-IP") or (request.remote or "?")
        why = limits.allow(ip)
        if why:
            return refuse(429, why)
        if request.content_length is not None and request.content_length > MAX_BYTES + 64 * 1024:
            return refuse(413, f"the file is larger than {MAX_BYTES // (1024 * 1024)} MB")
        try:
            reader = await request.multipart()
            part = await reader.next()
            while part is not None and part.name != "file":
                part = await reader.next()
            if part is None:
                return refuse(400, "no file in the upload")
            data = bytearray()
            while True:
                chunk = await part.read_chunk(64 * 1024)
                if not chunk:
                    break
                data += chunk
                if len(data) > MAX_BYTES:
                    return refuse(413, f"the file is larger than {MAX_BYTES // (1024 * 1024)} MB")
        except Exception:
            return refuse(400, "the upload could not be read")
        if not data:
            return refuse(400, "the file is empty")
        mime = sniff(bytes(data[:64]))
        if mime is None:
            return refuse(415, "only image, video, audio or GLB 3D files can be uploaded")
        try:
            if await _repo_size() + len(data) > STORE_CAP:
                print(f"[nft_upload] REFUSED: the IPFS repo is at its {STORE_CAP} B cap", flush=True)
                return refuse(507, "media storage is full — try again later")
            form = FormData()
            form.add_field("file", bytes(data), filename="media", content_type="application/octet-stream")
            async with ClientSession(timeout=ClientTimeout(total=120)) as s:
                async with s.post(kubo + "/add?pin=true&cid-version=1&quieter=true", data=form) as r:
                    if r.status != 200:
                        return refuse(502, "the IPFS node refused the file")
                    cid = json.loads((await r.text()).strip().splitlines()[-1])["Hash"]
        except Exception as e:
            print(f"[nft_upload] IPFS node unavailable: {e}", flush=True)
            return refuse(503, "the IPFS node is not available right now — try again shortly")
        limits.record(ip)
        print(f"[nft_upload] pinned {cid} {mime} {len(data)} B from {ip}", flush=True)
        return web.json_response({"cid": cid, "mime": mime, "bytes": len(data)})

    async def health(request):
        return web.json_response({"ok": True, "max_bytes": MAX_BYTES})

    app = web.Application(client_max_size=MAX_BYTES + 128 * 1024)
    app.router.add_post("/upload", upload)
    app.router.add_get("/upload/health", health)
    return app


def unpin(cid):
    import urllib.request
    for path in (f"/pin/rm?arg={cid}", "/repo/gc"):
        req = urllib.request.Request(KUBO + path, method="POST")
        with urllib.request.urlopen(req, timeout=120) as r:  # nosec B310 # the local kubo API (127.0.0.1), operator CLI
            r.read()
    print(f"unpinned and collected {cid} on this node")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=9180)
    u = sub.add_parser("unpin")
    u.add_argument("cid")
    a = ap.parse_args()
    if a.cmd == "unpin":
        return unpin(a.cid)
    from aiohttp import web
    web.run_app(make_app(), host="127.0.0.1", port=a.port, print=None)


if __name__ == "__main__":
    sys.exit(main())
