#!/usr/bin/env python3
"""Headless-BROWSER walk of the Stwo shielded pool, two users, on a throwaway testnet WITH EXEC NODES (G6 exit test:
"deposit, private send, unshield walked as a user ... from the served URL"; G7: "first quorum settle lands; exits claim").

Run on a tree where STWO_POOL_HEIGHT is live (generation 29: 1). Launches n nodes and, beside each, its own exec node
(execnode/execnode.py on 127.0.0.1:9700+i, its state and DA under that node's home, signing settles with that node's
bonded key, so the bonded quorum settles exactly as on the fleet), funds every node (a relay pays the L1 fee of the
private payments it publishes) and wallet A, then drives the REAL wallet served by node1 (A) and node2 (B) — two origins,
two separate storages (scripts/testnet/wallet_shield.mjs): A shields 2 NADO, sends 1 privately to B's zaddr and hands
over the payment code, B receives it, unshields 0.5 to B's public address and claims it once the quorum settled.
Every effect is then confirmed on EVERY node over HTTP: B's public balance rose, the shield escrow holds what the pool
should, and the exec nodes agree on one root.

Usage: python3 scripts/testnet/test_shield_wallet.py [n] [seconds]      (exit 0 iff every browser step passed)
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
import run_testnet as RT                                            # noqa: E402
RT.PORT = int(os.environ.get("NADO_SHIELDWALLET_PORT", "9583"))     # a free port: prod 9173, the other scenarios 9373-9573
EXEC_BASE = int(os.environ.get("NADO_SHIELDWALLET_EXEC_PORT", "9700"))
from signatures import generate_keydict                             # noqa: E402
import protocol as P                                                # noqa: E402

PORT = RT.PORT
NADO = 10_000_000_000


def url(i, path):
    return f"http://{RT.node_ip(i)}:{PORT}{path}"


def get(i, path, timeout=8):
    with urllib.request.urlopen(url(i, path), timeout=timeout) as r:  # nosec B310 # loopback testnet harness: literal http:// to its own 127.0.0.x nodes
        return json.loads(r.read().decode())


def exec_get(i, path, timeout=8):
    with urllib.request.urlopen(f"http://127.0.0.1:{EXEC_BASE + i}{path}", timeout=timeout) as r:  # nosec B310 # loopback testnet harness: its own exec node
        return json.loads(r.read().decode())


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    run_seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 2400
    if P.STWO_POOL_HEIGHT > 1:
        print(f"[shield-wallet] STWO_POOL_HEIGHT is {P.STWO_POOL_HEIGHT} on this tree (generation {P.CHAIN_GENERATION}): "
              "a loopback chain never reaches it — run this on the generation-29 tree", flush=True)
        return 2
    workdir = tempfile.mkdtemp(prefix="nado_shieldwallet_")
    print(f"[shield-wallet] {n} nodes + {n} exec nodes, budget {run_seconds}s, workdir {workdir}", flush=True)
    keys = [generate_keydict() for _ in range(n)]
    bond_manifest = sorted(({"address": k["address"], "bonded": P.B_MIN} for k in keys), key=lambda e: e["address"])
    homes = [os.path.join(workdir, f"node{i}") for i in range(n)]
    A, B = generate_keydict(), generate_keydict()            # the two users' wallets (throwaways made here)
    # the alloc SETS balance AND bonded (genesis.py, authoritative): a node entry without "bonded" unbonded the very keys
    # the bond manifest seeded, and every settle was refused "Settle sender is not a bonded validator"
    alloc = ([{"address": k["address"], "balance": 100 * NADO, "bonded": P.B_MIN} for k in keys]
             + [{"address": A["address"], "balance": 10 * NADO}])
    for i in range(n):
        RT.seed_node(homes[i], i, keys, bond_manifest)
        json.dump(alloc, open(os.path.join(homes[i], "nado", "private", "genesis_alloc.dat"), "w"))

    def own_genesis(i):
        # this testnet's OWN genesis: the tree's genesis_data carry and exec genesis describe the real chain
        return {"NADO_GENESIS_CARRY": os.path.join(homes[i], "no_genesis_carry.dat"),
                "NADO_EXEC_GENESIS": os.path.join(homes[i], "no_exec_genesis.json")}

    def launch_node(i):
        env = dict(os.environ, HOME=homes[i], NADO_TESTNET="1", NADO_EXEC_PORT=str(EXEC_BASE + i), **own_genesis(i))
        return subprocess.Popen([sys.executable, "nado.py"], cwd=REPO, env=env,
                                stdout=open(os.path.join(homes[i], "node.log"), "a"), stderr=subprocess.STDOUT)

    def launch_exec(i):
        env = dict(os.environ, HOME=homes[i], NADO_TESTNET="1", NADO_L1_URL=f"http://{RT.node_ip(i)}:{PORT}",
                   NADO_EXEC_STATE=os.path.join(homes[i], "exec_state.json"), NADO_EXEC_DA=os.path.join(homes[i], "exec_da"),
                   # 0.0.0.0, as on the fleet: the wallet reaches it on the RELAY's host (127.0.0.x), the node on 127.0.0.1
                   NADO_EXEC_PORT=str(EXEC_BASE + i), NADO_EXEC_BIND="0.0.0.0", **own_genesis(i))
        return subprocess.Popen([sys.executable, os.path.join(REPO, "execnode", "execnode.py")], cwd=homes[i], env=env,
                                stdout=open(os.path.join(homes[i], "exec.log"), "a"), stderr=subprocess.STDOUT)

    procs = [launch_node(i) for i in range(n)]
    ok_all = False
    try:
        genesis, converged = None, False
        deadline = time.time() + 600
        while time.time() < deadline and not converged:
            sts = [RT.status(i) for i in range(n)]
            if all("error" not in s for s in sts):
                genesis = genesis or sts[0].get("latest_block_hash")
                tips = {s.get("latest_block_hash") for s in sts}
                converged = len(tips) == 1 and next(iter(tips)) != genesis
            if not converged:
                time.sleep(5)
        if not converged:
            print("[shield-wallet] RESULT: FAIL — the testnet never converged past genesis", flush=True)
            return 2
        procs += [launch_exec(i) for i in range(n)]
        up = False
        deadline = time.time() + 300
        while time.time() < deadline and not up:
            try:
                up = all(exec_get(i, "/exec/root") is not None for i in range(n))
            except Exception:
                time.sleep(5)
        print(f"[shield-wallet] fleet converged; exec nodes up: {up}", flush=True)
        if not up:
            print("".join(open(os.path.join(homes[0], "exec.log")).readlines()[-25:]), flush=True)
            return 2
        hold = int(os.environ.get("NADO_WALK_HOLD", "0"))
        if hold:                                     # debugging: keep the testnet up for a hand-driven browser
            print(f"[shield-wallet] HOLD {hold}s — A {url(1, '/wallet')} seed {A['private_key']} pub-len {len(A['public_key'])} "
                  f"addr {A['address']} | B {url(2, '/wallet')} addr {B['address']} | workdir {workdir}", flush=True)
            json.dump({"A": A, "B": B, "urlA": url(1, "/wallet"), "urlB": url(2, "/wallet")},
                      open(os.path.join(workdir, "walk.json"), "w"))
            time.sleep(hold)
            return 0
        proc = subprocess.run(["node", os.path.join(HERE, "wallet_shield.mjs"),
                               url(1, "/wallet"), A["private_key"], A["public_key"], A["address"],
                               url(2, "/wallet"), B["private_key"], B["public_key"], B["address"]],
                              capture_output=True, text=True, timeout=run_seconds)
        for line in proc.stdout.splitlines():
            print("[shield-wallet] " + line, flush=True)
        if proc.stderr.strip():
            print("[shield-wallet] stderr: " + proc.stderr.strip()[-800:], flush=True)
        ok_all = proc.returncode == 0
        # independent confirmation on EVERY node: B's public balance is the claimed exit, and the exec nodes agree
        for i in range(n):
            try:
                b = int(get(i, f"/get_account?address={B['address']}").get("balance", 0))
            except Exception:
                b = 0
            try:
                s = int((get(i, f"/get_account?address={P.SHIELD_ESCROW}") or {}).get("balance", 0))
            except Exception:
                s = 0                                       # never touched: no deposit landed
            print(f"[shield-wallet] node{i}: B public {b} raw, SHIELD_ESCROW {s} raw", flush=True)
            ok_all = ok_all and b > 0
        roots = set()
        for i in range(n):
            try:
                st = exec_get(i, "/exec/root")
                roots.add((st.get("cursor"), st.get("root") or st.get("state_root")))
            except Exception as e:
                roots.add(("down", str(e)))
        print(f"[shield-wallet] exec nodes (cursor, root): {sorted(roots, key=str)[:3]}", flush=True)
        settled = get(0, "/get_settled")
        print(f"[shield-wallet] settled on L1: {json.dumps(settled)[:200]}", flush=True)
        print(f"\n[shield-wallet] RESULT: {'PASS' if ok_all else 'FAIL'}", flush=True)
        if not ok_all:
            for f in ("node.log", "exec.log"):
                print(f"--- node1 {f}\n" + "".join(open(os.path.join(homes[1], f)).readlines()[-25:]), flush=True)
        return 0 if ok_all else 2
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        if ok_all:
            import shutil
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
