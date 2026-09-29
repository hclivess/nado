"""Switching accounts keeps collecting where it belongs (static/interface.js switchAccount), and the account selector
does not flicker (renderAccountBar, nadodapp.autoEnhanceSelects).

WHY (operator 2026-09-29): "when i switch to Account 2 and back to Main, it wrongly shows 'start collecting'" — the
collecting loop runs for one address, halts for registration on an unregistered account, and a switch never restarted
it, so a registered Main sat on the idle button. And "account selector ... switching basic to advanced style, very
distracting": the bar rebuilt a native <select> on every refresh and the styled picker replaced it up to 1.2 s later.

Pins (source, as the wallet ships):
  1. switchAccount pauses the loop for the old account without dropping the persisted intent, and resumes it for the
     new one exactly like unlock does (startMining when the intent is set, else keep the dashboard polling);
  2. renderAccountBar rebuilds only when count, active account or labels change;
  3. the SDK enhances a select before paint (a MutationObserver), keeping the sweep as the fallback.

Run: python3 tests/test_account_switch_keeps_collecting.py
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
js = open(os.path.join(ROOT, "static", "interface.js")).read()
sdk = open(os.path.join(ROOT, "static", "nadodapp.js")).read()
fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    fails += 0 if ok else 1


sw = js[js.index("function switchAccount(i) {"):js.index("function addAccount() {")]
check("a switch reads the persisted collecting intent", 'const resume = localStorage.getItem(LS_MINING) === "1";' in sw)
check("...pauses the loop for the old account (pauseMining keeps the intent; stopMining would drop it)",
      "pauseMining();" in sw and "stopMining" not in sw)
check("...and resumes it for the new account after the switch", sw.index("if (resume) startMining();") > sw.index("showWalletUI();"))
check("...or at least keeps the dashboard polling", "else if (!state.pollTimer) startPollLoop();" in sw)
pm = js[js.index("function pauseMining() {"):js.index("async function unlockWallet(")]
check("pauseMining leaves the intent flag alone", "LS_MINING" not in pm)
bar = js[js.index("function renderAccountBar() {"):js.index("// Validate a recipient address")]
check("the account bar rebuilds only on a change", "if (bar.dataset.sig === sig && bar.childElementCount) return;" in bar)
auto = sdk[sdk.index("export function autoEnhanceSelects() {"):sdk.index("// a two-choice dropdown reads better")]
check("the SDK enhances new selects before paint", "new MutationObserver(" in auto and "subtree: true" in auto)
check("...and keeps the sweep as a fallback", "setInterval(run, 1200)" in auto)
print("ALL PASS — the account switch keeps collecting and the selector does not flicker" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
