"""The settlement VM verifier builds on stable Rust without Stwo's prover, and a node verifies through it.

A node builds native/stwo_settle the way ops/self_update builds every crate: stable cargo, default features. Until
2026-10-27 the crate was nightly-only, because its verifier recomputed a per-statement preprocessed commitment with the
prover's machinery. The statement's table is now public LogUp terms whose multiplicities the proof states and the
transcript fixes, and the remaining preprocessed columns are constant, with their root pinned (vm_air::PREPROCESSED_ROOT).
Checked:
  1. the library builds on STABLE with default features, and no package in that build has Stwo's `prover` feature on;
  2. the pinned preprocessed root is the one the prover recomputes (vm_prove VM_PREROOT);
  3. through the node's binding (execnode/stwo_settle_native.py, ctypes into ffi.rs): an honest proof of real
     tictactoe calls verifies; a changed io value, a changed step count, a proof of other calls, corrupted and garbage
     proof bytes are refused, never crash; an unparsable statement is a caller error, not a verdict;
  4. execnode/settle_b2.verify_span, given NO prover binary, verifies a real span through that library and lands on the
     exec node's root.

Needs the stable toolchain (and nightly, for the prover that makes the proofs); skips with the reason otherwise.
Run: python3 tests/test_the_stwo_settle_verifier_builds_on_stable_without_the_prover.py
"""
import os
_REAL_HOME = os.path.expanduser("~")      # BEFORE isolate: the toolchains live under the real HOME
import _harness
HOME = _harness.isolate("nado-test-stwo-settle-stable-")
os.environ["NADO_EXEC_STATE"] = os.path.join(HOME, "exec_state")
os.environ["NADO_EXEC_DA"] = os.path.join(HOME, "exec_da")
import re
import subprocess

from tests._stwo_settle_build import CRATE, NIGHTLY, build, build_verifier, stable_bin

T = _harness.Report()

so, log = build_verifier(_REAL_HOME)
if so is None and not log:
    print("SKIP  no stable toolchain: the node's build of native/stwo_settle cannot be checked here")
    T.done("SKIPPED (no toolchain)")
T.check("1a. the verifier library builds on stable Rust with default features", so is not None, log)
if so is None:
    T.done()
sbin = stable_bin(_REAL_HOME)
src = os.path.join(os.path.dirname(os.path.dirname(so)), "src-copy")
tree = subprocess.run([os.path.join(sbin, "cargo"), "tree", "-e", "normal", "-f", "{p} [{f}]", "--prefix", "none",
                       "--locked"], cwd=src, capture_output=True, text=True, timeout=600,
                      env=dict(os.environ, RUSTC=os.path.join(sbin, "rustc"), PATH=sbin + os.pathsep + os.environ["PATH"],
                               CARGO_HOME=os.path.join(_REAL_HOME, ".cargo"),
                               CARGO_TARGET_DIR=os.path.dirname(os.path.dirname(so))))
with_prover = [l for l in tree.stdout.splitlines() if re.search(r"\[[^\]]*\bprover\b", l)]
T.check("1b. no package in the node's build has Stwo's `prover` feature on", tree.returncode == 0 and not with_prover,
        (with_prover[:5], tree.stderr[-500:]))

PROVE, plog = build(_REAL_HOME, "vm_prove")
SETTLE, slog = build(_REAL_HOME, "vm_settle")
if PROVE is None or SETTLE is None:
    if not (plog or slog):
        print(f"SKIP  no {NIGHTLY} toolchain: no prover to make the proofs the stable verifier checks")
        T.done("SKIPPED (no prover toolchain)")
    T.check("the prover builds", False, plog or slog)
    T.done()

pin = re.search(r"PREPROCESSED_ROOT: .*?Blake2sHash\(\[\s*([^\]]+)\]", open(os.path.join(CRATE, "src", "blake", "vm_air.rs")).read(), re.S)
pinned = "".join("%02x" % int(x, 16) for x in pin.group(1).replace(",", " ").split()) if pin else None
r = subprocess.run([PROVE], input="", capture_output=True, text=True, env=dict(os.environ, VM_PREROOT="1"), timeout=600)
T.check("2. the pinned preprocessed root is the one the prover recomputes", pinned and f"PREROOT {pinned}" in r.stdout,
        (pinned, r.stdout[-200:], r.stderr[-300:]))

# ---- 3: through the node's binding ------------------------------------------------------------------------------------
os.environ["NADO_STWO_SETTLE_LIB"] = so
from execnode import settle_b2 as S  # noqa: E402
from execnode.games import tictactoe  # noqa: E402
from execnode import stwo_settle_native as N  # noqa: E402
from execnode.state import ExecState  # noqa: E402
from execnode import block_apply  # noqa: E402

A, B = "ndo" + "A" * 45, "ndo" + "B" * 45
st = ExecState(os.path.join(HOME, "st.json"))
st.cursor = 3000
code = tictactoe.build()


def apply(blocks, s):
    for b in blocks:
        # (no stark.rules_at: the Goldilocks proof rules went with execnode/stark in G9 slice 4)
        block_apply.begin({"default": s}, b["block_number"])
        block_apply.dispatch({"default": s}, s, b, {}, set(), verbose=False)
        block_apply.close({"default": s}, b["block_number"], b["block_hash"])


blob = lambda who, n, p: {"recipient": "blob", "sender": who, "txid": n, "data": p}  # noqa: E731
apply([{"block_number": 3001, "block_hash": "%064x" % 1, "block_transactions": [
    blob(A, "d", {"op": "deploy", "runtime": "zkvm", "code": code, "nonce": "n"}),
    {"recipient": "bridge", "sender": A, "amount": 10**6}, {"recipient": "bridge", "sender": B, "amount": 10**6}]}], st)
cid = st.contract_id(A, code, "n")
call = lambda who, n, m, args, value=0: blob(who, n, {"op": "call", "contract": cid, "method": m, "args": args,  # noqa: E731
                                                      **({"value": value} if value else {})})
pre = st.clone()
span = [{"block_number": 3002, "block_hash": "%064x" % 2, "block_transactions": [
    call(A, "c1", "open", [4], 50), call(B, "c2", "join", [4], 50), call(A, "c3", "move", [4, 0, 0])]}]
chain = S.reference_chain(pre, span, lambda E: (0, {}))
bundle = S.prove_span(pre, span, chain, SETTLE)
store = S._verifier_store(bundle)
_st, oracle = S._replay(store, span, pre.cursor, chain, bundle["runs"])
text = S.vm_statement_text(oracle.calls)
proof = bytes.fromhex(bundle["vm_proof"])
ok, why = N.verify(text, proof)
T.check("3a. an honest proof of 3 real tictactoe calls verifies through the stable library", ok, why)


def refused(name, t, p):
    try:
        ok, why = N.verify(t, p)
    except ValueError as e:
        ok, why = None, f"ValueError {e}"
    T.check(f"3b. refused: {name}", ok is False, why)


first_io = next(l for l in text.splitlines() if l.startswith("IO "))
k, a, b = first_io.split()[1:]
refused("an io value changed", text.replace(first_io, f"IO {k} {a} {int(b, 16) ^ 1:064x}", 1), proof)
call_line = next(l for l in text.splitlines() if l.startswith("CALL "))
refused("a step count changed", text.replace(call_line, f"CALL {call_line.split()[1]} {int(call_line.split()[2]) + 1}", 1), proof)
span1 = [{**span[0], "block_transactions": span[0]["block_transactions"][:1]}]            # the first call alone
other = S.prove_span(pre, span1, S.reference_chain(pre, span1, lambda E: (0, {})), SETTLE)
refused("a proof of other calls", text, bytes.fromhex(other["vm_proof"]))
bad = bytearray(proof)
bad[len(bad) // 2] ^= 0x40
refused("corrupted proof bytes", text, bytes(bad))
refused("garbage proof bytes", text, os.urandom(4096))
refused("an empty proof", text, b"")
try:
    N.verify("WHAT is this\n", proof)
    caller = False
except ValueError:
    caller = True
T.check("3c. an unparsable statement is a caller error (ValueError), not a verdict", caller)

# ---- 4: settle_b2 with no prover binary: the node's path -----------------------------------------------------------------
real = pre.clone()
apply(span, real)
ok, why, post = S.verify_span(pre.cursor, pre.state_root(), span, chain, bundle)
T.check("4. settle_b2.verify_span with no prover binary verifies the span through the stable library, on the exec "
        "node's root", ok and post == real.state_root(), why)
T.done("ALL PASS — the node verifies settlement VM proofs on stable Rust, and refuses forgeries")
