"""THE STWO JOIN-SPLIT'S PREPROCESSED ROOT IS A PINNED CONSTANT, AND IT IS THE ROOT THE COLUMN BUILDERS PRODUCE.

lib.rs verify_js refuses any proof whose preprocessed commitment (commitments[0]: the js_*/rd_*/xs_* selectors and the
xor lookup table) is not NODE_PREPROCESSED_ROOT — before the pin, a prover chose that tree, committed it all zero, and
a proof for any public inputs verified (review 2026-10-11; the forgery itself is refused in
tests/test_stwo_js_honest_proof_verifies_and_forged_public_inputs_are_refused.py). The pin is only right while it is
the root of the columns the prover really commits, so this pins three things:
  1. the root recomputed from the column builders (prover.rs preprocessed_root over preprocessed_columns, the same
     builders prove_js commits) equals the constant in lib.rs — a selector or table change cannot drift from the pin;
  2. it is a function of the config alone: two recomputations agree (no salt, no randomness, no witness);
  3. an honest proof carries exactly that root in commitments[0] (and verifies, so the pin is not refusing honesty).

SKIPS (with a SKIP line) when there is no stable cargo or no nightly-2026-01-15 toolchain on this machine.

Run: python3 tests/test_stwo_js_preprocessed_root_is_pinned_and_recomputed_from_the_column_builders.py
"""
import os
import sys
import tempfile

_REAL_HOME = os.path.expanduser("~")          # for the rustup / cargo homes, read BEFORE the throwaway HOME below
_T = tempfile.mkdtemp(prefix="nado-test-stwo-js-preroot-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, _T, ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import re
import subprocess

from tests._stwo_js_build import Env, CRATE

import _harness
_report = _harness.Report()
check = _report.check


def pinned_root():
    src = open(os.path.join(CRATE, "src", "lib.rs")).read()
    m = re.search(r"pub const NODE_PREPROCESSED_ROOT: \[u8; 32\] = \[([^\]]*)\];", src)
    assert m, "lib.rs declares NODE_PREPROCESSED_ROOT"
    b = bytes(int(x, 16) for x in re.findall(r"0x([0-9a-fA-F]{2})", m.group(1)))
    assert len(b) == 32, "the pin is 32 bytes"
    return b.hex()


pin = pinned_root()
check("lib.rs pins a 32-byte preprocessed root that is not a placeholder", pin != "00" * 32, pin)

env = Env(_REAL_HOME)
if not env.have_stable():
    print("SKIP  no stable cargo (`cargo +stable`) on this machine: the verifier cannot be built here")
    sys.exit(1 if _report.fails else 0)
nbin = env.nightly_bin()
if not nbin:
    print("SKIP  no nightly-2026-01-15 toolchain (or $NADO_STWO_NIGHTLY_BIN): the column builders cannot be run here")
    sys.exit(1 if _report.fails else 0)

exe, psecs, plog = env.build_prover(nbin)
check(f"the test prover builds ({psecs:.0f} s)", exe is not None, plog)
so, secs, log = env.build_verifier()
check(f"the verifier builds on stable ({secs:.0f} s)", so is not None, log)
if not exe or not so:
    sys.exit(1)

r1 = subprocess.run([exe, "preroot"], capture_output=True, text=True, timeout=600)
r2 = subprocess.run([exe, "preroot"], capture_output=True, text=True, timeout=600)
got = r1.stdout.strip()
check("1. the root recomputed from the column builders equals the lib.rs pin", r1.returncode == 0 and got == pin,
      f"recomputed {got!r} vs pinned {pin} {r1.stderr[-300:]}")
check("2. ...and it is a constant of the config (two recomputations agree)", r2.stdout.strip() == got, r2.stdout)

out = tempfile.mkdtemp(prefix="nado-stwo-js-proof-a-", dir=_T)
r = subprocess.run([exe, "a", "", out], capture_output=True, text=True, timeout=600)
check("an honest proof is made", r.returncode == 0, r.stderr[-500:])
if r.returncode == 0:
    pa = open(os.path.join(out, "proof.bin"), "rb").read()
    A = json.load(open(os.path.join(out, "public.json")))
    # bincode: claimed Vec (8 + 3 x 16), PcsConfig (28), commitments Vec length (8), then commitments[0]
    check("3. an honest proof's commitments[0] IS the pinned root",
          pa[84:92] == (4).to_bytes(8, "little") and pa[92:124].hex() == pin, pa[84:124].hex())
    os.environ["NADO_STWO_JS_LIB"] = so
    from execnode.stark import stwo_js_native as SJ
    ok, why = SJ.verify(pa, A["root"], A["nf"], A["cm1"], A["cm2"], A["unshield"], A["fee"], A["dest"])
    check("...and verifies under the pin", ok, why)

print("ALL PASS — the preprocessed root is pinned, recomputed from the builders, and carried by honest proofs"
      if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
