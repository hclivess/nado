/*
 * test_the_in_page_tests_leave_no_browser_profile_behind.mjs — found 2026-11-16 on the live host: 109 Chrome profiles of
 * the in-page tests (cdp-landlive-*), 14 GB, in /tmp since 11-11, the disk at 96 % beside the node's database. Each test's
 * cleanup killed only Chrome's main process and deleted the profile while its helper processes were still writing into
 * it; and a run killed by a timeout never cleaned up at all. Every in-page test now starts Chrome in its own process
 * group and kills the group, and sweeps at its start the profiles a killed run left (tests/_cdp_profiles.mjs). Here the
 * sweep runs on a scratch directory, and every test that makes such a profile is read for the three.
 * Run: node tests/test_the_in_page_tests_leave_no_browser_profile_behind.mjs
 */
import { readFileSync, readdirSync, mkdtempSync, mkdirSync, utimesSync, existsSync, rmSync } from "node:fs";
import { join, dirname } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { sweepStaleProfiles, STALE_MS } from "./_cdp_profiles.mjs";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const dir = mkdtempSync(join(tmpdir(), "sweep-test-"));
try {
  const old = join(dir, "cdp-landlive-old"), old2 = join(dir, "cdp-landhud-old"), fresh = join(dir, "cdp-landlive-fresh"), other = join(dir, "not-a-profile");
  for (const d of [old, old2, fresh, other]) mkdirSync(join(d, "Default"), { recursive: true });
  const past = (Date.now() - STALE_MS - 60000) / 1000;
  utimesSync(old, past, past); utimesSync(old2, past, past); utimesSync(other, past, past);
  const n = sweepStaleProfiles(dir);
  ok(n === 2 && !existsSync(old) && !existsSync(old2), "a profile older than any test runs is swept, whichever test named it (cdp-landlive-, cdp-landhud-)");
  ok(existsSync(fresh) && existsSync(other), "…a fresh one (a test running now) is kept, and nothing that is not such a profile is touched");
} finally { rmSync(dir, { recursive: true, force: true }); }
const tests = readdirSync(join(ROOT, "tests")).filter((f) => f.endsWith(".mjs") && !f.startsWith("_") && f !== "test_the_in_page_tests_leave_no_browser_profile_behind.mjs").map((f) => [f, readFileSync(join(ROOT, "tests", f), "utf8")]).filter(([, s]) => /mkdtempSync\(join\(tmpdir\(\), "cdp-[a-z]+-"\)\)/.test(s));   // EVERY test-made profile, not
// only cdp-landlive-: ten tests named theirs otherwise and had none of the three below (84 profiles, 3.3 GB, 2026-11-17)
ok(tests.length >= 30, `(${tests.length} in-page tests make a Chrome profile in the temp directory)`);
const bad = (pred) => tests.filter(([, s]) => !pred(s)).map(([f]) => f);
let b = bad((s) => /"about:blank"\], \{ stdio: "ignore", detached: true \}\)/.test(s));
ok(!b.length, "each starts Chrome in its own process group " + (b.length ? JSON.stringify(b) : ""));
b = bad((s) => s.includes('chrome && process.kill(-chrome.pid, "SIGKILL")') && !s.includes('chrome && chrome.kill("SIGKILL")'));
ok(!b.length, "…and kills the whole group, helpers and all, before deleting the profile " + (b.length ? JSON.stringify(b) : ""));
b = bad((s) => s.includes('import { sweepStaleProfiles } from "./_cdp_profiles.mjs";') && s.indexOf("sweepStaleProfiles();") < s.search(/mkdtempSync\(join\(tmpdir\(\), "cdp-[a-z]+-"\)\)/));
ok(!b.length, "…and sweeps what a killed run left, before making its own " + (b.length ? JSON.stringify(b) : ""));
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
