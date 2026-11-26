"""EVERY ACTOR MANIFEST IS VALID AND PINS ITS CODE — the NADO actor standard (doc/actors.md), held to.

Operator 2026-11-26: "i kinda like the idea of Actirs that apify has … do the manifest and standardisation". An actor is an
off-chain program that acts on NADO as its own identity, described by actors/<id>/actor.json against actors/schema.json;
tools/actor.py validates it and builds the standard command line. Pinned:
  1. every manifest in actors/ is valid — its shape (read from the published schema), its code's hash, and the flags,
     variables and commands it promises being in that code;
  2. each rule bites: a manifest that breaks one is refused, for that reason (the key rule — an actor anyone may run never
     uses a node wallet —, a stale hash, a flag the code does not take, a default of the wrong type, a dry-run actor with
     no arm, a transacting command that names nothing it transacts with, a directory that is not its id);
  3. the standard invocation: global inputs before the command (argparse's top-level options), the command's after it, a
     true boolean as its bare flag, a false one left out; a missing required input, an unknown input or command refused;
  4. the three actors the node already runs are described (otc-watchtower, land-agent, otc-market-maker), the operator's
     own job marked so;
  5. otc_mm.py names its commands — an unknown one is refused before a key loads, where it used to start the daemon.

Run: python3 tests/test_every_actor_manifest_is_valid_and_pins_its_code.py
"""
import _harness
HOME = _harness.isolate("nado-test-actors-", exec_state=False)
import copy, glob, json, os, subprocess, sys, tempfile

T = _harness.Report()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import actor as A   # noqa: E402

# 1
manifests = sorted(glob.glob(os.path.join(ROOT, "actors", "*", "actor.json")))
T.check("there are actors to hold to the standard", len(manifests) >= 3, manifests)
for p in manifests:
    errs = A.validate(p)
    T.check(f"{os.path.relpath(p, ROOT)} is a valid actor", not errs, errs)
T.check("the validator reads the PUBLISHED schema (actors/schema.json), not a copy", A.SCHEMA_PATH == os.path.join(ROOT, "actors", "schema.json")
        and json.load(open(A.SCHEMA_PATH))["properties"]["manifest"]["const"] == "nado-actor/1")

# 2 — each rule bites, on a copy of a real manifest in a scratch actors/<id>/ (its entry still the repository's)
base = json.load(open(os.path.join(ROOT, "actors", "otc-watchtower", "actor.json")))


def refused(mut, why, dirname=None):
    m = copy.deepcopy(base)
    mut(m)
    d = os.path.join(tempfile.mkdtemp(dir=HOME), dirname or m["id"])
    os.makedirs(d)
    p = os.path.join(d, "actor.json")
    json.dump(m, open(p, "w"))
    errs = A.validate(p)
    return bool(errs) and any(why in e for e in errs), errs


def setp(path, value):
    def f(m):
        node = m
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = value
    return f


cases = [
    ("the key rule: an actor anyone may run never uses a node wallet", setp(["identity", "kind"], "node-wallet"), "never uses a node wallet"),
    ("a changed entry is a new version: a stale hash is refused", setp(["source", "sha256"], "0" * 64), "SHA-256"),
    ("a flag the code does not take is refused", setp(["commands", "scan", "inputs", "submit", "cli"], "--post-everything"), "not in scripts/otc_watchtower.py"),
    ("a default of the wrong type is refused", setp(["commands", "scan", "inputs", "loop", "default"], "sixty"), "is not a integer"),
    ("a dry-run actor must name what arms it", setp(["safety", "arm"], "nothing"), "names no input"),
    ("a transacting command names what it transacts with", setp(["commands", "scan", "effects"], {"transactions": True, "spends": "fees"}), "names no contract"),
    ("a transacting actor declares safety", lambda m: m.pop("safety"), "declares `safety`"),
    ("an unknown field is refused (the schema's additionalProperties)", setp(["colour"], "blue"), "unknown field 'colour'"),
    ("an input reaches the code exactly one way (cli or env)", setp(["commands", "scan", "inputs", "loop", "env"], "TOWER_LOOP"), "exactly one"),
    ("a command the code does not have is refused", lambda m: m["commands"].__setitem__("launch", copy.deepcopy(m["commands"]["scan"])), "command 'launch' is not in"),
]
for name, mut, why in cases:
    ok, errs = refused(mut, why)
    T.check(name, ok, errs)
ok, errs = refused(lambda m: None, "its id", dirname="not-the-id")
T.check("the manifest's directory is its id", ok, errs)

# 3 — the standard invocation
la = json.load(open(os.path.join(ROOT, "actors", "land-agent", "actor.json")))
argv, env = A.command_line(la, "build", {"server": "https://s", "keys": "k.json", "plot": "5", "file": "h.json"})
T.check("global inputs before the command, the command's after it", argv == ["python3", "scripts/land_agent.py", "--server", "https://s", "--keys", "k.json", "build", "--plot", "5", "--file", "h.json"], argv)
wt = json.load(open(os.path.join(ROOT, "actors", "otc-watchtower", "actor.json")))
T.check("a true boolean is its bare flag, a false one is left out", A.command_line(wt, "scan", {"submit": "true", "loop": "60"})[0][2:] == ["scan", "--submit", "--loop", "60"]
        and A.command_line(wt, "scan", {"submit": "false"})[0][2:] == ["scan"])


def raises(f):
    try:
        f()
    except ValueError as e:
        return str(e)
    return None


T.check("a missing required input is refused", "is required" in (raises(lambda: A.command_line(la, "build", {"plot": "5"})) or ""))
T.check("an unknown input is refused", "unknown input" in (raises(lambda: A.command_line(wt, "scan", {"bogus": "1"})) or ""))
T.check("an unknown command is refused", "no command" in (raises(lambda: A.command_line(wt, "launch", {})) or ""))
T.check("a value of the wrong type is refused", raises(lambda: A.command_line(wt, "scan", {"loop": "soon"})) is not None)
# and run for real, the safe command: the land agent makes its OWN key (never a person's), private to its owner
out = os.path.join(HOME, "agent.json")
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "actor.py"), "run", os.path.join(ROOT, "actors", "land-agent", "actor.json"), "newkey", f"out={out}"],
                   capture_output=True, text=True, timeout=120, env=dict(os.environ, HOME=HOME))
T.check("the standard invocation runs an actor: land-agent newkey writes the agent's own key, readable by its owner alone",
        r.returncode == 0 and os.path.exists(out) and (os.stat(out).st_mode & 0o777) == 0o600, (r.returncode, r.stderr[-300:]))

# 4
ids = {json.load(open(p))["id"]: json.load(open(p)) for p in manifests}
T.check("the node's three actors are described", {"otc-watchtower", "land-agent", "otc-market-maker"} <= set(ids), sorted(ids))
T.check("…the market maker is the operator's own job (node wallet), the others anyone's (own key)",
        ids["otc-market-maker"]["audience"] == "operator" and ids["otc-market-maker"]["identity"]["kind"] == "node-wallet"
        and all(ids[k]["audience"] == "anyone" and ids[k]["identity"]["kind"] == "own-key" for k in ("otc-watchtower", "land-agent")))

# 5
r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "otc_mm.py"), "wtach"], capture_output=True, text=True, timeout=60,
                   env=dict(os.environ, HOME=HOME))
T.check("otc_mm.py refuses an unknown command before any key loads (a typo used to start the daemon)",
        r.returncode != 0 and "usage: otc_mm.py post | watch | cancel" in r.stderr, (r.returncode, r.stderr[-200:]))
T.done("ALL PASS — every actor manifest is valid and pins its code")
