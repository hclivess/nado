"""EVERY REWRITE OF AN HONEST STWO JOIN-SPLIT PROOF, AND EVERY CHEATING PROVER WE HAVE, IS REFUSED BY THE NODE VERIFIER
(adversarial soundness review 2026-10-11, before STWO_POOL_HEIGHT is set; native/stwo_js, execnode/stark/stwo_js_native).

The harness tests/stwo_js_attack/stwo_js_attack.rs is built into a TEMP copy of the crate (src/bin/, feature `prover`,
nightly) — never into the checkout — and proves fixture b (an unshield with a fee) at the pinned node config. Then:

  mutate  every prover-supplied field of the proof, one at a time, after proving: each claimed LogUp sum (+1, and a
          shift between two sums that keeps their total — the one the verifier checks), each of the four tree roots,
          the first and last sampled value of each tree, a queried value of each tree (trace and salt), each Merkle
          decommitment (one hash short, one hash long), the proof-of-work nonce, the FRI commitments, witnesses, layer
          count and last-layer polynomial, and every PcsConfig field (queries, pow bits, blowup, lifting size, last
          layer bound, fold step); plus a proof honestly made at a CHEAPER config (1/80/20) and the crate's two
          cheating provers (Cheat::ShiftClaimed, Cheat::ForgeLookup). Every one must be refused (rc != 0).
  struct  structurally inconsistent proofs (a dropped queried column / tree / decommitment, an extra commitment, no FRI
          inner layers, an empty claimed vector, a 2^60 length prefix, a proof over the 16 MiB cap, a max-size proof
          padded with hash witnesses): refused, never accepted, never an abort; the padded one is timed (a DoS bound).
  fuzz    random single-bit flips and truncations of the honest proof: none accepted, the process survives them all.
  dump    an honest proof and one that makes the verifier PANIC, verified through the node's own ctypes binding (the
          STABLE build a node loads): the honest one passes, the panicking one comes back as a refusal and this Python
          process is still alive afterwards (a panic across the FFI would be a node crash).

SKIPS (with a SKIP line) when there is no stable cargo or no nightly-2026-01-15 toolchain on this machine.

Run: python3 tests/test_stwo_js_every_post_proof_mutation_and_cheat_is_refused.py
"""
import os
import sys
import tempfile

_REAL_HOME = os.path.expanduser("~")          # for the rustup / cargo homes, read BEFORE the throwaway HOME below
_T = tempfile.mkdtemp(prefix="nado-test-stwo-js-attack-")
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
if not env.have_stable():
    print("SKIP  no stable cargo (`cargo +stable`) on this machine: the verifier cannot be built here")
    sys.exit(0)
nbin = env.nightly_bin()
if not nbin:
    print("SKIP  no nightly-2026-01-15 toolchain (or $NADO_STWO_NIGHTLY_BIN): the attack harness cannot be built here")
    sys.exit(0)

so, secs, log = env.build_verifier()
check(f"the verifier builds on stable ({secs:.0f} s)", so is not None, log)

# the harness goes into the temp copy only (Env.source() is a mkdtemp copy of native/stwo_js, never the checkout)
src = env.source()
shutil.copy(os.path.join(HERE, "stwo_js_attack", "stwo_js_attack.rs"), os.path.join(src, "src", "bin", "stwo_js_attack.rs"))
benv = env.base_env({"CARGO_TARGET_DIR": os.path.join(env.target, "prover"), "RUSTC": os.path.join(nbin, "rustc"),
                     "PATH": nbin + os.pathsep + os.environ.get("PATH", "")})
benv.pop("RUSTUP_TOOLCHAIN", None)
r = subprocess.run([os.path.join(nbin, "cargo"), "build", "--release", "--locked", "--features", "prover",
                    "--bin", "stwo_js_attack"], cwd=src, capture_output=True, text=True, timeout=1800, env=benv)
exe = os.path.join(env.target, "prover", "release", "stwo_js_attack")
check("the attack harness builds (feature prover, nightly, in a temp copy)", r.returncode == 0 and os.path.exists(exe),
      r.stderr[-3000:])
if not so or r.returncode != 0:
    sys.exit(1)


import protocol as PROTO
os.environ["NADO_STWO_JS_LIB"] = so
from execnode.stark import stwo_js_native as SJ


def cases(cfg, *args):
    p = subprocess.run([exe, *args], capture_output=True, text=True, timeout=1800,
                       env=dict(os.environ, NADO_ATTACK_CFG=str(cfg)))
    check(f"[cfg {cfg}] the harness ({args[0]}) runs to the end without an abort", p.returncode == 0,
          (p.returncode, p.stderr[-1500:]))
    out = {}
    for line in p.stdout.splitlines():
        if line.startswith("CASE "):
            name, _, rest = line[5:].partition(" ")
            out[name] = rest
    return out


# EVERY NODE CONFIG GETS THE WHOLE BATTERY (STWO_JS_128_HEIGHT): the 56-query config is a new verifier input, so its
# mutations, cheats and structural refusals are measured, not assumed from the 160-query one.
for CFG, HEIGHT in ((SJ.CFG_340, 0), (SJ.CFG_128, int(PROTO.STWO_JS_128_HEIGHT))):
    m = cases(CFG, "mutate")
    check(f"[cfg {CFG}] the honest proof verifies (rc=0), so every refusal below is the mutation's", m.get("honest") == "rc=0", m)
    expected = ["claimed0+1", "claimed1+1", "claimed2+1", "claimed0+x,claimed1-x", "claimed0+x,claimed2-x",
                "claimed-extra", "pow+1", "fri-first-commit", "fri-first-witness", "fri-first-witness-push",
                "fri-inner0-witness", "fri-inner-last-pop", "fri-last-poly", "cfg-queries-1", "cfg-pow-0", "cfg-blowup-1",
                "cfg-lift+1", "cfg-lastlayer-1", "cfg-foldstep-2", "cheaper-config", "other-node-config",
                "cheat-ShiftClaimed", "cheat-ForgeLookup"]
    for t in range(4):
        expected += [f"commitment{t}", f"sampled{t}", f"sampled{t}-last", f"queried{t}", f"queried{t}-salt",
                     f"decommit{t}-pop", f"decommit{t}-push"]
    if CFG == SJ.CFG_128:                      # the OODS grind (lib.rs NODE128_OODS_POW_BITS): only this config grinds
        expected += ["oods-nonce+1", "oods-nonce-zero"]
    for name in expected:
        got = m.get(name)
        check(f"[cfg {CFG}] refused: {name}", got is not None and got != "rc=0", got)

    s = cases(CFG, "struct")
    for name in ["queried1-drop-column", "queried1-short-column", "queried-drop-tree", "decommit-drop-tree",
                 "sampled-drop-tree", "commitments-5", "fri-no-inner", "fri-witness-empty", "claimed-empty",
                 "huge-len-prefix", "over-cap"]:
        got = s.get(name)
        check(f"[cfg {CFG}] refused, not crashed on: {name}", got in ("rc=2", "rc=3", "rc=4"), got)
    pad = dict(kv.split("=") for kv in (s.get("max-size-padded") or "rc=0").split())
    check(f"[cfg {CFG}] a max-size (16 MiB) proof padded with hash witnesses is refused within 5 s (no verify-time DoS)",
          pad.get("rc") != "0" and int(pad.get("ms", 10 ** 9)) < 5000, pad)
    ht = dict(kv.split("=") for kv in (s.get("honest-timing") or "rc=1").split())
    print(f"      [cfg {CFG}] honest proof {int(ht.get('bytes', 0)):,} bytes, native verify {ht.get('ms')} ms")

    # THE FREE-CELL PROBE (Cheat::Flip; Zcash Orchard's counterfeiting bug, live 2022-2026, was one unconstrained witness
    # cell): one real-row cell tampered in EVERY original-trace column of JS and ROUND plus the XOR multiplicity column,
    # each proven by a prover that skips its own checks. None may verify. A probe the pipeline cannot even prove
    # (prover-refused / -panicked) is counted, not passed: most must reach the verifier for this to mean anything.
    # The three by-design classes (held-register range pieces probed on row 0, carry helpers probed with +2, ZK blinding
    # excluded by count) are explained in the harness, stwo_js_attack.rs "flip".
    fl = cases(CFG, "flip")
    wd = fl.pop("widths", "")
    ex = dict(kv.split("=") for kv in fl.pop("excluded", "").split())
    probes = {k: v for k, v in fl.items() if k.startswith("flip-")}
    accepted = sorted(k for k, v in probes.items() if v == "rc=0")
    verified = [k for k, v in probes.items() if v in ("rc=2", "rc=3", "rc=4")]
    widths = {k: int(v) for k, v in (x.split("=") for x in wd.split())}
    check(f"[cfg {CFG}] every witness column was probed but the 12 blinding columns ({wd}; {len(probes)} probes)",
          bool(wd) and ex.get("js_blind") == "4" and ex.get("round_blind") == "8" and ex.get("carry_plus2") == "32"
          and len(probes) == widths["js"] + widths["round"] - 12 + 1, (wd, ex, len(probes)))
    check(f"[cfg {CFG}] no tampered witness cell yields an accepted proof (no free cell)", not accepted, accepted)
    check(f"[cfg {CFG}] ...and at least 90 % of the probes reached the verifier and were refused there",
          len(verified) * 10 >= len(probes) * 9,
          (len(verified), len(probes), sorted({v for v in probes.values() if v not in ("rc=2", "rc=3", "rc=4")})[:5]))

    f = cases(CFG, "fuzz", "400")
    fz = f.get("fuzz", "")
    check(f"[cfg {CFG}] no single-bit flip or truncation of an honest proof is accepted (one proof, one encoding)",
          "accepted_mutants=0" in fz, fz)

    out = tempfile.mkdtemp(prefix="nado-stwo-js-attack-dump-", dir=_T)
    d = cases(CFG, "dump", out)
    P = json.load(open(os.path.join(out, "public.json")))
    args = (P["root"], P["nf"], P["cm1"], P["cm2"], P["unshield"], P["fee"], P["dest"], HEIGHT)
    ok, why = SJ.verify(open(os.path.join(out, "honest.bin"), "rb").read(), *args)
    check(f"[cfg {CFG}] through the node's ctypes binding: the honest proof verifies", ok, why)
    ok, why = SJ.verify(open(os.path.join(out, "panic.bin"), "rb").read(), *args)
    check(f"[cfg {CFG}] through the node's ctypes binding: a proof that panics the verifier is a refusal, not a crash",
          not ok and "panicked" in why, (ok, why))
    ok, why = SJ.verify(open(os.path.join(out, "honest.bin"), "rb").read(), *args)
    check(f"[cfg {CFG}] ...and the binding still verifies afterwards (the caller survived the panic)", ok, why)

print("ALL PASS — every post-proof mutation and every cheating prover is refused" if not _report.fails
      else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
