"""A node that relays Stwo spends claims the fees they paid it (core_loop.CoreClient._claim_relay_unshields, called from
maybe_auto_collect), so relaying is paid for and not a standing cost to the operator.

Each relayed spend pays the relay by an unshield exit to the node's address (ops/stwo_relay.py); only an `unshield`
claim against the SETTLED exec root brings it to L1, and without one the node paid MIN_TX_FEE per spend for nothing.
Pins, with the exec node's answers and the settled root stubbed (no chain, no live node):
  1. each pending exit with a proof against the settled root becomes ONE `unshield` tx signed by the node key:
     self-claimed (data.addr == sender), fee-exempt, amount in data, exact landing at tip + TX_INCLUSION_DELAY;
  2. an exit the exec node cannot prove against the settled root (no proof) and an exit to another address are skipped;
  3. no settled root -> nothing is sent; at most _RELAY_CLAIMS_PER_PASS claims per pass.

Run: python3 tests/test_a_relaying_node_claims_its_fee_exits_against_the_settled_root.py
"""
import os, sys, tempfile, shutil
_T = tempfile.mkdtemp(prefix="nado-test-relay-claim-")
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
import protocol as P
from ops.key_ops import generate_keys
from ops.transaction_ops import create_txid
from signatures import verify as sig_verify, unhex
import ops.settlement_ops as SO
from loops.core_loop import CoreClient

node = generate_keys()
ROOT = "ab" * 32
TIP = 5000


class _Mem:
    def __init__(self):
        self.address, self.keydict, self.latest_block = node["address"], node, {"block_number": TIP}
        self.merged = []

    def merge_transaction(self, tx, user_origin=False):
        self.merged.append(tx)
        return {"result": True, "message": "Success"}


class _Node:
    _RELAY_CLAIMS_PER_PASS = CoreClient._RELAY_CLAIMS_PER_PASS
    _claim_relay_unshields = CoreClient._claim_relay_unshields

    def __init__(self, exits, proofs):
        self.memserver, self.logger = _Mem(), logging.getLogger("t")
        self.exits, self.proofs = exits, proofs

    def _exec_get(self, path):
        if path.startswith("/exec/unshields?addr="):
            return {"unshields": [e for e in self.exits if e["addr"] == path.split("=", 1)[1]]}
        if path.startswith("/exec/unshield_proof?"):
            q = dict(kv.split("=", 1) for kv in path.split("?", 1)[1].split("&"))
            if q.get("root") != ROOT:
                return None
            return self.proofs.get(q["nonce"])


SO.latest_settled = lambda: (100, ROOT)
me = node["address"]
exits = [{"addr": me, "amount": 100000, "nonce": "1"}, {"addr": me, "amount": 100000, "nonce": "2"},
         {"addr": me, "amount": 100000, "nonce": "3"}]
proofs = {"1": {"addr": me, "amount": 100000, "nonce": "1", "proof": {"path": ["x"]}},
          "3": {"addr": me, "amount": 100000, "nonce": "3", "proof": {"path": ["y"]}}}
n = _Node(exits, proofs)
sent = n._claim_relay_unshields()
txs = n.memserver.merged
check("1. each exit provable against the settled root becomes one claim (the unprovable one waits)",
      sent == 2 and [t["data"]["nonce"] for t in txs] == ["1", "3"], [t["data"] for t in txs])
t = txs[0] if txs else {}
check("...an `unshield` tx, self-claimed and fee-exempt, the amount in data",
      t.get("recipient") == "unshield" and t.get("sender") == me and t["data"]["addr"] == me and t.get("amount") == 0
      and t.get("fee") == 0 and t["data"]["amount"] == 100000, t)
check("...landing exactly at tip + TX_INCLUSION_DELAY (unshield is exact-landing)",
      t.get("max_block") == TIP + P.TX_INCLUSION_DELAY and "min_block" not in t, t.get("max_block"))
body = {k: v for k, v in t.items() if k not in ("signature", "txid")}
check("...signed by the node key", create_txid(body) == t.get("txid") and sig_verify(t["signature"], node["public_key"],
                                                                                      unhex(t["txid"])))
n2 = _Node([{"addr": me, "amount": 5, "nonce": "9"}], {"9": {"addr": "someone_else", "amount": 5, "nonce": "9",
                                                              "proof": {"p": 1}}})
check("2. a proof naming another address is never claimed", n2._claim_relay_unshields() == 0 and not n2.memserver.merged)
SO.latest_settled = lambda: (None, None)
n3 = _Node(exits, proofs)
check("3. no settled root -> nothing is sent", n3._claim_relay_unshields() == 0 and not n3.memserver.merged)
SO.latest_settled = lambda: (100, ROOT)
many = [{"addr": me, "amount": 7, "nonce": str(i)} for i in range(20)]
n4 = _Node(many, {str(i): {"addr": me, "amount": 7, "nonce": str(i), "proof": {"p": i}} for i in range(20)})
check("...and at most _RELAY_CLAIMS_PER_PASS claims go out per pass",
      n4._claim_relay_unshields() == CoreClient._RELAY_CLAIMS_PER_PASS == len(n4.memserver.merged))

src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "loops", "core_loop.py")).read()
ac = src[src.index("    def maybe_auto_collect(self):"):src.index("    _RELAY_CLAIMS_PER_PASS")]
check("the claim runs inside maybe_auto_collect, after its emergency-mode guard",
      ac.index("emergency_mode") < ac.index("self._claim_relay_unshields()"))

print("ALL PASS — a relaying node claims its fee exits" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
