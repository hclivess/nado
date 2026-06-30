#!/usr/bin/env python3
"""
Local multi-node NADO testnet harness.

Launches N `nado.py` nodes on distinct 127.0.0.x loopback IPs (shared port 9173) in
NADO_TESTNET mode, meshes them via pre-seeded peer files, polls /status, and reports whether
they converge on a common tip and produce blocks. Tears everything down at the end.

Usage:  python scripts/testnet/run_testnet.py [num_nodes=3] [run_seconds=240]

NADO_TESTNET=1 (set per child) relaxes check_ip for loopback peers, makes get_public_ip return
the configured IP (no internet), and binds each node to its own 127.0.0.x:port. NEVER set it on
mainnet. This harness only touches throwaway temp dirs; it does not touch any real node data.
"""
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
from hashing import base64encode          # noqa: E402
from Curve25519 import generate_keydict   # noqa: E402
from protocol import B_MIN                 # noqa: E402  (bond amount; NOT a literal — must be >= B_MIN)

PORT = 9173


def node_ip(i):
    return f"127.0.0.{i + 2}"             # node 0 -> 127.0.0.2, etc. (avoid 127.0.0.1)


def seed_node(home, i, all_keys, bond_manifest):
    """write config + keys + peer files + the shared bond manifest for node i under <home>/nado/
    (NOT blocks/ or index/, which the node creates itself at genesis)."""
    base = os.path.join(home, "nado")
    os.makedirs(os.path.join(base, "private"), exist_ok=True)
    os.makedirs(os.path.join(base, "peers"), exist_ok=True)

    json.dump({"port": PORT, "ip": node_ip(i), "protocol": 2,
               "server_key": secrets.token_hex(32), "min_peers": 1, "max_rollbacks": 10,
               "cascade_limit": 1, "promiscuous": True,
               # fast local blocks so a short run produces many blocks (LOCAL timing knob only —
               # block_time is non-consensus; every node uses the same value so tips still agree).
               # Override with NADO_TESTNET_BLOCKTIME to model realistic blocks where the mempool
               # gossip-converges between blocks (so per-node FFG/RANDAO txs don't fork same-height blocks).
               "block_time": int(os.environ.get("NADO_TESTNET_BLOCKTIME", "2"))},
              open(os.path.join(base, "private", "config.dat"), "w"))

    # pre-generate the key so we know every node's address up front and can fully mesh them
    json.dump(all_keys[i], open(os.path.join(base, "private", "keys.dat"), "w"))

    # BYTE-IDENTICAL bond manifest on every node: genesis seeds these bonded accounts (S4.3) so
    # there is an eligible producer set from block 1. Any per-node difference -> different
    # registry -> different winner -> permanent fork, so it must be the same bytes everywhere.
    json.dump(bond_manifest, open(os.path.join(base, "private", "genesis_bonds.dat"), "w"))

    # seed peer files for ALL nodes (incl. self) so the producer set is known from boot
    for j, kd in enumerate(all_keys):
        peer = {"peer_address": kd["address"], "peer_ip": node_ip(j),
                "peer_port": PORT, "peer_trust": 10000}
        json.dump(peer, open(os.path.join(base, "peers", f"{base64encode(node_ip(j))}.dat"), "w"))


def status(i, timeout=4):
    try:
        with urllib.request.urlopen(f"http://{node_ip(i)}:{PORT}/status", timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    run_seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 240

    workdir = tempfile.mkdtemp(prefix="nado_testnet_")
    print(f"[testnet] {n} nodes, up to {run_seconds}s, workdir {workdir}", flush=True)
    keys = [generate_keydict() for _ in range(n)]
    # shared, sorted, BYTE-IDENTICAL bond manifest: each node bonds exactly B_MIN -> 1 share each,
    # so total_shares == n > 0 and the fail-closed selector always has a winner from block 1.
    bond_manifest = sorted(({"address": kd["address"], "bonded": B_MIN} for kd in keys),
                           key=lambda e: e["address"])
    homes = [os.path.join(workdir, f"node{i}") for i in range(n)]
    for i in range(n):
        seed_node(homes[i], i, keys, bond_manifest)
        print(f"[testnet] node{i} {node_ip(i)}:{PORT} address={keys[i]['address']}", flush=True)
    print(f"[testnet] genesis bonds: {n} accounts x {B_MIN} (1 share each)", flush=True)

    procs = []
    try:
        for i in range(n):
            env = dict(os.environ, HOME=homes[i], NADO_TESTNET="1")
            logf = open(os.path.join(homes[i], "node.log"), "w")
            procs.append(subprocess.Popen([sys.executable, "nado.py"], cwd=REPO, env=env,
                                          stdout=logf, stderr=subprocess.STDOUT))
        print("[testnet] launched; polling /status ...", flush=True)

        # NADO_TESTNET_FULL: don't stop at first convergence — run the full duration and keep checking,
        # so the net can cross epoch boundaries (FFG attestations + RANDAO beacon engage at epoch >= 2).
        full_mode = bool(os.environ.get("NADO_TESTNET_FULL"))
        deadline = time.time() + run_seconds
        converged = False
        while time.time() < deadline:
            time.sleep(10)
            sts = [status(i) for i in range(n)]
            up = sum(1 for s in sts if "error" not in s)
            blocks = []
            for i, s in enumerate(sts):
                # /status exposes the tip hash; height is logged, so infer progress via hash != genesis
                blocks.append(s.get("latest_block_hash", "err")[:10] if "error" not in s else "DOWN")
            tips = {s.get("latest_block_hash") for s in sts if "error" not in s}
            finals = [s.get("finalized_height") for s in sts if "error" not in s]
            ffgs = [s.get("ffg_finalized") for s in sts if "error" not in s]
            print(f"[testnet] t={int(time.time()-(deadline-run_seconds))}s up={up}/{n} "
                  f"tips={blocks} distinct_tips={len(tips)} finalized={finals} ffg={ffgs}", flush=True)
            # progress check: any node advanced past genesis AND all agree on one tip
            genesis_hash = "21872f6c3dd92a402fc939587ae7a1580ba448ff75c5ccbe3091f0da248d6e46"
            advanced = any(s.get("latest_block_hash") not in (None, genesis_hash)
                           for s in sts if "error" not in s)
            if up == n and len(tips) == 1 and advanced:
                converged = True
                if not full_mode:
                    print("[testnet] CONVERGED: all nodes agree on a non-genesis tip", flush=True)
                    break
            elif full_mode:
                converged = False  # reflect current (transient) divergence in full-duration mode

        # final report
        print("\n[testnet] final /status:", flush=True)
        for i in range(n):
            s = status(i)
            print(f"  node{i} {node_ip(i)}: {json.dumps(s)[:200]}", flush=True)
        print(f"\n[testnet] RESULT: {'PASS — converged + produced a block' if converged else 'INCOMPLETE — see logs'}",
              flush=True)
        if not converged:
            print("[testnet] HINT: if nodes are up + meshed but stuck at genesis, check that each "
                  "seeded bond >= B_MIN (else total_shares==0 and the fail-closed selector mints "
                  "nothing), and that genesis_bonds.dat is byte-identical across nodes.", flush=True)
            for i in range(n):
                print(f"\n----- node{i} log tail -----", flush=True)
                try:
                    print("".join(open(os.path.join(homes[i], "node.log")).readlines()[-20:]), flush=True)
                except Exception as e:
                    print(f"(no log: {e})", flush=True)
        return 0 if converged else 2
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        time.sleep(2)
        for p in procs:
            try:
                p.kill()
            except Exception:
                pass
        print(f"[testnet] torn down. logs under {workdir}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
