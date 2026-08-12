"""
Governance archive (ops/treasury_history.py) — the durable record of what the treasury actually paid.

Derived from `treasury_execute` transactions in blocks, so these checks drive the scanner with synthetic
blocks and assert the properties a governance page is quoted on: totals that only count VALID payouts,
per-recipient aggregates, an idempotent re-scan (an archive that double-counts is worse than none), and
a reroll dropping the previous chain's numbers instead of mixing them into the new chain's totals.
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


def mk(h, txs):
    # the REAL field name a stored block carries (ops/daily_stats.py reads the same)
    return {"block_number": h, "block_transactions": txs}


def pay(to, amt, pid="p1", memo="", by="exec1"):
    return {"recipient": "treasury_execute", "sender": by, "txid": "t" + pid,
            "data": {"pid": pid, "spend": {"recipient": to, "amount": amt, "memo": memo}}}


def main():
    with tempfile.TemporaryDirectory() as d:
        os.environ["HOME"] = d
        os.makedirs(os.path.join(d, "nado"), exist_ok=True)
        from ops import treasury_history as th

        blocks = {
            1: mk(1, [pay("addrA", 500, "p1", "grant")]),
            2: mk(2, [{"recipient": "transfer", "sender": "x"}]),
            3: mk(3, [pay("faucet", 250, "p2", "prize bank")]),
            4: mk(4, [pay("addrA", 100, "p3"),
                      {"recipient": "treasury_execute", "sender": "y", "data": {}}]),   # malformed
            5: mk(5, [pay("addrB", -5, "p4")]),                                          # negative
        }
        r = th.scan(5, lambda h: blocks.get(h))
        check("scan finds only the valid payouts", r["found"] == 3)

        rep = th.report()
        check("total_paid sums valid payouts only", rep["total_paid"] == 850)
        check("malformed / non-positive payouts are skipped", rep["count"] == 3)
        check("start_height records where this node's view begins", rep["start_height"] == 1)

        by = {e["recipient"]: e for e in rep["by_recipient"]}
        check("per-recipient total + count", by["addrA"]["total"] == 600 and by["addrA"]["count"] == 2)
        check("faucet is archived like any recipient", by["faucet"]["total"] == 250)
        check("recipients ranked by total", rep["by_recipient"][0]["recipient"] == "addrA")
        check("payouts newest-first", rep["payouts"][0]["height"] >= rep["payouts"][-1]["height"])

        r2 = th.scan(5, lambda h: blocks.get(h))
        check("re-scan is idempotent", r2["found"] == 0 and th.report()["total_paid"] == 850)

        blocks[6] = mk(6, [pay("addrC", 1000, "p5")])
        th.scan(6, lambda h: blocks.get(h))
        check("incremental pass archives new payouts", th.report()["total_paid"] == 1850)

        import json
        p = th._path()
        j = json.load(open(p))
        j["chain"] = "otherchain/99"
        json.dump(j, open(p, "w"))
        check("a reroll drops the previous chain's archive",
              th.report()["total_paid"] == 0 and th.report()["count"] == 0)

    print()
    print("ALL TREASURY-ARCHIVE CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
