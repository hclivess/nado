"""Mutation check: break one guard at a time, and require the suite that claims to cover it to go RED.

WHY THIS EXISTS. A passing test is evidence only if it would fail when the thing it tests is broken. This
branch found the counter-example the hard way: a test that hashed two statements and asserted the digests
differed, claiming to prove the withdrawal destination was bound. It passed, it proved nothing, and the
helper it exercised turned out to be dead code — so the assurance it gave was entirely false. Every guard
below was added in response to a real defect; this establishes that removing any one of them is noticed.

DRIVE IT FROM THIS TABLE, never from a copy. A pointer in this file once named the wrong suite; the fix
was applied with a string replace that silently did not match, the script printed success anyway, and the
"verification" was a separate snippet with the correct suite hardcoded — so it confirmed the intended fix
while the file still held the broken one. The mutation duly survived again on the next full run. If you
re-check a subset, read the entries out of MUTATIONS rather than retyping them.

KILL-SAFE, and that mattered immediately. The first version reverted in a `finally`, which SIGTERM skips —
a timeout killed it mid-run and left a consensus guard replaced by `if False:` in the working tree. Now:
mutations are restored from an in-memory copy of the ORIGINAL bytes, signal handlers restore on
SIGTERM/SIGINT, and the run ends by asserting `git status` is clean and SAYING SO. A harness that can leave
a guard switched off is more dangerous than any bug it might find.

    python3 tests/mutation_check.py       # a few minutes; every line must read CAUGHT
"""
import os, shutil, signal, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY_BIN = sys.executable
_ORIGINALS = {}

def _purge_bytecode():
    """Delete every __pycache__ under the repo.

    NOT optional, and not hygiene. Python invalidates a .pyc on (source mtime, source size). A mutation
    that is the SAME BYTE LENGTH as the original — 18 -> 19, `11, 12` -> `13, 14`, 3 -> 4, 128 -> 256 —
    restored within the same mtime second leaves the cached bytecode considered valid, so the MUTATED code
    keeps running from cache while the source on disk is correct. Observed exactly that: the source read
    TREE_DEPTH = 18 and a fresh interpreter reported 19. Every result from a same-length mutation is
    untrustworthy without this, in both directions — a later suite can fail against code that no longer
    exists, and a mutation can appear caught for the wrong reason."""
    for root, dirs, _files in os.walk(ROOT):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                dirs.remove(d)


def restore_all(*_a):
    for path, data in _ORIGINALS.items():
        open(path, "w", encoding="utf8").write(data)
    _ORIGINALS.clear()
    _purge_bytecode()

signal.signal(signal.SIGTERM, lambda *a: (restore_all(), sys.exit(143)))
signal.signal(signal.SIGINT, lambda *a: (restore_all(), sys.exit(130)))

MUTATIONS = [
    # The shielded-contract guards this table held (shielded_state.py, appnote_circuit, private_call's ledger checks,
    # exec_root's app-state projection) went with that code in G9 slice 5. What is left is the LEGACY transparent pool,
    # still live on generation 29 for zero-value notes (ExecState "shielded_transfer"): its guards, each with the suite
    # that claims it.
    ("unbacked-mint fence", "execnode/state.py",
     "                if pv > 0:\n                    return \"skip shielded_transfer: public_value > 0",
     "                if False:\n                    return \"skip shielded_transfer: public_value > 0", "test_unbacked_mint"),
    ("stark bundle refusal", "execnode/state.py",
     '                if proof.get("stark") is not None:', "                if False:", "test_privacy_pause"),
    ("duplicate commitment (Z6)", "execnode/state.py",
     "                if self.rules_r2() and any(cm in self.shielded.commitments",
     "                if False and any(cm in self.shielded.commitments", "test_review_round2"),
    ("double-spend check", "execnode/shielded.py",
     "        if pool.has_nullifier(nf):", "        if False:", "test_shielded_exec"),
    ("value conservation", "execnode/shielded.py",
     "    if in_sum + pub_val != out_sum + fee:", "    if False:", "test_shielded_exec"),
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
                            env={**os.environ, "FAST": "1",
                                 "PYTHONDONTWRITEBYTECODE": "1"}).returncode
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
