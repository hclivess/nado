"""/status publishes every node's native-library state (2026-09-25), and the updater checks the file each loader opens.

After a Rust commit a peer must rebuild its libraries during /update, and nothing let an operator confirm that
without a shell on the box. self_update.native_report() now rides in /status: per crate, the library's state
(ok / stale / missing, by native_guard.is_stale, the loader's own definition), its build time, and whether it was
rebuilt after this process loaded it (restart_needed).

Building it found a real gap: the updater's staleness and digest checks built `libnado_<crate>.so` for every crate,
but wasm/goldilocks' loader opens `libgoldilocks.so`, so a stale goldilocks library was never detected or rebuilt.
Both now go through self_update._loader_lib.

Driven against a temporary crate tree; never touches the real native/ directory.
Run: python3 tests/test_native_report.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-native-report-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import sys, time, traceback
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ops import self_update as SU

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def _crate(repo, crate, lib, src_age, lib_age):
    """A fake crate: src/lib.rs aged `src_age` seconds, the loader's library aged `lib_age` (None = absent)."""
    now = time.time()
    src = os.path.join(repo, crate, "src"); os.makedirs(src, exist_ok=True)
    rs = os.path.join(src, "lib.rs"); open(rs, "w").write("// x\n"); os.utime(rs, (now - src_age, now - src_age))
    rel = os.path.join(repo, crate, "target", "release"); os.makedirs(rel, exist_ok=True)
    if lib_age is not None:
        so = os.path.join(rel, lib); open(so, "wb").write(b"\0"); os.utime(so, (now - lib_age, now - lib_age))


def _with_repo(build):
    repo = tempfile.mkdtemp(dir=os.environ["HOME"])
    build(repo)
    saved = SU._REPO_DIR, SU._NATIVE_REPORT[:], SU._PROC_START
    SU._REPO_DIR, SU._NATIVE_REPORT[:] = repo, [0.0, None]
    return saved


def _restore(saved):
    SU._REPO_DIR, SU._NATIVE_REPORT[:], SU._PROC_START = saved[0], saved[1], saved[2]


def t_goldilocks_is_checked_under_the_name_its_loader_opens():
    assert SU._loader_lib("wasm/goldilocks").endswith("wasm/goldilocks/target/release/libgoldilocks.so")
    assert SU._loader_lib("native/starkprove").endswith("native/starkprove/target/release/libnado_starkprove.so")
    src = open(os.path.join(ROOT, "execnode", "stark", "goldilocks_native.py")).read()
    assert '"libgoldilocks.so"' in src, "the goldilocks loader's file name changed: update _loader_lib"


def t_each_state_is_reported_and_a_stale_goldilocks_is_now_seen():
    saved = _with_repo(lambda r: (
        _crate(r, "native/starkprove", "libnado_starkprove.so", src_age=100, lib_age=50),     # current
        _crate(r, "native/alghash2", "libnado_alghash2.so", src_age=10, lib_age=50),          # stale
        _crate(r, "native/attest", "libnado_attest.so", src_age=100, lib_age=None),           # missing
        _crate(r, "wasm/goldilocks", "libgoldilocks.so", src_age=10, lib_age=50)))            # stale, the gap
    try:
        SU._PROC_START = time.time()                          # every library predates this "process"
        rep = SU.native_report()
        c = rep["crates"]
        assert c["native/starkprove"]["state"] == "ok" and c["native/starkprove"]["built"]
        assert c["native/alghash2"]["state"] == "stale"
        assert c["native/attest"]["state"] == "missing" and c["native/attest"]["built"] is None
        assert c["wasm/goldilocks"]["state"] == "stale", "a stale goldilocks library must be reported"
        assert rep["ok"] is False
        assert not any(v["restart_needed"] for v in c.values())
        assert set(SU._stale_required_libs()) == {"native/alghash2", "wasm/goldilocks"}, \
            "the updater must see the stale goldilocks library too, or it never rebuilds it"
    finally:
        _restore(saved)


def t_a_library_rebuilt_after_the_process_started_needs_a_restart():
    saved = _with_repo(lambda r: _crate(r, "native/starkprove", "libnado_starkprove.so", src_age=100, lib_age=5))
    try:
        SU._PROC_START = time.time() - 60                     # the "process" loaded its libraries a minute ago
        rep = SU.native_report()
        assert rep["ok"] and rep["crates"]["native/starkprove"]["restart_needed"] is True
    finally:
        _restore(saved)


def t_the_report_is_cached():
    saved = _with_repo(lambda r: _crate(r, "native/starkprove", "libnado_starkprove.so", src_age=100, lib_age=50))
    try:
        first = SU.native_report()
        shutil.rmtree(os.path.join(SU._REPO_DIR, "native"))
        assert SU.native_report() is first, "a second call inside max_age must not stat again"
        assert SU.native_report(max_age=0)["crates"] == {}, "past max_age it re-reads"
    finally:
        _restore(saved)


def t_status_publishes_it():
    src = open(os.path.join(ROOT, "nado.py")).read()
    assert '"native": self_update.native_report(),' in src


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("t_"):
            check(name[2:].replace("_", " "), fn)
    print("ALL PASS" if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
