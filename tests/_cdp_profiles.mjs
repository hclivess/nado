// The in-page tests' Chrome profiles (cdp-<test>-*: cdp-landlive-, cdp-landhud-, cdp-dexcancel- …): what a run that never reached its cleanup left behind is swept at
// the start of the next. Found 2026-11-16 on the live host: 109 profiles, 14 GB, in /tmp since 11-11, the disk at 96 %
// beside the node's database — a cleanup that killed only Chrome's main process deleted the profile while its helper
// processes were still writing into it (the tests now kill Chrome's whole process group), and a run killed by a timeout
// never cleaned up at all (this sweep). Not a test itself: imported by them.
import { readdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
export const STALE_MS = 2 * 3600 * 1000;                     // longer than any in-page test runs (the quest walk: ~13 min)
// ORPHANED BROWSERS (2026-11-22): a test killed by `timeout` never runs its cleanup, and the Chrome it started DETACHED (its
// own process group) lives on — seven of them, up to two days old, each burning 70-340 % CPU, were most of the host's load
// of 66-79, and a running orphan keeps writing to its profile so the stale sweep never touched it. A test's Chrome whose
// parent is gone (reparented to init, ppid 1) has no test left to clean it: its whole process group is ended. A browser
// whose test is still running is never touched — side-by-side runs are safe.
export function killOrphanBrowsers(root = tmpdir()) {
  let n = 0;
  let pids = [];
  try { pids = readdirSync("/proc").filter((d) => /^\d+$/.test(d)); } catch (e) { return 0; }   // (not Linux: nothing to do)
  for (const pid of pids) {
    try {
      const args = readFileSync(`/proc/${pid}/cmdline`, "utf8").split("\0");
      if (!args.some((a) => /chrome/.test(a)) || args.some((a) => a.startsWith("--type="))) continue;   // Chrome's main process only
      const dir = (args.find((a) => a.startsWith("--user-data-dir=")) || "").slice(16);
      if (!dir.startsWith(root + "/") || !/^cdp-[a-z]+-/.test(dir.slice(root.length + 1))) continue;   // an in-page test's browser
      const st = readFileSync(`/proc/${pid}/stat`, "utf8"), f = st.slice(st.lastIndexOf(")") + 2).split(" ");
      const ppid = Number(f[1]), pgid = Number(f[2]);
      if (ppid !== 1 || pgid !== Number(pid)) continue;                    // its test still owns it / not a group leader
      process.kill(-pgid, "SIGKILL"); n++;
    } catch (e) {}
  }
  return n;
}
export function sweepStaleProfiles(root = tmpdir(), now = Date.now()) {
  let n = 0;
  killOrphanBrowsers(root);
  for (const name of readdirSync(root)) {
    // every in-page test's profile, not only cdp-landlive-: ten tests named theirs otherwise (cdp-landhud-, cdp-landleaf-…),
    // had neither this sweep nor the group kill, and left 84 profiles, 3.3 GB, in /tmp (found 2026-11-17)
    if (!/^cdp-[a-z]+-/.test(name)) continue;
    const p = join(root, name);
    try { if (statSync(p).isDirectory() && now - statSync(p).mtimeMs > STALE_MS) { rmSync(p, { recursive: true, force: true }); n++; } } catch (e) {}
  }
  return n;
}
