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
TL = importlib.util.module_from_spec(spec)
# Pillow blocked while the table is read: the pre-push runner has none, and an import of it at module level refused a push
_pil = sys.modules.get("PIL", False); sys.modules["PIL"] = None
try:
    spec.loader.exec_module(TL); readable = True
except ImportError:
    readable = False
finally:
    sys.modules.pop("PIL") if _pil is False else sys.modules.__setitem__("PIL", _pil)
check("the tool's material table reads where Pillow is not installed", readable)
if not readable:
    _report.done()

land = open(os.path.join(ROOT, "static", "land.js")).read()
check("the licence is stated: Poly Haven, CC0 1.0", "CC0 1.0" in src and "polyhaven.com" in src)
originals = re.findall(r"^(https://dl\.polyhaven\.org/\S+) ([0-9a-f]{32})$", src, re.M)
check("an original (url + MD5) for every material's colour and normal map", len(originals) == 2 * len(TL.MATERIALS), len(originals))
pins = dict((f, h) for h, f in re.findall(r"^([0-9a-f]{64})  (\S+)$", src, re.M))
files = sorted(f for f in os.listdir(D) if f.endswith(".jpg"))
check("every file in the folder is pinned, and every pin is a file", sorted(pins) == files, (sorted(set(files) ^ set(pins))))
bad = [f for f in files if hashlib.sha256(open(os.path.join(D, f), "rb").read()).hexdigest() != pins.get(f)]
check("every texture's bytes are the recorded ones", not bad, bad)
check("the tool's materials are exactly the folder's (and the phone set)", sorted([f"{k}_{t}.jpg" for k in TL.MATERIALS for t in ("col", "nor")] + TL.phone_files()) == files,
      sorted(set(files) ^ set([f"{k}_{t}.jpg" for k in TL.MATERIALS for t in ("col", "nor")] + TL.phone_files())))
# THE PHONE SET (#139/#150): the ground at 512 px for a phone, made from the 1024 px outputs; a quarter of the bytes
ground = [k for k, (_, px) in TL.MATERIALS.items() if px > TL.PHONE_PX]
check("a 512 px copy of every map of the ground's six, for phones", sorted(ground) == sorted(["grass", "dirt", "rock", "sand", "snow", "gravel"])
      and TL.phone_files() == sorted(f"{k}_{t}_512.jpg" for k in ground for t in ("col", "nor")))
def _px(f):  # a baseline/progressive JPEG's size from its SOF marker, without Pillow
    b = open(os.path.join(D, f), "rb").read(); i = 2
    while i < len(b):
        m, n = b[i + 1], int.from_bytes(b[i + 2:i + 4], "big")
        if m in (0xC0, 0xC1, 0xC2): return int.from_bytes(b[i + 7:i + 9], "big"), int.from_bytes(b[i + 5:i + 7], "big")
        i += 2 + n
    return None
check("…each 512 × 512, its 1024 px original beside it", all(_px(f) == (512, 512) and _px(f.replace("_512", "")) == (1024, 1024) for f in TL.phone_files()),
      [(f, _px(f)) for f in TL.phone_files()][:3])
big = sum(os.path.getsize(os.path.join(D, f.replace("_512", ""))) for f in TL.phone_files())
small = sum(os.path.getsize(os.path.join(D, f)) for f in TL.phone_files())
check(f"…a third of the bytes or less ({small / 1e6:.2f} MB against {big / 1e6:.2f})", small * 3 <= big)
check("the page loads the 512 px ground on a phone only, and every other material at its own size",
      'const file = PHONE && GROUND.includes(name.replace(/_(col|nor)$/, "")) ? name + "_512" : name;' in land
      and "/static/vendor/textures/${file}.jpg" in land)
check("the page loads the ground's six from here", all(f'"{k}"' in land for k in ("grass", "dirt", "rock", "sand", "snow", "gravel"))
      and "/static/vendor/textures/" in land)
_report.done()
