"""
GENESIS-SYNC INVARIANT (regression guard for the "fresh node can't sync from genesis" wedge).

A fresh node re-derives every historical block through construct_block / block_content_hash and demands the
result reproduce the stored block_hash (loops.core_loop.produce_block, "hash mismatch ... would fork us").
So ANY consensus-identity field that a re-derivation reads from a *live constant* — rather than from the
block itself or a height-gated schedule — silently breaks sync-from-genesis the moment that constant changes.
This exact bug shipped: renaming the CHAIN_ID constant (nado-relaunch-3 -> alphanet-1) made every re-derived
historical block hash to a new value, so a fresh node rejected block 1.

This test locks in the fix + guards the general property:
  1. A block's hash + authorship-signature message are INVARIANT to chain_id (it is informational only).
  2. block_content_hash is self-consistent for a constructed block.
  3. A simulated from-genesis re-derivation reproduces stored hashes even when the CHAIN_ID constant has
     changed since the blocks were minted — the thing that actually broke.
If someone later folds chain_id (or any other live constant) back into the block hash, (1)/(3) fail here.

Run: python3 tests/test_genesis_sync_invariant.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ops.block_ops as bo
from ops.block_ops import construct_block, block_content_hash, block_signature_message

fails = 0
def check(name, cond):
    global fails
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond: fails += 1

CREATOR = "ndo" + "1" * 46
def mk(parent_hash, n, chain_id, ts=1000 + 0):
    return construct_block(block_timestamp=1000 + n, block_number=n, parent_hash=parent_hash,
                           creator=CREATOR, transaction_pool=[], block_reward=100,
                           parent_cumulative_fees=0, parent_cumulative_weight=n - 1, block_weight=1,
                           chain_id=chain_id)

# (1) hash + signature message are invariant to chain_id
a = mk("aa" * 32, 5, "old-name")
b = mk("aa" * 32, 5, "brand-new-name")
check("block hash invariant to chain_id", a["block_hash"] == b["block_hash"])
check("authorship-signature message invariant to chain_id",
      block_signature_message(a) == block_signature_message(b))
check("chain_id label is still carried on the block", a["chain_id"] == "old-name" and b["chain_id"] == "brand-new-name")

# (2) self-consistency
check("block_content_hash reproduces the stored hash", block_content_hash(a) == a["block_hash"])

# (3) SIMULATE the sync wedge: build a short chain under one chain_id, record hashes, then "rename" the
#     CHAIN_ID constant and re-derive every block (as a fresh node would) — hashes MUST still match.
genesis_hash = "00" * 32
chain, parent = [], genesis_hash
bo.CHAIN_ID = "chain-v1"                                  # constant at mint time
for n in range(1, 8):
    blk = mk(parent, n, bo.CHAIN_ID)
    chain.append(blk); parent = blk["block_hash"]
stored = [blk["block_hash"] for blk in chain]

bo.CHAIN_ID = "chain-v2-renamed"                          # operator renames the network (constant change)
ok = True
parent = genesis_hash
for n, orig in enumerate(chain, start=1):
    # a fresh node re-derives from ITS current constant; hash must reproduce the stored one
    rebuilt = mk(parent, n, bo.CHAIN_ID)
    if rebuilt["block_hash"] != stored[n - 1]:
        ok = False
    # also: validating the ORIGINAL stored block (built under v1) must still pass under v2
    if block_content_hash(orig) != orig["block_hash"]:
        ok = False
    parent = orig["block_hash"]
check("from-genesis re-derivation reproduces all hashes after a chain_id rename", ok)

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
