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
N_BLOCKS = 40                     # static/land-world.js BLOCKS.length (tests/test_the_land_planet_… checks the two agree)
DOOR = 37                         # static/land-world.js B.door: a piece that swings open and shut ("door" op)
TREE_WOOD = {7, 31}                # static/land-world.js TREE_WOOD (log, birchlog): cutting one fells its tree above
UNBUILDABLE = {5, 30}             # water, bedrock: never placed (no item in land-recipes.json places them either)
MAX_CELLS = 4096                  # per /set call or ws "set"
RATE = 400                        # cells per second per caller, refilling a bucket that holds one full call (MAX_CELLS)
PLANET = 0
WORK_CAP = 10.0                   # seconds of breaking work a caller can bank (refills at 1 s/s)
RULES = json.load(open(os.path.join(REPO, "static", "land-recipes.json")))   # the page reads the same file

# ---- the plot's commitment (land-world.js commitmentBytes, byte for byte) ------------------------------------------
def canonical_edits(edits):
    m = {}
    for x, z, y, b in edits:
        if not (0 <= x < PLOT and 0 <= z < PLOT and 0 <= y < H and 0 <= b < N_BLOCKS):
            raise ValueError("bad edit")
        m[(y * PLOT + z) * PLOT + x] = b
    return [(k % PLOT, (k // PLOT) % PLOT, k // (PLOT * PLOT), m[k]) for k in sorted(m)]


CM, PLOT_CM, H_CM = 100, PLOT * 100, H * 100      # static/land-world.js CM, PLOT_CM, H_CM
BLOCK_CM3 = CM ** 3                                # one gathered block of material: 1,000,000 cm³
MAX_BOXES = 20000                                  # pieces on one plot
MAX_BOX_OPS = 1024                                 # pieces added or removed per call


def box_ok(b):
    """land-world.js boxOk: [x, z, y, w, d, h, m] in whole centimetres inside the plot, positive size, a solid material."""
    if not isinstance(b, (list, tuple)) or len(b) != 7 or not all(isinstance(v, int) and not isinstance(v, bool) for v in b):
        return False
    x, z, y, w, d, h, m = b
    return (x >= 0 and z >= 0 and y >= 0 and w >= 1 and d >= 1 and h >= 1 and x + w <= PLOT_CM and z + d <= PLOT_CM
            and y + h <= H_CM and 0 < m < N_BLOCKS and m != 5)


def boxes_overlap(a, b):
    return a[0] < b[0] + b[3] and b[0] < a[0] + a[3] and a[1] < b[1] + b[4] and b[1] < a[1] + a[4] and a[2] < b[2] + b[5] and b[2] < a[2] + a[5]


def commitment_bytes(plot, salt, edits, boxes=()):
    """land-world.js commitmentBytes, byte for byte (v2: the ground's cell edits, then the built boxes)."""
    if len(salt) != 32:
        raise ValueError("salt must be 32 bytes")
    ce, cb = canonical_edits(edits), sorted({tuple(b) for b in boxes})
    if not all(box_ok(list(b)) for b in cb):
        raise ValueError("bad box")
    out = bytearray(b"nado-land-plot-v2") + plot.to_bytes(4, "big") + salt + len(ce).to_bytes(4, "big")
    for x, z, y, b in ce:
        out += bytes([x, z, y >> 8, y & 255, b])
    out += len(cb).to_bytes(4, "big")
    for x, z, y, w, d, h, m in cb:
        out += b"".join(v.to_bytes(2, "big") for v in (x, z, y, w, d, h)) + bytes([m])
    return bytes(out)


def commitment(plot, salt, edits, boxes=()):
    n = int.from_bytes(hashlib.sha256(commitment_bytes(plot, salt, edits, boxes)).digest(), "big")
    return str(n or 1)


def box_vol(b):
    return b[3] * b[4] * b[5]


def buckets_of(b):
    """The 1 m buckets a piece touches: the spatial index that keeps an overlap check local instead of a scan of every
    piece on the plot (20,000 x 1,024 per call would be 20 million comparisons)."""
    return [(i, j, k) for i in range(b[0] // CM, (b[0] + b[3] - 1) // CM + 1)
            for j in range(b[1] // CM, (b[1] + b[4] - 1) // CM + 1)
            for k in range(b[2] // CM, (b[2] + b[5] - 1) // CM + 1)]


class BoxIndex:
    """Pieces of one plot bucketed by the 1 m cells they touch. A piece spanning many metres sits in every bucket it
    touches, so a lookup near any part of it finds it."""
    def __init__(self, boxes):
        self.cells = {}
        for b in boxes:
            self.add(b)

    def add(self, b):
        t = tuple(b)
        for c in buckets_of(b):
            self.cells.setdefault(c, set()).add(t)

    def remove(self, b):
        t = tuple(b)
        for c in buckets_of(b):
            s = self.cells.get(c)
            if s:
                s.discard(t)
                if not s:
                    del self.cells[c]

    def overlaps(self, b):
        seen = set()
        for c in buckets_of(b):
            for o in self.cells.get(c, ()):
                if o not in seen:
                    seen.add(o)
                    if boxes_overlap(b, o):
                        return True
        return False


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
        self.workb = {}                       # caller -> [seconds of work banked, at]
        self.players, self.pdirty = {}, set()  # address -> {"items", "tools", "stations"}; who changed since the flush
        os.makedirs(os.path.join(self.dir, "players"), exist_ok=True)
        try:
            self.offers = json.load(open(os.path.join(self.dir, "offers.json")))
        except Exception:
            self.offers = {}
        self.odirty = False
        self.http = self.oracle = None
        for f in os.listdir(self.dir):
            if f.endswith(".json") and f[:-5].isdigit():
                try:
                    d = json.load(open(os.path.join(self.dir, f)))
                    self.plots[int(f[:-5])] = {"edits": {tuple(map(int, k.split(":"))): b for k, b in d["edits"].items()},
                                               "salt": bytes.fromhex(d["salt"]), "ver": int(d.get("ver", 0)),
                                               "exp": {tuple(map(int, k.split(":"))): t for k, t in d.get("exp", {}).items()},
                                               "boxes": [list(b) for b in d.get("boxes", [])]}
                except Exception:
                    pass

    # -- persistence
    def plot(self, p):
        rec = self.plots.get(p)
        if rec is None:
            rec = self.plots[p] = {"edits": {}, "salt": secrets.token_bytes(32), "ver": 0, "boxes": []}
        return rec

    def flush(self):
        for p in list(self.dirty):
            rec = self.plots[p]
            body = {"edits": {f"{x}:{z}:{y}": b for (x, z, y), b in rec["edits"].items()}, "salt": rec["salt"].hex(), "ver": rec["ver"],
                    "exp": {f"{x}:{z}:{y}": t for (x, z, y), t in (rec.get("exp") or {}).items()}, "boxes": rec.get("boxes", [])}
            self._write(f"{p}.json", body)
            self.dirty.discard(p)
        for a in list(self.pdirty):
            self._write(os.path.join("players", a + ".json"), self.players[a])
            self.pdirty.discard(a)
        if self.odirty:
            self._write("offers.json", self.offers)
            self.odirty = False

    def _write(self, rel, body):
        path = os.path.join(self.dir, rel)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
        with os.fdopen(fd, "w") as f:
            json.dump(body, f, separators=(",", ":"))
        os.replace(tmp, path)                      # a reader (or a crash) never sees half a file

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

    # -- the untouched planet, from the browsers' own generator (scripts/land_terrain.mjs)
    async def start_oracle(self):
        self.oracle = await asyncio.create_subprocess_exec("node", os.path.join(REPO, "scripts", "land_terrain.mjs"),
                                                           stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
        self.oracle_lock = asyncio.Lock()

    async def fell_cells(self, face, u, v, h):
        """The untouched planet's cells of the tree cut at [face, u, v, h] that stand above the cut (land_terrain.mjs fell)."""
        async with self.oracle_lock:
            self.oracle.stdin.write((json.dumps({"fell": [face, u, v, h]}) + "\n").encode())
            await self.oracle.stdin.drain()
            r = json.loads(await self.oracle.stdout.readline())
        if "error" in r:
            raise RuntimeError("terrain oracle: " + r["error"])
        return r["cells"]

    async def terrain(self, cells):
        """Block ids of the untouched planet at [face, u, v, h] cells (one round trip for the lot)."""
        if not cells:
            return []
        async with self.oracle_lock:
            self.oracle.stdin.write((json.dumps({"cells": cells}) + "\n").encode())
            await self.oracle.stdin.drain()
            r = json.loads(await self.oracle.stdout.readline())
        if "error" in r:
            raise RuntimeError("terrain oracle: " + r["error"])
        return r["blocks"]

    # -- players: inventory, tools, stations, and the work their hands (or tools) can do per second
    def player(self, addr):
        pl = self.players.get(addr)
        if pl is None:
            path = os.path.join(self.dir, "players", addr + ".json")
            try:
                pl = json.load(open(path))
            except Exception:
                pl = {"items": {}, "tools": [], "stations": []}
            pl.setdefault("items", {}); pl.setdefault("tools", []); pl.setdefault("stations", []); pl.setdefault("vol", {})
            self.players[addr] = pl
        return pl

    def inv_json(self, addr):
        pl = self.player(addr)
        return {"items": {k: n for k, n in sorted(pl["items"].items()) if n > 0}, "tools": sorted(pl["tools"]),
                "stations": sorted(pl["stations"]), "vol": {k: v for k, v in sorted(pl["vol"].items()) if v > 0}}

    def _has(self, pl, need):
        """A station by id; a tool by id OR by class — a recipe "with an axe" takes an iron axe as well as a stone one."""
        return need in pl["stations"] or self._has_class(pl, need)

    @staticmethod
    def _has_class(pl, cls):
        return any(t == cls or RULES["tools"].get(t, {}).get("class") == cls for t in pl["tools"])

    @staticmethod
    def _speed(pl, cls):
        """The best speed among the caller's tools of class `cls` (an iron axe outworks a stone one); 1 by hand."""
        return max([RULES["tools"][t]["speed"] for t in pl["tools"] if t in RULES["tools"] and RULES["tools"][t].get("class") == cls] or [1])

    def work(self, who, seconds):
        """Breaking takes time: a bucket of WORK_CAP seconds refilling at 1 s/s. An agent works no faster than a hand."""
        t, at = self.workb.get(who, [WORK_CAP, time.time()])
        t = min(WORK_CAP, t + (time.time() - at))
        if seconds > t:
            self.workb[who] = [t, time.time()]
            return False
        self.workb[who] = [t - seconds, time.time()]
        return True

    async def apply(self, who, cells):
        """Apply [face, u, v, h, block] cells: block 0 BREAKS (gathering: its yield goes to the caller's inventory),
        any other id PLACES one item from the inventory. Returns (applied by plot, refused, inventory changed)."""
        if not isinstance(cells, list) or len(cells) > MAX_CELLS:
            return {}, [[None, f"at most {MAX_CELLS} cells per call"]], False
        if not self.take(who, len(cells)):
            return {}, [[None, "rate limited — slow down"]], False
        parsed, refused = [], []
        for c in cells:
            try:
                face, u, v, h, b = (int(x) for x in c)
            except Exception:
                refused.append([c, "a cell is [face, u, v, h, block]"]); continue
            if not (0 <= face < 6 and 0 <= u < W and 0 <= v < W and 1 <= h < H and 0 <= b < N_BLOCKS) or b in UNBUILDABLE:
                refused.append([c, "out of the world, or not a block you can place"]); continue
            parsed.append((face, u, v, h, b, c))
        # what is there now: an edit, else the untouched planet
        keys = []
        for face, u, v, h, b, c in parsed:
            p = plot_of(face, u, v)
            fr, fc = (p // FACE_N) % FACE_N, p % FACE_N
            keys.append((p, (u - fc * PLOT, v - fr * PLOT, h)))
        # the untouched planet for every cell without an edit at the start, by index (a cell listed twice in one batch
        # reads the first one's edit the second time, never another cell's terrain)
        idx = [i for i, ((f, u, v, h, b, c), (p, k)) in enumerate(zip(parsed, keys)) if k not in (self.plots.get(p) or {}).get("edits", {})]
        base = dict(zip(idx, await self.terrain([list(parsed[i][:4]) for i in idx]))) if idx else {}
        pl, places = self.player(who), {it["places"]: name for name, it in RULES["items"].items() if "places" in it}
        applied, titled_ok, changed = {}, {}, False
        for i, ((face, u, v, h, b, c), (p, k)) in enumerate(zip(parsed, keys)):
            rec = self.plots.get(p)
            cur = rec["edits"][k] if rec and k in rec["edits"] else base[i]
            if p not in titled_ok:
                titled_ok[p] = (await self.holder(p)) is not None, await self.may_build(p, who)
            titled, may = titled_ok[p]
            if b == 0:                                              # ---- break: gather
                rule = RULES["breaking"].get(str(cur))
                if not rule:
                    refused.append([c, "nothing here that can be gathered"]); continue
                if titled and not may:
                    refused.append([c, "not your plot — only its owner and the builders they invite take from it"]); continue
                if rule.get("needs") and not self._has_class(pl, rule["needs"]):
                    refused.append([c, f"needs a {RULES['tools'][rule['needs']]['name'].lower()}"]); continue
                speed = self._speed(pl, rule.get("class"))
                if not self.work(who, rule["hard"] / speed):
                    refused.append([c, "too fast — breaking takes time (a better tool is quicker)"]); continue
                for item, n in rule["yields"]:
                    pl["items"][item] = pl["items"].get(item, 0) + n
                if rule.get("bonus") and (face * 7919 + u * 31 + v * 17 + h) % rule["bonus"][1] == 0:
                    pl["items"][rule["bonus"][0]] = pl["items"].get(rule["bonus"][0], 0) + 1
                changed = True
                rec = self.plot(p)
                rec["edits"][k] = 0
                if not titled:                                     # the commons regrows: the cell comes back later
                    rec.setdefault("exp", {})[k] = time.time() + RULES["wilderness_regrow_s"]
                if cur in TREE_WOOD:
                    # FELLING ("can we add some basic gravity", operator 2026-11-06): a cut trunk brings down everything
                    # of its tree above the cut — logs and crown — instead of leaving it floating. Only cells still as
                    # the planet made them come down (an edit is someone's), each paying what breaking it would; a tree
                    # lies inside its own plot (land-world roots keep 2 columns from an edge), so the plot is this one.
                    for ff, fu, fv, fh, fb in await self.fell_cells(face, u, v, h):
                        fk = (fu - (p % FACE_N) * PLOT, fv - ((p // FACE_N) % FACE_N) * PLOT, fh)
                        if fk in rec["edits"]:
                            continue
                        for item, n in (RULES["breaking"].get(str(fb)) or {"yields": []})["yields"]:
                            pl["items"][item] = pl["items"].get(item, 0) + n
                        rec["edits"][fk] = 0
                        if not titled:
                            rec.setdefault("exp", {})[fk] = time.time() + RULES["wilderness_regrow_s"]
                        applied.setdefault(p, []).append([ff, fu, fv, fh, 0])
            else:                                                   # ---- place: spend one item
                # "you can build anywhere unless it is owned" (operator, 2026-11-06): unowned land is open to everyone
                if titled and not may:
                    refused.append([c, "not your plot — only its owner and the builders they invite build here"]); continue
                if cur not in (0, 5):
                    refused.append([c, "something is already there"]); continue
                item = places.get(b)
                if not item or pl["items"].get(item, 0) < 1:
                    refused.append([c, f"you have no {RULES['items'][item]['name'].lower() if item else 'such block'} to place"]); continue
                pl["items"][item] -= 1
                changed = True
                rec = self.plot(p)
                rec["edits"][k] = b
                rec.get("exp", {}).pop(k, None)
            rec["ver"] += 1
            self.dirty.add(p)
            self.pdirty.add(who)
            applied.setdefault(p, []).append([face, u, v, h, rec["edits"][k]])
        return applied, refused, changed

    def regrow(self):
        """Wilderness cells whose time is up go back to the untouched planet: {plot: [[face, u, v, h], ...]}."""
        out, now = {}, time.time()
        for p, rec in self.plots.items():
            exp = rec.get("exp")
            if not exp:
                continue
            face, row, col = plot_coords(p)
            for k in [k for k, t in exp.items() if t <= now]:
                exp.pop(k); rec["edits"].pop(k, None); rec["ver"] += 1; self.dirty.add(p)
                out.setdefault(p, []).append([face, col * PLOT + k[0], row * PLOT + k[1], k[2]])
        return out

    # -- built pieces: boxes at 1 cm, paid for by volume
    def _spend(self, pl, item, cm3):
        """Take `cm3` of `item` from the opened stock, opening whole blocks of it as needed; False if there is not enough."""
        have = pl["vol"].get(item, 0) + pl["items"].get(item, 0) * BLOCK_CM3
        if have < cm3:
            return False
        need = max(0, cm3 - pl["vol"].get(item, 0))
        opened = -(-need // BLOCK_CM3)
        pl["items"][item] = pl["items"].get(item, 0) - opened
        pl["vol"][item] = pl["vol"].get(item, 0) + opened * BLOCK_CM3 - cm3
        return True

    def _refund(self, pl, item, cm3):
        v = pl["vol"].get(item, 0) + cm3
        pl["items"][item] = pl["items"].get(item, 0) + v // BLOCK_CM3
        pl["vol"][item] = v % BLOCK_CM3

    async def boxes(self, who, p, add, remove):
        """Add and remove built pieces on plot `p`; returns (added, removed, refused). Removing goes first, so a piece
        can be replaced in one call. Only where the caller may build; added pieces stay inside the plot, overlap nothing
        and are paid for by volume (one block of material is 1 m³); a removed piece is refunded by its volume and takes
        work time in proportion to its size."""
        add, remove = add or [], remove or []
        if not isinstance(p, int) or not isinstance(add, list) or not isinstance(remove, list) or len(add) + len(remove) > MAX_BOX_OPS:
            return [], [], [[None, f"at most {MAX_BOX_OPS} pieces per call"]]
        # anyone builds on unowned land; an owned plot only by its holder and the builders they invited
        if (await self.holder(p)) is not None and not await self.may_build(p, who):
            return [], [], [[None, "not your plot — only its owner and the builders they invite build here"]]
        places = {it["places"]: name for name, it in RULES["items"].items() if "places" in it}
        pl, rec = self.player(who), self.plot(p)
        rec.setdefault("boxes", [])
        if "index" not in rec:
            rec["index"] = BoxIndex(rec["boxes"])
        idx = rec["index"]
        added, removed, refused = [], [], []
        for b in remove:
            b = list(b) if isinstance(b, (list, tuple)) else b
            if b not in rec["boxes"]:
                refused.append([b, "no such piece here"]); continue
            rule = RULES["breaking"].get(str(b[6])) or {"hard": 1.0}
            unit = RULES["items"][places[b[6]]].get("unit")
            speed = self._speed(pl, rule.get("class"))
            if not self.work(who, max(0.05, rule["hard"] * (1 if unit else box_vol(b) / BLOCK_CM3) / speed)):
                refused.append([b, "too fast — taking a piece down takes time"]); continue
            rec["boxes"].remove(b)
            idx.remove(b)
            if unit:                                                # a door comes back as the door it was
                pl["items"][places[b[6]]] = pl["items"].get(places[b[6]], 0) + 1
            else:
                self._refund(pl, places[b[6]], box_vol(b))
            removed.append(b)
        for b in add:
            b = list(b) if isinstance(b, (list, tuple)) else b
            if not box_ok(b) or b[6] not in places:
                refused.append([b, "a piece is [x, z, y, w, d, h, material] in whole cm inside the plot, of a material you can place"]); continue
            if len(rec["boxes"]) >= MAX_BOXES:
                refused.append([b, f"a plot holds at most {MAX_BOXES} pieces"]); continue
            if idx.overlaps(b):
                refused.append([b, "it would overlap another piece"]); continue
            # UNIT ITEMS (a door): made whole, placed whole at their own size (either way round), one per piece
            unit = RULES["items"][places[b[6]]].get("unit")
            if unit:
                if sorted(b[3:5]) != sorted(unit[:2]) or b[5] != unit[2]:
                    refused.append([b, f"a {RULES['items'][places[b[6]]]['name'].lower()} is {unit[0]} x {unit[1]} x {unit[2]} cm"]); continue
                if pl["items"].get(places[b[6]], 0) < 1:
                    refused.append([b, f"you have no {RULES['items'][places[b[6]]]['name'].lower()}"]); continue
                pl["items"][places[b[6]]] -= 1
            elif not self._spend(pl, places[b[6]], box_vol(b)):
                refused.append([b, f"not enough {RULES['items'][places[b[6]]]['name'].lower()} (it takes {box_vol(b) / BLOCK_CM3:.3f} of a block)"]); continue
            rec["boxes"].append(b)
            idx.add(b)
            added.append(b)
        if added or removed:
            rec["ver"] += 1
            self.dirty.add(p); self.pdirty.add(who)
        return added, removed, refused

    async def door(self, who, p, b):
        """Open or close door `b` on plot `p`: it swings a quarter turn on its hinge (the corner at its x, z), i.e. its width
        and depth swap. Anyone signed in may (a lock is for later); refused if the swung door would hit another piece.
        Returns (new box, removed box, error)."""
        rec = self.plots.get(p)
        b = list(b) if isinstance(b, (list, tuple)) else b
        if not rec or not isinstance(b, list) or b not in rec.get("boxes", []):
            return None, None, "no such door here"
        if b[6] != DOOR:
            return None, None, "that is not a door"
        nb = [b[0], b[1], b[2], b[4], b[3], b[5], b[6]]
        if not box_ok(nb):
            return None, None, "no room to swing it"
        if "index" not in rec:
            rec["index"] = BoxIndex(rec["boxes"])
        idx = rec["index"]
        idx.remove(b)
        if idx.overlaps(nb):
            idx.add(b)
            return None, None, "no room to swing it"
        rec["boxes"].remove(b); rec["boxes"].append(nb); idx.add(nb)
        rec["ver"] += 1
        self.dirty.add(p)
        return nb, b, None

    # -- crafting
    def craft(self, who, rid, times=1):
        r = next((x for x in RULES["recipes"] if x["id"] == rid), None)
        if not r or not isinstance(times, int) or not 1 <= times <= 64:
            return "no such recipe"
        pl = self.player(who)
        for need in r.get("with", []):
            if not self._has(pl, need):
                return f"needs a {(RULES['tools'].get(need) or RULES['stations'].get(need))['name'].lower()}"
        for item, n in r["uses"]:
            if pl["items"].get(item, 0) < n * times:
                return f"needs {n * times} {RULES['items'][item]['name'].lower()}"
        for item, n in r["uses"]:
            pl["items"][item] -= n * times
        for item, n in r["makes"]:
            if item in RULES["tools"]:
                if item not in pl["tools"]:
                    pl["tools"].append(item)
            elif item in RULES["stations"]:
                if item not in pl["stations"]:
                    pl["stations"].append(item)
            else:
                pl["items"][item] = pl["items"].get(item, 0) + n * times
        self.pdirty.add(who)
        return None

    # -- trading: a gift, or an offer anyone may take (both sides move at once, or neither)
    def _bag(self, d):
        if not isinstance(d, dict) or not d or len(d) > 16:
            return None
        out = {}
        for k, n in d.items():
            if k not in RULES["items"] or not isinstance(n, int) or not 1 <= n <= 10 ** 6:
                return None
            out[k] = n
        return out

    def give(self, who, to, items):
        bag = self._bag(items)
        if not bag:
            return "name the items and counts to give"
        if not validate_address(to, allow_reserved=False) or to == who:
            return "that is not another player's address"
        pl = self.player(who)
        if any(pl["items"].get(k, 0) < n for k, n in bag.items()):
            return "you do not have that much"
        dst = self.player(to)
        for k, n in bag.items():
            pl["items"][k] -= n; dst["items"][k] = dst["items"].get(k, 0) + n
        self.pdirty.update((who, to))
        return None

    def offer(self, who, give, want):
        g, w = self._bag(give), self._bag(want)
        if not g or not w:
            return None, "an offer gives some items and wants some items"
        pl = self.player(who)
        if any(pl["items"].get(k, 0) < n for k, n in g.items()):
            return None, "you do not have what you offer"
        if sum(1 for o in self.offers.values() if o["by"] == who) >= 50:
            return None, "at most 50 open offers each"
        for k, n in g.items():                                     # escrowed until taken or cancelled
            pl["items"][k] -= n
        oid = secrets.token_hex(6)
        self.offers[oid] = {"id": oid, "by": who, "give": g, "want": w, "at": int(time.time())}
        self.pdirty.add(who); self.odirty = True
        return oid, None

    def accept(self, who, oid):
        o = self.offers.get(oid)
        if not o:
            return "that offer is gone"
        if o["by"] == who:
            return "that is your own offer"
        pl, maker = self.player(who), self.player(o["by"])
        if any(pl["items"].get(k, 0) < n for k, n in o["want"].items()):
            return "you do not have what it asks for"
        for k, n in o["want"].items():
            pl["items"][k] -= n; maker["items"][k] = maker["items"].get(k, 0) + n
        for k, n in o["give"].items():
            pl["items"][k] = pl["items"].get(k, 0) + n
        del self.offers[oid]
        self.pdirty.update((who, o["by"])); self.odirty = True
        return None

    def cancel(self, who, oid):
        o = self.offers.get(oid)
        if not o or o["by"] != who:
            return "not an offer of yours"
        pl = self.player(who)
        for k, n in o["give"].items():
            pl["items"][k] = pl["items"].get(k, 0) + n
        del self.offers[oid]
        self.pdirty.add(who); self.odirty = True
        return None

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

    async def boxes(self, p, added, removed, by):
        """Pieces added or taken down on plot `p`: every socket watching it, the builder's included."""
        if not (added or removed):
            return
        for ws, st in list(self.socks.items()):
            if p in st["watch"]:
                try:
                    await ws.send_json({"t": "boxes", "plot": p, "add": added, "remove": removed, "by": by})
                except Exception:
                    pass

    async def reverts(self, back):
        """Wilderness cells that regrew: every watcher drops its override and shows the untouched planet again."""
        for ws, st in list(self.socks.items()):
            for p, cells in back.items():
                if p in st["watch"]:
                    try:
                        await ws.send_json({"t": "revert", "plot": p, "cells": cells})
                    except Exception:
                        pass

    async def inv(self, world, addr):
        """A player's inventory changed: tell every socket that player has open."""
        if not addr:
            return
        for ws, st in list(self.socks.items()):
            if st["who"] == addr:
                try:
                    await ws.send_json(dict(world.inv_json(addr), t="inv"))
                except Exception:
                    pass

    async def offers(self, world):
        snap = {"t": "offers", "offers": sorted(world.offers.values(), key=lambda o: -o["at"])[:500]}
        for ws in list(self.socks):
            try:
                await ws.send_json(snap)
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
        await world.start_oracle()
        app["bg"] = [asyncio.ensure_future(_flusher()), asyncio.ensure_future(_mover()), asyncio.ensure_future(_regrower())]

    async def on_stop(app):
        for t in app.get("bg", []):
            t.cancel()
        world.flush()
        await world.http.close()
        if world.oracle and world.oracle.returncode is None:
            world.oracle.kill()
            await world.oracle.wait()                         # reaped here, not by a finalizer after the loop is gone

    async def _regrower():
        while True:
            await asyncio.sleep(5)
            try:
                back = world.regrow()
                if back:
                    await hub.reverts(back)
            except Exception:
                pass

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
        out = {"plot": p, "ver": rec["ver"], "edits": [[x, z, y, b] for (x, z, y), b in sorted(rec["edits"].items())],
               "boxes": sorted(rec.get("boxes", []))}
        if may and p in world.plots:
            out["salt"] = rec["salt"].hex()
            out["commitment"] = commitment(p, rec["salt"], out["edits"], out["boxes"])
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
            if f == face and u0 <= c * PLOT + PLOT and c * PLOT <= u1 and v0 <= r * PLOT + PLOT and r * PLOT <= v1 and (rec["edits"] or rec.get("boxes")):
                out[p] = plot_json(p, None, False)
        return web.json_response({"plots": out})

    async def set_cells(request):
        addr = world.who(request)
        if not addr:
            raise web.HTTPUnauthorized(text="sign in first (agents: /land/api/agent_login)")
        d = await request.json()
        applied, refused, changed = await world.apply(addr, d.get("cells"))
        await hub.edits(applied, addr)
        if changed:
            await hub.inv(world, addr)
        return web.json_response({"applied": sum(len(c) for c in applied.values()), "refused": refused, "inventory": world.inv_json(addr)})

    async def boxes(request):
        addr = world.who(request)
        if not addr:
            raise web.HTTPUnauthorized(text="sign in first (agents: /land/api/agent_login)")
        d = await request.json()
        added, removed, refused = await world.boxes(addr, d.get("plot"), d.get("add"), d.get("remove"))
        await hub.boxes(d.get("plot"), added, removed, addr)
        if added or removed:
            await hub.inv(world, addr)
        return web.json_response({"added": len(added), "removed": len(removed), "refused": refused, "inventory": world.inv_json(addr)})

    def need_addr(request):
        addr = world.who(request)
        if not addr:
            raise web.HTTPUnauthorized(text="sign in first (agents: /land/api/agent_login)")
        return addr

    async def inventory(request):
        return web.json_response(world.inv_json(need_addr(request)))

    async def craft(request):
        addr, d = need_addr(request), await request.json()
        err = world.craft(addr, d.get("recipe"), d.get("times", 1))
        if not err:
            await hub.inv(world, addr)
        return web.json_response({"ok": not err, "error": err, "inventory": world.inv_json(addr)})

    async def give(request):
        addr, d = need_addr(request), await request.json()
        err = world.give(addr, d.get("to", ""), d.get("items"))
        if not err:
            await hub.inv(world, addr); await hub.inv(world, d.get("to"))
        return web.json_response({"ok": not err, "error": err, "inventory": world.inv_json(addr)})

    async def offers(request):
        return web.json_response({"offers": sorted(world.offers.values(), key=lambda o: -o["at"])[:500]})

    async def offer(request):
        addr, d = need_addr(request), await request.json()
        oid, err = world.offer(addr, d.get("give"), d.get("want"))
        if not err:
            await hub.inv(world, addr); await hub.offers(world)
        return web.json_response({"ok": not err, "id": oid, "error": err, "inventory": world.inv_json(addr)})

    async def accept(request):
        addr, d = need_addr(request), await request.json()
        maker = (world.offers.get(d.get("id")) or {}).get("by")
        err = world.accept(addr, d.get("id"))
        if not err:
            await hub.inv(world, addr); await hub.inv(world, maker); await hub.offers(world)
        return web.json_response({"ok": not err, "error": err, "inventory": world.inv_json(addr)})

    async def cancel_offer(request):
        addr, d = need_addr(request), await request.json()
        err = world.cancel(addr, d.get("id"))
        if not err:
            await hub.inv(world, addr); await hub.offers(world)
        return web.json_response({"ok": not err, "error": err, "inventory": world.inv_json(addr)})

    async def ws_handler(request):
        """{t:"watch", plots:[…]} -> {t:"plot", …} for each; {t:"pos", p:[face,u,v,h,yaw]}; {t:"set", cells:[…]} ->
        {t:"set_ok", applied, refused} and {t:"edit"} to every watcher (the sender included, so all agree)."""
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=1 << 20)
        await ws.prepare(request)
        addr = world.who(request)
        st = hub.socks[ws] = {"who": addr, "watch": set(), "pos": None, "id": secrets.token_hex(4)}
        await ws.send_json({"t": "hello", "you": addr, "id": st["id"]})
        if addr:
            await ws.send_json(dict(world.inv_json(addr), t="inv"))
        await ws.send_json({"t": "offers", "offers": sorted(world.offers.values(), key=lambda o: -o["at"])[:500]})
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
                    applied, refused, changed = await world.apply(addr, m.get("cells"))
                    await ws.send_json({"t": "set_ok", "applied": sum(len(c) for c in applied.values()), "refused": refused, "req": m.get("req")})
                    await hub.edits(applied, addr)
                    if changed:
                        await hub.inv(world, addr)
                elif t == "boxes":
                    if not addr:
                        await ws.send_json({"t": "boxes_ok", "req": m.get("req"), "added": 0, "removed": 0, "refused": [[None, "sign in to build"]]})
                        continue
                    added, removed, refused = await world.boxes(addr, m.get("plot"), m.get("add"), m.get("remove"))
                    await ws.send_json({"t": "boxes_ok", "req": m.get("req"), "plot": m.get("plot"), "added": len(added), "removed": len(removed), "refused": refused})
                    await hub.boxes(m.get("plot"), added, removed, addr)
                    if added or removed:
                        await hub.inv(world, addr)
                elif t == "door":
                    if not addr:
                        await ws.send_json({"t": "done", "req": m.get("req"), "error": "sign in first"})
                        continue
                    nb, ob, err = await world.door(addr, m.get("plot"), m.get("box"))
                    await ws.send_json({"t": "done", "req": m.get("req"), "error": err})
                    if not err:
                        await hub.boxes(m.get("plot"), [nb], [ob], addr)
                elif t in ("craft", "give", "offer", "accept", "cancel_offer"):
                    if not addr:
                        await ws.send_json({"t": "done", "req": m.get("req"), "error": "sign in first"})
                        continue
                    other = (world.offers.get(m.get("id")) or {}).get("by") if t == "accept" else m.get("to") if t == "give" else None
                    err = (world.craft(addr, m.get("recipe"), m.get("times", 1)) if t == "craft"
                           else world.give(addr, m.get("to", ""), m.get("items")) if t == "give"
                           else world.offer(addr, m.get("give"), m.get("want"))[1] if t == "offer"
                           else world.accept(addr, m.get("id")) if t == "accept" else world.cancel(addr, m.get("id")))
                    await ws.send_json({"t": "done", "req": m.get("req"), "error": err})
                    if not err:
                        await hub.inv(world, addr)
                        if other:
                            await hub.inv(world, other)
                        if t in ("offer", "accept", "cancel_offer"):
                            await hub.offers(world)
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
        web.post("/land/api/boxes", boxes),
        web.get("/land/api/inventory", inventory),
        web.post("/land/api/craft", craft),
        web.post("/land/api/give", give),
        web.get("/land/api/offers", offers),
        web.post("/land/api/offer", offer),
        web.post("/land/api/accept", accept),
        web.post("/land/api/cancel_offer", cancel_offer),
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
