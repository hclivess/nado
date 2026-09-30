"""After the heavy refresh switches our public address, the node USES the new one (issue #86).

update_local_ip rewrites private/config.json's "ip" with the address that answers on our port, but memserver.ip
was read once at boot and never again. So after a switch (a CGNAT'd v4 at boot, a working IPv6 found by the
probe) the can_mine self-probe, announce_me and the /relays self row kept using the DEAD address until a restart:
the node reported "ports closed" and announced an address nobody could dial. PeerClient._refresh_own_ip now
re-reads the config after the write and probes the address it will advertise; a pinned address ("auto_ip":
false, which update_local_ip never overwrites) stays exactly as it was.

The network and the config are stand-ins; nothing is dialled or written outside this test's HOME.
"""
import os as _os, tempfile as _tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): never the live node's HOME or exec files
_os.environ["HOME"] = _tempfile.mkdtemp(prefix="nado-test-")
_os.environ["NADO_EXEC_STATE"] = _os.path.join(_os.environ["HOME"], "exec_state.json")
_os.environ["NADO_EXEC_DA"] = _os.path.join(_os.environ["HOME"], "exec_da")
import logging
import os
import sys
import types

import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import loops.peer_loop as PL                                           # noqa: E402

_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def run(boot_ip, answering, pinned=False):
    """One heavy-refresh IP step. `answering` = the addresses that answer on our port."""
    cfg = {"ip": boot_ip, "auto_ip": (False if pinned else True)}
    probed = []

    async def public_ips(logger=None):
        return ["203.0.113.7", "2001:db8::7"]             # what the detectors report: CGNAT v4 first, then v6

    def self_port(ip, port):
        probed.append(ip)
        return ip in answering

    def update_local_ip(ip, logger):                       # the real one's contract: honour a pin, else write
        if cfg.get("auto_ip") is False:
            return
        if ip and ip != cfg["ip"]:
            cfg["ip"] = ip

    PL.get_public_ips, PL.test_self_port, PL.update_local_ip = public_ips, self_port, update_local_ip
    PL.pick_reachable_ip = lambda cands, port, logger, current=None: next(
        (c for c in cands if self_port(c, port)), current if current and self_port(current, port) else None)
    PL.get_config = lambda: dict(cfg)
    mem = types.SimpleNamespace(ip=boot_ip, port=9173, can_mine=None)
    peer = types.SimpleNamespace(memserver=mem, logger=logging.getLogger("own-ip"))
    PL.PeerClient._refresh_own_ip(peer)
    return mem, cfg, probed


mem, cfg, probed = run("203.0.113.7", answering={"2001:db8::7"})
check("the config moves to the address that answers", cfg["ip"] == "2001:db8::7", cfg)
check("memserver.ip follows it", mem.ip == "2001:db8::7", mem.ip)
check("can_mine is probed on the NEW address", probed[-1] == "2001:db8::7" and mem.can_mine is True, (probed, mem.can_mine))

mem, cfg, probed = run("198.51.100.9", answering={"198.51.100.9", "2001:db8::7"}, pinned=True)
check("a pinned address is never replaced", cfg["ip"] == "198.51.100.9" and mem.ip == "198.51.100.9", (cfg, mem.ip))
check("...and is what can_mine probes", probed[-1] == "198.51.100.9" and mem.can_mine is True, probed)

mem, cfg, probed = run("2001:db8::7", answering=set())
check("when nothing answers, nothing churns", cfg["ip"] == "2001:db8::7" and mem.ip == "2001:db8::7")
check("...and the node reports it cannot be reached", mem.can_mine is False)

if __name__ == "__main__":
    if _fails:
        print(f"{len(_fails)} FAILED: {_fails}")
        sys.exit(1)
    print("ALL PASS")
