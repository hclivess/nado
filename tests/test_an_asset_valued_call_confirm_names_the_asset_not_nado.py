"""The wallet's confirm for a contract call that escrows an ASSET says units of that asset, never NADO.

Found by the live NFT walk (2026-11-02, tests/test_nft_market_live_e2e.mjs): listing one edition of an NFT is a call
carrying {asset, value: 1}, and the confirm's sentence read "It ESCROWS 0.0000000001 NADO from your exec balance" — the
edition count printed as raw NADO, while the rows below it already said "1 units of asset …". Static/interface.js must
pick dapp.bodyAsset (rendered through _unit) whenever the call names an asset, and that sentence must exist in all 16
languages with its placeholders.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "static", "interface.js"), encoding="utf8").read()
fails = 0
def check(name, cond):
    global fails
    print(("  PASS  " if cond else "  FAIL  ") + name)
    fails += not cond

a = src.find("body: escrow > 0n && _assetId")
branch = src[a:src.find("      : escrow > 0n", a)] if a >= 0 else ""
check("an asset-valued escrow is worded by dapp.bodyAsset with the amount in the asset's units (_unit)",
      'i18("dapp.bodyAsset"' in branch and "v: _unit(escrow)" in branch and "rawToNado" not in branch)
i = src.find('body: escrow > 0n && _assetId')
j = src.find('i18("dapp.bodyValue"', i)
check("the NADO sentence (dapp.bodyValue) is only the fallback after the asset branch", i >= 0 and j > i)
check("_unit names the asset's units when the call carries one",
      '_unit = (v) => _assetId ? String(v) + " " + i18("dapp.assetUnits"' in src)
tables = json.load(open(os.path.join(ROOT, "static", "i18n", "dapp.json"), encoding="utf8"))
check("dapp.bodyAsset exists in all 16 languages with {app}, {a} and {v} kept, and none says NADO for the amount",
      len(tables) == 16 and all(all(p in t.get("dapp.bodyAsset", "") for p in ("{app}", "{a}", "{v}"))
                                and "{v} NADO" not in t["dapp.bodyAsset"] for t in tables.values()))
print("ALL PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
