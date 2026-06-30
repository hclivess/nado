import asyncio
from threading import Lock

from compounder import compound_get_list_of
from config import get_timestamp_seconds, get_config
from hashing import blake2b_hash
from ops.account_ops import get_account, get_finalized_height
from ops.block_ops import load_block_producers, get_block_ends_info
from ops.data_ops import set_and_sort, sort_list_dict
from ops.key_ops import load_keys
from ops.transaction_ops import (
    validate_single_spending,
    validate_transaction,
    sort_transaction_pool,
    validate_txid,
    validate_base_fee

)
from versioner import read_version


class MemServer:
    """storage thread for core.py, also accessed by most other threads, serves mostly as data storage"""

    def __init__(self, logger):
        self.logger = logger
        self.logger.info("Starting MemServer")
        self.genesis_timestamp = 1669852800

        self.purge_peers_list = []
        self.purge_producers_list = []


        self.start_time = get_timestamp_seconds()
        self.keydict = load_keys()
        self.config = get_config()
        self.protocol = self.config["protocol"]
        self.private_key = self.keydict["private_key"]
        self.public_key = self.keydict["public_key"]
        self.address = self.keydict["address"]
        self.server_key = self.config["server_key"]
        self.transaction_pool = []
        self.since_last_block = 0
        self.user_tx_buffer = []
        self.tx_buffer = []
        self.peer_buffer = []
        self.ip = self.config["ip"]
        self.port = self.config["port"]
        self.terminate = False
        self.producers_refresh_interval = 10
        self.heavy_refresh_interval = 360

        self.block_time = self.config.get("block_time") or 60  # configurable (e.g. fast demo networks)
        self.periods = [0]

        self.unreachable = {}
        self.peers = []

        self.transaction_pool_hash = None
        self.block_producers_hash = None
        self.block_generation_age = 0 # time since last block (real, not target)
        self.reported_uptime = self.get_uptime()
        self.block_producers = load_block_producers()

        self.emergency_mode = False

        self.version = read_version()
        block_ends_info = get_block_ends_info(logger=logger)
        self.latest_block = block_ends_info["latest_block"]
        self.earliest_block = block_ends_info["earliest_block"]
        self.transaction_pool_limit = 150000
        self.transaction_buffer_limit = 1500000
        self.cascade_depth = 0
        self.force_sync_ip = None
        self.rollbacks = 0
        self.can_mine = False
        self.replaced_this_round = False
        self.switch_mode = {"name":"Initialization",
                            "mode": -1}

        _mp = self.config.get("min_peers")  # respect an explicit 0 (solo mode); `or 5` would force 5
        self.min_peers = 5 if _mp is None else _mp
        self.peer_limit = self.config.get("peer_limit") or 24
        self.max_rollbacks = self.config.get("max_rollbacks") or 10
        # ENFORCED FINALITY (#17, security step 1): a persisted monotonic finalized_height floor that
        # rollback_one_block REFUSES to cross (FinalityViolation). The ordering invariant below makes
        # the epoch-beacon anchor un-reorgable (a live epoch's anchor can never be reorged out) and
        # bounds 51%/long-range rollback. It fails loudly at startup so a mis-set config can't silently
        # disable the protection. (Stake-weighted fork-choice that bounds reorg COST is steps 2-3.)
        from protocol import EPOCH_LENGTH, FINALITY_DEPTH
        self.finality_depth = self.config.get("finality_depth") or FINALITY_DEPTH
        assert self.max_rollbacks < self.finality_depth < EPOCH_LENGTH, (
            f"need max_rollbacks ({self.max_rollbacks}) < finality_depth ({self.finality_depth}) "
            f"< EPOCH_LENGTH ({EPOCH_LENGTH}) for enforced-finality safety")
        # in-memory mirror of the persisted floor (advanced by core_loop.incorporate_block)
        self.finalized_height = get_finalized_height()
        # FFG (#6): the stake-attested finalized checkpoint height (observability; <= finalized_height,
        # which is the deeper time-based floor that bounds rollback). Updated by core_loop.maybe_attest.
        self.ffg_finalized = 0
        # RANDAO (#7): this validator's locally-held secrets {target_epoch: secret}, committed in E-2
        # and revealed in E-1. In-memory only (a secret never revealed after a restart is simply a
        # wasted commit — harmless; the beacon falls back to the anchor + other validators' reveals).
        self.randao_secrets = {}
        self.cascade_limit = self.config.get("cascade_limit") or 1
        self.promiscuous = True if self.config.get("promiscuous") is True else False
        # NOTE: the old `quick_sync` flag is GONE. It only ever gated the verify_block validation bypass
        # that the 2026-06-30 audit removed (forged-tx injection, HIGH) — so the flag became a silent
        # no-op. For a genuine fast bootstrap use the snapshot sync (ops/snapshot_ops.py), which is
        # quorum/checkpoint-gated rather than validation-skipping. Do NOT re-add a validation bypass.
        # AUTO-BOND (non-consensus, opt-in): route this % of newly-mined spendable earnings straight
        # into bonded stake, unattended (core_loop.maybe_auto_bond). 0 = off (default). Source order:
        # NADO_AUTO_BOND_PERCENT env (handy for headless/systemd) overrides config["auto_bond_percent"].
        import os as _os
        _ab = _os.environ.get("NADO_AUTO_BOND_PERCENT")
        if _ab is None:
            _ab = self.config.get("auto_bond_percent", 0)
        try:
            self.auto_bond_percent = max(0, min(100, int(_ab)))
        except (TypeError, ValueError):
            self.auto_bond_percent = 0

    def ban_peer(self, peer):
        if peer not in self.purge_peers_list and peer not in self.unreachable:
            self.purge_peers_list.append(peer)

    def get_transaction_pool_hash(self) -> [str, None]:
        if self.transaction_pool:
            sorted_transaction_pool = sort_transaction_pool(self.transaction_pool.copy())
            transaction_pool_hash = blake2b_hash(sorted_transaction_pool)
        else:
            transaction_pool_hash = None
        return transaction_pool_hash

    def get_block_producers_hash(self) -> [str, None]:
        if self.block_producers:
            self.block_producers = set_and_sort(self.block_producers)
            producers_pool_hash = blake2b_hash(self.block_producers)
        else:
            producers_pool_hash = None
        return producers_pool_hash

    def get_uptime(self) -> int:
        return get_timestamp_seconds() - self.start_time

    def merge_remote_transactions(self, user_origin=False) -> None:
        """reach out to all peers and merge their transactions to our transaction pool"""
        remote_pool_transactions = asyncio.run(
            compound_get_list_of(
                key="transaction_pool",
                entries=self.peers,
                port=self.port,
                logger=self.logger,
                fail_storage=self.purge_peers_list,
                compress="msgpack",
                semaphore=asyncio.Semaphore(50)
            )
        )
        self.merge_transactions(remote_pool_transactions, user_origin)

        remote_buffer_transactions = asyncio.run(
            compound_get_list_of(
                key="transaction_buffer",
                entries=self.peers,
                port=self.port,
                logger=self.logger,
                fail_storage=self.purge_peers_list,
                compress="msgpack",
                semaphore=asyncio.Semaphore(50)
            )
        )

        self.merge_transactions(remote_buffer_transactions, user_origin)


    def merge_transaction(self, transaction, user_origin=False) -> dict:
        """warning, can get stuck if not efficient"""
        # AUDIT FIX: a malicious peer can serve a /transaction_pool list with a malformed entry; the
        # pre-validation field accesses below (sender, target_block) would KeyError/TypeError and abort
        # the whole merge batch. Reject malformed txs up front so the rest of the batch still merges.
        if (not isinstance(transaction, dict) or "sender" not in transaction
                or not isinstance(transaction.get("target_block"), int)
                or isinstance(transaction.get("target_block"), bool)):
            return {"result": False, "message": "Malformed transaction"}

        united_pools = self.transaction_pool.copy() + self.tx_buffer.copy() + self.user_tx_buffer.copy()

        # Anti-DoS: hard-cap the mempool so a flood (incl. fee-exempt register/heartbeat spam) cannot
        # grow it unbounded and OOM the node. Pairs with the per-IP HTTP rate limiter. The lane cap
        # already stops spam from buying extra block share; this stops it taking the node down.
        if len(united_pools) >= self.transaction_pool_limit:
            return {"result": False, "message": "Mempool full"}

        # OPEN-lane onboarding: register/heartbeat are fee-exempt ENTRY txs — a brand-new zero-coin
        # address has no on-chain account YET (registration is what creates it), so they must bypass
        # the empty-account anti-spam gate. (register is PoW-gated and heartbeat requires registered=1
        # in validate_transaction, so this opens no spam hole.) Spending txs still need a funded account.
        if transaction.get("recipient") not in ("register", "heartbeat") \
                and not get_account(transaction["sender"], create_on_error=False):
            msg = {"result": False,
                   "message": f"Empty account"}
            return msg

        elif transaction["target_block"] < self.latest_block["block_number"]:
            msg = {"result": False,
                   "message": f"Target block too low"}
            return msg

        elif transaction["target_block"] > self.latest_block["block_number"] + 360:
            msg = {"result": False,
                   "message": f"Target block too high"}
            return msg

        elif not validate_txid(transaction, logger=self.logger):  # always enforced (compat gate gone)
            msg = {"result": False,
                   "message": f"Invalid txid"}
            return msg
        # NOTE: the old byte-size validate_base_fee gate is removed: get_byte_size is
        # sys.getsizeof(repr(...)) and is non-deterministic, so it is unsafe as a fee rule.
        # The deterministic MIN_TX_FEE floor is enforced in validate_transaction below.

        elif transaction not in united_pools:
            try:
                validate_transaction(transaction=transaction,
                                     logger=self.logger,
                                     block_height=self.latest_block["block_number"])
            except Exception as e:
                msg = {"result": False,
                       "message": f"Could not merge remote transaction: {e}"}
                # self.logger.info(msg) spam
                # raise #test
                return msg
            else:
                try:
                    validate_single_spending(transaction_pool=united_pools, transaction=transaction)

                    if transaction not in self.transaction_pool:
                        if user_origin and transaction not in self.tx_buffer:
                            self.user_tx_buffer.append(transaction)
                            self.user_tx_buffer = sort_list_dict(self.user_tx_buffer)
                        elif transaction not in self.user_tx_buffer:
                            self.tx_buffer.append(transaction)
                            self.tx_buffer = sort_list_dict(self.tx_buffer)

                except Exception as e:
                    msg = f"Remote transaction failed to validate: {e}"
                    self.logger.info(msg)
                    self.purge_txs_of_sender(transaction["sender"])
                    return {"message": msg,
                            "result": False}

            return {"message": "Success", "result": True}

    def merge_transactions(self, transactions, user_origin=False) -> None:
        for transaction in transactions:
            self.merge_transaction(transaction, user_origin)

    def purge_txs_of_sender(self, sender) -> None:
        """remove all transactions of sender to prevent possible double spending attempt"""
        """of sender sending different txs to different nodes both exhausting balance"""
        for transaction in self.transaction_pool:
            if transaction["sender"] == sender:
                self.transaction_pool.remove(transaction)

        for transaction in self.tx_buffer:
            if transaction["sender"] == sender:
                self.tx_buffer.remove(transaction)
