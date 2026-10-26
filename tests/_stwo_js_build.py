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

THE WALLET'S WASM (static/vendor/stwo_js.wasm) is built by `build_wasm` and nothing else — the shipped file must be
byte-identical to it (tests/test_the_shipped_stwo_wasm_is_a_build_of_the_committed_sources.py). The exact command, from a
copy of the crate at a FIXED path with the pinned lock:
    RUSTFLAGS="-C target-feature=+simd128 --remap-path-prefix=<src>=/nado-stwo-js --remap-path-prefix=<CARGO_HOME>=/cargo
               --remap-path-prefix=<rustc --print sysroot>=/rust-toolchain"
    cargo build --release --locked --lib --features prover --target wasm32-unknown-unknown     (nightly-2026-01-15)
The three remaps take the build machine's paths out of the panic-location strings, so two machines build the same bytes.
To refresh the shipped file after a change under native/stwo_js:  python3 tests/_stwo_js_build.py --ship
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

    # ---- the wallet's WASM prover --------------------------------------------------------------------------------
    def wasm_source(self):
        """The crate copied to a FIXED directory under the target root (the path is remapped out of the binary, and a
        fixed one keeps the build incremental: RUSTFLAGS name it). Refreshed from the checkout on every call."""
        d = os.path.join(self.target, "wasm-src")
        if os.path.isdir(os.path.join(d, "src")):
            shutil.rmtree(os.path.join(d, "src"))
        os.makedirs(d, exist_ok=True)
        shutil.copytree(os.path.join(CRATE, "src"), os.path.join(d, "src"))
        shutil.copy(os.path.join(CRATE, "Cargo.toml"), d)
        shutil.copy(os.path.join(CRATE, "Cargo.lock.pinned"), os.path.join(d, "Cargo.lock"))
        return d

    def have_wasm_target(self, nbin):
        sysroot = subprocess.run([os.path.join(nbin, "rustc"), "--print", "sysroot"], capture_output=True, text=True)
        return sysroot.returncode == 0 and os.path.isdir(
            os.path.join(sysroot.stdout.strip(), "lib", "rustlib", "wasm32-unknown-unknown"))

    def build_wasm(self, nbin):
        """The wallet's prover WASM (feature `prover`, nightly, wasm32 + simd128) -> (path or None, seconds, log)."""
        t0 = time.time()
        src = self.wasm_source()
        sysroot = subprocess.run([os.path.join(nbin, "rustc"), "--print", "sysroot"], capture_output=True,
                                 text=True).stdout.strip()
        flags = (f"-C target-feature=+simd128 --remap-path-prefix={src}=/nado-stwo-js "
                 f"--remap-path-prefix={self.cargo_home}=/cargo --remap-path-prefix={sysroot}=/rust-toolchain")
        env = self.base_env({"CARGO_TARGET_DIR": os.path.join(self.target, "wasm"), "RUSTC": os.path.join(nbin, "rustc"),
                             "RUSTFLAGS": flags, "PATH": nbin + os.pathsep + os.environ.get("PATH", "")})
        env.pop("RUSTUP_TOOLCHAIN", None)
        r = subprocess.run([os.path.join(nbin, "cargo"), "build", "--release", "--locked", "--lib", "--features", "prover",
                            "--target", "wasm32-unknown-unknown"], cwd=src, capture_output=True, text=True,
                           timeout=3600, env=env)
        out = os.path.join(self.target, "wasm", "wasm32-unknown-unknown", "release", "nado_stwo_js.wasm")
        return (out if r.returncode == 0 and os.path.exists(out) else None), time.time() - t0, r.stderr[-3000:]


SHIPPED_WASM = os.path.join(ROOT, "static", "vendor", "stwo_js.wasm")


def wasm_sources_digest():
    """sha256 over the inputs of the WASM build (Cargo.toml, the pinned lock, src/ minus the test binary), by relative
    path — pinned beside the shipped file's sha256 so a source change without a re-ship fails without a toolchain."""
    import hashlib
    files = sorted([os.path.join(dp, f) for dp, _d, fn in os.walk(os.path.join(CRATE, "src"))
                    if os.path.relpath(dp, CRATE).split(os.sep)[:2] != ["src", "bin"] for f in fn]
                   + [os.path.join(CRATE, "Cargo.toml"), os.path.join(CRATE, "Cargo.lock.pinned")])
    h = hashlib.sha256()
    for f in files:
        h.update(os.path.relpath(f, CRATE).replace(os.sep, "/").encode() + b"\0" + open(f, "rb").read() + b"\0")
    return h.hexdigest()

_WALLET_PROBE = r"""
import * as S from %s;
import fs from "fs";
import { randomFillSync } from "crypto";
const c = JSON.parse(fs.readFileSync(0, "utf8"));
const core = await S.StwoCore.instantiate(fs.readFileSync(c.wasm));
const rand = (n) => randomFillSync(new Uint8Array(n));
const t0 = performance.now();
const r = await S.proveSpend(c.spend, c.leaves, c.pos, (w, d, cfg) => S.proveWith(core, w, d, rand, cfg));
console.log(JSON.stringify({ bundle: r.bundle, ms: performance.now() - t0 }));
"""


def wallet_prove(spend, leaves, pos, height):
    """One spend proved by the SHIPPED wallet WASM through static/stark/stwo_js.js proveSpend, in Node (no Worker) ->
    {bundle, ms}. spend = {nsk, vIn, rho, v1, o1, r1, v2, o2, r2, unshield, fee, dest}, all strings. ~20 s a proof.
    `height`: the L1 height the spend lands at — it selects the node config the proof is made at, exactly as the wallet's
    stwoCfgId does (protocol STWO_JS_128_HEIGHT), so a test proves at what its own state will verify on either tree."""
    import json
    from execnode.stark.stwo_js_native import config_id_at
    spend = dict(spend, cfg=config_id_at(height))
    probe = _WALLET_PROBE % json.dumps("file://" + os.path.join(ROOT, "static", "stark", "stwo_js.js"))
    case = json.dumps({"wasm": SHIPPED_WASM, "spend": spend, "leaves": leaves, "pos": pos})
    r = subprocess.run(["node", "--input-type=module", "-e", probe], input=case, capture_output=True, text=True,
                       timeout=900)
    if r.returncode != 0:
        raise RuntimeError("wallet prove failed: " + r.stderr[-2000:])
    return json.loads(r.stdout)


if __name__ == "__main__":
    # python3 tests/_stwo_js_build.py --ship : rebuild the wallet WASM and copy it to static/vendor/stwo_js.wasm
    import sys
    if sys.argv[1:] != ["--ship"]:
        print("usage: python3 tests/_stwo_js_build.py --ship"); sys.exit(2)
    e = Env(os.path.expanduser("~"))
    nb = e.nightly_bin()
    if not nb or not e.have_wasm_target(nb):
        print(f"need {NIGHTLY} with the wasm32-unknown-unknown target (or $NADO_STWO_NIGHTLY_BIN)"); sys.exit(1)
    w, secs, log = e.build_wasm(nb)
    if not w:
        print(log); sys.exit(1)
    shutil.copyfile(w, SHIPPED_WASM)
    import hashlib
    print(f"built in {secs:.0f} s -> {SHIPPED_WASM}\n  WASM_SHA256    = \"{hashlib.sha256(open(w, 'rb').read()).hexdigest()}\"\n"
          f"  SOURCES_SHA256 = \"{wasm_sources_digest()}\"\n"
          "pin both in tests/test_the_shipped_stwo_wasm_is_a_build_of_the_committed_sources.py")
