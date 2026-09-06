"""(1) peer_ops.own_ips covers EVERY address that is this host (config ip + detected ip + all global
interface addresses) and check_ip rejects each; (2) while fast-forwarding, the depth-floor corroboration
verdict is reused for SYNC_CORROB_TTL_S instead of being re-probed per applied block; other modes probe
every call. Source pins for the peer-loop merges."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import peer_ops


def main():
    peer_ops._local_ips_cache["v"] = frozenset({"203.0.113.9", "2001:db8::9"})
    peer_ops._own_ip_cache["v"] = "2001:db8::9"
    peer_ops.get_config = lambda: {"ip": "2001:db8::9"}
    mine = peer_ops.own_ips()
    assert {"203.0.113.9", "2001:db8::9"} <= mine, mine
    os.environ.pop("NADO_TESTNET", None)
    assert not peer_ops.check_ip("203.0.113.9") and not peer_ops.check_ip("2001:db8::9")
    assert peer_ops.check_ip("8.8.8.8")

    from loops import core_loop
    class _MS: emergency_mode = True
    class _C:
        memserver = _MS()
        probes = 0
        def _depth_floor_corroborated_probe(self):
            self.probes += 1
            return self.probes % 2 == 1
    c = _C()
    f = core_loop.CoreClient._depth_floor_corroborated
    v1 = f(c); v2 = f(c); v3 = f(c)
    assert (v1, v2, v3) == (True, True, True) and c.probes == 1, (v1, v2, v3, c.probes)
    c._sync_corrob_memo = (time.monotonic() - core_loop.SYNC_CORROB_TTL_S - 1, True)
    assert f(c) is False and c.probes == 2          # expired: re-probed, fresh verdict returned
    c.memserver.emergency_mode = False
    f(c); f(c)
    assert c.probes == 4                              # normal mode: every call probes

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "loops", "peer_loop.py")).read()
    assert "check_ip(entry)" in src and "peer not in _mine and check_ip(peer)" in src
    assert "self.memserver.peers.remove(_my_ip)" in src
    assert "elif key in own_ips() or key == self.memserver.ip:" in src, "own status must never enter status_pool"
    assert 'Dropped our own ip {_my_ip} from the consensus pools' in src
    assert "_s not in _mine_seed" in src, "seed re-dial must use the own-ip SET (this box IS a seed)"
    psrc = open(os.path.join(root, "ops", "peer_ops.py")).read()
    assert "ip == my_ip or ip in own_ips()" in psrc and "p not in own_ips() and check_ip(p)" in psrc
    csrc = open(os.path.join(root, "loops", "core_loop.py")).read()
    assert csrc.count("_me = own_ips() | {self.memserver.ip, get_config().get(\"ip\")}") == 4
    print("ALL OK")


if __name__ == "__main__":
    main()
