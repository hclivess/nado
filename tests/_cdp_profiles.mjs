// The in-page tests' Chrome profiles (cdp-<test>-*: cdp-landlive-, cdp-landhud-, cdp-dexcancel- …): what a run that never reached its cleanup left behind is swept at
// the start of the next. Found 2026-11-16 on the live host: 109 profiles, 14 GB, in /tmp since 11-11, the disk at 96 %
// beside the node's database — a cleanup that killed only Chrome's main process deleted the profile while its helper
// processes were still writing into it (the tests now kill Chrome's whole process group), and a run killed by a timeout
// never cleaned up at all (this sweep). Not a test itself: imported by them.
import { readdirSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
export const STALE_MS = 2 * 3600 * 1000;                     // longer than any in-page test runs (the quest walk: ~13 min)
export function sweepStaleProfiles(root = tmpdir(), now = Date.now()) {
  let n = 0;
  for (const name of readdirSync(root)) {
    // every in-page test's profile, not only cdp-landlive-: ten tests named theirs otherwise (cdp-landhud-, cdp-landleaf-…),
    // had neither this sweep nor the group kill, and left 84 profiles, 3.3 GB, in /tmp (found 2026-11-17)
    if (!/^cdp-[a-z]+-/.test(name)) continue;
    const p = join(root, name);
    try { if (statSync(p).isDirectory() && now - statSync(p).mtimeMs > STALE_MS) { rmSync(p, { recursive: true, force: true }); n++; } } catch (e) {}
  }
  return n;
}
