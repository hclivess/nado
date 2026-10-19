"""The trading page builds the hashlock the otc contract checks, on generation 28 and on generation 29.

A cross-chain swap's NADO side is locked in the otc contract by a hashlock the PAGE computes (static/dex.js otcVmParts)
and the contract recombines in post() and checks in settle(). If the two disagree by a bit, every order posted from
the page is unsettleable and the maker's collateral sits until expiry. So: otcLimbs / HDOM / otcVmParts are lifted
VERBATIM from dex.js, run under Node with the real nadodapp.js (algHashn, vmV2) and /protocol.js rendered by the
protocol hook, and compared with execnode.games.otc.vm_hashlock_parts over random secrets:
  1. generation 28: the four 64-bit alghash hashlocks as eight halves;
  2. generation 29 (NADO_TEST_PROTOCOL_OVERRIDES: BLAKE_EXEC_HEIGHT = 1): one 256-bit BLAKE2s hashlock as eight
     pieces — and they differ from the gen-28 pieces (the page really switched).

Run: python3 tests/test_the_trading_page_builds_the_hashlock_the_otc_contract_checks.py
"""
import _harness
HOME = _harness.isolate("nado-test-dex-otc-parts-")
import json
import os
import random
import re
import shutil
import subprocess

import protocol as P
from execnode.games import otc as O

T = _harness.Report()
ROOT = _harness.ROOT
rnd = random.Random(7)
secrets = ["%064x" % rnd.getrandbits(256) for _ in range(20)] + ["00" * 32, "ff" * 32]

src = open(os.path.join(ROOT, "static", "dex.js")).read()


def lift_const(name):
    """`const <name> = ...` from dex.js, verbatim: one line if it ends there, else through its closing `};` line"""
    lines = src.split("\n")
    for i, line in enumerate(lines):
        if line.startswith(f"const {name} = "):
            if line.rstrip().endswith(";") and not line.rstrip().endswith("{"):
                return line
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("};"):
                    return "\n".join(lines[i:j + 1])
    return None


lift = []
for name in ("otcLimbs", "HDOM", "otcVmParts"):
    code = lift_const(name)
    T.check(f"dex.js defines {name}", code is not None)
    lift.append(code or "")
lim = re.search(r"\bLIMB_BITS\s*=\s*(\d+)n?\b[^;]*?\bLIMBS\s*=\s*(\d+)", src)

DRIVER = """
import "./protocol_hook.mjs";
const { algHashn, vmV2 } = await import("../static/nadodapp.js");
const LIMB_BITS = %dn, LIMBS = %d;
%s
const out = %s.map((s) => otcVmParts(s));
console.log(JSON.stringify({ v2: vmV2(), parts: out }));
"""


def run_node(overrides):
    js = DRIVER % (int(lim.group(1)) if lim else 52, int(lim.group(2)) if lim else 5, "\n".join(lift), json.dumps(secrets))
    path = os.path.join(ROOT, "tests", "_dex_otc_parts_driver.mjs")
    with open(path, "w") as f:
        f.write(js)
    try:
        env = dict(os.environ, NADO_TEST_PROTOCOL_OVERRIDES=json.dumps(overrides))
        r = subprocess.run(["node", path], capture_output=True, text=True, timeout=300, env=env)
    finally:
        os.remove(path)
    if r.returncode != 0:
        print(r.stderr[-1500:])
        return None
    return json.loads(r.stdout.strip().splitlines()[-1])


if shutil.which("node") is None:
    print("SKIP  node not installed: the page cannot be run here")
else:
    g28 = run_node({})
    T.check("1a. node ran the page's code as generation 28", g28 is not None and g28["v2"] is False, g28 and g28.get("v2"))
    want28 = [O.vm_hashlock_parts(s, "v1") for s in secrets]
    T.check("1b. gen 28: the page's eight halves equal otc.vm_hashlock_parts (four alghash hashlocks)",
            g28 is not None and g28["parts"] == want28)
    g29 = run_node({"BLAKE_EXEC_HEIGHT": 1})
    T.check("2a. node ran the page's code as generation 29", g29 is not None and g29["v2"] is True, g29 and g29.get("v2"))
    P.BLAKE_EXEC_HEIGHT = 1
    try:
        want29 = [O.vm_hashlock_parts(s) for s in secrets]
    finally:
        P.BLAKE_EXEC_HEIGHT = 1 << 62
    T.check("2b. gen 29: the page's eight pieces equal otc.vm_hashlock_parts (one 256-bit BLAKE2s hashlock)",
            g29 is not None and g29["parts"] == want29)
    T.check("2c. the gen-29 pieces differ from the gen-28 ones (the page really switched)", want29 != want28)
T.done("ALL PASS — the trading page builds the hashlock the otc contract checks, on both generations")
