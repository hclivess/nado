"""At a reroll, an OPEN invite or HTLC lock goes back to whoever funded it (tools/alphanet6_carryforward
.open_escrow_refunds), debited from its escrow — the records do not survive the reroll, so without the fold the coins
would carry as the escrow's balance with nothing left that could release them. Claimed and refunded records are
settled already and move nothing. The fold is wired into build() beside the other escrow folds, before the
conservation check.

Run: python3 tests/test_reroll_refunds_open_invites_and_htlcs.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_carry_escrow_")
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools.alphanet6_carryforward import open_escrow_refunds

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


inv = {"i1": ["alice", 500, 9000, "open", ""], "i2": ["alice", 70, 9000, "open", ""],
       "i3": ["bob", 999, 9000, "claimed", "carol"], "i4": ["bob", 5, 9000, "refunded", ""]}
htl = {"h1": {"sender": "dave", "claimant": "erin", "amount": 300, "status": "open"},
       "h2": {"sender": "dave", "claimant": "erin", "amount": 40, "status": "claimed"}}
refunds, out = open_escrow_refunds(inv, htl)
check("every open invite goes back to its referrer", refunds.get("alice") == 570, refunds)
check("an open HTLC lock goes back to its sender", refunds.get("dave") == 300, refunds)
check("claimed and refunded records move nothing", "bob" not in refunds and "carol" not in refunds and "erin" not in refunds, refunds)
check("each escrow is debited by exactly what it refunds", out == {"invite": 570, "htlc": 300}, out)
check("refunds and debits balance (supply conserved)", sum(refunds.values()) == sum(out.values()))
src = open(os.path.join(ROOT, "tools", "alphanet6_carryforward.py")).read()
b = src[src.index("def build():"):src.index("CONSERVATION")]
check("build() applies the fold before the conservation check",
      "open_escrow_refunds(kv_ops.invite_all(), kv_ops.htlc_all())" in b and "debit_reserved(acct, v)" in b)
print("ALL PASS — open escrows go home at a reroll" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
