#!/usr/bin/env python3
"""
Fork-resolution scenario suite on the loopback testnet harness.

Scenarios (each on a fresh throwaway net; see run_testnet.py for the base mechanics):

  behind     One node is SIGSTOPped while the rest produce, then resumed. It must catch up by
             FORWARD SYNC ONLY: convergence to the fleet tip with zero rollbacks on the lagger.

  split      Two groups boot with DISJOINT peer meshes from one shared genesis, so each mines its
             own branch from block 1. After both branches outgrow max_rollbacks (the per-burst
             rollback cap — the 2026-08-23 live incident showed a measured span of 84 vs a cap of
             40 can otherwise never complete), the partition heals via /announce_peer. Every node
             must end on ONE common branch: the losing side performs a deeper-than-cap,
             possession-backed reorg (graft-point + span-budget fixes), the winning side keeps its
             chain. Convergence is the pass signal; a node parked mid-branch is the failure this
             suite exists to catch.

Usage:  python scripts/testnet/test_fork_resolution.py [scenario ...]
        (no args = all scenarios; exit 0 only if every scenario converges)

NADO_TESTNET only; never touches real node data.
"""
import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
from hashing import base64encode                    # noqa: E402
from signatures import generate_keydict             # noqa: E402
from scripts.testnet.run_testnet import node_ip  # noqa: E402

# own port: the production node on this box holds 0.0.0.0:9173, which blocks every 127.0.0.x:9173 bind
PORT = int(os.environ.get("NADO_TESTNET_PORT", "19173"))


def status(i, timeout=4):
    try:
        with urllib.request.urlopen(f"http://{node_ip(i)}:{PORT}/status", timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}
from protocol import B_MIN                          # noqa: E402

BLOCK_TIME = int(os.environ.get("NADO_TESTNET_BLOCKTIME", "6"))   # 2s starves mempool gossip under load
NODES = int(os.environ.get("NADO_FORKNET_NODES", "0"))             # scenario-specific default when 0
MAX_ROLLBACKS = 10          # mirrors the per-node config below; the split must outgrow this


def seed(home, i, all_keys, bond_manifest, peer_indices):
    """run_testnet.seed_node, but the peer mesh is only `peer_indices` (partition support)."""
    base = os.path.join(home, "nado")
    os.makedirs(os.path.join(base, "private"), exist_ok=True)
    os.makedirs(os.path.join(base, "peers"), exist_ok=True)
    json.dump({"port": PORT, "ip": node_ip(i), "protocol": 2,
               "server_key": secrets.token_hex(32), "min_peers": 1,
               "max_rollbacks": MAX_ROLLBACKS, "block_time": BLOCK_TIME},
              open(os.path.join(base, "private", "config.json"), "w"))
    json.dump(all_keys[i], open(os.path.join(base, "private", "keys.dat"), "w"))
    json.dump(bond_manifest, open(os.path.join(base, "private", "genesis_bonds.dat"), "w"))
    for j in peer_indices:
        peer = {"peer_address": all_keys[j]["address"], "peer_ip": node_ip(j), "peer_port": PORT}
        json.dump(peer, open(os.path.join(base, "peers", f"{base64encode(node_ip(j))}.dat"), "w"))


_LIVE_PROCS = []


def launch(n, meshes, stagger=False):
    """Start n nodes; node i's initial peer mesh is meshes[i] (list of node indices, incl. itself).
    With stagger=True, node 0 boots alone and the rest start only after it has produced a few blocks —
    fresh fully-meshed nodes otherwise RACE at genesis (deterministic production + divergent mempools =
    same-height forks; observed 2026-08-23: 4 fresh nodes -> 3 branches + one parked, no convergence in
    3 min). Real nodes join an established chain, so scenarios about anything OTHER than genesis racing
    should stagger. Returns (procs, homes, keys, tmp)."""
    tmp = tempfile.mkdtemp(prefix="nado-forknet-")
    keys = [generate_keydict() for _ in range(n)]
    bond_manifest = sorted(({"address": kd["address"], "bonded": B_MIN} for kd in keys),
                           key=lambda e: e["address"])
    procs, homes = [], []
    for i in range(n):
        home = os.path.join(tmp, f"n{i}")
        os.makedirs(home, exist_ok=True)
        seed(home, i, keys, bond_manifest, meshes[i])
        env = dict(os.environ, HOME=home, NADO_TESTNET="1")
        log = open(os.path.join(home, "node.log"), "w")
        procs.append(subprocess.Popen([sys.executable, os.path.join(REPO, "nado.py")],
                                      cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT))
        homes.append(home)
        if stagger and i == 0:
            t0 = time.time()
            while time.time() - t0 < 60 + 20 * BLOCK_TIME:
                st = status(0)
                if st.get("latest_block_height", 0) >= 4:
                    break
                time.sleep(2)
    _LIVE_PROCS.extend(procs)
    return procs, homes, keys, tmp


def teardown(procs):
    for p in procs:
        try:
            p.send_signal(signal.SIGCONT)
        except Exception:
            pass
        try:
            p.terminate()
        except Exception:
            pass
    deadline = time.time() + 15
    for p in procs:
        try:
            p.wait(timeout=max(0.1, deadline - time.time()))
        except Exception:
            p.kill()


def heights(n):
    out = {}
    for i in range(n):
        st = status(i)
        if "error" not in st:
            out[i] = (st.get("latest_block_height", -1), st.get("latest_block_hash", ""))
    return out


def wait_all_up(n, deadline_s=90):
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        if len(heights(n)) == n:
            return True
        time.sleep(2)
    return False


def wait_height(indices, h, deadline_s):
    """Wait until every node in `indices` reports height >= h."""
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        hs = heights(max(indices) + 1)
        if all(i in hs and hs[i][0] >= h for i in indices):
            return True
        time.sleep(2)
    return False


def wait_converged(n, deadline_s, tol=2):
    """All n nodes on one branch: highest common prefix — every pair's hash agrees at min height,
    and heights within tol of the max. Returns (ok, snapshot)."""
    t0 = time.time()
    snap = {}
    while time.time() - t0 < deadline_s:
        snap = heights(n)
        if len(snap) == n:
            hmin = min(h for h, _ in snap.values())
            hmax = max(h for h, _ in snap.values())
            if hmax - hmin <= tol and hmin > 0:
                # compare everyone's hash at hmin (query each node's own index)
                ref = None
                agree = True
                for i in snap:
                    try:
                        with urllib.request.urlopen(
                                f"http://{node_ip(i)}:{PORT}/get_block?number={hmin}&hash_only=1",
                                timeout=4) as r:
                            bh = json.loads(r.read().decode()).get("block_hash")
                    except Exception:
                        agree = False
                        break
                    if ref is None:
                        ref = bh
                    elif bh != ref:
                        agree = False
                        break
                if agree and ref:
                    return True, snap
        time.sleep(3)
    return False, snap


def announce(to_i, ip):
    try:
        urllib.request.urlopen(f"http://{node_ip(to_i)}:{PORT}/announce_peer?ip={ip}", timeout=4).read()
        return True
    except Exception:
        return False


def clean():
    """Kill every stray forknet node (children of any prior run, crashed or leaked) and remove their
    homes. Safe: matches only processes whose HOME is under a /tmp/nado-forknet-* dir."""
    import glob
    killed = 0
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            env = open(f"/proc/{pid}/environ", "rb").read().decode(errors="ignore")
        except Exception:
            continue
        if "/tmp/nado-forknet-" in env and "NADO_TESTNET=1" in env:
            try:
                os.kill(int(pid), signal.SIGKILL)
                killed += 1
            except Exception:
                pass
    time.sleep(1)
    removed = 0
    for d in glob.glob("/tmp/nado-forknet-*"):
        subprocess.run(["rm", "-rf", d], check=False)
        removed += 1
    print(f"[clean] killed {killed} node(s), removed {removed} dir(s)")
    return True


def scenario_swarm():
    """SCALE: N fully-meshed nodes (default 50, NADO_FORKNET_NODES) from one genesis must converge and
    keep producing. Exercises fork-choice and gossip at a fleet size the real network has not reached;
    the pass signal is one common branch across all N within the deadline."""
    n = NODES or 50
    meshes = [list(range(n))] * n
    procs, homes, keys, tmp = launch(n, meshes)
    try:
        assert wait_all_up(n, deadline_s=60 + 4 * n), f"not all {n} nodes booted"
        ok, snap = wait_converged(n, 120 * BLOCK_TIME + 10 * n)
        hs = sorted((h for h, _ in snap.values()))
        assert ok, f"swarm failed to converge: heights {hs[:3]}..{hs[-3:]} over {len(snap)} nodes"
        print(f"[swarm] PASS — {n} nodes converged at height {hs[0]}..{hs[-1]}")
        return True
    finally:
        teardown(procs)


def scenario_behind():
    """One lagging node must rejoin by pure forward sync."""
    n = 4
    meshes = [list(range(n))] * n
    procs, homes, keys, tmp = launch(n, meshes, stagger=True)
    try:
        assert wait_all_up(n), "nodes failed to boot"
        ok, _ = wait_converged(n, 60 * BLOCK_TIME)
        assert ok, "initial convergence failed"
        base_h = max(h for h, _ in heights(n).values())
        procs[n - 1].send_signal(signal.SIGSTOP)
        print(f"[behind] node {n-1} frozen at ~{base_h}")
        assert wait_height(list(range(n - 1)), base_h + 15, 30 * BLOCK_TIME + 120), \
            "fleet did not produce while lagger frozen"
        procs[n - 1].send_signal(signal.SIGCONT)
        print(f"[behind] node {n-1} resumed")
        ok, snap = wait_converged(n, 300)
        assert ok, f"lagger failed to catch up: {snap}"
        # forward-sync purity, precisely: the lagger must never revert a block the FLEET holds. Rolling
        # its OWN post-resume blocks is legitimate — on wake it can mint 1-2 blocks on its stale view
        # before gossip tells it the fleet is ahead, and reorging those away is the healthy self-fork
        # exit (observed in every run; those hashes never appear on any other node).
        import re as _re
        log = open(os.path.join(homes[n - 1], "node.log")).read()
        rolled = _re.findall(r"Rolled back ([0-9a-f]{16})", log)
        fleet_log = "".join(open(os.path.join(homes[j], "node.log")).read() for j in range(n - 1))
        offenders = [h for h in set(rolled) if h in fleet_log]
        assert not offenders, f"lagger rolled back FLEET blocks while merely BEHIND: {offenders}"
        print(f"[behind] PASS — converged at {snap}")
        return True
    finally:
        teardown(procs)


def scenario_split(minority=2, majority=3, grow_past=None):
    """Two disjoint meshes mine competing branches from genesis; after both outgrow the rollback
    cap, the partition heals; everyone must converge on one branch."""
    n = minority + majority
    grow_past = grow_past or (MAX_ROLLBACKS + 8)
    ga = list(range(minority))                    # group A (minority)
    gb = list(range(minority, n))                 # group B (majority)
    meshes = [ga if i in ga else gb for i in range(n)]
    procs, homes, keys, tmp = launch(n, meshes)
    try:
        assert wait_all_up(n), "nodes failed to boot"
        # both branches must clear the rollback cap so the losing reorg is deeper than max_rollbacks
        assert wait_height(list(range(n)), grow_past, grow_past * BLOCK_TIME * 6 + 300), \
            f"branches failed to reach {grow_past}: {heights(n)}"
        hs = heights(n)
        print(f"[split] pre-heal: {hs}")
        # sanity: the two groups really are on different branches
        assert hs[ga[0]][1] != hs[gb[0]][1] or hs[ga[0]][0] != hs[gb[0]][0], \
            "groups converged before the heal — partition did not hold"
        # heal: cross-announce every pair
        healed = 0
        for i in ga:
            for j in gb:
                healed += announce(i, node_ip(j)) + announce(j, node_ip(i))
        print(f"[split] partition healed ({healed} announcements)")
        ok, snap = wait_converged(n, 600)
        assert ok, f"fleet failed to converge after heal: {snap}"
        print(f"[split] PASS — converged at {snap}")
        return True
    finally:
        teardown(procs)


SCENARIOS = {"behind": scenario_behind, "split": scenario_split, "swarm": scenario_swarm,
             "clean": clean}


import atexit


@atexit.register
def _reap():
    for p in _LIVE_PROCS:
        try:
            p.send_signal(signal.SIGCONT)
            p.kill()
        except Exception:
            pass


def main():
    names = sys.argv[1:] or ["behind", "split"]
    results = {}
    for name in names:
        print(f"===== scenario: {name} =====", flush=True)
        try:
            results[name] = bool(SCENARIOS[name]())
        except AssertionError as e:
            print(f"[{name}] FAIL — {e}", flush=True)
            results[name] = False
        except Exception as e:
            print(f"[{name}] ERROR — {type(e).__name__}: {e}", flush=True)
            results[name] = False
    print("===== results =====")
    for k, v in results.items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
