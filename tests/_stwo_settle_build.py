"""Builds native/stwo_settle's test binaries (G4) for the tests that drive them, OUTSIDE the checkout.

The tests/_stwo_js_build.py pattern, for the same three reasons:
  * the crate is COPIED (src/, Cargo.toml, Cargo.lock) into a cache dir and built `--locked` there, so a test never
    writes into native/ — this checkout may be the live node, and a cargo run in place can rewrite the tracked
    Cargo.lock (a dirty tree the updater has to move aside);
  * the toolchain is the pinned nightly found under the REAL HOME's rustup (the caller captures it BEFORE assigning a
    throwaway HOME — under the throwaway one, rustup sees no toolchains at all), invoked by its own cargo/rustc
    rather than the rustup proxy: rustup >= 1.28 INSTALLS a missing `+toolchain` on the spot, which on a CI runner or a
    fleet box running scripts/run_tests.sh is a download nobody asked for. A missing toolchain is None and the caller
    prints SKIP;
  * the target dir lives under the real HOME's cache, so reruns are incremental ($NADO_STWO_SETTLE_TEST_TARGET
    overrides it).
$NADO_STWO_NIGHTLY_BIN may name a directory holding the nightly's cargo and rustc instead of a rustup toolchain.
"""
import glob
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRATE = os.path.join(ROOT, "native", "stwo_settle")
NIGHTLY = "nightly-2026-01-15"


def nightly_bin(real_home):
    d = os.environ.get("NADO_STWO_NIGHTLY_BIN")
    if d and os.access(os.path.join(d, "cargo"), os.X_OK):
        return d
    rustup_home = os.environ.get("RUSTUP_HOME") or os.path.join(real_home, ".rustup")
    for d in sorted(glob.glob(os.path.join(rustup_home, "toolchains", NIGHTLY + "-*", "bin"))):
        if os.access(os.path.join(d, "cargo"), os.X_OK):
            return d
    return None


def build(real_home, binary):
    """-> (path to the release binary or None, log). None with an empty log: the toolchain is absent (SKIP); with a
    log: it exists and the build failed (the caller FAILS)."""
    nbin = nightly_bin(real_home)
    if nbin is None:
        return None, ""
    target = os.environ.get("NADO_STWO_SETTLE_TEST_TARGET") or os.path.join(real_home, ".cache", "nado-stwo-settle-target")
    # ONE BUILD AT A TIME PER TARGET: the copy below is a shared directory that each build deletes and refills, so two
    # tests building at once (scripts/run_tests.sh runs tests in parallel) pulled the sources out from under each other
    # (measured 2026-10-27: the VM test's build failed while the span test's ran). Held until this build is done.
    import fcntl
    os.makedirs(target, exist_ok=True)
    with open(os.path.join(target, ".build-lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _build_locked(real_home, nbin, target, binary)


def _build_locked(real_home, nbin, target, binary):
    src = os.path.join(target, "src-copy")
    if os.path.isdir(os.path.join(src, "src")):
        shutil.rmtree(os.path.join(src, "src"))
    os.makedirs(src, exist_ok=True)
    shutil.copytree(os.path.join(CRATE, "src"), os.path.join(src, "src"))
    for f in ("Cargo.toml", "Cargo.lock"):
        shutil.copy(os.path.join(CRATE, f), src)
    env = dict(os.environ, CARGO_TARGET_DIR=target, RUSTC=os.path.join(nbin, "rustc"), CARGO_BUILD_JOBS="4",
               CARGO_HOME=os.environ.get("CARGO_HOME") or os.path.join(real_home, ".cargo"),
               PATH=nbin + os.pathsep + os.environ.get("PATH", ""))
    env.pop("RUSTUP_TOOLCHAIN", None)
    stamped = invalidate_if_changed(src, target, "nado-stwo-settle")
    r = subprocess.run([os.path.join(nbin, "cargo"), "build", "--release", "--locked", "--bin", binary], cwd=src,
                       capture_output=True, text=True, timeout=3600, env=env)
    exe = os.path.join(target, "release", binary)
    if r.returncode != 0 or not os.path.exists(exe):
        return None, r.stderr[-3000:] or "build failed with no output"
    stamped()
    return exe, ""


def invalidate_if_changed(src, target, pkg):
    """CARGO DECIDES "FRESH" FROM THE LAST BUILD'S RECORDED SOURCE PATHS AND THEIR MTIMES, NOT FROM THIS COPY. Every test
    build copies the crate to a new or refreshed directory, and cargo's dep-info for `pkg` still names the previous copy;
    if that copy is still on disk and older than the artifact, cargo links the old library for new sources. Measured
    2026-10-27: a test of the live checkout's stwo_js verifier ran a worktree's newer one. So the sha256 of the copied
    sources is stamped in the target dir; when it differs, `pkg`'s fingerprints are deleted (cargo then rebuilds that one
    crate; its dependencies stay cached). Returns the function that writes the stamp, called after a successful build."""
    import glob
    import hashlib
    h = hashlib.sha256()
    for root, _dirs, names in sorted(os.walk(src)):
        if os.path.relpath(root, src).split(os.sep)[0] == "target":
            continue
        for n in sorted(names):
            p = os.path.join(root, n)
            h.update(os.path.relpath(p, src).encode() + b"\0")
            with open(p, "rb") as f:
                h.update(f.read())
    digest = h.hexdigest()
    stamp = os.path.join(target, ".nado-src-stamp-" + pkg)
    if (open(stamp).read() if os.path.exists(stamp) else None) != digest:
        for fp in glob.glob(os.path.join(target, "**", ".fingerprint", pkg + "-*"), recursive=True):
            shutil.rmtree(fp, ignore_errors=True)
        if os.path.exists(stamp):
            os.remove(stamp)

    def done():
        os.makedirs(target, exist_ok=True)
        with open(stamp, "w") as f:
            f.write(digest)
    return done
