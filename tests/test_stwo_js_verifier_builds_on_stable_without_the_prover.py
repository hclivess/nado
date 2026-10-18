"""THE STWO JOIN-SPLIT VERIFIER BUILDS ON STABLE RUST AND NEVER PULLS STWO'S PROVER (native/stwo_js,
doc/stwo-migration.md section 5.1).

Fleet nodes are run by operators who give us no shell and build native crates with whatever stable `cargo` they have
(/status native.rustc). Stwo's prover needs nightly (`portable_simd`), so a single `prover` feature anywhere in the
verifier's default dependency graph would make the crate unbuildable on every node. This pins: `cargo +stable build
--release --locked` (the pinned lock, Cargo.lock.pinned) succeeds, and `cargo tree` (each package with its enabled features)
enables no `prover` feature on any crate, while the same query with `--features prover` does (the detector can fire).

SKIPS (with a SKIP line) when there is no stable cargo on this machine.

Run: python3 tests/test_stwo_js_verifier_builds_on_stable_without_the_prover.py
"""
import os
import sys
import tempfile

_REAL_HOME = os.path.expanduser("~")          # for the rustup / cargo homes, read BEFORE the throwaway HOME below
_T = tempfile.mkdtemp(prefix="nado-test-stwo-js-stable-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._stwo_js_build import CRATE, Env

import _harness
_report = _harness.Report()
check = _report.check


toml = open(os.path.join(CRATE, "Cargo.toml")).read()
check("the crate has no rust-toolchain file (it would force nightly onto the verifier build)",
      not any(os.path.exists(os.path.join(CRATE, f)) for f in ("rust-toolchain", "rust-toolchain.toml")))
check("`prover` is not a default feature", "default =" not in toml.split("[features]", 1)[-1].split("[", 1)[0], toml)
check("the dependency set is pinned (Cargo.lock.pinned is tracked beside the crate)",
      os.path.exists(os.path.join(CRATE, "Cargo.lock.pinned")))

env = Env(_REAL_HOME)
if not env.have_stable():
    print("SKIP  no stable cargo (`cargo +stable`) on this machine: the stable build cannot be checked here")
    sys.exit(1 if _report.fails else 0)

so, secs, log = env.build_verifier()
print(f"INFO  cargo +stable build --release --locked: {secs:.0f} s")
check("`cargo +stable build --release --locked` builds libnado_stwo_js.so", so is not None, log)

tree, err = env.feature_tree()
check("cargo tree of the default build runs", tree is not None, err)


def with_prover(text):
    """Packages whose enabled-feature list names `prover`."""
    return [l for l in (text or "").splitlines() if "[" in l and "prover" in l.rsplit("[", 1)[1].split("]")[0].split(",")]


hits = with_prover(tree)
check("no crate has its `prover` feature enabled in the default build's graph", tree is not None and not hits, hits[:5])
check("stwo is in that graph with exactly its `std` feature",
      any(l.startswith("stwo v") and l.rstrip(" (*)").endswith("[std]") for l in (tree or "").splitlines()), tree)
ptree, err = env.feature_tree("prover")
check("the detector fires: with --features prover, stwo and the framework are listed with `prover` enabled",
      {l.split()[0] for l in with_prover(ptree)} >= {"stwo", "stwo-constraint-framework"}, err or ptree)

print("ALL PASS — the verifier builds on stable without the prover" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
