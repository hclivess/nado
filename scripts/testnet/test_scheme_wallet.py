#!/usr/bin/env python3
"""Headless-BROWSER walk of user-selectable signature schemes on a throwaway testnet (doc/signature-schemes.md).

Run on a generation-29 tree (the schemes hold from block 1). Launches n nodes, funds — from node0, with a plain
ML-DSA-44 transfer — the SLH-DSA-128s account the node derives for a fresh master seed's first derived account, then
drives the REAL wallet page served by node1 (scripts/testnet/wallet_schemes.mjs): the master opens as Main, Account ->
"+ Add" offers the schemes with ML-DSA-44 first, the user picks SLH-DSA-128s, the wallet lands on exactly the address
the node derived, shows the funded balance, shows the SLH-DSA fee in the confirm dialog, and the transfer lands.
Every on-chain effect is then confirmed on EVERY node through its HTTP API, including that the landed transaction
names its scheme.

Usage: python3 scripts/testnet/test_scheme_wallet.py [n] [seconds]      (exit 0 iff every browser step passed)
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
RT.PORT = int(os.environ.get("NADO_SCHEMEWALLET_PORT", "9573"))     # a free port: prod 9173, the other scenarios 9373/9473
from signatures import generate_keydict, from_private_key           # noqa: E402
from ops.transaction_ops import draft_transaction, create_transaction  # noqa: E402
from hashing import blake2b_hash                                    # noqa: E402
import protocol as P                                                # noqa: E402

PORT = RT.PORT


def url(i, path):
    return f"http://{RT.node_ip(i)}:{PORT}{path}"


def get(i, path, timeout=6):
    with urllib.request.urlopen(url(i, path), timeout=timeout) as r:  # nosec B310 # loopback testnet harness: literal http:// to its own 127.0.0.x nodes
        return json.loads(r.read().decode())


def post(i, path, body):
    req = urllib.request.Request(url(i, path), data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # nosec B310 # loopback testnet harness: literal http:// to its own 127.0.0.x nodes
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"result": False, "message": e.read().decode()[:300]}


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    run_seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 900
    workdir = tempfile.mkdtemp(prefix="nado_schemewallet_")
    print(f"[scheme-wallet] {n} nodes, budget {run_seconds}s, workdir {workdir}", flush=True)
    keys = [generate_keydict() for _ in range(n)]
    bond_manifest = sorted(({"address": k["address"], "bonded": P.B_MIN} for k in keys), key=lambda e: e["address"])
    homes = [os.path.join(workdir, f"node{i}") for i in range(n)]
    alloc = [{"address": keys[0]["address"], "balance": 100 * 10_000_000_000, "bonded": P.B_MIN}]
    for i in range(n):
        RT.seed_node(homes[i], i, keys, bond_manifest)
        json.dump(alloc, open(os.path.join(homes[i], "nado", "private", "genesis_alloc.dat"), "w"))
    MASTER_KD = generate_keydict()                   # the browser wallet's master (a throwaway made here; Main is ML-DSA-44)
    MASTER = MASTER_KD["private_key"]
    child = blake2b_hash(["hd-account-v1", MASTER, 1, "slhdsa128s"], size=32)
    SLH = from_private_key(child, "slhdsa128s")      # what the node derives for Account 2 under SLH-DSA-128s
    PAYEE = generate_keydict()["address"]

    def launch(i):
        # this testnet's OWN genesis: the tree's genesis_carry.dat is the real chain's carried state (its open invites
        # need an INVITE_ESCROW this alloc does not hold), so point genesis at a carry file that does not exist
        env = dict(os.environ, HOME=homes[i], NADO_TESTNET="1", NADO_GENESIS_CARRY=os.path.join(homes[i], "no_genesis_carry.dat"),
                   NADO_EXEC_GENESIS=os.path.join(homes[i], "no_exec_genesis.json"))   # nor its carried contracts' pots
        logf = open(os.path.join(homes[i], "node.log"), "a")
        return subprocess.Popen([sys.executable, "nado.py"], cwd=REPO, env=env, stdout=logf, stderr=subprocess.STDOUT)

    procs = [launch(i) for i in range(n)]
    ok_all = False
    try:
        genesis, converged = None, False
        deadline = time.time() + run_seconds // 2
        while time.time() < deadline and not converged:
            sts = [RT.status(i) for i in range(n)]
            if all("error" not in s for s in sts):
                genesis = genesis or sts[0].get("latest_block_hash")
                tips = {s.get("latest_block_hash") for s in sts}
                converged = len(tips) == 1 and next(iter(tips)) != genesis
            if not converged:
                time.sleep(5)
        if not converged:
            print("[scheme-wallet] RESULT: FAIL — the testnet never converged on a block past genesis", flush=True)
            print("".join(open(os.path.join(homes[0], "node.log")).readlines()[-20:]), flush=True)
            return 2
        print("[scheme-wallet] fleet converged", flush=True)
        t = int(get(0, "/get_latest_block")["block_number"])
        d = draft_transaction(keys[0]["address"], SLH["address"], 10 * 10_000_000_000, keys[0]["public_key"], int(time.time()), "", t + 40)
        d["chain_id"] = P.CHAIN_ID
        r = post(0, "/submit_transaction", create_transaction(d, keys[0]["private_key"], P.MIN_TX_FEE))
        print(f"[scheme-wallet] funding the SLH-DSA account {SLH['address']}: {r}", flush=True)
        deadline = time.time() + 240
        while time.time() < deadline:
            try:
                if int(get(1, f"/get_account?address={SLH['address']}").get("balance", 0)) >= 10 * 10_000_000_000:
                    break
            except Exception:
                pass
            time.sleep(3)
        print("[scheme-wallet] funded; driving the browser against node1", flush=True)
        proc = subprocess.run(["node", os.path.join(HERE, "wallet_schemes.mjs"), url(1, "/wallet"), MASTER, MASTER_KD["public_key"], MASTER_KD["address"], SLH["address"], PAYEE],
                              capture_output=True, text=True, timeout=max(600, run_seconds))
        for line in proc.stdout.splitlines():
            print("[scheme-wallet] " + line, flush=True)
        if proc.stderr.strip():
            print("[scheme-wallet] stderr: " + proc.stderr.strip()[-600:], flush=True)
        ok_all = proc.returncode == 0
        # independent on-chain confirmation on EVERY node: the payee was paid, and the SLH-DSA account's key is the one
        # it published (PUBKEY-ONCE) — 32 bytes, an SLH-DSA key, under the address that commits to that scheme
        for i in range(n):
            try:
                a = get(i, f"/get_account?address={PAYEE}")
            except Exception:
                a = {}
            s = get(i, f"/get_account?address={SLH['address']}")
            pk = s.get("public_key") or ""
            good = int(a.get("balance", 0)) >= 10_000_000_000 and pk == SLH["public_key"] and len(pk) == 64
            print(f"[scheme-wallet] node{i}: payee {a.get('balance')} raw, SLH-DSA key published {len(pk) // 2} B -> {'ok' if good else 'WRONG'}", flush=True)
            ok_all = ok_all and good
        txs = get(1, f"/get_transactions_of_account?address={SLH['address']}&limit=50").get("transactions", [])
        sent = [x for x in txs if x.get("sender") == SLH["address"]]
        named = bool(sent) and all(x.get("alg") == "slhdsa128s" for x in sent)
        print(f"[scheme-wallet] the landed transfer names its scheme: {named} ({[x.get('alg') for x in sent]})", flush=True)
        ok_all = ok_all and named
        print(f"\n[scheme-wallet] RESULT: {'PASS' if ok_all else 'FAIL'}", flush=True)
        if not ok_all:
            print("".join(open(os.path.join(homes[1], "node.log")).readlines()[-25:]), flush=True)
        return 0 if ok_all else 2
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
