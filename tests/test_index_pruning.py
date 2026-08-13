"""
NUMBER<->HASH INDEX RETENTION — the standard (protocol.INDEX_RETENTION_*, doc/index-pruning.md).

THE PROBLEM. block_by_num (height->hash) and block_by_hash (hash->height) were the only stores that grew
forever in EVERY mode: 144 B/block combined, ~7 GiB per decade at 6 s blocks. Once rolling mode prunes
bodies and tx history, they are the dominant term — the thing standing between a volunteer VPS and ~10 GB
a year.

WHY IT COULDN'T JUST BE A NODE SETTING. Both live in kv_ops.SNAPSHOT_DBS, and every carried row feeds
state_digest. Two nodes retaining different depths emit different snapshot_hash values for the SAME
checkpoint and fail quorum agreement — a consensus split produced by a disk-space knob. The depth has to be
a rule every node computes identically, so it is keyed on the one height they all already agree on: the
checkpoint height C the snapshot is OF. The payload carries [C-N, C]; the window is a pure function of C,
so every honest node builds a byte-identical payload. THAT is what makes local pruning below the window
unobservable, and therefore allowed at all.

WHAT THESE CHECKS PIN

  * DETERMINISM — the property the whole design rests on. Same C, same rows in, byte-identical payload and
    digest out, regardless of what each node happens to hold below the window. If this breaks, nodes fork
    on snapshot_hash and the failure looks like a mysterious quorum stall, not like a pruning bug.
  * THE WINDOW IS ENFORCED ON IMPORT, not just export. The import side re-derives it from the manifest's
    own snapshot_height, so a donor shipping out-of-window index rows has them dropped instead of trusted.
    A forged block_by_num row IS a forged epoch-beacon/PoSW anchor, which is why the payload is re-filtered
    rather than taken on faith.
  * ROWS ABOVE C ARE REJECTED. They cannot exist in an honest snapshot of C, and admitting one is exactly
    how a donor would smuggle a future anchor past the filter.
  * THE TWO DEPTHS STAY SEPARATE. Most of the saving comes from block_by_hash keeping 200x less than
    block_by_num; collapsing them to one number silently doubles the permanent index.
  * THE PRUNE LEAVES EVERY REAL CONSUMER RESOLVABLE — the deepest is POSW_DIFF_TRAIL epochs of
    registration-difficulty lookback.
  * TWO WATERMARKS. Heights between lo_num and lo_hash lose their hash row while the num row must stay; a
    shared watermark advances past them and their num row is never collected once the deeper window catches
    up. That leak is invisible except as an index that stops shrinking.
"""
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fails = []


def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        _fails.append(name)


def be8(n):
    return struct.pack(">Q", n)


def main():
    with tempfile.TemporaryDirectory() as d:
        os.environ["HOME"] = d
        os.makedirs(os.path.join(d, "nado"), exist_ok=True)
        from protocol import (INDEX_RETENTION_NUM, INDEX_RETENTION_HASH, POSW_DIFF_TRAIL,
                              EPOCH_LENGTH, FINALITY_DEPTH)
        from ops import snapshot_ops as S

        C = 200_000

        def idx_rows(lo, hi):
            """Both index directions for heights [lo, hi)."""
            out = []
            for h in range(lo, hi):
                bh = (f"{h:064x}").encode()
                out.append(("block_by_num", be8(h), bh))
                out.append(("block_by_hash", bh, be8(h)))
            return out

        # a realistic mix: deep history, in-window history, and a non-index row that must pass through
        rows = idx_rows(0, 60) + idx_rows(C - 60_000, C + 1) + [("accounts", b"addr", b"doc")]
        payload = S._payload_triples(rows, C)
        kept_num = {int.from_bytes(k, "big") for n, k, _ in payload if n == "block_by_num"}
        kept_hash = {int.from_bytes(v, "big") for n, _, v in payload if n == "block_by_hash"}

        # ---- the window is exactly [C-N, C] --------------------------------------------------------
        check(f"block_by_num keeps exactly {INDEX_RETENTION_NUM} heights back",
              min(kept_num) == C - INDEX_RETENTION_NUM and max(kept_num) == C)
        check(f"block_by_hash keeps exactly {INDEX_RETENTION_HASH} heights back",
              min(kept_hash) == C - INDEX_RETENTION_HASH and max(kept_hash) == C)
        check("...so the two depths really are different (that asymmetry IS the saving)",
              len(kept_num) > len(kept_hash) * 4)
        check("genesis-era rows far below the window are dropped", 0 not in kept_num and 0 not in kept_hash)
        check("a non-index row is untouched by the window",
              ("accounts", b"addr", b"doc") in payload)

        # ---- rows ABOVE C are refused (a forged future anchor) --------------------------------------
        future = [("block_by_num", be8(C + 1), b"f" * 64), ("block_by_hash", b"f" * 64, be8(C + 1))]
        check("a row ABOVE the checkpoint is rejected on both directions",
              S._payload_triples(future, C) == [])

        # ---- DETERMINISM: what a node holds BELOW the window must not change the payload -------------
        thin = idx_rows(C - 60_000, C + 1) + [("accounts", b"addr", b"doc")]          # pruned node
        fat = idx_rows(0, 1000) + idx_rows(C - 60_000, C + 1) + [("accounts", b"addr", b"doc")]  # archive
        p_thin, p_fat = S._payload_triples(thin, C), S._payload_triples(fat, C)
        check("a pruned node and an archive node emit the SAME payload for the same C", p_thin == p_fat)
        check("...and therefore the same state_digest",
              S.state_digest(thin, C) == S.state_digest(fat, C))
        check("a DIFFERENT checkpoint gives a different digest (the window really is keyed on C)",
              S.state_digest(thin, C) != S.state_digest(thin, C - 1))
        check("unbounded (C=None) still works for callers with no checkpoint",
              len(S._payload_triples(fat, None)) > len(p_fat))

        # ---- every real consumer still resolves ------------------------------------------------------
        deepest = POSW_DIFF_TRAIL * EPOCH_LENGTH
        check(f"the deepest consensus lookback ({deepest} blocks) is inside the num window",
              INDEX_RETENTION_NUM > deepest)
        check("the dedupe guard's horizon (FINALITY_DEPTH) is far inside the hash window",
              INDEX_RETENTION_HASH > FINALITY_DEPTH * 100)

        # ---- the LOCAL prune, against a real LMDB ----------------------------------------------------
        from genesis import create_indexers
        create_indexers()
        from ops import kv_ops
        TIP = 80_000
        # ONE write txn for the whole seed — 80k individual block_index_put calls is 80k txns and minutes
        def _fill(txn):
            dbs = kv_ops._dbs()
            for h in range(0, TIP + 1):
                bh = f"{h:064x}".encode()
                txn.put(be8(h), bh, db=dbs["block_by_num"])
                txn.put(bh, be8(h), db=dbs["block_by_hash"])
        kv_ops._write(_fill)
        check(f"seeded {TIP + 1} heights", kv_ops.hash_by_number(0) is not None
              and kv_ops.hash_by_number(TIP) is not None)

        # prune with small windows so the effect is visible on a short chain
        KN, KH = 20_000, 5_000
        total = {"num": 0, "hash": 0}
        for _ in range(60):                      # bounded per call; loop until it stops finding work
            got = kv_ops.prune_index_window(TIP, KN, KH, max_rows=4000)
            total["num"] += got["num"]; total["hash"] += got["hash"]
            if not got["num"] and not got["hash"]:
                break
        print(f"      pruned {total['num']} num rows, {total['hash']} hash rows")

        check("heights below the num window are gone", kv_ops.hash_by_number(TIP - KN - 100) is None)
        check("the num window boundary is KEPT", kv_ops.hash_by_number(TIP - KN + 10) is not None)
        check("the tip is kept", kv_ops.hash_by_number(TIP) is not None)
        check("heights below the hash window lose the REVERSE row",
              not kv_ops.block_hash_indexed(f"{TIP - KH - 100:064x}"))
        check("...while KEEPING their forward row (the deeper window still covers them)",
              kv_ops.hash_by_number(TIP - KH - 100) is not None)
        check("the hash window boundary is kept", kv_ops.block_hash_indexed(f"{TIP - KH + 10:064x}"))

        # THE TWO-WATERMARK LEAK: advance the tip so the deeper window catches up with heights whose hash
        # row is already gone. A shared watermark would have skipped past them for good.
        before = kv_ops.hash_by_number(TIP - KH - 100)
        for _ in range(60):
            got = kv_ops.prune_index_window(TIP + KN, KN, KH, max_rows=4000)
            if not got["num"] and not got["hash"]:
                break
        check("a later pass DOES collect num rows whose hash row went earlier",
              before is not None and kv_ops.hash_by_number(TIP - KH - 100) is None)

    print()
    print("ALL INDEX-PRUNING CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
