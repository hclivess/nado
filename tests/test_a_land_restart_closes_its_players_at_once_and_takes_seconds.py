"""
A restart of the Land world server takes seconds, not a minute (measured 2026-11-16 on the live planet: three restarts,
each 46-47 s from systemd's "Stopping" to "Started", the planet down for every player meanwhile). The framework waited
out its 60 s shutdown timeout for the players' open sockets while the background loops ran on, writing twice a second to
the terrain oracle already gone with the stop ("pipe closed by peer"). scripts/land_server.py make_app now cancels the
loops and closes every socket as "going away" (1001) on the stop's first step — each page reconnects by itself — and
run_app waits SHUTDOWN_S for requests in flight. Here the real server is started on a free port with a throwaway data
directory, a visitor's socket opened, and SIGTERM sent: the socket is told 1001 and the process is gone within seconds.
Run: python3 tests/test_a_land_restart_closes_its_players_at_once_and_takes_seconds.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-restart-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, signal, socket, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _harness
_report = _harness.Report()
check = _report.check
src = open(os.path.join(ROOT, "scripts", "land_server.py")).read()
check("the stop's first step cancels the loops and closes every socket as going away",
      "app.on_shutdown.append(on_going)" in src and "await ws.close(code=WSCloseCode.GOING_AWAY" in src)
check("run_app waits SHUTDOWN_S for requests in flight, not the framework's 60 s",
      "shutdown_timeout=SHUTDOWN_S)" in src and "SHUTDOWN_S = 5.0" in src)
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
s = socket.socket(); s.bind(("127.0.0.1", 0)); DEAD = s.getsockname()[1]; s.close()     # an exec node nobody answers on
data = tempfile.mkdtemp(prefix="land-restart-", dir=os.environ["HOME"])
env = dict(os.environ, NADO_ALLOW_PYTHON_KERNELS=os.environ.get("NADO_ALLOW_PYTHON_KERNELS", "1"))
proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "scripts", "land_server.py"), "--data", data, "--port", str(PORT),
                         "--exec", f"http://127.0.0.1:{DEAD}", "--shot-page", "off"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env)
atexit.register(lambda: proc.poll() is None and proc.kill())


async def main():
    import aiohttp
    async with aiohttp.ClientSession() as c:
        for _ in range(120):                                   # the server and its terrain oracle starting
            try:
                async with c.get(f"http://127.0.0.1:{PORT}/land/api/sats") as r:
                    if r.status < 500:
                        break
            except Exception:
                await asyncio.sleep(0.5)
        else:
            check("the world server started", False, proc.stderr.read().decode()[-500:] if proc.poll() is not None else "no answer")
            return
        async with c.ws_connect(f"http://127.0.0.1:{PORT}/land/ws") as ws:
            hello = await asyncio.wait_for(ws.receive_json(), 20)
            check("a visitor's page is connected (the server said hello)", hello.get("t") == "hello", hello)
            t0 = time.time()
            proc.send_signal(signal.SIGTERM)                   # what systemctl restart sends
            code = None
            while True:
                m = await asyncio.wait_for(ws.receive(), 30)
                if m.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                    code = ws.close_code; break
            told = time.time() - t0
        check(f"the page is told the server is going away (1001), {told:.1f} s after the stop", code == 1001 and told < 3, (code, told))
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        pass
    gone = time.time() - t0
    check(f"the process is gone {gone:.1f} s after the stop (a live restart measured 46-47 s)", proc.poll() is not None and gone < 10, gone)

asyncio.run(main())
_report.done()
