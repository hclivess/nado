"""
Shared guard for the native accelerators — and, since alphanet-14, the place that makes them MANDATORY.

RUST-ONLY POLICY (project owner's decision, 2026-07-29). Where a Rust variant exists, it is the only
production implementation. A missing or stale .so is a HARD FAILURE at load, not a quiet downgrade to Python.

Why the old behaviour had to go. The fallback was justified as "bit-identical, consensus-safe, just slower",
and each of those words is true in isolation — which is exactly what made it dangerous. A degraded node looks
healthy: it produces correct answers, so nothing fails, and the only symptom is throughput nobody is watching.
This session found /srv/nado-dev silently running pure-Python ML-DSA against a production node on the native
backend. Every signature test in that tree was orders of magnitude slower, four of them "timed out" and looked
like defects, and the heavy-proof timings I was about to write into the release notes were measured under the
handicap without my knowing. Not one of those was a wrong answer; all of them were wrong conclusions.

`require()` therefore refuses to guess. A crate that is meant to be there and is not, or is there and predates
its own sources, stops the process with a message naming the crate and the fix.

WHAT REMAINS PYTHON, deliberately and not as a fallback: only four crates exist
(alghash2, mldsa44, starkcompose, starkprove), covering LDE/composition, hashing/Merkle and ML-DSA. The rest
of the prover — fri, stark, air_ir, recursion*, recursive_verify*, comp_verify, rowcomp_verify,
settlement_sparse — has no Rust counterpart to switch to, so it is not a dual path and there is nothing here
to remove. And the Python kernels that DO mirror a crate stay in the tree as TEST ORACLES: they are what
tests/test_arena_ext_identity.py, tests/test_ext_merkle_native.py and extf._check_inv_agreement() compare the
Rust against. Deleting them would not remove a fallback, it would remove the only evidence the Rust is right.
Production must never reach them; the tests must.

Shared guard against loading a STALE native accelerator .so.

The STARK loaders (alghash2 / starkprove / starkcompose / goldilocks) fall back to pure Python only when their
.so is ABSENT — a PRESENT-but-stale one is loaded and TRUSTED, which silently diverges from consensus (e.g. an
old 8-round alghash2 .so against new 54-round Python). ops/self_update.py rebuilds on /update and purges the
.so if it cannot, but a node advanced by a MANUAL `git pull` (bypassing /update) never rebuilds. This catches
that: git writes changed files with mtime = checkout time, while a gitignored .so keeps its old build mtime, so
`source newer than .so` is exactly `the .so predates the current source`. A stale .so is then treated as if it
were absent → the pure-Python path (bit-identical, consensus-safe, just slower) runs instead.

This is an mtime *staleness* screen, not a correctness proof; alghash2 additionally runs a known-answer interop
self-test at load (the strongest guard, on the crate whose rounds change most). A false "stale" (sources touched
without a rebuild) only costs speed, never correctness.
"""
import os


def is_stale(so_path, crate_dir):
    """True iff any Rust source / manifest under crate_dir is NEWER than the built .so at so_path (⇒ the .so was
    built before the current sources ⇒ do not trust it). A MISSING .so is not 'stale' — the caller's own
    existence check already routes that to the pure-Python fallback."""
    try:
        so_m = os.path.getmtime(so_path)
    except OSError:
        return False
    newest = 0.0
    src = os.path.join(crate_dir, "src")
    try:
        for root, _dirs, files in os.walk(src):
            for f in files:
                if f.endswith(".rs"):
                    try:
                        newest = max(newest, os.path.getmtime(os.path.join(root, f)))
                    except OSError:
                        pass
    except OSError:
        pass
    for extra in ("Cargo.toml", "Cargo.lock"):
        try:
            newest = max(newest, os.path.getmtime(os.path.join(crate_dir, extra)))
        except OSError:
            pass
    return newest > so_m


# The one escape hatch, and it is for BUILDING, not for running. scripts/build_*.sh and the conformance tests
# that compare a Python kernel against its Rust counterpart have to be able to import while the .so is absent
# or mid-rebuild. Nothing in the node sets this; if you find it set on a validator, that is the bug.
_ALLOW_ABSENT = "NADO_ALLOW_PYTHON_KERNELS"


def allow_absent() -> bool:
    return bool(os.environ.get(_ALLOW_ABSENT))


class NativeMissing(RuntimeError):
    """A mandatory Rust accelerator is absent or stale. Raised at load, never swallowed."""


def require(crate: str, so_path, crate_dir, reason: str = ""):
    """Assert that `crate`'s Rust accelerator is present and not older than its sources.

    Raises NativeMissing otherwise. Called by every loader whose crate exists under native/ — so the failure
    surfaces where the cause is (this .so, this crate) rather than as a mysterious slowdown, or worse, as a
    proof that takes six hours because it silently ran in Python.

    A STALE .so is treated exactly as harshly as a missing one, and it is the more dangerous case: a missing
    library announces itself, while a stale one loads and is TRUSTED, so an old kernel gets to answer questions
    about new sources. `git pull` writes source files with the checkout time and leaves the gitignored .so at
    its old build time, which is precisely the state this detects."""
    if allow_absent():
        return False
    if not so_path or not os.path.exists(so_path):
        raise NativeMissing(
            f"native crate '{crate}' is REQUIRED but its library is missing"
            f"{(' (' + reason + ')') if reason else ''}. Build it (scripts/build_pq_native.sh for mldsa44, "
            f"`cargo build --release` in native/{crate} otherwise). There is no Python fallback: since "
            f"alphanet-14 the Rust kernel is the only production implementation, because a silent downgrade "
            f"produces right answers slowly and is therefore invisible until it has already misled you.")
    if is_stale(so_path, crate_dir):
        raise NativeMissing(
            f"native crate '{crate}' library at {so_path} is STALE — its Rust sources are newer than the "
            f"built library, so it was compiled before the code it claims to implement. Rebuild it. This is "
            f"refused rather than downgraded because a stale .so does not announce itself: it loads happily "
            f"and answers with an older kernel.")
    return True
