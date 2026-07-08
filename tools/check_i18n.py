#!/usr/bin/env python3
"""
i18n completeness validator for the NADO wallet.

Extracts every key REFERENCED by the UI (data-i18n* attrs in interface.html + i18("key",…) calls in
interface.js) and every key DEFINED per language in i18n.js, then reports:
  1. referenced keys MISSING from the English base   (render the raw fallback -> effectively untranslated)
  2. per-language keys missing vs. English            (fall back to English)

Run: python3 tools/check_i18n.py
Exit non-zero if the English base is missing any referenced key (the launch-blocking case).
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "static")


def referenced_keys():
    """Keys the UI actually asks for."""
    keys = set()
    html = open(os.path.join(STATIC, "interface.html"), encoding="utf-8").read()
    for attr in ("data-i18n", "data-i18n-ph", "data-i18n-title", "data-i18n-html"):
        keys |= set(re.findall(attr + r'="([^"]+)"', html))
    js = open(os.path.join(STATIC, "interface.js"), encoding="utf-8").read()
    keys |= set(re.findall(r'\bi18\(\s*"([^"]+)"', js))
    return keys


def lang_keysets():
    """{lang: set(keys)} — UNION of each language's block across BOTH tables (T + T2). A block is
    `\\n    <lang>: {` up to the next 4-space-indented close brace."""
    src = open(os.path.join(STATIC, "i18n.js"), encoding="utf-8").read()
    out = {}
    for m in re.finditer(r'\n {4}([a-z]{2}): \{', src):
        lang = m.group(1)
        rest = src[m.end():]
        close = re.search(r'\n {4}\}', rest)          # end of this language's object
        block = rest[:close.start()] if close else rest
        out.setdefault(lang, set()).update(re.findall(r'"([^"]+)"\s*:', block))
    return out


def main():
    ref = referenced_keys()
    langs = lang_keysets()
    if "en" not in langs:
        print("FATAL: no `en` table found"); return 2
    en = langs["en"]

    missing_en = sorted(ref - en)
    print(f"referenced keys: {len(ref)} | en defines: {len(en)} | languages: {len(langs)}\n")
    if missing_en:
        print(f"[FAIL] {len(missing_en)} referenced key(s) MISSING from the English base (render raw fallback):")
        for k in missing_en:
            print(f"    {k}")
    else:
        print("[ok] every referenced key exists in the English base")

    print("\nper-language completeness (missing vs. English base):")
    for lang in sorted(langs):
        if lang == "en":
            continue
        miss = en - langs[lang]
        flag = "ok " if not miss else "GAP"
        print(f"  [{flag}] {lang}: {len(langs[lang])}/{len(en)}   missing {len(miss)}")

    return 1 if missing_en else 0


if __name__ == "__main__":
    sys.exit(main())
