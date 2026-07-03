import asyncio
import json
import os

from config import create_config
from hashing import blake2b_hash_link
from ops.account_ops import create_account
from ops.block_ops import save_block, set_latest_block_info, set_earliest_block_info
from ops.data_ops import get_home, make_folder
from ops.log_ops import get_logger
from ops.peer_ops import save_peer, get_public_ip
from ops import kv_ops
from protocol import GENESIS_ADDRESS, CHAIN_ID, TREASURY_ADDRESS, TREASURY_GENESIS


def create_indexers():
    # ONE LMDB env with named sub-DBs so the whole incorporate_block mutation (account docs, tx
    # index, block index, totals, recerts) commits in a SINGLE write transaction -> crash-atomic
    # (audit LO-1/CO-4). The schema is schemaless msgpack documents (no DDL): see ops/kv_ops.py for
    # the sub-DB table —
    #   accounts (address -> {balance,produced,bonded,registered,fidelity,...}), totals,
    #   block_by_num / block_by_hash, tx + tx_by_sender / tx_by_recipient (DUPSORT),
    #   recerts (DUPSORT address -> epoch) + recert_by_epoch (DUPSORT epoch -> address).
    # `bonded` = refundable stake locked for mining eligibility (S4), NOT spendable balance.
    # `registered`/`fidelity` = OPEN-lane mining state (registered=1 after the one-time registration
    # PoW; fidelity = continuity over recerts, clamped to FIDELITY_CAP on read by open_shares).
    kv_ops.init_env()      # opens the env + creates every sub-DB (replaces CREATE TABLE DDL)
    kv_ops.totals_seed()   # seed totals to {0,0} once (idempotent re-run)
    # IDEMPOTENT self-heal: mirror any pre-existing recerts into the (later-added) recert_by_epoch index,
    # so an upgraded node never reports a validly-leased miner as ABSENT. No-op once the index is populated.
    n = kv_ops.backfill_recert_by_epoch()
    if n:
        print(f"[startup] recert_by_epoch backfill: {n} recert row(s) mirrored", flush=True)


def make_folders():
    make_folder(f"{get_home()}/blocks")
    make_folder(f"{get_home()}/peers", strict=False)
    make_folder(f"{get_home()}/private", strict=False)
    make_folder(f"{get_home()}/index")

    create_indexers()


def make_genesis(address, balance, ip, port, timestamp, logger):
    config_ip = asyncio.run(get_public_ip(logger=logger))
    create_config(ip=config_ip)

    block_transactions = []
    block_hash = blake2b_hash_link(link_from=timestamp, link_to=block_transactions)

    genesis_block_message = {
        "block_number": 0,
        "parent_hash": None,
        "block_ip": ip,
        "block_creator": address,
        "block_hash": block_hash,
        "block_timestamp": timestamp,
        "block_transactions": block_transactions,
        "block_reward": 0,
        "cumulative_fees": 0,        # running total of fees burned up to and incl. this block
        "cumulative_weight": 0,      # #17 step 2: fork-choice chain-weight base (genesis = 0)
        "chain_id": CHAIN_ID,
    }

    # The genesis address IS the treasury (owner's decision): it holds the bootstrap allocation
    # and accrues the 10% per-block cut. Because this address is key-controlled, the seed balance
    # is effectively a founder allocation; pass balance=0 (TREASURY_GENESIS=0) for a no-coins start.
    create_account(address=address, balance=balance)

    # TESTNET ONLY: seed bonded stake for the node addresses listed in private/genesis_bonds.dat
    # (byte-identical on every node) so there is an eligible bonded producer set from block 1 and
    # the fail-closed S4.3 selector can mint. Off-chain account seeding only — it does NOT change
    # the genesis block hash (block 0 hash = blake2b_hash_link(timestamp, []) ignores account state).
    if os.environ.get("NADO_TESTNET"):
        bonds_path = f"{get_home()}/private/genesis_bonds.dat"
        if os.path.exists(bonds_path):
            with open(bonds_path) as bf:
                bonds = json.load(bf)
            for entry in bonds:
                create_account(address=entry["address"], balance=0, bonded=entry["bonded"])
            logger.warning(f"TESTNET: seeded {len(bonds)} bonded genesis accounts")

    # MAINNET-capable OPEN-lane bootstrap (no premine, no bonded seed required): seed registered +
    # present relay identities from a byte-identical genesis_open.dat so a fresh chain can PRODUCE
    # from height 1 through the OPEN lane. With TREASURY_GENESIS=0 nobody holds coins to bond, so the
    # bonded lane is empty at genesis; the founder's relay nodes mine the open lane like everyone else
    # (fair launch), and the bonded lane fills organically as miners earn the base subsidy and bond.
    # The epoch-0 recert makes them present in get_open_registry (the presence LEASE) for the first
    # POSW_LEASE_EPOCHS — ample time for the relays to start posting on-chain recerts and stay present.
    open_path = f"{get_home()}/private/genesis_open.dat"
    if os.path.exists(open_path):
        with open(open_path) as of:
            open_ids = json.load(of)
        for addr in sorted(open_ids):
            create_account(address=addr, registered=1)
            kv_ops.recert_put(address=addr, epoch=0)  # seed a lease at epoch 0 (DUPSORT dedups per addr@0)
        logger.warning(f"Seeded {len(open_ids)} registered open-lane genesis identities (epoch 0)")

    # FAUCET GUARD: there is intentionally NO auto-bond faucet anywhere. Granting a fresh address a
    # bonded share would pipe the CAPPED free lane into the UNCAPPED capital lane (a Sybil ->
    # stake-majority path that broke the rejected fronted/faucet designs). Onboarding is strictly:
    # register (free) -> mine the open lane -> optionally bond EARNED coins. Do not add one.

    save_peer(ip=ip,
              address=address,
              port=port,
              peer_trust=50)

    save_block(block=genesis_block_message,
               logger=logger)

    set_earliest_block_info(earliest_block=genesis_block_message,
                            logger=logger)

    set_latest_block_info(latest_block=genesis_block_message,
                          logger=logger)



if __name__ == "__main__":
    logger = get_logger(file="genesis.log", logger_name="genesis_logger")

    input("Not supposed to be run directly, continue?\n")
    make_folders()
    make_genesis(
        address=GENESIS_ADDRESS,          # genesis address == treasury (canonical checksum)
        balance=TREASURY_GENESIS,          # bootstrap allocation minted to the genesis/treasury
        ip="78.102.98.72",
        port=9173,
        timestamp=1669852800,
        logger=logger,
    )
