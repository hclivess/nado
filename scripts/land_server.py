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
  GET  /land/api/card?plot=                     -> the plot's listing card: size, place, biome, ground, trees, its title
                                                   and photo (any origin; a plot without a photo is queued for one)
  GET  /land/api/shot?plot=                     -> its aerial photo, image/jpeg (any origin)
  POST /land/api/set {cells: [[face, u, v, h, block], ...]}   -> {applied, refused: [[cell, reason], ...]}
  GET  /land/ws                                 -> the live channel (see _ws)
Auth on the API: the land_session cookie (browser) or `Authorization: Bearer <token>` (agent).
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-land-")   # BEFORE any node import (CLAUDE.md rule 4); data is --data
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)   # and gone after (a start
# and every test that imports this left one in /tmp: 640 of them by 2026-11-08)
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import argparse, asyncio, hashlib, json, math, random, secrets, shutil, time, urllib.parse

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
sid = lambda token: hashlib.blake2b(token.encode(), digest_size=32).hexdigest()   # a session's name on disk (World.sessions)
FACE_N, PLOT, W, H = L.FACE_N, L.PLOT, L.FACE_N * L.PLOT, 256
N_BLOCKS = 75                     # static/land-world.js BLOCKS.length (tests/test_the_land_planet_… checks the two agree)
DOOR = 37                         # static/land-world.js B.door: a piece that swings open and shut ("door" op)
THRUSTER, SEAT = 65, 66           # static/land-world.js B.thruster, B.pilotseat: a craft's working parts (FLIGHT, #147)
SMELTER, ASSEMBLER, GENERATOR = 67, 68, 69   # static/land-world.js: FACTORIES (#148) — machines and their power
CHEST = 54                        # static/land-world.js B.chest: a piece that keeps items on its plot ("chest" op, #114)
CHEST_MAX = 2000                  # items one chest holds
TREE_WOOD = {7, 31}                # static/land-world.js TREE_WOOD (log, birchlog): cutting one fells its tree above
TREE_LEAVES = {8, 32, 33}         # static/land-world.js TREE_LEAVES (leaves, needles, fronds) — a test checks they agree
UNBUILDABLE = {30}                # bedrock: never placed (no item in land-recipes.json places it either)
# WATER is carried in a bucket (land-recipes.json: a bucket scoops a cell of it, a bucketful places one) and placed only
# where something holds it — on a block or on more water — so a pond, a basin or a fountain holds; it does not flow.
WATER = 5
FLOWERS = {58, 59, 60, 61}        # static/land-world.js FLOWERS: picked by hand, planted in soil like a sapling
# FOOD AND FARMING (#153, #154; doc/land-civilisation.md): static/land-world.js B.berrybush, wheat (ripe or wild grain),
# wheatyoung (sown), farmland (tilled). A hoe tills, a seed is sown on farmland and ripens by its soil (RULES "farming").
BERRYBUSH, WHEAT, WHEATYOUNG, FARMLAND = 70, 71, 72, 73
WELL = 74                         # static/land-world.js B.well: Use on it with a bucket draws water (#155)
SWEPT = {34, 35, 51, BERRYBUSH, WHEAT} | FLOWERS   # static/land-world.js SWEPT: pebble, twigs, flax, flowers, wild food — a placed block takes their place
# THE DEEP (#129, doc/land-core.md): layers below 0, down to DEEP_MIN (static/land-world.js DEEP_MIN), are the deep crust.
# Nobody owns them — anyone signed in digs and builds there, under an owned plot too — and a dug deep cell never grows
# back: a mine stays a mine. The deep is kept with the plot above it but is never part of that plot's commitment.
DEEP_MIN = -2048
# GRAVITY ("can we add some basic gravity", operator 2026-11-06; "i kept digging in snow but the snow stays put and i dig
# under it"): sand, gravel and snow (static/land-world.js B) are LOOSE — dug out from under, or placed over a hole, they
# fall until they rest on something; they fall through air and water (a vacated cell under water fills with water).
FALLS = {4, 17, 6}
PASSABLE = {0, 5}
# THE LISTING (#125, "the land plot should have a screenshot attached like in a realtor ad, also plot size etc", operator
# 2026-11-07): every title gets an aerial photo (scripts/land_shot.mjs: the page's photo mode in headless Chrome) and a
# card of facts read from the planet itself (land_terrain.mjs card). One photo at a time, niced — the browser renders in
# software on the relay's CPU — re-taken only once a plot has changed AND its photo is SHOT_STALE old.
TOWN_HALL_PLOT = 40963440         # scripts/land_town.py: the hall stands on plot (5000, 3440) of face 0
SHOT_STALE = 1800
SHOT_DAILY = 86400                # and every title's photo is retaken once a day, changed or not: the market shows the plot
                                  # as it is ("plot pics on the nft bazar should be updated daily", operator 2026-11-07)
SHOT_TIMEOUT = 900
SHOT_TMP = None                   # where a capture's browser profile is made (None: the system's temp directory)
FALL_REACH = 48                   # cells a column is settled over, below and above the change (bounds one call's work)
# ECOLOGY ("trees should have a process of reproduction as well as the grass", operator 2026-11-06): a SAPLING (leaves
# sometimes give one) planted in soil grows into a young tree of its climate after GROW_S; on an owned plot, bare earth
# with open air above it turns to grass when grass grows next to it (a fair chance each SPREAD_S). The commons needs no
# spreading: its gathered cells grow back whole (regrow). Both write ordinary edits, broadcast like any other.
# FORESTS SPREAD (#110): on an owned plot each standing tree — the planet's or one grown from a sapling — now and then
# drops a sapling on open grass two or three metres from its trunk (SEED_ODDS per SEED_S), never closer than two metres
# to another trunk or sapling and never past TREE_CAP trees on the plot; the sapling then grows like a planted one. Bare
# earth greens over on its own too, slowly (LONE_ODDS per SPREAD_S), and fast beside grass. The same hash-of-the-cell-
# and-tick answers as spread(): a restart changes nothing.
SAPLING, GRASS, DIRT = 52, 1, 2   # static/land-world.js B
GROW_S = 1200                     # a sapling's twenty minutes
SPREAD_S = 60
SEED_S, SEED_ODDS, TREE_CAP = 600, 36, 10       # a tree seeds about once in six hours: a meadow does not become a grove in a day
LONE_ODDS = 40
# CLOTHES (#111, "the crafted items should be what changes how you look"): a garment sewn from linen (land-recipes.json
# items with "wear": its slot) is put ON from the bag and taken off back into it — one per slot, kept with the player and
# shown to everyone near them. The look's other half is chosen, not made: skin and hair, a palette index each.
WEAR_SLOTS = ("head", "body", "legs", "back")
LOOK_SKIN, LOOK_HAIR = 6, 12      # static/land.js SKIN / HAIR palettes (hair: six natural, six bright — #145)
LOOK_BODY, LOOK_FACE = 2, 6       # static/land.js BODIES / FACES: a body type and a drawn kawaii face (#145)
POS_SAVE_S = 10                   # a signed-in player's place is kept at most this often (and when they leave)
MAX_CELLS = 4096                  # per /set call or ws "set"
RATE = 400                        # cells per second per caller, refilling a bucket that holds one full call (MAX_CELLS)
PLANET = 0
# FIRE (#124, "invent fire and tools to generate it, spreading dynamics, destruction mechanics"). A fire is a FIRE cell in
# the air beside something that burns. Each tick it burns what is beside it — a cell turns into what it leaves
# (static/land-world.js BURNS: grass to earth, wood, leaves, litter and plants to air) after its burn time, a built piece of
# a burning material (PIECE_BURNS) burns down whole — and it catches the air beside what it burns, upward more readily;
# with nothing left to burn it dies. It spreads ONLY where its starter may build (the commons, their own plot, a plot
# they are invited to): nobody can burn another's plot. Fires are transient: a restart puts them out.
FIRE = 55
BURNS = {1: 2, 7: 0, 31: 0, 8: 0, 32: 0, 33: 0, 35: 0, 51: 0, 52: 0, 58: 0, 59: 0, 60: 0, 61: 0, 70: 0, 71: 0, 72: 0}   # land-world BURNS (the test checks they agree)
PIECE_BURNS = {9, 15, 39, 38, 37, 40, 45, 46, 47, 48, 49, 50, 53, 54}  # land-world PIECE_BURNS
BURN_TICKS = {7: 8, 31: 8, 1: 3}  # ticks a cell takes to burn through (default 3: leaves, litter, plants)
PIECE_TICKS = 6                   # ticks a built piece takes to burn down
FIRE_TICK = 2.0                   # seconds per fire tick
FIRE_LIFE = 45                    # ticks before a fire burns out even with fuel left (it has moved on by then)
FIRE_MAX = 1500                   # fires burning on the planet at once (a cap on what one spark can start)
SPREAD_SIDE, SPREAD_UP = 0.18, 0.45   # per tick, the chance a fire catches an air cell beside / above what it burns
NEIGH6 = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
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
    """land-world.js boxOk: [x, z, y, w, d, h, m] in whole centimetres inside the plot, positive size, a solid material —
    or with an 8th number, a slope's shape 1..4 (land-world.js SHAPES: a roof needs slopes)."""
    if not isinstance(b, (list, tuple)) or len(b) not in (7, 8) or not all(isinstance(v, int) and not isinstance(v, bool) for v in b):
        return False
    x, z, y, w, d, h, m = b[:7]
    return (x >= 0 and z >= 0 and y >= 0 and w >= 1 and d >= 1 and h >= 1 and x + w <= PLOT_CM and z + d <= PLOT_CM
            and y + h <= H_CM and 0 < m < N_BLOCKS and m != 5 and (len(b) == 7 or 1 <= b[7] <= 4))


def normal_box(b):
    """land-world.js normalBox: one spelling — a box is 7 numbers, a slope 8 (a trailing shape 0 is dropped)."""
    b = list(b)
    return b[:7] if len(b) > 7 and not b[7] else b


def boxes_overlap(a, b):
    return a[0] < b[0] + b[3] and b[0] < a[0] + a[3] and a[1] < b[1] + b[4] and b[1] < a[1] + a[4] and a[2] < b[2] + b[5] and b[2] < a[2] + a[5]


def commitment_bytes(plot, salt, edits, boxes=()):
    """land-world.js commitmentBytes, byte for byte (v3: the ground's cell edits, then the built pieces with their shapes)."""
    if len(salt) != 32:
        raise ValueError("salt must be 32 bytes")
    # the deep below a plot is the commons, not the plot's build: never committed (land-world.js commitmentBytes agrees)
    ce, cb = canonical_edits([e for e in edits if e[2] >= 0]), sorted({tuple(normal_box(b)) for b in boxes})
    if not all(box_ok(list(b)) for b in cb):
        raise ValueError("bad box")
    out = bytearray(b"nado-land-plot-v3") + plot.to_bytes(4, "big") + salt + len(ce).to_bytes(4, "big")
    for x, z, y, b in ce:
        out += bytes([x, z, y >> 8, y & 255, b])
    out += len(cb).to_bytes(4, "big")
    for bx in cb:
        x, z, y, w, d, h, m = bx[:7]
        out += b"".join(v.to_bytes(2, "big") for v in (x, z, y, w, d, h)) + bytes([m, bx[7] if len(bx) > 7 else 0])
    return bytes(out)


def commitment(plot, salt, edits, boxes=()):
    n = int.from_bytes(hashlib.sha256(commitment_bytes(plot, salt, edits, boxes)).digest(), "big")
    return str(n or 1)


def box_vol(b):
    """cm³ a piece costs — a slope (8th number 1..4) half its box (land-world.js boxVolume)."""
    return b[3] * b[4] * b[5] // 2 if len(b) > 7 and b[7] else b[3] * b[4] * b[5]


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


# ---- FLIGHT (#147, doc/land-tech-to-flight.md; "you must add actual physics like engines and gravity to the game and
# build a real usable xfighter", operator 2026-11-09). A craft is built pieces that touch one another and hold a pilot
# seat and at least one thruster. Boarding the seat lifts them off the plot into a craft record — its pieces kept
# relative to the seat, a pose [face, u, v, h, yaw] — that the pilot's page flies; the server bounds the pilot's claims by
# the craft's own top speed, keeps it across restarts, shows it to everyone near, and docks it back onto a plot as pieces.
FLIGHT = RULES["flight"]
CRAFT_PAD = 1                     # cm: pieces this close count as touching (one craft)
CRAFT_PIECES = 400                # pieces one craft holds at most
CRAFT_SLACK = 12.0                # m a pose may run ahead of vmax x the time since the last (a slow network's bunching)


def boxes_touch(a, b):
    return all(a[i] - CRAFT_PAD < b[i] + b[i + 3] and b[i] - CRAFT_PAD < a[i] + a[i + 3] for i in range(3))


def connected(boxes, seed):
    """The pieces that touch `seed`, and those touching them, and so on (a craft is one connected build)."""
    left, out, todo = [b for b in boxes if b != seed], [seed], [seed]
    while todo and len(out) <= CRAFT_PIECES:
        cur = todo.pop()
        near = [b for b in left if boxes_touch(cur, b)]
        for b in near:
            left.remove(b); out.append(b); todo.append(b)
    return out


def craft_mass(pieces):
    """Tonnes: a unit part by its own mass, any other piece by its volume x its material's density."""
    dens, unit = FLIGHT["density"], FLIGHT["unit_mass"]
    return sum(unit[str(b[6])] if str(b[6]) in unit else b[3] * b[4] * b[5] / 1e6 * dens.get(str(b[6]), dens["default"]) for b in pieces)


def craft_thrust(pieces):
    """kN: every thruster's push."""
    return sum(FLIGHT["thrust_kn"] for b in pieces if b[6] == THRUSTER)


def turn_pieces(pieces, quarter):
    """The pieces (x east, z north, relative to the seat) as they lie when the craft's yaw is `quarter` quarter-turns:
    yaw +90° sends its nose (+z) east and its right side (+x) south — a point (x, z) goes to (z, -x) — the page's frame
    (land.js craftMesh: forward = sin(yaw)·east + cos(yaw)·north). A slope rises the next way round: +x -> -z -> -x -> +z."""
    out = []
    for b in pieces:
        x, z, y, w, d, h = b[:6]
        shape = b[7] if len(b) > 7 else 0
        for _ in range(quarter % 4):
            x, z, w, d = z, -(x + w), d, w
            shape = {1: 4, 4: 2, 2: 3, 3: 1}.get(shape, 0)
        out.append([x, z, y, w, d, h, b[6]] + ([shape] if shape else []))
    return out


# ---- FACTORIES (#148, "we also may need factorization like factorio or Satisfactory … for advanced tech", operator
# 2026-11-09): a smelter or an assembler runs one chosen recipe by itself, on the world server's clock — taking what it
# needs from the chests touching it, making into a chest touching it — while a generator within power_reach metres on the
# same plot burns coal or charcoal from a chest beside it. land-recipes.json "machines" holds what each one stands in for.
MACH = RULES["machines"]


def machine_can(blk, r):
    """Machine `blk` can run recipe `r`: every station or tool it asks for is one the machine stands in for, and it makes
    items only (a machine never makes a station or a tool)."""
    does = MACH.get(str(blk), {}).get("does", [])
    return all(w in does for w in r.get("with", [])) and all(m in RULES["items"] for m, _ in r["makes"])


def centre(b):
    return (b[0] + b[3] / 2, b[1] + b[4] / 2, b[2] + b[5] / 2)


def chest_key(b):
    """A chest's identity on its plot: its box (a chest never moves; taking it down needs it empty)."""
    return ",".join(str(int(x)) for x in b[:7])


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
        # SIGNED IN ACROSS A RESTART: sessions lived only in memory, so every restart of this server (every Land deploy)
        # signed every player and agent out mid-game (found walking the live page, 2026-11-08). They are kept in
        # sessions.json under the token's hash — never the token itself, so the file signs nobody in.
        self.sessions = {}                    # blake2b(token) -> {"address", "until"}
        try:
            now = time.time()
            self.sessions = {k: v for k, v in json.load(open(os.path.join(self.dir, "sessions.json"))).items() if v["until"] > now}
        except Exception:
            pass
        self.buckets = {}                     # caller -> [tokens, at]
        self.workb = {}                       # caller -> [seconds of work banked, at]
        self.players, self.pdirty = {}, set()  # address -> {"items", "tools", "stations"}; who changed since the flush
        os.makedirs(os.path.join(self.dir, "players"), exist_ok=True)
        try:
            self.offers = json.load(open(os.path.join(self.dir, "offers.json")))
        except Exception:
            self.offers = {}
        self.odirty = False
        try:                                              # FLIGHT: crafts flying or parked, kept across restarts
            self.crafts = json.load(open(os.path.join(self.dir, "crafts.json")))
        except Exception:
            self.crafts = {}
        for c in self.crafts.values():                    # a restart lands every pilot: the craft is parked where it was
            c["pilot"] = None
        self.cdirty = False
        self.http = self.oracle = None
        self.shots = os.path.join(self.dir, "shots")      # <plot>.jpg + <plot>.json {"ver", "at"} (THE LISTING)
        os.makedirs(self.shots, exist_ok=True)
        self.shot_want = []                               # plots asked for, first come first served
        self.cards = {}                                   # plot -> the untouched planet's facts (they never change)
        self.fires = {}                # (face, u, v, h) -> {"by", "age"}: the fires burning now (FIRE)
        self.burning = {}              # (face, u, v, h) of a cell, or (plot, box key) of a piece -> ticks it has burned
        for f in os.listdir(self.dir):
            if f.endswith(".json") and f[:-5].isdigit():
                try:
                    d = json.load(open(os.path.join(self.dir, f)))
                    self.plots[int(f[:-5])] = {"edits": {tuple(map(int, k.split(":"))): b for k, b in d["edits"].items()},
                                               "salt": bytes.fromhex(d["salt"]), "ver": int(d.get("ver", 0)),
                                               "exp": {tuple(map(int, k.split(":"))): t for k, t in d.get("exp", {}).items()},
                                               "grow": {tuple(map(int, k.split(":"))): t for k, t in d.get("grow", {}).items()},
                                               "chests": {k: {i: int(n) for i, n in v.items()} for k, v in d.get("chests", {}).items()},
                                               "boxes": [list(b) for b in d.get("boxes", [])],
                                               "machines": d.get("machines") or {}, "gens": d.get("gens") or {}}
                    rec = self.plots[int(f[:-5])]
                    for k in [k for k, b in rec["edits"].items() if b == FIRE]:      # a restart puts every fire out
                        rec["edits"].pop(k)
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
                    "exp": {f"{x}:{z}:{y}": t for (x, z, y), t in (rec.get("exp") or {}).items()},
                    "grow": {f"{x}:{z}:{y}": t for (x, z, y), t in (rec.get("grow") or {}).items()},
                    "chests": {k: v for k, v in (rec.get("chests") or {}).items() if v}, "boxes": rec.get("boxes", []),
                    # FACTORIES (#148): each machine's recipe and status, each generator's charge (not in the commitment)
                    "machines": rec.get("machines") or {}, "gens": {k: v for k, v in (rec.get("gens") or {}).items() if v}}
            self._write(f"{p}.json", body)
            self.dirty.discard(p)
        for a in list(self.pdirty):
            self._write(os.path.join("players", a + ".json"), self.players[a])
            self.pdirty.discard(a)
        if self.odirty:
            self._write("offers.json", self.offers)
            self.odirty = False
        if self.cdirty:
            self._write("crafts.json", self.crafts)
            self.cdirty = False

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

    async def grow_cells(self, face, u, v, h):
        """The young tree a sapling at [face, u, v, h] grows into (land_terrain.mjs grow): [[face, u, v, h, id], ...]."""
        async with self.oracle_lock:
            self.oracle.stdin.write((json.dumps({"grow": [face, u, v, h]}) + "\n").encode())
            await self.oracle.stdin.drain()
            r = json.loads(await self.oracle.stdout.readline())
        if "error" in r:
            raise RuntimeError("terrain oracle: " + r["error"])
        return r["cells"]

    async def soil_at(self, face, u, v):
        """The column's soil (land_terrain.mjs soil → land-world soilOf): loam, sandy, clay, peat or stony."""
        async with self.oracle_lock:
            self.oracle.stdin.write((json.dumps({"soil": [face, u, v]}) + "\n").encode())
            await self.oracle.stdin.drain()
            r = json.loads(await self.oracle.stdout.readline())
        if "error" in r:
            raise RuntimeError("terrain oracle: " + r["error"])
        return r["soil"]

    async def moist(self, face, u, v, h):
        """FARMING: water (the sea, a lake, a bucketful poured) within moist_reach columns of the field cell (face, u, v, h),
        at its layer or the one under it — a field by the water, or one a player irrigates, grows quicker."""
        r = RULES["farming"]["moist_reach"]
        look = [[face, u + du, v + dv, h + dh] for du in range(-r, r + 1) for dv in range(-r, r + 1) for dh in (0, -1)
                if 0 <= u + du < W and 0 <= v + dv < W]
        return WATER in (await self.blocks_at(look)).values()

    async def crop_due(self, face, u, v, h, now=None):
        """When a seed sown at (face, u, v, h) — on the farmland at h - 1 — ripens: crop_s by its soil's time, sooner moist."""
        F = RULES["farming"]
        t = F["crop_s"] * F["soil"][await self.soil_at(face, u, v)]["time"]
        if await self.moist(face, u, v, h - 1):
            t *= F["moist"]
        return (time.time() if now is None else now) + t

    async def terrain_card(self, p):
        """The untouched plot's facts (land_terrain.mjs card): a pure function of the seed, so kept forever."""
        if p not in self.cards:
            async with self.oracle_lock:
                self.oracle.stdin.write((json.dumps({"card": p}) + "\n").encode())
                await self.oracle.stdin.drain()
                r = json.loads(await self.oracle.stdout.readline())
            if "error" in r:
                raise RuntimeError("terrain oracle: " + r["error"])
            self.cards[p] = r
        return self.cards[p]

    def shot_meta(self, p):
        try:
            return json.load(open(os.path.join(self.shots, f"{p}.json")))
        except Exception:
            return None

    def shot_due(self, p, now=None):
        """Whether plot p needs a (new) photo: none yet, it changed since and the photo is SHOT_STALE old, or the photo is
        a day old (SHOT_DAILY)."""
        m = self.shot_meta(p)
        if not m:
            return True
        age, rec = (now or time.time()) - m.get("at", 0), self.plots.get(p)
        return age >= SHOT_DAILY or (bool(rec) and rec["ver"] != m.get("ver") and age >= SHOT_STALE)

    def next_shot(self):
        """The next plot to photograph: one asked for, else a title of the issuer's without a current photo."""
        while self.shot_want:
            p = self.shot_want.pop(0)
            if self.shot_due(p):
                return p
        due = [p for p in sorted(self.titles) if self.shot_due(p)]
        return min(due, key=lambda p: (self.shot_meta(p) or {}).get("at", 0)) if due else None   # the oldest photo first

    async def shoot(self, p, page):
        """Photograph plot p (scripts/land_shot.mjs) into shots/<p>.jpg; the photo is swapped in whole or not at all."""
        ver = (self.plots.get(p) or {}).get("ver", 0)
        tmp = os.path.join(self.shots, f".{p}.jpg")
        # THE BROWSER PROFILE IS OURS TO REMOVE: the capture made and removed its own, and most captures left it behind in
        # /tmp (60 in a day, found 2026-11-08) — a browser's children still writing into it as it went. It is made here,
        # handed over, and removed here once the whole process group is gone, however the capture ended.
        prof = tempfile.mkdtemp(prefix="land-shot-", dir=SHOT_TMP)
        proc = await asyncio.create_subprocess_exec("nice", "-n", "19", "node", os.path.join(REPO, "scripts", "land_shot.mjs"),
                                                    f"{page}/?shot={p}", tmp, stdout=asyncio.subprocess.DEVNULL,
                                                    stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
                                                    env={**os.environ, "LAND_SHOT_PROFILE": prof})
        try:
            ok = await asyncio.wait_for(proc.wait(), SHOT_TIMEOUT) == 0
        except asyncio.TimeoutError:
            ok = False
        # its own process group: the browser it started dies with it (killing node alone left Chrome running) — on a
        # timeout, and after a finished capture too, whose browser's helpers may outlive it
        try:
            os.killpg(proc.pid, 9)
        except (ProcessLookupError, PermissionError):
            pass
        await proc.wait()
        await asyncio.sleep(0.5)                                     # the killed helpers' last writes
        shutil.rmtree(prof, ignore_errors=True)
        if not ok or not os.path.exists(tmp) or os.path.getsize(tmp) < 2000:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False
        os.replace(tmp, os.path.join(self.shots, f"{p}.jpg"))
        self._write(os.path.join("shots", f"{p}.json"), {"ver": ver, "at": int(time.time())})
        return True

    async def card(self, p):
        """A plot's listing card (#125): what it is, where, what is on it, its title and its photo."""
        face, row, col = plot_coords(p)
        t = await self.terrain_card(p)
        await self.refresh_titles()
        rec = self.plots.get(p) or {}
        hf, hr, hc = plot_coords(TOWN_HALL_PLOT)
        m = self.shot_meta(p)
        return {"plot": p, "planet": PLANET, "face": face, "row": row, "col": col, "size_m": PLOT, "area_m2": PLOT * PLOT,
                "u0": col * PLOT, "v0": row * PLOT, **t,
                "town_hall_m": round(((hr - row) ** 2 + (hc - col) ** 2) ** 0.5 * PLOT) if hf == face else None,
                "built": len(rec.get("edits") or {}), "pieces": len(rec.get("boxes") or []), "ver": rec.get("ver", 0),
                "aid": self.titles.get(p), "holder": await self.holder(p),
                "shot": f"/land/api/shot?plot={p}&v={m['at']}" if m else None, "shot_at": m and m["at"]}

    async def blocks_at(self, cells):
        """What each [face, u, v, h] holds now — its plot's edit, else the untouched planet (one oracle round trip)."""
        out, need = {}, []
        for c in cells:
            f, u, v, h = c
            p = plot_of(f, u, v)
            rec = self.plots.get(p)
            k = (u - (p % FACE_N) * PLOT, v - ((p // FACE_N) % FACE_N) * PLOT, h)
            if rec and k in rec["edits"]:
                out[tuple(c)] = rec["edits"][k]
            else:
                need.append(list(c))
        for c, b in zip(need, await self.terrain(need)):
            out[tuple(c)] = b
        return out

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

    async def settle(self, p, rec, face, u, v, h, titled, applied):
        """GRAVITY: let column (face, u, v) of plot `p` settle around height h after a change there — every loose block
        (FALLS) with something passable under it drops onto the first thing that holds it, in order, so a column of sand
        comes down as a column. One terrain round trip for the window; only the cells that changed are written (as edits
        that regrow like any other in the commons). Returns the number of cells moved."""
        lo, hi = max(DEEP_MIN, h - FALL_REACH), min(H - 1, h + FALL_REACH)
        fc, fr = p % FACE_N, (p // FACE_N) % FACE_N
        key = lambda hh: (u - fc * PLOT, v - fr * PLOT, hh)
        edits = rec["edits"]
        need = [hh for hh in range(lo, hi + 1) if key(hh) not in edits]
        base = dict(zip(need, await self.terrain([[face, u, v, hh] for hh in need]))) if need else {}
        col = {hh: (edits[key(hh)] if key(hh) in edits else base[hh]) for hh in range(lo, hi + 1)}
        before, out, vac, slot = dict(col), dict(col), set(), None
        for hh in range(lo, hi + 1):                         # bottom up: each loose block to the lowest free slot
            b = out[hh]
            if b in PASSABLE:
                if slot is None:
                    slot = hh
            elif b in FALLS:
                if slot is not None:
                    out[slot], out[hh] = b, 0
                    vac.add(hh); vac.discard(slot)
                    slot += 1
            else:
                slot = None
        for hh in range(hi - 1, lo - 1, -1):                 # a vacated cell under water is water, not an air pocket
            if hh in vac and out[hh] == 0 and out[hh + 1] == 5:
                out[hh] = 5
        moved = 0
        for hh in range(lo, hi + 1):
            if out[hh] == before[hh]:
                continue
            k = key(hh)
            edits[k] = out[hh]
            if not titled and hh >= 0:                       # the deep never grows back (THE DEEP)
                rec.setdefault("exp", {})[k] = time.time() + RULES["wilderness_regrow_s"]
            applied.setdefault(p, []).append([face, u, v, hh, out[hh]])
            moved += 1
        return moved

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
            pl.setdefault("worn", {}); pl.setdefault("look", {"skin": 0, "hair": 0})
            self.players[addr] = pl
        return pl

    def inv_json(self, addr):
        pl = self.player(addr)
        return {"items": {k: n for k, n in sorted(pl["items"].items()) if n > 0}, "tools": sorted(pl["tools"]),
                "stations": sorted(pl["stations"]), "vol": {k: v for k, v in sorted(pl["vol"].items()) if v > 0},
                "worn": dict(sorted(pl["worn"].items())), "look": dict(pl["look"]),
                "fed": max(0, int(pl.get("fed", 0) - time.time()))}          # seconds of a meal left (#155)

    def keep_place(self, addr, pos):
        """Remember where a signed-in player stands ([face, u, v, h, yaw]), written with the player at the next flush."""
        self.player(addr)["pos"] = [int(pos[0]), round(float(pos[1]), 2), round(float(pos[2]), 2), round(float(pos[3]), 2), round(float(pos[4]), 3)]
        self.player(addr)["pos_at"] = int(time.time())                # the page compares it with its own save
        self.pdirty.add(addr)

    def look_of(self, addr):
        """What others see of a player: what they wear and their skin and hair."""
        pl = self.player(addr)
        lk = pl["look"]
        return {"worn": dict(sorted(pl["worn"].items())), "skin": lk.get("skin", 0), "hair": lk.get("hair", 0),
                "body": lk.get("body", 0), "face": lk.get("face", 0)}

    def wear(self, addr, slot, item):
        """Put `item` on (from the bag) in `slot`, or take off what is there (item None) back into the bag. One per slot:
        what was worn goes back into the bag first. Returns an error or None."""
        if slot not in WEAR_SLOTS:
            return "no such place to wear something"
        pl = self.player(addr)
        if item is not None:
            spec = RULES["items"].get(item) if isinstance(item, str) else None
            if not spec or spec.get("wear") != slot:
                return "that is not worn there"
            if pl["items"].get(item, 0) < 1:
                return "you have none in your bag"
            pl["items"][item] -= 1
        old = pl["worn"].pop(slot, None)
        if old:
            pl["items"][old] = pl["items"].get(old, 0) + 1
        if item is not None:
            pl["worn"][slot] = item
        self.pdirty.add(addr)
        return None

    def set_look(self, addr, skin, hair, body=None, face=None):
        """The player's own look: skin and hair colour, body type and face ("let users customize the basics like gender and
        face and hair color", operator 2026-11-09, #145). A part not given keeps what it was (an older page sends two)."""
        cur = self.player(addr)["look"]
        body = cur.get("body", 0) if body is None else body
        face = cur.get("face", 0) if face is None else face
        parts = ((skin, LOOK_SKIN), (hair, LOOK_HAIR), (body, LOOK_BODY), (face, LOOK_FACE))
        if not all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x < n for x, n in parts):
            return "no such look"
        self.player(addr)["look"] = {"skin": skin, "hair": hair, "body": body, "face": face}
        self.pdirty.add(addr)
        return None

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

    @staticmethod
    def fed_work(pl):
        """EATING (#155): a fed player's work takes RULES food.work of its time while their meal lasts; 1 otherwise."""
        return RULES["food"]["work"] if pl.get("fed", 0) > time.time() else 1

    def eat(self, who, item):
        """Eat one of `item` (RULES food.items): work goes quicker for its seconds, added to what is left up to max_s.
        Food is a reward, never a need (doc/land-civilisation.md)."""
        F = RULES["food"]
        if item not in F["items"]:
            return "that is not food"
        pl = self.player(who)
        if pl["items"].get(item, 0) < 1:
            return f"you have no {RULES['items'][item]['name'].lower()}"
        pl["items"][item] -= 1
        if not pl["items"][item]:
            del pl["items"][item]
        now = time.time()
        pl["fed"] = min(now + F["max_s"], max(now, pl.get("fed", 0)) + F["items"][item])
        self.pdirty.add(who)
        return None

    async def well(self, who, p, b):
        """Draw a bucketful of water from well `b` on plot `p` (#155): anyone signed in with a bucket, and a well never runs
        dry — water anywhere a well is built, not only at a lake."""
        rec = self.plots.get(p)
        b = list(b) if isinstance(b, (list, tuple)) else b
        if not rec or not isinstance(b, list) or b not in rec.get("boxes", []) or b[6] != WELL:
            return "no such well here"
        pl = self.player(who)
        if not self._has_class(pl, "bucket"):
            return "a well is drawn with a bucket"
        pl["items"]["water"] = pl["items"].get("water", 0) + 1
        self.pdirty.add(who)
        return None

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
            if not (0 <= face < 6 and 0 <= u < W and 0 <= v < W and DEEP_MIN <= h < H and 0 <= b < N_BLOCKS) or b in UNBUILDABLE:
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
            if h < 0:                                               # THE DEEP: nobody's, and it does not grow back
                titled, may = False, True
            if b == 0 and cur == FIRE:                              # ---- beat out a fire: it goes, nothing is gathered
                self.fires.pop((face, u, v, h), None)
                rec = self.plot(p)
                rec["edits"].pop(k, None)
                rec["ver"] += 1
                self.dirty.add(p)
                applied.setdefault(p, []).append([face, u, v, h, 0])
                continue
            if b == 0:                                              # ---- break: gather
                rule = RULES["breaking"].get(str(cur))
                if not rule:
                    refused.append([c, "nothing here that can be gathered"]); continue
                if titled and not may:
                    refused.append([c, "not your plot — only its owner and the builders they invite take from it"]); continue
                if rule.get("needs") and not self._has_class(pl, rule["needs"]):
                    refused.append([c, f"needs a {RULES['tools'][rule['needs']]['name'].lower()}"]); continue
                speed = self._speed(pl, rule.get("class"))
                if not self.work(who, rule["hard"] / speed * self.fed_work(pl)):
                    refused.append([c, "too fast — breaking takes time (a better tool is quicker)"]); continue
                yields = rule["yields"]
                if cur == WHEAT and (await self.blocks_at([[face, u, v, h - 1]]))[(face, u, v, h - 1)] == FARMLAND:
                    # a HARVEST (#154): ripe wheat on a field gives what its soil gives, more than wild grain
                    sl = RULES["farming"]["soil"][await self.soil_at(face, u, v)]
                    yields = [["grain", sl.get("grain", 1)], ["seed", sl.get("seed", 1)]]
                for item, n in yields:
                    pl["items"][item] = pl["items"].get(item, 0) + n
                if rule.get("bonus") and (face * 7919 + u * 31 + v * 17 + h) % rule["bonus"][1] == 0:
                    pl["items"][rule["bonus"][0]] = pl["items"].get(rule["bonus"][0], 0) + 1
                changed = True
                rec = self.plot(p)
                rec["edits"][k] = 0
                (rec.get("grow") or {}).pop(k, None)               # a sapling pulled up grows no more
                if not titled and h >= 0:                          # the commons regrows (not the deep: a mine stays)
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
                if b == FARMLAND:                                   # ---- TILL (#154): a hoe turns turf or earth to a field
                    if cur not in (GRASS, DIRT):
                        refused.append([c, "a hoe tills grass or earth"]); continue
                    if not self._has_class(pl, "hoe"):
                        refused.append([c, "tilling needs a hoe"]); continue
                    if (await self.blocks_at([[face, u, v, h + 1]]))[(face, u, v, h + 1)] not in (0, *SWEPT):
                        refused.append([c, "a field needs open air over it"]); continue
                    soil = await self.soil_at(face, u, v)
                    if not RULES["farming"]["soil"][soil].get("till", True):
                        refused.append([c, f"{soil} ground: too stony to till"]); continue
                    changed = True
                    rec = self.plot(p)
                    rec["edits"][k] = FARMLAND
                    rec.get("exp", {}).pop(k, None)                 # a field is a build: it stays
                    rec["ver"] += 1
                    self.dirty.add(p)
                    applied.setdefault(p, []).append([face, u, v, h, FARMLAND])
                    continue
                swept = None
                if cur == FIRE:                                     # earth, sand or a block put on a fire smothers it
                    self.fires.pop((face, u, v, h), None)
                elif cur in SWEPT and b not in SWEPT and b != SAPLING:
                    swept = cur                                     # picked up below, once the block is paid for
                elif cur not in (0, 5):
                    refused.append([c, "something is already there"]); continue
                # a cell a built piece reaches into takes no block: a daisy was planted inside the plank floor of the town
                # pavilion — the cell under its 10 cm edge was "air" (built by hand on the live page, 2026-11-08)
                if rec and rec.get("boxes") and any(boxes_overlap([k[0] * CM, k[1] * CM, k[2] * CM, CM, CM, CM], o) for o in rec["boxes"]):
                    refused.append([c, "a built piece is there"]); continue
                if (b == SAPLING or b in FLOWERS) and (await self.blocks_at([[face, u, v, h - 1]]))[(face, u, v, h - 1)] not in (GRASS, DIRT):
                    refused.append([c, "a plant is planted in earth or grass"]); continue
                if b == WHEATYOUNG and (await self.blocks_at([[face, u, v, h - 1]]))[(face, u, v, h - 1)] != FARMLAND:
                    refused.append([c, "seed is sown on farmland — till the ground with a hoe first"]); continue
                if b == WATER and (cur == WATER or (await self.blocks_at([[face, u, v, h - 1]]))[(face, u, v, h - 1)] in PASSABLE - {WATER}):
                    refused.append([c, "water needs something under it to hold it"]); continue
                item = places.get(b)
                if not item or pl["items"].get(item, 0) < 1:
                    refused.append([c, f"you have no {RULES['items'][item]['name'].lower() if item else 'such block'} to place"]); continue
                pl["items"][item] -= 1
                # the litter it takes the place of goes into the placer's bag, as picking it up would have (SWEPT)
                for got, n in ((RULES["breaking"].get(str(swept)) or {"yields": []})["yields"] if swept else []):
                    pl["items"][got] = pl["items"].get(got, 0) + n
                changed = True
                rec = self.plot(p)
                rec["edits"][k] = b
                rec.get("exp", {}).pop(k, None)
                if b == SAPLING:
                    rec.setdefault("grow", {})[k] = time.time() + GROW_S
                elif b == WHEATYOUNG:                               # sown: it ripens in its soil's time (#154)
                    rec.setdefault("grow", {})[k] = await self.crop_due(face, u, v, h)
            rec["ver"] += 1
            self.dirty.add(p)
            self.pdirty.add(who)
            applied.setdefault(p, []).append([face, u, v, h, rec["edits"][k]])
            # GRAVITY: a hole under loose blocks, or a loose block placed over a hole, settles its column (after the
            # change itself is in `applied`, so a page applies the fall on top of it)
            if b in FALLS or b == 0:
                await self.settle(p, rec, face, u, v, h, titled, applied)
        return applied, refused, changed

    async def grow(self, now=None):
        """ECOLOGY: every sapling whose time is up becomes its young tree — written into the cells that are still air (a
        tree never overwrites a build) and only on its own plot; the planted cells stay (no regrow timer) like anything
        planted. Returns {plot: [[face, u, v, h, block], ...]} for the broadcast."""
        now = time.time() if now is None else now
        out = {}
        for p, rec in list(self.plots.items()):
            due = [k for k, t in (rec.get("grow") or {}).items() if t <= now]
            for k in due:
                rec["grow"].pop(k, None)
                face, row, col = plot_coords(p)
                if rec["edits"].get(k) == WHEATYOUNG:               # a sown crop ripens where it stands (#154)
                    rec["edits"][k] = WHEAT
                    rec["ver"] += 1
                    self.dirty.add(p)
                    out.setdefault(p, []).append([face, col * PLOT + k[0], row * PLOT + k[1], k[2], WHEAT])
                    continue
                if rec["edits"].get(k) != SAPLING:
                    continue
                u, v = col * PLOT + k[0], row * PLOT + k[1]
                cells = [c for c in await self.grow_cells(face, u, v, k[2]) if plot_of(c[0], c[1], c[2]) == p]
                here = await self.blocks_at([c[:4] for c in cells])
                for f, cu, cv, ch, b in cells:
                    ck = (cu - col * PLOT, cv - row * PLOT, ch)
                    # a tree's own TRUNK goes through a neighbour's leaves (leaves are no build): saplings 4 m apart grew
                    # under each other's crowns and one got a trunk with a gap (the town orchard, 2026-11-08)
                    if here[(f, cu, cv, ch)] not in (0, SAPLING) and not (b in TREE_WOOD and here[(f, cu, cv, ch)] in TREE_LEAVES):
                        continue
                    rec["edits"][ck] = b
                    rec.get("exp", {}).pop(ck, None)
                    out.setdefault(p, []).append([f, cu, cv, ch, b])
                rec["ver"] += 1
                self.dirty.add(p)
        return out

    async def spread(self, now=None):
        """ECOLOGY: on an OWNED plot, bare earth with open air above it turns to grass when grass grows beside it (the four
        neighbours at its height, or one up or down a step), each such cell with a fair chance per SPREAD_S tick — the
        same answer on a restart (a hash of the cell and the tick, no RNG). Returns the broadcast like grow()."""
        now = time.time() if now is None else now
        tick, out = int(now // SPREAD_S), {}
        for p, rec in list(self.plots.items()):
            if not rec["edits"] or (await self.holder(p)) is None:
                continue
            face, row, col = plot_coords(p)
            cand = {(x, z, y if b == DIRT else y - 1) for (x, z, y), b in rec["edits"].items() if b in (DIRT, 0) and y > 1}
            roll = lambda c, salt: int(hashlib.blake2b(f"{p}:{c}:{tick}{salt}".encode(), digest_size=4).hexdigest(), 16)
            near = {c for c in cand if roll(c, "") % 3 == 0}                     # beside grass: a fair chance a tick
            lone = {c for c in cand if roll(c, ":lone") % LONE_ODDS == 0}        # on its own: a slow one (#110)
            cand = list(near | lone)
            if not cand:
                continue
            g = lambda x, z, y: [face, col * PLOT + x, row * PLOT + z, y]
            look = []
            for x, z, y in cand:
                look += [g(x, z, y), g(x, z, y + 1)] + [g(x + dx, z + dz, y + dy) for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)) for dy in (-1, 0, 1)]
            look = [c for c in look if 0 <= c[1] < W and 0 <= c[2] < W and 1 <= c[3] < H]
            at = await self.blocks_at(look)
            for x, z, y in cand:
                if at.get(tuple(g(x, z, y))) != DIRT or at.get(tuple(g(x, z, y + 1))) != 0:
                    continue
                if (x, z, y) not in lone and not any(at.get(tuple(g(x + dx, z + dz, y + dy))) == GRASS
                                                     for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)) for dy in (-1, 0, 1)):
                    continue
                rec["edits"][(x, z, y)] = GRASS
                rec["ver"] += 1
                self.dirty.add(p)
                out.setdefault(p, []).append(g(x, z, y) + [GRASS])
        return out

    async def tree_roots(self, p):
        """The trees standing on plot p: [(u, v, ground)] — the planet's own (land_terrain.mjs trees) whose trunk is still
        there, and every trunk grown or built from wood that stands on soil (a trunk's lowest log)."""
        face, row, col = plot_coords(p)
        if not hasattr(self, "_roots"):
            self._roots = {}
        if p not in self._roots:
            async with self.oracle_lock:
                self.oracle.stdin.write((json.dumps({"trees": p}) + "\n").encode())
                await self.oracle.stdin.drain()
                r = json.loads(await self.oracle.stdout.readline())
            if "error" in r:
                raise RuntimeError("terrain oracle: " + r["error"])
            self._roots[p] = [tuple(x[1:]) for x in r["roots"]]
        rec = self.plots.get(p) or {"edits": {}}
        logs = [(col * PLOT + x, row * PLOT + z, y) for (x, z, y), b in rec["edits"].items() if b in TREE_WOOD]
        look = [[face, u, v, t + 1] for u, v, t in self._roots[p]] + [[face, u, v, y - 1] for u, v, y in logs]
        at = await self.blocks_at(look)
        out = [(u, v, t) for u, v, t in self._roots[p] if at[(face, u, v, t + 1)] in TREE_WOOD]
        out += [(u, v, y - 1) for u, v, y in logs if at[(face, u, v, y - 1)] in (GRASS, DIRT)]
        return out

    async def seed(self, now=None):
        """FORESTS SPREAD (#110): on each owned plot, a tree now and then drops a sapling on open grass 2-3 m from its trunk
        (see SEED_S). Returns the broadcast like grow()."""
        now = time.time() if now is None else now
        tick, out = int(now // SEED_S), {}
        for p, rec in list(self.plots.items()) + [(q, None) for q in list(self.titles) if q not in self.plots]:
            if (await self.holder(p)) is None:
                continue
            roots = await self.tree_roots(p)
            if not roots:
                continue
            face, row, col = plot_coords(p)
            rec = self.plot(p)
            sap = [(col * PLOT + x, row * PLOT + z) for (x, z, y), b in rec["edits"].items() if b == SAPLING]
            for u, v, t in sorted(roots):
                if len(roots) + len(sap) >= TREE_CAP:
                    break
                hsh = int(hashlib.blake2b(f"seed:{p}:{u}:{v}:{tick}".encode(), digest_size=8).hexdigest(), 16)
                if hsh % SEED_ODDS:
                    continue
                ring = [(dx, dz) for dx in range(-3, 4) for dz in range(-3, 4) if 2 <= max(abs(dx), abs(dz)) <= 3]
                dx, dz = ring[(hsh // SEED_ODDS) % len(ring)]
                tu, tv = u + dx, v + dz
                if plot_of(face, tu, tv) != p:
                    continue
                trunks = [(a, b) for a, b, _ in roots] + sap
                if any(max(abs(a - tu), abs(b - tv)) < 2 for a, b in trunks):
                    continue                                              # never crowding another tree
                cells = [[face, tu, tv, y] for y in range(t - 3, t + 5)]
                at = await self.blocks_at(cells)
                ground = next((y for y in range(t - 3, t + 3) if at[(face, tu, tv, y)] == GRASS
                               and at[(face, tu, tv, y + 1)] == 0 and at[(face, tu, tv, y + 2)] == 0), None)
                if ground is None:
                    continue                                              # only on open grass
                k = (tu - col * PLOT, tv - row * PLOT, ground + 1)
                rec["edits"][k] = SAPLING
                rec.get("exp", {}).pop(k, None)
                rec.setdefault("grow", {})[k] = now + GROW_S
                rec["ver"] += 1
                self.dirty.add(p)
                sap.append((tu, tv))
                out.setdefault(p, []).append([face, tu, tv, ground + 1, SAPLING])
        return out

    REGROW_CLEAR = 8                          # blocks around a player present in which nothing regrows yet

    def regrow(self, present=()):
        """Wilderness cells whose time is up go back to the untouched planet: {plot: [[face, u, v, h], ...]}.
        A cell within REGROW_CLEAR columns of a player present (`present`: their [face, u, v, h, ...]) waits until they
        have gone: the commons once refilled a whole mine shaft around the player standing at its bottom and buried
        them in rock 10 m down (operator's agent, 2026-11-09) — every column, the shaft above them included."""
        out, now = {}, time.time()
        for p, rec in self.plots.items():
            exp = rec.get("exp")
            if not exp:
                continue
            face, row, col = plot_coords(p)
            near = [(pu, pv) for pf, pu, pv, *_ in present if pf == face
                    and col * PLOT - self.REGROW_CLEAR <= pu < (col + 1) * PLOT + self.REGROW_CLEAR
                    and row * PLOT - self.REGROW_CLEAR <= pv < (row + 1) * PLOT + self.REGROW_CLEAR]
            for k in [k for k, t in exp.items() if t <= now]:
                u, v = col * PLOT + k[0], row * PLOT + k[1]
                if any(abs(u - pu) <= self.REGROW_CLEAR and abs(v - pv) <= self.REGROW_CLEAR for pu, pv in near):
                    continue                          # someone is working here: it regrows once they have gone
                exp.pop(k); rec["edits"].pop(k, None); rec["ver"] += 1; self.dirty.add(p)
                out.setdefault(p, []).append([face, u, v, k[2]])
        return out

    # -- FIRE ------------------------------------------------------------------------------------------------------------
    def _cell_key(self, face, u, v, h):
        p = plot_of(face, u, v)
        return p, (u - (p % FACE_N) * PLOT, v - ((p // FACE_N) % FACE_N) * PLOT, h)

    async def _may_burn(self, p, who, cache):
        if p not in cache:
            cache[p] = (await self.holder(p)) is None or await self.may_build(p, who)
        return cache[p]

    def _set(self, face, u, v, h, b, out, natural=None):
        """Write cell (face, u, v, h) = b as an edit; back to the untouched planet when b is what the planet holds there
        (a burnt-out fire cell in open air), so fire leaves no stray edits behind."""
        p, k = self._cell_key(face, u, v, h)
        rec = self.plot(p)
        if natural is not None and b == natural:
            rec["edits"].pop(k, None)
            rec.get("exp", {}).pop(k, None)
        else:
            rec["edits"][k] = b
            if p not in self.titles:                       # the commons heals: what burnt there grows back like any edit
                rec.setdefault("exp", {})[k] = time.time() + RULES["wilderness_regrow_s"]
        rec["ver"] += 1
        self.dirty.add(p)
        out.setdefault(p, []).append([face, u, v, h, b])

    def _pieces_near(self, p, face, u, v, h):
        """The burning-material pieces on plot p within reach of the cell (face, u, v, h): its cube grown by half a metre."""
        rec = self.plots.get(p)
        if not rec or not rec.get("boxes"):
            return []
        fc, fr = p % FACE_N, (p // FACE_N) % FACE_N
        x0, z0, y0 = (u - fc * PLOT) * 100 - 50, (v - fr * PLOT) * 100 - 50, h * 100 - 50
        return [b for b in rec["boxes"] if b[6] in PIECE_BURNS and b[0] < x0 + 200 and b[0] + b[3] > x0
                and b[1] < z0 + 200 and b[1] + b[4] > z0 and b[2] < y0 + 200 and b[2] + b[5] > y0]

    async def ignite(self, who, cell):
        """Light a fire in air cell `cell` beside something that burns, with a fire-making tool (class "fire"), where the
        caller may build. Returns (applied, error)."""
        try:
            face, u, v, h = (int(x) for x in cell)
        except Exception:
            return {}, "a cell is [face, u, v, h]"
        if not (0 <= face < 6 and 0 <= u < W and 0 <= v < W and DEEP_MIN <= h < H):
            return {}, "out of the world"
        pl = self.player(who)
        if not self._has_class(pl, "fire"):
            return {}, "you need something to make fire with — a bow drill (sticks and cordage) or flint and steel"
        p, _ = self._cell_key(face, u, v, h)
        if not await self._may_burn(p, who, {}):
            return {}, "not your plot — you can light a fire only where you may build"
        if len(self.fires) >= FIRE_MAX:
            return {}, "too many fires burn already"
        near = [[face, u + du, v + dv, h + dh] for du, dv, dh in NEIGH6]
        at = await self.blocks_at([[face, u, v, h]] + near)
        if at[(face, u, v, h)] != 0:
            return {}, "a fire needs air to burn in"
        if not any(at[tuple(c)] in BURNS for c in near) and not self._pieces_near(p, face, u, v, h):
            return {}, "nothing here burns — light it beside grass, wood, leaves, thatch or planks"
        if not self.work(who, 2.0 / self._speed(pl, "fire")):
            return {}, "too fast — making fire takes time"
        out = {}
        self._set(face, u, v, h, FIRE, out)
        self.fires[(face, u, v, h)] = {"by": who, "age": 0}
        return out, None

    async def fire_tick(self):
        """One FIRE tick. Returns (cell edits {plot: [[face, u, v, h, block]]}, pieces burnt {plot: [box]})."""
        out, burnt, cache = {}, {}, {}
        fires = list(self.fires.items())
        if not fires:
            return out, burnt
        look = set()
        for (face, u, v, h), _ in fires:
            for du, dv, dh in NEIGH6:
                look.add((face, u + du, v + dv, h + dh))
        at = await self.blocks_at([list(c) for c in look])
        for (face, u, v, h), f in fires:
            if (face, u, v, h) not in self.fires:
                continue
            f["age"] += 1
            p, _ = self._cell_key(face, u, v, h)
            fuel = [(face, u + du, v + dv, h + dh) for du, dv, dh in NEIGH6 if at.get((face, u + du, v + dv, h + dh)) in BURNS]
            fuel = [c for c in fuel if await self._may_burn(self._cell_key(*c)[0], f["by"], cache)]
            pieces = self._pieces_near(p, face, u, v, h) if await self._may_burn(p, f["by"], cache) else []
            if (not fuel and not pieces) or f["age"] > FIRE_LIFE:
                self.fires.pop((face, u, v, h), None)
                self._set(face, u, v, h, 0, out, natural=0)       # it goes out: open air again
                continue
            for c in fuel:                                         # burn what is beside it
                self.burning[c] = self.burning.get(c, 0) + 1
                if self.burning[c] >= BURN_TICKS.get(at[c], 3):
                    self.burning.pop(c, None)
                    self._set(*c, BURNS[at[c]], out)
                    at[c] = BURNS[at[c]]
            # it catches the air around it — upward more readily — where something beside that air burns (checked
            # below): so flames run along a meadow (the air over the next grass) and lick up a trunk (the air beside it)
            for du, dv, dh in NEIGH6:
                q = (face, u + du, v + dv, h + dh)
                if q in self.fires or len(self.fires) >= FIRE_MAX:
                    continue
                if random.random() < (SPREAD_UP if dh > 0 else SPREAD_SIDE):
                    self.fires[q] = {"by": f["by"], "age": 0, "pending": True}
            for b in pieces:                                       # a built piece burns down whole
                key = (p, chest_key(b))
                self.burning[key] = self.burning.get(key, 0) + 1
                if self.burning[key] >= PIECE_TICKS:
                    self.burning.pop(key, None)
                    rec = self.plots[p]
                    if b in rec["boxes"]:
                        rec["boxes"].remove(b)
                        if "index" in rec:
                            rec["index"].remove(b)
                        (rec.get("chests") or {}).pop(chest_key(b), None)  # what a burnt chest held burns with it
                        rec["ver"] += 1
                        self.dirty.add(p)
                        burnt.setdefault(p, []).append(b)
        # the cells the fires caught: only where open air is, and only where the starter may build
        pend = [c for c, f in self.fires.items() if f.get("pending") and 0 <= c[1] < W and 0 <= c[2] < W and DEEP_MIN <= c[3] < H]
        for c in [c for c, f in self.fires.items() if f.get("pending") and c not in pend]:
            self.fires.pop(c, None)
        if pend:
            near = {c: [(c[0], c[1] + du, c[2] + dv, c[3] + dh) for du, dv, dh in NEIGH6] for c in pend}
            now_at = await self.blocks_at([list(c) for c in pend] + [list(q) for qs in near.values() for q in qs])
            for c in pend:
                f = self.fires[c]
                f.pop("pending", None)
                fuel = any(now_at.get(q) in BURNS for q in near[c]) or self._pieces_near(self._cell_key(*c)[0], *c)
                ok = (now_at.get(c) == 0 and fuel and await self._may_burn(self._cell_key(*c)[0], f["by"], cache))
                if ok:
                    self._set(*c, FIRE, out)
                else:
                    self.fires.pop(c, None)
        return out, burnt

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
            b = normal_box(b) if isinstance(b, (list, tuple)) else b
            if b not in rec["boxes"]:
                refused.append([b, "no such piece here"]); continue
            if b[6] == CHEST and (rec.get("chests") or {}).get(chest_key(b)):
                refused.append([b, "empty the chest first"]); continue          # its items are never lost with it
            rule = RULES["breaking"].get(str(b[6])) or {"hard": 1.0}
            unit = RULES["items"][places[b[6]]].get("unit")
            speed = self._speed(pl, rule.get("class"))
            if not self.work(who, max(0.05, rule["hard"] * (1 if unit else box_vol(b) / BLOCK_CM3) / speed * self.fed_work(pl))):
                refused.append([b, "too fast — taking a piece down takes time"]); continue
            rec["boxes"].remove(b)
            idx.remove(b)
            if unit:                                                # a door comes back as the door it was
                pl["items"][places[b[6]]] = pl["items"].get(places[b[6]], 0) + 1
            else:
                self._refund(pl, places[b[6]], box_vol(b))
            removed.append(b)
        for b in add:
            b = normal_box(b) if isinstance(b, (list, tuple)) else b
            if not box_ok(b) or b[6] not in places:
                refused.append([b, "a piece is [x, z, y, w, d, h, material] in whole cm inside the plot, of a material you can place"]); continue
            if len(rec["boxes"]) >= MAX_BOXES:
                refused.append([b, f"a plot holds at most {MAX_BOXES} pieces"]); continue
            if idx.overlaps(b):
                refused.append([b, "it would overlap another piece"]); continue
            # UNIT ITEMS (a door): made whole, placed whole at their own size (either way round), one per piece
            unit = RULES["items"][places[b[6]]].get("unit")
            if unit:
                if sorted(b[3:5]) != sorted(unit[:2]) or b[5] != unit[2] or len(b) > 7:
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

    # -- FACTORIES (#148)
    async def set_machine(self, who, p, b, recipe):
        """Choose what machine `b` on plot `p` makes (its owner and their builders; in the commons anyone). recipe None
        just reads it. Returns (its record, the recipes it can run, error)."""
        rec = self.plots.get(p)
        b = list(b) if isinstance(b, (list, tuple)) else b
        if not rec or not isinstance(b, list) or b not in rec.get("boxes", []) or b[6] not in (SMELTER, ASSEMBLER, GENERATOR):
            return None, [], "no machine here"
        if b[6] == GENERATOR:
            return {"charge": (rec.get("gens") or {}).get(chest_key(b), 0)}, [], None
        can = [r["id"] for r in RULES["recipes"] if machine_can(b[6], r)]
        cfg = (rec.get("machines") or {}).get(chest_key(b)) or {"recipe": None, "status": "idle", "made": 0}
        if recipe is None:
            return cfg, can, None
        if (await self.holder(p)) is not None and not await self.may_build(p, who):
            return None, can, "not your plot — only its owner and the builders they invite set its machines"
        if recipe not in can:
            return None, can, "this machine cannot make that"
        cfg = rec.setdefault("machines", {})[chest_key(b)] = {"recipe": recipe, "status": "idle", "made": 0}
        self.dirty.add(p)
        return cfg, can, None

    def factory_tick(self):
        """One run of every machine that can run: power from a generator near (burning a fuel from the chest beside it when
        its charge is spent), inputs from the chests touching the machine, the product into a touching chest with room.
        Each machine's status says why it waits. Returns the plots whose chests changed."""
        changed = set()
        recipes = {r["id"]: r for r in RULES["recipes"]}
        for p, rec in list(self.plots.items()):
            cfgs = rec.get("machines")
            if not cfgs:
                continue
            boxes = rec.get("boxes", [])
            bykey = {chest_key(b): b for b in boxes if b[6] in (SMELTER, ASSEMBLER)}
            for key in [k for k in cfgs if k not in bykey]:            # a machine taken down forgets its recipe
                del cfgs[key]; self.dirty.add(p)
            store = rec.setdefault("chests", {})
            for key, cfg in cfgs.items():
                b, r = bykey[key], recipes.get(cfg.get("recipe"))
                def status(st):
                    if cfg.get("status") != st:
                        cfg["status"] = st; self.dirty.add(p)
                if not r:
                    status("idle"); continue
                chests = [c for c in boxes if c[6] == CHEST and boxes_touch(c, b)]
                if not chests:
                    status("no chest beside it"); continue
                have = {}
                for c in chests:
                    for item, n in store.get(chest_key(c), {}).items():
                        have[item] = have.get(item, 0) + n
                short = [item for item, n in r["uses"] if have.get(item, 0) < n]
                if short:
                    status("needs " + RULES["items"][short[0]]["name"].lower()); continue
                made = sum(n for _, n in r["makes"])
                out = next((c for c in chests if sum(store.get(chest_key(c), {}).values()) + made <= CHEST_MAX), None)
                if not out:
                    status("its chest is full"); continue
                # power: the nearest generator in reach with charge, or one that can burn a fuel beside it
                reach = MACH["power_reach"] * CM
                gens = sorted((g for g in boxes if g[6] == GENERATOR and math.dist(centre(g), centre(b)) <= reach), key=lambda g: math.dist(centre(g), centre(b)))
                charges = rec.setdefault("gens", {})
                gen = None
                for g in gens:
                    gk = chest_key(g)
                    if charges.get(gk, 0) <= 0:
                        for fc in (c for c in boxes if c[6] == CHEST and boxes_touch(c, g)):
                            fs = store.get(chest_key(fc), {})
                            fuel = next((f for f in MACH["fuel"] if fs.get(f, 0) > 0), None)
                            if fuel:
                                fs[fuel] -= 1
                                if not fs[fuel]:
                                    del fs[fuel]
                                charges[gk] = charges.get(gk, 0) + MACH["fuel"][fuel]
                                changed.add(p); break
                    if charges.get(gk, 0) > 0:
                        gen = gk; break
                if not gen:
                    status("no power — a generator with coal or charcoal beside it, within %d m" % MACH["power_reach"]); continue
                for item, n in r["uses"]:                              # take from the chests beside it, in order
                    for c in chests:
                        cs = store.get(chest_key(c), {})
                        k = min(n, cs.get(item, 0))
                        if k:
                            cs[item] -= k; n -= k
                            if not cs[item]:
                                del cs[item]
                        if not n:
                            break
                os_ = store.setdefault(chest_key(out), {})
                for item, n in r["makes"]:
                    os_[item] = os_.get(item, 0) + n
                charges[gen] -= 1
                cfg["made"] = cfg.get("made", 0) + 1
                status("running")
                changed.add(p); self.dirty.add(p)
        return changed

    # -- FLIGHT (#147): board, fly, leave, dock
    async def board(self, who, p=None, b=None, cid=None):
        """Take the pilot seat. Of a parked craft `cid` (its owner only), or of seat piece `b` on plot `p`: the pieces
        touching it (connected) become a new craft, lifted off the plot — where the caller may build, holding at least one
        thruster. Returns (craft, the plot's removed pieces, error)."""
        if cid is not None:
            c = self.crafts.get(cid)
            if not c:
                return None, [], "no such craft"
            if c["owner"] != who:
                return None, [], "only its owner flies it"
            if c["pilot"] and c["pilot"] != who:
                return None, [], "someone is flying it"
            c["pilot"] = who; c["at"] = time.time(); self.cdirty = True
            return c, [], None
        rec = self.plots.get(p)
        b = list(b) if isinstance(b, (list, tuple)) else b
        if not rec or not isinstance(b, list) or b not in rec.get("boxes", []) or b[6] != SEAT:
            return None, [], "no pilot seat here"
        if (await self.holder(p)) is not None and not await self.may_build(p, who):
            return None, [], "not your plot — only its owner and the builders they invite take off from it"
        parts = connected(rec["boxes"], b)
        if len(parts) > CRAFT_PIECES:
            return None, [], f"a craft holds at most {CRAFT_PIECES} pieces"
        if not any(x[6] == THRUSTER for x in parts):
            return None, [], "a craft needs a thruster touching it"
        if sum(1 for x in parts if x[6] == SEAT) != 1:
            return None, [], "one pilot seat to a craft"
        face, row, col = plot_coords(p)
        sx, sz, sy = b[0] + b[3] / 2, b[1] + b[4] / 2, b[2]
        pieces = [[x[0] - sx, x[1] - sz, x[2] - sy] + list(x[3:]) for x in parts]
        cid = secrets.token_hex(6)
        c = self.crafts[cid] = {"id": cid, "owner": who, "pilot": who, "pieces": pieces,
                                "pose": [face, col * PLOT + sx / CM, row * PLOT + sz / CM, sy / CM, 0.0], "at": time.time(),
                                "mass": round(craft_mass(pieces), 3), "thrust": craft_thrust(pieces)}
        if "index" not in rec:
            rec["index"] = BoxIndex(rec["boxes"])
        for x in parts:
            rec["boxes"].remove(x); rec["index"].remove(x)
        rec["ver"] += 1
        self.dirty.add(p); self.cdirty = True
        return c, parts, None

    def fly(self, who, cid, pose):
        """The pilot's page says where the craft is. Taken when it is in the world and no farther from the last pose than
        the craft's top speed allows (CRAFT_SLACK for a bunched network); otherwise refused, and the page is told the
        pose the server holds. Returns error or None."""
        c = self.crafts.get(cid)
        if not c or c["pilot"] != who:
            return "you are not flying that"
        if not (isinstance(pose, list) and len(pose) == 5 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in pose)
                and pose[0] == c["pose"][0] and 0 <= pose[1] < W and 0 <= pose[2] < W and DEEP_MIN <= pose[3] < H + 400):
            return "not a place"
        now = time.time()
        far = math.dist(pose[1:4], c["pose"][1:4])
        if far > FLIGHT["vmax"] * max(0.05, now - c["at"]) + CRAFT_SLACK:
            return "faster than it can fly"
        c["pose"] = [int(pose[0]), round(float(pose[1]), 3), round(float(pose[2]), 3), round(float(pose[3]), 3), round(float(pose[4]), 4)]
        c["at"] = now; self.cdirty = True
        return None

    def leave(self, who, cid):
        c = self.crafts.get(cid)
        if not c or c["pilot"] != who:
            return "you are not flying that"
        c["pilot"] = None; self.cdirty = True
        return None

    async def dock(self, who, cid):
        """Set a parked craft down as pieces on the plot under its seat — its owner, where they may build, its yaw taken to
        the nearest quarter turn (pieces stand square on a plot); every piece inside that plot and clear of the pieces
        there. Returns (plot, added pieces, error)."""
        c = self.crafts.get(cid)
        if not c or c["owner"] != who:
            return None, [], "not your craft"
        if c["pilot"] and c["pilot"] != who:
            return None, [], "someone is flying it"
        face, u, v, h, yaw = c["pose"]
        p = plot_of(face, int(u), int(v))
        if (await self.holder(p)) is not None and not await self.may_build(p, who):
            return None, [], "not your plot — land where you may build to set it down"
        _, row, col = plot_coords(p)
        quarter = round(yaw / (math.pi / 2)) % 4
        ox, oz, oy = round((u - col * PLOT) * CM), round((v - row * PLOT) * CM), round(h * CM)
        add = [[round(x[0]) + ox, round(x[1]) + oz, round(x[2]) + oy] + list(x[3:]) for x in turn_pieces(c["pieces"], quarter)]
        if not all(box_ok(x) for x in add):
            return None, [], "it does not fit inside this plot — land with all of it over one plot"
        rec = self.plot(p)
        rec.setdefault("boxes", [])
        if "index" not in rec:
            rec["index"] = BoxIndex(rec["boxes"])
        if any(rec["index"].overlaps(x) for x in add):
            return None, [], "it would overlap a piece here"
        for x in add:
            rec["boxes"].append(x); rec["index"].add(x)
        rec["ver"] += 1
        del self.crafts[cid]
        self.dirty.add(p); self.cdirty = True
        return p, add, None

    def crafts_near(self, pos, near):
        return [c for c in self.crafts.values() if c["pose"][0] == pos[0] and abs(c["pose"][1] - pos[1]) < near and abs(c["pose"][2] - pos[2]) < near]

    async def chest(self, who, p, b, put, take):
        """Move items between the caller's bag and chest `b` on plot `p` (#114): `put` and `take` are {item: count}. On an
        owned plot only its owner and their builders open it; in the commons a chest is everyone's. All or nothing: a
        call that cannot move everything it names moves nothing. Returns (the chest's items, error)."""
        rec = self.plots.get(p)
        b = list(b) if isinstance(b, (list, tuple)) else b
        if not rec or not isinstance(b, list) or b not in rec.get("boxes", []) or b[6] != CHEST:
            return None, "no such chest here"
        if (await self.holder(p)) is not None and not await self.may_build(p, who):
            return None, "not your plot — only its owner and the builders they invite open its chests"
        if not isinstance(put, dict) or not isinstance(take, dict):
            return None, "put and take are {item: count}"
        store = dict((rec.get("chests") or {}).get(chest_key(b), {}))
        pl = self.player(who)
        bag = dict(pl["items"])
        for src, dst, moves in ((bag, store, put), (store, bag, take)):
            for item, n in moves.items():
                if item not in RULES["items"] or not isinstance(n, int) or isinstance(n, bool) or n <= 0:
                    return None, "an item and a whole count"
                if src.get(item, 0) < n:
                    return None, f"not enough {RULES['items'][item]['name'].lower()}"
                src[item] -= n
                dst[item] = dst.get(item, 0) + n
        if sum(store.values()) > CHEST_MAX:
            return None, f"a chest holds at most {CHEST_MAX} items"
        pl["items"] = {k: v for k, v in bag.items() if v}
        rec.setdefault("chests", {})[chest_key(b)] = {k: v for k, v in store.items() if v}
        rec["ver"] += 1
        self.dirty.add(p); self.pdirty.add(who)
        return rec["chests"][chest_key(b)], None

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
        now = time.time()
        self.sessions = {k: v for k, v in self.sessions.items() if v["until"] > now}
        self.sessions[sid(token)] = {"address": address, "until": now + SESSION_TTL}
        self._write("sessions.json", self.sessions)
        return token

    def end_session(self, token):
        if self.sessions.pop(sid(token or ""), None):
            self._write("sessions.json", self.sessions)

    def who(self, request):
        tok = request.cookies.get("land_session") or ""
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            tok = auth[7:].strip()
        tok = tok or request.query.get("token", "")
        s = self.sessions.get(sid(tok)) if tok else None
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

    async def chat(self, sender, who, text):
        """A chat line to every socket whose watched plots meet the sender's (its own included)."""
        near = sender["watch"]
        for ws, st in list(self.socks.items()):
            if st is sender or st["watch"] & near:
                try:
                    await ws.send_json({"t": "chat", "who": who, "text": text})
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

    async def positions(self, world=None):
        socks = list(self.socks.items())
        for ws, st in socks:
            me = st["pos"]
            if not me:
                continue
            # each player near comes with their look (CLOTHES): what they wear, their skin and hair
            near = [{"id": o["id"], "who": o["who"], "p": o["pos"], **({"look": world.look_of(o["who"])} if world and o["who"] else {})}
                    for w2, o in socks
                    if w2 is not ws and o["pos"] and o["pos"][0] == me[0]
                    and abs(o["pos"][1] - me[1]) < self.NEAR and abs(o["pos"][2] - me[2]) < self.NEAR]
            # FLIGHT: the crafts near, flying or parked — each one's pieces once per socket, then its pose
            crafts = []
            if world:
                seen = st.setdefault("crafts_seen", set())
                for c in world.crafts_near(me, self.NEAR):
                    o = {"id": c["id"], "owner": c["owner"], "pilot": c["pilot"], "pose": c["pose"], "mass": c["mass"], "thrust": c["thrust"]}
                    if c["id"] not in seen:
                        o["pieces"] = c["pieces"]; seen.add(c["id"])
                    crafts.append(o)
            try:
                await ws.send_json({"t": "players", "list": near, "crafts": crafts})
            except Exception:
                pass


def make_app(world, hub, site_origin, wallet_url, secure_cookies=True, shot_page=None):
    async def on_start(app):
        world.http = ClientSession(timeout=ClientTimeout(total=10))
        await world.start_oracle()
        app["bg"] = [asyncio.ensure_future(_flusher()), asyncio.ensure_future(_mover()), asyncio.ensure_future(_regrower()),
                     asyncio.ensure_future(_ecology()), asyncio.ensure_future(_fire()), asyncio.ensure_future(_factory())]
        if shot_page:
            app["bg"].append(asyncio.ensure_future(_photographer()))

    async def on_stop(app):
        for t in app.get("bg", []):
            t.cancel()
        world.flush()
        await world.http.close()
        if world.oracle and world.oracle.returncode is None:
            world.oracle.kill()
            await world.oracle.wait()                         # reaped here, not by a finalizer after the loop is gone

    async def _photographer():
        """THE LISTING: one plot's photo at a time, asked-for plots first, then every title without a current one."""
        await asyncio.sleep(30)
        while True:
            try:
                await world.refresh_titles()
                p = world.next_shot()
                if p is None:
                    await asyncio.sleep(60)
                    continue
                await world.shoot(p, shot_page)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await asyncio.sleep(5)

    async def _regrower():
        while True:
            await asyncio.sleep(5)
            try:
                # (never around a player present: the regrowth buried one at the bottom of their shaft)
                back = world.regrow([st["pos"] for st in hub.socks.values() if st.get("pos")])
                if back:
                    await hub.reverts(back)
            except Exception:
                pass

    async def _ecology():
        n = 0
        while True:
            await asyncio.sleep(10)
            n += 1
            try:
                grown = await world.grow()
                if grown:
                    await hub.edits(grown, "planet")
                if n % (SPREAD_S // 10) == 0:
                    spread = await world.spread()
                    if spread:
                        await hub.edits(spread, "planet")
                if n % (SEED_S // 10) == 0:
                    seeded = await world.seed()
                    if seeded:
                        await hub.edits(seeded, "planet")
            except Exception:
                pass

    async def _factory():
        while True:
            await asyncio.sleep(MACH["tick_s"])
            try:
                world.factory_tick()
            except Exception:
                pass

    async def _fire():
        while True:
            await asyncio.sleep(FIRE_TICK)
            try:
                out, burnt = await world.fire_tick()
                if out:
                    await hub.edits(out, "fire")
                for p, bs in burnt.items():
                    await hub.boxes(p, [], bs, "fire")
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
            await hub.positions(world)

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
        world.end_session(tok)
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

    # THE LISTING is public and read across origins (the NFT market's page shows a title's photo and card), so these two
    # answer any origin; they never read a session
    LISTING_CORS = {"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=60"}

    def _plot_q(request):
        try:
            p = int(request.query["plot"])
        except Exception:
            raise web.HTTPBadRequest(text="?plot=<id>")
        if not 0 <= p < 6 * FACE_N * FACE_N:
            raise web.HTTPBadRequest(text="no such plot")
        return p

    async def crafts_api(request):
        """GET /land/api/crafts?face=&u=&v= -> {crafts: [...]}: the crafts within 192 m, flying or parked (FLIGHT, #147) —
        what a page near them is sent, read-only, for agents and tests."""
        try:
            f, u, v = int(request.query.get("face", 0)), float(request.query["u"]), float(request.query["v"])
        except (KeyError, ValueError):
            raise web.HTTPBadRequest(text="face, u and v")
        return web.json_response({"crafts": world.crafts_near([f, u, v], Hub.NEAR)})

    async def card(request):
        p = _plot_q(request)
        out = await world.card(p)
        if world.shot_due(p) and p not in world.shot_want and len(world.shot_want) < 64:
            world.shot_want.append(p)                         # asked for (a sale opens with this): photographed next
        return web.json_response(out, headers=LISTING_CORS)

    async def shot(request):
        p = _plot_q(request)
        path = os.path.join(world.shots, f"{p}.jpg")
        if not os.path.exists(path):
            raise web.HTTPNotFound(text="not photographed yet", headers=LISTING_CORS)
        return web.FileResponse(path, headers=dict(LISTING_CORS, **{"Content-Type": "image/jpeg"}))

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

    async def eat(request):
        addr, d = need_addr(request), await request.json()
        err = world.eat(addr, d.get("item"))
        if not err:
            await hub.inv(world, addr)
        return web.json_response({"ok": not err, "error": err, "inventory": world.inv_json(addr)})

    async def draw_well(request):
        addr, d = need_addr(request), await request.json()
        err = await world.well(addr, d.get("plot"), d.get("box"))
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
        # A PLAYER'S LAST PLACE is kept with them (not only in one browser's storage): a signed-in player who comes back —
        # on any device, in any browser — is put where they left off ("why did i respawn somewhere off again", 2026-11-07)
        await ws.send_json({"t": "hello", "you": addr, "id": st["id"],
                            **({"pos": world.player(addr).get("pos"), "pos_at": world.player(addr).get("pos_at")} if addr else {})})
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
                    if (isinstance(p, list) and len(p) == 5 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in p)
                            and 0 <= p[0] < 6 and 0 <= p[1] < W and 0 <= p[2] < W and DEEP_MIN <= p[3] < H + 400):
                        st["pos"] = [int(p[0]), float(p[1]), float(p[2]), float(p[3]), float(p[4])]
                        if addr and time.time() - st.get("pos_at", 0) > POS_SAVE_S:
                            world.keep_place(addr, st["pos"]); st["pos_at"] = time.time()
                elif t == "set":
                    if not addr:
                        await ws.send_json({"t": "set_ok", "applied": 0, "refused": [[None, "sign in to build"]], "req": m.get("req")})
                        continue
                    applied, refused, changed = await world.apply(addr, m.get("cells"))
                    await ws.send_json({"t": "set_ok", "applied": sum(len(c) for c in applied.values()), "refused": refused, "req": m.get("req")})
                    await hub.edits(applied, addr)
                    if changed:
                        await hub.inv(world, addr)
                elif t == "chat":
                    # the console's chat: one line to every socket watching any plot the sender watches (the players
                    # around them), signed-in only, one line a second, 200 characters, no control characters
                    if not addr:
                        await ws.send_json({"t": "chat_ok", "error": "sign in to chat"})
                        continue
                    text = "".join(ch for ch in str(m.get("text") or "")[:200] if ch >= " " and ch != "\x7f").strip()
                    if not text or time.time() - st.get("chat_at", 0) < 1.0:
                        continue
                    st["chat_at"] = time.time()
                    await hub.chat(st, addr, text)
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
                elif t == "machine":
                    # FACTORIES (#148): read a machine (what it makes, its status, what it can make) or choose its recipe
                    if not addr:
                        await ws.send_json({"t": "machine", "req": m.get("req"), "error": "sign in first"})
                        continue
                    cfg, can, err = await world.set_machine(addr, m.get("plot"), m.get("box"), m.get("recipe"))
                    await ws.send_json({"t": "machine", "req": m.get("req"), "plot": m.get("plot"), "box": m.get("box"), "cfg": cfg, "can": can, "error": err})
                elif t in ("board", "fly", "leave", "dock"):
                    # FLIGHT (#147): take the seat, say where the craft is, leave it parked, set it down as pieces
                    if not addr:
                        await ws.send_json({"t": "craft_ok", "req": m.get("req"), "error": "sign in first"})
                        continue
                    if t == "board":
                        c, parts, err = await world.board(addr, m.get("plot"), m.get("box"), m.get("craft"))
                        await ws.send_json({"t": "craft_ok", "op": t, "req": m.get("req"), "error": err, "craft": c})
                        if parts:
                            await hub.boxes(m.get("plot"), [], parts, addr)
                            for s2 in hub.socks.values():                # every page draws the new craft afresh
                                s2.get("crafts_seen", set()).discard(c["id"])
                    elif t == "fly":
                        err = world.fly(addr, m.get("craft"), m.get("pose"))
                        if err and m.get("craft") in world.crafts:
                            await ws.send_json({"t": "craft_fix", "craft": m.get("craft"), "pose": world.crafts[m.get("craft")]["pose"], "error": err})
                    elif t == "leave":
                        await ws.send_json({"t": "craft_ok", "op": t, "req": m.get("req"), "error": world.leave(addr, m.get("craft"))})
                    else:
                        p, added, err = await world.dock(addr, m.get("craft"))
                        await ws.send_json({"t": "craft_ok", "op": t, "req": m.get("req"), "error": err, "plot": p})
                        if added:
                            await hub.boxes(p, added, [], addr)
                            for s2 in hub.socks.values():
                                s2.get("crafts_seen", set()).discard(m.get("craft"))
                elif t == "ignite":
                    if not addr:
                        await ws.send_json({"t": "ignite", "req": m.get("req"), "error": "sign in first"})
                        continue
                    applied, err = await world.ignite(addr, m.get("cell") or [])
                    await ws.send_json({"t": "ignite", "req": m.get("req"), "error": err})
                    if applied:
                        await hub.edits(applied, addr)
                elif t in ("wear", "look"):
                    if not addr:
                        await ws.send_json({"t": "done", "req": m.get("req"), "error": "sign in first"})
                        continue
                    err = world.wear(addr, m.get("slot"), m.get("item")) if t == "wear" else world.set_look(addr, m.get("skin"), m.get("hair"), m.get("body"), m.get("face"))
                    await ws.send_json({"t": "done", "req": m.get("req"), "error": err})
                    if not err:
                        await hub.inv(world, addr)
                elif t == "chest":
                    if not addr:
                        await ws.send_json({"t": "chest", "req": m.get("req"), "error": "sign in first"})
                        continue
                    items, err = await world.chest(addr, m.get("plot"), m.get("box"), m.get("put") or {}, m.get("take") or {})
                    await ws.send_json({"t": "chest", "req": m.get("req"), "plot": m.get("plot"), "box": m.get("box"),
                                        "items": items, "error": err})
                    if not err:
                        await hub.inv(world, addr)
                elif t in ("eat", "well"):                         # FOOD AND WATER (#155)
                    if not addr:
                        await ws.send_json({"t": "done", "req": m.get("req"), "error": "sign in first"})
                        continue
                    err = world.eat(addr, m.get("item")) if t == "eat" else await world.well(addr, m.get("plot"), m.get("box"))
                    await ws.send_json({"t": "done", "req": m.get("req"), "op": t, "error": err})
                    if not err:
                        await hub.inv(world, addr)
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
            if addr and st.get("pos"):
                world.keep_place(addr, st["pos"])               # where they stood when they left
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
        web.get("/land/api/card", card),
        web.get("/land/api/crafts", crafts_api),
        web.get("/land/api/shot", shot),
        web.post("/land/api/set", set_cells),
        web.post("/land/api/boxes", boxes),
        web.get("/land/api/inventory", inventory),
        web.post("/land/api/craft", craft),
        web.post("/land/api/give", give),
        web.post("/land/api/eat", eat),
        web.post("/land/api/well", draw_well),
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
    ap.add_argument("--shot-page", default="", help="the Land page the photographer opens (default: --site; 'off' = none)")
    a = ap.parse_args()
    src = open(os.path.join(REPO, "static", "land.js")).read()
    cid = (src.split('const CID = "', 1)[1].split('"', 1)[0]) if 'const CID = "' in src else ""
    world = World(a.data, a.exec, cid)
    page = None if a.shot_page == "off" else (a.shot_page or a.site).rstrip("/")
    web.run_app(make_app(world, Hub(), a.site.rstrip("/"), a.wallet.rstrip("/"), shot_page=page), host="127.0.0.1", port=a.port, access_log=None)


if __name__ == "__main__":
    main()
