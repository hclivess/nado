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
    r = subprocess.run([os.path.join(nbin, "cargo"), "build", "--release", "--locked", "--bin", binary], cwd=src,
                       capture_output=True, text=True, timeout=3600, env=env)
    exe = os.path.join(target, "release", binary)
    if r.returncode != 0 or not os.path.exists(exe):
        return None, r.stderr[-3000:] or "build failed with no output"
    return exe, ""
