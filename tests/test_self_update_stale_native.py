"""The self-updater must repair a STALE native library, not just a missing one.

WHY IT EXISTS. A node fast-forwarded across a commit touching native/*.rs, kept the .so it had already
built, and native_guard refused it — correctly, because a stale .so does not announce itself, it loads
happily and answers with an older kernel. The node then could not produce blocks at all:

    ERROR Failed to validate transaction during block preparation: native crate 'alghash2' library at
    …/libnado_alghash2.so is STALE — its Rust sources are newer than the built library … Rebuild it.
    WARNING Block production skipped due to: …

Observed on a peer 2026-08-08, after 6af13f71 and 5f372758 (both 2026-08-04) changed native/alghash2. The
updater reported "up_to_date" the entire time, because in GIT it was: `_missing_required_libs` only ever
noticed an ABSENT library. Present is not the same as usable.

The four behaviours pinned here are the ones that make this safe to run unattended on somebody else's box:
a stale library is DETECTED, a rebuild is VERIFIED rather than assumed, a build failure does NOT restart
into a node that will fail-stop again, and a dirty working tree is REFUSED (a rebuild compiles whatever is
in the tree, so on a box mid-edit it would restart into unfinished work).

Run: python3 tests/test_self_update_stale_native.py
"""
import os
import shutil
import sys
import tempfile
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ops import self_update as SU                                      # noqa: E402
from execnode.stark import native_guard as NG                          # noqa: E402

fails = 0


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


def _crate(tmp, name, so_older_than_src):
    """Build a fake crate tree: src/lib.rs + Cargo.toml + target/release/libnado_<name>.so."""
    d = os.path.join(tmp, "native", name)
    os.makedirs(os.path.join(d, "src"), exist_ok=True)
    os.makedirs(os.path.join(d, "target", "release"), exist_ok=True)
    src = os.path.join(d, "src", "lib.rs")
    so = os.path.join(d, "target", "release", f"libnado_{name}.so")
    open(src, "w").write("// rust\n")
    open(os.path.join(d, "Cargo.toml"), "w").write("[package]\n")
    open(so, "wb").write(b"\x7fELF-old")
    now = time.time()
    if so_older_than_src:
        os.utime(so, (now - 100, now - 100))                            # built BEFORE the sources
        os.utime(src, (now, now))
    else:
        os.utime(src, (now - 100, now - 100))
        os.utime(so, (now, now))                                        # built AFTER the sources
    return d, src, so


class _Sandbox:
    """Point self_update at a throwaway repo and stub out git/cargo/restart."""

    def __init__(self, crates, dirty=False, build=lambda c: {x: "built" for x in c}):
        self.tmp = tempfile.mkdtemp(prefix="nado-stale-")
        self.crates = crates
        self.dirty = dirty
        self.build = build
        self.restarted = False

    def __enter__(self):
        self._saved = (SU._REPO_DIR, SU._CRATES, SU._build_crates, SU._schedule_restart, SU._git)
        SU._REPO_DIR = self.tmp
        SU._CRATES = tuple(f"native/{c}" for c in self.crates)
        SU._build_crates = self._build_crates
        SU._schedule_restart = self._restart
        SU._git = self._git
        return self

    def __exit__(self, *a):
        (SU._REPO_DIR, SU._CRATES, SU._build_crates, SU._schedule_restart, SU._git) = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _build_crates(self, crates):
        return self.build(list(crates))

    def _restart(self):
        self.restarted = True
        return True

    def _git(self, *args, **kw):
        # The real check_and_update asks several distinct questions; answering them all with one sha sends
        # it down "not on main" and "remote is ahead" paths that have nothing to do with staleness.
        if args[:1] == ("diff",):
            if self.dirty:
                raise RuntimeError("dirty tree")
            return ""
        if args[:3] == ("rev-parse", "--abbrev-ref", "HEAD"):
            return SU._BRANCH                       # on the expected branch
        if args[:1] == ("rev-parse",):
            return "deadbeefcafe"                   # HEAD == origin/BRANCH  -> the "up_to_date" branch
        if args[:2] == ("remote", "get-url"):
            return "https://github.com/hclivess/nado"   # must satisfy _OFFICIAL_REPO_RE
        return ""


# ---- detection ------------------------------------------------------------------------------------------

def t_a_present_but_stale_library_is_detected():
    """THE gap that stopped a node: the .so is right there, and unusable."""
    with _Sandbox(["alghash2"]) as sb:
        _crate(sb.tmp, "alghash2", so_older_than_src=True)
        assert SU._stale_required_libs() == ["native/alghash2"], "a stale .so must be reported"
        assert SU._missing_required_libs() == [], "it is present — this is not a MISSING library"


def t_a_current_library_is_left_alone():
    with _Sandbox(["alghash2"]) as sb:
        _crate(sb.tmp, "alghash2", so_older_than_src=False)
        assert SU._stale_required_libs() == [], "a library newer than its sources must not be touched"


def t_only_the_loader_resolved_artifact_counts():
    """A stray build artifact must never trigger a rebuild and a RESTART of a healthy node. This box had a
    `_thin_test.so` and an old crate-root copy under native/mldsa44; an earlier version of the detector
    walked every .so and flagged the crate on their account alone."""
    with _Sandbox(["mldsa44"]) as sb:
        d, _src, _so = _crate(sb.tmp, "mldsa44", so_older_than_src=False)
        stray = os.path.join(d, "_thin_test.so")
        open(stray, "wb").write(b"\x7fELF-stray")
        os.utime(stray, (time.time() - 10_000, time.time() - 10_000))   # ancient, i.e. "stale"
        assert SU._stale_required_libs() == [], "a stray .so must not make the crate look stale"


def t_the_definition_comes_from_native_guard():
    """The updater and the loader must agree by construction; a second mtime comparison would drift."""
    src = open(os.path.join(ROOT, "ops", "self_update.py")).read()
    seg = src[src.index("def _stale_required_libs"):src.index("def _lib_digests")]
    assert "native_guard" in seg and "is_stale" in seg, "staleness must be decided by native_guard.is_stale"


# ---- repair ---------------------------------------------------------------------------------------------

def _run(sb):
    # check_and_update self-rate-limits (_MIN_INTERVAL); these tests call it back to back on purpose.
    SU._last_check[0] = 0.0
    return SU.check_and_update("test")


def t_a_stale_library_is_rebuilt_and_the_node_restarts():
    """The whole point: unattended recovery. The rebuild must change the bytes for a restart to be
    justified — see t_an_unchanged_rebuild_does_not_restart."""
    def build(crates):
        for c in crates:
            so = os.path.join(SU._REPO_DIR, c, "target", "release",
                              f"libnado_{os.path.basename(c)}.so")
            open(so, "wb").write(b"\x7fELF-NEW")                        # different bytes
            os.utime(so, None)                                          # and now newer than the sources
        return {c: "built" for c in crates}

    with _Sandbox(["alghash2"], build=build) as sb:
        _crate(sb.tmp, "alghash2", so_older_than_src=True)
        out = _run(sb)
        assert out.get("native_rebuilt") == ["native/alghash2"], f"expected a rebuild, got {out}"
        assert sb.restarted is True, "a node running a stale library must be restarted once it is fixed"
        assert SU._stale_required_libs() == [], "the staleness must actually be gone"


def t_an_unchanged_rebuild_does_not_restart():
    """Staleness is an MTIME question, so a crate goes stale when a manifest is merely TOUCHED. Bouncing a
    healthy validator to install a byte-identical .so is a self-inflicted outage."""
    def build(crates):
        for c in crates:
            so = os.path.join(SU._REPO_DIR, c, "target", "release",
                              f"libnado_{os.path.basename(c)}.so")
            open(so, "wb").write(b"\x7fELF-old")                        # IDENTICAL bytes to before
            later = time.time() + 10                                    # explicitly newer than the sources
            os.utime(so, (later, later))
        return {c: "built" for c in crates}

    with _Sandbox(["alghash2"], build=build) as sb:
        _crate(sb.tmp, "alghash2", so_older_than_src=True)
        out = _run(sb)
        assert sb.restarted is False, "an identical library must not cost a restart"
        assert out.get("restarting") is False, f"expected restarting=False, got {out}"


def t_a_failed_build_does_not_restart():
    """Restarting while still stale would only fail-stop again, and would turn one broken node into a
    restart loop."""
    with _Sandbox(["alghash2"], build=lambda c: {x: "build-failed" for x in c}) as sb:
        _crate(sb.tmp, "alghash2", so_older_than_src=True)
        out = _run(sb)
        assert sb.restarted is False, "a failed rebuild must NOT restart the node"
        assert out.get("native_stale") == ["native/alghash2"], f"the unresolved staleness must be reported: {out}"
        assert "manual" in (out.get("note") or ""), "the operator must be told what to do by hand"


def t_a_dirty_tree_refuses_the_rebuild():
    """A rebuild compiles whatever is in the working tree, so on a box mid-edit it would build and then
    RESTART INTO unfinished work. The update path already refuses a dirty tree; this branch never reaches
    that check, so it needs its own."""
    with _Sandbox(["alghash2"], dirty=True) as sb:
        _crate(sb.tmp, "alghash2", so_older_than_src=True)
        out = _run(sb)
        assert sb.restarted is False, "a dirty tree must not be restarted into"
        assert out.get("native_stale") == ["native/alghash2"], f"it must still REPORT the staleness: {out}"
        assert "uncommitted" in (out.get("note") or ""), "the refusal must say why"


for nm, fn in [("a present-but-stale library is detected", t_a_present_but_stale_library_is_detected),
               ("a current library is left alone", t_a_current_library_is_left_alone),
               ("only the loader-resolved artifact counts", t_only_the_loader_resolved_artifact_counts),
               ("the definition comes from native_guard", t_the_definition_comes_from_native_guard),
               ("stale library rebuilt and node restarted", t_a_stale_library_is_rebuilt_and_the_node_restarts),
               ("an unchanged rebuild does not restart", t_an_unchanged_rebuild_does_not_restart),
               ("a failed build does not restart", t_a_failed_build_does_not_restart),
               ("a dirty tree refuses the rebuild", t_a_dirty_tree_refuses_the_rebuild)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
