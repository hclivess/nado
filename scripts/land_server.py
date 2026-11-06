#!/usr/bin/env python3
"""Land world server (doc/land.md): the live planet — who is where, and every block anyone changed — for the page
(static/land.js) and for the AI agents owners invite. Runs as its own declared job (deploy/units/nado-land.service), NOT
inside the node: a game outage never touches the chain.

WHAT IT TRUSTS. Ownership is the chain's: a plot's title holder is read from the exec node (/exec/asset), a builder's
grant from the land contract (/exec/view builder_of) and honoured only while its grantor still holds the title. Identity
is a signature: a browser signs a one-time, domain-tagged challenge in the NADO wallet (static/interface.js
resumePendingLandLogin), an agent signs one with ITS OWN key (scripts/land_agent.py) — never the owner's. Every write,
a click or an API call, passes the same check (may_build).

WHAT IT STORES. Each plot's edits over the generated terrain and its commitment salt, one JSON file per plot under
--data (atomic replace). The terrain itself is static/land-world.js, a pure function of the seed: the server never
generates it; a cell edit is [x, z, y, block] within its plot, exactly what the commitment hashes (commitment_bytes, the
byte-for-byte twin of land-world.js commitmentBytes — tests/test_the_land_server_lets_only_holders_and_their_builders_change_a_plot.py
checks the two agree).

API (JSON; doc/land.md "The API for agents"):
  GET  /land/api/challenge?kind=agent|browser   -> {nonce, issued, origin}   (browser: also a login cookie, redirect-free)
  GET  /land/api/login?return=/                 -> 302 to the wallet with a browser challenge
  POST /land/api/login_callback (form)          <- the wallet's top-level POST: address, public_key, alg, signature, nonce
  POST /land/api/agent_login {address, public_key, alg?, signature, nonce}  -> {token}
  GET  /land/api/me                             -> {address|null, plots: [...], builds: [...]}
  GET  /land/api/plot?plot=                     -> {plot, edits, ver, holder}   (+ salt for its holder and builders)
  GET  /land/api/region?face=&u0=&v0=&u1=&v1=   -> {plots: {plot: {ver, edits}}} for the edited plots in a box
  POST /land/api/set {cells: [[face, u, v, h, block], ...]}   -> {applied, refused: [[cell, reason], ...]}
  GET  /land/ws                                 -> the live channel (see _ws)
Auth on the API: the land_session cookie (browser) or `Authorization: Bearer <token>` (agent).
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-land-")   # BEFORE any node import (CLAUDE.md rule 4); data is --data
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import argparse, asyncio, hashlib, json, secrets, time, urllib.parse

from aiohttp import web, ClientSession, ClientTimeout, WSMsgType

from signatures import verify as sig_verify, unhex          # noqa: E402 — pure crypto, no database
from ops.address_ops import proof_sender, validate_address  # noqa: E402 — pure derivation, no database
from hashing import blake2b_hash                            # noqa: E402
from execnode.games import land as L                        # noqa: E402 — constants + plot_seed only
from execnode.runtimes import zkvm_addr_digest              # noqa: E402 — pure hashing

DOMAIN = "land-login-v1"          # static/interface.js DOMAIN_LAND_LOGIN — a login signature is good for nothing else
AGENT_ORIGIN = "land-agent"       # the origin an agent's challenge names (a browser's names the site): not interchangeable
CHALLENGE_TTL = 300
SESSION_TTL = 7 * 86400
FACE_N, PLOT, W, H = L.FACE_N, L.PLOT, L.FACE_N * L.PLOT, 256
N_BLOCKS = 31                     # static/land-world.js BLOCKS.length
UNBUILDABLE = {5, 30}             # water, bedrock: never placed (land-world.js `build: false` besides air)
MAX_CELLS = 4096                  # per /set call or ws "set"
RATE = 400                        # cells per second per caller, refilling a bucket that holds one full call (MAX_CELLS)
PLANET = 0

# ---- the plot's commitment (land-world.js commitmentBytes, byte for byte) ------------------------------------------
def canonical_edits(edits):
    m = {}
    for x, z, y, b in edits:
        if not (0 <= x < PLOT and 0 <= z < PLOT and 0 <= y < H and 0 <= b < N_BLOCKS):
            raise ValueError("bad edit")
        m[(y * PLOT + z) * PLOT + x] = b
    return [(k % PLOT, (k // PLOT) % PLOT, k // (PLOT * PLOT), m[k]) for k in sorted(m)]


def commitment_bytes(plot, salt, edits):
    if len(salt) != 32:
        raise ValueError("salt must be 32 bytes")
    out = bytearray(b"nado-land-plot-v1") + plot.to_bytes(4, "big") + salt
    for x, z, y, b in canonical_edits(edits):
        out += bytes([x, z, y >> 8, y & 255, b])
    return bytes(out)


def commitment(plot, salt, edits):
    n = int.from_bytes(hashlib.sha256(commitment_bytes(plot, salt, edits)).digest(), "big")
    return str(n or 1)


def plot_of(face, u, v):
    return (face * FACE_N + v // PLOT) * FACE_N + u // PLOT


def plot_coords(plot):
    return plot // (FACE_N * FACE_N), (plot // FACE_N) % FACE_N, plot % FACE_N     # face, row, col


# ---- the world ------------------------------------------------------------------------------------------------------
class World:
    def __init__(self, data_dir, exec_url, land_cid, issuer=L.ISSUER):
        self.dir = data_dir
        os.makedirs(self.dir, exist_ok=True)
        self.exec_url, self.cid, self.issuer = exec_url.rstrip("/"), land_cid, issuer
        self.plots = {}                       # plot -> {"edits": {(x,z,y): b}, "salt": bytes, "ver": int}
        self.dirty = set()
        self.titles = {}                      # plot -> asset id (planet 0 titles of the issuer)
        self.titles_at = 0
        self.holders = {}                     # plot -> (holder, at)
        self.grants = {}                      # (plot, addr) -> (grantor digest or 0, at)
        self.challenges = {}                  # nonce -> {"issued", "origin", "bind"}
        self.sessions = {}                    # token -> {"address", "until"}
        self.buckets = {}                     # caller -> [tokens, at]
        self.http = None
        for f in os.listdir(self.dir):
            if f.endswith(".json") and f[:-5].isdigit():
                try:
                    d = json.load(open(os.path.join(self.dir, f)))
                    self.plots[int(f[:-5])] = {"edits": {tuple(map(int, k.split(":"))): b for k, b in d["edits"].items()},
                                               "salt": bytes.fromhex(d["salt"]), "ver": int(d.get("ver", 0))}
                except Exception:
                    pass

    # -- persistence
    def plot(self, p):
        rec = self.plots.get(p)
        if rec is None:
            rec = self.plots[p] = {"edits": {}, "salt": secrets.token_bytes(32), "ver": 0}
        return rec

    def flush(self):
        for p in list(self.dirty):
            rec = self.plots[p]
            body = {"edits": {f"{x}:{z}:{y}": b for (x, z, y), b in rec["edits"].items()}, "salt": rec["salt"].hex(), "ver": rec["ver"]}
            path = os.path.join(self.dir, f"{p}.json")
            fd, tmp = tempfile.mkstemp(dir=self.dir, prefix=".plot-")
            with os.fdopen(fd, "w") as f:
                json.dump(body, f, separators=(",", ":"))
            os.replace(tmp, path)                  # a reader (or a crash) never sees half a plot
            self.dirty.discard(p)

    # -- the chain's answers, cached a few seconds (a view is a VM run on the exec node)
    async def _get(self, path):
        async with self.http.get(self.exec_url + path) as r:
            return await r.json(content_type=None)

    async def refresh_titles(self, force=False):
        if not force and time.time() - self.titles_at < 30:
            return
        try:
            r = await self._get("/exec/assets?issuer=" + self.issuer)
            for a in r.get("assets") or []:
                s = int(a.get("seed", 0))
                if s >> 48 == L.SEED_TAG >> 48 and (s >> 32) & 0xFFFF == PLANET:
                    self.titles[s & 0xFFFFFFFF] = str(a["id"])
            self.titles_at = time.time()
        except Exception:
            pass

    async def holder(self, p):
        h = self.holders.get(p)
        if h and time.time() - h[1] < 10:
            return h[0]
        await self.refresh_titles()
        aid = self.titles.get(p)
        if not aid:
            return None
        try:
            r = await self._get("/exec/asset?id=" + aid)
            hs = r.get("holders") or {}
            who = next((a for a, n in hs.items() if int(n) > 0), None)
        except Exception:
            return h[0] if h else None
        self.holders[p] = (who, time.time())
        return who

    async def grant(self, p, addr):
        """The digest of whoever granted `addr` on plot `p` (land.py builder_of; 0 = no grant)."""
        g = self.grants.get((p, addr))
        if g and time.time() - g[1] < 15:
            return g[0]
        d = 0
        if self.cid:
            try:
                q = urllib.parse.urlencode({"cid": self.cid, "method": "builder_of", "args": json.dumps([p, addr])})
                d = int((await self._get("/exec/view?" + q)).get("result") or 0)
            except Exception:
                return g[0] if g else 0
        self.grants[(p, addr)] = (d, time.time())
        return d

    async def may_build(self, p, addr):
        """THE ONE WRITE CHECK, for a person's click and an agent's call alike: the title's current holder, or a builder
        whose grant was made by that holder (a sale voids the old owner's grants)."""
        if not addr or not (0 <= p < L.PLOT_MAX):
            return False
        h = await self.holder(p)
        if not h:
            return False
        if h == addr:
            return True
        d = await self.grant(p, addr)
        return bool(d) and d == zkvm_addr_digest(h)

    def take(self, who, n):
        """Rate limit: n cells against a bucket of MAX_CELLS refilling at RATE cells/s (a full call, then ~10 s)."""
        t, at = self.buckets.get(who, [MAX_CELLS, time.time()])
        t = min(MAX_CELLS, t + (time.time() - at) * RATE)
        if n > t:
            self.buckets[who] = [t, time.time()]
            return False
        self.buckets[who] = [t - n, time.time()]
        return True

    async def apply(self, who, cells):
        """Apply [face, u, v, h, block] cells the caller may build on; returns (applied by plot, refused)."""
        if not isinstance(cells, list) or len(cells) > MAX_CELLS:
            return {}, [[None, f"at most {MAX_CELLS} cells per call"]]
        if not self.take(who, len(cells)):
            return {}, [[None, "rate limited — slow down"]]
        applied, refused, ok_plot = {}, [], {}
        for c in cells:
            try:
                face, u, v, h, b = (int(x) for x in c)
            except Exception:
                refused.append([c, "a cell is [face, u, v, h, block]"]); continue
            if not (0 <= face < 6 and 0 <= u < W and 0 <= v < W and 1 <= h < H and 0 <= b < N_BLOCKS) or b in UNBUILDABLE:
                refused.append([c, "out of the world, or not a block you can place"]); continue
            p = plot_of(face, u, v)
            if p not in ok_plot:
                ok_plot[p] = await self.may_build(p, who)
            if not ok_plot[p]:
                refused.append([c, "not your plot — only its owner and the builders they invite build here"]); continue
            fr, fc = (p // FACE_N) % FACE_N, p % FACE_N
            key = (u - fc * PLOT, v - fr * PLOT, h)
            rec = self.plot(p)
            if rec["edits"].get(key) == b:
                continue
            rec["edits"][key] = b          # an edit back to the terrain's own block stays listed: the server does not
            rec["ver"] += 1                # generate terrain, so it cannot tell — the commitment binds it either way
            self.dirty.add(p)
            applied.setdefault(p, []).append([face, u, v, h, b])
        return applied, refused

    # -- identity
    def challenge(self, origin, bind=None):
        self.challenges = {n: c for n, c in self.challenges.items() if time.time() - c["issued"] < CHALLENGE_TTL}
        if len(self.challenges) > 10000:
            raise web.HTTPServiceUnavailable(text="login busy — try again")
        nonce = secrets.token_urlsafe(18)
        self.challenges[nonce] = {"issued": int(time.time()), "origin": origin, "bind": bind}
        return nonce, self.challenges[nonce]["issued"]

    def login(self, address, public_key, alg, signature, nonce, origin, bind=None):
        ch = self.challenges.get(nonce)
        if not ch or ch["origin"] != origin or time.time() - ch["issued"] >= CHALLENGE_TTL:
            raise web.HTTPBadRequest(text="login expired or unknown — start again")
        if ch["bind"] is not None and ch["bind"] != bind:
            raise web.HTTPForbidden(text="finish the login in the browser that started it")
        if not validate_address(address, allow_reserved=False):
            raise web.HTTPBadRequest(text="bad address")
        alg = alg or None
        if not proof_sender(public_key, address, alg=alg):
            raise web.HTTPBadRequest(text="that key does not derive that address")
        msg = blake2b_hash([DOMAIN, origin, address, nonce, ch["issued"]], 32)
        if not sig_verify(signature, public_key, unhex(msg), alg=alg):
            raise web.HTTPUnauthorized(text="signature verification failed")
        self.challenges.pop(nonce, None)                       # single use
        token = secrets.token_urlsafe(32)
        self.sessions[token] = {"address": address, "until": time.time() + SESSION_TTL}
        return token

    def who(self, request):
        tok = request.cookies.get("land_session") or ""
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            tok = auth[7:].strip()
        tok = tok or request.query.get("token", "")
        s = self.sessions.get(tok)
        if not s or s["until"] < time.time():
            return None
        return s["address"]


# ---- the live channel --------------------------------------------------------------------------------------------
class Hub:
    """Every open socket: what it watches (plots) and where its player stands. An applied edit goes to every socket
    watching its plot; positions go to sockets near them (same face, within NEAR blocks)."""
    NEAR = 192

    def __init__(self):
        self.socks = {}                       # ws -> {"who", "watch": set(), "pos": [face,u,v,h,yaw] | None, "id"}

    async def edits(self, applied, by):
        for ws, st in list(self.socks.items()):
            for p, cells in applied.items():
                if p in st["watch"]:
                    try:
                        await ws.send_json({"t": "edit", "plot": p, "cells": cells, "by": by})
                    except Exception:
                        pass

    async def positions(self):
        socks = list(self.socks.items())
        for ws, st in socks:
            me = st["pos"]
            if not me:
                continue
            near = [{"id": o["id"], "who": o["who"], "p": o["pos"]} for w2, o in socks
                    if w2 is not ws and o["pos"] and o["pos"][0] == me[0]
                    and abs(o["pos"][1] - me[1]) < self.NEAR and abs(o["pos"][2] - me[2]) < self.NEAR]
            try:
                await ws.send_json({"t": "players", "list": near})
            except Exception:
                pass


def make_app(world, hub, site_origin, wallet_url, secure_cookies=True):
    async def on_start(app):
        world.http = ClientSession(timeout=ClientTimeout(total=10))
        app["bg"] = [asyncio.ensure_future(_flusher()), asyncio.ensure_future(_mover())]

    async def on_stop(app):
        for t in app.get("bg", []):
            t.cancel()
        world.flush()
        await world.http.close()

    async def _flusher():
        while True:
            await asyncio.sleep(2)
            try:
                world.flush()
            except Exception:
                pass

    async def _mover():
        while True:
            await asyncio.sleep(0.2)
            await hub.positions()

    def plot_json(p, addr, may):
        rec = world.plots.get(p) or {"edits": {}, "ver": 0}
        out = {"plot": p, "ver": rec["ver"], "edits": [[x, z, y, b] for (x, z, y), b in sorted(rec["edits"].items())]}
        if may and p in world.plots:
            out["salt"] = rec["salt"].hex()
            out["commitment"] = commitment(p, rec["salt"], out["edits"])
        return out

    async def challenge(request):
        kind = request.query.get("kind", "agent")
        if kind != "agent":
            raise web.HTTPBadRequest(text="a browser signs in through /land/api/login")
        nonce, issued = world.challenge(AGENT_ORIGIN)
        return web.json_response({"nonce": nonce, "issued": issued, "origin": AGENT_ORIGIN, "domain": DOMAIN})

    async def login(request):
        bind = secrets.token_urlsafe(18)
        nonce, issued = world.challenge(site_origin, bind)
        q = urllib.parse.urlencode({"land_login": "1", "nonce": nonce, "issued": issued, "site": site_origin})
        resp = web.HTTPFound(f"{wallet_url}/?{q}")
        resp.set_cookie("land_login", bind, max_age=CHALLENGE_TTL, httponly=True, secure=secure_cookies, samesite="Lax", path="/")
        return resp

    async def login_callback(request):
        d = await request.post()
        token = world.login(d.get("address", ""), d.get("public_key", ""), d.get("alg", ""), d.get("signature", ""),
                            d.get("nonce", ""), site_origin, bind=request.cookies.get("land_login"))
        resp = web.HTTPFound("/")
        resp.set_cookie("land_session", token, max_age=SESSION_TTL, httponly=True, secure=secure_cookies, samesite="Lax", path="/")
        resp.del_cookie("land_login", path="/")
        return resp

    async def agent_login(request):
        d = await request.json()
        token = world.login(d.get("address", ""), d.get("public_key", ""), d.get("alg"), d.get("signature", ""),
                            d.get("nonce", ""), AGENT_ORIGIN)
        return web.json_response({"token": token, "address": d.get("address"), "expires_in": SESSION_TTL})

    async def logout(request):
        tok = request.cookies.get("land_session")
        world.sessions.pop(tok, None)
        resp = web.json_response({"ok": True})
        resp.del_cookie("land_session", path="/")
        return resp

    async def me(request):
        addr = world.who(request)
        return web.json_response({"address": addr})

    async def plot(request):
        try:
            p = int(request.query["plot"])
        except Exception:
            raise web.HTTPBadRequest(text="?plot=<id>")
        addr = world.who(request)
        may = bool(addr) and await world.may_build(p, addr)
        out = plot_json(p, addr, may)
        out["holder"] = await world.holder(p)
        out["may_build"] = may
        return web.json_response(out)

    async def region(request):
        try:
            face = int(request.query["face"]); u0, v0, u1, v1 = (int(request.query[k]) for k in ("u0", "v0", "u1", "v1"))
        except Exception:
            raise web.HTTPBadRequest(text="?face=&u0=&v0=&u1=&v1=")
        if (u1 - u0) > 4096 or (v1 - v0) > 4096:
            raise web.HTTPBadRequest(text="a region is at most 4096 blocks across")
        out = {}
        for p, rec in world.plots.items():
            f, r, c = plot_coords(p)
            if f == face and u0 <= c * PLOT + PLOT and c * PLOT <= u1 and v0 <= r * PLOT + PLOT and r * PLOT <= v1 and rec["edits"]:
                out[p] = plot_json(p, None, False)
        return web.json_response({"plots": out})

    async def set_cells(request):
        addr = world.who(request)
        if not addr:
            raise web.HTTPUnauthorized(text="sign in first (agents: /land/api/agent_login)")
        d = await request.json()
        applied, refused = await world.apply(addr, d.get("cells"))
        await hub.edits(applied, addr)
        return web.json_response({"applied": sum(len(c) for c in applied.values()), "refused": refused})

    async def ws_handler(request):
        """{t:"watch", plots:[…]} -> {t:"plot", …} for each; {t:"pos", p:[face,u,v,h,yaw]}; {t:"set", cells:[…]} ->
        {t:"set_ok", applied, refused} and {t:"edit"} to every watcher (the sender included, so all agree)."""
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=1 << 20)
        await ws.prepare(request)
        addr = world.who(request)
        st = hub.socks[ws] = {"who": addr, "watch": set(), "pos": None, "id": secrets.token_hex(4)}
        await ws.send_json({"t": "hello", "you": addr, "id": st["id"]})
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    m = json.loads(msg.data)
                except Exception:
                    continue
                t = m.get("t")
                if t == "watch":
                    plots = [int(p) for p in (m.get("plots") or [])[:2048] if isinstance(p, int)]
                    new = set(plots) - st["watch"]
                    st["watch"] = set(plots)
                    for p in new:              # every newly watched plot, empty ones too: the page drops what it cached
                        await ws.send_json(dict(plot_json(p, None, False), t="plot"))
                elif t == "pos":
                    p = m.get("p")
                    if isinstance(p, list) and len(p) == 5 and all(isinstance(x, (int, float)) for x in p):
                        st["pos"] = [int(p[0]), float(p[1]), float(p[2]), float(p[3]), float(p[4])]
                elif t == "set":
                    if not addr:
                        await ws.send_json({"t": "set_ok", "applied": 0, "refused": [[None, "sign in to build"]], "req": m.get("req")})
                        continue
                    applied, refused = await world.apply(addr, m.get("cells"))
                    await ws.send_json({"t": "set_ok", "applied": sum(len(c) for c in applied.values()), "refused": refused, "req": m.get("req")})
                    await hub.edits(applied, addr)
        finally:
            hub.socks.pop(ws, None)
        return ws

    app = web.Application(client_max_size=2 << 20)
    app.on_startup.append(on_start)
    app.on_cleanup.append(on_stop)
    app.add_routes([
        web.get("/land/api/challenge", challenge),
        web.get("/land/api/login", login),
        web.post("/land/api/login_callback", login_callback),
        web.post("/land/api/agent_login", agent_login),
        web.post("/land/api/logout", logout),
        web.get("/land/api/me", me),
        web.get("/land/api/plot", plot),
        web.get("/land/api/region", region),
        web.post("/land/api/set", set_cells),
        web.get("/land/ws", ws_handler),
    ])
    return app


def main():
    ap = argparse.ArgumentParser(description="NADO Land world server")
    ap.add_argument("--data", required=True, help="directory of plot files (persistent)")
    ap.add_argument("--port", type=int, default=9176)
    ap.add_argument("--exec", default="http://127.0.0.1:9273")
    ap.add_argument("--site", default="https://land.nadochain.com")
    ap.add_argument("--wallet", default="https://get.nadochain.com")
    a = ap.parse_args()
    src = open(os.path.join(REPO, "static", "land.js")).read()
    cid = (src.split('const CID = "', 1)[1].split('"', 1)[0]) if 'const CID = "' in src else ""
    world = World(a.data, a.exec, cid)
    web.run_app(make_app(world, Hub(), a.site.rstrip("/"), a.wallet.rstrip("/")), host="127.0.0.1", port=a.port, access_log=None)


if __name__ == "__main__":
    main()
