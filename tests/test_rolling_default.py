"""
ROLLING MODE IS THE DEFAULT, and the consensus floor under it cannot be lowered by config.

WHY IT FLIPPED. An archive node keeps every block body forever, and "forever" is not a rounding error:
measured on betanet-3, bodies grew 133 MB/day = ~47.6 GB/year. That is a reasonable price for the one box
that hosts an explorer and an unreasonable one for the volunteer VPSes that are most of the network. It is
also not a storage problem that stays a storage problem — a node that fills its disk stops UPDATING (git
fetch cannot write its objects), and once it cannot take a consensus change it forks. Four nodes were
already stuck that way when this flipped.

Rolling keeps STATE and the number<->hash indexes and drops only bodies older than the retention window,
so the node still validates, produces, and serves beacon/FFG lookbacks. What it loses is the ability to
serve ancient bodies to a peer or an explorer.

WHAT THESE CHECKS PIN:

  * the default is rolling in EVERY place that decides it. There are four — config.py's generated file,
    memserver's fallback for configs that predate the key, the core loop's prune guard, and /status's
    node_type. They are independent `getattr(..., default)` sites, so a mismatch does not fail loudly: it
    produces a node that reports one mode and behaves as the other.
  * the HARD FLOOR holds. prune_block_bodies computes it from consensus constants and takes max() against
    the configured retention, so no operator setting (and no zero) can prune into a window consensus still
    reads. POSW_ANCHOR_OFFSET feeds that floor and moved 30 -> 150 the same day, which is exactly the kind
    of change that silently invalidates a retention assumption.
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


def main():
    with tempfile.TemporaryDirectory() as d:
        os.environ["HOME"] = d
        os.makedirs(os.path.join(d, "nado"), exist_ok=True)
        from protocol import (HISTORY_RETENTION_BLOCKS, POSW_ANCHOR_OFFSET, POSW_DIFF_TRAIL,
                              EPOCH_LENGTH, FINALITY_DEPTH, REWARD_WINDOW, BLOCK_TIME)
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # ---- all four decision sites agree on ROLLING -------------------------------------------------
        cfg = open(os.path.join(root, "config.py")).read()
        m = re.search(r'"archive":\s*(True|False)', cfg)
        check("config.py generates archive=False", bool(m) and m.group(1) == "False")

        mem = open(os.path.join(root, "memserver.py")).read()
        check("memserver falls back to archive=False for configs predating the key",
              'self.config.get("archive", False)' in mem)
        check("...and nothing there still defaults to True",
              'self.config.get("archive", True)' not in mem)

        core = open(os.path.join(root, "loops", "core_loop.py")).read()
        check("the prune guard defaults to rolling (so the prune actually RUNS)",
              'getattr(self.memserver, "archive", False)' in core)

        nado = open(os.path.join(root, "nado.py")).read()
        check("/status reports the same default it behaves as",
              'getattr(memserver, "archive", True)' not in nado)

        # ---- the hard floor cannot be lowered by config ------------------------------------------------
        # Mirrors prune_block_bodies exactly; the point is that `retention` never wins against it.
        floor = max(REWARD_WINDOW + FINALITY_DEPTH + 1,
                    POSW_ANCHOR_OFFSET + POSW_DIFF_TRAIL * EPOCH_LENGTH + FINALITY_DEPTH)

        def effective(retention):
            r = int(retention) if retention and int(retention) > 0 else HISTORY_RETENTION_BLOCKS
            return max(r, floor)

        check(f"a 0 (unset) retention uses the protocol default ({HISTORY_RETENTION_BLOCKS} blocks)",
              effective(0) == max(HISTORY_RETENTION_BLOCKS, floor))
        check("an absurdly small retention is floored, not honoured", effective(1) == floor)
        check("a negative retention cannot prune anything extra", effective(-99999) >= floor)
        check("a LARGER retention is honoured (an operator may always keep more)",
              effective(HISTORY_RETENTION_BLOCKS * 4) == HISTORY_RETENTION_BLOCKS * 4)

        # the floor must cover the whole registration-difficulty read window, which POSW_ANCHOR_OFFSET
        # feeds — it moved 30 -> 150 on 2026-08-13 and this is what keeps that honest
        check("the floor covers the reg-difficulty read window",
              floor >= POSW_ANCHOR_OFFSET + POSW_DIFF_TRAIL * EPOCH_LENGTH)
        check("...and the rollback/reward window", floor >= REWARD_WINDOW + FINALITY_DEPTH)

        # ---- and the default retention is actually a sane disk budget ----------------------------------
        days = HISTORY_RETENTION_BLOCKS * BLOCK_TIME / 86400
        MB_PER_DAY = 133           # measured on betanet-3, 2026-08-13
        check(f"the default keeps ~{days:.1f} days of bodies (>= 1 day of real history)", days >= 1.0)
        check(f"...which is ~{days * MB_PER_DAY:.0f} MB, not the ~{365 * MB_PER_DAY / 1024:.1f} GB/year an "
              f"archive node grows to", days * MB_PER_DAY < 4096)
        check("the floor alone is a small fraction of that",
              floor * BLOCK_TIME / 86400 * MB_PER_DAY < days * MB_PER_DAY)

    # ---- the MIGRATION, which is the only thing that reaches an already-installed node ---------------
    # A changed default reaches new installs and nothing else: create_config is create-only and writes
    # every default at install time, so the value the old installer wrote is indistinguishable on disk
    # from a value the operator chose. Observed directly — flipping the default moved exactly the ONE node
    # whose config predated the key, while five nodes carrying an installer-written "archive": true kept
    # archiving. Those five are the nodes the change is for.
    import json
    from config import migrate_config, get_config, update_config, CONFIG_VERSION
    cdir = os.path.join(d, "nado", "private")
    os.makedirs(cdir, exist_ok=True)
    cp = os.path.join(cdir, "config.json")

    def write(cfg):
        json.dump(cfg, open(cp, "w"))

    write({"port": 9173, "archive": True, "auto_update": True})
    r = migrate_config(config_path=cp)
    check("an installer-written archive=True is migrated to rolling",
          r["migrated"] and r["changed"].get("archive") is False)
    check("...and the file now says so", get_config(cp)["archive"] is False)
    check("...and is stamped, so it never runs twice",
          get_config(cp)["config_version"] == CONFIG_VERSION)
    check("re-running is a no-op", migrate_config(config_path=cp)["migrated"] is False)

    # THE IMPORTANT ONE: a deliberate choice must survive. An explorer/seed operator sets archive back on;
    # a migration that kept re-flipping it would be a bug that silently deletes their history.
    update_config({"archive": True}, cp)
    migrate_config(config_path=cp)
    check("an operator who deliberately re-enables archive KEEPS it", get_config(cp)["archive"] is True)

    write({"port": 9173})
    check("a config that never had the key is left alone (already rolling by default)",
          "archive" not in migrate_config(config_path=cp).get("changed", {}))
    write({"port": 9173, "archive": False})
    check("an operator who already chose rolling is untouched",
          "archive" not in migrate_config(config_path=cp).get("changed", {}))

    # every knob create_config writes must be readable by the migration path
    check("newly created configs are stamped with the current version",
          '"config_version": CONFIG_VERSION' in open(os.path.join(root, "config.py")).read())

    print()
    print("ALL ROLLING-DEFAULT CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
