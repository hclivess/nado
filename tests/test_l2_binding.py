"""
L1<->L2 BINDING + REROLL wipe (the alphanet-7 reroll hardening):

  * Every L1 block commits the L1-JUSTIFIED settled L2 (exec_cursor, exec_root) INTO its hash, so the L2
    settled root is reorg-consistent and a relay cannot present a block carrying a root that isn't justified
    as-of-parent. The live per-block exec root can't be committed (the exec node lags by ~FINALITY_DEPTH in a
    separate process); the SETTLED root is the strongest per-block-available anchor, and it is already
    transitively bound via the settlement attestations inside state_root.
  * A CHAIN_GENERATION reroll must AUTHORITATIVELY wipe the exec layer at the paths the exec node actually
    uses (NADO_EXEC_STATE / NADO_EXEC_DA) — even when they sit OUTSIDE the node home — or a stale exec layer
    replays the fresh chain onto old state and forks L2.

Run: python3 tests/test_l2_binding.py
"""
import os, sys, tempfile, glob

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


def test_exec_root_in_block_hash():
    _fresh_home("nado_l2bind_")
    from ops import account_ops
    from ops.block_ops import construct_block, block_content_hash
    from ops.settlement_ops import settled_header_commitment
    from protocol import EXEC_GENESIS_ROOT

    account_ops.create_account("a", balance=100)

    # Empty chain: no settlement is justified, so the header commits the empty sentinel.
    c, r = settled_header_commitment()
    check("empty-chain settled commitment is the (-1, EXEC_GENESIS_ROOT) sentinel",
          c == -1 and r == EXEC_GENESIS_ROOT)

    blk = construct_block(block_timestamp=123, block_number=1, parent_hash="0" * 64,
                          creator="a", transaction_pool=[], block_reward=0)
    check("block commits the settled exec_root", blk["exec_root"] == EXEC_GENESIS_ROOT)
    check("block commits the settled exec_cursor", blk["exec_cursor"] == -1)
    check("block_content_hash reproduces the hash (exec_root + exec_cursor are in the preimage)",
          block_content_hash(blk) == blk["block_hash"])

    # Tampering EITHER the exec_root OR the exec_cursor breaks hash-consistency (save_block refuses it).
    t1 = dict(blk); t1["exec_root"] = "ab" * 32
    check("a tampered exec_root no longer hashes to its own block_hash", block_content_hash(t1) != t1["block_hash"])
    t2 = dict(blk); t2["exec_cursor"] = 999
    check("a tampered exec_cursor no longer hashes to its own block_hash", block_content_hash(t2) != t2["block_hash"])


def test_reroll_wipes_exec_paths_outside_home():
    home = _fresh_home("nado_l2reroll_")
    # Put the exec state + DA OUTSIDE the node home, exactly the --home-install layout the bug missed.
    ext = tempfile.mkdtemp(prefix="nado_exec_ext_")
    exec_state = os.path.join(ext, "exec_state.json")
    exec_state_ns = exec_state + ".shielded"
    exec_gen = exec_state + ".gen"
    exec_da = os.path.join(ext, "exec_da")
    for f in (exec_state, exec_state_ns, exec_gen):
        open(f, "w").write("stale")
    os.makedirs(exec_da, exist_ok=True)
    open(os.path.join(exec_da, "blob.bin"), "w").write("stale")

    os.environ["NADO_EXEC_STATE"] = exec_state
    os.environ["NADO_EXEC_DA"] = exec_da
    try:
        from ops.data_ops import purge_chain_data
        purge_chain_data()
        check("reroll wipes exec_state.json outside the home", not os.path.exists(exec_state))
        check("reroll wipes namespaced exec state (.shielded) outside the home", not os.path.exists(exec_state_ns))
        check("reroll wipes the exec generation marker (.gen)", not os.path.exists(exec_gen))
        check("reroll wipes the exec DA dir outside the home", not os.path.isdir(exec_da))
        # sanity: the L1 index is gone too (regular purge)
        check("reroll wipes the L1 index", not os.path.isdir(f"{home}/nado/index"))
    finally:
        os.environ.pop("NADO_EXEC_STATE", None)
        os.environ.pop("NADO_EXEC_DA", None)


if __name__ == "__main__":
    for t in (test_exec_root_in_block_hash, test_reroll_wipes_exec_paths_outside_home):
        print(f"\n--- {t.__name__} ---")
        t()
    print(f"\n{'ALL L2-BINDING CHECKS PASSED' if not fails else str(fails) + ' FAILED'}")
    sys.exit(1 if fails else 0)
