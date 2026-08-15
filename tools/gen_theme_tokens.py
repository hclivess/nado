#!/usr/bin/env python3
"""Generate static/theme.css — the ONE definition of every themeable colour — from interface.css.

The palette used to live in three places that disagreed: interface.css held the real values, the dapp SDK
(nadodapp.js) hardcoded its own hex copies, and where it did use variables it invented names nothing
defined (--accent2, --elev, --dim) so its fallbacks always won. The wallet themed; every game page stayed
brand teal. Deriving one file mechanically is what stops that recurring — a new theme added to
interface.css reaches the games by regenerating, not by remembering to copy hexes into a second file.

    python3 tools/gen_theme_tokens.py           # rewrite static/theme.css
    python3 tools/gen_theme_tokens.py --check   # verify it is current (CI / pre-release)
"""
import hashlib
import re
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "static", "interface.css")
OUT = os.path.join(ROOT, "static", "theme.css")
VARS = ["bg", "bg-elev", "bg-elev2", "border", "txt", "txt-dim", "txt-faint",
        "accent", "accent-2", "accent-rgb"]

# The SAME palette is spelled two ways in this codebase. The wallet uses the descriptive names above; all
# 24 game pages were written earlier against --elev/--elev2/--dim/--faint/--accent2 and define those in
# their own inline <style> as brand-teal literals. Emitting both spellings from the one source is what
# makes a theme reach a game page: this file is injected AFTER the page's inline style, so these override
# the hardcoded copies, and no game page needs editing. They are var() references, not duplicated hexes,
# so there is still exactly one value per colour. Drop an alias only once no page uses that name.
ALIASES = ("  --elev: var(--bg-elev); --elev2: var(--bg-elev2); --dim: var(--txt-dim);\n"
           "  --faint: var(--txt-faint); --accent2: var(--accent-2);\n")

HEADER = '''/* NADO THEME TOKENS — the single source of truth for every themeable colour.
 *
 * WHY THIS FILE EXISTS. The palette used to live in three places that could not agree: interface.css had
 * the real values, nadodapp.js (the dapp SDK every game page loads) hardcoded its own copies as hex
 * literals, and where it did use variables it invented DIFFERENT names — --accent2, --elev, --dim —
 * that nothing anywhere defined, so its fallbacks were what actually rendered. The visible result: the
 * wallet themed, and every game page stayed brand teal no matter what you picked.
 *
 * Game pages carry inline <style> and load no shared stylesheet, so the tokens have to travel with the
 * SDK. nadodapp.js injects this file's contents on load; interface.html links it directly. One file, one
 * set of names, both surfaces.
 *
 * GENERATED — do not hand-edit. tools/gen_theme_tokens.py derives it from interface.css so the wallet and
 * the SDK cannot drift apart; tests/test_themes.mjs recomputes every contrast ratio from whatever ends up
 * here, so a palette that dips below the readability bar fails the build rather than shipping.
 */'''


def _grab(block, name):
    m = re.search(r"--%s:\s*([^;]+);" % re.escape(name), block)
    return m.group(1).strip() if m else None


def build():
    css = open(SRC, encoding="utf8").read()
    root = re.search(r":root \{(.*?)\n\}", css, re.S).group(1)
    # A selector may appear in SEVERAL blocks — the palette and the logo ramp are declared separately, and
    # CSS merges them. Concatenate every block for a selector before reading, or the first one wins and a
    # complete palette looks empty.
    def blocks_for(sel_regex):
        return "".join(m.group(2) for m in re.finditer(sel_regex, css))

    palettes = [(":root", {v: _grab(root + blocks_for(r"(:root)\s*\{([^}]*)\}"), v) for v in VARS})]
    for name in dict.fromkeys(re.findall(r'html\[data-theme="([a-z]+)"\]', css)):
        merged = blocks_for(r'(html\[data-theme="%s"\])\s*\{([^}]*)\}' % name)
        palettes.append((f'html[data-theme="{name}"]', {v: _grab(merged, v) for v in VARS}))
    missing = [(sel, v) for sel, d in palettes for v in VARS if not d[v]]
    if missing:
        sys.exit(f"incomplete palette(s) in interface.css: {missing}")
    # ---- the SHARED-COMPONENTS region -------------------------------------------------------------
    # Tokens alone were not enough: the game pages also need the COMPONENTS built from them, or a toggle
    # on a game page stays a native OS-green checkbox while the wallet themes correctly. The region is
    # copied verbatim rather than reimplemented, so there is exactly one definition of the switch.
    m = re.search(r"/\* >>> SHARED-COMPONENTS(.*?)/\* <<< SHARED-COMPONENTS \*/", css, re.S)
    if not m:
        sys.exit("interface.css has no >>> SHARED-COMPONENTS region — did the sentinels get edited out?")
    shared = m.group(0).strip()

    out = [HEADER]
    for sel, d in palettes:
        out.append(f"{sel} {{\n"
                   f"  --bg: {d['bg']}; --bg-elev: {d['bg-elev']}; --bg-elev2: {d['bg-elev2']}; --border: {d['border']};\n"
                   f"  --txt: {d['txt']}; --txt-dim: {d['txt-dim']}; --txt-faint: {d['txt-faint']};\n"
                   f"  --accent: {d['accent']}; --accent-2: {d['accent-2']}; --accent-rgb: {d['accent-rgb']};\n"
                   f"{ALIASES}"
                   f"}}")
    out.append(shared)
    return "\n\n".join(out) + "\n", len(palettes)


def stamp(text):
    """Content-stamp the SDK's link to this file. Cloudflare serves /static with a four-hour max-age, so an
    UNSTAMPED href means a palette change — or a fix to the shared toggle now living in here — reaches
    nobody for four hours, and reaches each visitor at a different moment in between. nadodapp.js is itself
    stamped by merge_games.bust_module_imports(), so bumping the href here propagates to all 24 pages."""
    h = hashlib.md5(text.encode()).hexdigest()[:8]
    sdk = os.path.join(ROOT, "static", "nadodapp.js")
    src = open(sdk, encoding="utf8").read()
    out = re.sub(r'"/static/theme\.css(?:\?v=[^"]*)?"', '"/static/theme.css?v=%s"' % h, src)
    if out != src:
        open(sdk, "w", encoding="utf8").write(out)
        return f"stamped theme.css?v={h} into nadodapp.js"
    return f"theme.css?v={h} already current in nadodapp.js"


def check_stamp(text):
    h = hashlib.md5(text.encode()).hexdigest()[:8]
    src = open(os.path.join(ROOT, "static", "nadodapp.js"), encoding="utf8").read()
    if f"/static/theme.css?v={h}" not in src:
        sys.exit(f"nadodapp.js links a STALE theme.css stamp (want ?v={h}) — run: python3 tools/gen_theme_tokens.py")


if __name__ == "__main__":
    text, n = build()
    if "--check" in sys.argv:
        cur = open(OUT, encoding="utf8").read() if os.path.exists(OUT) else ""
        if cur != text:
            sys.exit("static/theme.css is STALE — run: python3 tools/gen_theme_tokens.py")
        check_stamp(text)
        print(f"theme.css is current ({n} palettes + shared components), stamp matches")
    else:
        open(OUT, "w", encoding="utf8").write(text)
        print(f"wrote static/theme.css ({n} palettes + shared components)")
        print(stamp(text))
