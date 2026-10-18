"""THE STWO JOIN-SPLIT VERIFIER ACCEPTS AN HONEST PROOF AND REFUSES EVERY REWRITE OF ITS PUBLIC INPUTS, through the
node's own binding (execnode/stark/stwo_js_native.py -> native/stwo_js, doc/stwo-migration.md section 5.1).

A proof is made by the crate's own prover (feature `prover`, nightly, built for this test by tests/_stwo_js_build.py,
outside the checkout) at the pinned node config, then verified by the STABLE build of the same crate, the library a node
would load. The soundness negatives are the four the phase-0 prototype ran, now through the wrapper:
  wrong root, fee + 1, a changed unshield destination, and a proof made for different public inputs;
plus the wire-format refusals a node relies on (a trailing byte, a non-canonical field element);
plus THE ZERO-PREPROCESSED FORGERY (review 2026-10-11): a proof whose preprocessed tree (every selector and the xor
table) is all zero, with claimed sums that cancel the public LogUp sum, for public inputs no witness produced (a fresh
nullifier, outputs from nowhere, an unshield of 10^18). It verified before lib.rs pinned NODE_PREPROCESSED_ROOT;
it must be refused, and refused BY the pin.

SKIPS (with a SKIP line) when there is no stable cargo or no nightly-2026-01-15 toolchain on this machine.

Run: python3 tests/test_stwo_js_honest_proof_verifies_and_forged_public_inputs_are_refused.py
"""
import os
import sys
import tempfile

_REAL_HOME = os.path.expanduser("~")          # for the rustup / cargo homes, read BEFORE the throwaway HOME below
_T = tempfile.mkdtemp(prefix="nado-test-stwo-js-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import subprocess

from tests._stwo_js_build import Env

import _harness
_report = _harness.Report()
check = _report.check


env = Env(_REAL_HOME)
if not env.have_stable():
    print("SKIP  no stable cargo (`cargo +stable`) on this machine: the verifier cannot be built here")
    sys.exit(0)
nbin = env.nightly_bin()
if not nbin:
    print("SKIP  no nightly-2026-01-15 toolchain (or $NADO_STWO_NIGHTLY_BIN): the test prover cannot be built here")
    sys.exit(0)

so, secs, log = env.build_verifier()
check(f"the verifier builds on stable ({secs:.0f} s)", so is not None, log)
exe, psecs, plog = env.build_prover(nbin)
check(f"the test prover builds with feature prover on {os.path.basename(os.path.dirname(nbin))} ({psecs:.0f} s)",
      exe is not None, plog)
if not so or not exe:
    sys.exit(1)

os.environ["NADO_STWO_JS_LIB"] = so
from execnode.stark import stwo_js_native as SJ


def prove(fixture, dest):
    out = tempfile.mkdtemp(prefix=f"nado-stwo-js-proof-{fixture}-", dir=_T)
    r = subprocess.run([exe, fixture, dest, out], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]
    return open(os.path.join(out, "proof.bin"), "rb").read(), json.load(open(os.path.join(out, "public.json")))


def run(proof, p, **over):
    a = dict(root=p["root"], nf=p["nf"], cm1=p["cm1"], cm2=p["cm2"], unshield=p["unshield"], fee=p["fee"], dest=p["dest"])
    a.update(over)
    return SJ.verify(proof, **a)


check("the library verifies at the pinned node config 2/160/20", SJ.config() == (2, 160, 20), SJ.config())

DEST = "ndo1-unshield-destination-for-the-test"
pb, P = prove("b", DEST)                       # fixture b: unshield 5000, fee 77
pa, A = prove("a", "")                         # fixture a: a private transfer (unshield 0, fee 0)
check("fixture b is an unshield with a fee (so the fee/destination negatives mean something)",
      P["unshield"] > 0 and P["fee"] > 0, P)

ok, why = run(pb, P)
check("an honest unshield proof verifies through the wrapper", ok and why == "", why)
ok, why = run(pa, A)
check("an honest private-transfer proof verifies through the wrapper", ok and why == "", why)

bad_root = ("00" if P["root"][:2] != "00" else "01") + P["root"][2:]
ok, why = run(pb, P, root=bad_root)
check("a wrong pool root is refused", not ok and why, why)
ok, why = run(pb, P, fee=P["fee"] + 1)
check("fee + 1 is refused", not ok and why, why)
ok, why = run(pb, P, dest=DEST + "x")
check("a changed unshield destination is refused", not ok and why, why)
ok, why = run(pb, P, unshield=P["unshield"] + 1)
check("unshield + 1 is refused", not ok and why, why)
ok, why = run(pb, A)
check("a proof made for different public inputs is refused (proof of b against a's statement)", not ok and why, why)
ok, why = run(pa, P)
check("... and the other way round (proof of a against b's statement)", not ok and why, why)

ok, why = SJ.verify(pb + b"\x00", P["root"], P["nf"], P["cm1"], P["cm2"], P["unshield"], P["fee"], P["dest"])
check("a trailing byte is refused (one proof, one encoding)", not ok and "malformed" in why, why)
# the first claimed LogUp sum's first M31 starts after the 8-byte Vec length: 0xffffffff is >= P, i.e. non-canonical
nc = pb[:8] + b"\xff\xff\xff\xff" + pb[12:]
ok, why = SJ.verify(nc, P["root"], P["nf"], P["cm1"], P["cm2"], P["unshield"], P["fee"], P["dest"])
check("a non-canonical field element is refused", not ok and "NonCanonical" in why, why)
ok, why = SJ.verify(pb[: len(pb) // 2], P["root"], P["nf"], P["cm1"], P["cm2"], P["unshield"], P["fee"], P["dest"])
check("a truncated proof is refused, not crashed on", not ok and why, why)
ok, why = SJ.verify(pb, "zz" * 32, P["nf"], P["cm1"], P["cm2"], P["unshield"], P["fee"], P["dest"])
check("a digest that is not hex is refused by the wrapper", not ok and "root" in why, why)
ok, why = SJ.verify(pb, P["root"], P["nf"], P["cm1"], P["cm2"], P["unshield"], 1 << 64, P["dest"])
check("a fee outside u64 is refused by the wrapper", not ok and "fee" in why, why)

# THE UNSHIELD IS VALUE LEAVING THE POOL (lib.rs conservation invariant, found 2026-10-11): v_in = v1 + v2 + fee + pv.
# The mint witness balances the OLD way (v1 + v2 + fee = v_in + pv) while pv is paid out as an exit — outputs and an exit
# worth pv more than the input. The prover must refuse it, or, forced, produce nothing the verifier accepts.
out = tempfile.mkdtemp(prefix="nado-stwo-js-proof-mint-", dir=_T)
r = subprocess.run([exe, "mint", DEST, out], capture_output=True, text=True, timeout=600)
if r.returncode == 0:
    pm, M = open(os.path.join(out, "proof.bin"), "rb").read(), json.load(open(os.path.join(out, "public.json")))
    ok, why = run(pm, M)
    check("a witness that mints the unshield (old balance) never yields an accepted proof", not ok, (ok, why))
else:
    check("a witness that mints the unshield (old balance) is refused by the prover", r.returncode != 0, r.stderr[-300:])
# THE PREPROCESSED TREE IS PINNED (lib.rs NODE_PREPROCESSED_ROOT): the forgery that switched every gate off
out = tempfile.mkdtemp(prefix="nado-stwo-js-proof-zeropre-", dir=_T)
r = subprocess.run([exe, "zeropre", "attacker-address", out], capture_output=True, text=True, timeout=600)
check("the zero-preprocessed forgery is produced (Cheat::ZeroPre, prover feature only)", r.returncode == 0, r.stderr[-500:])
if r.returncode == 0:
    pz, Z = open(os.path.join(out, "proof.bin"), "rb").read(), json.load(open(os.path.join(out, "public.json")))
    check("...for public inputs no witness produced (unshield 10^18)", Z["unshield"] == 10 ** 18, Z)
    ok, why = run(pz, Z)
    check("a proof over an all-zero preprocessed tree (every gate off) is REFUSED by the node verifier",
          not ok and "preprocessed" in why, (ok, why))
    # its commitments[0] (bincode: claimed Vec 8+3*16, PcsConfig 28, commitments Vec len 8) is not the pinned root
    check("...the forgery's preprocessed root differs from the honest proofs' (the pin is what refuses it)",
          pz[84:92] == (4).to_bytes(8, "little") and pz[92:124] != pb[92:124], pz[84:124].hex())
check("the honest unshield balances on the OUTPUT side: v_in = v1 + v2 + fee + unshield (fixture b verifies)",
      run(pb, P)[0])

print("ALL PASS — the Stwo join-split verifier accepts the honest proof and refuses every rewrite" if not _report.fails
      else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
