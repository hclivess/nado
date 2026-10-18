"""Every wallet and game page runs under the Content-Security-Policy the node serves for it, with no script refused
(ops/static_versions.page_csp, nado.py _html_response; audit 2026-09-24 #22).

The node now sends script-src 'self' + the sha256 of each page's own inline scripts and inline handlers +
'wasm-unsafe-eval' + the analytics host — no 'unsafe-inline'. A policy that blocks a page's own code is an outage, so
this loads EVERY static/*.html in headless Chromium from a local server that answers with exactly that header (and the
real /protocol.js), waits for the page to settle, and fails on any "Refused to …" CSP message in the console. It also
pins that an injected inline script (one not shipped with the page) IS refused.
SKIPs without Chromium + Selenium.

Run: python3 tests/test_every_page_runs_under_its_content_security_policy.py
"""
import _harness
_harness.isolate("nado-test-csp-", exec_state=False)
import glob, http.server, os, shutil, sys, threading, time

T = _harness.Report()
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
except Exception:
    print("SKIP  selenium is not importable here"); sys.exit(0)
CHROME = shutil.which("chromium-browser") or shutil.which("chromium") or shutil.which("google-chrome")
if not CHROME:
    print("SKIP  no Chromium on this host"); sys.exit(0)
from ops.static_versions import page_csp
from ops import client_protocol
STATIC = os.path.join(_harness.ROOT, "static")
_pj = client_protocol.render_js()
PROTO = _pj if isinstance(_pj, bytes) else str(_pj).encode()
EVIL = b"<script>window.__csp_injected = 1</script>"


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        p = self.path.split("?", 1)[0]
        if p == "/protocol.js":
            return self._send(PROTO, "text/javascript")
        if p in ("/__inject.html", "/__inject_nocsp.html"):   # a page with an injected inline script NOT in its policy
            raw = open(os.path.join(STATIC, "dice.html"), "rb").read()
            assert b"</body>" in raw
            return self._send(raw.replace(b"</body>", EVIL + b"</body>"), "text/html",
                              csp=page_csp(raw) if p == "/__inject.html" else None)
        if not p.startswith("/static/"):
            return self._send(b"{}", "application/json")          # API calls: an empty answer is enough here
        f = os.path.normpath(os.path.join(STATIC, p[len("/static/"):]))
        if not f.startswith(STATIC) or not os.path.isfile(f):
            self.send_response(404); self.end_headers(); return
        body = open(f, "rb").read()
        ct = {".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
              ".wasm": "application/wasm", ".json": "application/json", ".svg": "image/svg+xml"}.get(os.path.splitext(f)[1], "application/octet-stream")
        self._send(body, ct, csp=page_csp(body) if f.endswith(".html") else None)

    def _send(self, body, ct, csp=None):
        self.send_response(200)
        self.send_header("Content-Type", ct)
        if csp:
            self.send_header("Content-Security-Policy", csp)
        self.end_headers(); self.wfile.write(body)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
o = Options()
for a in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"):
    o.add_argument(a)
o.binary_location = CHROME
o.set_capability("goog:loggingPrefs", {"browser": "ALL"})
try:
    d = webdriver.Chrome(options=o)
except Exception as e:
    print(f"SKIP  Chromium did not start under Selenium: {str(e)[:160]}"); sys.exit(0)
pages = sorted(os.path.basename(p) for p in glob.glob(os.path.join(STATIC, "*.html")))
T.check("the pages are found", len(pages) >= 20, len(pages))
refused = {}
try:
    for name in pages:
        d.get(f"{base}/static/{name}")
        time.sleep(2.5)
        msgs = [m["message"] for m in d.get_log("browser") if "Content Security Policy" in m["message"] or "Refused to" in m["message"]]
        if msgs:
            refused[name] = msgs[:2]
    d.get(f"{base}/__inject.html"); time.sleep(1.5)
    injected = d.execute_script("return window.__csp_injected || 0")
    _logs = [m["message"] for m in d.get_log("browser")]
    inj_logged = any("Content Security Policy" in m or "Refused to" in m for m in _logs)
    # the control: the same page served WITHOUT a policy runs the injected script (so the 0 above is the policy's doing)
    d.get(f"{base}/__inject_nocsp.html"); time.sleep(1.5)
    control = d.execute_script("return window.__csp_injected || 0")
finally:
    d.quit(); srv.shutdown()
T.check(f"all {len(pages)} pages run their own scripts with nothing refused", not refused,
        "; ".join(f"{k}: {v[0][:220]}" for k, v in list(refused.items())[:4]))
T.check("control: without the policy the injected script runs", control == 1, control)
T.check("an inline script injected into a page (not shipped with it) is refused by the policy", injected == 0 and inj_logged,
        (injected, inj_logged))
T.done("ALL PASS — every page runs under its Content-Security-Policy")
