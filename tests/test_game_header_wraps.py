"""A game page fits a phone: the shared header wraps instead of running off the screen (static/nadodapp.js _pickCss).

WHY (measured 2026-09-29, the post-reroll page walk at 412 px): every game docks the language picker (the SDK's
enhanced select, .pick/.pickbtn) and the header wallet button (#hdrWallet) into one non-wrapping flex <header> beside
the logo, title and "All apps"; eight pages were 7-66 px wider than the screen (autogame 478 px at 412) and scrolled
sideways, worse at 360. With the rules below every game page measured exactly 412 / 360 wide.

Pins (the SDK source every game loads): a header holding the picker or the wallet button wraps; the picker never
exceeds its row and its label may shrink (a flex child ellipsizes only with min-width:0).

Run: python3 tests/test_game_header_wraps.py
"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "static", "nadodapp.js")).read()
fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    fails += 0 if ok else 1


check("a header holding the picker or the wallet button wraps", "header:has(.pick),header:has(#hdrWallet){flex-wrap:wrap" in src)
check("the picker never exceeds its row", ".pick{position:relative;display:inline-block;min-width:0;max-width:100%}" in src)
check("the picker's label may shrink and ellipsize", "text-overflow:ellipsis;white-space:nowrap;min-width:0}" in src)
print("ALL PASS — a game header fits a phone" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
