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
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=4000")
    return con

def init_db():
    con = db()
    con.executescript(SCHEMA)
    try: con.execute("ALTER TABLE users ADD COLUMN sver INTEGER DEFAULT 0")   # migrate older DBs
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
def _b64(b): return base64.urlsafe_b64encode(b).decode().rstrip("=")
def _unb64(s): return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

def make_session(address, sver):
    payload = json.dumps({"a": address, "v": int(sver), "e": int(time.time()) + SESSION_TTL}, separators=(",", ":")).encode()
    sig = hmac.new(SECRET, payload, hashlib.sha256).digest()
    return _b64(payload) + "." + _b64(sig)

def _read_token(token):
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
    return dict(max_age=SESSION_TTL, httponly=True, secure=COOKIE_SECURE, samesite="Lax", path="/")

# ---- login challenges (in-memory, short-lived, hard-capped) ---------------------------------------
_challenges = {}     # request_id -> {nonce, issued}

def _reap_challenges():
    now = time.time()
    for rid in [k for k, v in _challenges.items() if now - v["issued"] > CHALLENGE_TTL]:
        _challenges.pop(rid, None)

def challenge_message(address, nonce, issued):
    return blake2b_hash(["nado-forum-login", FORUM_ORIGIN, address, nonce, int(issued)])

# ---- on-chain "registered" gate (shared session + short cache) ------------------------------------
_reg_cache = {}      # address -> (ts, bool)
def _http():
    global _HTTP
    return _HTTP

async def is_registered(address):
    if not REQUIRE_REG:
        return True
    hit = _reg_cache.get(address)
    if hit and time.time() - hit[0] < REG_CACHE_TTL:
        return hit[1]
    ok = False
    try:
        async with _http().get(f"{NADO_NODE}/get_account?address={address}",
                               timeout=aiohttp.ClientTimeout(total=6)) as r:
            if r.status == 200:
                acc = await r.json()
                ok = int(acc.get("registered", 0)) == 1
    except Exception:
        ok = False       # fail closed
    _reg_cache[address] = (time.time(), ok)
    return ok

# ---- helpers -------------------------------------------------------------------------------------
def role_of(address): return "mod" if address in MODS else "user"

def touch_user(con, address, public_key=None):
    now = int(time.time())
    if con.execute("SELECT address FROM users WHERE address=?", (address,)).fetchone():
        con.execute("UPDATE users SET last_seen=?, public_key=COALESCE(?,public_key), role=? WHERE address=?",
                    (now, public_key, role_of(address), address))
    else:
        con.execute("INSERT INTO users(address,public_key,handle,created_at,last_seen,role,sver) VALUES(?,?,?,?,?,?,0)",
                    (address, public_key, address[:10], now, now, role_of(address)))

def jerr(msg, status=400): return web.json_response({"ok": False, "error": msg}, status=status)

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
    if not await is_registered(a):
        return None, jerr("posting requires a REGISTERED NADO address (do the one-time registration in the wallet)", 403)
    return a, None

_last_post = {}
def _reap_last_post():
    if len(_last_post) > 50000:
        now = time.time()
        for k in [k for k, t in _last_post.items() if now - t > 3600]:
            _last_post.pop(k, None)

# ---- SSO auth routes -----------------------------------------------------------------------------
async def sso_start(request):
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
    a = current_user(request)
    if not a:
        return web.json_response({"ok": True, "user": None})
    reg = await is_registered(a)
    return web.json_response({"ok": True, "user": {"address": a, "role": role_of(a), "registered": reg, "can_post": reg}})

async def api_logout(request):
    a = current_user(request)
    if a and origin_ok(request):        # bump the session version -> every outstanding token for this user is void
        con = db(); con.execute("UPDATE users SET sver=sver+1 WHERE address=?", (a,)); con.commit(); con.close()
    resp = web.json_response({"ok": True})
    resp.del_cookie(SESS_COOKIE, path="/")
    return resp

# ---- content routes ------------------------------------------------------------------------------
async def api_boards(request):
    con = db()
    rows = con.execute("SELECT b.*, (SELECT COUNT(*) FROM threads t WHERE t.board_id=b.id) AS threads FROM boards b ORDER BY position").fetchall()
    con.close()
    return web.json_response({"ok": True, "boards": [dict(r) for r in rows]})

async def api_threads(request):
    slug = request.query.get("board", "")
    con = db()
    b = con.execute("SELECT * FROM boards WHERE slug=?", (slug,)).fetchone()
    if not b:
        con.close(); return jerr("no such board", 404)
    rows = con.execute(
        "SELECT t.*, (SELECT COUNT(*) FROM posts p WHERE p.thread_id=t.id AND p.deleted=0) AS replies "
        "FROM threads t WHERE t.board_id=? ORDER BY t.pinned DESC, t.bumped_at DESC LIMIT 100", (b["id"],)).fetchall()
    con.close()
    return web.json_response({"ok": True, "board": dict(b), "threads": [dict(r) for r in rows]})

async def api_thread(request):
    try:
        tid = int(request.query.get("id", "0"))
    except ValueError:
        return jerr("bad id")
    con = db()
    t = con.execute("SELECT * FROM threads WHERE id=?", (tid,)).fetchone()
    if not t:
        con.close(); return jerr("no such thread", 404)
    posts = con.execute("SELECT * FROM posts WHERE thread_id=? AND deleted=0 ORDER BY created_at", (tid,)).fetchall()
    b = con.execute("SELECT * FROM boards WHERE id=?", (t["board_id"],)).fetchone()
    con.close()
    return web.json_response({"ok": True, "board": dict(b), "thread": dict(t), "posts": [dict(p) for p in posts]})

def _board_allows(board_row, address):
    return board_row["post_min_role"] != "mod" or role_of(address) == "mod"

async def api_new_thread(request):
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
    if not _board_allows(b, a):
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
    if not t:
        con.close(); return jerr("no such thread", 404)
    b = con.execute("SELECT * FROM boards WHERE id=?", (t["board_id"],)).fetchone()
    if b and not _board_allows(b, a):                 # mod-only board gate ALSO applies to replies
        con.close(); return jerr("only moderators can post in this board", 403)
    if t["locked"] and role_of(a) != "mod":
        con.close(); return jerr("thread is locked", 403)
    now = int(time.time())
    con.execute("INSERT INTO posts(thread_id,author,body_md,created_at) VALUES(?,?,?,?)", (tid, a, body, now))
    con.execute("UPDATE threads SET bumped_at=? WHERE id=?", (now, tid))
    touch_user(con, a); con.commit(); con.close()
    _last_post[a] = time.time(); _reap_last_post()
    return web.json_response({"ok": True})

async def api_mod(request):
    if not origin_ok(request):
        return jerr("bad origin", 403)
    a = current_user(request)
    if not a or role_of(a) != "mod":
        return jerr("mods only", 403)
    data = await request.json()
    action = data.get("action"); tid = data.get("thread_id"); pid = data.get("post_id")
    con = db()
    if action == "lock":   con.execute("UPDATE threads SET locked=1 WHERE id=?", (tid,))
    elif action == "unlock": con.execute("UPDATE threads SET locked=0 WHERE id=?", (tid,))
    elif action == "pin":  con.execute("UPDATE threads SET pinned=1 WHERE id=?", (tid,))
    elif action == "unpin": con.execute("UPDATE threads SET pinned=0 WHERE id=?", (tid,))
    elif action == "delete_post": con.execute("UPDATE posts SET deleted=1 WHERE id=?", (pid,))
    else:
        con.close(); return jerr("unknown action")
    con.commit(); con.close()
    return web.json_response({"ok": True})

async def api_treasury(request):
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

# ---- static + security headers -------------------------------------------------------------------
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")

@web.middleware
async def sec_headers(request, handler):
    resp = await handler(request)
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp

async def index(request):
    return web.FileResponse(os.path.join(HERE, "static", "index.html"))

_HTTP = None
async def _on_start(app):
    global _HTTP
    _HTTP = aiohttp.ClientSession()
async def _on_stop(app):
    if _HTTP: await _HTTP.close()

def build_app():
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
        web.post("/api/mod", api_mod),
        web.get("/api/treasury", api_treasury),
        web.get("/", index),
        web.static("/static", os.path.join(HERE, "static")),
    ])
    return app

if __name__ == "__main__":
    web.run_app(build_app(), host="127.0.0.1", port=PORT)
