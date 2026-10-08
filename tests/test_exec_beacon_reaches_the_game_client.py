"""A finalized exec beacon reaches the game client and yields the outcome the contract pays.

  * GET /exec/beacon?epochs= (execnode.h_beacon, called through aiohttp) returns {cursor, beacons: {epoch: hex|null}}
    from the FINALIZED state: a known epoch as the unreduced hex, an unknown one as null, junk ignored;
  * the shipped client (NadoDapp.beacons / bc) requests exactly the epochs it lacks, caches what came back and
    never re-requests a cached epoch; bc() of a missing epoch stays undefined;
  * BankedGame.prefetchBeacons asks only for live seats of the active table whose beacon epoch has begun;
  * chainResultAlg(bc(gb), "0", seat, 100) equals a dice seat bound to that epoch settled in the contract.

Run: python3 tests/test_exec_beacon_reaches_the_game_client.py
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-beacon-client-")    # never the live database (assign, not setdefault)
import atexit; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from aiohttp.test_utils import make_mocked_request                     # noqa: E402
from execnode import execnode as EN                                    # noqa: E402
from execnode.state import ExecState                                   # noqa: E402
from execnode.games import dice                                        # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


B5 = (1 << 255) + 987654321          # above the field: the endpoint serves it unreduced, the client reduces
B6 = 123456789
st = ExecState(os.path.join(os.environ["HOME"], "s.json"))
st.cursor = 6 * 60 + 3
st.beacons = {5: B5, 6: B6}
EN.states["default"] = st

resp = asyncio.run(EN.h_beacon(make_mocked_request("GET", "/exec/beacon?ns=default&epochs=5,6,7,x,-1")))
body = json.loads(resp.body)
check("/exec/beacon serves the cursor", body.get("cursor") == st.cursor, body)
check("a known epoch is its unreduced hex", body["beacons"].get("5") == format(B5, "x"), body)
check("an epoch not final here is null", body["beacons"].get("7", "missing") is None, body)
check("junk is ignored", "x" not in body["beacons"], body)
r404 = asyncio.run(EN.h_beacon(make_mocked_request("GET", "/exec/beacon?ns=nope&epochs=5")))
check("an unknown namespace is a 404", r404.status == 404, r404.status)

if not shutil.which("node"):
    print("SKIP  node not installed: client half not run")
else:
    out = subprocess.run(["node", os.path.join(ROOT, "tests", "beacon_client_cache.mjs"), json.dumps(body)],
                         cwd=ROOT, capture_output=True, text=True, timeout=300)
    try:
        js = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        js = None
    check("the client ran", js is not None, (out.stdout + out.stderr)[-600:])
    if js:
        check("the client asks /exec/beacon once, for exactly the epochs it lacks (0 and duplicates dropped)",
              len(js["urls"]) == 1 and js["urls"][0].endswith("/exec/beacon?ns=default&epochs=5,6,7"), js["urls"])
        check("a cached epoch is never requested again", js["afterCache"] == 1, js["afterCache"])
        check("bc() returns the cached beacons; a null epoch stays uncached",
              js["bc5"] == format(B5, "x") and js["bc6"] == format(B6, "x") and js["bc7"] is None, js)
        check("prefetchBeacons asks only for live, begun seats of the active table", js["asked"] == [5, 6], js["asked"])

        # the contract: a dice seat (id 10) bound to epoch 5 settles to the client's roll
        st2 = ExecState(os.path.join(os.environ["HOME"], "s2.json"))
        st2.cursor = 3 * 60 + 7                     # epoch 3 -> gb = 5
        for a in ("ndoBANK", "ndoPLAYER"):
            st2.credit_deposit(a, 10 ** 13)
        code = dice.build()
        st2.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": dice.ABI, "nonce": "n"}, "ndoBANK", "d")
        cid = st2.contract_id("ndoBANK", code, "n")
        st2.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [1], "value": 10 ** 12}, "ndoBANK", "o")
        st2.apply_blob({"op": "call", "contract": cid, "method": "bet", "args": [10, 1, 50], "value": 10 ** 9},
                       "ndoPLAYER", "b")
        st2.beacons[5] = B5
        st2.cursor = 5 * 60
        st2.apply_blob({"op": "call", "contract": cid, "method": "settle", "args": [10]}, "ndoBANK", "s")
        slots = st2.contracts[cid]["storage"].get("slots") or {}
        gr = int(slots.get(str(dice.GR * (1 << 32) + 10), 0))
        check("the seat bound to epoch 5 settled", gr > 0, gr)
        check("the client's roll from bc(5) equals the contract's", gr - 1 == js["roll"], (gr - 1, js["roll"]))

print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILURES")
sys.exit(1 if FAILED else 0)
