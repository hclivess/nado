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


import protocol as PROTO
# BOTH NODE CONFIGS (STWO_JS_128_HEIGHT): the whole battery runs at each, at a height that selects it — below the gate
# NODE_CFG_340, from the gate NODE_CFG_128. The gate is 2^62 on generation 28 and 1 on 29; either way these heights
# select the two configs, so the test is the same on both trees.
H340, H128 = 0, int(PROTO.STWO_JS_128_HEIGHT)
assert SJ.config_id_at(H340) == SJ.CFG_340 and SJ.config_id_at(H128) == SJ.CFG_128


def prove(fixture, dest, cfg):
    out = tempfile.mkdtemp(prefix=f"nado-stwo-js-proof-{fixture}-", dir=_T)
    r = subprocess.run([exe, fixture, dest, out, "-", str(cfg)], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]
    return open(os.path.join(out, "proof.bin"), "rb").read(), json.load(open(os.path.join(out, "public.json")))


check("the library's node configs are 2/160/20 and 2/56/20", (SJ.config(SJ.CFG_340), SJ.config(SJ.CFG_128)) ==
      ((2, 160, 20), (2, 56, 20)), (SJ.config(SJ.CFG_340), SJ.config(SJ.CFG_128)))
DEST = "ndo1-unshield-destination-for-the-test"
honest = {}
for CFG, HEIGHT, TAG in ((SJ.CFG_340, H340, "340"), (SJ.CFG_128, H128, "128")):
    print(f"---- node config {TAG} (height {HEIGHT})")

    def run(proof, p, **over):
        a = dict(root=p["root"], nf=p["nf"], cm1=p["cm1"], cm2=p["cm2"], unshield=p["unshield"], fee=p["fee"],
                 dest=p["dest"], height=HEIGHT)
        a.update(over)
        return SJ.verify(proof, **a)

    pb, P = prove("b", DEST, CFG)                  # fixture b: unshield 5000, fee 77
    pa, A = prove("a", "", CFG)                    # fixture a: a private transfer (unshield 0, fee 0)
    honest[TAG] = (pb, P)
    check(f"[{TAG}] fixture b is an unshield with a fee (so the fee/destination negatives mean something)",
          P["unshield"] > 0 and P["fee"] > 0, P)

    ok, why = run(pb, P)
    check(f"[{TAG}] an honest unshield proof verifies through the wrapper", ok and why == "", why)
    ok, why = run(pa, A)
    check(f"[{TAG}] an honest private-transfer proof verifies through the wrapper", ok and why == "", why)

    bad_root = ("00" if P["root"][:2] != "00" else "01") + P["root"][2:]
    ok, why = run(pb, P, root=bad_root)
    check(f"[{TAG}] a wrong pool root is refused", not ok and why, why)
    ok, why = run(pb, P, fee=P["fee"] + 1)
    check(f"[{TAG}] fee + 1 is refused", not ok and why, why)
    ok, why = run(pb, P, dest=DEST + "x")
    check(f"[{TAG}] a changed unshield destination is refused", not ok and why, why)
    ok, why = run(pb, P, unshield=P["unshield"] + 1)
    check(f"[{TAG}] unshield + 1 is refused", not ok and why, why)
    ok, why = run(pb, A)
    check(f"[{TAG}] a proof made for different public inputs is refused (proof of b against a's statement)", not ok and why, why)
    ok, why = run(pa, P)
    check(f"[{TAG}] ... and the other way round (proof of a against b's statement)", not ok and why, why)

    ok, why = run(pb + b"\x00", P)
    check(f"[{TAG}] a trailing byte is refused (one proof, one encoding)", not ok and "malformed" in why, why)
    # the first claimed LogUp sum's first M31 starts after the 8-byte Vec length: 0xffffffff is >= P, i.e. non-canonical
    nc = pb[:8] + b"\xff\xff\xff\xff" + pb[12:]
    ok, why = run(nc, P)
    check(f"[{TAG}] a non-canonical field element is refused", not ok and "NonCanonical" in why, why)
    ok, why = run(pb[: len(pb) // 2], P)
    check(f"[{TAG}] a truncated proof is refused, not crashed on", not ok and why, why)
    ok, why = run(pb, P, root="zz" * 32)
    check(f"[{TAG}] a digest that is not hex is refused by the wrapper", not ok and "root" in why, why)
    ok, why = run(pb, P, fee=1 << 64)
    check(f"[{TAG}] a fee outside u64 is refused by the wrapper", not ok and "fee" in why, why)

    # THE UNSHIELD IS VALUE LEAVING THE POOL (lib.rs conservation invariant, found 2026-10-11): v_in = v1 + v2 + fee + pv.
    # The mint witness balances the OLD way (v1 + v2 + fee = v_in + pv) while pv is paid out as an exit — outputs and an
    # exit worth pv more than the input. The prover must refuse it, or, forced, produce nothing the verifier accepts.
    out = tempfile.mkdtemp(prefix="nado-stwo-js-proof-mint-", dir=_T)
    r = subprocess.run([exe, "mint", DEST, out, "-", str(CFG)], capture_output=True, text=True, timeout=600)
    if r.returncode == 0:
        pm, M = open(os.path.join(out, "proof.bin"), "rb").read(), json.load(open(os.path.join(out, "public.json")))
        ok, why = run(pm, M)
        check(f"[{TAG}] a witness that mints the unshield (old balance) never yields an accepted proof", not ok, (ok, why))
    else:
        check(f"[{TAG}] a witness that mints the unshield (old balance) is refused by the prover", r.returncode != 0,
              r.stderr[-300:])
    # THE PREPROCESSED TREE IS PINNED (lib.rs NODE_CFGS roots): the forgery that switched every gate off
    out = tempfile.mkdtemp(prefix="nado-stwo-js-proof-zeropre-", dir=_T)
    r = subprocess.run([exe, "zeropre", "attacker-address", out, "-", str(CFG)], capture_output=True, text=True, timeout=600)
    check(f"[{TAG}] the zero-preprocessed forgery is produced (Cheat::ZeroPre, prover feature only)", r.returncode == 0,
          r.stderr[-500:])
    if r.returncode == 0:
        pz, Z = open(os.path.join(out, "proof.bin"), "rb").read(), json.load(open(os.path.join(out, "public.json")))
        check(f"[{TAG}] ...for public inputs no witness produced (unshield 10^18)", Z["unshield"] == 10 ** 18, Z)
        ok, why = run(pz, Z)
        check(f"[{TAG}] a proof over an all-zero preprocessed tree (every gate off) is REFUSED by the node verifier",
              not ok and "preprocessed" in why, (ok, why))
        # its commitments[0] (bincode: claimed Vec 8+3*16, PcsConfig 28, commitments Vec len 8) is not the pinned root
        check(f"[{TAG}] ...the forgery's preprocessed root differs from the honest proofs' (the pin is what refuses it)",
              pz[84:92] == (4).to_bytes(8, "little") and pz[92:124] != pb[92:124], pz[84:124].hex())
    check(f"[{TAG}] the honest unshield balances on the OUTPUT side: v_in = v1 + v2 + fee + unshield (fixture b verifies)",
          run(pb, P)[0])

# THE HEIGHT CHOOSES THE CONFIG, NEVER THE PROVER: an honest proof at the other node config is refused
(p340, Q340), (p128, Q128) = honest["340"], honest["128"]
ok, why = SJ.verify(p340, Q340["root"], Q340["nf"], Q340["cm1"], Q340["cm2"], Q340["unshield"], Q340["fee"], Q340["dest"],
                    height=H128)
check("an honest 340-bit proof is REFUSED at a height where the 128-bit config is required", not ok and "config" in why,
      (ok, why))
ok, why = SJ.verify(p128, Q128["root"], Q128["nf"], Q128["cm1"], Q128["cm2"], Q128["unshield"], Q128["fee"], Q128["dest"],
                    height=H340)
check("an honest 128-bit proof is REFUSED below the gate (no prover may pick the cheaper config early)",
      not ok and "config" in why, (ok, why))
try:
    SJ.verify(p128, Q128["root"], Q128["nf"], Q128["cm1"], Q128["cm2"], Q128["unshield"], Q128["fee"], Q128["dest"])
    check("verify without a height is a caller error, never a verdict", False)
except TypeError:
    check("verify without a height is a caller error, never a verdict", True)
# THE OODS GRIND (lib.rs NODE128_OODS_POW_BITS, 16 bits; upstream starkware-libs/proving f0bf0195): the 128-bit proof
# carries its 8-byte nonce after the bincode pair, the 340-bit proof carries nothing (the live format, byte-identical).
args128 = (Q128["root"], Q128["nf"], Q128["cm1"], Q128["cm2"], Q128["unshield"], Q128["fee"], Q128["dest"])
nonce = int.from_bytes(p128[-8:], "little")
bad = p128[:-8] + ((nonce + 1) % (1 << 64)).to_bytes(8, "little")
ok, why = SJ.verify(bad, *args128, height=H128)
check("a 128-bit proof whose OODS nonce does not meet the 16 bits is refused (before the OODS point is drawn)",
      not ok and "OODS" in why, (ok, why))
ok, why = SJ.verify(p128[:-8], *args128, height=H128)
check("...and one without its nonce is refused as malformed (one proof, one encoding)", not ok and "nonce" in why, (ok, why))
ok, why = SJ.verify(p340 + b"\x00" * 8, Q340["root"], Q340["nf"], Q340["cm1"], Q340["cm2"], Q340["unshield"], Q340["fee"],
                    Q340["dest"], height=H340)
check("a 340-bit proof with 8 bytes appended is refused: the live format carries no nonce", not ok and "trailing" in why,
      (ok, why))

# THE POINT OF THE CHANGE, MEASURED: the 128-bit proof is smaller (doc/stwo/phase0-results.md has the numbers)
check(f"the 128-bit proof is at most half the 340-bit one ({len(p128):,} vs {len(p340):,} bytes)",
      len(p128) * 2 <= len(p340), (len(p128), len(p340)))

print("ALL PASS — the Stwo join-split verifier accepts the honest proof and refuses every rewrite" if not _report.fails
      else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
