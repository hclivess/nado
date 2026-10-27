"""Records every SUCCESSFUL zkvm2 run made while test scripts execute, for the settlement VM component's tests (G4).

    python3 tests/_vm_record.py OUT.jsonl tests/a.py [tests/b.py ...]

runs each script in THIS process (runpy) with execnode.zkvm2.run wrapped, and writes one JSON line per successful run:
{"method", "code": [[op id, d, s, imm], ...] (the method's instructions), "args", "ctx": [caller, value, cursor, time],
"actx": [asset, self, 0, 0], "io": [[kind, a, b], ...], "gas"} — every value reduced to the 256-bit word as zkvm2.run
reduces it, so the record is exactly the call the VM executed. The scripts are ordinary tests: each isolates its own
HOME and exec paths (tests/_harness.isolate) before it imports the node, so recording them touches nothing live.
"""
import json
import os
import runpy
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from execnode import zkvm2  # noqa: E402  (zkvm2 imports nothing that reaches a database)


def main():
    out = open(sys.argv[1], "w")
    orig = zkvm2.run
    mask = zkvm2.MASK
    seen = {"ok": 0, "revert": 0}

    def run(code, method, caller, args, storage, value=0, cursor=0, timestamp=0, beacons=None, block_hashes=None,
            asset=0, selfd=0, abal=None, witness=False, meter=None):
        m = {} if meter is None else meter
        r = orig(code, method, caller, args, storage, value=value, cursor=cursor, timestamp=timestamp, beacons=beacons,
                 block_hashes=block_hashes, asset=asset, selfd=selfd, abal=abal, witness=witness, meter=m)
        seen["ok" if r[0] else "revert"] += 1
        if r[0]:
            out.write(json.dumps({
                "method": method,
                "code": [[zkvm2.OP[i[0]], i[1], i[2], i[3]] for i in code[method]],
                "args": [int(a) & mask for a in args],
                "ctx": [int(caller) & mask, int(value) & mask, int(cursor) & mask, int(timestamp) & mask],
                "actx": [int(asset) & mask, int(selfd) & mask, 0, 0],
                "io": [list(e) for e in r[3]],
                "gas": m.get("gas"),
            }) + "\n")
        return r

    zkvm2.run = run
    for t in sys.argv[2:]:
        try:
            runpy.run_path(t, run_name="__main__")
        except SystemExit:
            pass
    out.close()
    print("RECORDED", json.dumps(seen))


if __name__ == "__main__":
    main()
