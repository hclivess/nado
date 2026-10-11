"""A relaying node keeps claiming the fees its Stwo relay earns after its first eight relayed spends have been claimed
(loops/core_loop.CoreClient._claim_relay_unshields).

FOUND BY THE LOOPBACK WALK OF THE STWO POOL (2026-10-12): a real nado.py + execnode on loopback relayed a wallet's
private spend, the exec node recorded the relay's fee exit (nonce 1), the root settled, and auto-collect claimed it —
SHIELD_ESCROW fell by exactly the 100000-raw fee. But the exec node's /exec/unshields kept listing nonce 1 afterwards
(ExecState.unshields_for lists every exit ever recorded: the exec layer never learns that L1 claimed one), and a second
claim of the same exit was refused by L1 with "this unshield was already claimed". _claim_relay_unshields takes
pending[:_RELAY_CLAIMS_PER_PASS] of that list as-is, so once a relay's first eight exits are claimed, every pass
re-sends eight doomed claims and the ninth exit — and every later one — is never claimed: the relay pays MIN_TX_FEE per
spend from then on and recovers nothing, the standing cost the auto-collect was added to remove.

Pins, with L1's claimed-set held in a real (throwaway) KV store and L1's refusal mirrored from the unshield validation
(kv_ops.shield_nullifier_exists -> "this unshield was already claimed"):
  1. the exec node lists a claimed exit (it cannot know) — the input _claim_relay_unshields actually receives;
  2. with exits 1..8 already claimed on L1 and exit 9 not, a pass claims exit 9;
  3. no pass re-sends an exit L1 already claimed.

Run: python3 tests/test_a_relaying_node_still_claims_new_fee_exits_after_eight_were_claimed.py
"""
import os, sys, tempfile, shutil
_T = tempfile.mkdtemp(prefix="nado-test-relay-claim-after-eight-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
import atexit; atexit.register(shutil.rmtree, _T, ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {str(detail)[:600]}"))
    fails += 0 if ok else 1


import logging
from ops import kv_ops
from ops.key_ops import generate_keys
import ops.settlement_ops as SO
from loops.core_loop import CoreClient
from execnode.state import ExecState

node = generate_keys()
me = node["address"]
ROOT = "ab" * 32
TIP = 5000
N = CoreClient._RELAY_CLAIMS_PER_PASS

# 1. the exec node's view: every recorded exit, claimed or not (ExecState.unshields_for, what /exec/unshields serves)
st = ExecState(os.path.join(_T, "s.json"))
for i in range(1, N + 2):
    st.unshield_withdrawals[str(i)] = {"addr": me, "amount": 100000}
listed = st.unshields_for(me)
check("1. the exec node lists every recorded exit — it has no way to know which ones L1 already released",
      [u["nonce"] for u in listed] == [str(i) for i in range(1, N + 2)], listed)

# L1: exits 1..N already claimed (the burned (addr, nonce) unshield nullifier, as the unshield apply path writes it)
kv_ops.init_env()
with kv_ops.write_txn():
    for i in range(1, N + 1):
        kv_ops.shield_nullifier_put(me, str(i))


class _Mem:
    def __init__(self):
        self.address, self.keydict, self.latest_block = me, node, {"block_number": TIP}
        self.merged, self.accepted = [], []

    def merge_transaction(self, tx, user_origin=False):
        # L1's own refusal (ops/transaction_ops unshield branch): a claimed (addr, nonce) is refused
        self.merged.append(tx["data"]["nonce"])
        if kv_ops.shield_nullifier_exists(tx["data"]["addr"], tx["data"]["nonce"]):
            return {"result": False, "message": "Could not merge remote transaction: this unshield was already claimed"}
        self.accepted.append(tx["data"]["nonce"])
        return {"result": True, "message": "Success"}


class _Node:
    _RELAY_CLAIMS_PER_PASS = CoreClient._RELAY_CLAIMS_PER_PASS
    _claim_relay_unshields = CoreClient._claim_relay_unshields

    def __init__(self):
        self.memserver, self.logger = _Mem(), logging.getLogger("t")

    def _exec_get(self, path):
        if path.startswith("/exec/unshields?addr="):
            return {"unshields": st.unshields_for(path.split("=", 1)[1])}
        if path.startswith("/exec/unshield_proof?"):
            q = dict(kv.split("=", 1) for kv in path.split("?", 1)[1].split("&"))
            w = st.unshield_withdrawals.get(q["nonce"])
            return {"addr": w["addr"], "amount": w["amount"], "nonce": q["nonce"], "proof": {"p": q["nonce"]}} if w else None


SO.latest_settled = lambda: (100, ROOT)
n = _Node()
for _ in range(3):                       # three epochs' passes
    n._claim_relay_unshields()
check(f"2. with exits 1..{N} claimed on L1, a pass claims exit {N + 1}", str(N + 1) in n.memserver.accepted,
      {"sent": n.memserver.merged, "accepted": n.memserver.accepted})
check("3. no pass re-sends an exit L1 already claimed",
      not [x for x in n.memserver.merged if kv_ops.shield_nullifier_exists(me, x) and x not in n.memserver.accepted],
      n.memserver.merged)

print("ALL PASS — a relay keeps claiming its fees" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
