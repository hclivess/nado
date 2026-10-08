"""Pets rebirth costs REBIRTH_FEE, burned into the slot-1 tally (execnode/games/pets.py REBIRTH, Release B game
fairness). A free rebirth let an egg be re-pinned again and again until a pleasing gene block came up.

  * rebirth without value, or with any value other than REBIRTH_FEE, is refused and the egg keeps its pin;
  * rebirth with exactly REBIRTH_FEE re-pins the gene block (bh = cursor + HATCH_DELAY), adds the fee to the burn
    tally (slot 1) and to the pet's lifetime spend (tf);
  * the client mirrors the fee (static/pets-genes.js REBIRTH_FEE) and sends it with the call (static/pets.js).

Run: python3 tests/test_pets_rebirth_costs_a_burned_fee.py
"""
import os
import re
import sys
import tempfile
import shutil

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-pets-rebirth-")      # never the live database (assign, not setdefault)
import atexit; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from execnode.state import ExecState                                   # noqa: E402
from execnode.games import pets as P                                   # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


A = "ndoA" + "a" * 44
B = "ndoB" + "b" * 44
_n = [0]

st = ExecState(os.path.join(tempfile.mkdtemp(dir=os.environ["HOME"]), "s.json"))
st.cursor = 1000
st.bridge[A] = st.bridge[B] = 10 ** 13
code = P.build()
st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": P.ABI, "nonce": "n"}, A, "d")
cid = st.contract_id(A, code, "n")


def call(who, m, args, value=None):
    _n[0] += 1
    blob = {"op": "call", "contract": cid, "method": m, "args": args}
    if value is not None:
        blob["value"] = value
    return st.apply_blob(blob, who, f"{m}-{_n[0]}")


def rd(f, k):
    return int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))


check("REBIRTH_FEE is a small positive NADO amount", 0 < P.REBIRTH_FEE < P.MINT_FEE)
assert "ok" in call(A, "mint", [5], P.MINT_FEE)
bh0 = rd(P.BH, 5)
st.cursor = bh0 + P.STALE + 1                                 # the gene block is pruned: rebirth is the way out
burn0, tf0, bal0 = rd(0, P.BURN_SLOT), rd(P.TF, 5), st.bridge[A]
check("rebirth without value is refused", "ok" not in call(A, "rebirth", [5]) and rd(P.BH, 5) == bh0)
check("rebirth with less than REBIRTH_FEE is refused", "ok" not in call(A, "rebirth", [5], P.REBIRTH_FEE - 1))
check("rebirth with more than REBIRTH_FEE is refused", "ok" not in call(A, "rebirth", [5], P.REBIRTH_FEE + 1))
check("a stranger cannot rebirth my egg even paying the fee", "ok" not in call(B, "rebirth", [5], P.REBIRTH_FEE))
check("nothing was charged or burned by the refused calls", st.bridge[A] == bal0 and rd(0, P.BURN_SLOT) == burn0)
r = call(A, "rebirth", [5], P.REBIRTH_FEE)
check("rebirth with exactly REBIRTH_FEE re-pins the gene block", "ok" in r
      and rd(P.BH, 5) == st.cursor + P.HATCH_DELAY, r)
check("the fee is paid by the owner", bal0 - st.bridge[A] == P.REBIRTH_FEE)
check("the fee lands in the burn tally (slot 1)", rd(0, P.BURN_SLOT) == burn0 + P.REBIRTH_FEE)
check("and in the pet's lifetime spend (tf)", rd(P.TF, 5) == tf0 + P.REBIRTH_FEE)
check("a fresh egg cannot be reborn again right away, fee or not",
      "ok" not in call(A, "rebirth", [5], P.REBIRTH_FEE))

genes = open(os.path.join(ROOT, "static", "pets-genes.js"), encoding="utf-8").read()
m = re.search(r"REBIRTH_FEE\s*=\s*([0-9n *]+);", genes)
val = eval(m.group(1).replace("n", "")) if m else None                   # "10n ** 9n" -> 10 ** 9
check("static/pets-genes.js mirrors REBIRTH_FEE", val == P.REBIRTH_FEE, m and m.group(1))
js = open(os.path.join(ROOT, "static", "pets.js"), encoding="utf-8").read()
check("static/pets.js sends REBIRTH_FEE with the rebirth call",
      re.search(r'dapp\.call\("rebirth",[^;]*G\.REBIRTH_FEE', js) is not None)

print(f"\n{'ALL PASS' if not FAILED else str(len(FAILED)) + ' FAILED'}")
sys.exit(1 if FAILED else 0)
