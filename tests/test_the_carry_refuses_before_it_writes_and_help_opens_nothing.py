"""The carry runs every refusal before it writes anything — in the dry run too — and `--help` opens no database
(tools/alphanet6_carryforward.py main(); found in the gen-29 rehearsal, 2026-10-25).

Two defects, both reproduced:
  * build_extra() — where an open invite whose link key cannot be recovered REFUSES the carry — ran only under --write,
    and AFTER genesis_alloc.dat had been written. So the documented dry run reported nothing about invites, and the
    --write that refused left a half-written genesis: a new alloc beside the previous reroll's carry file.
  * the tool parses no arguments, so `--help` ran the whole carry: build() opened get_home()'s LMDB env, which under
    root's HOME is the live node's database.

Pins: in main(), the refusal path (build_extra) runs before the first write and whenever a tip is given; and `--help`
prints the usage and exits 0 without creating anything under HOME (no env was opened).

Run: python3 tests/test_the_carry_refuses_before_it_writes_and_help_opens_nothing.py
"""
import os, sys, tempfile, subprocess
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-carryorder-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


src = open(os.path.join(ROOT, "tools", "alphanet6_carryforward.py"), encoding="utf-8").read()
main = src[src.index("def main():"):]
first_write = main.index('if "--write" in sys.argv:')
refusals = main.find("extra = build_extra()")
check("main() builds the carried extras (the invite refusal) before the first write", 0 <= refusals < first_write,
      (refusals, first_write))
check("...whenever a tip is given, so the dry run refuses exactly as --write does",
      'if extra is None and ("--write" in sys.argv or "--l1-tip" in sys.argv):' in main[:first_write])
check("...and the write path never builds them late (no call after the first write)",
      "= build_extra()" not in main[first_write:])
help_at, build_at = main.index('("-h", "--help")'), main.index("alloc = build()")
check("--help is answered before build() opens any database", help_at < build_at)

home = os.environ["HOME"]
before = sorted(os.listdir(home))
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "alphanet6_carryforward.py"), "--help"],
                   capture_output=True, text=True, timeout=300, cwd=ROOT, env=dict(os.environ))
check("--help prints the usage and exits 0", r.returncode == 0 and "carry" in r.stdout.lower(), r.stderr[-400:])
check("...and creates nothing under HOME (no LMDB env was opened)", sorted(os.listdir(home)) == before,
      sorted(os.listdir(home)))

print("\nALL PASS — the carry refuses before it writes, and --help opens nothing" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
