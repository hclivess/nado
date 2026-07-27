"""
REGRESSION (deep-audit finding 2026-07-27, #14): settle-with-proof was single-block-span-only. The prover
dropped the per-call cursor, so calls_commitment stamped every leaf with the epoch-wide span cursor, while L1's
verify_calls_bound_to_summaries folds per-block summary leaves (each stamped with its block height). Any
multi-block span therefore failed the DA binding and fell back to quorum — and, worse, executed every call with
the wrong block context (a BHASH/TIME-reading call in a non-final block proved a wrong root).

Fix: _run_call / _epoch_pub_statement now thread the PER-CALL cursor (block height), which block_calls stamps.
This test proves a 2-block span's prover calls_commitment now equals L1's per-block summary fold, that the bound
epoch still verifies, and (control) that the old span-cursor stamping would NOT have matched.

Run: python3 tests/test_settle_multiblock_da.py
"""
import os, sys, tempfile, traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_mbda_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
from genesis import create_indexers
create_indexers()

from execnode import zkvmasm
from execnode.stark import settlement_sparse as SS, calls_commit as CC, alghash, field as F

fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1

D, NQ, NS = 16, 2, "default"
CID = "c" * 32
ALICE = "ndoAAAA" + "A" * 41
COUNTER = {"bump": zkvmasm.assemble("movi r1 0\n sload r2 r1\n movi r3 1\n add r2 r3\n sstore r1 r2\n ret r2")}


def _pre():
    return {CID: {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}}


def _block(h):
    return {"block_number": h, "block_hash": f"{h:02x}" * 32,
            "block_transactions": [{"recipient": "blob", "sender": ALICE,
                                    "data": {"op": "call", "contract": CID, "method": "bump", "args": [], "ns": NS}}]}


def _l1_fold(*blocks):
    """L1's per-block summary fold — exactly what verify_calls_bound_to_summaries computes."""
    node = alghash.IV
    for b in blocks:
        _inert, calls_by_ns = CC.block_summary(b)
        node = CC.fold_leaves(node, calls_by_ns.get(NS, []))
    return node % F.P


def main():
    b1, b2 = _block(1), _block(2)
    span_calls = CC.block_calls(b1, NS) + CC.block_calls(b2, NS)     # per-call cursor = 1, then 2
    check("span calls carry per-block cursors", [c["cursor"] for c in span_calls] == [1, 2])

    # prove a single bound epoch over the 2-block span (span cursor = 2)
    bundle = SS.prove_bound_epoch(_pre(), span_calls, cursor=2, depth=D, num_queries=NQ)
    prover_cc = int(bundle["calls_commitment"]) % F.P

    check("prover calls_commitment == L1 per-block summary fold (2-block span binds)",
          prover_cc == _l1_fold(b1, b2))
    ok, why, _ = SS.verify_bound_epoch(bundle, num_queries=NQ)
    check(f"bound epoch over the 2-block span verifies ({why})", ok)

    # CONTROL: the old behaviour (every leaf stamped with the span cursor, no per-call cursor) would NOT match
    stripped = [{k: v for k, v in c.items() if k not in ("cursor", "timestamp")} for c in bundle["calls"]]
    old_cc = int(CC.calls_commitment(stripped, cursor=2)) % F.P
    check("control: span-cursor stamping does NOT match L1's per-block fold (the bug)", old_cc != _l1_fold(b1, b2))

    # single-block span still binds (the previously-working case)
    b3 = _block(3)
    single = SS.prove_bound_epoch(_pre(), CC.block_calls(b3, NS), cursor=3, depth=D, num_queries=NQ)
    check("single-block span still binds", int(single["calls_commitment"]) % F.P == _l1_fold(b3))

    # THE END-TO-END GATE: a 2-block span must pass L1's verify_calls_bound_to_summaries, both non-recursive
    # (one segment) and recursive (one block-aligned segment per block).
    def _summaries(*blocks):
        out = {}
        for b in blocks:
            inert, cbn = CC.block_summary(b)
            out[int(b["block_number"])] = {"inert": 1 if inert else 0, "calls": cbn}
        return out
    sums = _summaries(b1, b2)
    get = lambda h: sums.get(int(h))

    nrec = SS.prove_settlement_sparse(_pre(), span_calls, cursor=2, rec_hex="00" * 32, num_queries=NQ, depth=D)
    ok_nr, why_nr = CC.verify_calls_bound_to_summaries(nrec, NS, 0, 2, get, 240)
    check(f"non-recursive 2-block span passes L1 DA binding ({why_nr})", ok_nr)

    rec = SS.prove_settlement_sparse(_pre(), span_calls, cursor=2, rec_hex="00" * 32, num_queries=NQ, depth=D,
                                     recursive=True, fold=False)
    check("recursive yields one block-aligned segment per block (cursors [1,2])",
          [int(s["cursor"]) for s in rec["segments"]] == [1, 2])
    ok_r, why_r = CC.verify_calls_bound_to_summaries(rec, NS, 0, 2, get, 240)
    check(f"recursive per-block 2-block span passes L1 DA binding ({why_r})", ok_r)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        fails += 1; print(f"FAIL  exception: {e}"); traceback.print_exc()
    print("\nALL PASS — multi-block spans now bind to the DA calldata" if fails == 0 else f"\n{fails} FAILURES")
    sys.exit(1 if fails else 0)
