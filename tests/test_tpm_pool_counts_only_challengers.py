"""Only a challenger's own acts earn a seat in the TPM challenger pool — never the enrollee's commit
(ops/transaction_ops._proven_challengers, protocol.TPM_POOL_CHALLENGER_ACTS_HEIGHT).

WHY (2026-10-05, operator: "make sure there is no way to exploit it"). The pool counted every tpm_commit sender as a
challenger that had "acted". The commit is the ENROLLEE's message (tpm_enrol.apply_commit: sender == owner) and any
well-formed commitment lands, so opening an enrolment with a copied endorsement certificate and committing garbage
bought a seat for the whole 6000-block window: no bond, no node. Cheap seats dilute the pool — dead draws that fail
honest enrolments, and, often enough, all three seats of one enrolment.

Pins, on a synthetic chain (the draw reads committed blocks only):
  1. BELOW the gate the old rule holds (replay keeps every verdict): a commit sender is in the pool — the hole, shown;
  2. FROM the gate a commit sender is not, however many commits it lands;
  3. challengers' own acts still earn a seat: tpm_challenge, tpm_reveal, a recent tpm_ready;
  4. the rule is keyed on the draw's window, not on the scanned block (one window, one rule);
  5. the gate is keyed on the live generation.

Run: python3 tests/test_tpm_pool_counts_only_challengers.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-tpmpool-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import protocol as P
from ops import transaction_ops as T

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


L = P.EPOCH_LENGTH
NODE, CHAL, REV, SQUAT = "n" * 50, "c" * 50, "r" * 50, "s" * 50


def chain(top):
    """Every 5th block: NODE announces + lands a duty; CHAL challenges; REV reveals; SQUAT (an enrollee) commits."""
    blocks = {}
    for h in range(1, top + 1):
        txs = []
        if h % 5 == 0:
            txs = [{"recipient": "tpm_ready", "sender": NODE}, {"recipient": "duty", "sender": NODE},
                   {"recipient": "tpm_challenge", "sender": CHAL}, {"recipient": "tpm_reveal", "sender": REV},
                   {"recipient": "tpm_commit", "sender": SQUAT}]
        blocks[h] = {"block_transactions": txs}
    T.get_block_number = lambda n: blocks.get(int(n))
    T._tpm_proven_cache[0] = None


LIVE = P.TPM_POOL_CHALLENGER_ACTS_HEIGHT
GATE = 30 * L                                     # a gate inside the synthetic chain
P.TPM_POOL_CHALLENGER_ACTS_HEIGHT = GATE
try:
    chain(GATE + 10 * L)
    below = T._proven_challengers(GATE - 2 * L)
    check("BELOW the gate an enrollee's commit bought a seat (the hole, shown on the old rule)", SQUAT in below, below)
    T._tpm_proven_cache[0] = None
    above = T._proven_challengers(GATE + 2 * L)
    check("FROM the gate an enrollee's commit buys no seat", SQUAT not in above, above)
    check("...while a challenge, a reveal and a recent tpm_ready still earn one",
          {NODE, CHAL, REV} <= set(above), above)
    lo, hi = T.proven_window(GATE + 2 * L)
    check("one window, one rule: a window that starts below the gate but is drawn from it already excludes commits",
          lo < GATE <= hi and SQUAT not in above, (lo, hi))
finally:
    P.TPM_POOL_CHALLENGER_ACTS_HEIGHT = LIVE

src = open(os.path.join(ROOT, "protocol.py")).read()
check("the gate is keyed on the live generation (gen 28)",
      "TPM_POOL_CHALLENGER_ACTS_HEIGHT = 92000 if CHAIN_GENERATION == 28 else 1" in src and P.CHAIN_GENERATION == 28)
print("ALL PASS — only challengers earn a seat" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
