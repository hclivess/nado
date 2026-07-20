"""
Autogame UI test — drives REAL CLICKS in a headless browser against a running page.

Run:  python3 tests/autogame_ui_test.py [url]        (default: https://autogame.nadochain.com/)

Why this exists. Loading a page proves the shell renders; it does not prove a button works. Autogame
shipped with a "Set out" button that was clickable while signed out and did absolutely nothing — no alert,
no sign-in prompt, no error — and every check I had was green, because none of them clicked anything.

The specific bugs this would have caught, all of them SDK misuse:
  * `gate` takes a MAP of {elementId: visible} and toggles a `hidden` class. Calling it per-element
    (gate(el, cond, dapp)) iterates an element's keys and does nothing, so no button was ever gated.
  * The page never defined `.hidden`, so even correct gating would have been invisible.
  * Actions never called `canPay(dapp, 0n, what)`, the SDK helper whose whole job is to raise the shared
    sign-in bar when there is no wallet.
  * `alertBar(msg, label, fn)` renders its OWN fixed #alertBar element; passing a container element as the
    first argument printed "[object HTMLDivElement]" into the toast.

Requires chromium + websockets. Skips (exit 0) if either is missing, and says so loudly.
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request

URL = sys.argv[1] if len(sys.argv) > 1 else "https://autogame.nadochain.com/"
PORT = 9925
CHROME = next((p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium", "/snap/bin/chromium")
               if os.path.exists(p)), None)

fails = []


def ck(cond, msg, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + msg + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(msg)


async def run():
    try:
        import websockets
    except ImportError:
        print("SKIP: python websockets not installed — the clicks did NOT run")
        return 0

    chrome = subprocess.Popen(
        [CHROME, "--headless=new", f"--remote-debugging-port={PORT}", "--no-sandbox", "--disable-gpu",
         "--hide-scrollbars", "--window-size=900,1500", "--disable-dev-shm-usage", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        tgt = None
        for _ in range(40):
            try:
                tgt = [t for t in json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=2))
                       if t["type"] == "page"][0]
                break
            except Exception:
                time.sleep(0.5)
        if not tgt:
            print("SKIP: chromium did not start — the clicks did NOT run")
            return 0

        errors = []
        async with websockets.connect(tgt["webSocketDebuggerUrl"], max_size=40 * 1024 * 1024) as ws:
            n = 0

            async def send(method, params=None, wait=False):
                nonlocal n
                n += 1
                mine = n
                await ws.send(json.dumps({"id": mine, "method": method, "params": params or {}}))
                if not wait:
                    return None
                while True:
                    m = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                    if m.get("id") == mine:
                        return m.get("result")
                    if m.get("method") == "Runtime.exceptionThrown":
                        d = m["params"]["exceptionDetails"]
                        errors.append(str(d.get("exception", {}).get("description") or d.get("text")).split("\n")[0])
                    elif m.get("method") == "Runtime.consoleAPICalled" and m["params"]["type"] == "error":
                        errors.append(" ".join(str(a.get("value", "")) for a in m["params"]["args"])[:160])

            for meth in ("Runtime.enable", "Log.enable", "Page.enable"):
                await send(meth)
            await send("Page.navigate", {"url": URL})
            await asyncio.sleep(9)

            async def ev(expr):
                r = await send("Runtime.evaluate", {"expression": expr, "returnByValue": True}, wait=True)
                return (r or {}).get("result", {}).get("value")

            alert = "(document.getElementById('alertBar')?.innerText || '')"

            print(f"signed out, at {URL}")
            ck(await ev("!!document.getElementById('beginBtn')"), "the Set out button exists")
            ck(bool(await ev("document.getElementById('who')?.textContent")),
               "the wallet card renders (SDK drives #who/#bal/#l1bal by id)")
            ck(await ev("!!document.querySelector('#stanceseg button')"), "the stance control is built")
            ck(await ev("!!document.getElementById('hero')?.getContext('2d')"), "the gear canvas is present")
            ck((await ev("(()=>{const c=document.getElementById('hero');const d=c.getContext('2d')"
                         ".getImageData(0,0,c.width,c.height).data;let k=0;for(let i=3;i<d.length;i+=4)"
                         "if(d[i])k++;return k;})()") or 0) > 500,
               "the warrior is actually drawn, not an empty box")

            # the one that matters: a signed-out click must SAY something
            await ev(f"document.getElementById('alertBar')?.remove()")
            await ev("document.getElementById('beginBtn').click()")
            await asyncio.sleep(2.5)
            txt = (await ev(alert)) or ""
            ck(bool(txt.strip()), "clicking Set out while signed out gives visible feedback", txt[:60].replace("\n", " "))
            ck("sign in" in txt.lower() or "wallet" in txt.lower(),
               "that feedback tells you to sign in", txt[:60].replace("\n", " "))
            ck(await ev("!!document.querySelector('#alertBar button')"),
               "the feedback offers a sign-in button, not just text")

            # sign-in must hand off to the wallet with a return address back here
            await ev("document.getElementById('btnSignIn').click()")
            await asyncio.sleep(7)
            url = (await ev("location.href")) or ""
            ck("get.nadochain.com" in url, "Sign in hands off to the wallet", url[:70])
            ck("exec_sign=" in url and "ret=" in url, "the handoff carries the exec_sign payload and a return url")
            ck("autogame.nadochain.com" in urllib.parse.unquote(url),
               "the return url points back at this game")

        ck(not errors, f"no console errors ({len(errors)})", "; ".join(dict.fromkeys(errors))[:120])
    finally:
        chrome.terminate()
    return 1 if fails else 0


if __name__ == "__main__":
    import urllib.parse
    if not CHROME:
        print("SKIP: no chromium found — the clicks did NOT run")
        sys.exit(0)
    rc = asyncio.run(run())
    print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILURES"))
    sys.exit(rc)
