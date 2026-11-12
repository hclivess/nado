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
import argparse, asyncio, hashlib, json, math, random, re, secrets, shutil, time, urllib.parse

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
N_BLOCKS = 85                     # static/land-world.js BLOCKS.length (tests/test_the_land_planet_… checks the two agree)
DOOR = 37                         # static/land-world.js B.door: a piece that swings open and shut ("door" op)
THRUSTER, SEAT = 65, 66           # static/land-world.js B.thruster, B.pilotseat: a craft's working parts (FLIGHT, #147)
SMELTER, ASSEMBLER, GENERATOR = 67, 68, 69   # static/land-world.js: FACTORIES (#148) — machines and their power
ROCKET_ENGINE, PROP_TANK, SATELLITE, LAUNCH_PAD = 81, 82, 83, 84   # static/land-world.js: ROCKETS (#173)
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
SEA = 96                          # static/land-world.js SEA: the sea surface layer (animals keep to dry land)
STAND = 75                        # static/land-world.js B.stand: a trading stand — offers are made and taken at one (#161)
BED = 48                          # static/land-world.js B.bed: Use on one and a player wakes there after a death (#162)
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
# scripts/land_town.py: the town is the four central plots of the first wave (face 0, rows 4999-5000, cols 3439-3440)
TOWN_PLOTS = frozenset(r * FACE_N + c for r in (4999, 5000) for c in (3439, 3440))
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
# TRAVEL (#167, operator 2026-11-10, "pick recommended"): a cell was broken anywhere on the planet without going there
# (the town agent dug ore 48 m off, standing still), and a page's place jumped anywhere (/tp <u> <v>) — so the local
# markets, a trip to the beach for sand, a hunt, all measured a place that cost nothing to change. Now a block is
# BROKEN only within REACH_M of the breaker's eye (placed too, except on a plot they may build on: an agent builds an
# owner's house from a file, and placing pays from their own bag); a reported place moves at most PACE_MPS over the
# ground (+ PACE_SLACK), counting at most PACE_DT_MAX s since the last one (waiting buys no jump); /tp goes to the
# landing or your own bed only.
REACH_M = 12                      # the page reaches 7 m; its levelling square (shovel, L) works up to ~11 m from the eye
PACE_MPS, PACE_SLACK, PACE_DT_MAX = 65.0, 6.0, 5.0      # free flight's fastest is 60 m/s (static/land.js FLY_FAST)
EYE = 1.62                        # static/land.js EYE: the eye over the feet


def pace_ok(last, last_t, p, now):
    """May a place move from `last` (kept at `last_t`) to `p` by `now`? Over the ground only: a fall or a climb is no
    journey. Another face only from near a face's edge (walking over it)."""
    if not last:
        return True
    reach = PACE_MPS * max(0.0, min(now - last_t, PACE_DT_MAX)) + PACE_SLACK
    if int(p[0]) != int(last[0]):
        return min(last[1], last[2], W - last[1], W - last[2]) <= reach
    return math.hypot(p[1] - last[1], p[2] - last[2]) <= reach


WAKE_NEAR = 8.0                   # metres: a page this near the place its dead player wakes has woken (#176)
def landing():
    """Where the landing is (static/land.js townSpawn): the town hall's door, its height left to the page."""
    face, row, col = plot_coords(TOWN_HALL_PLOT)
    return [face, col * PLOT + 8.5, row * PLOT + 1.5]
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


ROT_MAX = 1800                                     # land-world.js ROTATION (#169): yaw, pitch, roll in tenths of a degree


# PARTS (#175, static/land-shapes.js — read its header): from 16 a piece's shape byte is a modelled solid filling its own
# box, 16 + 10 x type + variant. The server draws nothing; it holds what a part IS for the rules: which bytes are parts
# (box_ok), how much of its box one fills (part_fill, in thousandths, the SAME whole-number sums as land-shapes.js fill —
# the parts test compares every code across the two), which are hollow skins that take a tenth (PART_SHELL), and that an
# ENGINE is thrusters (engine_count). INVARIANT: a code's meaning is permanent once a plot holds it — a new part is a
# new type appended here AND in land-shapes.js TYPES, never a change to an old one's fill.
PART_FIRST = 16
P_TUBE, P_BODY, P_HULL, P_WING, P_ENGINE, P_CANNON, P_DOME, P_NOSE, P_CANOPY, P_RING = range(10)
PART_VARIANTS = [10, 10, 10, 10, 1, 1, 1, 10, 1, 10]
PART_HOLLOW = {P_HULL, P_NOSE, P_WING, P_CANOPY, P_DOME}
PART_SHELL = 10                   # a hollow part takes a tenth of its solid (land-shapes.js SHELL: a labelled design choice)
THRUSTER_CM3 = 1400000            # the thruster item's own 1.0 x 1.0 x 1.4 m: what one thruster of an engine's volume is


def part_of(s):
    """land-shapes.js decode: (type, variant) of a shape byte, or None for a box, a slope and any byte that is no part."""
    if not isinstance(s, int) or s < PART_FIRST:
        return None
    t, v = (s - PART_FIRST) // 10, (s - PART_FIRST) % 10
    return (t, v) if t < len(PART_VARIANTS) and v < PART_VARIANTS[t] else None


def is_part(b):
    return len(b) > 7 and part_of(b[7]) is not None


def is_engine(b):
    """land-world.js isEngine: the engine part, in the thruster's material (box_ok allows it no other)."""
    return len(b) > 7 and b[6] == THRUSTER and (part_of(b[7]) or (None,))[0] == P_ENGINE


def part_fill(s):
    """land-shapes.js fill: the thousandths of its box a part fills. Whole numbers only, the same sums in the same order."""
    t, v = part_of(s)
    k = v + 1
    if t == P_TUBE:
        return 785 * (100 + 10 * k + k * k) // 300
    if t == P_BODY:
        return 1000 * (100 + 10 * k + k * k) // 300
    if t == P_HULL:
        return 859 * (250 + 25 * k + k * k) // 600
    if t == P_WING:
        return 980 * (260 + 22 * k) // 600
    if t == P_NOSE:
        return 527
    if t == P_RING:
        h = 10 + v
        return 785 * (400 - h * h) // 400
    return {P_ENGINE: 415, P_CANNON: 260, P_DOME: 523, P_CANOPY: 510}[t]


def box_ok(b):
    """land-world.js boxOk: [x, z, y, w, d, h, m] in whole centimetres inside the plot, positive size, a solid material —
    with an 8th number a slope's shape 1..4 (land-world.js SHAPES: a roof needs slopes) or a part's code from 16 (#175;
    an engine only in the thruster's material), and with a 9th-11th its yaw, pitch and roll in tenths of a degree (#169:
    turned about its centre; the turned piece inside the plot)."""
    if not isinstance(b, (list, tuple)) or len(b) not in (7, 8, 11) or not all(isinstance(v, int) and not isinstance(v, bool) for v in b):
        return False
    x, z, y, w, d, h, m = b[:7]
    if not (x >= 0 and z >= 0 and y >= 0 and w >= 1 and d >= 1 and h >= 1 and 0 < m < N_BLOCKS and m != 5):
        return False
    if (len(b) > 7 and not (0 <= b[7] <= 4 or part_of(b[7]))) or (len(b) == 8 and not b[7]):
        return False
    if len(b) > 7 and (part_of(b[7]) or (None,))[0] == P_ENGINE and m != THRUSTER:
        return False                                # an engine is made of thrusters, nothing else (engine_count)
    if len(b) == 11:
        if not all(-ROT_MAX < r <= ROT_MAX for r in b[8:]) or not any(b[8:]):
            return False
        a = box_aabb(b)
        return a[0] >= 0 and a[1] >= 0 and a[2] >= 0 and a[0] + a[3] <= PLOT_CM and a[1] + a[4] <= PLOT_CM and a[2] + a[5] <= H_CM
    return x + w <= PLOT_CM and z + d <= PLOT_CM and y + h <= H_CM


def normal_box(b):
    """land-world.js normalBox: one spelling — a box is 7 numbers, a slope 8, a turned piece 11 (no rotation dropped, a
    trailing shape 0 too)."""
    b = list(b)
    if len(b) > 8 and not any(b[8:11]):
        b = b[:8]
    return b[:7] if len(b) == 8 and not b[7] else b


def turned(b):
    return len(b) > 8 and any(b[8:11])


def rot_of(b):
    return list(b[8:11]) if len(b) > 8 else [0, 0, 0]


def turn_vec(r, v, inverse=False):
    """land-world.js turnVec: [x, z, y] turned by roll, then pitch, then yaw (tenths of a degree)."""
    rad = lambda t: math.radians(t / 10)
    roll = lambda q, a: [q[0] * math.cos(a) - q[2] * math.sin(a), q[1], q[0] * math.sin(a) + q[2] * math.cos(a)]
    pitch = lambda q, a: [q[0], q[1] * math.cos(a) - q[2] * math.sin(a), q[1] * math.sin(a) + q[2] * math.cos(a)]
    yaw = lambda q, a: [q[0] * math.cos(a) - q[1] * math.sin(a), q[0] * math.sin(a) + q[1] * math.cos(a), q[2]]
    if not inverse:
        return yaw(pitch(roll(v, rad(r[2])), rad(r[1])), rad(r[0]))
    return roll(pitch(yaw(v, -rad(r[0])), -rad(r[1])), -rad(r[2]))


def box_aabb(b):
    """land-world.js boxAabb: the box [x, z, y, w, d, h] (whole cm, outward) a piece fills, turned or not."""
    if not turned(b):
        return list(b[:6])
    r, c, ex = rot_of(b), [b[0] + b[3] / 2, b[1] + b[4] / 2, b[2] + b[5] / 2], [0.0, 0.0, 0.0]
    for i in range(3):
        e = [0.0, 0.0, 0.0]; e[i] = b[3 + i] / 2
        t = turn_vec(r, e)
        for k in range(3):
            ex[k] += abs(t[k])
    lo = [math.floor(c[k] - ex[k] + 1e-6) for k in range(3)]
    hi = [math.ceil(c[k] + ex[k] - 1e-6) for k in range(3)]
    return [lo[0], lo[1], lo[2], hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]]


def _aabb_overlap(a, b):
    return a[0] < b[0] + b[3] and b[0] < a[0] + a[3] and a[1] < b[1] + b[4] and b[1] < a[1] + a[4] and a[2] < b[2] + b[5] and b[2] < a[2] + a[5]


def boxes_overlap(a, b):
    """land-world.js boxesOverlap: square pieces as boxes; a turned one by the separating axis test of oriented boxes."""
    if not turned(a) and not turned(b):
        return _aabb_overlap(a, b)
    if not _aabb_overlap(box_aabb(a), box_aabb(b)):
        return False
    def axes(p):
        out = []
        for i in range(3):
            e = [0.0, 0.0, 0.0]; e[i] = 1.0
            out.append(turn_vec(rot_of(p), e))
        return out
    A, Bx = axes(a), axes(b)
    ha, hb = [a[3] / 2, a[4] / 2, a[5] / 2], [b[3] / 2, b[4] / 2, b[5] / 2]
    T = [b[k] + b[k + 3] / 2 - a[k] - a[k + 3] / 2 for k in range(3)]
    dot = lambda u, v: u[0] * v[0] + u[1] * v[1] + u[2] * v[2]
    tests = A + Bx
    for u in A:
        for v in Bx:
            c = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
            if math.hypot(*c) > 1e-9:
                tests.append(c)
    for ax in tests:                                          # (never `L`: that is the land contract's module here)
        n = math.hypot(*ax); l = [ax[0] / n, ax[1] / n, ax[2] / n]
        ra = sum(ha[i] * abs(dot(A[i], l)) for i in range(3)); rb = sum(hb[i] * abs(dot(Bx[i], l)) for i in range(3))
        if abs(dot(T, l)) >= ra + rb - 1e-3:
            return False
    return True


def commitment_bytes(plot, salt, edits, boxes=()):
    """land-world.js commitmentBytes, byte for byte (v3: the ground's cell edits, then the built pieces with their shapes)."""
    if len(salt) != 32:
        raise ValueError("salt must be 32 bytes")
    # the deep below a plot is the commons, not the plot's build: never committed (land-world.js commitmentBytes agrees)
    ce, cb = canonical_edits([e for e in edits if e[2] >= 0]), sorted({tuple(normal_box(b)) for b in boxes}, key=lambda b: (b[:7], len(b), b[7:]))
    if not all(box_ok(list(b)) for b in cb):
        raise ValueError("bad box")
    # v4 (#169) only for a plot with a turned piece; every other plot keeps its v3 bytes (and so its anchored commitment)
    v4 = any(turned(b) for b in cb)
    out = bytearray(b"nado-land-plot-v4" if v4 else b"nado-land-plot-v3") + plot.to_bytes(4, "big") + salt + len(ce).to_bytes(4, "big")
    for x, z, y, b in ce:
        out += bytes([x, z, y >> 8, y & 255, b])
    out += len(cb).to_bytes(4, "big")
    for bx in cb:
        x, z, y, w, d, h, m = bx[:7]
        out += b"".join(v.to_bytes(2, "big") for v in (x, z, y, w, d, h)) + bytes([m, bx[7] if len(bx) > 7 else 0])
        if v4:
            out += b"".join((r & 0xFFFF).to_bytes(2, "big") for r in rot_of(bx))
    return bytes(out)


def commitment(plot, salt, edits, boxes=()):
    n = int.from_bytes(hashlib.sha256(commitment_bytes(plot, salt, edits, boxes)).digest(), "big")
    return str(n or 1)


def box_vol(b):
    """cm³ a piece costs (land-world.js boxVolume) — a box its box, a slope (8th number 1..4) half of it, a part (#175) the
    share of its box its shape fills, a tenth of that for a hollow one; never less than 1."""
    box = b[3] * b[4] * b[5]
    if len(b) <= 7 or not b[7]:
        return box
    if not is_part(b):
        return box // 2
    return max(1, box * part_fill(b[7]) // (1000 * (PART_SHELL if part_of(b[7])[0] in PART_HOLLOW else 1)))


def engine_count(b):
    """land-world.js engineCount: how many thrusters a piece is — an engine part as many as its volume comes to (to the
    nearest whole one, never fewer than one), a plain thruster one, anything else none. What an engine costs to place,
    gives back taken down, weighs and pushes."""
    if is_engine(b):
        return max(1, (box_vol(b) + THRUSTER_CM3 // 2) // THRUSTER_CM3)
    return 1 if b[6] == THRUSTER else 0


def buckets_of(b):
    """The 1 m buckets a piece touches: the spatial index that keeps an overlap check local instead of a scan of every
    piece on the plot (20,000 x 1,024 per call would be 20 million comparisons). A turned piece: the box it reaches."""
    b = box_aabb(b)
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
        """May `b` not be put here? land-world.js piecesClash: boxes and slopes may not overlap one another; a PART (#175)
        overlaps freely — it does not fill its box, and parts are sunk into one another so no seam shows — and only the
        very same piece twice is refused. INVARIANT: boxes_overlap itself stays pure geometry (a block set into a piece's
        cell, a craft's joints still ask it); this is the one place the parts rule lives on the server."""
        seen, part, t = set(), is_part(b), tuple(b)
        for c in buckets_of(b):
            for o in self.cells.get(c, ()):
                if o not in seen:
                    seen.add(o)
                    if o == t or (not part and not is_part(o) and boxes_overlap(b, o)):
                        return True
        return False


# ---- FLIGHT (#147, doc/land-tech-to-flight.md; "you must add actual physics like engines and gravity to the game and
# build a real usable xfighter", operator 2026-11-09). A craft is built pieces that touch one another and hold a pilot
# seat and at least one thruster. Boarding the seat lifts them off the plot into a craft record — its pieces kept
# relative to the seat, a pose [face, u, v, h, yaw] — that the pilot's page flies; the server bounds the pilot's claims by
# the craft's own top speed, keeps it across restarts, shows it to everyone near, and docks it back onto a plot as pieces.
FLIGHT = RULES["flight"]
CRAFT_PAD = 2                     # cm: pieces this close count as touching (one craft). Not 1: docking turns a craft by
                                  # quarter turns and a tilted piece's centre rounds to a whole cm (turn_pieces), so two
                                  # flush wing plates of odd width came out a centimetre apart — the X fighter docked at
                                  # 270° and took off again as 228 of its 267 pieces (2026-11-11). land.js craftSeat agrees.
CRAFT_PIECES = 400                # pieces one craft holds at most
CRAFT_SLACK = 12.0                # m a pose may run ahead of vmax x the time since the last (a slow network's bunching)
FAR_R = 2600.0                    # m: the farthest a page may ask for the built land's far view (#193; the page asks 2 km)
CHARGE_RISE = 8.0                 # m above or below itself an animal still charges a player — DESIGN CHOICE (#192): a hillside
                                  # it runs up, never the air; the strike itself stays within 2.5 m (herd)


def boxes_touch(a, b):
    if turned(a) or turned(b):                      # a turned piece (#169): its own box grown by the pad, oriented
        g = [a[0] - CRAFT_PAD, a[1] - CRAFT_PAD, a[2] - CRAFT_PAD, a[3] + 2 * CRAFT_PAD, a[4] + 2 * CRAFT_PAD, a[5] + 2 * CRAFT_PAD] + list(a[6:])
        return boxes_overlap(g, b)
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
    """Tonnes: a unit part by its own mass — an engine (#175) as many thrusters as it is — any other piece by its volume
    x its material's density; a part by the material actually in it (box_vol: its fill, a tenth of it for a skin)."""
    dens, unit = FLIGHT["density"], FLIGHT["unit_mass"]
    def one(b):
        if str(b[6]) in unit:
            return unit[str(b[6])] * (engine_count(b) if b[6] == THRUSTER else 1)
        return (box_vol(b) if is_part(b) else b[3] * b[4] * b[5]) / 1e6 * dens.get(str(b[6]), dens["default"])
    return sum(one(b) for b in pieces)


def craft_thrust(pieces):
    """kN: every thruster's push — an engine part pushes as the thrusters it is made of (engine_count)."""
    return sum(FLIGHT["thrust_kn"] * engine_count(b) for b in pieces)


def turn_pieces(pieces, quarter):
    """The pieces (x east, z north, relative to the seat) as they lie when the craft's yaw is `quarter` quarter-turns:
    yaw +90° sends its nose (+z) east and its right side (+x) south — a point (x, z) goes to (z, -x) — the page's frame
    (land.js craftMesh: forward = sin(yaw)·east + cos(yaw)·north). A slope rises the next way round: +x -> -z -> -x -> +z."""
    out = []
    for b in pieces:
        if turned(b) or (is_part(b) and quarter % 4):
            # a turned piece (#169) keeps its own size and turns about the craft's yaw axis: its centre goes round with the
            # quarter turns and its yaw takes -90° each (yaw +90° in the page sends the nose east = a turn of -90° about up
            # in the piece's frame: (x, z) -> (z, -x)); its roll and pitch ride along. A centre on a half centimetre
            # rounds to the nearer whole one.
            # A PART (#175) is turned the same way even when it stood square: its outline has a front and a root, so
            # swapping its width and depth (what a plain box gets below) would draw a different thing — a wing's chord
            # across its span. INVARIANT: the result goes through normal_box — a piece whose yaw comes back to 0 with no
            # pitch or roll is a square piece again, and an 11-number piece with no rotation is refused by box_ok (a
            # part docked at 270° and then at 90° would never have docked again).
            cx, cz = b[0] + b[3] / 2, b[1] + b[4] / 2
            yw, pt, rl = rot_of(b)
            for _ in range(quarter % 4):
                cx, cz = cz, -cx
                yw = yw - 900 if yw - 900 > -ROT_MAX else yw + 2700
            out.append(normal_box([round(cx - b[3] / 2), round(cz - b[4] / 2)] + list(b[2:7]) + [b[7] if len(b) > 7 else 0, yw, pt, rl]))
            continue
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
MACHINES = {int(k) for k, v in MACH.items() if k.isdigit() and isinstance(v, dict) and "does" in v}   # every machine block


def run_cost(r):
    """Runs of power recipe `r` takes: its energy over run_mj when it names one (#173: electrolysis, liquefaction — land
    research rockets/ENERGY.md), one run otherwise (the smelter's and the assembler's, as before)."""
    return r["mj"] / MACH["run_mj"] if r.get("mj") else 1


def machine_can(blk, r):
    """Machine `blk` can run recipe `r`: every station or tool it asks for is one the machine stands in for, and it makes
    items only (a machine never makes a station or a tool)."""
    # …and at least one: work done by hand at no station (cordage, thatch, arrows) is no machine's — every machine offered
    # it, an electrolyser arrows and a smelter thatch (2026-11-11, #173)
    does = MACH.get(str(blk), {}).get("does", [])
    return bool(r.get("with")) and all(w in does for w in r["with"]) and all(m in RULES["items"] for m, _ in r["makes"])


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
        # the page walks put their player where a step needs them (tests/_land_live_fixture.py): no pace there; the pace
        # has its own test (#167)
        self.pace_free = False
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
        try:                                              # THE TOWN TREASURY (#165): the market's share, paying quests
            self.treasury = json.load(open(os.path.join(self.dir, "treasury.json")))
        except Exception:
            self.treasury = {}
        try:                                              # PRICES (#163): the trades taken, the record prices come from
            self.trades = json.load(open(os.path.join(self.dir, "trades.json")))
        except Exception:
            self.trades = []
        try:                                              # FLIGHT: crafts flying or parked, kept across restarts
            self.crafts = json.load(open(os.path.join(self.dir, "crafts.json")))
        except Exception:
            self.crafts = {}
        # A RESTART KEEPS EVERY PILOT IN THEIR SEAT, as a reload does (hello "flying" seats the page again): it used to park
        # each craft where it was, so a craft flying at the restart was left parked in the mid-air — out of anyone's reach,
        # its owner unable to board it again (#171, 2026-11-10: the fighter stranded 21 m up). Only the engines stop until
        # the pilot's page says again what they do.
        for c in self.crafts.values():
            c["eng"] = None
        self.cdirty = False
        self.survey_sets = {}                              # #173: each surveying player's squares, as a set (survey_at)
        try:                                               # #173: satellites in orbit, kept across restarts
            self.sats = json.load(open(os.path.join(self.dir, "sats.json")))
        except Exception:
            self.sats = []
        self.sdirty = False
        # HUNTING (#156): the animals near players — the world server's own, never saved (they wander off and others come)
        self.animals, self.animal_seq, self.rng = {}, 0, random.Random()
        self.drops, self.drop_seq = {}, 0                 # things lying on the ground to pick up: arrows that missed (#157)
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
            self._write("trades.json", self.trades)
            self._write("treasury.json", self.treasury)
            self.odirty = False
        if self.cdirty:
            self._write("crafts.json", self.crafts)
            self.cdirty = False
        if self.sdirty:
            self._write("sats.json", self.sats)
            self.sdirty = False

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

    async def cols(self, cells):
        """[height, top, biome] of each [face, u, v] column's untouched ground (land_terrain.mjs cols)."""
        if not cells:
            return []
        async with self.oracle_lock:
            self.oracle.stdin.write((json.dumps({"cols": cells}) + "\n").encode())
            await self.oracle.stdin.drain()
            r = json.loads(await self.oracle.stdout.readline())
        if "error" in r:
            raise RuntimeError("terrain oracle: " + r["error"])
        return r["cols"]

    # -- HUNTING (#156, doc/land-civilisation.md) ---------------------------------------------------------------------
    def tame(self, face, u, v):
        """SETTLED LAND IS SAFE (#168, operator 2026-11-10, "pick recommended": "no animals on plots with buildings or in
        the town"): stags killed players who stood still — reading the bag, a panel, building — four times in three hours
        on the town agent. The town's plots and any plot with a piece built on it take no animal: none is spawned there,
        none walks in, and none strikes a player standing there. The wild stays dangerous."""
        p = plot_of(face, int(u), int(v))
        return (face == 0 and p in TOWN_PLOTS) or bool((self.plots.get(p) or {}).get("boxes"))

    async def herd(self, present, dt=0.5, players=None):
        """One step of the animals near the players present ([face, u, v, h, ...] each): those no player is near go,
        each player's surroundings fill up to per_area (a couple a step, 18-40 m off, on dry land, of the kinds its biome
        holds), and every animal wanders — or flees at full speed from a player within flee metres."""
        Hn = RULES["hunting"]
        near = lambda a, q, r: a["face"] == q[0] and abs(a["u"] - q[1]) < r and abs(a["v"] - q[2]) < r
        for k in [k for k, a in self.animals.items() if not any(near(a, q, Hn["keep"]) for q in present)]:
            del self.animals[k]
        want = []
        for q in present:
            n = sum(1 for a in self.animals.values() if near(a, q, Hn["area"]))
            for _ in range(min(2, Hn["per_area"] - n)):
                ang, d = self.rng.random() * math.tau, 18 + self.rng.random() * 22
                u, v = q[1] + math.cos(ang) * d, q[2] + math.sin(ang) * d
                if 0 <= u < W and 0 <= v < W and not self.tame(int(q[0]), u, v):      # none spawned on settled land (#168)
                    want.append([int(q[0]), u, v])
        now = time.time()
        for (f, u, v), (hgt, top, biome) in zip(want, await self.cols(want)):
            kinds = [k for k, sp in Hn["species"].items() if biome in sp["biomes"]]
            if top <= SEA or not kinds:
                continue
            self.animal_seq += 1
            kind = self.rng.choice(kinds)
            self.animals[self.animal_seq] = {"id": self.animal_seq, "kind": kind, "face": f, "u": u, "v": v, "h": hgt,
                                              "yaw": self.rng.random() * math.tau, "hp": Hn["species"][kind]["hp"],
                                              "go": now + self.rng.random() * 4, "flee": 0,
                                              "angry": self.rng.random() < Hn["species"][kind].get("angry", 0)}
        moved, hits = [], []
        self.charges, self.struck_from = [], {}
        for a in self.animals.values():
            sp = Hn["species"][a["kind"]]["speed"]
            # AGGRESSION (#162): an angry animal — a stag, or one a hunter struck — charges the nearest player within charge
            # metres and strikes within strike_reach, every strike_every_s
            dmg = Hn["species"][a["kind"]].get("damage", 0)
            if (a.get("angry") or a.get("mad", 0) > now) and dmg and players:
                # a player on settled land is no foe (#168): it neither charges nor strikes them there
                # …and only one it can reach on foot (#192): within CHARGE_RISE of its own height — a slope it runs up,
                # not a pilot in the air or a player on a roof. A craft 500 m up was charged (by ground distance alone),
                # and the warning that it had turned on them reached a pilot nothing could touch.
                foe = min(((math.hypot(q[1] - a["u"], q[2] - a["v"]), who, q) for who, q in players
                           if q and q[0] == a["face"] and abs(q[3] - a["h"]) < CHARGE_RISE and not self.tame(q[0], q[1], q[2])), default=None, key=lambda x: x[0])
                if foe and foe[0] < Hn["charge"]:
                    a["yaw"] = math.atan2(foe[2][1] - a["u"], foe[2][2] - a["v"])
                    # THE WARNING (#176): the player is told the moment it turns on them — once per charge — while it
                    # is still `charge` metres off; a strike used to be the first they knew of it
                    if a.get("warned") != foe[1]:
                        a["warned"] = foe[1]
                        self.charges.append((foe[1], a["id"], a["kind"], a["u"], a["v"]))
                    if foe[0] <= Hn["strike_reach"] and abs(foe[2][3] - a["h"]) < 2.5:
                        if now >= a.get("bite", 0):
                            a["bite"] = now + Hn["strike_every_s"]
                            hits.append((foe[1], dmg, a["kind"]))
                            self.struck_from[foe[1]] = (a["u"], a["v"])      # …and a strike says where it came from
                        continue                                  # at the player: it stands and strikes
                    step = sp * dt
                    nu, nv = a["u"] + math.sin(a["yaw"]) * step, a["v"] + math.cos(a["yaw"]) * step
                    if 0 <= nu < W and 0 <= nv < W:
                        moved.append((a, nu, nv))
                    continue
                a.pop("warned", None)                             # the charge is over: the next one is told again
            threat = min(((math.hypot(q[1] - a["u"], q[2] - a["v"]), q) for q in present if q[0] == a["face"]), default=(1e9, None), key=lambda x: x[0])
            if threat[0] < Hn["flee"] or a["flee"] > now:
                if threat[1] is not None:
                    a["yaw"] = math.atan2(a["u"] - threat[1][1], a["v"] - threat[1][2])
                step = sp * dt
            elif now >= a["go"]:                              # wander: a new heading now and then, a pause between
                a["yaw"] += (self.rng.random() - 0.5) * 2.0
                a["go"] = now + 2 + self.rng.random() * 5
                a["walk"] = self.rng.random() < 0.6
                continue
            else:
                step = sp * 0.3 * dt if a.get("walk") else 0
            if step:
                nu, nv = a["u"] + math.sin(a["yaw"]) * step, a["v"] + math.cos(a["yaw"]) * step
                if 0 <= nu < W and 0 <= nv < W:
                    moved.append((a, nu, nv))
        for (a, nu, nv), (hgt, top, _) in zip(moved, await self.cols([[a["face"], nu, nv] for a, nu, nv in moved])):
            # never into the sea, and never onto settled land (#168) — an animal already there (the plot was built on around
            # it) may still walk out: it turns back
            if top <= SEA or (self.tame(a["face"], nu, nv) and not self.tame(a["face"], a["u"], a["v"])):
                a["yaw"] += math.pi
                continue
            a["u"], a["v"], a["h"] = nu, nv, hgt
        return hits

    def animals_near(self, pos, r):
        now = time.time()
        return [[a["id"], a["kind"], round(a["u"], 2), round(a["v"], 2), round(a["h"], 2), round(a["yaw"], 2),
                 1 if a.get("angry") or a.get("mad", 0) > now else 0]
                for a in self.animals.values() if a["face"] == pos[0] and abs(a["u"] - pos[1]) < r and abs(a["v"] - pos[2]) < r]

    # -- NPCS AND QUESTS (#165, doc/land-civilisation.md) --------------------------------------------------------------
    @staticmethod
    def npc(nid):
        return next((n for n in RULES["quests"]["npcs"] if n["id"] == nid), None)

    @staticmethod
    def level_of(xp):
        """Level n needs level_xp * n * (n - 1) / 2 experience: 1 at 0, 2 at 100, 3 at 300, 4 at 600..."""
        n = 1
        while RULES["quests"]["level_xp"] * (n + 1) * n // 2 <= xp:
            n += 1
        return n

    def near_npc(self, nid, pos):
        n = self.npc(nid)
        return bool(n and pos and int(pos[0]) == n["at"][0]
                    and math.hypot(pos[1] - n["at"][1], pos[2] - n["at"][2]) <= RULES["quests"]["talk"])

    def _new_quest(self, giver):
        Q = RULES["quests"]
        kind = self.rng.choice(["bring", "bring", "hunt", "deliver"])
        q = {"id": secrets.token_hex(4), "kind": kind, "giver": giver}
        if kind == "bring":
            q["item"], q["n"] = self.rng.choice(Q["bring"])
        elif kind == "hunt":
            q["what"], q["n"] = self.rng.choice(Q["hunt"])
            q["got"] = 0
        else:
            q["to"] = self.rng.choice([n["id"] for n in Q["npcs"] if n["id"] != giver])
        return q

    def offered(self, who, nid):
        """What `nid` offers this player now: kept with the player, topped up to `offered` from the world's templates."""
        n = self.npc(nid)
        if not n or not n.get("gives"):
            return []
        pl = self.player(who)
        offers = pl.setdefault("offered", {}).setdefault(nid, [])
        while len(offers) < RULES["quests"]["offered"]:
            offers.append(self._new_quest(nid))
            self.pdirty.add(who)
        return offers

    def talk(self, who, nid, pos):
        """An NPC's word for this player: their offers and the player's quests that end with them (ready or not)."""
        n = self.npc(nid)
        if not n:
            return None, "no one by that name here"
        if not self.near_npc(nid, pos):
            return None, "too far away — go up to them"
        pl = self.player(who)
        ends = [dict(q, ready=self._ready(pl, q)) for q in pl.get("quests", []) if (q.get("to") or q["giver"]) == nid]
        return {"npc": nid, "name": n["name"], "role": n["role"], "offers": self.offered(who, nid), "ends": ends}, None

    def _ready(self, pl, q):
        if q["kind"] == "bring":
            return pl["items"].get(q["item"], 0) >= q["n"]
        if q["kind"] == "hunt":
            return q.get("got", 0) >= q["n"]
        return pl["items"].get("parcel", 0) >= 1

    def quest(self, who, op, nid, qid, pos):
        """op "accept" (an offer of nid's), "turnin" (a quest ending with nid, ready), "drop" (any of the player's).
        Returns (reward or None, error)."""
        pl = self.player(who)
        Q = RULES["quests"]
        mine = pl.setdefault("quests", [])
        if op == "drop":
            q = next((q for q in mine if q["id"] == qid), None)
            if not q:
                return None, "no such quest"
            mine.remove(q)
            if q["kind"] == "deliver" and pl["items"].get("parcel"):
                pl["items"]["parcel"] -= 1                          # the parcel goes back to its sender
                if not pl["items"]["parcel"]:
                    del pl["items"]["parcel"]
            self.pdirty.add(who)
            return {}, None
        if not self.near_npc(nid, pos):
            return None, "too far away — go up to them"
        if op == "accept":
            offers = self.offered(who, nid)
            q = next((q for q in offers if q["id"] == qid), None)
            if not q:
                return None, "that is not offered any more"
            if len(mine) >= Q["max_open"]:
                return None, f"at most {Q['max_open']} quests at a time"
            offers.remove(q)
            mine.append(q)
            if q["kind"] == "deliver":
                pl["items"]["parcel"] = pl["items"].get("parcel", 0) + 1
            self.pdirty.add(who)
            return {"accepted": q}, None
        if op == "turnin":
            q = next((q for q in mine if q["id"] == qid), None)
            if not q or (q.get("to") or q["giver"]) != nid:
                return None, "that quest does not end here"
            if not self._ready(pl, q):
                return None, "not done yet"
            # the reward first, from the treasury as it stood: a quest is never paid with what it just brought in
            paid = {}
            stock = max(((k, n) for k, n in self.treasury.items() if n > 0), default=None, key=lambda kn: (kn[1], kn[0]))
            # (a delivery is a walk across the square — free to repeat with farmed accounts — so it pays experience only;
            # what is paid from the town is earned by bringing or hunting, which cost the player something)
            if stock and q["kind"] != "deliver":                    # from the treasury's largest stock, a small share
                k, n = stock
                give = min(n, max(1, int(n * Q["reward_share"])))
                self.treasury[k] -= give
                pl["items"][k] = pl["items"].get(k, 0) + give
                paid = {k: give}
            if q["kind"] == "bring":                                # what was brought goes to the town
                pl["items"][q["item"]] -= q["n"]
                if not pl["items"][q["item"]]:
                    del pl["items"][q["item"]]
                self.treasury[q["item"]] = self.treasury.get(q["item"], 0) + q["n"]
            elif q["kind"] == "deliver":
                pl["items"]["parcel"] -= 1
                if not pl["items"]["parcel"]:
                    del pl["items"]["parcel"]
            mine.remove(q)
            xp = Q["xp"][q["kind"]]
            pl["xp"] = pl.get("xp", 0) + xp
            self.pdirty.add(who); self.odirty = True
            return {"xp": xp, "paid": paid, "level": self.level_of(pl["xp"])}, None
        return None, "accept, turnin or drop"

    def npcs_for(self, who, pos, r):
        """The NPCs near pos, each with whether it has something for this player (work offered, or a quest to hand in)."""
        out = []
        for n in RULES["quests"]["npcs"]:
            if not pos or n["at"][0] != int(pos[0]) or abs(n["at"][1] - pos[1]) > r or abs(n["at"][2] - pos[2]) > r:
                continue
            mark = None
            if who:
                pl = self.player(who)
                if any((q.get("to") or q["giver"]) == n["id"] and self._ready(pl, q) for q in pl.get("quests", [])):
                    mark = "?"
                elif n.get("gives") and len(pl.get("quests", [])) < RULES["quests"]["max_open"]:
                    mark = "!"
            out.append({"id": n["id"], "name": n["name"], "role": n["role"], "at": n["at"], "look": n["look"], "mark": mark})
        return out

    # -- HEALTH, DEATH AND RESPAWN (#162) -----------------------------------------------------------------------------
    def hurt(self, who, dmg, by):
        """`who` takes `dmg` from `by` (an animal's kind). Returns ("hurt", hp), ("died", bed) — the bag is kept, health
        is full again and a few seconds of grace follow — or None while in grace."""
        Hh, pl, now = RULES["health"], self.player(who), time.time()
        if pl.get("grace", 0) > now:
            return None
        pl["hp"] = pl.get("hp", Hh["max"]) - dmg
        pl["hurt_at"] = now
        self.pdirty.add(who)
        if pl["hp"] > 0:
            return ("hurt", pl["hp"])
        pl["hp"], pl["grace"] = Hh["max"], now + Hh["grace_s"]
        pl["deaths"] = pl.get("deaths", 0) + 1
        # THE DEAD ARE NOWHERE NEAR THE ANIMAL (#176): the world keeps them at the place they wake — their bed, or the
        # landing — from the moment they die, not from the moment the page says so. With the place left at the death
        # spot (the landing case kept it there until 2026-11-11) the animal struck again when the grace ran out.
        wake = pl["bed"][:4] if pl.get("bed") else landing() + [(pl.get("pos") or [0, 0, 0, 0.0])[3]]
        pl["pos"] = list(wake) + [0.0]; pl["pos_at"] = int(now)
        return ("died", pl.get("bed"))

    def heal(self, now=None):
        """Players nothing has hurt for calm_s get a point back every regen_s, up to max. Returns who changed."""
        Hh, now, out = RULES["health"], time.time() if now is None else now, []
        for who, pl in self.players.items():
            hp = pl.get("hp", Hh["max"])
            if hp >= Hh["max"] or now - pl.get("hurt_at", 0) < Hh["calm_s"] or now - pl.get("heal_at", 0) < Hh["regen_s"]:
                continue
            pl["hp"], pl["heal_at"] = hp + 1, now
            self.pdirty.add(who); out.append(who)
        return out

    def bed(self, who, p, b):
        """Use on a bed (#162): the player wakes there after a death. The bed must stand; a bed taken down wakes no one."""
        rec = self.plots.get(p)
        b = list(b) if isinstance(b, (list, tuple)) else b
        if not rec or not isinstance(b, list) or b not in rec.get("boxes", []) or b[6] != BED:
            return "no such bed here"
        fc, fr = p % FACE_N, (p // FACE_N) % FACE_N
        self.player(who)["bed"] = [plot_coords(p)[0], fc * PLOT + (b[0] + b[3] / 2) / 100, fr * PLOT + (b[1] + b[4] / 2) / 100, (b[2] + b[5]) / 100, p, b]
        self.pdirty.add(who)
        return None

    def hunt(self, who, aid, pos):
        """A spear strike at animal `aid` from `pos` (where the hunter stands), within the spear's reach; a strike costs
        strike_s of work. A bow does not strike: it shoots (loose_arrow(), BALLISTICS #157 — not shoot(), which photographs a plot). Returns ({"hit", "killed",
        "drops"}, error)."""
        Hn = RULES["hunting"]
        a = self.animals.get(aid) if isinstance(aid, int) and not isinstance(aid, bool) else None
        if not a:
            return None, "it is gone"
        if not pos or pos[0] != a["face"]:
            return None, "too far away"
        pl = self.player(who)
        if not self._has_class(pl, "spear"):
            return None, ("a bow shoots — aim and loose" if self._has_class(pl, "bow") else "hunting needs a spear or a bow")
        d = math.hypot(a["u"] - pos[1], a["v"] - pos[2], a["h"] + 0.5 - (pos[3] + 1.5))
        if d > Hn["weapons"]["spear"]["reach"]:
            return None, "too far away"
        if not self.work(who, Hn["strike_s"]):
            return None, "too fast"
        return self._strike(who, pl, a, Hn["weapons"]["spear"]["damage"]), None

    def _strike(self, who, pl, a, damage):
        """`a` takes `damage` from `who`: it turns on them or runs; at 0 hp it is gone, a hunt quest counts it, and its
        drops go to the hunter — its butcher items (hide, bone) only to one with a knife (#157)."""
        Hn = RULES["hunting"]
        a["hp"] -= damage
        if Hn["species"][a["kind"]].get("damage", 0):         # struck, a kind that can fight back turns on the hunter (#162)
            a["mad"] = time.time() + 20
        else:
            a["flee"] = time.time() + 8                       # struck, it runs
        self.pdirty.add(who)
        if a["hp"] > 0:
            return {"hit": a["kind"], "killed": None, "drops": []}
        self.animals.pop(a["id"], None)
        for q in pl.get("quests", []):                        # a hunt quest counts the kill (#165)
            if q["kind"] == "hunt" and q["what"] == a["kind"] and q.get("got", 0) < q["n"]:
                q["got"] = q.get("got", 0) + 1
        knife = self._has_class(pl, "knife")
        drops = [[i, n] for i, n in Hn["species"][a["kind"]]["drops"] if knife or i not in Hn.get("butcher", [])]
        for item, n in drops:
            pl["items"][item] = pl["items"].get(item, 0) + n
        return {"hit": a["kind"], "killed": a["kind"], "drops": drops, "knife": knife}

    async def loose_arrow(self, who, pos, yaw, pitch):
        """BALLISTICS (#157): an arrow loosed from the hunter's eye along (yaw, pitch) at `draw` m/s, falling under g. It
        hits the first animal whose body the arrow passes through where that animal IS when the arrow gets there (its
        own run carries it on: a running animal must be led), or lands on the ground — some arrows then lie there to be
        picked up. Returns ({"hit", "killed", "drops", "flight" (seconds), "end"}, error)."""
        Hn, B = RULES["hunting"], RULES["hunting"]["ballistics"]
        pl = self.player(who)
        if not self._has_class(pl, "bow"):
            return None, "shooting needs a bow"
        if pl["items"].get("arrow", 0) < 1:
            return None, "no arrows"
        if not pos or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in (yaw, pitch)):
            return None, "aim first"
        if not self.work(who, Hn["strike_s"]):
            return None, "too fast"
        pl["items"]["arrow"] -= 1
        if not pl["items"]["arrow"]:
            del pl["items"]["arrow"]
        self.pdirty.add(who)
        face, now = int(pos[0]), time.time()
        o = [pos[1], pos[2], pos[3] + 1.5]
        cp = math.cos(pitch)
        vel = [B["draw"] * cp * math.sin(yaw), B["draw"] * cp * math.cos(yaw), B["draw"] * math.sin(pitch)]
        # the ground under the arc, sampled every 0.1 s of flight (4 s at most)
        steps = [(t / 10.0) for t in range(1, 41)]
        arc = [[o[0] + vel[0] * t, o[1] + vel[1] * t, o[2] + vel[2] * t - B["g"] * t * t / 2] for t in steps]
        cols = await self.cols([[face, min(W - 1, max(0, p[0])), min(W - 1, max(0, p[1]))] for p in arc])
        ground = [c[0] for c in cols]
        def moving(a):                                        # where an animal's own run takes it, per second
            sp = Hn["species"][a["kind"]]["speed"]
            fast = a.get("flee", 0) > now or a.get("mad", 0) > now or a.get("angry")
            v = sp if fast else (sp * 0.3 if a.get("walk") else 0)
            return v * math.sin(a["yaw"]), v * math.cos(a["yaw"])
        near = [(a, moving(a)) for a in self.animals.values() if a["face"] == face and math.hypot(a["u"] - o[0], a["v"] - o[1]) < 120]
        t, dt, prev = 0.0, 0.02, list(o)
        while t < 4.0:
            t += dt
            p = [o[0] + vel[0] * t, o[1] + vel[1] * t, o[2] + vel[2] * t - B["g"] * t * t / 2]
            for a, (mu, mv) in near:
                size = Hn["species"][a["kind"]].get("size", [1, 0.5, 1])
                c = [a["u"] + mu * t, a["v"] + mv * t, a["h"] + size[2] * 0.6]
                if math.dist(p, c) <= max(size[0], size[2]) * 0.5 + B["pad"]:
                    res = self._strike(who, pl, a, Hn["weapons"]["bow"]["damage"])
                    return dict(res, flight=round(t, 2), end=[face, round(p[0], 2), round(p[1], 2), round(p[2], 2)]), None
            g = ground[min(len(ground) - 1, int(t * 10))]
            if p[2] <= g:                                     # it lands: some arrows can be picked up where they fell
                if self.rng.random() < B["recover"]:
                    self.drop_seq += 1
                    self.drops[self.drop_seq] = {"id": self.drop_seq, "face": face, "u": p[0], "v": p[1], "h": g, "item": "arrow", "n": 1, "until": now + B["drop_s"]}
                return {"hit": None, "killed": None, "drops": [], "flight": round(t, 2), "end": [face, round(p[0], 2), round(p[1], 2), round(g, 2)]}, None
            prev = p
        return {"hit": None, "killed": None, "drops": [], "flight": round(t, 2), "end": [face] + [round(x, 2) for x in prev]}, None

    def drops_near(self, pos, r):
        now = time.time()
        self.drops = {k: d for k, d in self.drops.items() if d["until"] > now}
        return [[d["id"], d["item"], round(d["u"], 2), round(d["v"], 2), round(d["h"], 2)] for d in self.drops.values()
                if pos and d["face"] == int(pos[0]) and abs(d["u"] - pos[1]) < r and abs(d["v"] - pos[2]) < r]

    def pickup(self, who, did, pos):
        """Pick up a thing lying on the ground (an arrow that missed) from within its pickup reach."""
        d = self.drops.get(did) if isinstance(did, int) and not isinstance(did, bool) else None
        if not d or d["until"] <= time.time():
            return "it is gone"
        if not pos or int(pos[0]) != d["face"] or math.hypot(d["u"] - pos[1], d["v"] - pos[2]) > RULES["hunting"]["ballistics"]["pickup"]:
            return "too far away"
        del self.drops[did]
        pl = self.player(who)
        pl["items"][d["item"]] = pl["items"].get(d["item"], 0) + d["n"]
        self.pdirty.add(who)
        return None

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
                "fed": max(0, int(pl.get("fed", 0) - time.time())),          # seconds of a meal left (#155)
                "hp": pl.get("hp", RULES["health"]["max"]), "hp_max": RULES["health"]["max"],   # health (#162)
                "quests": [dict(q, ready=self._ready(pl, q)) for q in pl.get("quests", [])],      # the quest log (#165)
                "xp": pl.get("xp", 0), "level": self.level_of(pl.get("xp", 0))}

    def keep_place(self, addr, pos):
        """Remember where a signed-in player stands ([face, u, v, h, yaw]), written with the player at the next flush."""
        self.player(addr)["pos"] = [int(pos[0]), round(float(pos[1]), 2), round(float(pos[2]), 2), round(float(pos[3]), 2), round(float(pos[4]), 3)]
        self.player(addr)["pos_at"] = int(time.time())                # the page compares it with its own save
        self.player(addr)["pos_t"] = time.time()                      # Hub.where: newer than the page's socket, or not
        self.pdirty.add(addr)
        self.survey_at(addr, pos)

    # THE SURVEYED MAP (#173, doc/land-navigation.md 1.3): a player carrying a map draws the land as they go, as a surveyor
    # draws in the field on a plane table (Plane table l.4) — the server keeps the SURVEY_TILE-metre squares they passed
    # through with one (on foot or flying), and the page draws those, and only those, from the planet's own generator.
    # The square and the cap are design choices.
    SURVEY_TILE, SURVEY_MAX = 64, 10000

    def survey_at(self, addr, pos):
        pl = self.player(addr)
        if pl["items"].get("map", 0) < 1:
            return
        have = self.survey_sets.get(addr)
        if have is None:
            have = self.survey_sets[addr] = {tuple(x) for x in pl.get("survey", [])}
        k = (int(pos[0]), int(pos[1] // self.SURVEY_TILE), int(pos[2] // self.SURVEY_TILE))
        if k not in have and len(have) < self.SURVEY_MAX:
            have.add(k); pl.setdefault("survey", []).append(list(k)); self.pdirty.add(addr)

    def survey_of(self, addr, near=4096):
        """What a player's map shows, from where they stand: the squares they surveyed on this face within `near` m, the
        town hall, their bed and their crafts. No squares without a map — a map is what remembers them."""
        pl = self.player(addr)
        pos = pl.get("pos") or [0, 0, 0, 0, 0]
        t = self.SURVEY_TILE
        tiles = [[x[1], x[2]] for x in pl.get("survey", []) if pl["items"].get("map", 0) >= 1 and x[0] == pos[0]
                 and abs((x[1] + 0.5) * t - pos[1]) <= near and abs((x[2] + 0.5) * t - pos[2]) <= near]
        return {"tile": t, "face": pos[0], "tiles": tiles, "town": landing(), "bed": pl["bed"][:3] if pl.get("bed") else None,
                "crafts": [{"id": c["id"], "pose": c["pose"]} for c in self.crafts_of(addr)]}

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

    async def apply(self, who, cells, at=False):
        """Apply [face, u, v, h, block] cells: block 0 BREAKS (gathering: its yield goes to the caller's inventory),
        any other id PLACES one item from the inventory. Returns (applied by plot, refused, inventory changed).
        `at` is where the caller stands ([face, u, v, h, ...]) and each break — and each place off a plot they may build
        on — must be within REACH_M of their eye (#167); None: nobody knows where they are, so nothing within reach;
        False (the server's own work and tests that call this directly): not checked."""
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
            # REACH (#167): broken only beside the breaker; placed from afar only on a plot they may build on
            if at is not False and (b == 0 or not (titled and may)):
                if at is None:
                    refused.append([c, "stand in the world first — open the game, or say where you are (/land/api/move)"]); continue
                if int(at[0]) != face or math.dist((u + 0.5, v + 0.5, h + 0.5), (at[1], at[2], at[3] + EYE)) > REACH_M:
                    refused.append([c, "out of reach — stand within %d m of it" % REACH_M]); continue
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
        return [b for b in rec["boxes"] if b[6] in PIECE_BURNS and (a := box_aabb(b))[0] < x0 + 200 and a[0] + a[3] > x0
                and a[1] < z0 + 200 and a[1] + a[4] > z0 and a[2] < y0 + 200 and a[2] + a[5] > y0]      # a turned piece: what it reaches

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
            if b[6] == STAND and any((o.get("stand") or [None])[0] == p and o["stand"][1] == b for o in self.offers.values()):
                refused.append([b, "offers are open at this stand — they are withdrawn first"]); continue
            rule = RULES["breaking"].get(str(b[6])) or {"hard": 1.0}
            unit = RULES["items"][places[b[6]]].get("unit")
            n = engine_count(b) if is_engine(b) else 1              # an engine (#175) is as many thrusters as its size
            speed = self._speed(pl, rule.get("class"))
            if not self.work(who, max(0.05, rule["hard"] * (n if unit else box_vol(b) / BLOCK_CM3) / speed * self.fed_work(pl))):
                refused.append([b, "too fast — taking a piece down takes time"]); continue
            rec["boxes"].remove(b)
            idx.remove(b)
            if unit:                                                # a door comes back as the door it was
                pl["items"][places[b[6]]] = pl["items"].get(places[b[6]], 0) + n
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
                # AN ENGINE (#175) is the one unit piece of any size and any turn: the engine part in the thruster's
                # material, paid as the thrusters its volume comes to (engine_count; taken down it gives them back).
                # INVARIANT: every other unit piece stays whole, square and at its own size — a door is a door.
                n = engine_count(b) if is_engine(b) else 1
                if not is_engine(b) and (sorted(b[3:5]) != sorted(unit[:2]) or b[5] != unit[2] or len(b) > 7):
                    refused.append([b, f"a {RULES['items'][places[b[6]]]['name'].lower()} is {unit[0]} x {unit[1]} x {unit[2]} cm"]); continue
                if pl["items"].get(places[b[6]], 0) < n:
                    refused.append([b, f"you have no {RULES['items'][places[b[6]]]['name'].lower()}" if n == 1 else f"an engine this size is {n} thrusters — you have {pl['items'].get(places[b[6]], 0)}"]); continue
                pl["items"][places[b[6]]] -= n
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
        if not rec or not isinstance(b, list) or b not in rec.get("boxes", []) or b[6] not in MACHINES | {GENERATOR}:
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
            bykey = {chest_key(b): b for b in boxes if b[6] in MACHINES}
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
                gen, cost = None, run_cost(r)
                for g in gens:
                    gk = chest_key(g)
                    if charges.get(gk, 0) < cost - 1e-9:
                        for fc in (c for c in boxes if c[6] == CHEST and boxes_touch(c, g)):
                            fs = store.get(chest_key(fc), {})
                            fuel = next((f for f in MACH["fuel"] if fs.get(f, 0) > 0), None)
                            if fuel:
                                fs[fuel] -= 1
                                if not fs[fuel]:
                                    del fs[fuel]
                                charges[gk] = charges.get(gk, 0) + MACH["fuel"][fuel]
                                changed.add(p); break
                    if charges.get(gk, 0) >= cost - 1e-9:
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
                charges[gen] = round(charges[gen] - cost, 6)                # its energy (#173), one run for the rest
                cfg["made"] = cfg.get("made", 0) + 1
                status("running")
                changed.add(p); self.dirty.add(p)
        return changed

    # -- ROCKETS (#173, doc/land-navigation.md 1.5): a rocket is the pieces built onto a launch pad (chests aside); the world
    # server computes its launch from their masses — land-recipes.json "rocket" holds every constant and where it comes from
    async def fly_ascent(self, params):
        """The rocket's ascent, flown by land-planet.js through the terrain oracle (the same integrator the page has)."""
        async with self.oracle_lock:
            self.oracle.stdin.write((json.dumps({"ascent": params}) + "\n").encode())
            await self.oracle.stdin.drain()
            r = json.loads(await self.oracle.stdout.readline())
        if "error" in r:
            raise RuntimeError("terrain oracle: " + r["error"])
        return r["ascent"]

    async def launch_numbers(self, p, pad):
        """What the rocket on launch pad `pad` (plot `p`) would do: its dry and loaded mass (kg), its thrust and weight (kN),
        the propellant it would load from the chests beside the pad, its Δv (rocket equation at sea-level Isp) less the
        gravity loss of its whole burn (as if straight up), against the Δv the orbit asks — and why not, when it cannot."""
        RK = RULES["rocket"]
        rec = self.plots.get(p) or {}
        boxes = rec.get("boxes", [])
        rocket = [b for b in connected([b for b in boxes if b[6] != CHEST], pad) if b != pad]
        n = lambda blk: sum(1 for b in rocket if b[6] == blk)
        engines, tanks, sats = n(ROCKET_ENGINE), n(PROP_TANK), n(SATELLITE)
        store = rec.get("chests", {})
        have = sum(store.get(chest_key(c), {}).get("propellant", 0) for c in boxes if c[6] == CHEST and boxes_touch(c, pad))
        load = min(have, tanks * RK["tank"]["holds"])
        dry = craft_mass(rocket) * 1000
        wet = dry + load * RK["canister_kg"]
        thrust = engines * RK["engine"]["thrust_kn"]
        weight = wet * FLIGHT["g"] / 1000
        isp, g0 = RK["engine"]["isp_sl"], RK["g0"]
        dv = isp * g0 * math.log(wet / dry) if dry > 0 and load else 0.0
        burn = load * RK["canister_kg"] * isp * g0 / (thrust * 1000) if thrust else 0.0
        net = dv - FLIGHT["g"] * burn
        # THE ASCENT, FLOWN (#174, doc/land-planet.md): gravity GM/r², the air's drag and the engines' thrust with the outside
        # pressure, step by step to the orbit — it decides; the rocket equation's figures above stay as the panel's summary
        flown = None
        if engines and tanks and sats and load and thrust > weight:
            xs = [b[0] for b in rocket] + [b[0] + b[3] for b in rocket]; zs = [b[1] for b in rocket] + [b[1] + b[4] for b in rocket]
            w_, d_ = (max(xs) - min(xs)) / 100, (max(zs) - min(zs)) / 100
            flown = await self.fly_ascent({"dryKg": dry, "propKg": load * RK["canister_kg"], "thrustSeaN": thrust * 1000,
                                           "ispSea": RK["engine"]["isp_sl"], "ispVac": RK["engine"]["isp_vac"],
                                           # a rocket climbs along its long axis: what meets the air is its cross-section
                                           # (the mean of all three faces — the craft's approximation — made a 1.5 m wide,
                                           # 7.3 m tall rocket 8 m² instead of 2.25, and it never reached orbit)
                                           "area": w_ * d_, "cd": 1.28, "padH": pad[2] / CM,
                                           "targetR": RK["orbit"]["r"]})
        why = (None if engines and tanks and sats and load and thrust > weight and flown and flown["ok"] else
               "no rocket engine on the pad" if not engines else "no propellant tank" if not tanks else
               "no satellite to carry" if not sats else "no propellant in a chest beside the pad" if not load else
               "too heavy to leave the pad: its thrust does not beat its weight" if thrust <= weight else
               "not enough Δv to reach orbit — more propellant, or less mass")
        flown_out = None if not flown else {k: (round(v, 1) if isinstance(v, float) else v) for k, v in flown.items()}
        return {"engines": engines, "tanks": tanks, "sats": sats, "pieces": len(rocket), "load": load, "have": have,
                "dry_kg": round(dry, 1), "wet_kg": round(wet, 1), "thrust_kn": round(thrust, 1), "weight_kn": round(weight, 1),
                "dv": round(dv, 1), "loss": round(FLIGHT["g"] * burn, 1), "net": round(net, 1), "need": RK["dv_orbit"],
                "flown": flown_out, "ok": why is None, "why": why}

    async def launch(self, who, p, pad):
        """Fire the rocket on `pad`: refused unless its thrust beats its weight (it would not leave the pad). Otherwise it
        goes: its pieces leave the plot and the propellant it loaded leaves the chests — spent either way — and with
        enough Δv its satellites are in orbit, each the next slot of the constellation. Returns (numbers, removed, err)."""
        rec = self.plots.get(p)
        pad = list(pad) if isinstance(pad, (list, tuple)) else pad
        if not rec or not isinstance(pad, list) or pad not in rec.get("boxes", []) or pad[6] != LAUNCH_PAD:
            return None, [], "no launch pad here"
        if (await self.holder(p)) is not None and not await self.may_build(p, who):
            return None, [], "not your plot — only its owner and the builders they invite launch from it"
        num = await self.launch_numbers(p, pad)
        if not (num["engines"] and num["tanks"] and num["sats"] and num["load"]) or num["thrust_kn"] <= num["weight_kn"]:
            return num, [], num["why"]
        rocket = [b for b in connected([b for b in rec["boxes"] if b[6] != CHEST], pad) if b != pad]
        left = num["load"]
        for c in (c for c in rec["boxes"] if c[6] == CHEST and boxes_touch(c, pad)):
            cs = rec.setdefault("chests", {}).get(chest_key(c), {})
            k = min(left, cs.get("propellant", 0))
            if k:
                cs["propellant"] -= k; left -= k
                if not cs["propellant"]:
                    del cs["propellant"]
        if "index" not in rec:
            rec["index"] = BoxIndex(rec["boxes"])
        for b in rocket:
            rec["boxes"].remove(b); rec["index"].remove(b)
        rec["ver"] += 1; self.dirty.add(p)
        if num["ok"]:
            for _ in range(num["sats"]):
                self.sats.append({"n": len(self.sats), "owner": who, "at": round(time.time(), 3)})
            self.sdirty = True
        num["in_orbit"] = len(self.sats)
        return num, rocket, None

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

    def fly(self, who, cid, pose, eng=None):
        """The pilot's page says where the craft is. Taken when it is in the world and no farther from the last pose than
        the craft's top speed allows (CRAFT_SLACK for a bunched network); otherwise refused, and the page is told the
        pose the server holds. Returns error or None."""
        c = self.crafts.get(cid)
        if not c or c["pilot"] != who:
            return "you are not flying that"
        # a pose is [face, u, v, h, yaw] or, for an aircraft (#191), [face, u, v, h, yaw, pitch, roll] in radians
        if not (isinstance(pose, list) and len(pose) in (5, 7) and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in pose)
                and pose[0] == c["pose"][0] and 0 <= pose[1] < W and 0 <= pose[2] < W and DEEP_MIN <= pose[3] < H + 400
                and all(abs(x) <= math.pi for x in pose[5:])):           # (pitch and roll within a half turn; the yaw is the page's own count of turns, unbounded)
            return "not a place"
        now = time.time()
        far = math.dist(pose[1:4], c["pose"][1:4])
        if far > FLIGHT["vmax"] * max(0.05, now - c["at"]) + CRAFT_SLACK:
            return "faster than it can fly"
        c["pose"] = [int(pose[0]), round(float(pose[1]), 3), round(float(pose[2]), 3), round(float(pose[3]), 3)] + [round(float(x), 4) for x in pose[4:]]
        c["at"] = now; self.cdirty = True
        self.survey_at(who, c["pose"])                              # a pilot carrying a map surveys from the air (#173)
        # THE ENGINES' WORK (#171): [throttle, lift, du, dv] as the pilot's page computes it (land-flight.js engine) —
        # only drawn (exhaust, dust, tremble), so it is kept as the pilot says it, within range
        if (isinstance(eng, list) and len(eng) == 4 and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in eng)
                and 0 <= eng[0] <= 1 and 0 <= eng[1] <= 1 and -1 <= eng[2] <= 1 and -1 <= eng[3] <= 1):
            c["eng"] = [round(float(x), 2) for x in eng]
        return None

    def leave(self, who, cid):
        c = self.crafts.get(cid)
        if not c or c["pilot"] != who:
            return "you are not flying that"
        c["pilot"] = None; c["eng"] = None; self.cdirty = True        # parked: the engines stop
        return None

    def give_craft(self, who, cid, to):
        """HANDING A CRAFT OVER (#171): its owner gives it to another player — the craft they fly (they step out first) or
        one parked. The receiver becomes its owner AND its pilot: their page takes its controls at once (or on their next
        visit, by the greeting), so a craft given in mid-air is never left where no one can reach it — the operator could
        not board the X fighter the agent built for them, and their own craft was stranded 30 m up (2026-11-10).
        Returns error or None."""
        c = self.crafts.get(cid)
        if not c:
            return "no such craft"
        if c["owner"] != who:
            return "only its owner gives it away"
        if c["pilot"] and c["pilot"] != who:
            return "someone is flying it"
        if not (isinstance(to, str) and re.fullmatch(r"[0-9a-f]{50}", to)):
            return "give it to a player's address"
        if to == who:
            return "it is yours already"
        if to not in self.players and not os.path.exists(os.path.join(self.dir, "players", to + ".json")):
            return "no such player"
        c["owner"] = c["pilot"] = to; c["eng"] = None; c["at"] = time.time(); self.cdirty = True
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
        face, u, v, h, yaw = c["pose"][:5]                              # (an aircraft's pose carries pitch and roll too, #191)
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

    # THE EVENT TRACE (#194): what a page saw happen to its player — boarding, leaving, every move of the body the player
    # did not make, hurt, death, errors — appended to trace/<address>.jsonl, the newest TRACE_KEEP bytes kept (the file
    # is cut to its last lines when it grows past twice that), one line an event with the server's time added.
    # scripts/land_trace.py <address> reads it. Nothing goes unlogged (the operator, 2026-11-12).
    TRACE_KEEP = 512 * 1024
    def trace_append(self, who, events):
        if not who or not isinstance(events, list):
            return 0
        d = os.path.join(self.dir, "trace"); os.makedirs(d, exist_ok=True)
        path, now, n = os.path.join(d, who + ".jsonl"), round(time.time(), 3), 0
        with open(path, "a") as f:
            for e in events[:50]:
                if not isinstance(e, dict) or not isinstance(e.get("k"), str):
                    continue
                line = json.dumps(dict(e, srv=now), separators=(",", ":"))
                if len(line) > 2000:
                    continue
                f.write(line + "\n"); n += 1
        if os.path.getsize(path) > 2 * self.TRACE_KEEP:
            with open(path, "rb") as f:
                f.seek(-self.TRACE_KEEP, 2); tail = f.read()
            tail = tail[tail.find(b"\n") + 1:]
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(tail)
            os.replace(tmp, path)
        return n

    # THE FAR VIEW OF THE BUILT LAND (#193; operator 2026-11-12: "the village is only visible from like 50 meters away,
    # this means that large cities will be completely invisible - we must fix this, and efficiently so"): every plot
    # with pieces within `r` metres of a place, each piece reduced to its bounding box and its block (what a page draws
    # at a kilometre: a box of the block's colour), with the plot's version so a page refetches only what changed.
    def far_view(self, face, u, v, r, since=None):
        out = []
        for p, rec in self.plots.items():
            boxes = rec.get("boxes") or []
            if not boxes:
                continue
            pf, prow, pcol = plot_coords(p)
            u0, v0 = pcol * PLOT, prow * PLOT
            if pf != face or max(u0 - u, 0, u - u0 - PLOT) > r or max(v0 - v, 0, v - v0 - PLOT) > r:
                continue
            if since is not None and since.get(str(p)) == rec["ver"]:
                out.append({"plot": p, "ver": rec["ver"]})               # unchanged: the page keeps what it has
                continue
            far = []
            for b in boxes:
                a = box_aabb(b)
                far.append([int(a[0]), int(a[1]), int(a[2]), int(a[3]), int(a[4]), int(a[5]), int(b[6])])
            out.append({"plot": p, "ver": rec["ver"], "boxes": far})
        return out

    def crafts_near(self, pos, near):
        return [c for c in self.crafts.values() if c["pose"][0] == pos[0] and abs(c["pose"][1] - pos[1]) < near and abs(c["pose"][2] - pos[2]) < near]

    def crafts_of(self, who):
        """FINDING ONE'S CRAFTS (#171, operator: "i left the x somewhere"): every craft a player owns, wherever it is —
        [{id, pose, pilot, pieces: n}], nearest first is the page's to sort."""
        return [{"id": c["id"], "pose": c["pose"], "pilot": c["pilot"], "pieces": len(c["pieces"])}
                for c in sorted(self.crafts.values(), key=lambda c: c["id"]) if c["owner"] == who]

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

    # -- MARKETS (#161, doc/land-civilisation.md): "local markets first, global only with the invention of the internet"
    # (operator 2026-11-09). An offer lives at the trading stand it was made at; it is seen and taken at the stands of
    # its market (within market.reach of it); a gift is handed over in person. `pos` is where the caller stands
    # ([face, u, v, h, ...]: their open page's place, else the place kept for them) — None: nowhere known.
    def stands_near(self, pos, r):
        """The trading stands within r metres (across the ground) of pos: [(plot, box, [face, u, v]), ...], nearest first."""
        if not pos:
            return []
        f, u, v = int(pos[0]), pos[1], pos[2]
        out, n = [], int(r // PLOT) + 1
        for dp in range(-n, n + 1):
            for dq in range(-n, n + 1):
                if not (0 <= u + dp * PLOT < W and 0 <= v + dq * PLOT < W):
                    continue
                p = plot_of(f, int(u + dp * PLOT), int(v + dq * PLOT))
                rec = self.plots.get(p)
                if not rec or not rec.get("boxes"):
                    continue
                fc, fr = p % FACE_N, (p // FACE_N) % FACE_N
                for b in rec["boxes"]:
                    if b[6] != STAND:
                        continue
                    cu, cv = fc * PLOT + (b[0] + b[3] / 2) / 100, fr * PLOT + (b[1] + b[4] / 2) / 100
                    d = math.hypot(cu - u, cv - v)
                    if d <= r:
                        out.append((d, p, b, [f, cu, cv]))
        return [(p, b, spot) for d, p, b, spot in sorted(out, key=lambda x: x[0])]

    def offer_seen(self, o, who, pos):
        """An offer is seen by its maker anywhere (to withdraw it), and by anyone else within market.reach of its stand."""
        if o["by"] == who:
            return True
        spot = o.get("spot")
        return bool(spot and pos and spot[0] == int(pos[0]) and math.hypot(spot[1] - pos[1], spot[2] - pos[2]) <= RULES["market"]["reach"])

    def offers_for(self, who, pos):
        return sorted((o for o in self.offers.values() if self.offer_seen(o, who, pos)), key=lambda o: -o["at"])[:500]

    def give(self, who, to, items, pos=None, to_pos=None):
        bag = self._bag(items)
        if not bag:
            return "name the items and counts to give"
        if not validate_address(to, allow_reserved=False) or to == who:
            return "that is not another player's address"
        if not (pos and to_pos and int(pos[0]) == int(to_pos[0]) and math.hypot(pos[1] - to_pos[1], pos[2] - to_pos[2]) <= RULES["market"]["hand"]):
            return "a gift is handed over in person — stand beside them"
        pl = self.player(who)
        if any(pl["items"].get(k, 0) < n for k, n in bag.items()):
            return "you do not have that much"
        dst = self.player(to)
        for k, n in bag.items():
            pl["items"][k] -= n; dst["items"][k] = dst["items"].get(k, 0) + n
        self.pdirty.update((who, to))
        return None

    def offer(self, who, give, want, pos=None):
        g, w = self._bag(give), self._bag(want)
        if not g or not w:
            return None, "an offer gives some items and wants some items"
        if any(RULES["items"][k].get("quest") for k in list(g) + list(w)):
            return None, "a quest's parcel is carried, not traded"
        at = self.stands_near(pos, RULES["market"]["at"])
        if not at:
            return None, "an offer is made at a trading stand — build one, or go to a market"
        pl = self.player(who)
        if any(pl["items"].get(k, 0) < n for k, n in g.items()):
            return None, "you do not have what you offer"
        if sum(1 for o in self.offers.values() if o["by"] == who) >= 50:
            return None, "at most 50 open offers each"
        for k, n in g.items():                                     # escrowed until taken or cancelled
            pl["items"][k] -= n
        oid = secrets.token_hex(6)
        self.offers[oid] = {"id": oid, "by": who, "give": g, "want": w, "at": int(time.time()), "stand": [at[0][0], at[0][1]], "spot": at[0][2]}
        self.pdirty.add(who); self.odirty = True
        return oid, None

    def accept(self, who, oid, pos=None):
        o = self.offers.get(oid)
        if not o:
            return "that offer is gone"
        if o["by"] == who:
            return "that is your own offer"
        if not o.get("spot"):                                     # made before the markets: only its maker withdraws it
            return "that offer is from before the markets — only its maker can withdraw it"
        if not self.stands_near(pos, RULES["market"]["at"]) or not self.offer_seen(o, who, pos):
            return "an offer is taken at a trading stand of its market — go there"
        pl, maker = self.player(who), self.player(o["by"])
        if any(pl["items"].get(k, 0) < n for k, n in o["want"].items()):
            return "you do not have what it asks for"
        fee = RULES["market"]["fee"]
        for k, n in o["want"].items():
            # the market's share of what the maker gets goes to the TOWN TREASURY, which pays quests (#165): out of
            # circulation until a quest pays it back — never coins or goods from nothing
            pl["items"][k] -= n; maker["items"][k] = maker["items"].get(k, 0) + n - int(n * fee)
            if int(n * fee):
                self.treasury[k] = self.treasury.get(k, 0) + int(n * fee)
        for k, n in o["give"].items():
            pl["items"][k] = pl["items"].get(k, 0) + n
        del self.offers[oid]
        # on the record (#163): what went for what, where and when — the market's prices come from these
        self.trades.append({"at": int(time.time()), "spot": o["spot"], "give": o["give"], "want": o["want"]})
        del self.trades[:-RULES["market"]["keep_trades"]]
        self.pdirty.update((who, o["by"])); self.odirty = True
        return None

    def prices(self, pos, unit, now=None):
        """PRICES (#163): what each item is worth in `unit` at the market where `pos` stands, from its trades alone — the
        volume-weighted ratio of each pair's trades in the window, each trade weighing half as much every half_life_s;
        an item never traded for `unit` priced through the items linking them, the best-traded path first.
        Returns {"unit", "values": {item: value}, "trades": n}. A trade of several items on a side splits nothing: it
        names no single price, and is left out."""
        MK, now = RULES["market"], time.time() if now is None else now
        pair = {}                                                # (x, y) -> [weight, w*qx, w*qy]
        n = 0
        for t in self.trades:
            age = now - t["at"]
            if age < 0 or age > MK["window_s"] or not pos or t["spot"][0] != int(pos[0]) \
                    or math.hypot(t["spot"][1] - pos[1], t["spot"][2] - pos[2]) > MK["reach"]:
                continue
            if len(t["give"]) != 1 or len(t["want"]) != 1:
                continue
            (x, qx), = t["give"].items()
            (y, qy), = t["want"].items()
            if x == y:
                continue
            w = 0.5 ** (age / MK["half_life_s"])
            n += 1
            for a, qa, b, qb in ((x, qx, y, qy), (y, qy, x, qx)):
                e = pair.setdefault((a, b), [0.0, 0.0, 0.0])
                e[0] += w; e[1] += w * qa; e[2] += w * qb
        values, best = {unit: 1.0}, {unit: float("inf")}
        frontier = [unit]
        while frontier:                                          # widest path: the best-traded link first
            frontier.sort(key=lambda k: -best[k])
            y = frontier.pop(0)
            for (a, b), (w, wa, wb) in pair.items():
                if b != y or wa <= 0:
                    continue
                strength = min(best[y], w)
                if a not in best or strength > best[a]:
                    best[a] = strength
                    values[a] = values[y] * wb / wa              # one a is worth wb/wa of y
                    if a not in frontier:
                        frontier.append(a)
        values.pop(unit, None)                                   # (one of the unit is worth one: not a price)
        return {"unit": unit, "values": {k: round(v, 6) for k, v in sorted(values.items())}, "trades": n}

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
        """Each socket the offers of the market where its player stands, and their own (#161: markets are local)."""
        for ws, st in list(self.socks.items()):
            try:
                await ws.send_json({"t": "offers", "offers": world.offers_for(st["who"], st.get("pos"))})
            except Exception:
                pass

    async def hurt(self, world, who, dmg, by):
        """A player struck (#162): their sockets are told their health, or that they died and where they wake."""
        res = world.hurt(who, dmg, by)
        if not res:
            return None
        msg = {"t": "hurt", "hp": res[1], "by": by} if res[0] == "hurt" else {"t": "died", "by": by, "bed": res[1][:4] if res[1] else None}
        at = getattr(world, "struck_from", {}).get(who)
        if at and res[0] == "hurt":
            msg["at"] = [round(at[0], 2), round(at[1], 2)]          # where the blow came from: the page shows the side (#176)
        for ws, st in list(self.socks.items()):
            if st["who"] == who and res[0] == "died":              # they wake far off: the pace starts again there (#167)
                wake = list(res[1][:4]) if res[1] else landing() + [(st.get("pos") or [0, 0, 0, 0.0])[3]]
                st["pace"] = (wake, time.time())
                # NO SECOND DEATH BEHIND THE CARD (#176): the socket stands at the wake place from now, whatever the page
                # (still at the death spot until its player presses Wake up, or away from the keyboard) goes on
                # reporting — see the "pos" handler. A player left at the death spot died again every grace_s: nine
                # deaths in one incident on the playtest of 2026-11-11, 1,103 on the town agent's record.
                st["pos"] = [int(wake[0]), float(wake[1]), float(wake[2]), float(wake[3]), 0.0]
                st["pos_t"] = time.time()
                st["dead"] = wake[:3]
            if st["who"] == who:
                try:
                    await ws.send_json(msg)
                except Exception:
                    pass
        await self.inv(world, who)
        return res

    async def herd_step(self, world):
        """One step of the animals around the open pages, and what it did to the players: who is charged, who is struck."""
        socks = [st for st in self.socks.values() if st.get("pos")]
        # the signed-in ones can be charged (#162); a visitor is seen by the animals, never hurt
        hits = await world.herd([st["pos"] for st in socks], players=[(st["who"], st["pos"]) for st in socks if st["who"]])
        for who, aid, kind, au, av in world.charges:
            await self.charged(who, aid, kind, au, av)
        for who, dmg, by in hits or []:
            await self.hurt(world, who, dmg, by)

    async def charged(self, who, aid, kind, u, v):
        """An animal turned on `who` (#176): their pages are told which one and where it is."""
        for ws, st in list(self.socks.items()):
            if st["who"] == who:
                try:
                    await ws.send_json({"t": "charge", "id": aid, "by": kind, "at": [round(u, 2), round(v, 2)]})
                except Exception:
                    pass

    @staticmethod
    def pace_anchor(world, st, addr):
        """The place (and when) a socket's next reported place is measured from: its last accepted one, else the place
        the world server kept for the player (#167)."""
        if st.get("pace"):
            return st["pace"]
        pl = world.player(addr)
        return (pl["pos"], pl.get("pos_at", 0)) if pl.get("pos") else None

    def where(self, world, addr):
        """Where a player stands: the place their most recently moved open page said, else the place the world server
        kept for them. The most recent, not the first found: a player with two pages open (a phone and a desktop, or an
        old tab) was measured from whichever socket came first — a dig beside them refused "out of reach" (the page walk
        with two tabs, 2026-11-10, #167)."""
        # …and the place the world server KEPT when that is newer still: an agent moving by /land/api/move while a tab of
        # theirs was open (or a socket not yet closed) was measured from the tab's old place — every dig beside the agent
        # refused "out of reach" (2026-11-11, mining iron ore for the map).
        if not addr:
            return None
        mine = [st for st in self.socks.values() if st.get("who") == addr and st.get("pos")]
        page = max(mine, key=lambda st: st.get("pos_t", 0)) if mine else None
        kept = world.player(addr)
        if page and (not kept.get("pos") or page.get("pos_t", 0) > kept.get("pos_t", 0)):
            return page["pos"]
        return kept.get("pos")

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
                    o = {"id": c["id"], "owner": c["owner"], "pilot": c["pilot"], "pose": c["pose"], "mass": c["mass"], "thrust": c["thrust"],
                         "eng": c.get("eng")}                          # the engines' work, for its exhaust (#171)
                    if c["id"] not in seen:
                        o["pieces"] = c["pieces"]; seen.add(c["id"])
                    crafts.append(o)
            animals = world.animals_near(me, self.NEAR) if world else []
            npcs = world.npcs_for(st["who"], me, self.NEAR) if world else []
            drops = world.drops_near(me, 64) if world else []
            try:
                await ws.send_json({"t": "players", "list": near, "crafts": crafts, "animals": animals, "npcs": npcs, "drops": drops})
            except Exception:
                pass


def make_app(world, hub, site_origin, wallet_url, secure_cookies=True, shot_page=None):
    async def on_start(app):
        world.http = ClientSession(timeout=ClientTimeout(total=10))
        await world.start_oracle()
        app["bg"] = [asyncio.ensure_future(_flusher()), asyncio.ensure_future(_mover()), asyncio.ensure_future(_regrower()),
                     asyncio.ensure_future(_ecology()), asyncio.ensure_future(_fire()), asyncio.ensure_future(_factory()),
                     asyncio.ensure_future(_herd())]
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

    async def _herd():                                     # HUNTING (#156): the animals near the players present
        while True:
            await asyncio.sleep(0.5)
            try:
                await hub.herd_step(world)
                for who in world.heal():
                    await hub.inv(world, who)
            except Exception:
                pass

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

    async def far_api(request):
        """GET /land/api/far?face=&u=&v=&r= -> {plots: [{plot, ver, boxes: [[x, z, y, w, d, h, block]…]}]}: the pieces of
        every built plot within r metres (at most FAR_R), each as its bounding box in cm of its plot, for the page's far
        buildings (#193). `since` = JSON {plot: ver} the page holds: those plots come back without boxes when unchanged."""
        try:
            f, u, v = int(request.query.get("face", 0)), float(request.query["u"]), float(request.query["v"])
            r = min(FAR_R, max(0.0, float(request.query.get("r", FAR_R))))
            since = json.loads(request.query["since"]) if request.query.get("since") else None
            if since is not None and not isinstance(since, dict):
                raise ValueError("since")
        except (KeyError, ValueError):
            raise web.HTTPBadRequest(text="face, u, v, r and since (a JSON object)")
        return web.json_response({"plots": world.far_view(f, u, v, r, since)})

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
        applied, refused, changed = await world.apply(addr, d.get("cells"), at=hub.where(world, addr))
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

    async def move(request):
        """POST /land/api/move {"p": [face, u, v, h, yaw]}: where an agent without a page stands (#167) — no faster than a
        player can go from where it last stood; refused with where it is kept."""
        addr, d = need_addr(request), await request.json()
        p = d.get("p")
        if not (isinstance(p, list) and len(p) == 5 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in p)
                and 0 <= p[0] < 6 and 0 <= p[1] < W and 0 <= p[2] < W and DEEP_MIN <= p[3] < H + 400):
            return web.json_response({"ok": False, "error": "p is [face, u, v, h, yaw] in the world"})
        pl = world.player(addr)
        if not world.pace_free and pl.get("pos") and not pace_ok(pl["pos"], pl.get("pos_at", 0), p, time.time()):
            return web.json_response({"ok": False, "error": "faster than you can go — move in steps (about %d m/s)" % PACE_MPS, "at": pl["pos"]})
        world.keep_place(addr, p)
        return web.json_response({"ok": True, "at": world.player(addr)["pos"]})

    async def draw_well(request):
        addr, d = need_addr(request), await request.json()
        err = await world.well(addr, d.get("plot"), d.get("box"))
        if not err:
            await hub.inv(world, addr)
        return web.json_response({"ok": not err, "error": err, "inventory": world.inv_json(addr)})

    async def shoot(request):
        addr, d = need_addr(request), await request.json()
        res, err = await world.loose_arrow(addr, hub.where(world, addr), d.get("yaw"), d.get("pitch"))
        if res is not None:
            await hub.inv(world, addr)
        return web.json_response(dict(res or {}, ok=not err, error=err, inventory=world.inv_json(addr)))

    async def pickup(request):
        addr, d = need_addr(request), await request.json()
        err = world.pickup(addr, d.get("id"), hub.where(world, addr))
        if not err:
            await hub.inv(world, addr)
        return web.json_response({"ok": not err, "error": err, "inventory": world.inv_json(addr)})

    async def talk(request):
        addr = need_addr(request)
        res, err = world.talk(addr, request.query.get("npc"), hub.where(world, addr))
        return web.json_response(dict(res or {}, ok=not err, error=err))

    async def quest(request):
        addr, d = need_addr(request), await request.json()
        res, err = world.quest(addr, d.get("op"), d.get("npc"), d.get("id"), hub.where(world, addr))
        if not err:
            await hub.inv(world, addr)
        return web.json_response(dict(res or {}, ok=not err, error=err, inventory=world.inv_json(addr)))

    async def bed(request):
        addr, d = need_addr(request), await request.json()
        err = world.bed(addr, d.get("plot"), d.get("box"))
        return web.json_response({"ok": not err, "error": err})

    async def hunt(request):
        addr, d = need_addr(request), await request.json()
        pos = next((st["pos"] for st in hub.socks.values() if st.get("who") == addr and st.get("pos")), None) or world.player(addr).get("pos")
        res, err = world.hunt(addr, d.get("id"), pos)
        if res:                                                     # game in the bag, or an arrow spent
            await hub.inv(world, addr)
        return web.json_response(dict(res or {}, ok=not err, error=err, inventory=world.inv_json(addr)))

    async def animals(request):
        f, u, v = (float(request.query.get(k, "0")) for k in ("face", "u", "v"))
        return web.json_response({"animals": world.animals_near([int(f), u, v], Hub.NEAR)})

    async def give(request):
        addr, d = need_addr(request), await request.json()
        err = world.give(addr, d.get("to", ""), d.get("items"), hub.where(world, addr), hub.where(world, d.get("to")))
        if not err:
            await hub.inv(world, addr); await hub.inv(world, d.get("to"))
        return web.json_response({"ok": not err, "error": err, "inventory": world.inv_json(addr)})

    async def offers(request):
        # the offers of the market where the caller stands (#161), or of the place named by face/u/v
        addr, q = world.who(request), request.query
        pos = [int(q["face"]), float(q["u"]), float(q["v"])] if all(k in q for k in ("face", "u", "v")) else hub.where(world, addr)
        return web.json_response({"offers": world.offers_for(addr, pos)})

    async def prices(request):
        # what things are worth at the market where the caller stands (#163), or at the place named by face/u/v, in `unit`
        addr, q = world.who(request), request.query
        pos = [int(q["face"]), float(q["u"]), float(q["v"])] if all(k in q for k in ("face", "u", "v")) else hub.where(world, addr)
        unit = q.get("unit", "copper_coin")
        if unit not in RULES["items"]:
            raise web.HTTPBadRequest(text="unit: an item")
        now, day = time.time(), 86400
        return web.json_response(dict(world.prices(pos, unit, now), before=world.prices(pos, unit, now - day)["values"]))

    async def offer(request):
        addr, d = need_addr(request), await request.json()
        oid, err = world.offer(addr, d.get("give"), d.get("want"), hub.where(world, addr))
        if not err:
            await hub.inv(world, addr); await hub.offers(world)
        return web.json_response({"ok": not err, "id": oid, "error": err, "inventory": world.inv_json(addr)})

    async def accept(request):
        addr, d = need_addr(request), await request.json()
        maker = (world.offers.get(d.get("id")) or {}).get("by")
        err = world.accept(addr, d.get("id"), hub.where(world, addr))
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
        # RELOADED IN THE AIR (operator 2026-11-10: "on respawn i fell out of the x and cannot reenter it … by respawn i
        # mean browser reload"): a page that reloads mid-flight forgot it was flying, while the craft stayed in the air
        # with them as its pilot — out of reach. The greeting names the craft they pilot; the page takes its seat again.
        flying = next((cid for cid, c in world.crafts.items() if addr and c.get("pilot") == addr), None)
        await ws.send_json({"t": "hello", "you": addr, "id": st["id"], "flying": flying,
                            **({"pos": world.player(addr).get("pos"), "pos_at": world.player(addr).get("pos_at")} if addr else {})})
        if addr:
            await ws.send_json(dict(world.inv_json(addr), t="inv"))
        await ws.send_json({"t": "offers", "offers": world.offers_for(addr, world.player(addr).get("pos") if addr else None)})
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
                        if st.get("dead"):
                            # the page of someone who died (#176): until it reports from the place they wake (it moves
                            # there with the death card; an older page only on Wake up) its reports are of the death
                            # spot — dropped without a word. Answering them with a pace pos_fix told a dead player
                            # "Faster than anyone can go" four times in eleven seconds.
                            d = st["dead"]
                            if int(p[0]) != d[0] or math.hypot(p[1] - d[1], p[2] - d[2]) > WAKE_NEAR:
                                continue
                            st["dead"] = None
                            st["pace"] = (list(p), time.time())
                            world.player(addr)["grace"] = time.time() + RULES["health"]["grace_s"]   # the grace runs from the waking
                        if addr and not world.pace_free:            # TRAVEL (#167): no faster than one can go
                            anc = hub.pace_anchor(world, st, addr)
                            if anc and not pace_ok(anc[0], anc[1], p, time.time()):
                                await ws.send_json({"t": "pos_fix", "p": list(anc[0][:4]), "why": "pace"})
                                continue
                            st["pace"] = (list(p), time.time())
                        st["pos"] = [int(p[0]), float(p[1]), float(p[2]), float(p[3]), float(p[4])]
                        st["pos_t"] = time.time()                  # which of a player's pages moved last (Hub.where)
                        if addr:
                            world.survey_at(addr, st["pos"])       # a map carried draws every square walked (#173), not only those of the saves
                        if time.time() - st.get("offers_at", 0) > 5:      # the market where they stand now (#161)
                            st["offers_at"] = time.time()
                            await ws.send_json({"t": "offers", "offers": world.offers_for(addr, st["pos"])})
                        if addr and time.time() - st.get("pos_at", 0) > POS_SAVE_S:
                            world.keep_place(addr, st["pos"]); st["pos_at"] = time.time()
                elif t == "set":
                    if not addr:
                        await ws.send_json({"t": "set_ok", "applied": 0, "refused": [[None, "sign in to build"]], "req": m.get("req")})
                        continue
                    applied, refused, changed = await world.apply(addr, m.get("cells"), at=st["pos"] or hub.where(world, addr))
                    await ws.send_json({"t": "set_ok", "applied": sum(len(c) for c in applied.values()), "refused": refused, "req": m.get("req")})
                    await hub.edits(applied, addr)
                    if changed:
                        await hub.inv(world, addr)
                elif t == "tp":
                    # /tp (#167): to the landing, or to your own bed — nowhere else; the page is told where it now is
                    if not addr:
                        continue
                    pl = world.player(addr)
                    if m.get("to") == "bed":
                        if not pl.get("bed"):
                            await ws.send_json({"t": "pos_fix", "p": None, "why": "nobed"}); continue
                        to = list(pl["bed"][:4])
                    else:
                        to = landing() + [None]
                    st["pace"] = (to, time.time())
                    await ws.send_json({"t": "pos_fix", "p": to, "why": "tp", "to": "bed" if m.get("to") == "bed" else "spawn"})
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
                elif t in ("pad", "launch"):                       # #173: a launch pad's numbers, and the launch
                    if not addr:
                        await ws.send_json({"t": "pad", "req": m.get("req"), "error": "sign in first"})
                        continue
                    if t == "pad":
                        pl, pd = m.get("plot"), m.get("box")
                        ok = pl in world.plots and isinstance(pd, list) and pd in world.plots[pl].get("boxes", []) and pd[6] == LAUNCH_PAD
                        await ws.send_json({"t": "pad", "req": m.get("req"), "plot": pl, "box": pd,
                                            **({"num": await world.launch_numbers(pl, pd)} if ok else {"error": "no launch pad here"})})
                    else:
                        num, gone, err = await world.launch(addr, m.get("plot"), m.get("box"))
                        await ws.send_json({"t": "launched", "req": m.get("req"), "plot": m.get("plot"), "num": num, "error": err})
                        if gone:
                            await hub.boxes(m.get("plot"), [], gone, addr)
                elif t == "survey":                                 # #173: what my map shows
                    await ws.send_json({"t": "survey", "req": m.get("req"), **(world.survey_of(addr) if addr else {"error": "sign in first"})})
                elif t == "mycrafts":                               # #171: where are my crafts
                    await ws.send_json({"t": "mycrafts", "req": m.get("req"), "list": world.crafts_of(addr) if addr else [],
                                        **({} if addr else {"error": "sign in first"})})
                elif t == "trace":                                        # the page's event trace (#194), a signed-in player's own file
                    world.trace_append(addr, m.get("events"))
                elif t in ("board", "fly", "leave", "dock", "handover"):   # not "give": that is a gift of items
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
                        err = world.fly(addr, m.get("craft"), m.get("pose"), m.get("eng"))
                        if err and m.get("craft") in world.crafts:
                            await ws.send_json({"t": "craft_fix", "craft": m.get("craft"), "pose": world.crafts[m.get("craft")]["pose"], "error": err})
                        elif not err:
                            # THE PILOT IS WHERE THE CRAFT IS (#192): the craft's pose, bounded by its top speed, is the
                            # pilot's place and the anchor their next "pos" is paced from. Their "pos" reports were refused
                            # as faster than walking, so the server kept the spot they BOARDED at — and a deer charged and
                            # bit a pilot 500 m up (operator, 2026-11-11: "im getting attacked by a deer 500 meters above
                            # the ground"), the herd, the market and "where" all reading that ground spot.
                            c = world.crafts[m.get("craft")]
                            st["pos"] = list(c["pose"]); st["pace"] = (list(c["pose"]), time.time()); st["pos_t"] = time.time()
                    elif t == "leave":
                        await ws.send_json({"t": "craft_ok", "op": t, "req": m.get("req"), "error": world.leave(addr, m.get("craft"))})
                    elif t == "handover":
                        err = world.give_craft(addr, m.get("craft"), m.get("to"))
                        await ws.send_json({"t": "craft_ok", "op": t, "req": m.get("req"), "error": err, "to": m.get("to")})
                        if not err:                                     # the receiver's pages take its controls
                            c = world.crafts[m.get("craft")]
                            for w2, s2 in list(hub.socks.items()):
                                if s2.get("who") == m.get("to"):
                                    try:
                                        await w2.send_json({"t": "given", "craft": c["id"], "by": addr})
                                    except Exception:
                                        pass
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
                elif t == "hunt":                                   # HUNTING (#156): a strike from where the hunter stands
                    if not addr:
                        await ws.send_json({"t": "hunt", "req": m.get("req"), "error": "sign in first"})
                        continue
                    res, err = world.hunt(addr, m.get("id"), st.get("pos"))
                    await ws.send_json(dict(res or {}, t="hunt", req=m.get("req"), error=err))
                    if res:                                         # game in the bag, or an arrow spent: the bag changed
                        await hub.inv(world, addr)
                elif t in ("shoot", "pickup"):                      # BALLISTICS (#157): an arrow loosed; one picked up
                    if not addr:
                        await ws.send_json({"t": t, "req": m.get("req"), "error": "sign in first"})
                        continue
                    if t == "shoot":
                        res, err = await world.loose_arrow(addr, st.get("pos"), m.get("yaw"), m.get("pitch"))
                    else:
                        res, err = {}, world.pickup(addr, m.get("id"), st.get("pos"))
                    await ws.send_json(dict(res or {}, t=t, req=m.get("req"), error=err))
                    if res is not None and not (t == "pickup" and err):
                        await hub.inv(world, addr)
                elif t in ("talk", "quest"):                        # NPCS AND QUESTS (#165)
                    if not addr:
                        await ws.send_json({"t": t, "req": m.get("req"), "error": "sign in first"})
                        continue
                    here = st.get("pos") or hub.where(world, addr)
                    res, err = world.talk(addr, m.get("npc"), here) if t == "talk" else world.quest(addr, m.get("op"), m.get("npc"), m.get("id"), here)
                    await ws.send_json(dict(res or {}, t=t, req=m.get("req"), op=m.get("op"), error=err))
                    if t == "quest" and not err:
                        await hub.inv(world, addr)
                elif t == "bed":                                    # #162: wake here after a death
                    err = world.bed(addr, m.get("plot"), m.get("box")) if addr else "sign in first"
                    await ws.send_json({"t": "done", "req": m.get("req"), "op": "bed", "error": err})
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
                    here = st.get("pos") or hub.where(world, addr)        # (#161: markets and gifts are where you stand)
                    err = (world.craft(addr, m.get("recipe"), m.get("times", 1)) if t == "craft"
                           else world.give(addr, m.get("to", ""), m.get("items"), here, hub.where(world, m.get("to"))) if t == "give"
                           else world.offer(addr, m.get("give"), m.get("want"), here)[1] if t == "offer"
                           else world.accept(addr, m.get("id"), here) if t == "accept" else world.cancel(addr, m.get("id")))
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
        web.get("/land/api/far", far_api),
        web.get("/land/api/sats", lambda request: web.json_response({"sats": world.sats, "orbit": RULES["rocket"]["orbit"]})),
        web.get("/land/api/shot", shot),
        web.post("/land/api/set", set_cells),
        web.post("/land/api/boxes", boxes),
        web.get("/land/api/inventory", inventory),
        web.post("/land/api/craft", craft),
        web.post("/land/api/give", give),
        web.post("/land/api/eat", eat),
        web.post("/land/api/hunt", hunt),
        web.post("/land/api/bed", bed),
        web.get("/land/api/talk", talk),
        web.post("/land/api/shoot", shoot),
        web.post("/land/api/pickup", pickup),
        web.post("/land/api/quest", quest),
        web.get("/land/api/animals", animals),
        web.get("/land/api/prices", prices),
        web.post("/land/api/well", draw_well),
        web.post("/land/api/move", move),
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
