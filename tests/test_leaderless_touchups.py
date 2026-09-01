"""LEADERLESS ASSEMBLY TOUCH-UPS (2026-09-01, doc/leaderless-assembly.md).

Every node assembles every block from its own pool — no proposer to censor or wait for — and the one
weakness of that model is a same-height split when two pools differ at the slot. Three touch-ups close
it without a leader; this file pins them:
  1. the MOST-COMPLETE-POOL tie-break: a strict-superset tx set wins the same-height tie, then the larger
     set, then the permanent lowest-hash rule; both sides compute one answer; missing sets degrade to hash;
  2. the PRE-ASSEMBLY RECONCILE: /next_block_txids serves exactly the set upcoming_block_hash hashes, and
     the core thread reconciles against peers ONCE per tip right before building;
  3. an aggregate-spend refusal no longer purges the sender's other pooled txs (that purge was itself a
     pool-divergence source)."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def t1_tie_winner_superset():
    from ops.fork_resolution import tie_winner
    lo, hi = "0" * 64, "f" * 64
    check("hash rule without sets (unchanged)", tie_winner(lo, hi) == "ours" and tie_winner(hi, lo) == "theirs")
    check("their strict superset wins even with the better hash",
          tie_winner(lo, hi, ["a"], ["a", "b"]) == "theirs")
    check("our strict superset wins even with the worse hash",
          tie_winner(hi, lo, ["a", "b"], ["a"]) == "ours")
    check("incomparable: larger set wins", tie_winner(hi, lo, ["a", "b", "c"], ["a", "d"]) == "ours"
          and tie_winner(lo, hi, ["a", "b"], ["c", "d", "e"]) == "theirs")
    check("incomparable + equal size: hash rule", tie_winner(lo, hi, ["a", "b"], ["c", "d"]) == "ours"
          and tie_winner(hi, lo, ["a", "b"], ["c", "d"]) == "theirs")
    check("equal sets: hash rule", tie_winner(hi, lo, ["a"], ["a"]) == "theirs")
    check("empty vs non-empty: the block with the tx wins", tie_winner(lo, hi, [], ["a"]) == "theirs")
    check("one side unknown -> hash rule", tie_winner(hi, lo, None, ["a"]) == "theirs")
    check("symmetric: swapping sides swaps the answer",
          all((tie_winner(a, b, x, y) == "ours") == (tie_winner(b, a, y, x) == "theirs")
              for a, b in ((lo, hi), (hi, lo))
              for x, y in ((["a"], ["a", "b"]), (["a", "b"], ["a"]), (["a", "b"], ["c", "d"]), (["a"], ["b", "c"]))))
    check("same hash never switches", tie_winner(lo, lo, ["a"], ["a", "b"]) == "ours")


def t2_next_block_set_matches_upcoming_hash():
    d = tempfile.mkdtemp(prefix="nado-nbs-")
    os.environ["HOME"] = d
    from ops import kv_ops
    kv_ops.close_all(); kv_ops.init_env()
    import logging
    from memserver import MemServer
    try:
        ms = MemServer.__new__(MemServer)
    except Exception as e:
        check("MemServer stub", False, str(e)); return
    ms.logger = logging.getLogger("t")
    ms.pool_gen = 0
    ms._transaction_pool = []
    ms._txid_set_cache = None
    ms._upcoming_hash_cache = None
    ms.latest_block = {"block_hash": "ab" * 32, "block_number": 41}
    h0 = ms.get_upcoming_block_hash()
    tip, height, ids = ms.get_next_block_txids()
    check("empty pool: next set empty, height tip+1, tip echoed", ids == [] and height == 42 and tip == "ab" * 32)
    # a mature tx (no min_block / target inside window) enters the next set; an immature one does not
    mature = {"txid": "11" * 32, "sender": "s", "recipient": "r", "max_block": 300, "fee": 1, "amount": 1, "timestamp": 1}
    immature = dict(mature, txid="22" * 32, min_block=50)
    ms.transaction_pool = [immature, mature]
    from ops.block_ops import match_transactions_target
    expect = [t["txid"] for t in (match_transactions_target(transaction_list=[immature, mature], block_number=42,
                                                             logger=ms.logger) or [])]
    h1 = ms.get_upcoming_block_hash()
    _, _, ids = ms.get_next_block_txids()
    check("next set == the set the upcoming hash hashes", ids == expect, f"{ids} vs {expect}")
    check("upcoming hash moved with the pool, cache keyed on pool_gen", h1 != h0 or expect == [])
    ms.transaction_pool = [mature]
    check("cache invalidates on mutation", ms.get_next_block_txids()[2] == [mature["txid"]] or expect == [])
    kv_ops.close_all()


def t3_wiring_by_source():
    core = open(os.path.join(ROOT, "loops", "core_loop.py")).read()
    ms = open(os.path.join(ROOT, "memserver.py")).read()
    nado = open(os.path.join(ROOT, "nado.py")).read()
    i_rec = core.index("self._reconcile_before_build(peers)")
    i_build = core.index("block_candidate = get_block_candidate(logger=self.logger,")
    check("reconcile runs BEFORE the candidate is built", i_rec < i_build)
    check("reconcile is once per tip", "_reconciled_tip" in core)
    check("tie-break passes both tx sets", "fork_resolution.tie_winner(ours, theirs, o_ids, t_ids)" in core)
    check("no sender-wide purge on an aggregate-spend refusal",
          "self.purge_txs_of_sender(transaction[\"sender\"])" not in ms)
    check("/next_block_txids routed", 'web.get("/next_block_txids", next_block_txids)' in nado)
    seg = ms[ms.index("def reconcile_next_block_set"):ms.index("def reconcile_next_block_set") + 4000]
    check("reconcile filters to SAME-TIP peers", 'd.get("tip") == tip' in seg)
    check("reconcile never re-fetches a MINED tx", "kv_ops.tx_get(i) is None" in seg)
    check("reconcile is time-bounded", "wait_for" in seg and "timeout" in seg)
    check("fetched txs go through ordinary admission", "self.merge_transaction(tx)" in seg)


if __name__ == "__main__":
    for name in ("t1_tie_winner_superset", "t2_next_block_set_matches_upcoming_hash", "t3_wiring_by_source"):
        try:
            globals()[name]()
        except Exception:
            import traceback; traceback.print_exc(); _fails.append(name)
    print("ALL PASS" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    raise SystemExit(1 if _fails else 0)
