"""The wallet's Stwo prover, static/vendor/stwo_js.wasm, is a build of the committed native/stwo_js — byte for byte.

A browser runs whatever file is SERVED, not what the crate says (CLAUDE.md rule 6: the TPM helper's fix was "in this
build" and absent from the file anyone downloaded). The shipped .wasm is a build product checked in at a path nothing
generates, so three things can drift and this pins all of them:
  1. the shipped file's sha256 is the one pinned here (WASM_SHA256), and
  2. the build's inputs (Cargo.toml, the pinned lock, src/ minus the test binary) hash to the pinned SOURCES_SHA256 —
     so a change to the circuit or the prover without a re-ship fails here even on a machine with no toolchain;
  3. with the toolchain (nightly-2026-01-15 + wasm32-unknown-unknown; $NADO_STWO_NIGHTLY_BIN may name its bin dir), a
     fresh build by tests/_stwo_js_build.Env.build_wasm — the ONE build command, documented there — is byte-identical
     to the shipped file. Without the toolchain this part prints SKIP and 1-2 still run.
To re-ship after a change under native/stwo_js:  python3 tests/_stwo_js_build.py --ship  (it prints both pins).

Run: python3 tests/test_the_shipped_stwo_wasm_is_a_build_of_the_committed_sources.py
"""
import os, sys, tempfile, hashlib
_REAL_HOME = os.path.expanduser("~")
_T = tempfile.mkdtemp(prefix="nado-test-stwo-wasm-ship-")
os.environ["HOME"] = _T
import atexit, shutil; atexit.register(shutil.rmtree, _T, ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests._stwo_js_build import Env, SHIPPED_WASM, wasm_sources_digest

WASM_SHA256 = "4d8df6ca781d5a30dfe7235ee478f9fa4e19802277fa53722d35aced797dc2bc"
SOURCES_SHA256 = "8b2b1b19865bb5463b4a92c9d6b603ffea675fc7384efff8eac2c1cada5f1b7d"

import _harness
_report = _harness.Report()
check = _report.check


shipped = open(SHIPPED_WASM, "rb").read()
check("1. the shipped static/vendor/stwo_js.wasm is the pinned build", hashlib.sha256(shipped).hexdigest() == WASM_SHA256,
      hashlib.sha256(shipped).hexdigest())
check("2. native/stwo_js is the source the pinned build was made from (re-ship after changing it)",
      wasm_sources_digest() == SOURCES_SHA256, wasm_sources_digest())

env = Env(_REAL_HOME)
nbin = env.nightly_bin()
if not nbin or not env.have_wasm_target(nbin):
    print("SKIP  3. no nightly-2026-01-15 with the wasm32-unknown-unknown target: the rebuild comparison needs it")
else:
    built, secs, log = env.build_wasm(nbin)
    if not built:
        check("3. the WASM builds from the committed sources", False, log[-1500:])
    else:
        fresh = open(built, "rb").read()
        check(f"3. a fresh build ({secs:.0f} s) is byte-identical to the shipped file", fresh == shipped,
              f"fresh {hashlib.sha256(fresh).hexdigest()} ({len(fresh)} B) vs shipped ({len(shipped)} B)")

print("ALL PASS — the shipped Stwo WASM is a build of the committed sources" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
