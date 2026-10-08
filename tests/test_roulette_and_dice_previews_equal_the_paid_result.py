"""The roulette and dice pages preview the result the contract will PAY — for beacon seats and legacy seats alike.

Places real bets on dice and roulette on an isolated ExecState (several seats, a beacon epoch each, plus legacy
seats written back to gb == 0 the way the pre-upgrade code left them), settles every one, reads the paid result (gr-1)
back out of storage, and hands those vectors to tests/roulette_and_dice_previews_equal_the_paid_result.mjs, which
evaluates the pages' own preview functions (static/roulette.js spinOf, static/dice.js rollOf) with the real
chainResultAlg and requires an exact match. This is what caught roulette.js salting its preview with the TABLE id
while the contract salts with the SEAT id.

Run: python3 tests/test_roulette_and_dice_previews_equal_the_paid_result.py
"""
import os, tempfile, shutil, atexit
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-roul-dice-preview-")         # assign, never setdefault
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)

import sys, json, random, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from execnode.state import ExecState
from execnode.games import dice, roulette

A, B = "ndoBANK" + "A" * 41, "ndoPLAY" + "B" * 41
TABLE = 3
rng = random.Random(20261008)


def vectors(mod, bet_arg, n_beacon=6, n_legacy=4):
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=os.environ["HOME"]), "s.json")); st.cursor = 1000
    code = mod.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": mod.ABI, "nonce": "n"}, A, "d")
    cid = st.contract_id(A, code, "n")
    st.credit_deposit(A, 10 ** 12); st.credit_deposit(B, 10 ** 12)
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [TABLE], "value": 10 ** 11}, A, "o")
    slots = lambda: st.contracts[cid]["storage"].setdefault("slots", {})     # re-read: a call may replace the dict
    rd = lambda f, k: int(slots().get(str(f * (1 << 32) + k), 0))

    def wr(f, k, v):
        if v:
            slots()[str(f * (1 << 32) + k)] = v
        else:
            slots().pop(str(f * (1 << 32) + k), None)

    seats, beacons, hashes = [], {}, {}
    for i in range(n_beacon + n_legacy):
        g = rng.randrange(1, 10 ** 9)
        st.cursor = 1000 + i * 61                                           # a different beacon epoch per seat
        r = str(st.apply_blob({"op": "call", "contract": cid, "method": "bet", "args": [g, TABLE, bet_arg],
                               "value": 1000}, B, f"b{i}"))
        assert "revert" not in r.lower(), r
        gb, gh = rd(mod.GB, g), rd(mod.GH, g)
        if i >= n_beacon:                                                   # a pre-upgrade seat: gb == 0, gh = cursor+2
            gb, gh = 0, st.cursor + 2
            wr(mod.GB, g, 0); wr(mod.GH, g, gh)
            for h in (gh, gh + 1):
                st.block_hashes[h] = hashes.setdefault(h, rng.getrandbits(256))   # 256-bit: exercises the mod-P reduction
        else:
            st.beacons[gb] = beacons.setdefault(gb, rng.getrandbits(256))
        seats.append((g, gb, gh))
    st.cursor = max(gh for _, _, gh in seats) + 2
    out = []
    for g, gb, gh in seats:
        r = str(st.apply_blob({"op": "call", "contract": cid, "method": "settle", "args": [g]}, B, f"s{g}"))
        assert "revert" not in r.lower(), r
        assert rd(mod.GD, g) == 1
        out.append({"g": g, "gb": gb, "gh": gh, "table": TABLE, "paid": rd(mod.GR, g) - 1})
    return {"seats": out, "beacons": {str(e): format(v, "x") for e, v in beacons.items()},
            "hashes": {str(h): format(v, "x") for h, v in hashes.items()}}


V = {"roulette": vectors(roulette, (1 << 7) | (1 << 17)), "dice": vectors(dice, 50)}
p = subprocess.run(["node", os.path.join(ROOT, "tests", "roulette_and_dice_previews_equal_the_paid_result.mjs")],
                   input=json.dumps(V), capture_output=True, text=True, cwd=ROOT, timeout=120)
print(p.stdout.rstrip())
if p.returncode:
    print(p.stderr.rstrip())
    print("FAIL  the page previews do not equal the paid results")
    sys.exit(1)
print("PASS  roulette and dice previews equal the paid result for beacon and legacy seats")
