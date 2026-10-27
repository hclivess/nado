"""Only a challenger's own acts earn a seat in the TPM challenger pool — never the enrollee's commit
(ops/transaction_ops._proven_challengers; gen 28's TPM_POOL_CHALLENGER_ACTS_HEIGHT, inlined in G9).

WHY (2026-10-05, operator: "make sure there is no way to exploit it"). The pool counted every tpm_commit sender as a
challenger that had "acted". The commit is the ENROLLEE's message (tpm_enrol.apply_commit: sender == owner) and any
well-formed commitment lands, so opening an enrolment with a copied endorsement certificate and committing garbage
bought a seat for the whole 6000-block window: no bond, no node. Cheap seats dilute the pool — dead draws that fail
honest enrolments, and, often enough, all three seats of one enrolment.

Pins, on a synthetic chain (the draw reads committed blocks only):
  1. a commit sender is never in the pool, however many commits it lands, in any window;
  2. challengers' own acts still earn a seat: tpm_challenge, tpm_reveal, a recent tpm_ready;
  3. the gate is gone: the rule holds from block 1 (a window ending at block 0 scans nothing).

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

import _harness
_report = _harness.Report()
check = _report.check


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


# The pre-gate half (a commit sender DID earn a seat below 92000) is retired in G9: generation 28's rules.
chain(40 * L)
for top in (2 * L, 10 * L, 40 * L):
    T._tpm_proven_cache[0] = None
    pool = T._proven_challengers(top)
    check(f"an enrollee's commit buys no seat (window drawn at {top})", SQUAT not in pool, pool)
    check(f"...while a challenge, a reveal and a recent tpm_ready still earn one (window drawn at {top})",
          {NODE, CHAL, REV} <= set(pool), pool)
T._tpm_proven_cache[0] = None
check("a window ending at block 0 scans nothing (the inlined gate never had a block to judge there)",
      T._proven_challengers(0) == {}, T._proven_challengers(0))
check("the gate is deleted (gen 29: the rule holds from block 1)", not hasattr(P, "TPM_POOL_CHALLENGER_ACTS_HEIGHT"))
print("ALL PASS — only challengers earn a seat" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
