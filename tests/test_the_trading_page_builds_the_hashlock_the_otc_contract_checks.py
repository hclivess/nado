"""The trading page builds the hashlock the otc contract checks.

A cross-chain swap's NADO side is locked in the otc contract by a hashlock the PAGE computes (static/dex.js otcVmParts)
and the contract recombines in post() and checks in settle(). If the two disagree by a bit, every order posted from
the page is unsettleable and the maker's collateral sits until expiry. So: otcLimbs / otcVmParts are lifted VERBATIM
from dex.js, run under Node with the real nadodapp.js (algHashn) and /protocol.js rendered by the protocol hook, and
compared with execnode.games.otc.vm_hashlock_parts over random secrets:
  1. (generation 28: four 64-bit alghash hashlocks — retired in G9 with BLAKE_EXEC_HEIGHT; the page has no gen-28 form)
  2. generation 29: one 256-bit BLAKE2s hashlock as eight pieces — the VM hash of the secret's five limbs.

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
for name in ("otcLimbs", "otcVmParts"):
    code = lift_const(name)
    T.check(f"dex.js defines {name}", code is not None)
    lift.append(code or "")
lim = re.search(r"\bLIMB_BITS\s*=\s*(\d+)n?\b[^;]*?\bLIMBS\s*=\s*(\d+)", src)

DRIVER = """
import "./protocol_hook.mjs";
const { algHashn } = await import("../static/nadodapp.js");
const LIMB_BITS = %dn, LIMBS = %d;
%s
const out = %s.map((s) => otcVmParts(s));
console.log(JSON.stringify({ parts: out }));
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
    # the shipped /protocol.js: the page has one form since G9 inlined BLAKE_EXEC_HEIGHT (the gen-28 half retired with it)
    g29 = run_node({})
    T.check("2a. node ran the page's code", g29 is not None)
    want29 = [O.vm_hashlock_parts(s) for s in secrets]
    T.check("2b. gen 29: the page's eight pieces equal otc.vm_hashlock_parts (one 256-bit BLAKE2s hashlock)",
            g29 is not None and g29["parts"] == want29)
    # (2c compared against the gen-28 four-digest pieces; that form went with the field VM in G9 slice 3b, so the check
    # is now positive: the eight pieces ARE the VM hash of the five limbs, most significant first)
    from execnode import zkvm2
    T.check("2c. the pieces recombine to the 256-bit VM hash of the secret's five limbs",
            all(sum(p << (32 * (7 - i)) for i, p in enumerate(parts)) == zkvm2.hash_words(O.preimage_limbs(s))
                for s, parts in zip(secrets, want29)))
T.done("ALL PASS — the trading page builds the hashlock the otc contract checks")
