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
for d in ("index", "blocks", "index/producer_sets", "logs", "peers"):
    os.makedirs(os.path.expanduser(f"~/nado/{d}"), exist_ok=True)

import logging
logger = logging.getLogger("s2b"); logger.addHandler(logging.NullHandler())

from genesis import create_indexers
create_indexers()

from ops import kv_ops
from ops.account_ops import (create_account, get_account, change_balance, change_bonded,
                             increase_produced_count, change_fidelity, apply_register,
                             apply_heartbeat, fetch_totals, index_totals, get_totals)
from ops.transaction_ops import index_transactions, unindex_transactions
from ops.block_ops import index_block_number, unindex_block
from protocol import split_block_reward, EPOCH_LENGTH, PRESENCE_WINDOW, FIDELITY_GAIN, TREASURY_ADDRESS

fails = 0
def check(name, fn):
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
    dbs = set(kv_ops._dbs().keys())
    for sub in ("accounts", "totals", "block_by_num", "block_by_hash",
                "tx", "tx_by_sender", "tx_by_recipient", "heartbeats"):
        assert sub in dbs, f"{sub} sub-DB missing (have {dbs})"
check("one LMDB env with accounts/totals/block/tx/heartbeats sub-DBs", t1)


# --- 2) write_txn commits all mutations together -------------------------------------------------
def t2():
    create_account("alice", balance=1000)
    with kv_ops.write_txn():
        change_balance("alice", -500, logger=logger)
        change_balance("alice", -100, logger=logger)
    assert get_account("alice")["balance"] == 400, "committed write_txn not persisted"
check("write_txn commits all mutations together", t2)


# --- 3) write_txn rolls back ALL on a mid-failure (atomic) ---------------------------------------
def t3():
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
    with kv_ops.write_txn():
        kv_ops.block_index_put(8, "e" * 64)
        kv_ops.tx_index_put("txY", 8, "carol", "x")
    assert kv_ops.hash_by_number(8) == "e" * 64
    assert kv_ops.tx_get("txY") == {"block_number": 8, "sender": "carol", "recipient": "x"}
check("write_txn commits across sub-DBs together", t5)


# --- 6) account doc round-trip + EXACT revert symmetry of every mutator --------------------------
def t6():
    create_account("dave", balance=5000, produced=10, bonded=3000, registered=0, fidelity=7)
    base = dict(get_account("dave"))
    base_bytes = dump_env()["accounts"]
    with kv_ops.write_txn():
        change_balance("dave", -1234, logger=logger)
        increase_produced_count("dave", 5, logger=logger)
        change_bonded("dave", 1000, logger=logger)
        change_fidelity("dave", 3, logger=logger)
        apply_register("dave", logger=logger)            # registered -> 1
        apply_heartbeat("dave", epoch=0, logger=logger)  # +heartbeat, fidelity +FIDELITY_GAIN
    after = get_account("dave")
    assert after["balance"] == base["balance"] - 1234
    assert after["produced"] == base["produced"] + 5
    assert after["bonded"] == base["bonded"] + 1000
    assert after["registered"] == 1
    assert after["fidelity"] == base["fidelity"] + 3 + FIDELITY_GAIN
    assert kv_ops.heartbeat_addresses_after(-1) == {"dave"}
    # revert in the exact mirror order -> doc returns byte-identical
    with kv_ops.write_txn():
        apply_heartbeat("dave", epoch=0, logger=logger, revert=True)
        apply_register("dave", logger=logger, revert=True)
        change_fidelity("dave", 3, logger=logger, revert=True)
        change_bonded("dave", 1000, logger=logger, revert=True)
        increase_produced_count("dave", 5, logger=logger, revert=True)
        change_balance("dave", -1234, logger=logger, revert=True)
    assert get_account("dave") == base, "account doc did not revert to baseline values"
    assert dump_env()["accounts"] == base_bytes, "account doc bytes not byte-identical after revert"
    assert kv_ops.heartbeat_addresses_after(-1) == set(), "heartbeat dup not removed on revert"
check("account doc round-trip + EXACT revert symmetry", t6)


# --- 7) DUPSORT heartbeat range scan (epoch > floor), dedup, ordering ----------------------------
def t7():
    for ep, addr in [(10, "p"), (11, "p"), (11, "q"), (12, "r"), (11, "p")]:  # (11,p) dup -> deduped
        kv_ops.heartbeat_put(ep, addr)
    assert kv_ops.heartbeat_addresses_after(10) == {"p", "q", "r"}   # epoch > 10
    assert kv_ops.heartbeat_addresses_after(11) == {"r"}             # epoch > 11
    # exact dup encoding -> a single delete is unambiguous
    kv_ops.heartbeat_del(11, "p")
    assert kv_ops.heartbeat_addresses_after(10) == {"q", "r"}
    kv_ops.heartbeat_gc(11)  # drop epoch <= 11
    assert kv_ops.heartbeat_addresses_after(-1) == {"r"}            # only epoch 12 remains
check("DUPSORT heartbeat range scan + dedup + gc", t7)


# --- 8) tx-history UNION ordering (merge sender|recipient dupsort cursors, by block) -------------
def t8():
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
    # Pre-create every account a block touches with a nonzero baseline so the revert returns each
    # doc to its exact prior bytes (no fresh zero-row artifacts). Then run the SAME sequence
    # core_loop.incorporate_block runs, inside one write_txn, and the SAME sequence
    # rollback_one_block runs, inside another — and assert the env is byte-identical to before.
    create_account("snd", balance=100000)
    create_account("rcv", balance=500)
    create_account("reg", balance=0, registered=0)
    create_account("hbt", balance=0, registered=1)   # heartbeat sender must be registered
    create_account("prod", balance=0, produced=0)
    create_account(TREASURY_ADDRESS, balance=0)

    block_number = 1                       # epoch 0 -> heartbeat GC floor = -3 -> no GC -> symmetric
    assert block_number // EPOCH_LENGTH == 0
    txs = [
        {"txid": "t_xfer", "sender": "snd", "recipient": "rcv", "amount": 1000, "fee": 7},
        {"txid": "t_reg",  "sender": "reg", "recipient": "register", "amount": 0, "fee": 0},
        {"txid": "t_hbt",  "sender": "hbt", "recipient": "heartbeat", "amount": 0, "fee": 0,
         "epoch": 0},
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
        index_totals(produced=totals["produced"], fees=totals["fees"], block_height=block_number)
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
        index_totals(produced=totals["produced"], fees=totals["fees"], block_height=block_number)
        unindex_transactions(block=block, logger=logger, block_height=block_number)
        unindex_block(block, logger=logger)

    after = dump_env()
    assert after == before, "incorporate->rollback is NOT byte-identical (revert asymmetry)"
check("atomic incorporate -> rollback returns env BYTE-IDENTICAL", t9)


print(f"\n{'ALL S2b CHECKS PASSED' if fails == 0 else str(fails) + ' S2b CHECK(S) FAILED'}")
sys.exit(1 if fails else 0)
