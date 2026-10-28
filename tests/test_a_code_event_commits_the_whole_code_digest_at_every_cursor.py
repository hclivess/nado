"""A code event's leaf commits the WHOLE 256-bit code digest at every cursor, and no Goldilocks prime is left anywhere in
the shipped tree (execnode/calls_commit.code_commitment, 2026-10-28).

calls_commit.code_commitment reduced the code digest to 1 + n mod (P - 1), P the Goldilocks prime: a ~64-bit commitment,
so a ~2^32 birthday search finds two codes with one event leaf (the call-leaf collision the 2026-09-24/25 audit rated
HIGH). CODE_COMMIT_WIDE_HEIGHT (19000 on betanet-10) made it wide; no deploy / upgrade / lock / transfer_contract exists
in blocks 0..19004 (measured 2026-10-28), so the narrow branch never ran on this chain and was deleted with the gate and
the constant — the LAST Goldilocks value in the tree. Pins:
  1. the commitment is the whole blake2b digest (wider than 64 bits), with no cursor to switch on;
  2. event_leaf commits the same code identically at cursor 1 and far past 19000 (no gate is left to cross);
  3. block_calls still stamps a code event with its block's height (the leaf commits it);
  4. the gate is gone from protocol.py (tests/test_gate_reroll_transfer.py keeps it in DELETED);
  5. no shipped source outside tests/ spells the Goldilocks prime's value — decimal, hex, or 2^64 - 2^32 + 1 in any
     notation. The G9 deletion was once declared complete from a NAME grep while reversi still reduced by the prime's
     value; this scans for the number, which a rename cannot hide.

Run: python3 tests/test_a_code_event_commits_the_whole_code_digest_at_every_cursor.py
"""
import os, re, sys, tempfile
_T = tempfile.mkdtemp(prefix="nado-test-code-commit-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, _T, ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import inspect
import protocol as PR
from hashing import blake2b_hash, canonical_bytes
from execnode import calls_commit as CC
from execnode.games import coinflip

import _harness
_report = _harness.Report()
check = _report.check

code = coinflip.build()
n = int(blake2b_hash(["code", canonical_bytes(code).hex()]), 16)

check("1. the whole digest, never reduced", CC.code_commitment(code) == n and n >= 1 << 64)
check("1. no cursor parameter is left to switch on", list(inspect.signature(CC.code_commitment).parameters) == ["code"])

ev = {"op": "deploy", "caller": "ndoA", "at": "", "nonce": "x", "code": code, "runtime": "zkvm", "upgradable": True,
      "timestamp": 0}
narrow = 1 + n % (2**64 - 2**32)   # the deleted residue, spelled without the prime itself (check 5 scans for it)


def _cc_in(leaf_ev):
    """The code commitment event_leaf hashed for this event: recompute the leaf with each candidate and see which one
    it is (the leaf is a digest, so the value cannot be read back out of it)."""
    got = CC.event_leaf(leaf_ev)
    orig = CC.code_commitment
    try:
        for name, v in (("wide", n), ("narrow", narrow)):
            CC.code_commitment = lambda c, _v=v: _v
            if CC.event_leaf(leaf_ev) == got:
                return name
    finally:
        CC.code_commitment = orig
    return None


check("2. event_leaf commits the whole digest at cursor 1, 18999, 19000 and far past",
      all(_cc_in({**ev, "cursor": c}) == "wide" for c in (1, 18999, 19000, 10**9)))

block = {"block_number": 19000, "block_transactions": [
    {"recipient": "blob", "sender": "ndoA", "data": {"op": "deploy", "code": code, "nonce": "x"}}]}
entries = CC.block_calls(block)
evs = [e for e in entries if e.get("op") == "deploy"]
check("3. block_calls stamps a code event with its block's height",
      len(evs) == 1 and int(evs[0].get("cursor", -1)) == 19000, entries)

check("4. the gate is gone from protocol.py",
      not hasattr(PR, "CODE_COMMIT_WIDE_HEIGHT") and "CODE_COMMIT_WIDE_HEIGHT =" not in open(PR.__file__).read())

# 5. Every spelling of p = 2^64 - 2^32 + 1, as a whole number (a hex run inside a longer constant — P-256's prime starts
# ffffffff00000001 — is not this number, hence the boundaries).
_PRIME = re.compile(
    r"(?<![0-9A-Za-z_])("
    r"18_?446_?744_?069_?414_?584_?321"
    r"|0x0*ffff_?ffff_?0000_?0001(?![0-9A-Fa-f_])"
    r"|2\s*(\*\*|\^)\s*64\s*-\s*2\s*(\*\*|\^)\s*32\s*\+\s*1"
    r"|\(\s*1u?\d*\s*<<\s*64\s*\)\s*-\s*\(\s*1u?\d*\s*<<\s*32\s*\)\s*\+\s*1"
    r"|2⁶⁴\s*[−-]\s*2³²\s*\+\s*1"
    r")", re.IGNORECASE)
_SRC = (".py", ".js", ".mjs", ".cjs", ".ts", ".rs", ".sh", ".html", ".c", ".h", ".go", ".sol", ".toml", ".json")
_SKIP_DIRS = {".git", "tests", "target", "node_modules", "__pycache__", "doc"}
hits = []
for d, dirs, files in os.walk(ROOT):
    dirs[:] = [x for x in dirs if x not in _SKIP_DIRS and not (d == ROOT and x.startswith("."))]
    for f in files:
        if not f.endswith(_SRC):
            continue
        p = os.path.join(d, f)
        try:
            text = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in _PRIME.finditer(text):
            hits.append(f"{os.path.relpath(p, ROOT)}:{text.count(chr(10), 0, m.start()) + 1}: {m.group(0)}")
check("5. no shipped source spells the Goldilocks prime", not hits, hits[:20])
_report.done()
