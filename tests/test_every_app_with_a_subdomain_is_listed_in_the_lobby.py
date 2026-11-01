"""Every app served on its own subdomain is listed in the lobby (nadochain.com/apps).

nft.nadochain.com shipped with its page, its vhost and its upload service live, and no lobby entry: the operator
asked three times for it to be on /apps (2026-11-01). An app that is reachable only by someone who knows the URL
does not exist (CLAUDE.md rule 9), so a checked-in vhost with no lobby entry fails here.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "website")

lobby = open(os.path.join(WEB, "apps.html"), encoding="utf8").read()
listed = set(re.findall(r'url:"https://([a-z0-9-]+)\.nadochain\.com"', lobby))
hosted = {m.group(1) for f in os.listdir(WEB)
          for m in [re.fullmatch(r"nginx-([a-z0-9-]+)\.nadochain\.com\.conf", f)] if m}
fails = 0
for host in sorted(hosted):
    ok = host in listed
    print(("  PASS  " if ok else "  FAIL  ") + f"{host}.nadochain.com is listed in website/apps.html")
    fails += not ok
ok = "nft" in hosted and "nft" in listed
print(("  PASS  " if ok else "  FAIL  ") + "the NFT marketplace is both hosted and listed")
fails += not ok
print("ALL PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
