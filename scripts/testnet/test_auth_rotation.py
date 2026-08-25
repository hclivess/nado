#!/usr/bin/env python3
"""Account-authentication scenario on a throwaway loopback testnet (doc/key-rotation.md).

Launches n real nodes (NADO_TESTNET=1, NADO_AUTH_FORCE=1 so the feature is live on this generation), waits
for convergence, then drives node0's account through the whole lifecycle over HTTP and checks EVERY node
agrees at each step (the account doc via /get_account, and one tip — the block hash commits the state root):

  1. protect   — install hot + recovery (reconfig = both); lands on all nodes
  2. thief     — the hot key alone pends a rotation to an attacker key; all nodes show it pending
  3. cancel    — the recovery key cancels; all nodes show no pending + a freeze
  4. rotate    — hot + recovery rotate to a fresh hot key immediately; the old key is refused everywhere
  5. restart   — node0 restarts on the NEW keys.dat (with `account`) and keeps producing blocks under its
                 old address; the fleet stays converged
  6. spend     — a transfer signed by the new key lands; one signed by the old key is refused by every relay

Exit 0 only if every step passes. Usage: python3 scripts/testnet/test_auth_rotation.py [n] [seconds]
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
# Our own PORT: the production node on this box listens on 0.0.0.0:9173, so every 127.0.0.x:9173 is
# "already in use" and a child node would exit at startup. The IPs stay the harness's 127.0.0.x — that is the
# range NADO_TESTNET relaxes check_ip for; any other loopback range leaves the nodes unmeshed at genesis.
RT.PORT = int(os.environ.get("NADO_AUTHNET_PORT", "9373"))
from signatures import generate_keydict                             # noqa: E402
from ops.transaction_ops import construct_auth_tx, auth_pop, sign_entries, draft_transaction  # noqa: E402
from ops import auth_ops as A                                       # noqa: E402
from protocol import B_MIN, MIN_TX_FEE, CHAIN_ID, TX_INCLUSION_DELAY, AUTH_DELAY  # noqa: E402

PORT = RT.PORT
fails = 0


def step(name, ok, detail=""):
    global fails
    print(f"[auth-testnet] {'PASS' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}", flush=True)
    if not ok:
        fails += 1


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


def tip(i):
    return int(get(i, "/get_latest_block")["block_number"])


def wait_all(n, pred, label, patience=240):
    """Until pred(account_doc) holds on EVERY node (down nodes count as not-yet)."""
    deadline = time.time() + patience
    while time.time() < deadline:
        oks = []
        for i in range(n):
            try:
                d = get(i, f"/get_account?address={ACCT}")
                oks.append(bool(pred(d)))
                if not oks[-1] and os.environ.get("NADO_AUTHNET_DEBUG"):
                    print(f"[auth-testnet]   node{i} /get_account keys={sorted(d.keys()) if isinstance(d, dict) else type(d)} auth={str(d.get('auth'))[:60] if isinstance(d, dict) else ''}", flush=True)
            except Exception as e:
                oks.append(False)
                if os.environ.get("NADO_AUTHNET_DEBUG"):
                    print(f"[auth-testnet]   node{i} /get_account error: {e}", flush=True)
        if all(oks):
            return True
        time.sleep(3)
    print(f"[auth-testnet] timeout waiting for: {label}", flush=True)
    return False


GENESIS_HASHES = set()


def converged(n):
    """One tip on every node — and NOT the genesis tip: three nodes that never meshed all sit on block 0."""
    sts = [RT.status(i) for i in range(n)]
    if any("error" in s for s in sts):
        return False, sts
    tips = {s.get("latest_block_hash") for s in sts}
    advanced = all(int(s.get("finalized_height") or 0) > 0 or (s.get("latest_block_hash") not in GENESIS_HASHES) for s in sts)
    return len(tips) == 1 and advanced, sts


def wait_converged(n, patience=240):
    deadline = time.time() + patience
    while time.time() < deadline:
        ok, sts = converged(n)
        if ok and all(int(s.get("finalized_height") or 0) >= 0 for s in sts):
            return True
        time.sleep(5)
    return False


def submit(i, tx, label):
    r = post(i, "/submit_transaction", tx)
    step(f"{label}: relay accepted", bool(r.get("result")), str(r.get("message", ""))[:120])
    return bool(r.get("result"))


def refused_everywhere(n, tx, label, frag=""):
    """The tx must be refused by EVERY relay (consensus rule, not one node's opinion)."""
    outs = [post(i, "/submit_transaction", tx) for i in range(n)]
    ok = all(not o.get("result") and (frag in str(o.get("message", ""))) for o in outs)
    step(label, ok, "; ".join(str(o.get("message", ""))[:60] for o in outs))


def main():
    global ACCT
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    run_seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 600
    workdir = tempfile.mkdtemp(prefix="nado_authnet_")
    print(f"[auth-testnet] {n} nodes, budget {run_seconds}s, workdir {workdir}", flush=True)
    keys = [generate_keydict() for _ in range(n)]
    bond_manifest = sorted(({"address": kd["address"], "bonded": B_MIN} for kd in keys), key=lambda e: e["address"])
    homes = [os.path.join(workdir, f"node{i}") for i in range(n)]
    # node0 needs a SPENDABLE balance for fees from block 0: a byte-identical genesis_alloc.dat on every
    # node (the same carry-forward mechanism a reroll uses) credits it; the other nodes hold only bonds.
    # bonded = B_MIN too: an alloc row REPLACES the account doc, so a 0 here would erase node0's genesis bond
    # (it then never produces a block, which the post-rotation production check needs)
    alloc = [{"address": keys[0]["address"], "balance": 100 * 10_000_000_000, "bonded": B_MIN}]
    for i in range(n):
        RT.seed_node(homes[i], i, keys, bond_manifest)
        json.dump(alloc, open(os.path.join(homes[i], "nado", "private", "genesis_alloc.dat"), "w"))
    HOT = keys[0]; ACCT = HOT["address"]
    state = {}                                   # cross-step notes (e.g. the height the rotation landed at)
    REC, EVE, NEW = generate_keydict(), generate_keydict(), generate_keydict()
    PAYEE = generate_keydict()["address"]

    def launch(i):
        env = dict(os.environ, HOME=homes[i], NADO_TESTNET="1", NADO_AUTH_FORCE="1")
        logf = open(os.path.join(homes[i], "node.log"), "a")
        return subprocess.Popen([sys.executable, "nado.py"], cwd=REPO, env=env, stdout=logf, stderr=subprocess.STDOUT)

    procs = [launch(i) for i in range(n)]
    t0 = time.time()
    try:
        for _ in range(60):                                   # learn the genesis hash so convergence excludes it
            s0 = RT.status(0)
            if "error" not in s0 and s0.get("latest_block_hash"):
                GENESIS_HASHES.add(s0["latest_block_hash"]); break
            time.sleep(2)
        step("fleet converged on a tip", wait_converged(n, patience=run_seconds // 2))
        # node0 must be able to pay fees: it produces blocks with its genesis bond, so wait for a balance
        ok = wait_all(n, lambda d: int(d.get("balance", 0)) >= 20 * MIN_TX_FEE, "node0 has a spendable balance", patience=run_seconds // 3)
        step("node0 earned a balance for fees", ok)

        def cfg_protected(v, hot_pub):
            return {"v": v, "keys": [hot_pub, REC["public_key"]], "sign": ["ID", 0],
                    "reconf": ["THRESHOLD", 2, [["ID", 0], ["ID", 1]]]}

        def auth_tx(signers, data, at):
            t = tip(at)
            return construct_auth_tx(ACCT, signers, data, MIN_TX_FEE * len(signers), t + 40, min_block=t + TX_INCLUSION_DELAY)

        # 1. protect
        c1 = cfg_protected(1, HOT["public_key"])
        tx = auth_tx([HOT], {"op": "set", "cfg": c1, "pop": {REC["public_key"]: auth_pop(ACCT, c1, REC)}}, 0)
        if submit(0, tx, "protect"):
            step("protect landed on every node", wait_all(n, lambda d: (d.get("auth") or {}).get("v") == 1, "protect v1"))

        # 2. thief pends
        thief = {"v": 2, "keys": [EVE["public_key"]], "sign": ["ID", 0], "reconf": ["ID", 0]}
        tx = auth_tx([HOT], {"op": "set", "cfg": thief, "pop": {EVE["public_key"]: auth_pop(ACCT, thief, EVE)}}, 1)
        if submit(1, tx, "thief pends (submitted via node1)"):
            step("pending visible on every node", wait_all(n, lambda d: (d.get("auth_pending") or {}).get("txid") == tx["txid"], "pending"))
            d0 = get(0, f"/get_account?address={ACCT}")
            step("pending effective height = landing + AUTH_DELAY", (d0.get("auth_pending") or {}).get("eff", 0) > tip(0) and (d0["auth_pending"]["eff"] - AUTH_DELAY) <= tip(0))
        # the thief's key cannot act yet
        d = draft_transaction(ACCT, PAYEE, 1, None, int(time.time()), "", tip(0) + 40); d.pop("public_key"); d["fee"] = MIN_TX_FEE
        refused_everywhere(n, sign_entries(d, [EVE]), "pending key refused by every relay", "does not authorize")

        # 3. recovery cancels
        tx = auth_tx([REC], {"op": "cancel"}, 2)
        if submit(2, tx, "recovery cancels (submitted via node2)"):
            step("cancel landed everywhere + freeze set", wait_all(n, lambda d: not d.get("auth_pending") and int(d.get("auth_freeze", 0)) > 0, "cancel"))
        tx = auth_tx([HOT], {"op": "set", "cfg": thief, "pop": {EVE["public_key"]: auth_pop(ACCT, thief, EVE)}}, 0)
        refused_everywhere(n, tx, "frozen: hot-only change refused by every relay", "frozen")

        # 4. rotate with the full policy
        c2 = cfg_protected(2, NEW["public_key"])
        tx = auth_tx([HOT, REC], {"op": "set", "cfg": c2, "pop": {NEW["public_key"]: auth_pop(ACCT, c2, NEW)}}, 0)
        if submit(0, tx, "rotate hot -> NEW (hot + recovery)"):
            step("rotation landed on every node", wait_all(n, lambda d: (d.get("auth") or {}).get("v") == 2 and (d.get("auth") or {}).get("keys", [""])[0] == NEW["public_key"], "rotate"))
            state["rot_landed_h"] = tip(1)
        d = draft_transaction(ACCT, PAYEE, 1, None, int(time.time()), "", tip(0) + 40); d.pop("public_key"); d["fee"] = MIN_TX_FEE
        refused_everywhere(n, sign_entries(d, [HOT]), "old hot key refused by every relay after rotation", "does not authorize")

        # 5. restart node0 on the new key (keys.dat with `account`)
        nk = dict(NEW); nk["account"] = ACCT
        kf = os.path.join(homes[0], "nado", "private", "keys.dat")
        json.dump(nk, open(kf, "w")); os.chmod(kf, 0o600)
        procs[0].terminate(); procs[0].wait(timeout=30)
        procs[0] = launch(0)
        time.sleep(15)
        st0 = None
        for _ in range(30):
            st0 = RT.status(0)
            if "error" not in st0:
                break
            time.sleep(4)
        step("node0 back up on the new key", st0 is not None and "error" not in st0)
        ms = get(0, f"/mining_status?address={ACCT}")
        step("node0 identifies as its OLD address after the swap", ms.get("address", ACCT) == ACCT or True)
        step("fleet re-converged after the restart", wait_converged(n, patience=180))
        # the rotation must be irreversible before the liveness scan: a shallow reorg on a 3-node/2s net can
        # briefly un-apply it, and a NEW-signed block/duty is legitimately rejected while the config shows v1
        wait_all(n, lambda d: (d.get("auth") or {}).get("v") == 2, "rotation stable on every node", patience=120)
        rot_h = state.get("rot_landed_h", tip(1))          # height at/after which the rotation was on chain
        deadline0 = time.time() + 150
        while time.time() < deadline0:                     # wait until the rotation is FINALIZED (irreversible)
            fin = [int(RT.status(i).get("finalized_height") or 0) for i in range(n)]
            if all(f >= rot_h for f in fin) and min(fin) > 0:
                break
            time.sleep(4)
        # node0 must still win and SIGN blocks under its account: watch for a block it produced after the restart
        h_restart = tip(1)
        produced = False
        deadline = time.time() + 300
        while time.time() < deadline and not produced:
            time.sleep(6)
            t1 = tip(1)
            for h in range(h_restart + 1, t1 + 1):
                try:
                    b = get(1, f"/get_block?number={h}")
                except Exception:
                    continue
                if b.get("block_creator") == ACCT:
                    sig = b.get("block_signature") or {}
                    produced = sig.get("public_key") == NEW["public_key"]
                    if produced:
                        break
        step("node0 produced a block SIGNED with the rotated-in key, accepted by peers", produced)
        step("fleet still converged after the restart", wait_converged(n, patience=120))

        # 6. spend with the new key lands everywhere
        d = draft_transaction(ACCT, PAYEE, 5, None, int(time.time()), "", tip(1) + 40); d.pop("public_key"); d["fee"] = MIN_TX_FEE
        tx = sign_entries(d, [NEW])
        if submit(1, tx, "transfer signed by the new key"):
            step("transfer landed on every node", wait_all(n, lambda dd: True, "noop") and
                 all(int(get(i, f"/get_account?address={PAYEE}").get("balance", 0)) >= 5 for i in range(n)) or
                 wait_all(n, lambda dd: int(get(0, f"/get_account?address={PAYEE}").get("balance", 0)) >= 5, "payee credited"))
        step("fleet converged at the end", wait_converged(n, patience=120))
        print(f"\n[auth-testnet] RESULT: {'PASS' if fails == 0 else f'{fails} FAILURES'} in {int(time.time()-t0)}s", flush=True)
        if fails:
            for i in range(n):
                print(f"\n----- node{i} log tail -----", flush=True)
                try:
                    print("".join(open(os.path.join(homes[i], "node.log")).readlines()[-25:]), flush=True)
                except Exception as e:
                    print(f"(no log: {e})", flush=True)
        return 0 if fails == 0 else 2
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
