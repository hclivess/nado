"""The BLAKE2s exec root is the exec root at every cursor of generation 29.

protocol.BLAKE_EXEC_HEIGHT (Goldilocks retirement G2; 2^62 on generation 28, 1 on 29, inlined in G9) switched the exec
root to execnode/exec_root_b2.py, L1's exit verifiers to match, and refused the Goldilocks settle proof (option R):
  1. the gate is gone (its DORMANT half, gen 28's rules, retired in G9);
  2. the gen-29 genesis canary: exec_root_b2 over an empty state equals protocol.EXEC_GENESIS_ROOT_B2;
  3. LIVE, as generation 29 runs it: the genesis cursors use the new root too (Goldilocks must
     not survive in the first root); state_root is the BLAKE2s root, follows every mutation, and equals the cold
     computation; an exit proof from the live state verifies on L1's path; a root remembered in the ring still proves
     after the state moves on, and refuses a value the record did not hold;
  4. L1 reads every settled root, at every cursor, with exec_root_b2 (the straddling-window case retired in G9 with the
     Goldilocks branch of exit_root_module);
  5. the settle path: L1 refuses a Goldilocks proof after the cursor's type check, at every cursor, and the settler
     never builds one (source), and no exit verifier is called except through exit_root_module.

Run: python3 tests/test_the_blake2s_exec_root_is_dormant_now_and_whole_from_its_gate.py
"""
import _harness
HOME = _harness.isolate("nado-test-blake-exec-gate-")
import os
import re

import protocol as P
from execnode import exec_root_b2 as R2
from execnode.state import ExecState

T = _harness.Report()
A1, A2 = "ndo" + "a" * 45, "ndo" + "b" * 45


def fresh(name):
    st = ExecState(os.path.join(HOME, name + ".json"))
    st.cursor = 400
    st.contracts = {"c" * 32: {"deployer": A1, "code": {"m": [1]}, "storage": {"slots": {"1": 9, "5": 3}}}}
    st.bridge = {A1: 10**11}
    st.dividend = {A2: 7 * 10**9}
    st.withdrawals = {"w1": {"addr": A1, "amount": 2 * 10**10}}
    st._touch()
    return st


# ---- 1: dormant — retired in G9: generation 28's rules (BLAKE_EXEC_HEIGHT inlined, exec_root_b2.blake_exec_at deleted;
#      the Goldilocks exec-state root and exit_root_module's Goldilocks branch went in slice 2)
from ops import transaction_ops as TX
T.check("1. the gate is gone: no BLAKE_EXEC_HEIGHT in protocol, no blake_exec_at predicate left to disagree",
        not hasattr(P, "BLAKE_EXEC_HEIGHT") and not hasattr(R2, "blake_exec_at"))

# ---- 2: canary
T.check("2. the gen-29 genesis canary matches the empty state's BLAKE2s root",
        R2.state_root_hex({}, ExecState(os.path.join(HOME, "empty.json"))) == P.EXEC_GENESIS_ROOT_B2)

# ---- 3: live, as generation 29 runs it at every cursor (3a, the genesis cursors, is 6c below: a fresh layer at -1)
st = fresh("live")
r0 = st.state_root()
T.check("3b. state_root is the BLAKE2s root and equals the cold computation", r0 == R2.state_root_hex(st.contracts, st))
# (its "and differs from the Goldilocks root" half, and 3g, the old verifier refusing a BLAKE2s proof, went with
# execnode/exec_root.py in G9 slice 4: there is no old root or verifier left to compare against)
pr = st._record_proof(R2.T_BRIDGE_WD, A1, "w1")
T.check("3c. an exit proof from the live state verifies on L1's path",
        TX.exit_root_module(st.cursor).verify_withdrawal(r0, A1, 2 * 10**10, "w1", pr))
st.note_root_point()
with st._mutate_lock:
    st.bridge[A2] = 5
    st.contracts["c" * 32]["storage"]["slots"]["1"] = 10
    st._touch()
r1 = st.state_root()
T.check("3d. the root follows a mutation and still equals the cold computation",
        r1 != r0 and r1 == R2.state_root_hex(st.contracts, st))
got = st.record_proof_at(r0, R2.T_BRIDGE_WD, A1, "w1", value=2 * 10**10)
T.check("3e. a root remembered in the ring still proves after the state moved on",
        got is not None and got[1] == r0 and R2.verify_withdrawal(r0, A1, 2 * 10**10, "w1", got[0]))
T.check("3f. ...and refuses a value the record did not hold under that root",
        st.record_proof_at(r0, R2.T_BRIDGE_WD, A1, "w1", value=3 * 10**10) is None)

# ---- 4: every settled root is BLAKE2s (the straddling-window case retired in G9 with the Goldilocks branch)
T.check("4. L1 reads every settled root with exec_root_b2, whatever the cursor",
        all(TX.exit_root_module(c) is R2 for c in (-1, 0, 99, 100, 10**9)))

# ---- 5: settle proofs and the exit invariant, by source
txs = open(os.path.join(_harness.ROOT, "ops", "transaction_ops.py")).read()
exn = open(os.path.join(_harness.ROOT, "execnode", "execnode.py")).read()
v = txs[txs.index("def _validate_settle("):txs.index("def _validate_bridge(")]
i_type = v.index("Settle exec_cursor must be an int in [0, 2**64-1)")
i_ref = v.find("a BLAKE2s exec root settles by quorum attestation only")
# from G9 the refusal is unconditional — no gate or cursor test guards it — and no proof verifier is left behind it
T.check("5a. L1 refuses a Goldilocks proof after the cursor's type check, at every cursor, with no proof work left",
        i_type < i_ref and "blake_exec_at" not in v and "settle_verify_key" not in txs
        and 'assert data.get("proof") is None and data.get("proof_da") is None' in v)
ms = exn[exn.index("async def maybe_settle("):]
T.check("5b. the settler never builds a Goldilocks proof",
        not re.search(r"(def |await |\b= )_build_settlement_proof\b", exn) and re.search(r"_pend_hold = .*?\n\s*proof = None\n", ms, re.S) is not None)
direct = re.findall(r"\bER\.verify_(?:withdrawal|dividend|unshield|outbox_msg|record)\(", txs)
T.check("5c. no exit verifier is called except through exit_root_module", not direct, direct)
# ---- 6: the genesis canary follows the generation (2026-10-19: the exec node's start-up check and L1's pre-settlement
#         header sentinel both read the alghash constant directly, which on gen 29 would have refused every exec node)
from ops import settlement_ops as SO
# (6a, the dormant canary = the alghash constant, retired in G9: generation 28's rules)
T.check("6b. live: the genesis canary and the header sentinel are the BLAKE2s root",
        R2.genesis_canary() == P.EXEC_GENESIS_ROOT_B2 and SO.settled_header_commitment() == (-1, P.EXEC_GENESIS_ROOT_B2))
T.check("6c. live: a fresh exec layer's root (cursor -1) equals the canary the exec node checks at start",
        ExecState(os.path.join(HOME, "fresh.json")).state_root() == R2.genesis_canary())
readers = []
for d in ("execnode", "ops", "loops"):
    for root_, _dirs, files in os.walk(os.path.join(_harness.ROOT, d)):
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root_, f)
                if path.endswith("exec_root_b2.py"):
                    continue
                import ast                                     # code, not prose: names, attributes and imports
                for node in ast.walk(ast.parse(open(path).read())):
                    hit = (isinstance(node, ast.Name) and node.id == "EXEC_GENESIS_ROOT") or \
                          (isinstance(node, ast.Attribute) and node.attr == "EXEC_GENESIS_ROOT") or \
                          (isinstance(node, ast.ImportFrom) and any(a.name == "EXEC_GENESIS_ROOT" for a in node.names))
                    if hit:
                        readers.append(f"{os.path.relpath(path, _harness.ROOT)}:{node.lineno}")
T.check("6d. nothing but exec_root_b2.genesis_canary reads EXEC_GENESIS_ROOT at runtime", not readers, readers)
T.check("6e. the Goldilocks genesis canary and exec root are gone (G9 slice 4)", not hasattr(P, "EXEC_GENESIS_ROOT")
        and not hasattr(P, "EXEC_TREE_DEPTH") and not os.path.exists(os.path.join(_harness.ROOT, "execnode", "exec_root.py")))
T.done("ALL PASS — the BLAKE2s exec root is the exec root at every cursor")
