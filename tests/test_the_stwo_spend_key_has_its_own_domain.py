"""THE WALLET'S STWO SPEND KEY IS DERIVED UNDER ITS OWN DOMAIN, never from another pool's (static/interface.js).

Review 2026-10-11: shieldNskStwo() was blake2bHash([DOMAIN_SHIELD_NSK_WIDE, privateKey]) taken whole — the very digest the
wide key's four lanes are cut from. A leak of a wide witness (the 2026-09-24 precedent: every legacy proof published the
v1 key, which is why the wide key got shield-nsk-v2) would then have opened every Stwo note of the same wallet. Pins:
  1. DOMAIN_SHIELD_NSK_STWO exists and differs from every other key-derived tag in the wallet;
  2. shieldNskStwo derives from it, and from nothing else;
  3. no other wallet line derives a key with the Stwo tag, and the wide/legacy derivations are unchanged (frozen tags:
     a rename orphans existing notes).
A static check of the source, like tests/test_zk_review_2026_09_24.py's for the wide key: the derivation is one line
of a browser module that a test cannot import.

Run: python3 tests/test_the_stwo_spend_key_has_its_own_domain.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-stwo-nsk-domain-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "static", "interface.js"), encoding="utf-8").read()
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


tags = dict(re.findall(r'^const (DOMAIN_[A-Z0-9_]+) = "([^"]+)";', src, re.M))
check("1. DOMAIN_SHIELD_NSK_STWO is declared", "DOMAIN_SHIELD_NSK_STWO" in tags, sorted(tags))
check("...and its value is unique among the wallet's domain tags",
      list(tags.values()).count(tags.get("DOMAIN_SHIELD_NSK_STWO")) == 1, tags)
check("...in particular it is neither the wide (v2) nor the legacy (v1) shield tag",
      tags.get("DOMAIN_SHIELD_NSK_STWO") not in (tags.get("DOMAIN_SHIELD_NSK_WIDE"), tags.get("DOMAIN_SHIELD_NSK")), tags)

m = re.search(r"function shieldNskStwo\(\) \{([^\n]*)\}", src)
body = m.group(1) if m else ""
check("2. shieldNskStwo derives from DOMAIN_SHIELD_NSK_STWO",
      "blake2bHash([DOMAIN_SHIELD_NSK_STWO, state.wallet.privateKey])" in body, body)
check("...and names no other pool's domain", "DOMAIN_SHIELD_NSK_WIDE" not in body and
      not re.search(r"DOMAIN_SHIELD_NSK\b(?!_)", body), body)

uses = [l for l in src.splitlines() if "DOMAIN_SHIELD_NSK_STWO" in l and not l.lstrip().startswith("//")]
check("3. the Stwo tag is used by its declaration and shieldNskStwo only", len(uses) == 2, uses)
check("...the frozen wide and legacy tags are unchanged",
      tags.get("DOMAIN_SHIELD_NSK_WIDE") == "shield-nsk-v2" and tags.get("DOMAIN_SHIELD_NSK") == "shield-nsk-v1", tags)

print("ALL PASS — the Stwo spend key has its own domain" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
