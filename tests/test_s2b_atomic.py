"""
S2b atomicity + KV-migration unit checks (LMDB index, doc/storage-kv-migration.md).

Covers: one env with all named sub-DBs; write_txn() commits-all / rolls-back-all (the single atomic
incorporate/rollback window); account doc round-trip + EXACT revert symmetry; DUPSORT heartbeat
range scan; tx-history UNION ordering; and a full incorporate->rollback that returns the WHOLE env
byte-identical to before.
"""
import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_s2b_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(os.path.expanduser(f"~/nado/{d}"), exist_ok=True)

import logging
logger = logging.getLogger("s2b"); logger.addHandler(logging.NullHandler())

from genesis import create_indexers
create_indexers()

from ops import kv_ops
from ops.account_ops import (create_account, get_account, change_balance, change_bonded,
                             increase_produced_count, change_fidelity, apply_register,
                             fetch_totals, index_totals, get_totals)
from ops.transaction_ops import index_transactions, unindex_transactions
from ops.block_ops import index_block_number, unindex_block
from protocol import split_block_reward, EPOCH_LENGTH, FIDELITY_GAIN, TREASURY_ADDRESS

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def dump_env():
    """Snapshot EVERY (key,value) of EVERY sub-DB as raw bytes (DUPSORT cursors yield each dup),
    in LMDB's deterministic sorted order — so two dumps compare byte-for-byte."""
    env = kv_ops.get_env()
    dbs = kv_ops._dbs()
    out = {}
    with env.begin() as txn:
        for name, db in dbs.items():
            entries = []
            with txn.cursor(db=db) as cur:
                for k, v in cur:
                    entries.append((bytes(k), bytes(v)))
            out[name] = entries
    return out


# --- 1) consolidation: ONE env with all eight named sub-DBs --------------------------------------
def t1():
    """Prove the single LMDB env exposes every expected named sub-DB (accounts/totals/block/tx/recert)."""
    dbs = set(kv_ops._dbs().keys())
    for sub in ("accounts", "totals", "block_by_num", "block_by_hash",
                "tx", "tx_by_sender", "tx_by_recipient", "recerts", "recert_by_epoch"):
        assert sub in dbs, f"{sub} sub-DB missing (have {dbs})"
check("one LMDB env with accounts/totals/block/tx/recert sub-DBs", t1)


# --- 2) write_txn commits all mutations together -------------------------------------------------
def t2():
    """Prove multiple mutations inside one write_txn commit together and persist."""
    create_account("alice", balance=1000)
    with kv_ops.write_txn():
        change_balance("alice", -500, logger=logger)
        change_balance("alice", -100, logger=logger)
    assert get_account("alice")["balance"] == 400, "committed write_txn not persisted"
check("write_txn commits all mutations together", t2)


# --- 3) write_txn rolls back ALL on a mid-failure (atomic) ---------------------------------------
def t3():
    """Prove an exception mid-write_txn rolls back every mutation (nothing persists)."""
    create_account("bob", balance=1000)
    try:
        with kv_ops.write_txn():
            change_balance("bob", -700, logger=logger)   # would leave 300 (uncommitted)
            raise RuntimeError("boom mid-transaction")
    except RuntimeError:
        pass
    assert get_account("bob")["balance"] == 1000, "aborted write_txn still mutated balance"
check("write_txn rolls back ALL on mid-failure (atomic)", t3)


# --- 4) atomic across ALL sub-DBs: an incorporate-style crash leaves no partial state ------------
def t4():
    """Prove an incorporate-style crash rolls back accounts, block index, tx index, and totals together — no partial state across sub-DBs."""
    create_account("carol", balance=2000)
    before_tot = fetch_totals()["produced"]
    try:
        with kv_ops.write_txn():
            change_balance("carol", -1000, logger=logger)
            kv_ops.block_index_put(7, "d" * 64)
            kv_ops.tx_index_put("txZ", 7, "carol", "x")
            kv_ops.totals_add(999, 0)
            raise RuntimeError("crash before commit")
    except RuntimeError:
        pass
    assert get_account("carol")["balance"] == 2000, "accounts not rolled back"
    assert kv_ops.hash_by_number(7) is None, "block index not rolled back"
    assert kv_ops.tx_get("txZ") is None, "tx index not rolled back"
    assert fetch_totals()["produced"] == before_tot, "totals not rolled back"
check("atomic across ALL sub-DBs: incorporate-style crash leaves no partial state", t4)


# --- 5) success path commits across sub-DBs together ---------------------------------------------
def t5():
    """Prove the success path commits writes to multiple sub-DBs (block + tx index) together."""
    with kv_ops.write_txn():
        kv_ops.block_index_put(8, "e" * 64)
        kv_ops.tx_index_put("txY", 8, "carol", "x")
    assert kv_ops.hash_by_number(8) == "e" * 64
    assert kv_ops.tx_get("txY") == {"block_number": 8, "sender": "carol", "recipient": "x"}
check("write_txn commits across sub-DBs together", t5)


# --- 6) account doc round-trip + EXACT revert symmetry of every mutator --------------------------
def t6():
    """Prove every account mutator (balance/produced/bonded/fidelity/apply_register) applies and, reverted in mirror order, restores the doc byte-identically."""
    create_account("dave", balance=5000, produced=10, bonded=3000, registered=0, fidelity=7)
    base = dict(get_account("dave"))
    base_bytes = dump_env()["accounts"]
    with kv_ops.write_txn():
        change_balance("dave", -1234, logger=logger)
        increase_produced_count("dave", 5, logger=logger)
        change_bonded("dave", 1000, logger=logger)
        change_fidelity("dave", 3, logger=logger)
        # a recert (apply_register) IS the presence lease now — registered->1, records the recert, and sets
        # fidelity. dave's FIRST recert (no prior) RESETS fidelity to GAIN (a lapse/first recert loses streak),
        # so the change_fidelity(+3) above is wiped forward and exactly restored on revert (the point of the test).
        apply_register("dave", epoch=0, logger=logger)
    after = get_account("dave")
    assert after["balance"] == base["balance"] - 1234
    assert after["produced"] == base["produced"] + 5
    assert after["bonded"] == base["bonded"] + 1000
    assert after["registered"] == 1
    assert after["fidelity"] == FIDELITY_GAIN     # first recert resets fidelity to GAIN
    assert kv_ops.recert_addresses_after(-1) == {"dave"}
    # revert in the exact mirror order -> doc returns byte-identical
    with kv_ops.write_txn():
        apply_register("dave", epoch=0, logger=logger, revert=True)
        change_fidelity("dave", 3, logger=logger, revert=True)
        change_bonded("dave", 1000, logger=logger, revert=True)
        increase_produced_count("dave", 5, logger=logger, revert=True)
        change_balance("dave", -1234, logger=logger, revert=True)
    assert get_account("dave") == base, "account doc did not revert to baseline values"
    assert dump_env()["accounts"] == base_bytes, "account doc bytes not byte-identical after revert"
    assert kv_ops.recert_addresses_after(-1) == set(), "recert not removed on revert"
check("account doc round-trip + EXACT revert symmetry", t6)


# --- 7) DUPSORT recert range scan (epoch > floor), dedup, delete ---------------------------------
def t7():
    """Prove the DUPSORT recert index range-scans by epoch floor, dedups exact duplicates, and deletes one (addr, epoch) pair unambiguously."""
    # recert_put(address, epoch) — note arg order (heartbeat_put(ep,addr) was retired in the lease refactor).
    for ep, addr in [(10, "p"), (11, "p"), (11, "q"), (12, "r"), (11, "p")]:  # (11,p) dup -> deduped
        kv_ops.recert_put(addr, ep)
    assert kv_ops.recert_addresses_after(10) == {"p", "q", "r"}   # epoch > 10 (p@11, q@11, r@12)
    assert kv_ops.recert_addresses_after(11) == {"r"}             # epoch > 11 (only r@12)
    # exact dup encoding -> a single delete is unambiguous
    kv_ops.recert_del("p", 11)
    assert kv_ops.recert_addresses_after(10) == {"q", "r"}        # p@11 gone; p@10 not > 10
check("DUPSORT recert range scan + dedup + delete", t7)


# --- 8) tx-history UNION ordering (merge sender|recipient dupsort cursors, by block) -------------
def t8():
    """Prove tx_of_account merges the sender and recipient indexes ordered by block, dedups self-sends, and honors min_block and limit."""
    kv_ops.drop_tx_index()
    # block-order deliberately scrambled relative to insert order
    kv_ops.tx_index_put("txB", 5, "u", "v")
    kv_ops.tx_index_put("txA", 2, "v", "u")   # u is recipient here
    kv_ops.tx_index_put("txC", 9, "u", "u")   # u both sender+recipient -> deduped once
    hist = [t[1] for t in kv_ops.tx_of_account("u", 0, 100)]
    assert hist == ["txA", "txB", "txC"], f"UNION not ordered by block / not deduped: {hist}"
    assert kv_ops.tx_of_account("u", 5, 100) == [(5, "txB"), (9, "txC")], "min_block filter wrong"
    assert [t[1] for t in kv_ops.tx_of_account("u", 0, 2)] == ["txA", "txB"], "limit wrong"
check("tx-history UNION ordered by block + deduped + limited", t8)


# --- 9) full incorporate -> rollback returns the WHOLE env byte-identical ------------------------
def t9():
    """Prove a full incorporate (core_loop sequence) followed by rollback (rollback_one_block sequence) leaves the WHOLE env byte-identical."""
    # Pre-create every account a block touches with a nonzero baseline so the revert returns each
    # doc to its exact prior bytes (no fresh zero-row artifacts). Then run the SAME sequence
    # core_loop.incorporate_block runs, inside one write_txn, and the SAME sequence
    # rollback_one_block runs, inside another — and assert the env is byte-identical to before.
    create_account("snd", balance=100000)
    create_account("rcv", balance=500)
    create_account("reg", balance=0, registered=0)
    create_account("prod", balance=0, produced=0)
    create_account(TREASURY_ADDRESS, balance=0)

    block_number = 1                       # epoch 0 (recert lands here; no GC in the rollback window)
    assert block_number // EPOCH_LENGTH == 0
    txs = [
        {"txid": "t_xfer", "sender": "snd", "recipient": "rcv", "amount": 1000, "fee": 7},
        # `register` is the presence lease/recert; index_transactions reflects it and unindex reverses it,
        # so the recert + registered flag + fidelity apply and revert byte-identically inside the block.
        {"txid": "t_reg",  "sender": "reg", "recipient": "register", "amount": 0, "fee": 0},
    ]
    block = {"block_number": block_number, "block_hash": "a" * 64, "block_creator": "prod",
             "block_reward": 4000, "block_transactions": txs}

    before = dump_env()

    # ---- incorporate (mirrors loops/core_loop.incorporate_block's atomic window) ----
    with kv_ops.write_txn():
        index_transactions(block=block, sorted_transactions=txs, logger=logger)
        producer_cut, treasury_cut = split_block_reward(block["block_reward"])
        change_balance(address="prod", amount=producer_cut, logger=logger)
        if treasury_cut:
            change_balance(address=TREASURY_ADDRESS, amount=treasury_cut, logger=logger)
        increase_produced_count(address="prod", amount=producer_cut, logger=logger)
        totals = get_totals(block=block)
        index_totals(produced=totals["produced"], fees=totals["fees"])
        index_block_number(block)

    mid = dump_env()
    assert mid != before, "incorporate made no change?!"
    assert get_account("rcv")["balance"] == 1500
    assert get_account("snd")["balance"] == 100000 - 1007
    assert get_account("reg")["registered"] == 1
    assert kv_ops.block_hash_indexed("a" * 64)
    assert kv_ops.tx_get("t_xfer") is not None

    # ---- rollback (mirrors rollback.rollback_one_block's atomic window) ----
    with kv_ops.write_txn():
        producer_cut, treasury_cut = split_block_reward(block["block_reward"])
        change_balance(address="prod", amount=producer_cut, revert=True, logger=logger)
        if treasury_cut:
            change_balance(address=TREASURY_ADDRESS, amount=treasury_cut, revert=True, logger=logger)
        increase_produced_count(address="prod", amount=producer_cut, revert=True, logger=logger)
        totals = get_totals(block=block, revert=True)
        index_totals(produced=totals["produced"], fees=totals["fees"])
        unindex_transactions(block=block, logger=logger, block_height=block_number)
        unindex_block(block, logger=logger)

    after = dump_env()
    assert after == before, "incorporate->rollback is NOT byte-identical (revert asymmetry)"
check("atomic incorporate -> rollback returns env BYTE-IDENTICAL", t9)


print(f"\n{'ALL S2b CHECKS PASSED' if fails == 0 else str(fails) + ' S2b CHECK(S) FAILED'}")
sys.exit(1 if fails else 0)
