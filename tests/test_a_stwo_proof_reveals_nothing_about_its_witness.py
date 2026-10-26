"""A STWO JOIN-SPLIT PROOF REVEALS NOTHING ABOUT ITS WITNESS that can be measured on real proofs at the node config
(ZK review 2026-10-11, rev-zk; doc/stwo/zk-argument.md). The mechanical checks that doc cites (zkproof/zkcheck) were in
a wiped scratch directory; this re-measures the load-bearing ones against native/stwo_js itself:

  1. two proofs of ONE witness under two seeds: every salted root (T1-T3) and every claimed LogUp sum differ, and the
     only equal OODS samples are the 32 public IV columns (the randomness reaches everything else);
  2. the wire bytes of a proof contain no secret of the witness as a byte string (nsk, owner, rho, values, outputs);
  3. opened values (queried T1-T3, OODS samples, FRI witnesses, claimed sums; the public IV columns excluded) equal to
     a secret limb, or below 2^16, occur at their chance rate: a leaked trace row would be mostly 16-bit limbs;
  4. every opened salt is distinct within a proof and across two proofs;
  5. L0: every free-row cell of the original and interaction traces resampled, every constraint still holds;
  6. L2/L3: for every column class, the functionals the verifier sees (lifted openings, in-composition points, OODS
     coordinates) have the same rank on the free rows as on all rows, after the point bookkeeping reproduces the proof's
     own opened and OODS values. This is the per-transcript rank condition the doc leaves open (section 5, "Open").

The probe (tests/_stwo_zk_probe.rs) is built as an extra bin in a TEMP copy of the crate, so the crate and the shipped
WASM's source digest are untouched. SKIPS without the nightly-2026-01-15 toolchain. ~10 min (build + 3 proofs + ranks).

Run: python3 tests/test_a_stwo_proof_reveals_nothing_about_its_witness.py
"""
import os
import sys
import tempfile

_REAL_HOME = os.path.expanduser("~")          # for the rustup / cargo homes, read BEFORE the throwaway HOME below
_T = tempfile.mkdtemp(prefix="nado-test-stwo-zk-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import shutil
import subprocess

from tests._stwo_js_build import Env

HERE = os.path.dirname(os.path.abspath(__file__))
import _harness
_report = _harness.Report()
check = _report.check


env = Env(_REAL_HOME)
nbin = env.nightly_bin()
if not nbin:
    print("SKIP  no nightly-2026-01-15 toolchain (or $NADO_STWO_NIGHTLY_BIN): the prover cannot be built here")
    sys.exit(0)

src = env.source()
shutil.copy(os.path.join(HERE, "_stwo_zk_probe.rs"), os.path.join(src, "src", "bin", "stwo_zk_probe.rs"))
with open(os.path.join(src, "Cargo.toml"), "a") as f:
    f.write('\n[[bin]]\nname = "stwo_zk_probe"\npath = "src/bin/stwo_zk_probe.rs"\nrequired-features = ["prover"]\n')
benv = env.base_env({"CARGO_TARGET_DIR": os.path.join(env.target, "zkprobe"), "RUSTC": os.path.join(nbin, "rustc"),
                     "PATH": nbin + os.pathsep + os.environ.get("PATH", "")})
benv.pop("RUSTUP_TOOLCHAIN", None)
r = subprocess.run([os.path.join(nbin, "cargo"), "build", "--release", "--locked", "--features", "prover",
                    "--bin", "stwo_zk_probe"], cwd=src, capture_output=True, text=True, timeout=3600, env=benv)
exe = os.path.join(env.target, "zkprobe", "release", "stwo_zk_probe")
check("the ZK probe builds", r.returncode == 0 and os.path.exists(exe), r.stderr[-3000:])
if _report.fails:
    sys.exit(1)

# EVERY NODE CONFIG (STWO_JS_128_HEIGHT): the 56-query config draws 3Q + 8 = 176 random rows per component, not 488,
# and its JS and XOR traces are smaller — its zero knowledge is measured here, not inferred from the 160-query one.
for CFG in (0, 1):
    print(f"---- node config {CFG}")
    p = subprocess.run([exe, "1"], capture_output=True, text=True, timeout=3600, env=dict(os.environ, NADO_ZK_CFG=str(CFG)))
    check(f"[cfg {CFG}] the probe runs", p.returncode == 0, p.stderr[-2000:])
    if _report.fails:
        sys.exit(1)
    d = json.loads(p.stdout)

    s = d["seeds"]
    check(f"[cfg {CFG}] two seeds, one witness: every salted root (T1-T3) differs", s["roots_differ"], s)
    check(f"[cfg {CFG}] two seeds, one witness: the preprocessed root is the same (it is the public circuit)", s["preprocessed_same"], s)
    check(f"[cfg {CFG}] two seeds, one witness: every claimed LogUp sum differs", s["claimed_differ"], s)
    check(f"[cfg {CFG}] two seeds, one witness: only the 32 public IV columns' OODS samples coincide", s["sampled_equal"] == 32, s)

    check(f"[cfg {CFG}] the wire bytes carry no secret of the witness", d["wire_hits"] == [], d["wire_hits"])

    for w in d["witness"]:
        check(f"[cfg {CFG}] proof {w['proof']}: opened values equal to a secret limb at chance rate "
              f"({w['secret_hits']} vs {w['secret_hits_expected']:.2f} expected)",
              w["secret_hits"] <= 5 + 4 * w["secret_hits_expected"], w)
        check(f"[cfg {CFG}] proof {w['proof']}: opened values below 2^16 at chance rate ({w['small']} vs {w['small_expected']:.1f})",
              w["small"] <= 3 * w["small_expected"] + 10, w)

    sl = d["salts"]
    check(f"[cfg {CFG}] every opened salt is distinct within a proof", sl["distinct_within"], sl)
    check(f"[cfg {CFG}] no opened salt is shared by two proofs", sl["shared_across"] == 0, sl)

    check(f"[cfg {CFG}] L0: free rows resampled, every constraint of JS, ROUND and XOR still holds (two proofs)",
          all(all(x) for x in d["l0"]), d["l0"])

    check(f"[cfg {CFG}] L2/L3: a rank row for each of the 11 column classes", len(d["rank"]) == 11, len(d["rank"]))
    for c in d["rank"]:
        check(f"[cfg {CFG}] {c['class']}: bookkeeping reproduces the proof's opened and OODS values", c["bookkeeping_ok"], c)
        check(f"[cfg {CFG}] {c['class']}: rank on free rows = rank on all rows ({c['rank_free']} of {c['functionals']} functionals, "
              f"{c['free_rows']} free rows)", c["rank_free"] == c["rank_all"], c)

sys.exit(1 if _report.fails else 0)
