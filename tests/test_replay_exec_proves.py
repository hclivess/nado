"""The exec replay tool (tools/replay_exec.py) computes the exec root the exec node computes, says IDENTICAL only when
two replays agree, names the first differing height otherwise, and never replays the live checkout.

WHY (2026-10-27). G9 deletes the Goldilocks stack from execnode/ as well as from L1, and tools/replay_chain.py replays
L1 only: it never computes an exec root. This tool replays the exec layer the way the exec node applies it
(exec_genesis, the canonical accrual, rules_at, block_apply), so a deletion slice is proven by identical exec roots at
every height. Validated once against the live exec node: its 30 recorded epoch-boundary roots were all equal.
Pins:
  1. compare: identical -> IDENTICAL and exit 0; one differing root -> DIFFER at that height, exit 1; differing genesis ->
     DIFFER at genesis;
  2. replay refuses the live checkout;
  3. the child, run on a small real chain (a deploy, calls, deposits, an epoch boundary with an accrual), records the
     same root at every height as the same blocks applied in-process through block_apply.

Run: python3 tests/test_replay_exec_proves.py
"""
import _harness
HOME = _harness.isolate("nado-test-replay-exec-")
import json
import os
import subprocess
import sys

from execnode import block_apply, exec_genesis
from execnode.games import tictactoe
from execnode.state import ExecState
from execnode.stark import stark as _stk
from protocol import EPOCH_LENGTH

T = _harness.Report()
ROOT = _harness.ROOT
TOOL = os.path.join(ROOT, "tools", "replay_exec.py")
W = os.path.join(HOME, "w")
os.makedirs(W)


def run(*a, **kw):
    return subprocess.run([sys.executable, TOOL, *a], capture_output=True, text=True, timeout=600, **kw)


def res(n, diff_at=None, genesis="g"):
    roots = {str(h): f"r{h}" for h in range(n + 1)}
    if diff_at is not None:
        roots[str(diff_at)] = "DIFFERENT"
    return {"genesis_root": genesis, "roots": roots, "stopped": None}


def compare(a, b):
    pa, pb = os.path.join(W, "a.json"), os.path.join(W, "b.json")
    json.dump(a, open(pa, "w"))
    json.dump(b, open(pb, "w"))
    return run("compare", pa, pb)


r = compare(res(50), res(50))
T.check("1a. identical replays: IDENTICAL, exit 0", r.returncode == 0 and "IDENTICAL exec roots through height 50" in r.stdout, r.stdout)
r = compare(res(50), res(50, diff_at=17))
T.check("1b. one differing root: DIFFER at that height, exit 1", r.returncode == 1 and "DIFFER at height 17" in r.stdout, r.stdout)
r = compare(res(50), res(50, genesis="h"))
T.check("1c. a differing genesis: DIFFER at genesis", r.returncode == 1 and "DIFFER at genesis" in r.stdout, r.stdout)
r = run("replay", "/srv/nado-home/nado", os.path.join(W, "x"), os.path.join(W, "y"), "--out", os.path.join(W, "z"))
T.check("2. replay refuses the live checkout", r.returncode != 0 and "live checkout" in (r.stdout + r.stderr), r.stdout + r.stderr)

# ---- 3: a small real chain ---------------------------------------------------------------------------------------------
A, B = "ndo" + "A" * 45, "ndo" + "B" * 45
code = tictactoe.build()
blob = lambda who, n, p: {"recipient": "blob", "sender": who, "txid": n, "data": p}  # noqa: E731
probe = ExecState(os.path.join(HOME, "probe.json"))
cid = probe.contract_id(A, code, "n")
call = lambda who, n, m, args, value=0: blob(who, n, {"op": "call", "contract": cid, "method": m, "args": args,  # noqa: E731
                                                      **({"value": value} if value else {})})
blocks = [{"block_number": 0, "block_hash": "%064x" % 1, "block_transactions": []},
          {"block_number": 1, "block_hash": "%064x" % 2, "block_transactions": [
              blob(A, "d", {"op": "deploy", "runtime": "zkvm", "code": code, "nonce": "n"}),
              {"recipient": "bridge", "sender": A, "amount": 10**6}, {"recipient": "bridge", "sender": B, "amount": 10**6}]},
          {"block_number": 2, "block_hash": "%064x" % 3, "block_transactions": [call(A, "c1", "open", [9], 40),
                                                                                call(B, "c2", "join", [9], 40)]}]
for h in range(3, 2 * EPOCH_LENGTH + 2):
    blocks.append({"block_number": h, "block_hash": "%064x" % (h + 1), "block_transactions":
                   [call(A, f"m{h}", "move", [9, 0, 0])] if h == 5 else []})
accrual = {"epochs": {str(e): [1000 * (e + 1), {A: 2, B: 1}] for e in range(4)}}
bp, ap, op = os.path.join(W, "blocks.json"), os.path.join(W, "accrual.json"), os.path.join(W, "out.json")
json.dump(blocks, open(bp, "w"))
json.dump(accrual, open(ap, "w"))
env = {k: v for k, v in os.environ.items() if not k.startswith("NADO_")}
env.update(HOME=os.path.join(HOME, "child"), NADO_EXEC_STATE=os.path.join(HOME, "child", "es.json"),
           NADO_EXEC_DA=os.path.join(HOME, "child", "da"), PYTHONPATH=ROOT,
           NADO_ALLOW_PYTHON_KERNELS=os.environ.get("NADO_ALLOW_PYTHON_KERNELS", ""))
os.makedirs(env["HOME"])
r = run("_child", bp, ap, op, "-1", cwd=ROOT, env=env)
got = json.load(open(op)) if os.path.exists(op) else {"roots": {}}

st = ExecState(os.path.join(HOME, "inproc.json"))
exec_genesis.apply(st)
want = {}
for b in blocks:
    h = b["block_number"]
    while st.last_div_epoch < h // EPOCH_LENGTH - 1:
        E = st.last_div_epoch + 1
        inflow, w = accrual["epochs"][str(E)]
        st.accrue_dividend_epoch(inflow, w, epoch=E)
        st.last_div_epoch = E
    with _stk.rules_at(h):
        block_apply.begin({"default": st}, h)
        block_apply.dispatch({"default": st}, st, b, {}, set(), verbose=False)
        block_apply.close({"default": st}, h, b["block_hash"])
    want[str(h)] = st.state_root()
T.check(f"3. the child records the in-process exec root at every one of {len(blocks)} heights (a deploy, calls, "
        "deposits, two accruals)", got["roots"] == want and len(set(want.values())) > 3 and st.dividend,
        (r.returncode, r.stderr[-800:], len(got["roots"])))
T.done()
