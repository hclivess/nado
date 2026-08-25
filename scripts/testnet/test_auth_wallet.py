#!/usr/bin/env python3
"""Headless-BROWSER test of the wallet's Account keys panel on a throwaway testnet (doc/key-rotation.md).

Launches n nodes with account authentication forced live, funds a fresh wallet seed from node0, then drives
the REAL wallet page served by node1 with puppeteer (scripts/testnet/wallet_auth.mjs): import seed → Settings →
Protect (phrase shown once) → Rotate with the phrase → wrong phrase refused → reload re-finds the signer →
Send with the rotated-in key. Every on-chain effect is verified through the node's HTTP API.

Usage: python3 scripts/testnet/test_auth_wallet.py [n] [seconds]      (exit 0 iff every browser step passed)
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
os.environ["NADO_AUTH_FORCE"] = "1"

import run_testnet as RT                                            # noqa: E402
RT.PORT = int(os.environ.get("NADO_AUTHWALLET_PORT", "9473"))       # a free port: prod holds 9173, the rotation scenario 9373
from signatures import generate_keydict                             # noqa: E402
from ops.transaction_ops import draft_transaction, create_transaction  # noqa: E402
from protocol import B_MIN, MIN_TX_FEE, CHAIN_ID                    # noqa: E402

PORT = RT.PORT


def url(i, path):
    return f"http://{RT.node_ip(i)}:{PORT}{path}"


def get(i, path, timeout=6):
    with urllib.request.urlopen(url(i, path), timeout=timeout) as r:
        return json.loads(r.read().decode())


def post(i, path, body):
    req = urllib.request.Request(url(i, path), data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"result": False, "message": e.read().decode()[:300]}


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    run_seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 900
    workdir = tempfile.mkdtemp(prefix="nado_authwallet_")
    print(f"[auth-wallet] {n} nodes, budget {run_seconds}s, workdir {workdir}", flush=True)
    keys = [generate_keydict() for _ in range(n)]
    bond_manifest = sorted(({"address": kd["address"], "bonded": B_MIN} for kd in keys), key=lambda e: e["address"])
    homes = [os.path.join(workdir, f"node{i}") for i in range(n)]
    alloc = [{"address": keys[0]["address"], "balance": 100 * 10_000_000_000, "bonded": B_MIN}]
    for i in range(n):
        RT.seed_node(homes[i], i, keys, bond_manifest)
        json.dump(alloc, open(os.path.join(homes[i], "nado", "private", "genesis_alloc.dat"), "w"))
    WALLET = generate_keydict()          # the browser wallet's seed = its private_key (32-byte seed hex)
    PAYEE = generate_keydict()["address"]

    def launch(i):
        env = dict(os.environ, HOME=homes[i], NADO_TESTNET="1", NADO_AUTH_FORCE="1")
        logf = open(os.path.join(homes[i], "node.log"), "a")
        return subprocess.Popen([sys.executable, "nado.py"], cwd=REPO, env=env, stdout=logf, stderr=subprocess.STDOUT)

    procs = [launch(i) for i in range(n)]
    ok_all = False
    try:
        # wait for a real (non-genesis) converged tip
        genesis = None
        deadline = time.time() + run_seconds // 2
        while time.time() < deadline:
            sts = [RT.status(i) for i in range(n)]
            if all("error" not in s for s in sts):
                genesis = genesis or sts[0].get("latest_block_hash")
                tips = {s.get("latest_block_hash") for s in sts}
                if len(tips) == 1 and next(iter(tips)) != genesis and all(int(s.get("finalized_height") or 0) >= 0 for s in sts):
                    break
            time.sleep(5)
        print("[auth-wallet] fleet converged", flush=True)
        # fund the wallet address from node0 (legacy string-signature transfer)
        t = int(get(0, "/get_latest_block")["block_number"])
        d = draft_transaction(keys[0]["address"], WALLET["address"], 10 * 10_000_000_000, keys[0]["public_key"], int(time.time()), "", t + 40)
        d["chain_id"] = CHAIN_ID
        tx = create_transaction(d, keys[0]["private_key"], MIN_TX_FEE)
        r = post(0, "/submit_transaction", tx)
        print(f"[auth-wallet] funding tx: {r}", flush=True)
        deadline = time.time() + 240
        while time.time() < deadline:
            try:
                if int(get(1, f"/get_account?address={WALLET['address']}").get("balance", 0)) >= 10 * 10_000_000_000:
                    break
            except Exception:
                pass
            time.sleep(3)
        print("[auth-wallet] wallet funded; driving the browser against node1", flush=True)
        proc = subprocess.run(["node", os.path.join(HERE, "wallet_auth.mjs"), url(1, "/wallet"), WALLET["private_key"], PAYEE],
                              capture_output=True, text=True, timeout=max(300, run_seconds))
        for line in proc.stdout.splitlines():
            print("[auth-wallet] " + line, flush=True)
        if proc.stderr.strip():
            print("[auth-wallet] stderr: " + proc.stderr.strip()[-600:], flush=True)
        ok_all = proc.returncode == 0
        # independent on-chain confirmation of the end state on EVERY node
        for i in range(n):
            a = get(i, f"/get_account?address={WALLET['address']}")
            print(f"[auth-wallet] node{i} final: auth v{(a.get('auth') or {}).get('v')} keys={len((a.get('auth') or {}).get('keys', []))} pending={bool(a.get('auth_pending'))}", flush=True)
            ok_all = ok_all and (a.get("auth") or {}).get("v") == 2
        print(f"\n[auth-wallet] RESULT: {'PASS' if ok_all else 'FAIL'}", flush=True)
        if not ok_all:
            print("".join(open(os.path.join(homes[1], "node.log")).readlines()[-20:]), flush=True)
        return 0 if ok_all else 2
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
