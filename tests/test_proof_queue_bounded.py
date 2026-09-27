"""The proof-verification queue is bounded (audit 2026-09-25, MEDIUM).

memserver._queue_proof_merge held whole proof-bearing settles — each up to the 192 MiB body cap — in an UNBOUNDED
queue, filled before validation from whatever peers advertised. Pins, by running the real method on a stub: the queue
holds at most _PROOF_Q_MAX; a tx over the bound is declined (returns False) without blocking and without being marked
in flight, so a later reconcile pass can fetch it again; a duplicate is not queued twice; and a tx is marked in flight
BEFORE it is queued, so the worker's discard always finds it.

The method is lifted from memserver.py's source: importing memserver opens the node's database.
Run: python3 tests/test_proof_queue_bounded.py
"""
import ast, os, sys, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "memserver.py")).read()
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


tree = ast.parse(SRC)
cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)
           and any(isinstance(m, ast.FunctionDef) and m.name == "_queue_proof_merge" for m in n.body))
parts = [ast.get_source_segment(SRC, m) for m in cls.body
         if (isinstance(m, ast.FunctionDef) and m.name == "_queue_proof_merge")
         or (isinstance(m, ast.Assign) and any(getattr(t, "id", None) == "_PROOF_Q_MAX" for t in m.targets))]
check("the bound and the method are found", len(parts) == 2, len(parts))
import textwrap
ns = {}
exec("class Stub:\n" + textwrap.indent("\n".join(textwrap.dedent(p) for p in parts), "    "), ns)
Stub = ns["Stub"]

release = threading.Event()


class Node(Stub):
    def __init__(self):
        self.merged = []
        self.logger = type("L", (), {"error": staticmethod(lambda *a: None)})()

    def _pool_txid_set(self):
        return set()

    def merge_transaction(self, tx, uo):
        release.wait(10)                  # the worker is busy verifying: the queue fills behind it
        self.merged.append(tx["txid"])


n = Node()
cap = Node._PROOF_Q_MAX
res = [n._queue_proof_merge({"txid": f"t{i}"}, False) for i in range(cap + 6)]
time.sleep(0.2)
# one is taken by the (blocked) worker, `cap` sit in the queue; everything past that is declined
accepted = sum(1 for r in res if r)
check(f"at most _PROOF_Q_MAX (+1 in the worker) are held ({accepted} accepted of {len(res)})", accepted <= cap + 1, res)
check("the queue itself never exceeds its bound", n._proof_q.qsize() <= cap, n._proof_q.qsize())
declined = [f"t{i}" for i, r in enumerate(res) if not r]
check("a declined tx is not left marked in flight (a later pass can fetch it again)",
      bool(declined) and not (set(declined) & n._proof_inflight), (declined, n._proof_inflight))
check("a duplicate of a queued tx is not queued twice",
      n._queue_proof_merge({"txid": "t1"}, False) is True and n._proof_q.qsize() <= cap)
release.set()
time.sleep(0.5)
check("the worker drains what was accepted and clears it from in-flight",
      len(n.merged) == accepted and not n._proof_inflight, (n.merged, n._proof_inflight))

body = ast.get_source_segment(SRC, next(m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name == "_queue_proof_merge"))
check("in flight is marked BEFORE the put", 0 < body.find("_proof_inflight.add(txid)") < body.find("put_nowait("))

print("ALL PASS — the proof queue is bounded and declines instead of growing" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
