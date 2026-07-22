"""
PUSH transaction gossip (ops/gossip.py) — the flood-control rules that keep push propagation from
becoming a broadcast storm, tested pure (no node import).

Load-bearing properties:
  * FIRST-SIGHT ONLY: a node re-gossips a tx only on the merge that NEWLY accepts it ("Success"); a
    dup ("Already present") and a reject (result False) never re-flood, so the epidemic terminates
    the instant every peer holds the tx — no TTL, no seen-set needed.
  * ECHO SUPPRESSION: the sender is never a target, so a relayed tx does not bounce straight back.
  * enqueue_gossip is best-effort: a full queue drops the overflow rather than blocking the accept
    path (the txid-diff pull reconcile is the correctness backstop).

Run: python3 tests/test_gossip.py
"""
import os, sys, queue

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops.gossip import should_gossip, gossip_targets

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}")


def t_should_gossip_first_sight_only():
    """Only a genuinely-new accept re-floods; dups and rejects do not (flood termination)."""
    assert should_gossip({"result": True, "message": "Success"}) is True
    assert should_gossip({"result": True, "message": "Already present"}) is False   # dup -> stop
    assert should_gossip({"result": False, "message": "Mempool full"}) is False
    assert should_gossip({"result": False, "message": "Target block too low"}) is False
    assert should_gossip(None) is False
    assert should_gossip("Success") is False


def t_gossip_targets_excludes_sender_and_cleans():
    """The sender is dropped (no echo), falsy entries removed, order preserved, de-duplicated."""
    assert gossip_targets(["a", "b", "c"], exclude_ip="b") == ["a", "c"]
    assert gossip_targets(["a", "a", "b"], exclude_ip=None) == ["a", "b"]        # de-dup
    assert gossip_targets(["a", None, "", "b"]) == ["a", "b"]                    # drop falsy
    assert gossip_targets([], exclude_ip="a") == []
    assert gossip_targets(None) == []


def t_flood_terminates_across_two_merges():
    """Narrative: node accepts tx (Success -> gossip), a peer echoes it back (Already present -> no
    gossip). Two hops, one fan-out — the flood cannot loop."""
    pool = set()
    def merge(txid):
        if txid in pool:
            return {"result": True, "message": "Already present"}
        pool.add(txid); return {"result": True, "message": "Success"}
    assert should_gossip(merge("tx1")) is True     # first sight -> re-broadcast
    assert should_gossip(merge("tx1")) is False    # echoed back -> silent, epidemic ends


def t_enqueue_is_best_effort_when_full():
    """A minimal enqueue mirroring memserver.enqueue_gossip: a full queue drops the overflow instead
    of raising into the accept path."""
    q = queue.Queue(maxsize=2)
    def enqueue(tx, exclude_ip=None):
        try: q.put_nowait((tx, exclude_ip))
        except queue.Full: pass
    enqueue({"txid": "a"}, "1.1.1.1")
    enqueue({"txid": "b"}, "1.1.1.1")
    enqueue({"txid": "c"}, "1.1.1.1")   # over capacity -> dropped, must not raise
    assert q.qsize() == 2
    assert q.get_nowait() == ({"txid": "a"}, "1.1.1.1")   # echo-exclusion payload preserved


for name, fn in [
    ("should_gossip fires only on first-sight accept", t_should_gossip_first_sight_only),
    ("gossip_targets excludes sender, dedups, cleans", t_gossip_targets_excludes_sender_and_cleans),
    ("flood terminates across two merges", t_flood_terminates_across_two_merges),
    ("enqueue is best-effort when the queue is full", t_enqueue_is_best_effort_when_full),
]:
    check(name, fn)

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
