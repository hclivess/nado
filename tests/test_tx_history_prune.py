"""
Rolling-mode TX-HISTORY pruning (kv_ops.prune_tx_history / block_ops.prune_tx_history_window).

The tx index is the term that dominates a busy node's disk — bodies plateau once rolling mode prunes
them, the tx history never did (~97% of a ten-year footprint at 20 tx/block). Pruning it is safe because
the three history sub-DBs are excluded from the state root AND from snapshots, so every snapshot-synced
node already runs without pre-checkpoint history.

The one thing that MUST survive is the at-most-once replay guard (`tx_get`), which reads this index. A tx
mined at H is unreplayable past H + TX_LANDING_WINDOW, so the retained window only has to clear that plus
FINALITY_DEPTH — but if the floor were ever wrong, an old txid could be re-mined. These checks pin:

  * rows below the cutoff are gone, rows above it are untouched (both the primary and the secondaries);
  * the retention floor is ENFORCED in code, so a reckless config cannot shrink the replay window;
  * a tx inside the guard window is still found by tx_get after a prune — the guard still bites;
  * pruning is idempotent and bounded per pass.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fails = []


def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        _fails.append(name)


class _Log:
    def info(self, *a):
        pass

    def error(self, *a):
        pass


def main():
    with tempfile.TemporaryDirectory() as d:
        os.environ["HOME"] = d
        os.makedirs(os.path.join(d, "nado"), exist_ok=True)
        from ops import kv_ops
        from ops import block_ops
        from protocol import TX_HISTORY_MIN_RETENTION, TX_LANDING_WINDOW, FINALITY_DEPTH
        kv_ops.init_env()

        # index txs across a range of heights
        for h in (10, 100, 1000, 5000, 9000, 9990, 10000):
            kv_ops.tx_index_put(f"tx{h}", h, f"sender{h}", f"recip{h}")
        check("indexed 7 txs", all(kv_ops.tx_get(f"tx{h}") for h in (10, 1000, 10000)))

        # ---- the floor is enforced, not trusted -------------------------------------------------------
        check("floor clears the replay horizon",
              TX_HISTORY_MIN_RETENTION > TX_LANDING_WINDOW + FINALITY_DEPTH)
        # ask for an absurdly small window at a high finalized height; the floor must override it
        block_ops.prune_tx_history_window(10000, 1, _Log())
        kept_by_floor = kv_ops.tx_get("tx9990")            # inside 10000 - 5000 floor
        check("a reckless retention=1 is floored (recent tx survives)", kept_by_floor is not None)
        check("floor still prunes what is genuinely old", kv_ops.tx_get("tx10") is None)

        # ---- the guard still bites inside the window --------------------------------------------------
        check("replay guard intact for an in-window tx", kv_ops.tx_get("tx9000") is not None)
        check("old rows are gone", kv_ops.tx_get("tx100") is None and kv_ops.tx_get("tx1000") is None)

        # ---- secondaries pruned with the primary ------------------------------------------------------
        rows_old = kv_ops.tx_of_account("sender100", 0, 10)
        rows_new = kv_ops.tx_of_account("sender9990", 0, 10)
        check("pruned tx left no secondary rows", not rows_old)
        check("retained tx still has its secondary rows", bool(rows_new))

        # ---- idempotent ------------------------------------------------------------------------------
        again = kv_ops.prune_tx_history(10000 - TX_HISTORY_MIN_RETENTION)
        check("re-pruning the same window deletes nothing", again == 0)

        # ---- bounded per pass ------------------------------------------------------------------------
        for i in range(50):
            kv_ops.tx_index_put(f"bulk{i}", 20 + i, f"s{i}", f"r{i}")
        n = kv_ops.prune_tx_history(100000, max_rows=10)
        check("per-pass cap respected", n == 10)

    print()
    print("ALL TX-HISTORY PRUNE CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
