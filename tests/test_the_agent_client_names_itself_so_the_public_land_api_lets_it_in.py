"""
The reference agent client (scripts/land_agent.py) names itself on every request. The public Land site sits behind
Cloudflare, which refuses Python's default "Python-urllib/x" client with 403 — so every AI agent using this client
reached nothing on land.nadochain.com until it sent an honest User-Agent (found building the town through the API,
2026-11-07). Here the client's own `call` is run against a local server that records what arrives.

Run: python3 tests/test_the_agent_client_names_itself_so_the_public_land_api_lets_it_in.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-agent-ua-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, sys, threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from aiohttp import web
import _harness
_report = _harness.Report()
check = _report.check
spec = importlib.util.spec_from_file_location("land_agent", os.path.join(ROOT, "scripts", "land_agent.py"))
A = importlib.util.module_from_spec(spec); spec.loader.exec_module(A)

seen = []


async def echo(request):
    seen.append((request.method, request.headers.get("User-Agent", "")))
    return web.json_response({"ok": True})

loop = asyncio.new_event_loop()
app = web.Application(); app.router.add_route("*", "/{tail:.*}", echo)
runner = web.AppRunner(app)
loop.run_until_complete(runner.setup())
site = web.TCPSite(runner, "127.0.0.1", 0)
loop.run_until_complete(site.start())
port = site._server.sockets[0].getsockname()[1]
threading.Thread(target=loop.run_forever, daemon=True).start()

A.call(f"http://127.0.0.1:{port}", "/land/api/challenge?kind=agent")
A.call(f"http://127.0.0.1:{port}", "/land/api/set", {"cells": []}, token="t")
check("every request names the client (a GET and a POST alike), never Python's default",
      len(seen) == 2 and all(ua == A.USER_AGENT for _, ua in seen) and not any("Python-urllib" in ua for _, ua in seen), seen)
check("…an honest name with where it comes from", A.USER_AGENT.startswith("nado-land-agent/") and "land.nadochain.com" in A.USER_AGENT)
_report.done()
