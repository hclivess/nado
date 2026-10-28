"""AN EXEC NODE PROVES ITS SETTLE SPAN FROM THE GATE, AND SETTLES BARE OTHERWISE (G8; execnode/execnode._stwo_settle_bundle,
wired into maybe_settle).

From protocol.STWO_SETTLE_HEIGHT the exec node proves the span from L1's JUSTIFIED settled tip to its newest unattested
epoch boundary, from the stash AT that tip, and publishes the bundle to its DA store; the settle then carries the
commitment as `stwo`. Anything that would make the proof impossible must cost the settle its proof, never the settle:
  1. below the gate (the shipped value) nothing is asked of L1 and nothing is proven: the settle goes bare, as today;
  2. from the gate, a span with contract calls proves with the vm_settle prover; the published bundle is exactly what the
     L1 side verifies (settle_b2.verify_span on the exec node's own chain inputs lands on the boundary root), and the
     publish hold is raised so no bare settle can walk the tip past the span while it is submitted;
  3. a node WITHOUT the prover still proves a span with no contract call (no VM proof is needed), and settles a span with
     calls bare — it never stalls; the in-flight flag is released when the prove thread ends;
  4. it settles bare when it cannot prove honestly: the boundary is already attested (L1 takes one settle per validator
     and cursor), no stash at the justified tip, a stash that does not hash to the justified root, nothing justified yet,
     a justified tip below protocol.EXEC_CARRY_ROOT_HEIGHT (its root commits no carry, so L1 would refuse the span);
     and the in-flight flag is raised before the first await, so a concurrent maybe_settle task never proves twice.
  5. construct_settle_tx carries the commitment as `stwo`, which is what L1's settle branch and apply key on.
Needs the nightly toolchain for section 2; without it that section is SKIPPED (named) and the rest still runs.
Run: python3 tests/test_an_exec_node_proves_its_settle_span_from_the_gate_and_settles_bare_otherwise.py
"""
import os
_REAL_HOME = os.path.expanduser("~")      # BEFORE isolate: the toolchain lives under the real HOME
import _harness
HOME = _harness.isolate("nado-test-exec-stwo-settle-")
import asyncio
import json

import execnode.execnode as EN
from execnode import block_apply, settle_b2 as S2
from execnode.games import dice
from execnode.state import ExecState
from protocol import EPOCH_LENGTH as L
from tests._stwo_settle_build import NIGHTLY, build, build_verifier

T = _harness.Report()
_harness.pinned(EXEC_ADDR_ROOT_HEIGHT=1).__enter__()       # the registry committed from block 1 (its reroll value)
_harness.pinned(EXEC_CARRY_ROOT_HEIGHT=1).__enter__()      # ...and the dividend carry (its reroll value; 30000 live)
A = "ndo" + "A" * 45
B = "ndo" + "B" * 45
DC = dice.build()
D_CID = ExecState(os.path.join(HOME, "probe.json")).contract_id(A, DC, "d")
_n = [0]


def blob(who, payload):
    _n[0] += 1
    return {"recipient": "blob", "sender": who, "txid": "t%d" % _n[0], "data": payload}


def txs_at(h):
    out = []
    if h == 1:
        out += [blob(A, {"op": "deploy", "runtime": "zkvm", "code": DC, "nonce": "d"})]
        out += [{"recipient": "bridge", "sender": x, "amount": 10**7} for x in (A, B)]
    if h == 2:
        out.append(blob(A, {"op": "call", "contract": D_CID, "method": "open", "args": [1], "value": 10**6}))
    if h == 70:
        out.append(blob(B, {"op": "call", "contract": D_CID, "method": "bet", "args": [3, 1, 50], "value": 100}))
    if h >= 1 and h % L == 1:
        out.append({"recipient": "duty", "sender": A, "data": {"reveal": {"target_epoch": h // L + 1, "secret": "s%d" % h}}})
    return out


BLOCKS = [{"block_number": h, "block_hash": "%064x" % (0xbeef0000 + 31337 * h), "block_transactions": txs_at(h)}
          for h in range(3 * L + 1)]


def accrual(E):
    return (1000 + E, {A: 2, B: 1})


st = ExecState(os.path.join(HOME, "st.json"))
states = {"default": st}
roots, payloads = {}, {}
for b in BLOCKS:
    h = b["block_number"]
    while st.last_div_epoch < h // L - 1:
        E = st.last_div_epoch + 1
        st.accrue_dividend_epoch(*accrual(E), epoch=E)
        st.last_div_epoch = E
    block_apply.begin(states, h)
    block_apply.dispatch(states, st, b, {}, set(), verbose=False)
    block_apply.close(states, h, b["block_hash"])
    if h % L == 0 and h:
        roots[h] = st.state_root()
        payloads[h] = json.dumps({"ns": "default", "cursor": h, "state_root": roots[h], "state": st._snapshot()},
                                 sort_keys=True)
st.boundary_roots = dict(roots)

# ---- L1 and the exec node's own HTTP helpers, stood in for -----------------------------------------------------------------
L1 = {"settled": (L, roots[L])}
ASKED = []
FLAG_AT_ASK = []


async def get_json(session, path):
    ASKED.append(path)
    if path.startswith("/get_settled"):
        FLAG_AT_ASK.append(EN._settle_proving)
        c, r = L1["settled"]
        return {"ns": "default", "exec_cursor": c, "state_root": r}
    if path.startswith("/get_block?number="):
        return json.loads(json.dumps(BLOCKS[int(path.split("=")[1])]))
    raise AssertionError(path)


async def accrual_inputs(session, E):
    ASKED.append(f"accrual {E}")
    return accrual(E)


async def announce(session, c, budget_s=20.0):
    return 0


EN._get_json, EN._get_l1_accrual_inputs, EN.da_announce = get_json, accrual_inputs, announce
EN._settled_history["default"] = {L: payloads[L], 2 * L: payloads[2 * L]}


def run(cur=3 * L, latest=3 * L + 5):
    EN._settle_publishing = 0.0
    return asyncio.run(EN._stwo_settle_bundle(None, "default", st, cur, latest))


# ---- 1. below the gate
ASKED.clear()
T.check("1. below STWO_SETTLE_HEIGHT nothing is asked of L1 and nothing is proven (the settle goes bare)",
        run() is None and not ASKED, ASKED)

BIN, blog = build(_REAL_HOME, "vm_settle")
SO, _slog = build_verifier(_REAL_HOME)
if SO is not None:
    os.environ["NADO_STWO_SETTLE_LIB"] = SO
with _harness.pinned(STWO_SETTLE_HEIGHT=1):
    # ---- 2. the call span (60, 180]: the bet runs on the VM
    if BIN is None or SO is None:
        print(f"SKIP  2. the call span: no {NIGHTLY} prover or no stable verifier on this machine")
    else:
        EN.STWO_VM_SETTLE = BIN
        out = run()
        T.check("2a. from the gate the span from the justified tip to the newest boundary is proven and published",
                out is not None and out[1:] == (3 * L, roots[3 * L]), out)
        if out:
            raw = EN.DA.get(out[0])
            bundle = json.loads(raw)
            pre = ExecState.snapshot_view(json.loads(payloads[L])["state"])
            span = BLOCKS[L + 1:3 * L + 1]
            ok, why, post = S2.verify_span(L, roots[L], span, S2.reference_chain(pre, span, accrual), bundle)
            T.check("2b. the published bundle is what L1 verifies: it lands on the boundary root, with one VM proof",
                    ok and post == roots[3 * L] and bundle["vm_proof"], why)
            T.check("2c. the publish hold is raised for the submit (no bare settle may walk the tip past the span)",
                    EN._settle_publishing > 0)
            T.check("2d. the in-flight prove flag is released when the prove thread ends", EN._settle_proving is False)

    # ---- 3. no prover on this node
    EN.STWO_VM_SETTLE = os.path.join(HOME, "no-such-vm_settle")
    T.check("3a. without the prover, a span with calls settles bare (never stalls)", run() is None)
    T.check("3b. ...and the in-flight flag is released", EN._settle_proving is False)
    L1["settled"] = (2 * L, roots[2 * L])
    out = run()
    T.check("3c. without the prover, a span with NO contract call still proves (no VM proof is needed)",
            out is not None and out[1:] == (3 * L, roots[3 * L]) and json.loads(EN.DA.get(out[0]))["vm_proof"] is None, out)

    # ---- 4. when it cannot prove honestly, it settles bare
    st.attested[3 * L] = roots[3 * L]
    T.check("4a. a boundary already attested is never proven (L1 takes one settle per validator and cursor)", run() is None)
    del st.attested[3 * L]
    EN._settled_history["default"].pop(2 * L)
    T.check("4b. no stash at the justified tip: bare", run() is None)
    EN._settled_history["default"][2 * L] = payloads[L]                # a stash that is not the tip's state
    T.check("4c. a stash that does not hash to the justified root: bare", run() is None)
    EN._settled_history["default"][2 * L] = payloads[2 * L]
    with _harness.pinned(EXEC_CARRY_ROOT_HEIGHT=2 * L + 1):
        ASKED.clear()
        T.check("4f. a justified tip below EXEC_CARRY_ROOT_HEIGHT: bare, before any block or accrual input is fetched",
                run() is None and not [a for a in ASKED if not a.startswith("/get_settled")], ASKED)
    L1["settled"] = (-1, None)
    T.check("4d. nothing justified yet (the first settlement is by quorum): bare", run() is None)
    T.check("4e. the in-flight flag is up from the FIRST await (a concurrent settle task holds instead of proving the same "
            "span twice), and down again after every bare return", FLAG_AT_ASK and all(FLAG_AT_ASK)
            and EN._settle_proving is False, (FLAG_AT_ASK, EN._settle_proving))

# ---- 5. the field L1 keys on
from ops.key_ops import generate_keys
from ops.transaction_ops import construct_settle_tx
tx = construct_settle_tx(generate_keys(), 3 * L, roots[3 * L], 400, stwo="ab" * 32)
T.check("5. construct_settle_tx carries the commitment as `stwo` (and no Goldilocks field)",
        tx["data"].get("stwo") == "ab" * 32 and "proof" not in tx["data"] and "proof_da" not in tx["data"], tx["data"])
T.done()
