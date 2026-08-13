"""
A node that cannot fetch must SAY so, and must try to fix itself first (ops/self_update.py).

THE INCIDENT. Four betanet-3 nodes stopped updating and stayed stuck for a day. Every /update answered:

    {"status": "fetch_failed", "reason": "git fetch failed: git fetch: exit 128 — fatal: unpack-objects failed"}

while the same nodes answered /status with `update_capable: true`, `update_blocking: []`,
`update_remote_reachable: true` and `update_available: false`. Nothing in the diagnosis looked at disk, and
`update_available` is derived from the last SUCCESSFUL fetch — which, on a node whose every fetch fails, can
never learn that origin moved. The node reported perfect health while it was permanently stranded, and the
condition was discoverable only by calling /update by hand and reading the string.

REPRODUCED (2026-08-13, 60 MiB loopback ext4, fetch run as the unprivileged service account):

    fatal: unable to write loose object file: No space left on device
    fatal: unpack-objects failed

DISK WAS NOT THE FLEET'S CAUSE. The reproduction matched the STRING, not this incident: once the new
telemetry shipped, 89.143.197.28 reported 1424 GiB free and was still failing intermittently. git prints
"fatal: unpack-objects failed" whenever the unpack-objects CHILD fails for ANY reason — ENOSPC, inode
exhaustion, or an OOM-kill — with nothing to tell them apart. The cause on these hosts is still UNKNOWN;
all three are now measured so the next occurrence names itself rather than earning another hypothesis.
Intermittency (the same node fetches fine on a retry minutes later) fits memory pressure, not a full disk.

Two details that make the disk case sneakier than "disk full":
  1. The write that fails is a LOOSE OBJECT. git takes the unpack-objects path whenever an incoming pack
     holds fewer than transfer.unpackLimit (default 100) objects — which is every push this project makes —
     so ordinary fetches land in git's most space-hungry form. Measured on the dev checkout: 2030 loose
     objects = 35.1 MiB, against 17112 PACKED objects = 22.6 MiB. ~17.7 KiB per loose object vs ~1.4 KiB.
  2. ext4 reserves 5% for root. The SERVICE USER hits the wall while `df` still shows space and a root
     shell writes happily — so the fetch that fails under systemd succeeds when the operator tries it by
     hand, which sends them looking anywhere but at disk.

WHAT THESE CHECKS PIN: that the space failure is CLASSIFIED as recoverable (so it earns a repack + retry
rather than a bare report), that unrelated git failures are NOT (a DNS hiccup must not trigger a gc), that
free disk is measured against the non-root allowance, and that a failed fetch becomes visible in the
diagnosis instead of being invisible until someone calls /update.

This cannot rescue an already-stranded node — it cannot receive this code; that is the defect. It stops the
next one, and makes the state visible in /status where a peer or an operator can see it.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fails = []


def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        _fails.append(name)


def main():
    os.environ.setdefault("HOME", tempfile.mkdtemp())
    from ops import self_update as su

    # ---- the failure the fleet actually reported is classified as recoverable --------------------------
    fleet_verbatim = "git fetch: exit 128 — fatal: unpack-objects failed"
    check("the fleet's verbatim error is recognised as disk pressure",
          su._looks_like_disk_pressure(fleet_verbatim))
    for msg in ("fatal: unable to write loose object file: No space left on device",
                "fatal: unpack-objects failed",
                "error: file write error: No space left on device",
                "fatal: Disk quota exceeded"):
        check(f"recoverable: {msg[:52]}", su._looks_like_disk_pressure(msg))

    # ---- and unrelated failures are NOT (a gc + retry on these is wasted work, or worse) ---------------
    for msg in ("git fetch: exit 128 — fatal: could not read Username for 'https://github.com'",
                "git fetch: timed out after 60s",
                "fatal: unable to access 'https://github.com/': Could not resolve host: github.com",
                "fatal: Unable to create '/srv/nado-home/nado/.git/index.lock': File exists"):
        check(f"NOT disk pressure: {msg[:52]}", not su._looks_like_disk_pressure(msg))

    # ---- free disk is measured against the NON-ROOT allowance -----------------------------------------
    # f_bavail, not f_bfree: ext4 holds back 5% for root, so f_bfree would report space the service
    # account cannot actually use — which is precisely the discrepancy that misdirects the operator.
    free = su._free_disk_mb()
    check("free disk is readable", free is not None and free >= 0)
    st = os.statvfs(su._REPO_DIR)
    check("...and uses f_bavail (non-root), not f_bfree",
          abs(free - (st.f_bavail * st.f_frsize) / (1024 * 1024)) < 1.0)
    check("f_bavail really is the stricter number (or equal, if unreserved)",
          st.f_bavail <= st.f_bfree)

    # ---- BYTES ARE NOT THE ONLY WAY THIS FAILS --------------------------------------------------------
    # 89.143.197.28 reported 1424 GiB free while every fetch died with "unpack-objects failed". git prints
    # that whenever the unpack-objects CHILD fails for ANY reason, so the message cannot distinguish
    # ENOSPC from inode exhaustion from an OOM-kill. All three are recorded so the next failure names
    # itself instead of inviting another hypothesis.
    r = su.updatability(probe_remote=False)
    check("inodes are measured (one loose object = one FILE; the worst consumer this node has)",
          "free_inodes" in r["checks"] or not os.statvfs(su._REPO_DIR).f_files)
    check("available memory is measured (an OOM-killed child reports the same string)",
          "mem_available_mb" in r["checks"])
    check("...and a healthy host trips none of them", not r["blocking"])

    # ---- thresholds are ordered and sane --------------------------------------------------------------
    check("warn threshold is above the blocking one", su._DISK_WARN_MB > su._DISK_BLOCKING_MB)
    check("blocking threshold leaves room for a fetch + repack", su._DISK_BLOCKING_MB >= 100)

    # ---- a failed fetch becomes VISIBLE in the diagnosis ----------------------------------------------
    # This is the whole point: updatability() is pure inspection and cannot fetch, so before this the
    # report could not know. The stranded nodes said capable=true, blocking=[].
    saved = su._last_fetch_error[0]
    try:
        su._last_fetch_error[0] = None
        clean = su.updatability(probe_remote=False)
        check("a healthy node reports no fetch failure",
              not any("last git fetch failed" in b for b in clean["blocking"]))
        check("...and reports its free disk in checks", "free_disk_mb" in clean["checks"])

        su._last_fetch_error[0] = fleet_verbatim
        broken = su.updatability(probe_remote=False)
        check("a node whose last fetch failed says so in blocking[]",
              any("last git fetch failed" in b for b in broken["blocking"]))
        check("...and is therefore NOT reported as capable", not broken["capable"])
        check("...naming git's own words, not a guess",
              any("unpack-objects failed" in b for b in broken["blocking"]))
    finally:
        su._last_fetch_error[0] = saved

    # ---- the fetch keeps packs instead of exploding to loose objects ----------------------------------
    src = open(os.path.join(su._REPO_DIR, "ops", "self_update.py")).read()
    check("both fetch call sites set transfer.unpackLimit=1",
          src.count('"-c", "transfer.unpackLimit=1"') == 2)
    # _git names the SUBCOMMAND in its errors; with a leading -c pair that used to become "git -c: ..."
    check("_subcommand skips leading -c pairs", su._subcommand(("-c", "a=b", "fetch", "--quiet")) == "fetch")
    check("...and is unchanged without them", su._subcommand(("fetch", "--quiet")) == "fetch")
    check("...and does not crash on a lone -c", su._subcommand(("-c",)) == "-c")

    print()
    print("ALL DISK-PRESSURE CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
