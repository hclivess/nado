#!/usr/bin/env python3
"""
The OLD entry point, kept so redeploy.py, docs and muscle memory keep working: it now runs tools/build_i18n.py, which
generates the WHOLE static/i18n.js from static/i18n/*.json + static/i18n_games/*.json + static/i18n/runtime.js.tmpl.

Before 2026-10-10 this script only spliced a T_GAMES block into a hand-layered i18n.js; the rest of the file was
edited by hand and 129 keys ended up defined more than once. After editing any <game>.json (or a namespace file),
run this — or tools/build_i18n.py directly — and commit the regenerated i18n.js with the JSON.

Run: python3 static/i18n_games/merge_games.py
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
import build_i18n  # noqa: E402


def main():
    rc = build_i18n.main([])
    if rc:
        sys.exit(rc)


# bust_pages() and bust_module_imports() — which wrote md5 ?v= literals into every page and 148 module imports — are
# gone (2026-10-10): the server versions every reference by content when it serves it (ops/static_versions.py), and a
# literal ?v= in a static source is refused by tests/test_static_versions.py.

if __name__ == "__main__":
    main()
