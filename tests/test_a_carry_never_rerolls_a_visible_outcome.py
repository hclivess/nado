"""A reroll carry never re-rolls a pets outcome that was already visible on the old chain (pets.carry_in_flight /
carry_rebase): it re-pins only a roll whose randomness is NOT YET MINED at the tip.

Found 2026-10-11 (review): carry_rebase re-pinned EVERY pending roll to a new-chain block — an unhatched egg whose gene
blocks were mined (its gene already public), a training session whose roll was already decided. An owner who saw a bad
result simply left it unresolved until the reroll and got a fresh roll for free, which is exactly what REBIRTH_FEE exists
to price ("an egg can no longer be re-pinned at no cost").

The choice, and why: a visible roll BLOCKS the carry while any caller can still resolve it on the old chain — hatch,
train_resolve, resolve/refund_battle, collect and a value-0 reroll are all permissionless — so the operator clears them
and runs the carry again, and nobody can hold the carry hostage with a pin only its owner could move. A visible roll that
no third party can resolve any more (its hashes left the exec ring) takes the contract's own stale outcome where one
exists: a training session lapses, as train() lapses a stale session.

Pins, on the REAL pets contract (throwaway HOME):
  1. an egg minted at the tip (gene blocks not mined) carries and is re-pinned — no blocker;
  2. an egg whose gene blocks are mined blocks the carry, naming hatch(pid), and the policy is "reset" (a blocker);
  3. a pending training session whose roll is mined blocks it too, naming train_resolve(pid);
  4. carry_rebase itself refuses to re-pin them (a direct caller cannot re-roll them either);
  5. a THIRD PARTY resolves both on the old chain (permissionless), and the contract then carries — with the hatched
     gene unchanged by the carry;
  6. a training session whose hashes left the exec ring is not a blocker: it lapses (TH = 0), never re-rolled;
  7. every value the rebase writes is an int.

Run: python3 tests/test_a_carry_never_rerolls_a_visible_outcome.py
"""
import os, sys, json, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-carry-visible-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
H = os.environ["HOME"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from execnode.state import ExecState, _BLOCKHASH_RING
from execnode.games import pets as P
import tools.alphanet6_carryforward as C

import _harness
_report = _harness.Report()
check = _report.check


A, X = "ndoA" + "a" * 44, "ndoX" + "x" * 44
_n = [0]


def call(st, cid, who, method, args, value=None):
    _n[0] += 1
    p = {"op": "call", "contract": cid, "method": method, "args": args}
    if value:
        p["value"] = value
    return st.apply_blob(p, who, f"{method}-{_n[0]}")


old = ExecState(os.path.join(H, "old.json"))
old.cursor, old.block_ts = 150_000, int(time.time())
old.block_hashes = {h: (h * 1_000_003 + 7) for h in range(120_000, 160_000)}
code = P.build()
old.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": P.ABI, "nonce": "n"}, A, "d")
cid = old.contract_id(A, code, "n")
rd = lambda st, f, k: int((st["slots"] if "slots" in st else st).get(str((f << 32) + k), 0))
S = lambda: old.contracts[cid]["storage"]
old.credit_deposit(A, 100 * P.MINT_FEE)

call(old, cid, A, "mint", [1], P.MINT_FEE)                     # a pet to train
old.cursor += 3
call(old, cid, A, "hatch", [1])
call(old, cid, A, "train", [1, 3], P.TRAIN_FEE)                # TH = cursor + 2
call(old, cid, A, "mint", [2], P.MINT_FEE)                     # an egg: BH = cursor + 2
old.cursor += 5                                                # both rolls are now mined and visible
call(old, cid, A, "mint", [3], P.MINT_FEE)                     # an egg minted AT the tip: BH = tip + 2, not mined
TIP = old.cursor
check("setup: a visible training roll, a visible egg, and an egg whose gene blocks are not mined yet",
      rd(S(), P.TH, 1) + 1 <= TIP and rd(S(), P.BH, 2) + 1 <= TIP and rd(S(), P.BH, 3) > TIP and not rd(S(), P.GN, 2),
      (rd(S(), P.TH, 1), rd(S(), P.BH, 2), rd(S(), P.BH, 3), TIP))

why = P.carry_in_flight(S(), tip=TIP)
check("1. an egg whose gene blocks are not mined is no blocker", not any("egg 3" in w for w in why), why)
check("2. an egg whose gene blocks are mined blocks the carry, naming hatch(2)", any("hatch(2)" in w for w in why), why)
check("3. a training session whose roll is mined blocks it, naming train_resolve(1)", any("train_resolve(1)" in w for w in why), why)
C.CARRY_BLOCKERS.clear()
check("...so the carry policy is reset with the blockers recorded (and the carry refuses: refuse_blockers)",
      C.carry_policy(cid, old.contracts[cid], tip=TIP) == "reset" and C.CARRY_BLOCKERS.get(cid) == why, C.CARRY_BLOCKERS)
try:
    P.carry_rebase(json.loads(json.dumps(S())), TIP)
    raised = False
except ValueError:
    raised = True
check("4. carry_rebase refuses to re-pin a visible roll", raised)

r1, r2 = call(old, cid, X, "hatch", [2]), call(old, cid, X, "train_resolve", [1])
gene = rd(S(), P.GN, 2)
check("5. a third party resolves both on the old chain (permissionless)", "ok" in r1 and "ok" in r2 and gene
      and rd(S(), P.TH, 1) == 0, (r1, r2))
C.CARRY_BLOCKERS.clear()
check("...and the contract then carries", C.carry_policy(cid, old.contracts[cid], tip=TIP) == "keep"
      and P.carry_in_flight(S(), tip=TIP) == [], P.carry_in_flight(S(), tip=TIP))
gen, _ = C.exec_genesis_doc({cid: old.contracts[cid]}, {}, tip=TIP)
gs = gen[cid]["storage"]
check("...with the hatched gene exactly as the old chain decided it, and the unmined egg re-pinned to the new chain",
      rd(gs, P.GN, 2) == gene and P.CARRY_PIN_FLOOR <= rd(gs, P.BH, 3) <= 10, (rd(gs, P.GN, 2), rd(gs, P.BH, 3)))

# 6. a session whose hashes left the exec block-hash ring: no third party can resolve it any more
call(old, cid, A, "train", [1, 4], P.TRAIN_FEE)
th = rd(S(), P.TH, 1)
far = th + _BLOCKHASH_RING + 10
why6 = P.carry_in_flight(S(), tip=far)
check("6. a roll whose hashes left the exec ring is no blocker (nobody could resolve it) ...",
      not any("train_resolve(1)" in w for w in why6), why6)
reb = P.carry_rebase(json.loads(json.dumps({k: v for k, v in S().items()})), far)
check("...it lapses (TH = 0, as train() lapses a stale session), never re-rolled", rd(reb, P.TH, 1) == 0, rd(reb, P.TH, 1))
pure = P.carry_rebase(json.loads(json.dumps(S())), far)
check("7. every value the rebase writes is an int",
      all(type(v) is int for k, v in pure["slots"].items() if k in {str((f << 32) + i) for f in
          (P.BH, P.FU, P.EX, P.TH) for i in (1, 2, 3)}), pure["slots"])
print("ALL PASS — a carry never re-rolls a visible outcome" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
