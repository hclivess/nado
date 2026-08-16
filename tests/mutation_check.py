"""Mutation check: break one guard at a time, and require the suite that claims to cover it to go RED.

WHY THIS EXISTS. A passing test is evidence only if it would fail when the thing it tests is broken. This
branch found the counter-example the hard way: a test that hashed two statements and asserted the digests
differed, claiming to prove the withdrawal destination was bound. It passed, it proved nothing, and the
helper it exercised turned out to be dead code — so the assurance it gave was entirely false. Every guard
below was added in response to a real defect; this establishes that removing any one of them is noticed.

KILL-SAFE, and that mattered immediately. The first version reverted in a `finally`, which SIGTERM skips —
a timeout killed it mid-run and left a consensus guard replaced by `if False:` in the working tree. Now:
mutations are restored from an in-memory copy of the ORIGINAL bytes, signal handlers restore on
SIGTERM/SIGINT, and the run ends by asserting `git status` is clean and SAYING SO. A harness that can leave
a guard switched off is more dangerous than any bug it might find.

    python3 tests/mutation_check.py       # ~25 min; every line must read CAUGHT
"""
import os, signal, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY_BIN = sys.executable
_ORIGINALS = {}

def restore_all(*_a):
    for path, data in _ORIGINALS.items():
        open(path, "w", encoding="utf8").write(data)
    _ORIGINALS.clear()

signal.signal(signal.SIGTERM, lambda *a: (restore_all(), sys.exit(143)))
signal.signal(signal.SIGINT, lambda *a: (restore_all(), sys.exit(130)))

MUTATIONS = [
    ("duplicate-commitment guard", "execnode/shielded_state.py",
     "        if pool.has_commitment(cid, cm):", "        if False:", "test_shielded_state_replay"),
    ("delta bound", "execnode/shielded_state.py",
     "        if not -VALUE_MAX < delta < VALUE_MAX:", "        if False:", "test_shielded_state_replay"),
    ("arity pin", "execnode/shielded_state.py",
     '        if want_arity is not None and stark.get("arity") != want_arity:', "        if False:",
     "test_shielded_state_replay"),
    ("depth pin", "execnode/shielded_state.py",
     '        if nfs and stark.get("D") != TREE_DEPTH:', "        if False:", "test_shielded_state_replay"),
    ("destination validation", "execnode/state.py",
     "                    if not validate_address(dest, allow_reserved=False) or dest in self.contracts:",
     "                    if False:", "test_shielded_state_replay"),
    ("empty-is-absent projection", "execnode/exec_root.py",
     "            if not app.trees[cid]:", "            if False:", "test_shielded_state_root"),
    ("nullifier-set absence", "execnode/exec_root.py",
     "        if app.nullifiers:", "        if True:", "test_shielded_state_root"),
    ("geometry bound (circuit)", "execnode/stark/appnote_circuit.py",
     "    if not (1 <= arity <= MAX_FIELDS) or not (1 <= D <= MAX_DEPTH):", "    if False:",
     "test_shielded_state_replay"),
    ("transparent-path switch", "execnode/shielded_state.py",
     "CONSENSUS_ALLOW_TRANSPARENT = False", "CONSENSUS_ALLOW_TRANSPARENT = True", "test_shielded_state"),
    ("no-mutation-on-rejection", "execnode/shielded_state.py",
     "    reason = verify_transition(public, proof, pool)\n    if reason is not None:\n        return reason",
     "    reason = verify_transition(public, proof, pool)\n    if reason is not None:\n        pool.spend(999)\n        return reason",
     "test_shielded_state_atomicity"),
]

print(f"{'guard broken':32s} {'suite':30s} result", flush=True)
survived = []
for label, path, old, new, suite in MUTATIONS:
    full = os.path.join(ROOT, path)
    src = open(full, encoding="utf8").read()
    if old not in src:
        print(f"{label:32s} {suite:30s} SKIP — anchor not found", flush=True)
        survived.append(label + " (anchor)"); continue
    _ORIGINALS[full] = src
    open(full, "w", encoding="utf8").write(src.replace(old, new, 1))
    try:
        rc = subprocess.run([PY_BIN, f"tests/{suite}.py"], cwd=ROOT, capture_output=True,
                            text=True, timeout=1200,
                            env={**os.environ, "FAST": "1"}).returncode
    except subprocess.TimeoutExpired:
        rc = -1
    finally:
        restore_all()
    caught = rc != 0
    print(f"{label:32s} {suite:30s} {'CAUGHT' if caught else '*** SURVIVED ***'}", flush=True)
    if not caught:
        survived.append(label)

dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
                       text=True).stdout.strip()
print()
print("working tree after the run:", "CLEAN" if not dirty else "DIRTY -> " + dirty)
print(f"{len(survived)} mutation(s) survived: {survived}" if survived else
      "every broken guard was caught by the suite that claims to cover it")
sys.exit(1 if (survived or dirty) else 0)
