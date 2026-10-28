"""A code event's leaf commits the WHOLE 256-bit code digest from protocol.CODE_COMMIT_WIDE_HEIGHT, and the frozen
Goldilocks residue below it (execnode/calls_commit.code_commitment, 2026-10-28).

calls_commit.code_commitment reduced the code digest to 1 + n mod (P - 1), P the Goldilocks prime: a ~64-bit commitment,
so a ~2^32 birthday search finds two codes with one event leaf (the call-leaf collision the 2026-09-24/25 audit rated
HIGH). Pins, under BOTH rule sets:
  1. below the gate the value is exactly the old residue (a replay of an older block reproduces its leaf);
  2. at and above the gate it is the whole blake2b digest, never reduced (here: wider than 64 bits);
  3. event_leaf reads the EVENT's own cursor, so the same deploy commits differently on either side of the gate;
  4. block_calls stamps a code event with its block's height, the cursor the gate keys on;
  5. the gate is keyed on generation 29 and is 1 on the next one (the residue never runs on a fresh chain).

Run: python3 tests/test_a_code_event_commits_the_whole_code_digest_from_its_gate.py
"""
import os, sys, tempfile
_T = tempfile.mkdtemp(prefix="nado-test-code-commit-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, _T, ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import protocol as PR
from hashing import blake2b_hash, canonical_bytes
from execnode import calls_commit as CC
from execnode.games import coinflip

import _harness
_report = _harness.Report()
check = _report.check

G = PR.CODE_COMMIT_WIDE_HEIGHT
P = 2**64 - 2**32 + 1
code = coinflip.build()
n = int(blake2b_hash(["code", canonical_bytes(code).hex()]), 16)

check("1. below the gate: exactly the frozen residue 1 + n mod (P - 1)",
      CC.code_commitment(code, G - 1) == 1 + n % (P - 1) and CC.code_commitment(code, 1) == 1 + n % (P - 1))
check("2. at and above the gate: the whole digest, never reduced",
      CC.code_commitment(code, G) == n == CC.code_commitment(code, G + 10**6) and n >= 1 << 64)
check("2. no cursor means now: the wide form", CC.code_commitment(code) == n)

ev = {"op": "deploy", "caller": "ndoA", "at": "", "nonce": "x", "code": code, "runtime": "zkvm", "upgradable": True,
      "timestamp": 0}
lo, hi = CC.event_leaf({**ev, "cursor": G - 1}), CC.event_leaf({**ev, "cursor": G})
check("3. event_leaf commits by the event's own cursor (the same deploy differs across the gate)",
      lo != hi and CC.event_leaf({**ev, "cursor": G - 1}) == lo)

block = {"block_number": G, "block_transactions": [
    {"recipient": "blob", "sender": "ndoA", "data": {"op": "deploy", "code": code, "nonce": "x"}}]}
entries = CC.block_calls(block)
evs = [e for e in entries if e.get("op") == "deploy"]
check("4. block_calls stamps a code event with its block's height", len(evs) == 1 and int(evs[0].get("cursor", -1)) == G,
      entries)

src = open(PR.__file__).read()
check("5. keyed on generation 29, 1 on a fresh chain",
      "CODE_COMMIT_WIDE_HEIGHT = 19000 if CHAIN_GENERATION == 29 else 1" in src)
_report.done()
