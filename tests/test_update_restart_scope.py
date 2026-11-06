"""A documentation-only (or Land-game-only, or tests-only) fast-forward must NOT restart the node; anything else must.

Ten doc commits pushed one at a time on 2026-09-10 restarted nado and nado-exec ten times, and wallet users saw
"the exec node returned no data (HTTP 502)" on every one. The updater now skips the restart when every changed
path is documentation.

THE DANGEROUS DIRECTION IS THE OTHER ONE. A path wrongly treated as inert leaves the fleet running old code —
including old CONSENSUS code — so every case below that is not purely documentation must still restart, and so
must every ambiguous one (no paths, an unreadable diff). These pin both halves; a future addition to
_INERT_PREFIXES that swallows something executable fails here.
"""
import os as _os, tempfile as _tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): never the live node's HOME or exec files
_os.environ["HOME"] = _tempfile.mkdtemp(prefix="nado-test-")
_os.environ["NADO_EXEC_STATE"] = _os.path.join(_os.environ["HOME"], "exec_state.json")
_os.environ["NADO_EXEC_DA"] = _os.path.join(_os.environ["HOME"], "exec_da")
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops.self_update import _only_inert


def test_documentation_only_does_not_restart():
    assert _only_inert(["doc/nado-key.md"])
    assert _only_inert(["doc/README.md", "doc/nado-hardware-wallet.md", "README.md"])
    assert _only_inert(["LICENSE"])
    assert _only_inert(["doc/deep/nested/note.md"])


def test_anything_executable_restarts():
    # the whole point: one code path among many doc paths still restarts
    assert not _only_inert(["doc/nado-key.md", "protocol.py"])
    assert not _only_inert(["ops/self_update.py"])
    assert not _only_inert(["nado.py"])
    assert not _only_inert(["loops/core_loop.py"])
    assert not _only_inert(["native/attest/src/lib.rs"])


def test_served_assets_restart():
    # the wallet and the games are stamped and served by the node; website/ may be served from this tree. Not inert,
    # and a stale wallet bundle is exactly the class of bug that wasted a session before (?v= stamping).
    assert not _only_inert(["static/interface.js"])
    assert not _only_inert(["static/nadodapp.js"])
    assert not _only_inert(["static/mines.html"])
    assert not _only_inert(["website/index.html"])


def test_a_land_game_update_does_not_restart():
    # "do not restart nado nodes for this!!! make an exception as there is for docs" (operator, 2026-11-06): the Land
    # page, its modules, rules, vendored three.js and textures, its translations (and the i18n.js they regenerate), its
    # world server (run as nado-land, never by this updater) and the tests are read fresh or never by the node
    assert _only_inert(["static/land.js", "static/land.html", "static/land-mesher.js", "static/land-recipes.json"])
    assert _only_inert(["static/vendor/three/three.webgpu.js", "static/vendor/textures/grass_col.jpg"])
    assert _only_inert(["static/i18n_games/land.json", "static/i18n.js"])
    assert _only_inert(["scripts/land_server.py", "scripts/land_terrain.mjs"])
    assert _only_inert(["tests/test_a_walker_crosses_slopes_and_steps_without_jitter.mjs", "doc/land.md"])
    # ...but a Land commit that also touches anything the node runs still restarts
    assert not _only_inert(["static/land.js", "execnode/games/land.py"])
    assert not _only_inert(["static/land.js", "nado.py"])
    assert not _only_inert(["static/i18n_games/land.json", "static/i18n/wallet.json"])
    assert not _only_inert(["scripts/land_server.py", "scripts/other_tool.py"])
    # look-alikes of the Land prefixes are not Land
    assert not _only_inert(["static/landing.html"])
    assert not _only_inert(["static/vendor/nado-crypto.js"])


def test_ambiguity_restarts():
    # no information must never be read as "nothing changed"
    assert not _only_inert([])
    assert not _only_inert([""])
    assert not _only_inert(None or [])


def test_lookalike_paths_are_not_inert():
    # a top-level file whose name merely starts with a doc prefix, or a doc-named file inside code
    assert not _only_inert(["docs_build.py"])
    assert not _only_inert(["ops/README.md"])
    assert not _only_inert(["doctor.py"])


def test_an_inert_update_is_adopted_not_restarted():
    # The inert exception never held before: check_and_update skipped the restart, but running_head stayed on the old
    # commit and apply_stale_checkout restarted the node 90 s later anyway (2026-11-06: "do not restart nado nodes for
    # this!!!"). Now the process adopts an inert commit — and a commit range with anything else in it still restarts.
    import ops.self_update as su
    calls = []
    saved = (su._RUNNING_HEAD, su.repo_head, su._git, su.working_tree_dirty, su._schedule_restart, su._stale_since[0], su._stale_acted[0],
             su._rebuild_optional_crates, su._missing_required_libs)
    try:
        su._rebuild_optional_crates = lambda *a, **k: {}                       # never a real cargo build from a test
        su._missing_required_libs = lambda: []
        su.working_tree_dirty = lambda: False
        su._schedule_restart = lambda: calls.append("restart") or ["nado"]
        su._stale_acted[0] = None
        for diff, inert in (("static/land.js\ntests/test_x.mjs\ndoc/land.md", True), ("static/land.js\nnado.py", False)):
            su._RUNNING_HEAD, su._stale_since[0] = "aaaaaaaaaaaa", None
            su.repo_head = lambda: "bbbbbbbbbbbb"
            su._git = lambda *a, **k: diff if a[0] == "diff" else ""
            out = su.apply_stale_checkout(now=0.0)
            if inert:
                assert out["status"] == "adopted" and su.running_head() == "bbbbbbbbbbbb" and not calls, out
                assert su.apply_stale_checkout(now=1000.0)["status"] == "current"     # and stays put
            else:
                assert out["status"] == "observing" and su.running_head() == "aaaaaaaaaaaa", out
                out = su.apply_stale_checkout(now=1000.0)
                assert out["status"] == "restarting" and calls == ["restart"], out
    finally:
        (su._RUNNING_HEAD, su.repo_head, su._git, su.working_tree_dirty, su._schedule_restart, su._stale_since[0], su._stale_acted[0],
         su._rebuild_optional_crates, su._missing_required_libs) = saved


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all passed")
