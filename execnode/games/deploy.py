"""
Deploy the ported zkVM game contracts to a live NADO node (doc/zk-execution-proofs.md). Builds each game's
{code, abi(+_view)} from execnode/games/<name>.py, submits a signed `deploy` blob (runtime=zkvm) to L1, and
prints the deterministic contract id the exec node will assign — which goes into the game's static/<name>.js
`const CID`. Idempotent per (deployer,code,nonce): re-running with the same nonce is a no-op once mined.

Usage (HOME points at the wallet dir with keys.dat):
  HOME=/root python3 -m execnode.games.deploy coinflip [dice roulette ...]   [--l1 URL] [--nonce N]
  HOME=/root python3 -m execnode.games.deploy --all
"""
import argparse
import base64
import importlib
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import zstandard
from ops.transaction_ops import construct_blob_tx
from ops.key_ops import load_keys
from protocol import MIN_TX_FEE, TX_INCLUSION_DELAY
from execnode.state import ExecState

GAMES = ["coinflip", "dice", "roulette", "mines", "slots", "reversi", "connect4", "tictactoe",
         "farkle", "chess", "blackjack", "bet", "battleship", "pets", "holdem", "stormhold"]


def _codez(code):
    raw = json.dumps(code, separators=(",", ":"), sort_keys=True).encode()
    return base64.b64encode(zstandard.ZstdCompressor(level=19).compress(raw)).decode()


def _get(l1, path):
    with urllib.request.urlopen(l1 + path, timeout=15) as r:
        return json.loads(r.read().decode())


def _post(l1, path, body):
    req = urllib.request.Request(l1 + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def deploy_one(name, l1, nonce, fee, upgrade_cid=None):
    mod = importlib.import_module(f"execnode.games.{name}")
    code = mod.build()
    abi = getattr(mod, "ABI", {})
    keys = load_keys()
    if upgrade_cid:                                        # replace an existing contract's code (deployer-only)
        payload = {"op": "upgrade", "contract": upgrade_cid, "codez": _codez(code)}
        cid = upgrade_cid
    else:
        payload = {"op": "deploy", "runtime": "zkvm", "codez": _codez(code), "nonce": nonce}
        cid = ExecState.contract_id(ExecState.__new__(ExecState), keys["address"], code, nonce)
    if abi:
        payload["abi"] = abi
    tip = int(_get(l1, "/get_latest_block")["block_number"])
    tx = construct_blob_tx(keys, payload, max_block=tip + 20, fee=fee, min_block=tip + TX_INCLUSION_DELAY)
    res = _post(l1, "/submit_transaction", tx)
    ok = isinstance(res, dict) and res.get("result")
    verb = "upgrade" if upgrade_cid else "deploy"
    print(f"{name}: {verb} tx {tx['txid'][:16]}… {'submitted' if ok else res} -> cid {cid}")
    return name, cid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("games", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--l1", default=os.environ.get("NADO_L1_URL", "http://127.0.0.1:9173").rstrip("/"))
    ap.add_argument("--nonce", default="a5")
    ap.add_argument("--fee", type=int, default=MIN_TX_FEE)
    ap.add_argument("--upgrade", default=None, help="cid to upgrade in place (single game only)")
    a = ap.parse_args()
    names = GAMES if a.all else a.games
    if not names:
        print("specify game names or --all"); return
    out = {}
    for n in names:
        try:
            _, cid = deploy_one(n, a.l1, a.nonce, a.fee, upgrade_cid=a.upgrade if len(names) == 1 else None)
            out[n] = cid
        except Exception as e:
            print(f"{n}: FAILED {e}")
    print("\nCIDs:")
    for n, cid in out.items():
        print(f'  {n}: const CID = "{cid}";')


if __name__ == "__main__":
    main()
