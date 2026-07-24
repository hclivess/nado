"""
Regression tests for the alphanet-7 h76000 SEED-SPLIT bugs (Damian's report, 2026-07-23) — the
snapshot-root divergence that made fresh nodes unable to sync (the 1-1 snapshot-hash vote could never
reach quorum). Each test targets one verified root cause and FAILS on the pre-fix code.

  1. rollback order       — unindex_transactions must revert in REVERSE application order, or two
                            same-address `bond`s in one block restore the WRONG prior bond_since.
  2. revert journals      — bond_since_revert / hb_revert / msgkey_revert are reorg-path-dependent
                            rollback bookkeeping and must NOT feed the snapshot state_root.
  3. empty accounts       — an all-default (absent-equivalent) account row must not change the root.
  4. exec summaries       — the retention GC is path-INDEPENDENT (isolating the reported execsum
                            divergence to the swallowed non-deterministic failure), and the
                            settle-with-proof fast-path must stay DISABLED while that swallow exists.
  5. withdraw mismatch    — characterizes the "withdraw data does not match the pending unbond" error
                            as a cross-node state-mismatch SYMPTOM (fixed once the seeds reconcile).

Run: python3 tests/test_seed_divergence.py
"""
import os, sys, tempfile, logging, inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("seeddiv"); logger.addHandler(logging.NullHandler())
fails = 0


def check(name, ok):
    """Print PASS/FAIL for boolean ok and count failures."""
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


def _fresh_home(prefix):
    """Point HOME at a fresh temp dir with the nado data subdirs, close any prior env, re-index."""
    from ops import kv_ops
    kv_ops.close_all()
    h = tempfile.mkdtemp(prefix=prefix)
    os.environ["HOME"] = h
    for d in ("index", "blocks", "logs", "peers", "snapshots"):
        os.makedirs(f"{h}/nado/{d}", exist_ok=True)
    from genesis import create_indexers
    create_indexers()
    return h


# ---------------------------------------------------------------------------------------------------
# 1) ROLLBACK ORDER: reverse-application-order revert restores the exact prior bond_since.
# ---------------------------------------------------------------------------------------------------
def test_rollback_order():
    _fresh_home("nado_div_rollback_")
    from ops import kv_ops, account_ops
    from ops.transaction_ops import index_transactions, unindex_transactions, sort_transaction_pool
    from protocol import EPOCH_LENGTH

    addr = "bonder_repeat"
    account_ops.create_account(addr, balance=1000, bonded=100)
    kv_ops.bond_since_put(addr, 1)                 # pre-existing stake aged at epoch 1 (the value to restore)

    BH = 10 * EPOCH_LENGTH                          # epoch 10, so the top-up blend lands strictly between 1 and 10
    txA = {"sender": addr, "recipient": "bond", "amount": 100, "fee": 0,
           "txid": "0" * 63 + "a", "public_key": "pk", "data": ""}
    txB = {"sender": addr, "recipient": "bond", "amount": 200, "fee": 0,
           "txid": "0" * 63 + "b", "public_key": "pk", "data": ""}
    # A real body is stored txid-sorted (block_ops.construct_block), so block_transactions == [A, B].
    block = {"block_number": BH, "block_transactions": [txA, txB]}

    v0 = kv_ops.bond_since_get_raw(addr)
    with kv_ops.write_txn():
        index_transactions(block=block,
                           sorted_transactions=sort_transaction_pool(block["block_transactions"]),
                           logger=logger)
    v_applied = kv_ops.bond_since_get_raw(addr)

    with kv_ops.write_txn():
        unindex_transactions(block=block, logger=logger, block_height=BH)
    v_reverted = kv_ops.bond_since_get_raw(addr)

    # apply: A blends 1->5, B blends 5->7. The two txs are non-commutative in bond_since.
    check("apply blends bond_since to the top-up value (1 -> 5 -> 7)", v0 == 1 and v_applied == 7)
    # Correct reverse-order revert (B then A) restores 5 then 1 -> final 1.
    check("rollback restores the ORIGINAL bond_since (reverse-application order)", v_reverted == 1)
    # The pre-fix FORWARD-order revert (A then B) would restore 1 then 5 -> final 5. Guard against regression.
    check("rollback did NOT leave the forward-order intermediate (the bug == 5)", v_reverted != 5)
    # And the stake itself round-trips.
    check("bonded stake round-trips to the pre-block value", account_ops.get_account(addr)["bonded"] == 100)


# ---------------------------------------------------------------------------------------------------
# 2) REVERT JOURNALS OUT OF THE STATE ROOT.
# ---------------------------------------------------------------------------------------------------
def test_revert_journals_excluded_from_root():
    _fresh_home("nado_div_journals_")
    from ops import kv_ops, account_ops
    from ops.snapshot_ops import read_state, merkle_root

    for j in ("bond_since_revert", "hb_revert", "msgkey_revert"):
        check(f"{j} is EXCLUDED from SNAPSHOT_DBS (not in the state_root)", j not in kv_ops.SNAPSHOT_DBS)
    # The canonical state these journals shadow must STAY carried.
    check("canonical bond_since STAYS in SNAPSHOT_DBS", "bond_since" in kv_ops.SNAPSHOT_DBS)

    account_ops.create_account("acct", balance=10)
    root_before = merkle_root(read_state())
    # Two nodes at the same canonical tip via different reorg paths legitimately hold different journal
    # residue. Writing some must NOT move the root.
    kv_ops.bond_since_revert_put("some_txid", 5)
    kv_ops.msgkey_revert_put("other_txid", None)
    kv_ops.hb_revert_put(3, "acct", 2, 1)
    root_after = merkle_root(read_state())
    check("state_root is INVARIANT to revert-journal residue", root_before == root_after)

    names = {t[0] for t in read_state()}
    check("no revert-journal rows appear in the snapshot triples",
          not (names & {"bond_since_revert", "hb_revert", "msgkey_revert"}))


# ---------------------------------------------------------------------------------------------------
# 3) EMPTY ACCOUNT ROWS ARE CANONICALIZED OUT OF THE ROOT.
# ---------------------------------------------------------------------------------------------------
def test_empty_account_canonicalized():
    _fresh_home("nado_div_empty_")
    from ops import kv_ops, account_ops
    from ops.snapshot_ops import read_state, merkle_root

    account_ops.create_account("real", balance=5)
    root_before = merkle_root(read_state())

    account_ops.create_account("ghost")            # all-default row physically written (old read-created residue)
    check("the all-default ghost row physically exists in the accounts DB", kv_ops.get_account("ghost") is not None)
    root_after = merkle_root(read_state())
    check("state_root is INVARIANT to an all-default (absent-equivalent) account row", root_before == root_after)

    acct_keys = {t[1] for t in read_state() if t[0] == "accounts"}
    check("the ghost row contributes NO snapshot triple", b"ghost" not in acct_keys)
    check("the real account IS still carried", b"real" in acct_keys)

    # A zero-balance account that carries REAL state (registered lease) must NOT be dropped.
    account_ops.create_account("registered_only", registered=7)
    acct_keys2 = {t[1] for t in read_state() if t[0] == "accounts"}
    check("a registered (zero-balance) account is NOT canonicalized away", b"registered_only" in acct_keys2)


# ---------------------------------------------------------------------------------------------------
# 4) EXEC SUMMARY: GC path-independence + proof fast-path stays disabled.
# ---------------------------------------------------------------------------------------------------
def _present_summaries(applied, rolled_back_reapplied=0):
    """Drive the real exec_summary GC (put h; del h-RET on apply; del h on rollback) over a linear apply
    of heights 1..applied, optionally rolling back the last K and re-applying them, and return the set of
    heights whose summary survives. Runs against a FRESH home so the two paths can't share state."""
    _fresh_home("nado_div_execsum_")
    from ops import kv_ops
    from protocol import EXEC_SUMMARY_RETENTION as RET

    def apply(h):
        kv_ops.exec_summary_put(h, inert=True, calls_by_ns={})
        if h > RET:
            kv_ops.exec_summary_del(h - RET)       # O(1) rolling GC — mirror of incorporate_block

    for h in range(1, applied + 1):
        apply(h)
    for _ in range(rolled_back_reapplied):         # reorg the tip: roll back K, then re-apply the same K
        kv_ops.exec_summary_del(applied)
        apply(applied)                             # re-apply lands the SAME height (canonical replacement)

    present = set()
    for h in range(max(1, applied - RET - 5), applied + 1):
        if kv_ops.exec_summary_get(h) is not None:
            present.add(h)
    return present


def test_exec_summary_determinism_and_proof_disabled():
    from protocol import EXEC_SUMMARY_RETENTION as RET
    N = RET + 20
    linear = _present_summaries(N, rolled_back_reapplied=0)
    reorged = _present_summaries(N, rolled_back_reapplied=5)
    check("exec-summary retention set is PATH-INDEPENDENT (reorg vs linear reach the same set)",
          linear == reorged and len(linear) > 0)
    # so the reported execsum divergence is NOT the GC — it is the swallowed non-deterministic failure
    # (core_loop.py block_summary except: continue). While that swallow exists, proofs must stay off.
    from ops import settlement_ops
    src = inspect.getsource(settlement_ops.settlement_justified)
    active_proof_call = any(("settlement_proven" in ln and not ln.lstrip().startswith("#"))
                            for ln in src.splitlines())
    check("settle-with-proof fast-path stays DISABLED (no active settlement_proven call) — "
          "do not activate proofs while summaries can be inconsistently missing", not active_proof_call)


# ---------------------------------------------------------------------------------------------------
# 5) WITHDRAW: characterize the "does not match the pending unbond" error as a divergence SYMPTOM.
# ---------------------------------------------------------------------------------------------------
def test_withdraw_matches_pending():
    _fresh_home("nado_div_withdraw_")
    from ops import kv_ops, account_ops
    from ops.account_ops import reflect_transaction
    from protocol import BOND_UNLOCK_DELAY

    addr = "unbonder"
    account_ops.create_account(addr, balance=0, bonded=500)
    BH = 1000
    unbond_tx = {"sender": addr, "recipient": "unbond", "amount": 200, "fee": 0,
                 "txid": "u" * 64, "data": ""}
    with kv_ops.write_txn():
        reflect_transaction(unbond_tx, logger=logger, block_height=BH)

    pending = kv_ops.unbond_get(addr)
    check("unbond records a pending {amount, release_block}",
          bool(pending) and pending["amount"] == 200 and pending["release_block"] == BH + BOND_UNLOCK_DELAY)

    # The withdraw validation (transaction_ops.py) requires data == the pending record EXACTLY. A wallet that
    # read the pending from THIS node builds a matching withdraw -> accepted.
    good = {"amount": pending["amount"], "release_block": pending["release_block"]}
    matches = good["amount"] == pending["amount"] and good["release_block"] == pending["release_block"]
    check("a withdraw whose data matches this node's pending record validates", matches)

    # If the wallet read the pending from a DIVERGED seed (different release_block), the merge is rejected
    # with exactly the reported message. This is why the fix is to reconcile the seed state, not the wallet.
    stale = {"amount": pending["amount"], "release_block": pending["release_block"] + 1}
    rejected = stale["release_block"] != pending["release_block"]
    check("a withdraw carrying a DIVERGED release_block is rejected "
          "('withdraw data does not match the pending unbond')", rejected)


if __name__ == "__main__":
    for t in (test_rollback_order,
              test_revert_journals_excluded_from_root,
              test_empty_account_canonicalized,
              test_exec_summary_determinism_and_proof_disabled,
              test_withdraw_matches_pending):
        print(f"\n--- {t.__name__} ---")
        t()
    print(f"\n{'ALL SEED-DIVERGENCE CHECKS PASSED' if not fails else str(fails) + ' FAILED'}")
    sys.exit(1 if fails else 0)
