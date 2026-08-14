"""
NO NODE-LOCAL VALUE MAY ENTER THE L1 CONSENSUS ROOT — checked structurally, not by memory.

THE INCIDENT (2026-08-14, betanet-3). The number<->hash index prune wrote two watermarks into the `meta`
sub-DB — index_pruned_below_num and index_pruned_below_hash — and nobody added them to
snapshot_ops.ROOT_EXCLUDED_META_KEYS. `meta` feeds the L1 state root, so a node's DISK RETENTION PROGRESS
became consensus state.

The fleet split at block 10047, and the height is not a coincidence: the index prune first fires when
finality crosses INDEX_RETENTION_HASH = 10 000. At that moment every ROLLING node wrote the watermark and
its committed root moved; every ARCHIVE node never prunes, never wrote the row, computed the old root, and
correctly refused to extend. Both sides behaved correctly given their inputs. Proven by replay: with the
row excluded the root is c55b376f31ee1296, with it included 00f00a01e387ccf3 — bit-for-bit the root
committed in block 10047.

WHY THE EXISTING TEST DID NOT CATCH IT. test_seed_divergence asserted

    ROOT_EXCLUDED_META_KEYS == frozenset((b"finalized_height", b"pruned_below"))

which is a LITERAL. A literal only fails once someone has already remembered to add the new key — the
very act it was supposed to enforce. It cannot catch the omission it exists for. (That check is now
containment plus a behavioural assertion; this file adds the structural half.)

WHAT THIS PINS. Every meta key written by a PRUNE/RETENTION path is, by definition, a function of local
disk policy rather than of the applied block sequence — so it must be excluded from the root. Rather than
trusting anyone to remember, this reads ops/kv_ops.py, extracts the meta keys written inside functions
whose names mark them as retention work, and requires each one to be excluded. A future
`prune_whatever_window` that stashes a new watermark fails here on the day it is written.
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  — " + detail) if detail and not cond else ""))
    if not cond:
        _fails.append(name)


# Functions whose writes are retention/pruning progress rather than block-derived state.
_LOCAL_FN = re.compile(r"^def\s+((?:prune|gc|reclaim|compact)_\w+)", re.M)
# Every way a watermark key literal reaches a meta write in kv_ops: the module helper, the in-txn setter,
# and the sweep helper that takes the key by name (which is how prune_index_window spells it — matching
# only the setters missed both of the keys that caused the incident).
_META_WRITE = re.compile(r"""(?:meta_set_int|_mark_set|_mark_get|_sweep)\(\s*["']([a-z0-9_:]+)["']""")


def main():
    with tempfile.TemporaryDirectory() as d:
        os.environ["HOME"] = d
        os.makedirs(os.path.join(d, "nado"), exist_ok=True)
        from ops.snapshot_ops import ROOT_EXCLUDED_META_KEYS, ROOT_EXCLUDED_META_PREFIXES
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(root, "ops", "kv_ops.py")).read()

        # ---- carve kv_ops into top-level functions, keep the retention ones ---------------------------
        bounds = [(m.start(), m.group(1)) for m in re.finditer(r"^def\s+(\w+)", src, re.M)]
        bodies = {}
        for i, (pos, name) in enumerate(bounds):
            end = bounds[i + 1][0] if i + 1 < len(bounds) else len(src)
            bodies[name] = src[pos:end]

        local_fns = [n for n in bodies if _LOCAL_FN.match(bodies[n].split("\n")[0] + "\n")]
        check("kv_ops has retention/prune functions to inspect", bool(local_fns),
              "found none — did they move out of kv_ops?")
        print(f"      retention functions: {sorted(local_fns)}")

        def excluded(key: bytes) -> bool:
            return key in ROOT_EXCLUDED_META_KEYS or key.startswith(tuple(ROOT_EXCLUDED_META_PREFIXES))

        found_any = False
        for fn in sorted(local_fns):
            for key in sorted(set(_META_WRITE.findall(bodies[fn]))):
                found_any = True
                check(f"{fn}() writes meta '{key}' — must be excluded from the root",
                      excluded(key.encode()),
                      "a disk-retention value in the consensus root splits rolling from archive nodes")
        check("at least one retention watermark was actually inspected", found_any,
              "the extractor matched nothing — it has rotted, fix the regex not this assert")

        # ---- and the two that caused the incident, by name --------------------------------------------
        for key in (b"index_pruned_below_num", b"index_pruned_below_hash", b"pruned_below",
                    b"finalized_height"):
            check(f"'{key.decode()}' is excluded", excluded(key))

        # ---- the BEHAVIOURAL half: pruning progress must not move the root ----------------------------
        from genesis import create_indexers
        create_indexers()
        from ops import kv_ops
        from ops.account_ops import create_account
        from ops.snapshot_ops import l1_state_root

        create_account("a", balance=100)
        base = l1_state_root()
        for fn in sorted(local_fns):
            for key in sorted(set(_META_WRITE.findall(bodies[fn]))):
                kv_ops.meta_set_int(key, 4242)
        check("a node that has pruned computes the SAME root as one that has not",
              l1_state_root() == base)
        for fn in sorted(local_fns):
            for key in sorted(set(_META_WRITE.findall(bodies[fn]))):
                kv_ops.meta_set_int(key, 999_999)
        check("...and the root does not move as pruning PROGRESSES", l1_state_root() == base)

        # a block-DERIVED meta row must still count, or the exclusion has gone too far and the root
        # has stopped binding real state
        kv_ops.meta_set_int("some_block_derived_guard", 7)
        check("a block-derived meta row DOES still move the root (exclusion is not blanket)",
              l1_state_root() != base)

    print()
    print("ALL LOCAL-STATE-IN-ROOT CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
