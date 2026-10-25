"""A pet page on generation 29 previews the combine the contract will actually roll (G6; doc/stwo/g5-carry.md 2c).

combine() grants the kept pet +1 to stat i = lo32(H(gn_keep + gn_consume + 888888)) % 10. On gen 29 the gene gn is a
256-bit word and the view's gl/gh are only its low 64 bits, so a page that rebuilt the gene from the halves previewed
a roll of the wrong number — the user was promised one stat and the chain raised another. The view now exposes gn
(execnode/games/pets.py _view "gn") and static/pets.js reads it whenever it is there.

Drives the REAL v2 pets contract on a gen-29 exec state (protocol.BLAKE_EXEC_HEIGHT = 1): mints and hatches until two
pets share a species, decodes the view exactly as the exec node serves it (ExecState.decode_view), reads each gene with
static/pets.js's own lines and previews with static/pets-genes.js combineStatOf under the same generation, then
combines on chain. Pins: the preview is the stat the contract raised; the halves alone would not have given the gene.

Run: python3 tests/test_a_gen29_pet_previews_the_combine_the_contract_rolls.py
"""
import _harness
HOME = _harness.isolate("nado-test-pets-combine-g29-")
import json
import os
import re
import shutil
import subprocess
import time

import protocol as PR
PR.BLAKE_EXEC_HEIGHT = 1                       # gen 29: the exec layer is BLAKE2s, the VM is v2, from genesis
from execnode.state import ExecState
from execnode.games import pets as P

T = _harness.Report()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OWN = "ndoPETSOWNER"

st = ExecState(os.path.join(HOME, "g29.json"))
st.cursor, st.block_ts = 3000, int(time.time())
st.block_hashes = {h: ((h * 0x9E3779B97F4A7C15) ^ (h << 200)) % (1 << 256) for h in range(0, 9000)}   # 256-bit hashes
st.credit_deposit(OWN, 10**15)
code = P.build("v2")
st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": P.ABI, "nonce": "p"}, OWN, "dp")
pc = st.contract_id(OWN, code, "p")
slot = lambda f, k: int((st.contracts[pc]["storage"].get("slots") or {}).get(str((f << 32) + k), 0))


def call(method, args, value=None):
    p = {"op": "call", "contract": pc, "method": method, "args": args}
    if value:
        p["value"] = value
    return st.apply_blob(p, OWN, f"{method}{args}{st.cursor}")


seen, pair = {}, None
for pid in range(1000, 1400):
    call("mint", [pid], P.MINT_FEE)
    st.cursor += 3
    call("hatch", [pid])
    if not slot(P.GN, pid):
        continue
    sp = slot(P.SP, pid)
    key = (sp, slot(P._rt(777), pid) % P.TIER_COUNT[sp])
    if key in seen:
        pair = (seen[key], pid)
        break
    seen[key] = pid
T.check("setup: two hatched pets of one species on gen 29", pair is not None, len(seen))
keep, consume = pair
gk, gc = slot(P.GN, keep), slot(P.GN, consume)
T.check("setup: their genes are 256-bit words (gl/gh hold only the low 64 bits)", gk >= (1 << 64) and gc >= (1 << 64), (gk, gc))
st.cursor = max(st.cursor, slot(P.EX, keep), slot(P.EX, consume)) + 1

view = st.decode_view(st.contracts[pc])
T.check("the view serves the whole gene (gn)", str(view.get("gn", {}).get(str(keep))) == str(gk), view.get("gn", {}).get(str(keep)))

# static/pets.js's own gene read (petsFrom), and pets-genes.js's preview, under the same generation
src = open(os.path.join(ROOT, "static", "pets.js"), encoding="utf-8").read()
m = re.search(r'    const gl = _m\(sto, "gl"\)\[pid\].*?\.toString\(\) : null;', src, re.S)
T.check("static/pets.js reads the gene from the view (the lines are found)", m is not None)
js = """
const _el = new Proxy(function () {}, { get: (t, k) => k === Symbol.toPrimitive ? () => "" : _el, apply: () => _el });
for (const k of ["document", "window", "localStorage", "sessionStorage", "location", "history"]) if (!(k in globalThis)) globalThis[k] = _el;
await import("./tests/protocol_hook.mjs");
const { loadCrypto } = await import("./static/nadotx.js");
const G = await import("./static/pets-genes.js");
await loadCrypto("./static");
const { _m } = await import("./static/nadodapp.js");
const [sto, keep, consume] = JSON.parse(process.argv[1]);
const geneOf = (pid) => { %s; return gs; };
const halves = (pid) => G.geneFromHalves(_m(sto, "gl")[pid] || 0, _m(sto, "gh")[pid] || 0).toString();
console.log(JSON.stringify({ gk: geneOf(keep), gc: geneOf(consume), hk: halves(keep),
  preview: G.combineStatOf(BigInt(geneOf(keep)), BigInt(geneOf(consume))) }));
process.exit(0);                               // the SDK starts pollers on import; nothing else to wait for
""" % (m.group(0) if m else "")
out = {}
if m and shutil.which("node"):
    env = dict(os.environ, NADO_TEST_PROTOCOL_OVERRIDES=json.dumps({"BLAKE_EXEC_HEIGHT": 1}))
    r = subprocess.run(["node", "--input-type=module", "-e", js, json.dumps([view, str(keep), str(consume)])],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    out = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else {}
    T.check("the page runs (node)", bool(out), r.stderr[-800:])
T.check("the page reads each pet's whole gene", out.get("gk") == str(gk) and out.get("gc") == str(gc), out)
T.check("...which the halves alone would not have given", out.get("hk") not in (None, str(gk)), out.get("hk"))

before = [slot(P.TB_BASE + i, keep) for i in range(10)]
r = call("combine", [keep, consume])
after = [slot(P.TB_BASE + i, keep) for i in range(10)]
raised = [i for i in range(10) if after[i] == before[i] + 1]
T.check("setup: the combine applies on chain", r.endswith("-> ok") and len(raised) == 1, (r, before, after))
T.check("the page's preview is the stat the contract raised", raised == [out.get("preview")], (raised, out.get("preview")))

T.done("ALL PASS — a gen-29 pet previews the combine the contract rolls")
