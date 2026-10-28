"""Every native crate the node requires (ops/self_update._CRATES) has its sources TRACKED in git — a commit can never
drop them while the files sit on disk untracked.

Found 2026-10-25, before the push: a docstring-only commit (905ac0c8, on a feature branch) also deleted the tracked
sources of all six required crates — mldsa44, alghash2, starkcompose, starkprove, attest, wasm/goldilocks — while the
files stayed on disk as untracked. Every local test passed, because the files were there. Pushed, every node would have
fast-forwarded to a tree without the sources of the libraries it verifies signatures and proofs with, and the updater's
rebuild of a stale or missing library would have had nothing to build. Pins, through git itself:
  1. every required (and optional) crate has its manifest and src/lib.rs in the COMMITTED tree (HEAD);
  2. every tracked crate manifest's src/lib.rs is tracked too (a half-deleted crate is caught as well);
  3. every tracked native/ crate is one the updater builds (_CRATES / _OPTIONAL_CRATES), and the Goldilocks crates G9
     slice 6 deleted (alghash2, starkcompose, starkprove, wasm/goldilocks) are neither tracked nor listed — a crate
     leaves _CRATES in the commit that deletes it, and its path is never reused (doc/stwo-migration.md 9.6).

Run: python3 tests/test_every_required_native_crate_is_tracked.py
"""
import _harness
HOME = _harness.isolate("nado-test-crates-tracked-")
import os
import subprocess

from ops import self_update as SU

T = _harness.Report()
ROOT = _harness.ROOT
tracked = set(subprocess.run(["git", "-c", "safe.directory=*", "-C", ROOT, "ls-tree", "-r", "--name-only", "HEAD"], capture_output=True, text=True, check=True).stdout.split("\n"))
crates = list(SU._CRATES) + list(SU._OPTIONAL_CRATES)
missing = [f"{c}/{f}" for c in crates for f in ("Cargo.toml", "src/lib.rs") if f"{c}/{f}" not in tracked]
T.check("1. every required crate's manifest and src/lib.rs are tracked", not missing and len(crates) >= 5, missing)
manifests = sorted(f for f in tracked if f.endswith("/Cargo.toml") and (f.startswith("native/") or f.startswith("wasm/"))
                   and f.count("/") == 2)
half = [m for m in manifests if m.replace("Cargo.toml", "src/lib.rs") not in tracked
        and m.replace("Cargo.toml", "src/main.rs") not in tracked]
T.check("2. no tracked crate is half-deleted (manifest without its sources)", not half and manifests, half)
unlisted = [m for m in manifests if m.startswith("native/") and m.rsplit("/", 1)[0] not in crates]
T.check("3a. every tracked native/ crate is built by the updater", not unlisted, unlisted)
GONE = ("native/alghash2", "native/starkcompose", "native/starkprove", "wasm/goldilocks")
back = [g for g in GONE if g in crates or any(f.startswith(g + "/") for f in tracked)]
T.check("3b. the deleted Goldilocks crates are neither tracked nor listed", not back, back)
T.done("ALL PASS — every required native crate is tracked")
