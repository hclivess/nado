"""
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
