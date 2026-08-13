"""
INDEX RETENTION, END TO END: build a real snapshot, ship it, import it, and check the chain still works.

The unit test (test_index_pruning.py) pins the window arithmetic. This one exercises the path that would
actually break the fleet: build_snapshot -> chunks -> import_snapshot, across nodes that hold
DIFFERENT amounts of history. If a pruned node and an archive node disagree on one carried byte they
compute different snapshot_hash values for the same checkpoint, fail quorum, and the symptom is a fleet
that cannot onboard anyone — not an obvious pruning bug.

WHAT THIS RUNS, for real, against real LMDB environments:

  1. Two independent node homes at the SAME checkpoint C. One holds the index from genesis (archive), the
     other only a shallow tail (already pruned). Every other row is identical.
  2. Both call build_snapshot(). Their manifests must match BYTE FOR BYTE — state_root, state_digest,
     entry_count, snapshot_hash. This is the property the whole standard rests on.
  3. A THIRD, empty node imports the archive node's snapshot through import_snapshot() and must
     end up with exactly the windowed index — not the archive's deep history.
  4. The joiner can still answer the deepest lookback consensus actually performs.
  5. A MALICIOUS donor that appends out-of-window index rows (a forged deep anchor is a forged epoch
     beacon / PoSW anchor) must have them dropped, and the tampered payload must fail authentication.

Run: python3 tests/test_index_pruning_e2e.py
"""
import os
import shutil
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


def bh(h):
    return f"{h:064x}"


def build_home(root, name, index_from, index_to, C):
    """A node home whose index covers [index_from, index_to] and whose other state is identical."""
    home = os.path.join(root, name)
    os.makedirs(os.path.join(home, "nado"), exist_ok=True)
    os.environ["HOME"] = home
    import importlib
    from ops import kv_ops
    kv_ops._envs.clear()                       # a fresh env per home, not the previous one's cache
    from genesis import create_indexers
    create_indexers()

    def _fill(txn):
        dbs = kv_ops._dbs()
        for h in range(index_from, index_to + 1):
            txn.put(be8(h), bh(h).encode(), db=dbs["block_by_num"])
            txn.put(bh(h).encode(), be8(h), db=dbs["block_by_hash"])
        # identical non-index state on both nodes, so ANY manifest difference is the index.
        # Rows must be REAL codec values — read_state canonicalizes accounts and would choke on junk.
        from ops import codec
        for i in range(50):
            txn.put(f"addr{i:040d}".encode(),
                    codec.pack({"balance": 100 + i, "produced": i, "bonded": 0,
                                "registered": 1, "fidelity": 1}), db=dbs["accounts"])
        txn.put(b"total_supply", codec.pack(12345), db=dbs["meta"])
    kv_ops._write(_fill)
    return home


def main():
    root = tempfile.mkdtemp()
    try:
        C = 60_000
        from protocol import INDEX_RETENTION_NUM, INDEX_RETENTION_HASH, POSW_DIFF_TRAIL, EPOCH_LENGTH

        # ---- 1. two nodes, same checkpoint, very different history ---------------------------------
        arch = build_home(root, "archive", 0, C, C)                       # genesis -> C
        from ops import snapshot_ops as S
        from ops import kv_ops
        m_arch, chunks_arch = S.build_snapshot(C, bh(C), protocol=7, version="t", home=arch)

        # A CONFORMING pruned node keeps EXACTLY the window. The standard is both a floor and a ceiling
        # for the payload: keeping less cannot serve a matching snapshot, keeping more is filtered away.
        thin_from = C - INDEX_RETENTION_NUM
        thin = build_home(root, "pruned", thin_from, C, C)
        m_thin, chunks_thin = S.build_snapshot(C, bh(C), protocol=7, version="t", home=thin)

        print(f"      archive held heights 0..{C}, pruned node held {thin_from}..{C}")
        check("state_root matches across the two nodes", m_arch["state_root"] == m_thin["state_root"])
        check("state_digest matches — the carried payload is byte-identical",
              m_arch["state_digest"] == m_thin["state_digest"])
        check("entry_count matches", m_arch["entry_count"] == m_thin["entry_count"])
        check("snapshot_hash matches (this is what quorum agrees on)",
              m_arch.get("snapshot_hash") == m_thin.get("snapshot_hash"))

        # A node pruned BELOW the window cannot serve a conforming snapshot — it is missing rows the rule
        # says must be carried, so its digest differs and the quorum will not accept it as a donor. That is
        # the correct outcome, and worth pinning: it is the difference between "prunes to the standard" and
        # "prunes as much as it likes".
        over = build_home(root, "overpruned", C - (INDEX_RETENTION_NUM // 2), C, C)
        m_over, _ = S.build_snapshot(C, bh(C), protocol=7, version="t", home=over)
        check("a node pruned DEEPER than the window is not a valid donor (digest differs)",
              m_over["state_digest"] != m_arch["state_digest"])

        # ---- 2. the payload really is bounded, not just equal ---------------------------------------
        # An unbounded payload would carry C+1 num rows; the window carries INDEX_RETENTION_NUM+1.
        kv_ops._envs.clear()
        os.environ["HOME"] = arch
        triples = S.read_state(arch)
        payload = S._payload_triples(triples, C)
        n_num = sum(1 for t in payload if t[0] == "block_by_num")
        n_hash = sum(1 for t in payload if t[0] == "block_by_hash")
        check(f"payload carries {INDEX_RETENTION_NUM + 1} num rows, not {C + 1}",
              n_num == INDEX_RETENTION_NUM + 1)
        check(f"payload carries {INDEX_RETENTION_HASH + 1} hash rows", n_hash == INDEX_RETENTION_HASH + 1)
        unbounded = S._payload_triples(triples, None)
        saved = len(unbounded) - len(payload)
        print(f"      windowing dropped {saved} rows from a {C}-block chain "
              f"({100.0 * saved / max(1, len(unbounded)):.0f}% of the payload)")
        check("windowing actually removes rows at this chain length", saved > 0)

        # ---- 3. a fresh node imports it and ends up with the WINDOW, not the archive's history -------
        joiner = os.path.join(root, "joiner")
        os.makedirs(os.path.join(joiner, "nado"), exist_ok=True)
        os.environ["HOME"] = joiner
        kv_ops._envs.clear()
        from genesis import create_indexers
        create_indexers()

        class L:
            def info(self, *a): pass
            def warning(self, *a): pass
            def error(self, *a): print("        restore error:", *a)

        ok = S.import_snapshot(m_arch, chunks_arch, home=joiner, logger=L())
        check("the snapshot imports cleanly", bool(ok))
        if ok:
            check("joiner resolves the checkpoint height", kv_ops.hash_by_number(C) == bh(C))
            check("joiner resolves the num-window boundary",
                  kv_ops.hash_by_number(C - INDEX_RETENTION_NUM) == bh(C - INDEX_RETENTION_NUM))
            check("joiner did NOT receive history below the window",
                  kv_ops.hash_by_number(C - INDEX_RETENTION_NUM - 1) is None)
            check("joiner resolves the hash-window boundary",
                  kv_ops.block_hash_indexed(bh(C - INDEX_RETENTION_HASH)))
            check("joiner did NOT receive reverse rows below the hash window",
                  not kv_ops.block_hash_indexed(bh(C - INDEX_RETENTION_HASH - 1)))

            # ---- 4. the deepest lookback consensus performs still resolves --------------------------
            deepest = POSW_DIFF_TRAIL * EPOCH_LENGTH
            check(f"the deepest consensus lookback ({deepest} back) resolves on the joiner",
                  kv_ops.hash_by_number(C - deepest) == bh(C - deepest))

        # ---- 5. a MALICIOUS donor cannot smuggle out-of-window index rows ----------------------------
        # A forged block_by_num row IS a forged epoch-beacon / PoSW anchor, so the import re-derives the
        # window from the manifest's own snapshot_height rather than trusting what arrived.
        forged = [("block_by_num", be8(C - INDEX_RETENTION_NUM - 5000), b"e" * 64),
                  ("block_by_num", be8(C + 500), b"f" * 64)]          # deep past AND future
        kept = S._payload_triples(list(payload) + forged, C)
        check("injected out-of-window rows are dropped on import", len(kept) == len(payload))
        check("...so the digest is unchanged by the injection",
              S.state_digest(list(payload) + forged, C) == S.state_digest(payload, C))
        # and a row tampered INSIDE the window must still break authentication
        inside = [t for t in payload if t[0] == "block_by_num"][10]
        tampered = [(("block_by_num", inside[1], b"0" * 64) if t == inside else t) for t in payload]
        check("a row tampered INSIDE the window still fails the digest",
              S.state_digest(tampered, C) != S.state_digest(payload, C))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print()
    print("ALL INDEX-PRUNING E2E CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
