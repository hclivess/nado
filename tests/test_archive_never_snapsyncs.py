"""
An ARCHIVE node must not shortcut its way past the history it exists to keep.

THE PRINCIPLE (raised for mainnet, 2026-08-13): if we decide to run archival nodes, we do not want them
deleting — or never acquiring — history via snapshot sync. `archive: true` is an explicit, deliberate
setting; a node carrying it should fail loudly rather than quietly become something else.

TWO HOLES, and they are different in kind.

1. FRESH NODE, snapshot bootstrap. snapshot_bootstrap backfills only
   REWARD_WINDOW + 2*EPOCH_LENGTH + FINALITY_DEPTH bodies behind its anchor and nothing older, EVER. Taken
   with archive=true it yields a node that keeps everything from its snapshot FORWARD, holds nothing
   before it, and advertises node_type "archive" to peers who read that as "can serve history". The
   operator has no reason to suspect it: the node syncs fast and looks healthy. This one is REFUSED —
   convenience is the wrong trade when the setting exists to buy correctness.

2. ESTABLISHED NODE, wedge recovery (force_reanchor=True). Everything below the new earliest block is
   orphaned in the store — the bytes may linger as inert garbage, but nothing references them, so the node
   can no longer SERVE the chain before it. That is the archive lost on a node whose purpose was keeping
   it. This one is NOT refused, and the reason is the point: the node is on a dead fork it cannot leave by
   rollback, so declining leaves it wedged forever, serving nothing. What must not happen is losing it
   SILENTLY — the operator has to learn their history now starts at N in time to re-seed from another
   archive, not from a user's bug report.

WHY REFUSING (1) IS SAFE AND REFUSING (2) IS NOT: (1) has alternatives that produce a correct archive
(genesis sync while a peer still serves deep bodies, or copying an archive's data dir). (2) has none.

A ROLLING node is untouched by all of this — it takes the snapshot path exactly as before, which is the
entire reason the path exists.
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fails = []


def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        _fails.append(name)


class FakeMem:
    """Just enough memserver for the guard: the archive flag, an earliest block, and no peers."""

    def __init__(self, archive, earliest=0, tip=0):
        self.archive = archive
        self.peers = []
        # tip 0 = "still at genesis", the only state a non-forced bootstrap runs in (guarded above ours)
        self.latest_block = {"block_number": tip}
        self.earliest_block = {"block_number": earliest}


class FakeLog:
    def __init__(self):
        self.errors, self.warnings = [], []

    def error(self, m, *a):
        self.errors.append(str(m))

    def warning(self, m, *a):
        self.warnings.append(str(m))

    def info(self, m, *a):
        pass


def main():
    with tempfile.TemporaryDirectory() as d:
        os.environ["HOME"] = d
        os.makedirs(os.path.join(d, "nado"), exist_ok=True)
        from loops.core_loop import CoreClient
        import types

        def run(archive, force_reanchor):
            """Drive the real snapshot_bootstrap guard with no peers, so it returns before any I/O."""
            log = FakeLog()
            core = types.SimpleNamespace(memserver=FakeMem(archive, tip=0 if not force_reanchor else 5000),
                                         logger=log)
            ok = CoreClient.snapshot_bootstrap(core, force_reanchor=force_reanchor)
            return ok, log

        # ---- 1. a fresh ARCHIVE node refuses the shortcut --------------------------------------------
        ok, log = run(archive=True, force_reanchor=False)
        check("an archive node REFUSES snapshot bootstrap", ok is False)
        joined = " ".join(log.errors).lower()
        check("...and says so loudly (error, not a debug line)", len(log.errors) >= 3)
        check("...naming what a snapshot actually carries", "state, not history" in joined)
        check("...and every route to a real archive: genesis sync",
              "genesis" in joined)
        check("...copying a data directory", "data directory" in joined)
        check("...or dropping to rolling", "archive\": false" in joined or "archive\\\": false" in joined)

        # ---- a ROLLING node is completely unaffected --------------------------------------------------
        # It gets past the guard and fails later on "no peers", which is the pre-existing behaviour.
        ok, log = run(archive=False, force_reanchor=False)
        check("a rolling node still takes the snapshot path", ok is False and not log.errors)

        # ---- 2. WEDGE RECOVERY is never refused, for either kind of node ------------------------------
        # Refusing would leave an archive node stranded on a dead fork forever, serving nothing at all —
        # strictly worse than a truncated archive it can be told about.
        ok, log = run(archive=True, force_reanchor=True)
        check("wedge recovery is NOT refused for an archive node",
              not any("REFUSING SNAPSHOT BOOTSTRAP" in e for e in log.errors))
        ok, log = run(archive=False, force_reanchor=True)
        check("...nor for a rolling one", not log.errors)

        # ---- and it does not truncate at all: the canonical chain is KEPT and refilled ----------------
        # e160ccad replaced the "ARCHIVE TRUNCATED, re-seed" shout with ops/canonical_restore: the blocks
        # below the fork point are common to both chains and stay; what is canonical and absent is fetched
        # from the donor — ALL of it on an archive node. The shout is gone because there is nothing left
        # to shout about; a re-anchor that can still truncate would be a regression, not a logging change.
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "loops", "core_loop.py")).read()
        restore_call = "self._restore_canonical_chain(_old_index, anchor, source)"
        check("a re-anchor RESTORES the canonical chain instead of truncating it", restore_call in src)
        check("...after the identity change, so retained bodies are vouched for by the new identity",
              restore_call in src and src.index("snapshot_ops.adopt_new_identity(logger=self.logger)")
              < src.index(restore_call))
        body = src[src.index("def _restore_canonical_chain("):src.index("def _start_deep_fill(")] \
            if "def _restore_canonical_chain(" in src and "def _start_deep_fill(" in src else ""
        check("...fetching ALL of it on an archive node (deep remainder), the window on a rolling one",
              re.search(r'archive = bool\(getattr\(self\.memserver, "archive", False\)\)', body) is not None
              and "if archive:" in body and "_start_deep_fill(" in body)
        check("...and the old truncation shout is gone", "ARCHIVE TRUNCATED BY WEDGE RECOVERY" not in src)

        # the guard must sit BEFORE any peer I/O — a refusal that still polls the network is a refusal
        # that can hang, and this runs on the boot path
        gate = src.index("REFUSING SNAPSHOT BOOTSTRAP")
        peers = src.index("peers = list(self.memserver.peers)")
        check("the refusal happens before any peer I/O", gate < peers)

    print()
    print("ALL ARCHIVE-INTEGRITY CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
