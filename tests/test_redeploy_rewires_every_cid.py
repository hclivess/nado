"""The redeploy rewires AND verifies every contract id a page carries (execnode/games/redeploy.py wire / verify).

A reroll wipes every contract; the redeploy repoints each page's constants. It rewired `const CID` and dex.js's
`const OTC_CID`, and its verify checked exactly those two names — so the wallet's `const RESERVE_CID` stayed on the
betanet-7 contract while the redeploy reported "every CID resolves" (2026-09-25). Pins: every `const <NAME>_CID` in
static/*.js is in wire()'s named list (so it is rewired), and verify() checks every `const CID` / `const <NAME>_CID`
by pattern, not by a list of names. Also pins that the faucet prize table it rewires is at a path that exists.

Run: python3 tests/test_redeploy_rewires_every_cid.py
"""
import os, re, sys, glob
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "execnode", "games", "redeploy.py")).read()
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


wired = set(re.findall(r'\(os\.path\.join\(STATIC, "([a-z_]+\.js)"\), "([A-Z_]+_CID)", "[a-z_]+"\)', src))
named = set()
for f in glob.glob(os.path.join(ROOT, "static", "*.js")):
    for var in re.findall(r"^const ([A-Z]+_CID) = \"[0-9a-z]+\";", open(f, encoding="utf-8").read(), re.M):
        named.add((os.path.basename(f), var))
check("every named contract-id constant in static/ is rewired by the redeploy", named <= wired, sorted(named - wired))
check("the wallet's RESERVE_CID and the DEX's OTC_CID are among them",
      {("interface.js", "RESERVE_CID"), ("dex.js", "OTC_CID")} <= wired, sorted(wired))
check("verify() checks every CID constant by pattern, not a list of names",
      "for var, cid in re.findall(r'^const ((?:[A-Z]+_)?CID) = " in src)
# The faucet prize table is rewired only if redeploy finds it: wire()/verify() skip a missing file silently, so a
# move of _faucet_rewards.py that leaves redeploy's path behind would strand every prize row at the next reroll.
m = re.search(r'^FAUCET_REWARDS = os\.path\.join\(ROOT, ((?:"[^"]+",\s*)*"[^"]+")\)', src, re.M)
fr_path = os.path.join(ROOT, *re.findall(r'"([^"]+)"', m.group(1))) if m else None
check("the redeploy rewires the faucet distributor at a path that exists", bool(fr_path) and os.path.isfile(fr_path),
      fr_path)
check("both the rewire and the verify read that path", src.count("fr = FAUCET_REWARDS") == 2)
print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
