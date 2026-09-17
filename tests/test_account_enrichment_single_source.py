"""THE BUNDLED READ CARRIES WHAT THE DIRECT READ CARRIES (nado._enrich_account).

2026-09-17, reported: "I dropped out of collecting for 2 days, when I returned, I click register and the
fucking Hello thing pops out although I have an exe registration... it worked only after the second try."
Cause: /get_account enriched the account with `devbind`; /wallet_view — the bundled read the wallet actually
polls — added only `reg_epoch`. interface.getAccount() prefers the bundle while it is fresh, so `acc.devbind`
was undefined on most reads, bindIsPermanent() answered FALSE for a permanently-bound identity, and the
register path fell past its statement-free branch into a Windows Hello prompt the enrolled chip cannot answer.
A stale bundle on the next click ran the direct endpoint, which is why the second try worked. The same gap made
leaseEpochsOf() fall back to the 36 h default for the 7-day classes.

nado.py cannot be imported (it starts a node), so the invariant is pinned at the source, as the other nado.py
wiring tests are: ONE enrichment function, called by both handlers, with no second devbind literal anywhere.
Also pins the two wallet-side halves of the same bug.
Run: python3 tests/test_account_enrichment_single_source.py
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
nado = open(os.path.join(ROOT, "nado.py")).read()
js = open(os.path.join(ROOT, "static", "interface.js")).read()

fails = []
def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond: fails.append(label)

def body(src, header, stop="\ndef "):
    i = src.index(header)
    j = src.find(stop, i + len(header))
    return src[i:j if j > 0 else len(src)]

check(nado.count("def _enrich_account(") == 1, "exactly one account-enrichment function exists")
enrich = body(nado, "def _enrich_account(")
for field in ("reg_epoch", "mode", "cls", "handle", "live", "epoch", "lease_epochs", "lease_epochs_next", "assert_ok"):
    check(f'"{field}"' in enrich, f"...and it is the one place '{field}' is derived")

# exactly two callers: the direct endpoint and the bundle the wallet polls
callers = [m.start() for m in re.finditer(r"_enrich_account\(", nado)]
check(len(callers) == 3, f"one definition + two call sites ({len(callers)} occurrences)")
acct = body(nado, "async def account(request):", "\nasync def ")
view = body(nado, "async def wallet_view(request):", "\nasync def ")
check("_enrich_account(" in acct, "/get_account enriches through it")
check("_enrich_account(" in view, "/wallet_view enriches through it — the bundle is what the wallet polls")
check('"devbind"' not in acct and '"devbind"' not in view,
      "neither handler builds its own devbind literal (a second site is how the two drifted)")
check('"reg_epoch"' not in acct and '"reg_epoch"' not in view,
      "...nor its own reg_epoch")

# --- the wallet halves
rds = body(js, "function readDeviceStatus() {", "\nfunction ")
check("readDeviceStatus()" not in rds.replace("function readDeviceStatus() {", "", 1),
      "readDeviceStatus does not call itself (it did from 2026-09-12: every read blew the stack)")
check("localStorage.getItem(deviceStatusKey())" in rds, "...it reads the store it is named for")
bip = body(js, "async function bindIsPermanent() {", "\nfunction ")
check('"devbind" in acc' in bip,
      "a read that OMITS devbind leaves the known binding alone (missing != unbound)")

print(("\nFAILED: " + "; ".join(fails)) if fails else "\nall checks passed")
sys.exit(1 if fails else 0)
