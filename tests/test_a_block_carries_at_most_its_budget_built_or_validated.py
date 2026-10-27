"""A block carries at most its budget, built or validated (from block 1; ops/transaction_ops
cap_block_budget / assert_block_budget; ops/block_ops.match_transactions_target; loops/core_loop validation).

Every transaction had its own size cap, but nothing bounded the work ONE block demands of every node validating it
(2026-10-27 incident survey: aleo snarkVM#3443 enforced a block-wide limit only when building, so every validator
accepted an over-limit block). From block 1 a block carries at most MAX_BLOCK_TXS transactions and MAX_BLOCK_TX_BYTES
canonical bytes, enforced identically when assembling and when validating.

Pins: at height 0 (genesis) neither function changes anything; from block 1 an over-budget set is refused
by assert_block_budget, the assembler keeps exactly a passing prefix (duty first, then txid order) whatever order it is
handed, a set inside the budget is untouched, the byte bound holds as well as the count, and both the assembly path and
the block-validation path call the budget (a limit checked only when building is no limit).

Run: python3 tests/test_a_block_carries_at_most_its_budget_built_or_validated.py
"""
import os, sys, tempfile, random, inspect
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-block-budget-")
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import protocol as P
from ops import transaction_ops as T
from hashing import canonical_bytes

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def refused(fn):
    try:
        fn()
        return False
    except AssertionError:
        return True


def tx(i, recipient="xyz", pad=0):
    return {"txid": f"{i:064x}", "recipient": recipient, "sender": f"{i:050x}", "amount": 1, "data": "x" * pad}


# BLOCK_BUDGET_HEIGHT (gen 28's gate, 1 from gen 29) was inlined in G9; the pre-gate heights of generation 28 are retired
# in G9: generation 28's rules. Height 0 keeps the old answer (the inlined `< 1`), pinned below.
GATE = 1000                                  # a base height past block 1
P.MAX_BLOCK_TXS = 50                         # small budgets for the test; the shipped values are pinned below
P.MAX_BLOCK_TX_BYTES = 40_000

many = [tx(i) for i in range(80)] + [tx(1000 + i, "duty") for i in range(5)]
random.Random(7).shuffle(many)
check("at height 0 an over-budget set passes validation unchanged",
      T.assert_block_budget(many, 0) is True and T.cap_block_budget(many, 0) == many)
check("from block 1 a set over MAX_BLOCK_TXS is refused",
      refused(lambda: T.assert_block_budget(many, 1)) and refused(lambda: T.assert_block_budget(many, GATE)))
kept = T.cap_block_budget(many, GATE)
check("the assembler keeps exactly MAX_BLOCK_TXS, which validation accepts", len(kept) == 50
      and T.assert_block_budget(kept, GATE) is True, len(kept))
check("...every duty transaction first (consensus participation is never the one left out)",
      [t["recipient"] for t in kept[:5]] == ["duty"] * 5)
check("...and the rest in txid order: the same prefix whatever order it was handed",
      kept == T.cap_block_budget(list(reversed(many)), GATE) and [t["txid"] for t in kept[5:]] == sorted(t["txid"] for t in kept[5:]))
small = many[:20]
check("a set inside the budget is untouched by the assembler", sorted(T.cap_block_budget(small, GATE), key=lambda t: t["txid"])
      == sorted(small, key=lambda t: t["txid"]))
fat = [tx(i, pad=3000) for i in range(30)]
check("the byte budget binds as well as the count", refused(lambda: T.assert_block_budget(fat, GATE))
      and sum(len(canonical_bytes(t)) for t in T.cap_block_budget(fat, GATE)) <= P.MAX_BLOCK_TX_BYTES
      and T.assert_block_budget(T.cap_block_budget(fat, GATE), GATE) is True)

from ops import block_ops as B
from loops import core_loop as C
check("the assembly path applies the budget (match_transactions_target -> cap_block_budget)",
      "cap_block_budget(" in inspect.getsource(B.match_transactions_target))
check("...and block validation enforces it on every block (validate_transactions_in_block -> assert_block_budget)",
      "assert_block_budget(" in inspect.getsource(C.CoreClient.validate_transactions_in_block))

src = open(os.path.join(os.path.dirname(P.__file__), "protocol.py")).read()
check("the shipped budget is far above honest load (measured max 19 txs, p99 54 KB per block)",
      "MAX_BLOCK_TXS = 2000" in src and "MAX_BLOCK_TX_BYTES = 8 * 1024 * 1024" in src)

print("\nALL PASS — a block carries at most its budget, built or validated" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
