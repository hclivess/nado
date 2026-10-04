"""The read-only incident tools (scripts/fleet_tips.py, scripts/diagnose_wedge.py) never invent a verdict.

CLAUDE.md: "Never trust a uniform answer from your own tool." Three ways these two did exactly that:

  - fleet_tips.fork_point read a FAILED probe (block_hash -> None: timeout, error body, pruned height) as "the
    hashes differ": one transient timeout at `lo` printed "only a purge moves it" for a node that was merely
    frozen, one inside the search moved the fork point and invented a REORG, and None == None at `lo` counted
    as agreement. A missing hash is now UNKNOWN — no verdict.
  - diagnose_wedge counted the local node TWICE: /peers is me_to(peers), which appends our own public IP, so we
    voted as a peer and as __local__. A 1-1 split read as "we are on the MAJORITY chain" and exited 0.
  - diagnose_wedge's comment promised "a tie is reported rather than silently broken", and max() broke it
    silently by /peers order.

The tools are imported from their files with the network functions replaced; nothing is dialled.
"""
import os as _os, tempfile as _tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): never the live node's HOME or exec files
_os.environ["HOME"] = _tempfile.mkdtemp(prefix="nado-test-")
_os.environ["NADO_EXEC_STATE"] = _os.path.join(_os.environ["HOME"], "exec_state.json")
_os.environ["NADO_EXEC_DA"] = _os.path.join(_os.environ["HOME"], "exec_da")
import contextlib
import importlib.util
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "scripts", f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def chain(tag, fork_at=None):
    """block hash at height n: the shared chain below fork_at, `tag`'s own from it on."""
    return lambda n: (f"shared-{n}" if fork_at is None or n < fork_at else f"{tag}-{n}")


def fleet_tips_cases():
    ft = load("fleet_tips")
    a = chain("A")
    b_lag = chain("A")                           # same chain, just behind
    b_fork = chain("B", fork_at=500)             # agrees below 500

    def use(fa, fb, holes=()):
        ft.block_hash = lambda ip, h: None if (ip, h) in holes else (fa if ip == "a" else fb)(h)

    use(a, b_fork)
    check("a real fork is located at its last shared height", ft.fork_point("a", "b", 100, 900) == 499,
          ft.fork_point("a", "b", 100, 900))
    use(a, b_lag)
    check("a lagging node on the same chain is not forked", ft.fork_point("a", "b", 100, 900) == 900)
    use(a, b_lag, holes={("b", 900)})
    got = ft.fork_point("a", "b", 100, 900)
    check("a failed probe at the top of the window is no verdict", got == ft.UNKNOWN, got)
    use(a, b_fork, holes={("b", 100)})
    got = ft.fork_point("a", "b", 100, 900)
    check("a failed probe at lo is no verdict, not 'below the floor'", got == ft.UNKNOWN, got)
    use(a, b_fork, holes={("a", 100), ("b", 100)})
    got = ft.fork_point("a", "b", 100, 900)
    check("two failed probes at lo are not agreement", got == ft.UNKNOWN, got)
    use(a, b_fork, holes={("b", 500)})           # the first bisection midpoint
    got = ft.fork_point("a", "b", 100, 900)
    check("a failed probe inside the search does not move the fork point", got == ft.UNKNOWN, got)


def run_wedge(dw, local_addr, peers, statuses, hashes):
    """Drive diagnose_wedge.main against a fake fleet. `hashes[who]` = hash at the probe height."""
    dw.get = lambda url, timeout=12: {"peers": list(peers)} if url.endswith("/peers") else {}
    dw.status = lambda host, port=9173: (
        {"latest_block_height": 100, "address": local_addr} if host == "127.0.0.1" else statuses[host])
    dw.block_hash = lambda host, n, port=9173: hashes["__local__" if host == "127.0.0.1" else host]
    out = io.StringIO()
    argv = sys.argv
    sys.argv = ["diagnose_wedge.py"]
    try:
        with contextlib.redirect_stdout(out):
            rc = dw.main()
    finally:
        sys.argv = argv
    return rc, out.getvalue()


def diagnose_wedge_cases():
    dw = load("diagnose_wedge")
    st = lambda addr: {"latest_block_height": 100, "address": addr}
    # 1-1 split, with our own public IP in /peers (me_to always adds it)
    rc, out = run_wedge(dw, "me", ["1.1.1.1", "9.9.9.9"],
                        {"1.1.1.1": st("peerA"), "9.9.9.9": st("me")},
                        {"__local__": "X", "9.9.9.9": "X", "1.1.1.1": "Y"})
    check("our own IP in /peers is not a second vote for our chain", "MAJORITY" not in out and rc != 0, (rc, out))
    check("the self entry is not listed as a peer", "9.9.9.9" not in out, out)
    # a real 2-2 tie between four distinct nodes
    rc, out = run_wedge(dw, "me", ["1.1.1.1", "2.2.2.2", "3.3.3.3"],
                        {"1.1.1.1": st("a"), "2.2.2.2": st("b"), "3.3.3.3": st("c")},
                        {"__local__": "X", "1.1.1.1": "X", "2.2.2.2": "Y", "3.3.3.3": "Y"})
    check("a tie is reported, not broken by /peers order", "TIE" in out and "MAJORITY" not in out and rc == 2,
          (rc, out))
    # a genuine majority still reads as one
    rc, out = run_wedge(dw, "me", ["1.1.1.1", "2.2.2.2"],
                        {"1.1.1.1": st("a"), "2.2.2.2": st("b")},
                        {"__local__": "X", "1.1.1.1": "X", "2.2.2.2": "Y"})
    check("a real 2-1 majority holding us is still reported as the majority", "MAJORITY" in out and rc == 0,
          (rc, out))


if __name__ == "__main__":
    fleet_tips_cases()
    diagnose_wedge_cases()
    if _fails:
        print(f"{len(_fails)} FAILED: {_fails}")
        sys.exit(1)
    print("ALL PASS")
