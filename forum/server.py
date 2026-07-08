"""
NADO forum — a from-scratch, wallet-native community + governance forum (doc/forum.md).

Identity IS your NADO wallet: you sign a one-time challenge with your post-quantum ML-DSA key (via the
interface, SSO handoff) and your `ndo…` address is your account. No passwords, no email. Posting is gated to
REGISTERED on-chain addresses, so spam costs the same sequential PoW the chain already requires.

Stack: aiohttp + SQLite (WAL). Reuses the node's own crypto (Curve25519 / ml-dsa, ops.address_ops,
hashing). Runs as its own systemd service behind nginx on forum.nadochain.com.

Security hardening (post adversarial review): browser-bound login challenge (login-CSRF), mod-board reply
gate, Origin-checked mutating POSTs, per-IP rate limits + bounded challenge store, revocable sessions,
CSP/security headers, __Host- cookie prefixes, cached registered-check on a shared client session.
"""
import os
import sys
import time
import json
import hmac
import base64
import asyncio
import hashlib
import secrets
import sqlite3
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from Curve25519 import verify as mldsa_verify, unhex
from ops.address_ops import proof_sender, validate_address
from hashing import blake2b_hash

import aiohttp
from aiohttp import web

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- config (env-overridable) --------------------------------------------------------------------
DB_PATH       = os.environ.get("FORUM_DB", os.path.join(HERE, "forum.db"))
PORT          = int(os.environ.get("FORUM_PORT", "8781"))
SECRET_FILE   = os.environ.get("FORUM_SECRET_FILE", os.path.join(HERE, ".secret"))
NADO_NODE     = os.environ.get("NADO_NODE", "http://127.0.0.1:9173").rstrip("/")
INTERFACE_URL = os.environ.get("INTERFACE_URL", "https://get.nadochain.com").rstrip("/")
FORUM_ORIGIN  = os.environ.get("FORUM_ORIGIN", "https://forum.nadochain.com").rstrip("/")
MODS          = set(a.strip() for a in os.environ.get("FORUM_MODS", "").split(",") if a.strip())
REQUIRE_REG   = os.environ.get("FORUM_REQUIRE_REGISTERED", "1") == "1"
COOKIE_SECURE = os.environ.get("FORUM_COOKIE_SECURE", "1") == "1"   # set 0 for local http testing

CHALLENGE_TTL = 300
MAX_CHALLENGES = 20000           # hard cap on the in-memory login-challenge store (DoS bound)
SESSION_TTL   = 7 * 86400
POST_MIN_GAP  = 8
REG_CACHE_TTL = 60
BODY_MAX      = 20000
TITLE_MAX     = 200
PID_MAX       = 128
# __Host- prefix (production) locks the cookie to the exact host, no Domain override from a sibling subdomain.
SESS_COOKIE   = "__Host-nadoforum" if COOKIE_SECURE else "nadoforum"
LOGIN_COOKIE  = "__Host-nadologin" if COOKIE_SECURE else "nadologin"

def _load_secret():
    """Load the HMAC session-signing secret from SECRET_FILE, generating a 0o600 32-byte one on first run."""
    if os.path.exists(SECRET_FILE):
        return open(SECRET_FILE, "rb").read()
    s = secrets.token_bytes(32)
    fd = os.open(SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(s)
    return s

SECRET = _load_secret()

# ---- db ------------------------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  address TEXT PRIMARY KEY, public_key TEXT, handle TEXT, created_at INTEGER, last_seen INTEGER,
  role TEXT DEFAULT 'user', sver INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS boards (
  id INTEGER PRIMARY KEY, slug TEXT UNIQUE, title TEXT, description TEXT, position INTEGER DEFAULT 0, post_min_role TEXT DEFAULT 'user');
CREATE TABLE IF NOT EXISTS threads (
  id INTEGER PRIMARY KEY, board_id INTEGER, author TEXT, title TEXT, created_at INTEGER, bumped_at INTEGER,
  locked INTEGER DEFAULT 0, pinned INTEGER DEFAULT 0, pid TEXT);
CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY, thread_id INTEGER, author TEXT, body_md TEXT, created_at INTEGER, edited_at INTEGER, deleted INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_threads_board ON threads(board_id, bumped_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_thread ON posts(thread_id, created_at);
"""

def db():
    """Open a new SQLite connection to DB_PATH (Row factory, WAL, 4s busy timeout). Caller closes."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=4000")
    return con

def init_db():
    """Create the schema (idempotent), migrate older DBs (users.sver), and seed the default boards once."""
    con = db()
    con.executescript(SCHEMA)
    try: con.execute("ALTER TABLE users ADD COLUMN sver INTEGER DEFAULT 0")   # migrate older DBs
    except sqlite3.OperationalError: pass
    try: con.execute("ALTER TABLE threads ADD COLUMN deleted INTEGER DEFAULT 0")   # migrate: soft-delete threads
    except sqlite3.OperationalError: pass
    try: con.execute("ALTER TABLE users ADD COLUMN alias TEXT")   # migrate: preferred display alias ('-' = show address)
    except sqlite3.OperationalError: pass
    if not con.execute("SELECT 1 FROM boards LIMIT 1").fetchone():
        seed = [
            ("announcements", "Announcements", "Official news from the maintainers.", 0, "mod"),
            ("governance", "Governance", "Discuss treasury proposals before the Quorum vote.", 1, "user"),
            ("general", "General", "Everything NADO.", 2, "user"),
            ("mining", "Mining & Nodes", "Running a node, the open + bonded lanes, troubleshooting.", 3, "user"),
            ("dev", "Development", "Protocol, exec layer, the shielded pool, the stablecoin.", 4, "user"),
        ]
        con.executemany("INSERT INTO boards(slug,title,description,position,post_min_role) VALUES(?,?,?,?,?)", seed)
    con.commit(); con.close()

# ---- request helpers -----------------------------------------------------------------------------
def client_ip(request):
    """Best-effort real client IP: CF-Connecting-IP, then first XFF hop, then the socket peer."""
    # behind Cloudflare -> nginx. CF sets the real client in CF-Connecting-IP; fall back to XFF's first hop.
    cf = request.headers.get("CF-Connecting-IP")
    if cf: return cf.strip()
    xff = request.headers.get("X-Forwarded-For")
    if xff: return xff.split(",")[0].strip()
    return request.remote or "?"

def origin_ok(request):
    """Reject state-changing POSTs whose Origin/Referer isn't the forum itself (defense-in-depth CSRF)."""
    o = request.headers.get("Origin")
    if o is not None:
        return o.rstrip("/") == FORUM_ORIGIN
    r = request.headers.get("Referer")
    if r:
        return r.startswith(FORUM_ORIGIN + "/") or r.rstrip("/") == FORUM_ORIGIN
    return False        # no Origin and no Referer on a mutating request -> refuse

# generic fixed-window rate limiter: {bucket_key: (window_start, count)}
_rate = {}
def rate_ok(key, limit, window):
    """Fixed-window rate limiter: True while `key` has seen <= `limit` hits in the current `window` seconds.
    Counts the current hit before deciding; the shared store is opportunistically pruned past 100k entries."""
    now = time.time()
    ws, n = _rate.get(key, (now, 0))
    if now - ws >= window:
        ws, n = now, 0
    n += 1
    _rate[key] = (ws, n)
    if len(_rate) > 100000:               # bound the limiter itself
        for k in [k for k, v in _rate.items() if now - v[0] > window]:
            _rate.pop(k, None)
    return n <= limit

# ---- session cookie (HMAC-signed + per-user revocation version) -----------------------------------
def _b64(b):
    """URL-safe base64 without padding."""
    return base64.urlsafe_b64encode(b).decode().rstrip("=")
def _unb64(s):
    """Inverse of _b64: re-pad and decode URL-safe base64."""
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

def make_session(address, sver):
    """Mint an HMAC-SHA256-signed session token `b64(payload).b64(sig)` carrying address, the user's
    current session version (revocation), and an expiry SESSION_TTL from now."""
    payload = json.dumps({"a": address, "v": int(sver), "e": int(time.time()) + SESSION_TTL}, separators=(",", ":")).encode()
    sig = hmac.new(SECRET, payload, hashlib.sha256).digest()
    return _b64(payload) + "." + _b64(sig)

def _read_token(token):
    """Verify a session token (constant-time HMAC check + expiry); return the payload dict or None.
    Any malformed input returns None — never raises."""
    try:
        p, s = token.split(".")
        payload = _unb64(p)
        if not hmac.compare_digest(_unb64(s), hmac.new(SECRET, payload, hashlib.sha256).digest()):
            return None
        d = json.loads(payload)
        if d["e"] < time.time():
            return None
        return d
    except Exception:
        return None

def current_user(request):
    """Resolve the session cookie to a logged-in address, or None. Cross-checks the token's version
    against users.sver in the DB so logout/ban (which bump sver) revokes every outstanding token."""
    tok = request.cookies.get(SESS_COOKIE)
    d = _read_token(tok) if tok else None
    if not d:
        return None
    con = db()
    row = con.execute("SELECT sver FROM users WHERE address=?", (d["a"],)).fetchone()
    con.close()
    if row is None or int(row["sver"]) != int(d.get("v", -1)):   # revoked (logout/ban bumps sver)
        return None
    return d["a"]

def _cookie_kw():
    """Standard attributes for the session cookie: HttpOnly, SameSite=Lax, SESSION_TTL, secure per config."""
    return dict(max_age=SESSION_TTL, httponly=True, secure=COOKIE_SECURE, samesite="Lax", path="/")

# ---- login challenges (in-memory, short-lived, hard-capped) ---------------------------------------
_challenges = {}     # request_id -> {nonce, issued}

def _reap_challenges():
    """Drop login challenges older than CHALLENGE_TTL from the in-memory store."""
    now = time.time()
    for rid in [k for k, v in _challenges.items() if now - v["issued"] > CHALLENGE_TTL]:
        _challenges.pop(rid, None)

def challenge_message(address, nonce, issued):
    """Deterministic blake2b login-challenge digest the wallet must sign; domain-separated by the literal
    'nado-forum-login' tag and bound to FORUM_ORIGIN, address, nonce and issue time."""
    return blake2b_hash(["nado-forum-login", FORUM_ORIGIN, address, nonce, int(issued)])

# ---- on-chain lookups (shared session + short caches) ---------------------------------------------
_acct_cache = {}     # address -> (ts, account dict | None)
_alias_cache = {}    # address -> (ts, [alias names])
ALIAS_TTL = 300

def _http():
    """Return the shared aiohttp ClientSession created at app startup (_on_start)."""
    global _HTTP
    return _HTTP

def _bound(cache, cap=50000):
    """Hard-bound an in-memory cache: wipe it entirely past `cap` entries (all entries are re-fetchable)."""
    if len(cache) > cap:
        cache.clear()

async def get_account(address):
    """Cached (REG_CACHE_TTL) fetch of the node's /get_account for `address`. Returns the account
    dict, or None on node error / non-200 — errors are cached too, so a down node can't be hammered."""
    hit = _acct_cache.get(address)
    if hit and time.time() - hit[0] < REG_CACHE_TTL:
        return hit[1]
    acc = None
    try:
        async with _http().get(f"{NADO_NODE}/get_account?address={address}",
                               timeout=aiohttp.ClientTimeout(total=6)) as r:
            if r.status == 200:
                acc = await r.json()
    except Exception:
        acc = None
    _bound(_acct_cache)
    _acct_cache[address] = (time.time(), acc)
    return acc

async def is_registered(address):
    """Async check that `address` is REGISTERED on-chain (cached via get_account). Node errors fail
    closed (False). Always True when REQUIRE_REG is off."""
    if not REQUIRE_REG:
        return True
    acc = await get_account(address)
    return bool(acc) and int(acc.get("registered", 0)) == 1

async def aliases_of(address):
    """All on-chain alias names owned by `address` (node /get_aliases_of), cached ALIAS_TTL seconds.
    Errors return [] (cached) — the UI just falls back to the short address."""
    hit = _alias_cache.get(address)
    if hit and time.time() - hit[0] < ALIAS_TTL:
        return hit[1]
    names = []
    try:
        async with _http().get(f"{NADO_NODE}/get_aliases_of?address={address}",
                               timeout=aiohttp.ClientTimeout(total=6)) as r:
            if r.status == 200:
                d = await r.json()
                names = [str(n) for n in (d.get("aliases") or [])][:20]
    except Exception:
        names = []
    _bound(_alias_cache)
    _alias_cache[address] = (time.time(), names)
    return names

# ---- helpers -------------------------------------------------------------------------------------
def is_admin(address):
    """Bootstrap admins: the FORUM_MODS env set. Admins are always mods, can never be banned/demoted
    through the API, and are the only ones who can grant/revoke the mod role."""
    return address in MODS

def user_role(con, address):
    """Effective role. Env admins are always 'mod'; everyone else gets users.role from the DB
    ('user' / 'mod' / 'banned'; unknown address -> 'user'). DB-backed so mods can be added and
    users banned at runtime, without a service restart."""
    if address in MODS:
        return "mod"
    row = con.execute("SELECT role FROM users WHERE address=?", (address,)).fetchone()
    return (row["role"] or "user") if row else "user"

def touch_user(con, address, public_key=None):
    """Upsert the user row: refresh last_seen (and public_key if given), or insert a new user
    (handle defaults to the address prefix, sver=0). NEVER overwrites an existing row's role —
    roles are managed by /api/mod (the old role=role_of() rewrite would silently demote a
    DB-promoted mod on their next post). Env admins self-heal to 'mod'. Does not commit."""
    now = int(time.time())
    if con.execute("SELECT address FROM users WHERE address=?", (address,)).fetchone():
        con.execute("UPDATE users SET last_seen=?, public_key=COALESCE(?,public_key) WHERE address=?",
                    (now, public_key, address))
        if address in MODS:
            con.execute("UPDATE users SET role='mod' WHERE address=?", (address,))
    else:
        con.execute("INSERT INTO users(address,public_key,handle,created_at,last_seen,role,sver) VALUES(?,?,?,?,?,?,0)",
                    (address, public_key, address[:10], now, now, "mod" if address in MODS else "user"))

def pick_alias(names, preferred):
    """Effective display alias: the user's stored preference when they still own it on-chain
    (aliases are transferable — a stale pick falls back), '-' meaning 'show my address' (None),
    else the first owned alias, else None."""
    if preferred == "-":
        return None
    if preferred and preferred in names:
        return preferred
    return names[0] if names else None

def _pref_aliases(con, addrs):
    """The stored users.alias preference for each address in `addrs` (missing rows -> absent)."""
    if not addrs:
        return {}
    q = ",".join("?" * len(addrs))
    return {r["address"]: r["alias"] for r in
            con.execute(f"SELECT address, alias FROM users WHERE address IN ({q})", list(addrs))}

async def authors_meta(con, addresses):
    """Display metadata for a set of author addresses: {addr: {"alias": effective display alias
    (pick_alias) or None, "role": effective role}}. Alias lookups are cache-backed (ALIAS_TTL) and
    node misses are fetched concurrently, so enriching a thread page costs at most one round of
    parallel node calls."""
    addrs = sorted(set(a for a in addresses if a))
    names = await asyncio.gather(*(aliases_of(a) for a in addrs)) if addrs else []
    prefs = _pref_aliases(con, addrs)
    return {a: {"alias": pick_alias(n, prefs.get(a)), "role": user_role(con, a)} for a, n in zip(addrs, names)}

def jerr(msg, status=400):
    """JSON error response: {"ok": false, "error": msg} with the given HTTP status."""
    return web.json_response({"ok": False, "error": msg}, status=status)

async def _gate_post(request):
    """auth + Origin + rate-limit (cheap) + registered (cached). Returns (address, None) or (None, errresp)."""
    if not origin_ok(request):
        return None, jerr("bad origin", 403)
    a = current_user(request)
    if not a:
        return None, jerr("sign in to post", 401)
    now = time.time()
    if now - _last_post.get(a, 0) < POST_MIN_GAP:              # cheap in-memory check FIRST (before the node call)
        return None, jerr("slow down — one post every few seconds", 429)
    if not rate_ok("post_ip:" + client_ip(request), 20, 60):  # per-IP cap (bounds HD-account multiplication)
        return None, jerr("too many posts from your network — slow down", 429)
    con = db(); role = user_role(con, a); con.close()
    if role == "banned":
        return None, jerr("this address is banned from posting", 403)
    if not await is_registered(a):
        return None, jerr("posting requires a REGISTERED NADO address (do the one-time registration in the wallet)", 403)
    return a, None

_last_post = {}
def _reap_last_post():
    """Bound the per-author last-post map: past 50k entries, drop authors idle over an hour."""
    if len(_last_post) > 50000:
        now = time.time()
        for k in [k for k, t in _last_post.items() if now - t > 3600]:
            _last_post.pop(k, None)

# ---- SSO auth routes -----------------------------------------------------------------------------
async def sso_start(request):
    """GET /api/sso_start — begin wallet SSO. Mints a one-time challenge (rid+nonce, CHALLENGE_TTL) and
    302-redirects to the interface with ?forum_login=rid&nonce&forum&issued. The rid is ALSO set as the
    LOGIN_COOKIE so only the initiating browser can complete the login (login-CSRF bind). Anti-abuse:
    30/min per IP, and the challenge store is reaped + hard-capped at MAX_CHALLENGES (503 when full)."""
    if not rate_ok("sso:" + client_ip(request), 30, 60):
        return web.Response(text="rate limited — try again shortly", status=429)
    _reap_challenges()
    if len(_challenges) >= MAX_CHALLENGES:
        return web.Response(text="login temporarily busy — try again", status=503)
    rid = secrets.token_urlsafe(18)
    nonce = secrets.token_urlsafe(18)
    issued = int(time.time())
    _challenges[rid] = {"nonce": nonce, "issued": issued}
    q = urllib.parse.urlencode({"forum_login": rid, "nonce": nonce, "forum": FORUM_ORIGIN, "issued": issued})
    resp = web.HTTPFound(f"{INTERFACE_URL}/?{q}")
    # BIND the challenge to THIS browser (login-CSRF fix): the callback must present the same cookie.
    resp.set_cookie(LOGIN_COOKIE, rid, max_age=CHALLENGE_TTL, httponly=True, secure=COOKIE_SECURE, samesite="Lax", path="/")
    return resp

async def sso_callback(request):
    """POST /api/sso_callback — complete wallet SSO. Form fields: request_id, address, public_key,
    signature. Requires the LOGIN_COOKIE to equal request_id (same-browser bind), a live challenge,
    a valid `ndo…` address whose key hashes to it (proof_sender), and an ML-DSA signature over
    challenge_message(). On success: consume the challenge (single-use), upsert the user, set the
    signed session cookie, drop the login cookie, 302 to /. Failures are plain-text 4xx."""
    _reap_challenges()
    data = await request.post()
    rid = data.get("request_id", ""); address = data.get("address", "")
    public_key = data.get("public_key", ""); signature = data.get("signature", "")
    # login-CSRF: the callback MUST come from the browser that started the login (holds the LOGIN_COOKIE).
    if not rid or request.cookies.get(LOGIN_COOKIE) != rid:
        return web.Response(text="login must be started from this browser — go to the forum and click Sign in", status=403)
    ch = _challenges.get(rid)
    if not ch:
        return web.Response(text="login expired or unknown — try again", status=400)
    if not validate_address(address):
        return web.Response(text="bad address", status=400)
    if not proof_sender(public_key=public_key, sender=address):
        return web.Response(text="address does not match public key", status=400)
    msg = challenge_message(address, ch["nonce"], ch["issued"])
    try:
        ok = mldsa_verify(signed=signature, message=unhex(msg), public_key=public_key)
    except Exception:
        ok = False
    if not ok:
        return web.Response(text="signature verification failed", status=401)
    _challenges.pop(rid, None)
    con = db(); touch_user(con, address, public_key)
    sver = con.execute("SELECT sver FROM users WHERE address=?", (address,)).fetchone()["sver"]
    con.commit(); con.close()
    resp = web.HTTPFound("/")
    resp.set_cookie(SESS_COOKIE, make_session(address, sver), **_cookie_kw())
    resp.del_cookie(LOGIN_COOKIE, path="/")
    return resp

async def api_me(request):
    """GET /api/me — whoami for the UI. Anonymous: {"ok":true,"user":null}. Logged in: address, role
    (DB-backed, so runtime-promoted mods and bans reflect immediately), admin flag, and
    registered/can_post from the cached on-chain check. No auth required; read-only."""
    a = current_user(request)
    if not a:
        return web.json_response({"ok": True, "user": None, "interface": INTERFACE_URL})
    con = db(); role = user_role(con, a); pref = _pref_aliases(con, [a]).get(a); con.close()
    reg = await is_registered(a)
    acc = await get_account(a) or {}
    names = await aliases_of(a)
    return web.json_response({"ok": True, "interface": INTERFACE_URL,
                              "user": {"address": a, "role": role, "admin": is_admin(a),
                                       "alias": pick_alias(names, pref),
                                       "balance": str(acc.get("balance", 0)),   # string: raw units can exceed JS floats
                                       "registered": reg, "can_post": reg and role != "banned"}})

async def api_logout(request):
    """POST /api/logout — bump users.sver (voiding EVERY outstanding session token for the user, not just
    this one) and clear the session cookie. The sver bump needs a valid session + Origin check; the
    cookie is deleted and {"ok":true} returned unconditionally."""
    a = current_user(request)
    if a and origin_ok(request):        # bump the session version -> every outstanding token for this user is void
        con = db(); con.execute("UPDATE users SET sver=sver+1 WHERE address=?", (a,)); con.commit(); con.close()
    resp = web.json_response({"ok": True})
    resp.del_cookie(SESS_COOKIE, path="/")
    return resp

# ---- content routes ------------------------------------------------------------------------------
def _is_mod(request, con):
    """True when the request carries a valid session whose effective role is 'mod'."""
    a = current_user(request)
    return bool(a) and user_role(con, a) == "mod"

async def api_boards(request):
    """GET /api/boards — all boards ordered by position, each with its non-deleted thread count.
    Public, no auth."""
    con = db()
    rows = con.execute("SELECT b.*, (SELECT COUNT(*) FROM threads t WHERE t.board_id=b.id AND t.deleted=0) AS threads "
                       "FROM boards b ORDER BY position").fetchall()
    con.close()
    return web.json_response({"ok": True, "boards": [dict(r) for r in rows]})

async def api_threads(request):
    """GET /api/threads?board=<slug> — the board plus its newest 100 threads (pinned first, then by
    bumped_at desc), each with a non-deleted reply count. Deleted threads are hidden from everyone
    except mods (who see them flagged, for restore). Public; 404 on unknown slug."""
    slug = request.query.get("board", "")
    con = db()
    b = con.execute("SELECT * FROM boards WHERE slug=?", (slug,)).fetchone()
    if not b:
        con.close(); return jerr("no such board", 404)
    mod = _is_mod(request, con)
    rows = con.execute(
        "SELECT t.*, (SELECT COUNT(*) FROM posts p WHERE p.thread_id=t.id AND p.deleted=0) AS replies "
        "FROM threads t WHERE t.board_id=?" + ("" if mod else " AND t.deleted=0") +
        " ORDER BY t.pinned DESC, t.bumped_at DESC LIMIT 100", (b["id"],)).fetchall()
    authors = await authors_meta(con, (r["author"] for r in rows))
    con.close()
    return web.json_response({"ok": True, "board": dict(b), "threads": [dict(r) for r in rows], "authors": authors})

async def api_thread(request):
    """GET /api/thread?id=<int> — one thread with its board and its posts in created order. Deleted
    threads/posts are hidden from everyone except mods (who see them flagged, for restore/review).
    Public; 400 on a non-integer id, 404 on unknown thread."""
    try:
        tid = int(request.query.get("id", "0"))
    except ValueError:
        return jerr("bad id")
    con = db()
    t = con.execute("SELECT * FROM threads WHERE id=?", (tid,)).fetchone()
    mod = _is_mod(request, con)
    if not t or (t["deleted"] and not mod):
        con.close(); return jerr("no such thread", 404)
    posts = con.execute("SELECT * FROM posts WHERE thread_id=?" + ("" if mod else " AND deleted=0") +
                        " ORDER BY created_at", (tid,)).fetchall()
    b = con.execute("SELECT * FROM boards WHERE id=?", (t["board_id"],)).fetchone()
    authors = await authors_meta(con, [t["author"]] + [p["author"] for p in posts])
    con.close()
    return web.json_response({"ok": True, "board": dict(b), "thread": dict(t),
                              "posts": [dict(p) for p in posts], "authors": authors})

def _board_allows(board_row, role):
    """True unless the board is mod-only (post_min_role='mod') and the caller's role isn't 'mod'."""
    return board_row["post_min_role"] != "mod" or role == "mod"

async def api_new_thread(request):
    """POST /api/thread — create a thread + its opening post. JSON body: board (slug), title, body,
    optional pid (governance proposal link). Gated by _gate_post (session + Origin + POST_MIN_GAP per
    author + 20/min per IP + on-chain REGISTERED); mod-only boards reject non-mods. Inputs are trimmed
    and truncated to TITLE_MAX/BODY_MAX/PID_MAX. Returns {"ok":true,"thread_id":id} and records the
    author's post time for the min-gap limiter."""
    a, err = await _gate_post(request)
    if err: return err
    data = await request.json()
    slug = (data.get("board") or "").strip()
    title = (data.get("title") or "").strip()[:TITLE_MAX]
    body = (data.get("body") or "").strip()[:BODY_MAX]
    pid = ((data.get("pid") or "").strip()[:PID_MAX]) or None
    if not title or not body:
        return jerr("title and body are required")
    con = db()
    b = con.execute("SELECT * FROM boards WHERE slug=?", (slug,)).fetchone()
    if not b:
        con.close(); return jerr("no such board", 404)
    if not _board_allows(b, user_role(con, a)):
        con.close(); return jerr("only moderators can post in this board", 403)
    now = int(time.time())
    cur = con.execute("INSERT INTO threads(board_id,author,title,created_at,bumped_at,pid) VALUES(?,?,?,?,?,?)",
                      (b["id"], a, title, now, now, pid))
    tid = cur.lastrowid
    con.execute("INSERT INTO posts(thread_id,author,body_md,created_at) VALUES(?,?,?,?)", (tid, a, body, now))
    touch_user(con, a); con.commit(); con.close()
    _last_post[a] = time.time(); _reap_last_post()
    return web.json_response({"ok": True, "thread_id": tid})

async def api_reply(request):
    """POST /api/reply — append a post to a thread and bump it. JSON body: thread_id (int), body
    (trimmed, BODY_MAX cap). Same _gate_post anti-spam gate as api_new_thread; additionally enforces
    the mod-only-board rule on replies and rejects locked threads for non-mods. Returns {"ok":true}."""
    a, err = await _gate_post(request)
    if err: return err
    data = await request.json()
    try:
        tid = int(data.get("thread_id", 0))
    except (TypeError, ValueError):
        return jerr("bad thread_id")
    body = (data.get("body") or "").strip()[:BODY_MAX]
    if not body:
        return jerr("empty reply")
    con = db()
    t = con.execute("SELECT * FROM threads WHERE id=?", (tid,)).fetchone()
    role = user_role(con, a)
    if not t or (t["deleted"] and role != "mod"):
        con.close(); return jerr("no such thread", 404)
    b = con.execute("SELECT * FROM boards WHERE id=?", (t["board_id"],)).fetchone()
    if b and not _board_allows(b, role):              # mod-only board gate ALSO applies to replies
        con.close(); return jerr("only moderators can post in this board", 403)
    if t["locked"] and role != "mod":
        con.close(); return jerr("thread is locked", 403)
    now = int(time.time())
    con.execute("INSERT INTO posts(thread_id,author,body_md,created_at) VALUES(?,?,?,?)", (tid, a, body, now))
    con.execute("UPDATE threads SET bumped_at=? WHERE id=?", (now, tid))
    touch_user(con, a); con.commit(); con.close()
    _last_post[a] = time.time(); _reap_last_post()
    return web.json_response({"ok": True})


async def api_edit_post(request):
    """POST /api/edit_post — edit the body of YOUR OWN post (a mod may edit any). JSON body:
    {post_id (int), body}. Sets body_md + edited_at; a deleted post can't be edited. No anti-spam gate
    (editing isn't a new post), but a banned user has no valid session. Returns {ok, edited_at, body_md}."""
    a = current_user(request)
    if not a:
        return jerr("not logged in", 401)
    try:
        data = await request.json()
        pid = int(data.get("post_id", 0))
    except (TypeError, ValueError, json.JSONDecodeError):
        return jerr("bad post_id")
    body = (data.get("body") or "").strip()[:BODY_MAX]
    if not body:
        return jerr("empty body")
    con = db()
    p = con.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone()
    if not p or p["deleted"]:
        con.close(); return jerr("no such post", 404)
    role = user_role(con, a)
    if role == "banned":
        con.close(); return jerr("this address is banned", 403)
    if p["author"] != a and role != "mod":
        con.close(); return jerr("you can only edit your own posts", 403)
    now = int(time.time())
    con.execute("UPDATE posts SET body_md=?, edited_at=? WHERE id=?", (body, now, pid))
    touch_user(con, a); con.commit(); con.close()
    return web.json_response({"ok": True, "edited_at": now, "body_md": body})

# thread flag toggles: action -> (column, value). Soft delete/restore included (nothing is ever DROPped).
_THREAD_ACTIONS = {"lock": ("locked", 1), "unlock": ("locked", 0),
                   "pin": ("pinned", 1), "unpin": ("pinned", 0),
                   "delete_thread": ("deleted", 1), "restore_thread": ("deleted", 0)}

async def api_mod(request):
    """POST /api/mod — moderator actions (session role 'mod' + Origin check; 403 otherwise).
    JSON body: {"action": ..., ...}:
      lock/unlock/pin/unpin/delete_thread/restore_thread  {thread_id}   — thread flag toggles (soft)
      move_thread   {thread_id, board}                                  — re-home a thread to a board slug
      delete_post/restore_post  {post_id}                               — soft delete/restore one post
      ban_user/unban_user  {address}      — role='banned'/'user' + sver bump (kills live sessions);
                                            admins can't be banned; banning a fellow MOD needs admin
      add_mod/remove_mod   {address}      — grant/revoke the mod role; ADMIN (FORUM_MODS env) only,
                                            env admins can't be demoted
    Every action targets one row and 404s when the target doesn't exist. Returns {"ok":true}."""
    if not origin_ok(request):
        return jerr("bad origin", 403)
    a = current_user(request)
    con = db()
    if not a or user_role(con, a) != "mod":
        con.close(); return jerr("mods only", 403)
    try:
        data = await request.json()
    except Exception:
        con.close(); return jerr("bad json")
    action = data.get("action")

    try:
        if action in _THREAD_ACTIONS:
            col, val = _THREAD_ACTIONS[action]
            cur = con.execute(f"UPDATE threads SET {col}=? WHERE id=?", (val, int(data.get("thread_id", 0))))
            if cur.rowcount == 0:
                return jerr("no such thread", 404)

        elif action == "move_thread":
            b = con.execute("SELECT id FROM boards WHERE slug=?", ((data.get("board") or "").strip(),)).fetchone()
            if not b:
                return jerr("no such board", 404)
            cur = con.execute("UPDATE threads SET board_id=? WHERE id=?", (b["id"], int(data.get("thread_id", 0))))
            if cur.rowcount == 0:
                return jerr("no such thread", 404)

        elif action in ("delete_post", "restore_post"):
            cur = con.execute("UPDATE posts SET deleted=? WHERE id=?",
                              (1 if action == "delete_post" else 0, int(data.get("post_id", 0))))
            if cur.rowcount == 0:
                return jerr("no such post", 404)

        elif action in ("ban_user", "unban_user", "add_mod", "remove_mod"):
            target = (data.get("address") or "").strip()
            if not validate_address(target):
                return jerr("bad address")
            if is_admin(target):
                return jerr("that address is a bootstrap admin — manage it via FORUM_MODS", 403)
            if action in ("add_mod", "remove_mod") and not is_admin(a):
                return jerr("only bootstrap admins (FORUM_MODS) can grant or revoke the mod role", 403)
            if action == "ban_user" and user_role(con, target) == "mod" and not is_admin(a):
                return jerr("only bootstrap admins can ban a moderator", 403)
            role = {"ban_user": "banned", "unban_user": "user", "add_mod": "mod", "remove_mod": "user"}[action]
            # the target may never have signed in — create the row so the role sticks on first login.
            now = int(time.time())
            con.execute("INSERT OR IGNORE INTO users(address,handle,created_at,last_seen,role,sver) "
                        "VALUES(?,?,?,?, 'user', 0)", (target, target[:10], now, now))
            # sver bump revokes every outstanding session (a ban logs the user out everywhere).
            con.execute("UPDATE users SET role=?, sver=sver+1 WHERE address=?", (role, target))

        else:
            return jerr("unknown action")

        con.commit()
        return web.json_response({"ok": True})
    except (TypeError, ValueError):
        return jerr("bad id")
    finally:
        con.close()

async def api_treasury(request):
    """GET /api/treasury — proxy the node's /treasury_status for the governance board. Public;
    30s process-wide cache, 20/min per IP (over-limit callers get the empty shape rather than an
    error), and node failures serve the last cached value or {"proposals":[]}."""
    if not rate_ok("treas:" + client_ip(request), 20, 60):
        return web.json_response({"proposals": []})
    now = time.time()
    if _treasury_cache["t"] and now - _treasury_cache["t"] < 30:
        return web.json_response(_treasury_cache["v"])
    try:
        async with _http().get(f"{NADO_NODE}/treasury_status", timeout=aiohttp.ClientTimeout(total=6)) as r:
            v = await r.json()
            _treasury_cache.update(t=now, v=v)
            return web.json_response(v)
    except Exception:
        return web.json_response(_treasury_cache["v"] or {"proposals": []})
_treasury_cache = {"t": 0, "v": None}

async def api_set_alias(request):
    """POST /api/set_alias — pick your display name. JSON body: {"alias": name | "-" | ""}.
    "" (or null) clears the preference (auto: first owned alias), "-" forces the plain address,
    a name must be an alias the session address currently owns on-chain (checked fresh — the
    per-address cache is busted first so an alias registered a minute ago works immediately).
    Session + Origin gated, 10/min per IP."""
    if not origin_ok(request):
        return jerr("bad origin", 403)
    a = current_user(request)
    if not a:
        return jerr("sign in first", 401)
    if not rate_ok("setalias:" + client_ip(request), 10, 60):
        return jerr("too many changes — slow down", 429)
    try:
        data = await request.json()
    except Exception:
        return jerr("bad json")
    pref = (data.get("alias") or "").strip().lower()[:64]
    if pref and pref != "-":
        _alias_cache.pop(a, None)               # fresh ownership check, not a 5-min-old snapshot
        names = await aliases_of(a)
        if pref not in names:
            return jerr("that alias is not owned by your address (register it in the wallet's Aliases tab first)")
    con = db()
    touch_user(con, a)                          # ensure the row exists before storing the preference
    con.execute("UPDATE users SET alias=? WHERE address=?", (pref or None, a))
    con.commit(); con.close()
    return web.json_response({"ok": True, "alias": pref or None})

async def api_profile(request):
    """GET /api/profile?address=ndo… — public profile card for any address: on-chain aliases, forum
    role/admin, REGISTERED flag, spendable + bonded balance (raw units, as strings), first/last seen
    (None if the address never signed in) and non-deleted thread/post counts. All chain data comes
    through the same short caches as the rest of the app; 60/min per IP."""
    if not rate_ok("prof:" + client_ip(request), 60, 60):
        return jerr("rate limited — try again shortly", 429)
    addr = (request.query.get("address") or "").strip()
    if not validate_address(addr):
        return jerr("bad address")
    con = db()
    u = con.execute("SELECT created_at,last_seen,alias FROM users WHERE address=?", (addr,)).fetchone()
    role = user_role(con, addr)
    threads = con.execute("SELECT COUNT(*) AS c FROM threads WHERE author=? AND deleted=0", (addr,)).fetchone()["c"]
    posts = con.execute("SELECT COUNT(*) AS c FROM posts WHERE author=? AND deleted=0", (addr,)).fetchone()["c"]
    con.close()
    if current_user(request) == addr:
        _alias_cache.pop(addr, None)   # your own profile reflects a just-registered alias instantly
    acc = await get_account(addr) or {}
    names = await aliases_of(addr)
    return web.json_response({"ok": True, "interface": INTERFACE_URL, "profile": {
        "address": addr, "alias": pick_alias(names, u["alias"] if u else None), "aliases": names,
        "alias_pref": u["alias"] if u else None,
        "role": role, "admin": is_admin(addr),
        "registered": int(acc.get("registered", 0)) == 1,
        "balance": str(acc.get("balance", 0)), "bonded": str(acc.get("bonded", 0)),
        "first_seen": u["created_at"] if u else None, "last_seen": u["last_seen"] if u else None,
        "threads": threads, "posts": posts}})

# ---- static + security headers -------------------------------------------------------------------
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")

@web.middleware
async def sec_headers(request, handler):
    """aiohttp middleware: stamp CSP, X-Frame-Options DENY, nosniff and no-referrer on every response
    (setdefault, so a handler can override)."""
    resp = await handler(request)
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp

async def index(request):
    """GET / — serve the single-page UI (static/index.html)."""
    return web.FileResponse(os.path.join(HERE, "static", "index.html"))

_HTTP = None
async def _on_start(app):
    """Startup hook: create the shared aiohttp ClientSession used for node calls."""
    global _HTTP
    _HTTP = aiohttp.ClientSession()
async def _on_stop(app):
    """Cleanup hook: close the shared client session."""
    if _HTTP: await _HTTP.close()

def build_app():
    """Initialize the DB and assemble the aiohttp Application: sec_headers middleware, HTTP-session
    lifecycle hooks, all API routes, / and /static."""
    init_db()
    app = web.Application(middlewares=[sec_headers])
    app.on_startup.append(_on_start)
    app.on_cleanup.append(_on_stop)
    app.add_routes([
        web.get("/api/sso_start", sso_start),
        web.post("/api/sso_callback", sso_callback),
        web.get("/api/me", api_me),
        web.post("/api/logout", api_logout),
        web.get("/api/boards", api_boards),
        web.get("/api/threads", api_threads),
        web.get("/api/thread", api_thread),
        web.post("/api/thread", api_new_thread),
        web.post("/api/reply", api_reply),
        web.post("/api/edit_post", api_edit_post),
        web.post("/api/mod", api_mod),
        web.get("/api/treasury", api_treasury),
        web.get("/api/profile", api_profile),
        web.post("/api/set_alias", api_set_alias),
        web.get("/", index),
        web.static("/static", os.path.join(HERE, "static")),
    ])
    return app

if __name__ == "__main__":
    web.run_app(build_app(), host="127.0.0.1", port=PORT)
