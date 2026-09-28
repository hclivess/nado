"""A wallet restored in-page is live: its dashboard keeps refreshing and the person lands on it (static/interface.js
walletAdopted).

WHY (measured 2026-09-28, the gen-28 legacy-claim walk in headless chromium). Restoring a wallet means Settings ->
Forget -> Import. Forget stops mining and with it the poll loop, and nothing restarted it: the restored wallet's claim
landed, and the balance card read "0 NADO" for five minutes — until a page reload — while the log told the person their
coins were on the way. They were also left on the Settings tab, under a "created for you on this device" backup hint
that is false for an imported wallet.

Pins (source, as the wallet ships): both in-page adoption paths (Import, the save screen's Continue) call walletAdopted,
which starts the poll loop when it is stopped and shows the wallet tab; an import clears the auto-created flag.

Run: python3 tests/test_wallet_restore_stays_live.py
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
js = open(os.path.join(ROOT, "static", "interface.js")).read()
fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    fails += 0 if ok else 1


fn = re.search(r"\nfunction walletAdopted\(\) \{(.*?)\n\}", js, re.S)
check("walletAdopted exists", bool(fn))
body = fn.group(1) if fn else ""
check("...and restarts the poll loop when it is stopped", "if (!state.pollTimer) startPollLoop();" in body)
check("...and shows the wallet tab", 'showTab("wallet")' in body)
adopt = js[js.index("function adoptWallet(w, { needsSavePrompt })"):js.index("function walletAdopted()")]
imp = adopt[adopt.index("} else {"):]
check("an Import adopts through walletAdopted", "walletAdopted();" in imp)
check("...and clears the auto-created flag (no false 'created for you' backup hint)", "localStorage.removeItem(LS_AUTO_WALLET)" in imp)
cont = js[js.index('$("btnConfirmSave").onclick'):]
cont = cont[:cont.index("};")]
check("the save screen's Continue adopts through walletAdopted", "walletAdopted();" in cont)
forget = js[js.index('$("btnForget").onclick'):]
forget = forget[:forget.index("};")]
check("(Forget still stops mining — which is why adoption must restart the loop)", "stopMining();" in forget)

print("ALL PASS — a restored wallet is live" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
