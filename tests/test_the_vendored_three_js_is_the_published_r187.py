"""
The three.js the Land game loads (static/vendor/three/) is the published r187 WebGPU build, byte for byte.

A vendored library is code every player runs; an edit to it — by a person, a formatter, or a merge — is invisible in a
diff of a 1.4 MB file. So the bytes are pinned: each file's SHA-256 must equal the line static/vendor/three/SOURCE.txt
records for it (taken from `npm pack three@0.187.0`, whose tarball matched the registry's dist.integrity), every file
the build imports is present, and the page imports exactly this build.

Run: python3 tests/test_the_vendored_three_js_is_the_published_r187.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-three-vendor-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import hashlib, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _harness
_report = _harness.Report()
check = _report.check

D = os.path.join(ROOT, "static", "vendor", "three")
src = open(os.path.join(D, "SOURCE.txt")).read()
pins = dict((name, h) for h, name in re.findall(r"^([0-9a-f]{64})  (\S+)$", src, re.M))
check("SOURCE.txt pins the three build files, the licence and the post-processing add-ons",
      set(pins) == {"three.webgpu.js", "three.core.js", "three.tsl.js", "LICENSE", "addons/tsl/display/GTAONode.js",
                    "addons/tsl/display/BloomNode.js", "addons/tsl/display/FXAANode.js"}, pins)
for name, want in sorted(pins.items()):
    p = os.path.join(D, name)
    got = hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None
    check(f"{name} is the published file", got == want, f"{got} != {want}")
check("the files are r187", "three@0.187.0" in src and "REVISION = '187'" in open(os.path.join(D, "three.core.js")).read())
for name in ("three.webgpu.js", "three.tsl.js"):
    deps = set(re.findall(r"from '\./([^']+)'", open(os.path.join(D, name)).read()))
    check(f"every file {name} imports is vendored beside it", deps and all(os.path.exists(os.path.join(D, x)) for x in deps), deps)
html = open(os.path.join(ROOT, "static", "land.html")).read()
check("the page's import map points the add-ons' bare imports at this build (through the one-URL shims)",
      '"three/webgpu":"/static/land-three-webgpu.js"' in html and '"three/tsl":"/static/land-three-tsl.js"' in html
      and 'export * from "/static/vendor/three/three.webgpu.js"' in open(os.path.join(ROOT, "static", "land-three-webgpu.js")).read()
      and 'export * from "/static/vendor/three/three.tsl.js"' in open(os.path.join(ROOT, "static", "land-three-tsl.js")).read())
land = open(os.path.join(ROOT, "static", "land.js")).read()
check("the Land page imports this build, by the import map's names", 'from "three/webgpu"' in land and 'from "three/tsl"' in land)
_report.done()
