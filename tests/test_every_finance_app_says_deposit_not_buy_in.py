"""Every app the lobby lists as NOT a game words its wallet row as Deposit / Withdraw / usable, in every language.

The SDK's wallet row says "Buy in", "Cash out" and "playable" (game words). The NFT marketplace and Lend shipped with
them, and the DEX overrode them with English-only literals (found 2026-11-02 on the live NFT walk). An app whose lobby
entry carries kind:"finance" must set dapp.walletLabels = financeLabels() (static/nadodapp.js), whose three strings are
defined in all 16 languages.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = 0
def check(name, cond):
    global fails
    print(("  PASS  " if cond else "  FAIL  ") + name)
    fails += not cond

lobby = open(os.path.join(ROOT, "website", "apps.html"), encoding="utf8").read()
finance = []
for m in re.finditer(r"\{\s*svg:SVG\.\w+,(.*?)\] \}", lobby, re.S):
    body = m.group(1)
    if 'kind:"finance"' in body:
        finance.append(re.search(r'url:"https://([a-z0-9-]+)\.nadochain\.com"', body).group(1))
check(f"the lobby marks DEX, Lend and NFT as finance apps ({', '.join(finance)})", {"dex", "lend", "nft"} <= set(finance))
for host in finance:
    js = open(os.path.join(ROOT, "static", f"{host}.js"), encoding="utf8").read()
    m = re.search(r"^\s*dapp\.walletLabels = financeLabels\(\);", js, re.M)   # a statement, not a comment
    w = re.search(r"^\s*wireWallet\(dapp", js, re.M)
    check(f"static/{host}.js sets the finance labels before wiring the wallet", bool(m and w and m.start() < w.start()))
sdk = open(os.path.join(ROOT, "static", "nadodapp.js"), encoding="utf8").read()
check("the SDK's financeLabels uses translated keys", all(f'_t("{k}"' in sdk for k in ("depositBtn", "withdrawBtn", "ofUsable")))
tables = json.load(open(os.path.join(ROOT, "static", "i18n_games", "sdk.json"), encoding="utf8"))
check("the three labels exist in all 16 languages, with {n} kept",
      len(tables) == 16 and all(all(f"sdk.{k}" in t for k in ("depositBtn", "withdrawBtn", "ofUsable"))
                                and "{n}" in t["sdk.ofUsable"] for t in tables.values()))
print("ALL PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
