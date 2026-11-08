"""A player or agent signed in to Land stays signed in when the world server restarts.

Sessions lived only in the server's memory, so every restart (every Land deploy) signed everyone out mid-game — found
2026-11-08 walking the live page as the town agent: after a deploy the page said "Sign in to build". They are kept in
sessions.json under the token's hash:
  1. a session made before a restart answers after it (a new World on the same data directory);
  2. the file never holds the token itself — reading it signs nobody in;
  3. signing out ends the session for good, across a restart too; an expired one is not loaded.
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-session-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import importlib.util, json, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from signatures import generate_keydict, sign, unhex     # noqa: E402 — pure crypto
from hashing import blake2b_hash                         # noqa: E402

spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    fails += 0 if cond else 1


class Req:                                                # just what World.who reads
    def __init__(self, token):
        self.cookies, self.headers, self.query = {}, {"Authorization": "Bearer " + token}, {}


data = tempfile.mkdtemp(prefix="nado_land_sess_", dir=os.environ["HOME"])
kd = generate_keydict()


def login(world):
    nonce, issued = world.challenge(S.AGENT_ORIGIN)
    msg = blake2b_hash([S.DOMAIN, S.AGENT_ORIGIN, kd["address"], nonce, issued], 32)
    return world.login(kd["address"], kd["public_key"], kd.get("alg"), sign(kd["private_key"], unhex(msg), alg=kd.get("alg")), nonce, S.AGENT_ORIGIN)


w1 = S.World(data, "http://127.0.0.1:1", "e" * 32)
tok = login(w1)
check("signed in", w1.who(Req(tok)) == kd["address"])
w2 = S.World(data, "http://127.0.0.1:1", "e" * 32)               # the restart
check("1. the session answers after a restart", w2.who(Req(tok)) == kd["address"])
raw = open(os.path.join(data, "sessions.json")).read()
check("2. sessions.json never holds the token itself", tok not in raw and S.sid(tok) in raw, raw[:200])
check("…a stored name is not a token: presenting it signs nobody in", w2.who(Req(S.sid(tok))) is None)
w2.end_session(tok)
check("3. signed out, the session is gone", w2.who(Req(tok)) is None)
check("…and stays gone across a restart", S.World(data, "http://127.0.0.1:1", "e" * 32).who(Req(tok)) is None)
tok2 = login(w2)
store = json.load(open(os.path.join(data, "sessions.json")))
store[S.sid(tok2)]["until"] = time.time() - 1
with open(os.path.join(data, "sessions.json"), "w") as f:
    json.dump(store, f)
check("…an expired session is not loaded", S.sid(tok2) not in S.World(data, "http://127.0.0.1:1", "e" * 32).sessions)

print("ALL PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
