"""Builds native/stwo_js for the tests/test_stwo_js_*.py tests, OUTSIDE the checkout.

The crate is copied (src/, Cargo.toml, and Cargo.lock.pinned as Cargo.lock) into a temp dir and built `--locked` there,
so a test never writes into native/ (this checkout may be the live node) and always builds the PINNED dependency set,
exactly as ops/self_update._build_crates does. Target dirs live under $NADO_STWO_JS_TEST_TARGET (default: a cache dir
under the real HOME, captured by the caller BEFORE it assigns a throwaway HOME), so reruns are incremental.

Toolchains (resolved from the real HOME's rustup, or RUSTUP_HOME / CARGO_HOME as set when the test started):
  verifier  `cargo +stable`            (what a fleet node has)
  prover    nightly-2026-01-15         (the toolchain Stwo's prover is pinned to; $NADO_STWO_NIGHTLY_BIN may name a
                                        directory holding its cargo and rustc instead of a rustup toolchain)
A missing toolchain is reported as None and the caller prints SKIP; a toolchain that exists but fails to build is a
failure (the caller asserts on the returned log).
"""
import glob
import os
import shutil
import subprocess
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRATE = os.path.join(ROOT, "native", "stwo_js")
NIGHTLY = "nightly-2026-01-15"


class Env:
    def __init__(self, real_home):
        self.real_home = real_home
        self.rustup_home = os.environ.get("RUSTUP_HOME") or os.path.join(real_home, ".rustup")
        self.cargo_home = os.environ.get("CARGO_HOME") or os.path.join(real_home, ".cargo")
        self.target = os.environ.get("NADO_STWO_JS_TEST_TARGET") or os.path.join(real_home, ".cache", "nado-stwo-js-target")
        self.cargo = shutil.which("cargo") or os.path.join(real_home, ".cargo", "bin", "cargo")
        self.src = None

    def base_env(self, extra=None):
        e = dict(os.environ, RUSTUP_HOME=self.rustup_home, CARGO_HOME=self.cargo_home, CARGO_BUILD_JOBS="4")
        e.update(extra or {})
        return e

    def source(self):
        """A temp copy of the crate with the pinned lock in place (made once per Env)."""
        if self.src is None:
            d = tempfile.mkdtemp(prefix="nado-stwo-js-src-")
            shutil.copytree(os.path.join(CRATE, "src"), os.path.join(d, "src"))
            shutil.copy(os.path.join(CRATE, "Cargo.toml"), d)
            shutil.copy(os.path.join(CRATE, "Cargo.lock.pinned"), os.path.join(d, "Cargo.lock"))
            self.src = d
        return self.src

    def have_stable(self):
        if not os.access(self.cargo, os.X_OK):
            return False
        r = subprocess.run([self.cargo, "+stable", "--version"], capture_output=True, text=True, env=self.base_env())
        return r.returncode == 0

    def nightly_bin(self):
        d = os.environ.get("NADO_STWO_NIGHTLY_BIN")
        if d and os.access(os.path.join(d, "cargo"), os.X_OK):
            return d
        for d in sorted(glob.glob(os.path.join(self.rustup_home, "toolchains", NIGHTLY + "-*", "bin"))):
            if os.access(os.path.join(d, "cargo"), os.X_OK):
                return d
        return None

    def build_verifier(self):
        """`cargo +stable build --release --locked` -> (so_path or None, seconds, log)."""
        t0 = time.time()
        r = subprocess.run([self.cargo, "+stable", "build", "--release", "--locked"], cwd=self.source(),
                           capture_output=True, text=True, timeout=1800,
                           env=self.base_env({"CARGO_TARGET_DIR": os.path.join(self.target, "stable")}))
        so = os.path.join(self.target, "stable", "release", "libnado_stwo_js.so")
        return (so if r.returncode == 0 and os.path.exists(so) else None), time.time() - t0, r.stderr[-3000:]

    def feature_tree(self, features=None):
        """Every package of the default build (or with `features`) with its ENABLED features, one per line:
        `cargo +stable tree -e normal -f "{p} [{f}]" --prefix none` -> text, e.g. "stwo v2.2.0 (...) [std]".
        (Plain `cargo tree -e features` draws feature nodes only in its inverted form; this lists them for every
        package, which is the question: is `prover` enabled on anything.)"""
        cmd = [self.cargo, "+stable", "tree", "-e", "normal", "-f", "{p} [{f}]", "--prefix", "none", "--locked"] + \
              (["--features", features] if features else [])
        r = subprocess.run(cmd, cwd=self.source(), capture_output=True, text=True, timeout=600, env=self.base_env())
        return r.stdout if r.returncode == 0 else None, r.stderr[-2000:]

    def build_prover(self, nbin):
        """The test prover binary (feature `prover`, nightly) -> (path or None, seconds, log)."""
        t0 = time.time()
        env = self.base_env({"CARGO_TARGET_DIR": os.path.join(self.target, "prover"), "RUSTC": os.path.join(nbin, "rustc"),
                             "PATH": nbin + os.pathsep + os.environ.get("PATH", "")})
        env.pop("RUSTUP_TOOLCHAIN", None)
        r = subprocess.run([os.path.join(nbin, "cargo"), "build", "--release", "--locked", "--features", "prover",
                            "--bin", "stwo_js_prove"], cwd=self.source(), capture_output=True, text=True,
                           timeout=1800, env=env)
        exe = os.path.join(self.target, "prover", "release", "stwo_js_prove")
        return (exe if r.returncode == 0 and os.path.exists(exe) else None), time.time() - t0, r.stderr[-3000:]
