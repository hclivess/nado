import gc

import psutil
import threading
import time
import traceback

from config import get_timestamp_seconds
from ops import self_update


class MessageClient(threading.Thread):
    """thread which displays output messages and logs them"""

    def __init__(self, memserver, consensus, core, peers, logger):
        """Hold read-only references to the other loop threads purely for reporting — their
        .duration fields and pools feed the periodic health/status lines; nothing is mutated."""
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
        """Per-component health snapshot {name: (level, detail)}, level in ok/warn/down (see the key
        above): peers, block freshness (thresholds scale with block_time), majority agreement,
        inbound reachability (can_mine), and sync mode. Pure read of shared state — no side effects,
        callable from tests; run() does the roll-up to a single worst-of verdict."""
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

        # --- Finality ------------------------------------------------------
        # Finality is supposed to trail the tip by finality_depth and no further. On 2026-07-20 it froze
        # for ~1.5 hours — every block's exec summary was failing, so no height got a settle binding —
        # while EVERY check above stayed green and this loop printed NODE HEALTHY the entire time. Peers
        # were linked, blocks were fresh, the hash was in the majority: nothing here looks at whether the
        # chain is still FINALIZING, which is the one thing that had stopped. A frozen floor is the
        # clearest single symptom that settlement has died, so it gets its own line.
        # The signal is FROZEN, not merely LAGGING. The real outage sat 109 blocks behind a depth-45 rule,
        # which any lag-only threshold generous enough to avoid false alarms would still have called
        # "degraded" rather than "dead" — and it had been going for ninety minutes. What actually
        # distinguishes a stalled chain from a busy one is that the floor STOPS MOVING while the tip keeps
        # going, so that is what this measures. Catching it by elapsed-frozen time also flags the incident
        # within minutes, long before the lag grows large enough for any depth multiple to notice.
        tip = int(self.memserver.latest_block.get("block_number") or 0)
        fin = int(self.memserver.finalized_height or 0)
        depth = self.memserver.finality_depth
        lag = tip - fin
        now = time.monotonic()
        if getattr(self, "_fin_last", None) is None or fin > self._fin_last:
            self._fin_last, self._fin_moved_at = fin, now      # advanced: restart the clock
        frozen_for = now - getattr(self, "_fin_moved_at", now)

        if frozen_for >= 300 or lag > depth * 4:
            fin_level = "down"
        elif frozen_for >= 120 or lag > depth * 2:
            fin_level = "warn"
        else:
            fin_level = "ok"
        if self.memserver.emergency_mode and fin_level == "down":
            fin_level = "warn"                       # catching up legitimately runs a big gap; don't cry wolf
        components["Finality"] = (
            fin_level,
            f"#{fin} · {lag} behind tip (depth {depth})"
            + (f" · FROZEN {int(frozen_for)}s" if frozen_for >= 120 else "")
            + (" — syncing" if self.memserver.emergency_mode else ""),
        )

        # --- Running code --------------------------------------------------
        # A fix that is committed but not RUNNING is not a fix. `update_available` in /status compares
        # against origin as of the last fetch, so it stays silent when the repair was committed locally —
        # which is exactly how the finality stall above survived 34 minutes past its own fix landing.
        try:
            if self_update.code_is_stale():
                components["Code"] = ("warn", f"running {self_update.running_head()}, checkout at "
                                              f"{self_update.repo_head()} — RESTART to apply")
            else:
                components["Code"] = ("ok", f"{self_update.running_head() or 'no git metadata'}")
        except Exception as e:                       # observability must never be able to break the loop
            components["Code"] = ("ok", f"unknown ({type(e).__name__})")

        # --- Sync mode -----------------------------------------------------
        components["Sync"] = (
            "warn" if self.memserver.emergency_mode else "ok",
            "EMERGENCY" if self.memserver.emergency_mode
            else f"{self.memserver.mode}",
        )

        return components

    def run(self) -> None:
        """Every 10s: emit the per-component health report, logging the WHOLE block at the severity
        of the worst component (so one degraded subsystem escalates the summary to warning/error),
        plus debug-level supporting detail and loop-duration/resource stats. Also backstop-persists
        the off-chain message pool each pass, so a hard crash that skips the SIGTERM save loses at
        most one interval of undelivered DMs. Observability only — never touches consensus state."""
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
                    f"Mempool: {len(self.memserver.transaction_pool)} tx")
                self.logger.debug(
                    f"Tx volatility index: {int(100 - self.consensus.transaction_hash_pool_percentage)}%")
                self.logger.debug(
                    f"Upcoming-block agreement: {int(self.consensus.upcoming_block_hash_pool_percentage)}% "
                    f"(next-block tx set — what the fast-forward depends on)")
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
                # the SIGTERM save loses at most one interval of undelivered DMs. gc() first: TTL reaping
                # previously had NO caller, so expired envelopes lived (and were re-persisted) until a
                # restart. save() itself now skips when the pool hasn't changed since the last write.
                try:
                    mp = self.memserver.message_pool
                    mp.gc(get_timestamp_seconds())
                    if mp.messages or mp.prekeys:
                        mp.save(self.memserver.message_pool_path)
                except Exception as e:
                    self.logger.error(f"Message pool save failed: {e}")

                time.sleep(10)
            except Exception as e:
                self.logger.error(f"Error in message loop: {e} {traceback.format_exc()}")
                time.sleep(1)
