"""A documentation-only fast-forward must NOT restart the node; anything else must.

Ten doc commits pushed one at a time on 2026-09-10 restarted nado and nado-exec ten times, and wallet users saw
"the exec node returned no data (HTTP 502)" on every one. The updater now skips the restart when every changed
path is documentation.

THE DANGEROUS DIRECTION IS THE OTHER ONE. A path wrongly treated as inert leaves the fleet running old code —
including old CONSENSUS code — so every case below that is not purely documentation must still restart, and so
must every ambiguous one (no paths, an unreadable diff). These pin both halves; a future addition to
_INERT_PREFIXES that swallows something executable fails here.
"""
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
    # static/ is stamped and served by the node; website/ may be served from this tree. Neither is inert,
    # and a stale wallet bundle is exactly the class of bug that wasted a session before (?v= stamping).
    assert not _only_inert(["static/interface.js"])
    assert not _only_inert(["static/i18n.js"])
    assert not _only_inert(["website/index.html"])


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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all passed")
