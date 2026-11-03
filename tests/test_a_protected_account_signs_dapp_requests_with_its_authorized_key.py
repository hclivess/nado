"""A protected account signs a dApp's request (an NFT mint, any game move) with the key its auth config names — never
the base key.

2026-11-03: a user with a protected account (account auth, sign = the HD signer child) could not mint on the NFT
marketplace: every relay refused the mint with "signature by a key that does not authorize this account". The wallet
picks the dApp request's signer in resumePendingExecSign, and showWalletUI starts that request right after it starts
authSync — the ASYNC step that swaps state.wallet to the signer child — so the signer was captured while state.wallet was
still the base key. The hidden background signer every game uses never ran authSync at all.

The end-to-end walk is scripts/testnet/test_auth_wallet.py (a real browser, a protected account on a loopback testnet,
a fresh ?exec_sign= load: ok=1 and the mint lands; without the fix it answers the user's exact error). This test pins
the ordering that walk depends on, and runs in the suite on every push.
"""
import os
import re
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-authsign-")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "static", "interface.js"), encoding="utf-8").read()
passed = failed = 0


def check(cond, label):
    global passed, failed
    if cond:
        passed += 1; print("PASS ", label)
    else:
        failed += 1; print("FAIL ", label)


def body(name):
    m = re.search(r"\n(?:async )?function " + re.escape(name) + r"\(.*?\n\}\n", SRC, re.S)
    return m.group(0) if m else ""


exec_sign = body("resumePendingExecSign")
check(bool(exec_sign), "resumePendingExecSign exists")
wait_at, signer_at = exec_sign.find("await authReady()"), exec_sign.find("signerFor(")
check(wait_at != -1, "the dApp signing path awaits authReady()")
check(wait_at != -1 and signer_at != -1 and wait_at < signer_at,
      "it awaits the signer BEFORE it picks one (signerFor) — the base key is never captured")
consumed = exec_sign.find("  pendingExecSign = null;  ")   # the consuming line itself (the early-return ones go on with needUI)
check(consumed != -1 and consumed < wait_at, "the request is consumed before the await, so a second resume cannot sign it twice")

ready = body("authReady")
check("authSync()" in ready and "state._authReady" in ready, "authReady memoises authSync on state._authReady")

ui = body("showWalletUI")
check("state._authReady = null" in ui and "authReady()" in ui, "a (re)loaded wallet finds its signer afresh")
check(not re.search(r"(?<![A-Za-z_.])authSync\(\)\.then", ui), "showWalletUI goes through authReady, not a bare authSync")

switch = SRC[SRC.find("state.authAcct = null;\n  state._authReady = null;"):][:200]
check("showWalletUI()" in switch, "an account switch resets the signer before showing the new account")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
