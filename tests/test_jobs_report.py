"""/status `jobs` reports exactly what is wrong with this node's declared jobs, and nothing that is not (ops/jobs.py).

Every job the node should run is declared in deploy/units/manifest.json; `problems` must name each one that is missing,
stopped or failing — and must NOT name a unit whose state simply could not be read. Measured 2026-09-27: on two fleet
nodes `systemctl show` returns no properties from the node's own process, and the report listed three working units
(they restart on every update) as "not installed". Pins, with systemctl scripted: loaded+active is fine; not-found is
"not installed"; a stopped unit is named with its state; a failed last run of a timer's service is named; an in-node
loop past STALE_S without success is named; an UNREADABLE unit is listed under `unreadable` and is not a problem; and a
unit outside this node's roles is not judged at all.

Run: python3 tests/test_jobs_report.py
"""
import os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-jobs-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import jobs as J

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


import json
manifest = json.load(open(J.MANIFEST))["jobs"]
node_units = [j["unit"] for j in manifest if j.get("role") == "node"]
check("the manifest declares node-role units", bool(node_units), manifest)

OK = {"load": "loaded", "state": "active", "sub": "running", "result": "success", "enabled": "enabled", "last": None}


def report(states, roles=("node",), inner=None):
    J._show = lambda unit: states.get(unit, OK)
    J.roles = lambda config: set(roles)
    J.inner.clear(); J.inner.update(inner or {})
    J.refresh({})
    return J._cache["value"]


r = report({})
check("every declared unit loaded and active: no problems", r["problems"] == [] and r["unreadable"] == [], r)

u = node_units[0]
r = report({u: dict(OK, load="not-found", state="inactive")})
check("a unit systemd does not know is 'not installed'", f"{u} not installed" in r["problems"], r["problems"])

r = report({u: dict(OK, state="inactive", sub="dead")})
check("a stopped unit is named with its state", f"{u} inactive" in r["problems"], r["problems"])

empty = {"load": None, "state": None, "sub": None, "result": None, "enabled": None, "last": None}
r = report({x: empty for x in node_units})
check("a unit whose state CANNOT BE READ is not reported as a problem", r["problems"] == [], r["problems"])
check("...it is listed as unreadable instead", sorted(r["unreadable"]) == sorted(node_units), r["unreadable"])

timed = [j for j in manifest if j.get("runs")]
if timed:
    j = timed[0]
    r = report({j["runs"]: dict(OK, result="exit-code")}, roles=(j["role"],))
    check("a timer whose service last FAILED is named", f"{j['runs']} last run exit-code" in r["problems"], r["problems"])

old = time.time() - 10 * J.STALE_S
r = report({}, inner={"dex_prices": {"role": "node", "since": old, "last_ok": old}})
check("an in-node loop past STALE_S without success is named",
      any(p.startswith("dex_prices has not succeeded") for p in r["problems"]), r["problems"])

other = [j for j in manifest if j.get("role") not in ("node",)]
if other:
    j = other[0]
    r = report({j["unit"]: dict(OK, load="not-found")}, roles=("node",))
    check("a unit outside this node's roles is not judged", not any(j["unit"] in p for p in r["problems"]), r["problems"])

print("ALL PASS — the jobs report names what is wrong and nothing that is not" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
