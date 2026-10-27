"""Contracts run on the 256-bit VM at every height of generation 29.

The zkvm runtime (execnode/runtimes.py) runs every call on zkvm2 with 256-bit BLAKE2s address digests, deploy is checked
by zkvm2's gate, a bare build() targets v2, asset ids follow the new hash, and call leaves digest args the way the VM
received them (protocol.BLAKE_EXEC_HEIGHT, 1 from gen 29, inlined in G9):
  1. (generation 28's VM, run under its dormant gate, retired in G9)
  2. LIVE: digests are 256-bit BLAKE2s (the formula itself, pinned), the assembler has one ISA and build() deploys, a
     call runs on zkvm2 and its PAY resolves through the registry to the right address, the caller check of a contract
     (tictactoe's two-player game) works with 256-bit digests, asset_id is zkvm2.hash_words over the digest, a call leaf
     digests args the way the VM receives them, and field-VM code (an alghash round opcode) is refused at deploy.
  (G9 slice 3b deleted the field VM, its ISA, the field digest and every `v2=` / `isa=` switch: the checks that compared
  against the v1 forms now pin the one form directly.)

Run: python3 tests/test_contracts_run_on_the_256_bit_vm_from_the_exec_gate.py
"""
import _harness
HOME = _harness.isolate("nado-test-zkvm2-runtime-")
import os

import hashlib
import inspect

from execnode import runtimes as RT, zkvm2, zkvmasm
from execnode.games import tictactoe
from hashing import canonical_bytes
from execnode.state import ExecState, asset_id
from execnode.stark import calls_commit as CC

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


# ---- 1: dormant — generation 28's VM — retired in G9: generation 28's rules (BLAKE_EXEC_HEIGHT inlined; a deployed
# contract can no longer reach zkvm.py, and a bare build() is v2 on every height)

# ---- 2: live, as generation 29 runs it at every height
d2 = RT.zkvm_addr_digest(A)
want = int.from_bytes(hashlib.blake2s(canonical_bytes(["zkvmaddr", A]), digest_size=32, person=b"NADOvmA1").digest(), "big")
T.check("2a. live: an address digest is the 256-bit BLAKE2s one, and the statement uses it", d2 == want
        and RT.zkvm_statement(A, [])[0] == d2 and RT.zkvm_statement(A, ["x"])[1] == [RT.zkvm_addr_digest("x")])
T.check("2b. live: the assembler has one ISA (no isa switch left to pick the field VM's)",
        not hasattr(zkvmasm, "default_isa") and not hasattr(zkvmasm, "ISAS")
        and list(inspect.signature(zkvmasm.assemble_contract).parameters) == ["methods"]
        and list(inspect.signature(tictactoe.build).parameters) == [])
st, cid, code, r, call = game("live")
T.check("2c. live: the built code deploys", cid in st.contracts and "HR0" not in str(code), r)
T.check("2d. live: a two-player game opens and joins on zkvm2 (caller checks over 256-bit digests)",
        call(A, "1", "open", [7], 500).endswith("-> ok") and call(B, "2", "join", [7], 500).endswith("-> ok"))
before = st.bridge.get(B, 0)
st.cursor = 100 + tictactoe.MOVE_CLOCK + 5
ab = call(B, "3", "abort", [7])                       # A (to move) stalled: B takes the pot through PAY
T.check("2e. live: a PAY resolves through the registry to the right address", ab.endswith("-> ok")
        and st.bridge.get(B, 0) == before + 1000, (ab, st.bridge.get(B, 0) - before))
try:
    st2 = ExecState(os.path.join(HOME, "v1code.json")); st2.cursor = 100
    # the shape the field VM's `hash r2 <- r1` assembled to: HABS followed by an alghash round opcode (HR0..HR26)
    v1 = {"m": [["HINIT", 0, 0, 0], ["HABS", 0, 1, 0], ["HR0", 0, 0, 0], ["HOUT", 2, 0, 0], ["RET", 0, 2, 0]]}
    res = st2.apply_blob({"op": "deploy", "runtime": "zkvm", "code": v1, "nonce": "n"}, A, "d")
except Exception as e:
    res = f"raised {e}"
T.check("2f. live: field-VM code with alghash rounds is refused at deploy", "skip" in str(res) or "invalid" in str(res) or "raised" in str(res), res)
T.check("2g. live: asset_id is zkvm2.hash_words over the digest", asset_id(A, 1) == zkvm2.hash_words([d2, 1]))
T.check("2h. live: a call leaf digests a string arg as the VM receives it", CC._arg_field("x") == RT.zkvm_addr_digest("x")
        and CC.call_leaf({"cid": "c", "method": "m", "args": ["x"], "cursor": 0})
        == CC.call_leaf({"cid": "c", "method": "m", "args": [RT.zkvm_addr_digest("x")], "cursor": 0}))
T.done("ALL PASS — contracts run on the 256-bit VM at every height")
