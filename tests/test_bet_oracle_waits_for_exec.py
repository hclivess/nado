"""The bet oracle rides out an exec node restarting for an update (scripts/bet_oracle.py _wait_for_exec).

MEASURED 2026-09-27 23:39: the oracle's timer fired while nado-exec restarted for the update to 7709680c; the contract
lookup got "Connection refused", the run failed, and /status jobs.problems showed "nado-bet-oracle.service last run
exit-code" — the fleet watch flags that as an anomaly after every deploy the timer happens to overlap.

Pins: an exec node that refuses twice then answers is waited for and the contract is found; one that never answers
still fails, naming the exec node as down (never a silent no-op).
Run: python3 tests/test_bet_oracle_waits_for_exec.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-betwait-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts")); sys.path.insert(0, ROOT)
import bet_oracle as B
import time
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


time.sleep = lambda s: None
state = {"refusals": 2}
CID = "ab" * 16


def fake_get(url, timeout=15):
    if state["refusals"] > 0:
        state["refusals"] -= 1
        raise ConnectionRefusedError("[Errno 111] Connection refused")
    if "/exec/contract?" in url:
        return {"methods": sorted(B.BET_METHODS)}
    return {"cursor": 1}


B._get = fake_get
B._cid_from_client = lambda: CID
cid, src = B.resolve_cid("http://127.0.0.1:1")
check("an exec node restarting (refused twice, then up) is waited for and the contract is found", cid == CID, (cid, src))

state["refusals"] = 10 ** 9
B.EXEC_WAIT_S = 0
try:
    B.resolve_cid("http://127.0.0.1:1")
    check("an exec node that stays down still fails", False)
except SystemExit as e:
    check("an exec node that stays down still fails, naming it as down", "did not answer" in str(e), str(e))

print("ALL PASS — the oracle rides out an exec restart" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
