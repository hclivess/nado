"""/status publishes every node's native-library state (2026-09-25), and the updater checks the file each loader opens.

After a Rust commit a peer must rebuild its libraries during /update, and nothing let an operator confirm that
without a shell on the box. self_update.native_report() now rides in /status: per crate, the library's state
(ok / stale / missing, by native_guard.is_stale, the loader's own definition), its build time, and whether it was
rebuilt after this process loaded it (restart_needed).

Building it found a real gap: the updater's staleness and digest checks built `libnado_<crate>.so` for every crate,
but wasm/goldilocks' loader opened `libgoldilocks.so`, so a stale goldilocks library was never detected or rebuilt.
Both now go through self_update._loader_lib. (wasm/goldilocks itself was deleted in G9 slice 6; a deleted crate's
leftover build must stay invisible to all of this.)

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

import _harness
_report = _harness.Report()
check = _report.run


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


def t_every_crate_is_checked_under_the_name_its_loader_opens():
    for crate in SU._CRATES + SU._OPTIONAL_CRATES:
        name = os.path.basename(crate)
        assert SU._loader_lib(crate).endswith(f"{crate}/target/release/libnado_{name}.so"), crate
    # (wasm/goldilocks, the one crate whose loader opened another name — libgoldilocks.so — was deleted in G9 slice 6.
    # A crate added with a different library name must be special-cased in _loader_lib, or it is never checked.)


def t_each_state_is_reported_and_a_stale_library_is_seen():
    saved = _with_repo(lambda r: (
        _crate(r, "native/mldsa44", "libnado_mldsa44.so", src_age=100, lib_age=50),          # current
        _crate(r, "native/stwo_js", "libnado_stwo_js.so", src_age=10, lib_age=50),            # stale
        _crate(r, "native/attest", "libnado_attest.so", src_age=100, lib_age=None),           # missing
        _crate(r, "native/pqsig", "libnado_pqsig.so", src_age=10, lib_age=50)))               # stale
    try:
        SU._PROC_START = time.time()                          # every library predates this "process"
        rep = SU.native_report()
        c = rep["crates"]
        assert c["native/mldsa44"]["state"] == "ok" and c["native/mldsa44"]["built"]
        assert c["native/stwo_js"]["state"] == "stale"
        assert c["native/attest"]["state"] == "missing" and c["native/attest"]["built"] is None
        assert c["native/pqsig"]["state"] == "stale"
        assert rep["ok"] is False
        assert not any(v["restart_needed"] for v in c.values())
        assert set(SU._stale_required_libs()) == {"native/stwo_js", "native/pqsig"}, \
            "the updater must see every stale required library, or it never rebuilds it"
    finally:
        _restore(saved)


def t_a_deleted_crates_leftover_build_is_neither_reported_nor_required():
    """G9 slice 6 deleted native/alghash2, starkcompose, starkprove and wasm/goldilocks. Their target/ dirs are git-ignored,
    so every fleet node keeps them after the update (and a leftover Cargo.toml/src if hand-edited). Nothing that judges
    libraries may look at them: a stale leftover reported here would flip native.ok, and one in _stale_required_libs
    would make the updater rebuild (and RESTART into) a crate with no sources. Everything iterates _CRATES."""
    gone = ("native/alghash2", "native/starkcompose", "native/starkprove", "wasm/goldilocks")
    assert not set(gone) & set(SU._CRATES + SU._OPTIONAL_CRATES)
    saved = _with_repo(lambda r: (
        [_crate(r, c, "libnado_x.so", src_age=10, lib_age=50) for c in gone],              # stale leftovers
        _crate(r, "wasm/goldilocks", "libgoldilocks.so", src_age=10, lib_age=50),
        [_crate(r, c, f"libnado_{os.path.basename(c)}.so", src_age=100, lib_age=50) for c in SU._CRATES]))
    try:
        rep = SU.native_report()
        assert not set(gone) & set(rep["crates"]), rep["crates"]
        assert rep["ok"] is True, rep
        assert SU._stale_required_libs() == [] and SU._missing_required_libs() == []
    finally:
        _restore(saved)


def t_a_library_rebuilt_after_the_process_started_needs_a_restart():
    saved = _with_repo(lambda r: _crate(r, "native/mldsa44", "libnado_mldsa44.so", src_age=100, lib_age=5))
    try:
        SU._PROC_START = time.time() - 60                     # the "process" loaded its libraries a minute ago
        rep = SU.native_report()
        assert rep["ok"] and rep["crates"]["native/mldsa44"]["restart_needed"] is True
    finally:
        _restore(saved)


def t_the_report_is_cached():
    saved = _with_repo(lambda r: _crate(r, "native/mldsa44", "libnado_mldsa44.so", src_age=100, lib_age=50))
    try:
        first = SU.native_report()
        shutil.rmtree(os.path.join(SU._REPO_DIR, "native"))
        assert SU.native_report() is first, "a second call inside max_age must not stat again"
        assert SU.native_report(max_age=0)["crates"] == {}, "past max_age it re-reads"
    finally:
        _restore(saved)


def t_it_names_the_rustc_this_node_would_build_with():
    """native.rustc: the compiler version a node would build crates with, so the fleet's oldest compiler can be read
    before a crate that needs a newer one ships (doc/stwo-migration.md §5.1); None without a usable compiler, never a
    crash. Driven with fake compilers on PATH (a throwaway HOME has no rustup default, so the real one prints nothing)."""
    import re as _re
    d = tempfile.mkdtemp(dir=os.environ["HOME"])
    def fake(out, code=0):
        p = os.path.join(d, "rustc")
        open(p, "w").write(f"#!/bin/sh\necho '{out}'\nexit {code}\n"); os.chmod(p, 0o755)
    saved = os.environ["PATH"]
    try:
        os.environ["PATH"] = d
        fake("rustc 1.95.0 (59807616e 2026-04-14)")
        SU._RUSTC.clear()
        assert SU.rustc_version() == "1.95.0", SU._RUSTC
        assert SU.native_report(max_age=0)["rustc"] == "1.95.0"
        fake("error: rustup could not choose a version of rustc to run", 1)
        SU._RUSTC.clear()
        assert SU.rustc_version() is None
        os.environ["PATH"] = "/nonexistent"
        SU._RUSTC.clear()
        assert not os.path.exists(os.path.expanduser("~/.cargo/bin/rustc"))
        assert SU.rustc_version() is None
    finally:
        os.environ["PATH"] = saved
        SU._RUSTC.clear()
        SU._NATIVE_REPORT[:] = [0, None]


def t_status_publishes_it():
    src = open(os.path.join(ROOT, "nado.py")).read()
    assert '"native": self_update.native_report(),' in src


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("t_"):
            check(name[2:].replace("_", " "), fn)
    print("ALL PASS" if not _report.fails else f"{_report.fails} FAILURES")
    sys.exit(1 if _report.fails else 0)
