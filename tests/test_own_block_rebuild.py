"""
OWN-BLOCK PRODUCTION vs the hash-consistency invariant (the 120-230s block-gap wedge).

construct_block hashes the tx set immediately; verify_block used to DROP an invalid pool tx (stale
duplicate attest/reveal) from block["block_transactions"] AFTER that, so save_block's anti-fork
invariant refused the node's OWN block every slot until the stale tx aged out — observed as blocks
"taking 120s+" (refused window + retry). This proves: (1) a freshly constructed block satisfies the
invariant; (2) a post-hash tx drop breaks it and save_block refuses BEFORE touching disk; (3) the
deterministic rebuild (same parent/timestamp, surviving txs) restores it; (4) the pending-reserved-tx
guard that stops the node minting duplicate attest/commit/reveal txs every loop iteration.

Run: python3 tests/test_own_block_rebuild.py
"""
import os, sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops.block_ops import construct_block, block_content_hash, save_block
from loops.core_loop import CoreClient

fails = 0
def check(name, cond):
    """Print PASS/FAIL for boolean cond and count failures."""
    global fails
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond: fails += 1

class _Logger:
    def error(self, *a, **k):
        """Swallow error logs (no-op stub for save_block)."""
        pass
    def warning(self, *a, **k):
        """Swallow warning logs (no-op stub for save_block)."""
        pass
    def info(self, *a, **k):
        """Swallow info logs (no-op stub for save_block)."""
        pass

def _tx(txid, fee=1):
    """Build a minimal transaction dict with the given txid and fee."""
    return {"txid": txid, "fee": fee, "sender": "ndoAA", "recipient": "ndoBB", "amount": 0}

def _mk_block(txs):
    """Construct block 42 with fixed parent/timestamp/fees and the given tx set."""
    return construct_block(block_timestamp=1783190000, block_number=42,
                           parent_hash="ab" * 32, creator="ndoAA",
                           transaction_pool=list(txs), block_reward=100,
                           parent_cumulative_fees=7, parent_cumulative_weight=9, block_weight=3)

# (1) a freshly constructed block is hash-consistent
txs = [_tx("cc" * 32), _tx("dd" * 32)]
block = _mk_block(txs)
check("freshly constructed block satisfies the invariant",
      block_content_hash(block) == block["block_hash"])

# (2) dropping a tx after hashing (the old verify_block behavior on own candidates) breaks it,
#     and save_block REFUSES the block by raising before any disk write
block["block_transactions"] = [t for t in block["block_transactions"] if t["txid"] != "dd" * 32]
check("post-hash tx drop breaks the invariant",
      block_content_hash(block) != block["block_hash"])
refused = False
try:
    save_block(block, _Logger())
except ValueError:
    refused = True
check("save_block refuses the mutated own block (raises, no disk write)", refused)

# (3) the deterministic rebuild from the surviving tx set restores consistency; the rebuilt
#     hash differs from the stale one (it commits to the REAL content, incl. cumulative_fees)
stale_hash = block["block_hash"]
rebuilt = _mk_block(block["block_transactions"])
check("rebuild restores the invariant", block_content_hash(rebuilt) == rebuilt["block_hash"])
check("rebuilt hash differs from the stale pre-drop hash", rebuilt["block_hash"] != stale_hash)
check("rebuilt cumulative_fees reflects the surviving tx set only",
      rebuilt["cumulative_fees"] == 7 + 1)

# (4) the pending-reserved-tx guard: an attest for the same (sender, epoch) already in ANY
#     pool/buffer suppresses minting a duplicate; other epochs/senders don't
core = object.__new__(CoreClient)  # no thread/node init needed; the method only reads memserver pools
pending = {"recipient": "attest", "sender": "ndoME", "data": {"target_epoch": 5}}
core.memserver = SimpleNamespace(address="ndoME", transaction_pool=[], tx_buffer=[pending],
                                 user_tx_buffer=[])
check("pending attest for same epoch is detected", core._reserved_tx_pending("attest", 5))
check("different epoch is not blocked", not core._reserved_tx_pending("attest", 6))
check("different reserved type is not blocked", not core._reserved_tx_pending("reveal", 5))
core.memserver.address = "ndoOTHER"
check("someone else's pending attest does not block ours", not core._reserved_tx_pending("attest", 5))

print(f"\n{'ALL OWN-BLOCK REBUILD CHECKS PASSED' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
