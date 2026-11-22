/*
 * test_an_in_page_tests_orphaned_browser_is_ended_and_a_running_ones_is_not.mjs — 2026-11-22: tests killed by `timeout`
 * never ran their cleanup, and the Chrome each had started detached lived on — seven, up to two days old, 70-340 % CPU
 * each, most of the host's load of 66-79. tests/_cdp_profiles.mjs killOrphanBrowsers (run by every in-page test's sweep):
 *   1. a test browser (its profile a cdp-<test>- folder) whose test is gone — reparented to init — has its group ended;
 *   2. one whose test is still running is left alone (side-by-side runs are safe), and so is any other program.
 * Stand-ins for Chrome: python processes whose command line carries "chrome" and a --user-data-dir, each its own group.
 * Run: node tests/test_an_in_page_tests_orphaned_browser_is_ended_and_a_running_ones_is_not.mjs
 */
import { spawn, execSync } from "node:child_process";
import { mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const { killOrphanBrowsers } = await import(join(dirname(fileURLToPath(import.meta.url)), "_cdp_profiles.mjs"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const alive = (pid) => existsSync("/proc/" + pid);
const root = mkdtempSync(join(tmpdir(), "orphtest-"));
const fake = (name) => ["-c", "import time; time.sleep(120)", "chrome", "--user-data-dir=" + join(root, name)];
// 1. an orphan: started by a shell that then exits, in a session (and group) of its own -> reparented to init
const orphanPid = Number(execSync(`sh -c 'setsid python3 ${fake("cdp-orphtest-a").map((a) => JSON.stringify(a)).join(" ")} > /dev/null 2>&1 & echo $!'`).toString().trim());
// 2. one whose "test" (this process) is alive: spawned detached, its own group, parent = us
const owned = spawn("python3", fake("cdp-orphtest-b"), { detached: true, stdio: "ignore" });
// 3. not a test browser at all: an orphan with no cdp- profile
const otherPid = Number(execSync(`sh -c 'setsid python3 ${fake("someone-elses").map((a) => JSON.stringify(a)).join(" ")} > /dev/null 2>&1 & echo $!'`).toString().trim());
await sleep(800);
const ppidOf = (pid) => { try { const st = execSync(`cat /proc/${pid}/stat`).toString(); return Number(st.slice(st.lastIndexOf(")") + 2).split(" ")[1]); } catch (e) { return -1; } };
const isOrphan = ppidOf(orphanPid) === 1;
if (!isOrphan) console.log(`SKIP  this host reparents orphans to a subreaper (ppid ${ppidOf(orphanPid)}), not init — the rule cannot be exercised here`);
const n = killOrphanBrowsers(root);
await sleep(500);
if (isOrphan) ok(!alive(orphanPid) && n >= 1, "a test browser whose test is gone (reparented to init) is ended");
ok(alive(owned.pid), "a test browser whose test is still running is left alone");
ok(alive(otherPid), "an orphan that is not a test browser (no cdp- profile) is left alone");
for (const p of [orphanPid, owned.pid, otherPid]) { try { process.kill(-p, "SIGKILL"); } catch (e) {} try { process.kill(p, "SIGKILL"); } catch (e) {} }
rmSync(root, { recursive: true, force: true });
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
