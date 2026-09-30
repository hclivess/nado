"""block_ops.mining_status: the lane totals are computed once per (env, write generation, epoch) and reused
across the wallet's ~4/s polls; a new write generation recomputes. Also pins the peer loop's self-ip guard."""
import os as _os, tempfile as _tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): never the live node's HOME or exec files
_os.environ["HOME"] = _tempfile.mkdtemp(prefix="nado-test-")
_os.environ["NADO_EXEC_STATE"] = _os.path.join(_os.environ["HOME"], "exec_state.json")
_os.environ["NADO_EXEC_DA"] = _os.path.join(_os.environ["HOME"], "exec_da")
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import block_ops, kv_ops

calls = {"open": 0, "bonded": 0}
GEN = [1]


def main():
    block_ops.epoch_beacon = lambda e: "beacon"
    def _open(epoch):
        calls["open"] += 1
        return {"a1": {"fidelity": 3}, "a2": {"fidelity": 5}}
    def _bonded():
        calls["bonded"] += 1
        return {"b1": {"bonded": 10 ** 12, "fidelity": 2, "bond_since": 0}}
    block_ops.get_open_registry = _open
    block_ops.get_bonded_registry = _bonded
    # The response also carries bonded_producer_cut (0cb61b8f), computed from the block reward, whose bond-elastic
    # multiplier reads the registry through get_bonded_registry's own per-write-generation cache. That read is not the
    # lane memo this test pins (and is cached in production), so it is stubbed out of the count.
    block_ops.get_block_reward = lambda: 10 ** 9
    # a path INSIDE this test's throwaway HOME: the stub used to be the literal "/x", so as root every run created an
    # LMDB env at the filesystem root (found 2026-09-30 when CI, unprivileged, got PermissionError: '/x')
    kv_ops.env_path = lambda home=None: _os.path.join(_os.environ["HOME"], "memo-env")
    kv_ops.write_generation = lambda: GEN[0]
    block_ops._ms_lanes_cache[0] = None

    r1 = block_ops.mining_status("a1", 100, 6)
    r2 = block_ops.mining_status("a2", 100, 6)
    r3 = block_ops.mining_status("zz", 100, 6)
    assert calls == {"open": 1, "bonded": 1}, calls
    assert r1["total_open_weight"] == r2["total_open_weight"] == r3["total_open_weight"] > 0
    assert r1["my_open_weight"] > 0 and r3["my_open_weight"] == 0 and r3["registered_present"] is False
    assert r1["open_registry_size"] == 2 and r1["bonded_registry_size"] == 1
    GEN[0] = 2                                   # a block landed: totals recomputed once
    block_ops.mining_status("a1", 100, 6)
    block_ops.mining_status("a1", 100, 6)
    assert calls == {"open": 2, "bonded": 2}, calls
    block_ops.mining_status("a1", 160, 6)        # new epoch: recomputed
    assert calls["open"] == 3

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "loops", "peer_loop.py")).read()
    assert "check_ip(entry)" in src and "peer not in _mine and check_ip(peer)" in src and \
        "self.memserver.peers.remove(_my_ip)" in src, "peer loop must never admit our own ip"
    print("ALL OK")


if __name__ == "__main__":
    main()
