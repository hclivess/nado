"""Contracts run on the 256-bit VM from the exec gate, and on the old VM before it.

The zkvm runtime (execnode/runtimes.py) follows the same predicate as the exec root (exec_root_b2.blake_exec_at;
protocol.BLAKE_EXEC_HEIGHT, dormant on gen 28, the whole of gen 29): from the gate a call runs on zkvm2 with 256-bit
BLAKE2s address digests, deploy is checked by zkvm2's gate, a bare build() targets v2, asset ids follow the new hash,
and call leaves digest args the way the VM received them. Both rule sets:
  1. DORMANT: digests are the old field digests, a bare build() is v1, the deploy gate refuses v2 code, a deployed
     contract runs on zkvm.py, asset_id is the alghash id, a call leaf digests args the old way;
  2. LIVE (gate patched to 1): digests are 256-bit BLAKE2s, a bare build() is v2 and deploys, a call runs on zkvm2 and
     its PAY resolves through the registry to the right address, the caller check of a contract (tictactoe's
     two-player game) works with 256-bit digests, asset_id is zkvm2.hash_words over the v2 digest, a call leaf digests
     args the v2 way, and old v1 code is refused at deploy.

Run: python3 tests/test_contracts_run_on_the_256_bit_vm_from_the_exec_gate.py
"""
import _harness
HOME = _harness.isolate("nado-test-zkvm2-runtime-")
import os

import protocol as P
from execnode import runtimes as RT, zkvm2, zkvmasm
from execnode.games import coinflip, tictactoe
from execnode.state import ExecState, asset_id
from execnode.stark import calls_commit as CC, field as F

T = _harness.Report()
A = "ndo" + "A" * 45
B = "ndo" + "B" * 45


def game(name):
    st = ExecState(os.path.join(HOME, name + ".json")); st.cursor = 100
    code = tictactoe.build()
    r = st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": tictactoe.ABI, "nonce": "n"}, A, "d")
    cid = st.contract_id(A, code, "n")
    for who in (A, B):
        st.credit_deposit(who, 10**6)
    call = lambda who, n, m, args, value=0: st.apply_blob(
        {"op": "call", "contract": cid, "method": m, "args": args, **({"value": value} if value else {})}, who, n)
    return st, cid, code, r, call


# ---- 1: dormant
T.check("1a. dormant: an address digest is the old field digest", RT.zkvm_addr_digest(A) < F.P)
T.check("1b. dormant: a bare build() targets v1", zkvmasm.default_isa() == "v1" and tictactoe.build() == tictactoe.build("v1"))
st, cid, code, r, call = game("dormant")
T.check("1c. dormant: v1 code deploys and a two-player game opens and joins on zkvm.py",
        cid in st.contracts and call(A, "1", "open", [7], 500).endswith("-> ok") and call(B, "2", "join", [7], 500).endswith("-> ok"))
try:
    RT.get("zkvm").validate_code(tictactoe.build("v2")); v1_gate_takes_v2 = True
except Exception:
    v1_gate_takes_v2 = False
T.check("1d. dormant: the deploy gate refuses v2 code", not v1_gate_takes_v2)
T.check("1e. dormant: asset_id is the alghash id (a field element)", asset_id(A, 1) < F.P)
T.check("1f. dormant: a call leaf digests a string arg the old way", CC._arg_field("x") == RT.zkvm_addr_digest("x"))

# ---- 2: live, as generation 29 runs it
P.BLAKE_EXEC_HEIGHT = 1
try:
    d2 = RT.zkvm_addr_digest(A, True)
    T.check("2a. live: an address digest is 256-bit BLAKE2s", d2 < 1 << 256 and RT.zkvm_statement(A, [], v2=True)[0] == d2
            and d2 != RT.zkvm_addr_digest(A))
    T.check("2b. live: a bare build() targets v2", zkvmasm.default_isa() == "v2" and tictactoe.build() == tictactoe.build("v2"))
    st, cid, code, r, call = game("live")
    T.check("2c. live: v2 code deploys", cid in st.contracts and "HR0" not in str(code), r)
    T.check("2d. live: a two-player game opens and joins on zkvm2 (caller checks over 256-bit digests)",
            call(A, "1", "open", [7], 500).endswith("-> ok") and call(B, "2", "join", [7], 500).endswith("-> ok"))
    before = st.bridge.get(B, 0)
    st.cursor = 100 + tictactoe.MOVE_CLOCK + 5
    ab = call(B, "3", "abort", [7])                       # A (to move) stalled: B takes the pot through PAY
    T.check("2e. live: a PAY resolves through the registry to the right address", ab.endswith("-> ok")
            and st.bridge.get(B, 0) == before + 1000, (ab, st.bridge.get(B, 0) - before))
    try:
        st2 = ExecState(os.path.join(HOME, "v1code.json")); st2.cursor = 100
        # a HASHING contract: its v1 code carries the alghash round opcodes (a non-hashing contract's v1 code, e.g.
        # tictactoe's, is a valid v2 program — its macro RANGE guards are v2 instructions too)
        res = st2.apply_blob({"op": "deploy", "runtime": "zkvm", "code": coinflip.build("v1"), "abi": coinflip.ABI,
                              "nonce": "n"}, A, "d")
    except Exception as e:
        res = f"raised {e}"
    T.check("2f. live: old v1 code with alghash rounds is refused at deploy", "skip" in str(res) or "invalid" in str(res) or "raised" in str(res), res)
    T.check("2g. live: asset_id is zkvm2.hash_words over the v2 digest",
            asset_id(A, 1, True) == zkvm2.hash_words([d2, 1]))
    T.check("2h. live: a call leaf digests a string arg the v2 way", CC._arg_field("x", True) == RT.zkvm_addr_digest("x", True))
finally:
    P.BLAKE_EXEC_HEIGHT = 1 << 62
T.done("ALL PASS — contracts run on the 256-bit VM from the exec gate and on the old VM before it")
