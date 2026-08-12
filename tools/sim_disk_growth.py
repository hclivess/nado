"""
Disk-usage growth model for a NADO node — what actually grows, what plateaus, and when.

The rates below are MEASURED on a live betanet node (height 16 678, 4 669 txs, 134 accounts), not
estimated: per-sub-DB byte totals came from walking each LMDB store, and the body figure from the blocks
directory. Re-measure with `--measure` on any node to refresh them.

THREE MODES:

  * ARCHIVE (`archive: True` — the DEFAULT) keeps ALL block bodies and ALL tx history forever.
  * ROLLING (`archive: False`) drops finalized bodies older than history_retention_blocks (100 800 =
    7 days at 6 s), and now ALSO prunes the tx history to tx_history_retention_blocks (floored at
    TX_HISTORY_MIN_RETENTION = 5000 blocks, ~8 h — the replay guard's horizon plus margin).
  * ROLLING, BODIES ONLY — what rolling mode used to be, kept here to show what the tx-history half buys.

What NO mode prunes, and is therefore the floor on every node:

  * the number<->hash index, 144 B/block, forever. Beacon anchors, FFG epoch boundaries and PoSW anchors
    resolve through it — including for heights before a snapshot — so it is deliberately kept in all
    modes. On a fully-pruned node this becomes the DOMINANT term: it grows with height even on an
    idle chain, and nothing bounds it.

A SNAPSHOT-SYNCED node is the genuinely small one: it never receives pre-checkpoint bodies or tx history
at all (both are excluded from snapshots), so it starts near zero and grows from its checkpoint forward.

Run:  python3 tools/sim_disk_growth.py            # model from the measured constants
      python3 tools/sim_disk_growth.py --measure  # re-measure this node first (needs HOME set to it)
"""
import sys

# ---- MEASURED CONSTANTS (betanet-2 node, height 16 678) ---------------------------------------------
# Permanent per-BLOCK index: block_by_num + block_by_hash, 72 B/row each. Kept forever by design —
# prune_block_bodies explicitly retains the number<->hash index so hash lookbacks still resolve.
PERM_PER_BLOCK = 72 + 72

# Permanent per-TX history: tx (164) + tx_by_sender (118) + tx_by_recipient (78). Never pruned.
PERM_PER_TX = 164 + 118 + 78

# One account row, dominated by the 1312-byte ML-DSA public key it stores.
PER_ACCOUNT = 3229

# Block BODY bytes on disk per block, measured across a mostly-idle chain (83 MiB / 16 662 blocks).
# This is the FLOOR: a block carrying transactions costs this plus the transactions themselves.
BODY_PER_BLOCK_IDLE = 5222
BODY_PER_TX = 250                    # marginal body bytes a transaction adds

# Roughly fixed overheads seen on the live node.
SNAPSHOTS_MIB = 12                   # checkpoint retention keeps a bounded set
EXEC_STATE_MIB = 4                   # exec_state.json, grows with contracts/assets rather than height
EXEC_STASH_MIB = 23                  # ~6 retained stash files

BLOCK_TIME = 6
HISTORY_RETENTION_BLOCKS = 100800    # protocol.py — bodies older than this are dropped (7 days at 6 s)
BLOCKS_PER_DAY = 86400 // BLOCK_TIME


TX_HISTORY_MIN_RETENTION = 5000      # protocol.py — the enforced floor on the tx-history window


def model(days, tx_per_block, accounts, archive=True, prune_tx=True):
    """Bytes on disk after `days`, at a steady `tx_per_block` and a final account count.

    archive=True (the DEFAULT) keeps every body and all tx history. archive=False caps bodies at the
    retention window and, when prune_tx, caps the tx history at TX_HISTORY_MIN_RETENTION. The per-block
    number<->hash index is never pruned in any mode."""
    height = BLOCKS_PER_DAY * days
    txs = height * tx_per_block

    bodies_blocks = height if archive else min(height, HISTORY_RETENTION_BLOCKS)
    bodies = bodies_blocks * (BODY_PER_BLOCK_IDLE + tx_per_block * BODY_PER_TX)

    tx_blocks = height if (archive or not prune_tx) else min(height, TX_HISTORY_MIN_RETENTION)
    perm_blocks = height * PERM_PER_BLOCK                          # unbounded in EVERY mode
    perm_txs = tx_blocks * tx_per_block * PERM_PER_TX
    state = accounts * PER_ACCOUNT
    fixed = (SNAPSHOTS_MIB + EXEC_STATE_MIB + EXEC_STASH_MIB) * 1024 * 1024
    return {"height": height, "txs": txs, "bodies": bodies, "perm_blocks": perm_blocks,
            "perm_txs": perm_txs, "state": state, "fixed": fixed,
            "total": bodies + perm_blocks + perm_txs + state + fixed}


def gib(b):
    return b / (1024 ** 3)


def mib(b):
    return b / (1024 ** 2)


def fmt(b):
    return f"{gib(b):8.2f} GiB" if b >= 1024 ** 3 else f"{mib(b):8.0f} MiB"


SCENARIOS = [
    ("idle (today's load)", 0.3, lambda d: 134 + d * 2),
    ("light   (2 tx/block)", 2, lambda d: 1000 + d * 20),
    ("busy   (20 tx/block)", 20, lambda d: 20000 + d * 200),
    ("heavy (100 tx/block)", 100, lambda d: 100000 + d * 1000),
]
HORIZONS = [30, 90, 365, 365 * 3, 365 * 10]


def main():
    if "--measure" in sys.argv:
        measure_live()
        return
    print("NADO node disk growth — measured rates, modelled forward")
    print(f"  block time {BLOCK_TIME}s -> {BLOCKS_PER_DAY:,} blocks/day; ROLLING mode prunes bodies past "
          f"{HISTORY_RETENTION_BLOCKS:,} blocks ({HISTORY_RETENTION_BLOCKS/BLOCKS_PER_DAY:.0f} days); ARCHIVE (default) keeps them all")
    print(f"  permanent: {PERM_PER_BLOCK} B/block + {PERM_PER_TX} B/tx; account {PER_ACCOUNT} B\n")
    for name, tpb, acct in SCENARIOS:
        print(f"{name}")
        print(f"  {'horizon':>9} {'height':>12} {'ARCHIVE':>13} {'ROLL(bodies)':>13} "
              f"{'ROLL(+tx)':>13} {'blk index':>12}")
        for d in HORIZONS:
            a = model(d, tpb, acct(d), archive=True)
            rb = model(d, tpb, acct(d), archive=False, prune_tx=False)
            rt = model(d, tpb, acct(d), archive=False, prune_tx=True)
            label = f"{d//365}y" if d >= 365 else f"{d}d"
            print(f"  {label:>9} {a['height']:>12,} {fmt(a['total'])} {fmt(rb['total'])} "
                  f"{fmt(rt['total'])} {fmt(a['perm_blocks'])}")
        print()
    a = model(365 * 10, 20, 20000 + 365 * 10 * 200, archive=True)
    rb = model(365 * 10, 20, 20000 + 365 * 10 * 200, archive=False, prune_tx=False)
    rt = model(365 * 10, 20, 20000 + 365 * 10 * 200, archive=False, prune_tx=True)
    print("Busy chain (20 tx/block) at 10 years:")
    print(f"  archive                {fmt(a['total'])}")
    print(f"  rolling, bodies only   {fmt(rb['total'])}   <- what rolling mode used to give")
    print(f"  rolling + tx pruning   {fmt(rt['total'])}   <- now")
    print(f"  Of that {fmt(rt['total'])}, {fmt(rt['perm_blocks'])} is the number<->hash index, which NO mode")
    print("  prunes. It is now the dominant term and the real floor on a pruned node.")


def measure_live():
    """Re-derive the constants from THIS node (HOME must point at its data dir)."""
    sys.path.insert(0, "/srv/nado-home/nado")
    from ops import kv_ops
    kv_ops.init_env()
    names = ("accounts", "tx", "tx_by_sender", "tx_by_recipient", "block_by_num", "block_by_hash")

    def walk(txn):
        d = kv_ops._dbs()
        out = {}
        for n in names:
            if n not in d:
                continue
            cnt = tot = 0
            for k, v in txn.cursor(d[n]):
                tot += len(k) + len(v)
                cnt += 1
            out[n] = (cnt, tot)
        return out

    r = kv_ops._read(walk)
    print(f"  {'store':18} {'rows':>8} {'bytes':>12} {'B/row':>8}")
    for n, (c, b) in sorted(r.items(), key=lambda x: -x[1][1]):
        print(f"  {n:18} {c:>8} {b:>12,} {b // max(c, 1):>8}")
    print("\nUpdate the constants at the top of this file from the B/row column.")


if __name__ == "__main__":
    main()
