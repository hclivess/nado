"""
_hexholm_daily_e2e.py — LIVE end-to-end of the Hexholm PROVABLE DAILY ISLAND on the running chain:
  1. drives the on-chain day anchor (_lib.daily_anchor): pin -> resolve -> av[day] readable
  2. plays a full honest daily run headlessly (tests/hexholm_daily_play.mjs) with THIS node's address
  3. posts the claim (day, score, n, 150 packed words) via a signed blob tx
  4. waits for the entry to land and runs the faucet distributor's oracle
     (tests/hexholm_daily_verify.mjs) — the run must rank, with the exact score
Run: HOME=/root ./nado_venv/bin/python _hexholm_daily_e2e.py
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ops.key_ops import load_keys

CID = "c532e36ac30f61619e9ac989a1c0994e"
EX = os.environ.get("NADO_EXEC_URL", "http://127.0.0.1:9273").rstrip("/")
PY = sys.executable


def j(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read().decode())


def sto():
    return j(f"{EX}/exec/contract?ns=default&cid={CID}&provisional=1").get("storage", {})


def call(method, args):
    out = subprocess.run([PY, "execnode/submit_blob.py", "call", CID, method, json.dumps(args)],
                         capture_output=True, text=True, timeout=60)
    print(f"  submit {method}: {out.stdout.strip().splitlines()[0] if out.stdout else out.stderr.strip()[:200]}")
    if out.returncode != 0:
        sys.exit(f"submit {method} failed:\n{out.stdout}\n{out.stderr}")


def wait_for(what, fn, tries=30, pause=4):
    for _ in range(tries):
        v = fn()
        if v:
            return v
        time.sleep(pause)
    sys.exit(f"TIMEOUT waiting for {what}")


addr = load_keys()["address"]
day = int(time.time()) // 86400
print(f"daily E2E · addr {addr} · day {day} · cid {CID}")

# 1 ---- the anchor: pin, then resolve (both are the same permissionless call) -----------------------
av = (sto().get("av") or {}).get(str(day))
if not av:
    if not (sto().get("ah") or {}).get(str(day)):
        call("anchor", [day])
        wait_for("anchor pin (ah)", lambda: (sto().get("ah") or {}).get(str(day)))
        print(f"  pinned at height {(sto().get('ah') or {}).get(str(day))}")
    call("anchor", [day])
    av = wait_for("anchor value (av)", lambda: (sto().get("av") or {}).get(str(day)))
print(f"  anchor av[{day}] = {av}")

# 2 ---- play the run headlessly ---------------------------------------------------------------------
out = subprocess.run(["node", "tests/hexholm_daily_play.mjs", str(day), str(av), addr],
                     capture_output=True, text=True, timeout=300)
if out.returncode != 0:
    sys.exit(f"play failed:\n{out.stderr}")
claim = json.loads(out.stdout.strip())
assert claim["ok"], f"local verifyClaim round-trip failed: {claim}"
print(f"  played: {claim['vp']} victory points in {claim['n']} moves -> score {claim['score']} (self-verified)")

# 3 ---- post the claim ------------------------------------------------------------------------------
already = any(a == addr and (sto().get("eday") or {}).get(e) == day
              for e, a in (sto().get("eaddr") or {}).items())
call("post", [day, claim["score"], claim["n"]] + claim["words"])
wait_for("posted entry", lambda: any(
    (sto().get("eday") or {}).get(e) == day and a == addr and (sto().get("escore") or {}).get(e) == claim["score"]
    for e, a in (sto().get("eaddr") or {}).items()))
print("  entry landed on-chain")

# 4 ---- the distributor's oracle must rank it -------------------------------------------------------
out = subprocess.run(["node", "tests/hexholm_daily_verify.mjs", CID, str(day)],
                     capture_output=True, text=True, timeout=600)
if out.returncode != 0:
    sys.exit(f"verify oracle failed:\n{out.stderr}")
rows = json.loads(out.stdout.strip())
mine = [r for r in rows if r[0] == addr]
assert mine and mine[0][1] == claim["score"], f"oracle rows {rows} lack our verified score {claim['score']}"
print(f"  oracle verified + ranked: {mine[0]}  (of {len(rows)} row(s))")
print("DAILY E2E: ALL PASS")
