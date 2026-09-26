"""A records-bound settle validated DEEP does not crash: the proof identity `_vk` is bound before the depth gate
(ops/transaction_ops.validate_transaction).

The records-half memo keys on `_vk`, which was assigned only in the strict branch; a node catching up more than
FINALITY_DEPTH behind validates deep, skipped that branch and raised UnboundLocalError. The first records-bound settle on
betanet-8 (block 10212) froze the relay at 10211 for 80 minutes, and every node syncing across it would have stopped
there. A real records-bound proof is too heavy for a unit test, so this pins the ORDER in the source: `_vk` is
assigned in the settle branch before the depth gate, and not again inside it.

Run: python3 tests/test_settle_deep_records_bound.py
"""
import os, sys, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
gate = src.index("if deep and _protocol.SETTLE_PROOF_DEPTH_GATED:")
assigns = [m.start() for m in re.finditer(r"^\s*_vk = settle_verify_key\(", src, re.M)]
def _code(i):                      # a use on a code line, not in a comment
    line = src[src.rfind("\n", 0, i) + 1:i]
    return "#" not in line
uses = [m.start() for m in re.finditer(r"\b_vk\b", src) if not src[m.start():].startswith("_vk = ") and _code(m.start())]
fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name); fails += 0 if ok else 1
check("the proof identity is assigned exactly once", len(assigns) == 1)
check("... BEFORE the depth gate, so the deep path has it too", assigns and assigns[0] < gate)
check("every later use of it comes after that assignment", assigns and all(u > assigns[0] for u in uses if u > gate - 5000))
print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
