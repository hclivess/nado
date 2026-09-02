"""METERED DIVIDEND CARRY (protocol.DIV_CARRY_METER_EPOCH, records_bind.dividend_accrual_effects) — 2026-09-02.

Epochs 0-193 of betanet-6: every identity on probation, weight set empty, the whole inflow carried forward.
Epoch 194: ONE identity had left probation and received the entire backlog, 113.29 NADO against 0.587 NADO
per epoch (fazer's report). Pinned here: the gate's shape; the pre-gate rule is byte-identical to the old one;
after the gate a backlog releases max(inflow, floor) per epoch on top of the inflow and drains even at zero
inflow; nothing is ever lost (inflow in == distributed + carry out); and the live accrual applies exactly
what the settle binding derives (one function).
Run: python3 tests/test_div_carry_meter.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_divmeter_")
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


import protocol as P
from execnode.stark import records_bind as RB

G = P.DIV_CARRY_METER_EPOCH
check("gate is generation-keyed: 600 on gen 24, 0 elsewhere", G == (600 if P.CHAIN_GENERATION == 24 else 0), G)
check("the expression self-disarms", "DIV_CARRY_METER_EPOCH = 600 if CHAIN_GENERATION == 24 else 0" in open(os.path.join(ROOT, "protocol.py")).read())

INF, W = 5_871_180_000, {"a": 2}
# ---- before the gate (or a caller with no epoch): the whole backlog is in the pot — the old rule, unchanged
eff, carry = RB.dividend_accrual_effects(INF, W, 100 * INF, None)
check("no epoch -> old rule: the whole backlog pays out at once", sum(d for _, _, d in eff) == 101 * INF and carry == 0)
if G > 0:
    eff, carry = RB.dividend_accrual_effects(INF, W, 100 * INF, G - 1)
    check("one epoch before the gate -> old rule", sum(d for _, _, d in eff) == 101 * INF and carry == 0)
# ---- at/after the gate: metered
eff, carry = RB.dividend_accrual_effects(INF, W, 100 * INF, G)
paid = sum(d for _, _, d in eff)
check("at the gate a 100-epoch backlog releases ONE epoch's inflow on top of the inflow", paid == 2 * INF and carry == 99 * INF, (paid, carry))
eff, carry = RB.dividend_accrual_effects(0, W, 3 * P.DIV_CARRY_RELEASE_FLOOR, G + 1)
check("zero inflow still drains the backlog by the floor", sum(d for _, _, d in eff) == P.DIV_CARRY_RELEASE_FLOOR and carry == 2 * P.DIV_CARRY_RELEASE_FLOOR)
eff, carry = RB.dividend_accrual_effects(INF, {}, 7 * INF, G + 2)
check("no present set -> nothing paid, inflow joins the backlog", eff == [] and carry == 8 * INF)
# ---- conservation over a simulated probation exit: 190 empty epochs then identities appear
carry, paid_total, inflow_total = 0, 0, 0
for e in range(G, G + 260):
    weights = {} if e < G + 190 else ({"first": 2} if e < G + 191 else {"first": 2, "b": 2, "c": 2, "d": 2})
    eff, carry = RB.dividend_accrual_effects(INF, weights, carry, e)
    paid_total += sum(d for _, _, d in eff); inflow_total += INF
    if e == G + 190:
        first_pay = sum(d for _, _, d in eff)
check("the first identity out of probation gets two epochs' worth, not the backlog", first_pay == 2 * INF, first_pay)
check("nothing is lost: inflow == paid + carry", inflow_total == paid_total + carry, (inflow_total, paid_total, carry))
check("the backlog is draining (carry < 190 epochs)", carry < 190 * INF, carry)
# ---- the live accrual applies exactly the shared rule's effects
from execnode.state import ExecState
st = ExecState(path=os.path.join(os.environ["HOME"], "s.json"))
st.div_carry = 50 * INF
dist = st.accrue_dividend_epoch(INF, {"x": 2, "y": 4}, epoch=G + 5)
eff, carry2 = RB.dividend_accrual_effects(INF, {"x": 2, "y": 4}, 50 * INF, G + 5)
check("state.accrue_dividend_epoch == records_bind rule (map + carry)",
      dist == sum(d for _, _, d in eff) and st.div_carry == carry2 and st.dividend == {a[0]: d for _, a, d in eff})
src = open(os.path.join(ROOT, "execnode", "state.py")).read()
check("the live accrual has no arithmetic of its own", "pot * max(1, int(w)) // total_w" not in src and "_RB.dividend_accrual_effects(inflow, weights, self.div_carry, epoch)" in src)
for f, needle in (("execnode/execnode.py", "accrue_dividend_epoch(inflow, (ow or {}).get(\"weights\", {}), epoch=E)"),
                  ("execnode/execnode.py", "carry, _E)"), ("loops/core_loop.py", "carry_in, int(epoch))")):
    check(f"{f} passes the epoch", needle in open(os.path.join(ROOT, f)).read())

print()
print("ALL DIV-CARRY-METER CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
sys.exit(1 if _fails else 0)
