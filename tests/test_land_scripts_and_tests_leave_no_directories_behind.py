"""The Land world server, the agent client and the Land tests leave nothing behind in the temp directory.

Found 2026-11-08, cleaning up after a session: 640 `nado-land-*` directories (the world server's own HOME, made on every
start and on every import by a test, never removed), 355 `nado_land_*` worlds made by tests outside their HOME, and 60
browser profiles left by the plot photographer in one day (that one: test_a_land_title_is_listed_with_its_aerial_photo…).

  1. the world server and the agent client, run, remove the HOME they made for themselves;
  2. a Land test makes its world inside its own HOME, which it removes;
  3. a test that starts the live fixture (and kills it, so the fixture's exit handlers never run) starts it with TMPDIR in
     the work directory it removes;
  4. a browser test tries Google Chrome before a snap Chromium, whose /tmp is a private one its cleanup never reaches.
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-noleft-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import glob, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    fails += 0 if cond else 1


# 1. run each script's --help with a temp directory of its own: it makes its HOME there and must leave it empty
for script in ("land_server.py", "land_agent.py"):
    tmp = tempfile.mkdtemp(prefix="tmpdir-", dir=os.environ["HOME"])
    env = {**os.environ, "TMPDIR": tmp, "NADO_ALLOW_PYTHON_KERNELS": "1"}
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", script), "--help"], env=env, capture_output=True, text=True, timeout=120)
    left = os.listdir(tmp)
    check(f"scripts/{script} runs and removes the HOME it made", r.returncode == 0 and left == [], f"rc={r.returncode} left={left} {r.stderr[-300:]}")

# 2. a test's Land world lives inside its HOME
for path in sorted(glob.glob(os.path.join(ROOT, "tests", "*.py"))):
    src = open(path, encoding="utf-8").read()
    for m in re.finditer(r'tempfile\.mkdtemp\(prefix="(nado_land_[a-z_]*)"([^)]*)\)', src):
        check(f"{os.path.basename(path)} makes its {m.group(1)} world inside its HOME", 'dir=os.environ["HOME"]' in m.group(2))

# 3. a test that starts the live fixture gives it TMPDIR in its work directory
for path in sorted(glob.glob(os.path.join(ROOT, "tests", "*.mjs"))):
    src = open(path, encoding="utf-8").read()
    if "_land_live_fixture.py" not in src:
        continue
    spawns = re.findall(r'spawn\("python3", \[join\(ROOT, "tests", "_land_live_fixture.py"\)[^\n]*', src)
    check(f"{os.path.basename(path)} starts the fixture with TMPDIR in its work directory",
          spawns and all("TMPDIR: work" in s for s in spawns) and "rmSync(d, { recursive: true, force: true })" in src)

# 4. a browser test tries Google Chrome before a snap Chromium: a snap's /tmp is its own private one
# (/tmp/snap-private-tmp/snap.chromium/tmp), so the profile a test made in /tmp and removed after was really written
# there and never removed — 15 GB of test profiles by 2026-11-08 ("something is filling up drive space")
for path in sorted(glob.glob(os.path.join(ROOT, "tests", "*.mjs"))):
    src = open(path, encoding="utf-8").read()
    for lst in re.findall(r'for \(const bin of \[([^\]]*)\]', src):
        names = re.findall(r'"([a-z-]+)"', lst)
        if "chromium-browser" in names and "google-chrome" in names:
            check(f"{os.path.basename(path)} tries Google Chrome before the snap Chromium", names.index("google-chrome") < names.index("chromium-browser"), names)

print("ALL PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
