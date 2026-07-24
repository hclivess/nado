"""
STATE-ROOT BINDING (the alphanet-7 reroll hardening): the L1 block hash now COMMITS the as-of-parent L1
state root, so state is bound to L1 consensus — a node whose state diverged from the producer rejects the
block at validation instead of silently carrying a different state that only surfaces (with no tiebreak) at
snapshot sync. These tests prove the root is in the hash preimage and that mutating state changes the hash.

Run: python3 tests/test_state_root_binding.py
"""
import os, sys, tempfile, logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("srbind"); logger.addHandler(logging.NullHandler())
fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


def _fresh_home(prefix):
    from ops import kv_ops
    kv_ops.close_all()
    h = tempfile.mkdtemp(prefix=prefix)
    os.environ["HOME"] = h
    for d in ("index", "blocks", "logs", "peers", "snapshots"):
        os.makedirs(f"{h}/nado/{d}", exist_ok=True)
    from genesis import create_indexers
    create_indexers()
    return h


def test_state_root_in_block_hash():
    _fresh_home("nado_srbind_")
    from ops import account_ops
    from ops.block_ops import construct_block, block_content_hash
    from ops.snapshot_ops import read_state, merkle_root

    account_ops.create_account("a", balance=100)
    expected = merkle_root(read_state())

    blk = construct_block(block_timestamp=123, block_number=1, parent_hash="0" * 64,
                          creator="a", transaction_pool=[], block_reward=0)
    check("block commits the current as-of-parent L1 state_root", blk["state_root"] == expected)
    check("block_content_hash reproduces the block hash (state_root is in the preimage)",
          block_content_hash(blk) == blk["block_hash"])

    # Tampering the committed root breaks hash-consistency -> save_block refuses it (anti-fork invariant).
    tampered = dict(blk); tampered["state_root"] = "de" * 32
    check("a tampered state_root no longer hashes to its own block_hash", block_content_hash(tampered) != tampered["block_hash"])

    # Mutating L1 state changes the committed root AND therefore the block hash — state is bound to the hash.
    account_ops.change_balance("a", 50, logger)
    blk2 = construct_block(block_timestamp=123, block_number=1, parent_hash="0" * 64,
                           creator="a", transaction_pool=[], block_reward=0)
    check("mutating L1 state changes the committed state_root", blk2["state_root"] != blk["state_root"])
    check("...and therefore changes the block hash (state bound to the L1 hash)",
          blk2["block_hash"] != blk["block_hash"])

    # The committed root equals the snapshot state_root (same merkle over SNAPSHOT_DBS) — L1 hash and
    # snapshot hash can never disagree for nodes that agree on the block.
    check("committed state_root == snapshot state_root (same canonical merkle)",
          blk2["state_root"] == merkle_root(read_state()))


if __name__ == "__main__":
    test_state_root_in_block_hash()
    print(f"\n{'ALL STATE-ROOT-BINDING CHECKS PASSED' if not fails else str(fails) + ' FAILED'}")
    sys.exit(1 if fails else 0)
