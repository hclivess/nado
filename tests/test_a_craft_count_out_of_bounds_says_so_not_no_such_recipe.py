"""
A CRAFT COUNT OUT OF BOUNDS SAYS SO (2026-11-16): the town agent, making through /land/api/craft, asked for 73 charcoal
at once and was told "no such recipe" — for a recipe that exists; the count was over the server's limit. World.craft now
answers a count it will not take with its own refusal, "make 1 to 64 at a time", and keeps "no such recipe" for a recipe
that does not exist; 1 and 64 are made, 0, 65, a fraction and true are not.
Run: python3 tests/test_a_craft_count_out_of_bounds_says_so_not_no_such_recipe.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-craftcount-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import importlib.util, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
import _harness
_report = _harness.Report(); check = _report.check

w = S.World(os.path.join(os.environ["HOME"], "land"), "http://127.0.0.1:1", "")
WHO = "ndoCRAFT" + "C" * 40
pl = w.player(WHO)
pl["items"]["wood"] = 200
w._has = lambda p, need: True                                  # the stations are not what is tested here
check("the limit is a named constant (64)", S.CRAFT_MAX == 64)
check("1 charcoal is made", w.craft(WHO, "charcoal", 1) is None and pl["items"]["charcoal"] == 2, pl["items"])
check("64 at once is made", w.craft(WHO, "charcoal", 64) is None and pl["items"]["wood"] == 200 - 65, pl["items"])
for bad in (65, 73, 0, -1, 2.5, True):
    err = w.craft(WHO, "charcoal", bad)
    check(f"{bad!r} at once is refused with the count's own message, not \"no such recipe\"", err == "make 1 to 64 at a time", err)
check("…and nothing is spent on a refused count", pl["items"]["wood"] == 135, pl["items"])
check("a recipe that does not exist is still \"no such recipe\"", w.craft(WHO, "unobtainium", 1) == "no such recipe")
_report.done()
