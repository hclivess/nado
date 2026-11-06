"""
Land's material textures (static/vendor/textures/) are exactly what tools/land_textures.py built from the recorded Poly
Haven originals, all CC0 1.0 (public domain): the pictures every player downloads are pinned, not just named.

  * SOURCE.txt states the licence and lists an original (Poly Haven URL + its published MD5) for every material's colour
    and normal map, and an output SHA-256 for every file in the folder — nothing unlisted, nothing missing;
  * every output's bytes hash to its line (an edit, a re-encode or a swapped file fails here);
  * the tool's material table and the folder agree, and the page loads the ground's six from it.

Run: python3 tests/test_the_land_textures_are_the_recorded_cc0_sources.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-textures-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import hashlib, importlib.util, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _harness
_report = _harness.Report()
check = _report.check

D = os.path.join(ROOT, "static", "vendor", "textures")
src = open(os.path.join(D, "SOURCE.txt")).read()
spec = importlib.util.spec_from_file_location("land_textures", os.path.join(ROOT, "tools", "land_textures.py"))
TL = importlib.util.module_from_spec(spec); spec.loader.exec_module(TL)

check("the licence is stated: Poly Haven, CC0 1.0", "CC0 1.0" in src and "polyhaven.com" in src)
originals = re.findall(r"^(https://dl\.polyhaven\.org/\S+) ([0-9a-f]{32})$", src, re.M)
check("an original (url + MD5) for every material's colour and normal map", len(originals) == 2 * len(TL.MATERIALS), len(originals))
pins = dict((f, h) for h, f in re.findall(r"^([0-9a-f]{64})  (\S+)$", src, re.M))
files = sorted(f for f in os.listdir(D) if f.endswith(".jpg"))
check("every file in the folder is pinned, and every pin is a file", sorted(pins) == files, (sorted(set(files) ^ set(pins))))
bad = [f for f in files if hashlib.sha256(open(os.path.join(D, f), "rb").read()).hexdigest() != pins.get(f)]
check("every texture's bytes are the recorded ones", not bad, bad)
check("the tool's materials are exactly the folder's", sorted(f"{k}_{t}.jpg" for k in TL.MATERIALS for t in ("col", "nor")) == files)
land = open(os.path.join(ROOT, "static", "land.js")).read()
check("the page loads the ground's six from here", all(f'"{k}"' in land for k in ("grass", "dirt", "rock", "sand", "snow", "gravel"))
      and "/static/vendor/textures/" in land)
_report.done()
