"""The Farkle page shows the dice the contract SCORES — die for die, for every seat, roll and dice count.

static/farkle.js rollDice once hashed with blake2b (no mod-P reduction, no LO32 window) while the contract derives
each die with the zkVM's alghash: die_p = (alghash([(seed+p) % P]) & 0xFFFFFFFF) % 6 + 1, seed = (bh(grh)%P +
bh(grh+1)%P + seat*1000 + rolln*10) % P. The page therefore showed one roll and the contract scored another: a
player set aside dice they could see, and hold() judged them against dice they could not.

This driver builds two sets of vectors and hands them to tests/farkle_client_rolls_the_contracts_dice.mjs, which
evaluates the page's OWN rollDice (lifted verbatim from static/farkle.js) with the real chainResultAlg:
  1. execnode.games.farkle.roll_dice over many random 256-bit block hashes / seats / roll numbers / dice counts;
  2. ACTUAL contract rolls on an isolated ExecState: open, roll, publish the two block hashes, hold — then the six
     dice the VM itself wrote into its scratch slots (SC 0..5) are read back out of storage.
Teeth: the .mjs also runs the old blake2b derivation and requires it to DISAGREE with the contract.

Run: python3 tests/test_farkle_client_rolls_the_contracts_dice.py
"""
import os, tempfile, shutil, atexit
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-farkle-dice-")              # assign, never setdefault
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)

import sys, json, random, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from execnode.state import ExecState
from execnode.games import farkle as fk

A = "ndoFARK" + "A" * 41
rng = random.Random(20261010)


def reference_vectors(n=400):
    out = []
    for _ in range(n):
        h0, h1 = rng.getrandbits(256), rng.getrandbits(256)          # 256-bit: exercises the mod-P reduction
        seat, rolln, dl = rng.randrange(1, 1 << 32), rng.randrange(0, 1000), rng.randrange(1, 7)
        out.append({"seat": seat, "rolln": rolln, "dl": dl, "a": format(h0, "x"), "b": format(h1, "x"),
                    "dice": fk.roll_dice(h0, h1, seat, rolln, dl)[:dl]})
    return out


def contract_vectors(n_seats=6, rolls_each=8):
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=os.environ["HOME"]), "s.json")); st.cursor = 100
    code = fk.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": fk.ABI, "nonce": "n"}, A, "d")
    cid = st.contract_id(A, code, "n")
    st.credit_deposit(A, 10 ** 12)
    rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
    pack = lambda k: sum(k[f] << (3 * (f - 1)) for f in range(1, 7))
    out, cur = [], 200
    for i in range(n_seats):
        T, G = 10 + i, rng.randrange(1, 1 << 32)
        r = str(st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [T, G], "value": 50_000}, A, f"o{i}"))
        assert "revert" not in r.lower(), r
        for j in range(rolls_each):
            if rd(fk.GFIN, G):
                break
            cur += 40; st.cursor = cur
            st.apply_blob({"op": "call", "contract": cid, "method": "roll", "args": [G]}, A, f"r{i}.{j}")
            grh, grn, gdl = rd(fk.GRH, G), rd(fk.GRN, G), rd(fk.GDL, G)
            assert grh, "roll must pin a future height"
            h0, h1 = rng.getrandbits(256), rng.getrandbits(256)
            st.block_hashes[grh] = h0; st.block_hashes[grh + 1] = h1; cur = grh + 2; st.cursor = cur
            dice = fk.roll_dice(h0, h1, G, grn, gdl)
            c = {f: sum(1 for d in dice if d == f) for f in range(1, 7)}
            keep = {f: (c[f] if f in (1, 5) or c[f] >= 3 else 0) for f in range(1, 7)}
            r = str(st.apply_blob({"op": "call", "contract": cid, "method": "hold", "args": [G, pack(keep), 1]}, A, f"h{i}.{j}"))
            assert "revert" not in r.lower(), r
            vm = [rd(fk.SC, p) for p in range(6)]                       # the dice the VM derived, as it stored them
            assert vm[gdl:] == [0] * (6 - gdl), vm
            out.append({"seat": G, "rolln": grn, "dl": gdl, "a": format(h0, "x"), "b": format(h1, "x"), "dice": vm[:gdl]})
    return out


V = {"reference": reference_vectors(), "contract": contract_vectors()}
assert len(V["contract"]) >= 30, len(V["contract"])
assert len({v["dl"] for v in V["contract"]}) >= 3, "contract rolls should cover several dice counts"
p = subprocess.run(["node", os.path.join(ROOT, "tests", "farkle_client_rolls_the_contracts_dice.mjs")],
                   input=json.dumps(V), capture_output=True, text=True, cwd=ROOT, timeout=300)
print(p.stdout.rstrip()[-3000:])
if p.returncode:
    print(p.stderr.rstrip())
    print("FAIL  the Farkle page's dice do not equal the contract's dice")
    sys.exit(1)
print(f"PASS  farkle.js rollDice equals roll_dice on {len(V['reference'])} vectors and the VM on {len(V['contract'])} real rolls")
