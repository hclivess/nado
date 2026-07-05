import gc

import psutil
import threading
import time
import traceback
import gc


class MessageClient(threading.Thread):
    """thread which displays output messages and logs them"""

    def __init__(self, memserver, consensus, core, peers, logger):
        threading.Thread.__init__(self)
        self.logger = logger
        self.logger.info(f"Starting Message Client")
        self.memserver = memserver
        self.consensus = consensus
        self.core = core
        self.peers = peers

    # Per-component health. Each check returns (level, detail):
    #   "ok"   — healthy
    #   "warn" — degraded but the node can keep operating
    #   "down" — this subsystem is not doing its job
    # The message loop renders one line per component plus a rolled-up verdict,
    # so a problem points at the actual failing part instead of a single flag.
    def health_report(self):
        components = {}

        # --- Peers ---------------------------------------------------------
        n_peers = len(self.memserver.peers)
        n_unreach = len(self.memserver.unreachable)
        if n_peers == 0:
            peer_level = "down"
        elif n_peers < 10:
            peer_level = "warn"
        else:
            peer_level = "ok"
        components["Peers"] = (
            peer_level,
            f"{n_peers} linked, {n_unreach} unreachable"
            + ("" if n_peers >= 10 else " (target 10)"),
        )

        # --- Block freshness ----------------------------------------------
        age = self.memserver.since_last_block
        bt = self.memserver.block_time
        if age <= 2 * bt:
            block_level = "ok"
        elif age <= 6 * bt:
            block_level = "warn"
        else:
            block_level = "down"
        components["Blocks"] = (
            block_level,
            f"#{self.memserver.latest_block['block_number']} · "
            f"{age}s old (block_time {bt}s)",
        )

        # --- Consensus agreement ------------------------------------------
        majority = self.consensus.majority_block_hash
        agree_pct = int(self.consensus.block_hash_pool_percentage)
        members = len(self.consensus.block_hash_pool)
        if members == 0:
            # No peers reporting yet (e.g. solo/bootstrap) — nothing to disagree with.
            cons_level = "warn" if n_peers == 0 else "ok"
            cons_detail = "no quorum reporting"
        elif self.memserver.latest_block["block_hash"] == majority:
            cons_level = "ok"
            cons_detail = f"in majority ({agree_pct}% / {members} peers)"
        else:
            cons_level = "warn"
            cons_detail = f"OUTSIDE majority ({agree_pct}% / {members} peers)"
        components["Consensus"] = (cons_level, cons_detail)

        # --- Reachability / mining ports ----------------------------------
        if self.memserver.can_mine:
            components["Ports"] = ("ok", "open (mineable)")
        else:
            components["Ports"] = ("warn", "closed — not accepting inbound")

        # --- Sync mode -----------------------------------------------------
        components["Sync"] = (
            "warn" if self.memserver.emergency_mode else "ok",
            "EMERGENCY" if self.memserver.emergency_mode
            else f"{self.memserver.mode}",
        )

        return components

    def run(self) -> None:
        while not self.memserver.terminate:
            try:
                # --- Health report: one line per subsystem + rolled-up verdict ---
                report = self.health_report()
                worst = "ok"
                for level, _ in report.values():
                    if level == "down":
                        worst = "down"
                        break
                    if level == "warn" and worst == "ok":
                        worst = "warn"

                glyph = {"ok": "[  OK  ]", "warn": "[ WARN ]", "down": "[ DOWN ]"}
                header = {"ok": "NODE HEALTHY",
                          "warn": "NODE DEGRADED",
                          "down": "NODE UNHEALTHY"}[worst]
                log_at = {"ok": self.logger.info,
                          "warn": self.logger.warning,
                          "down": self.logger.error}[worst]

                log_at(f"===== {header} =====")
                for name, (level, detail) in report.items():
                    log_at(f"  {glyph[level]} {name:<10} {detail}")

                # Supporting detail (kept at debug — the report above is the summary)
                self.logger.debug(
                    f"Transactions: {len(self.memserver.transaction_pool)}tp < "
                    f"{len(self.memserver.tx_buffer)}tb < {len(self.memserver.user_tx_buffer)}ub")
                self.logger.debug(
                    f"Tx hash agreement: {int(self.consensus.transaction_hash_pool_percentage)}%")
                self.logger.debug(
                    f"Latest hash: {self.memserver.latest_block['block_hash']}")
                self.logger.debug(
                    f"Purge queue: {len(self.memserver.purge_peers_list)} · "
                    f"Forced sync: {self.memserver.force_sync_ip}")

                self.logger.info(f"Loop durations: Core: {self.core.duration}; "
                                 f"Consensus: {self.consensus.duration}; "
                                 f"Peers: {self.peers.duration}")

                self.logger.info(f"Open files: {len(psutil.Process().open_files())}")
                # NOTE: removed the periodic `muppy.get_objects()` heap walk — it is a
                # stop-the-world GIL-bound full-heap traversal that (a) starves the Tornado
                # /status handler and (b) fatally trips CPython's GC ("PyObject_GC_Track:
                # object already tracked", _asyncio.FutureIter) under live asyncio load,
                # crashing the node. gc counts below are cheap and safe.
                gc_counts = gc.get_count()
                self.logger.info(f"GC counts: {gc_counts}")

                # Backstop-persist the off-chain message pool (~every 10s) so even a hard crash that skips
                # the SIGTERM save loses at most one interval of undelivered DMs. No-op while the pool is empty.
                try:
                    mp = self.memserver.message_pool
                    if mp.messages or mp.prekeys:
                        mp.save(self.memserver.message_pool_path)
                except Exception as e:
                    self.logger.error(f"Message pool save failed: {e}")

                time.sleep(10)
            except Exception as e:
                self.logger.error(f"Error in message loop: {e} {traceback.print_exc()}")
                time.sleep(1)
