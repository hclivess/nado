"""
Deploy or upgrade a GAME contract straight from its module (execnode/games/<name>.py) — assembles
build(), attaches the module's ABI (including the _view schema the frontend needs), compresses, signs
and submits in one step. This is the missing piece next to execnode/submit_blob.py, which only ships a
bare code JSON with no ABI.

  HOME=/root python scripts/deploy_game.py <name>                 # fresh deploy, echoes the future cid
  HOME=/root python scripts/deploy_game.py <name> --upgrade <cid> # in-place code+abi swap (deployer key)
"""
import argparse
import base64
import importlib
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import zstandard
from ops.transaction_ops import construct_blob_tx
from ops.key_ops import load_keys
from protocol import MIN_TX_FEE, TX_INCLUSION_DELAY


def _get(l1, path):
    with urllib.request.urlopen(l1 + path, timeout=15) as r:
        return json.loads(r.read().decode())


def _post(l1, path, body):
    req = urllib.request.Request(l1 + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="module under execnode/games/ exposing build() and ABI")
    ap.add_argument("--upgrade", default=None, help="existing cid to upgrade in place")
    ap.add_argument("--l1", default=os.environ.get("NADO_L1_URL", "http://127.0.0.1:9173").rstrip("/"))
    ap.add_argument("--fee", type=int, default=MIN_TX_FEE)
    args = ap.parse_args()

    mod = importlib.import_module(f"execnode.games.{args.name}")
    code = mod.build()
    raw = json.dumps(code, separators=(",", ":"), sort_keys=True).encode()
    codez = base64.b64encode(zstandard.ZstdCompressor(level=19).compress(raw)).decode()

    if args.upgrade:
        payload = {"op": "upgrade", "contract": args.upgrade, "codez": codez,
                   "runtime": "zkvm", "abi": mod.ABI}
    else:
        payload = {"op": "deploy", "codez": codez, "nonce": os.urandom(6).hex(),
                   "runtime": "zkvm", "abi": mod.ABI}

    keys = load_keys()
    # Re-derive the sender from the PUBKEY under the current ADDRESS_PREFIX, rather than trusting the address
    # cached in the keyfile. Across a debrand/prefix cutover (alphanet-7: ndo… → mldsa44…) the keyfile can hold
    # a STALE address string while the funded account lives under the re-rolled current-prefix address — signing
    # with the stale one is rejected "Empty account". make_address is deterministic, so this is a no-op when the
    # stored address is already current.
    from ops.address_ops import make_address
    keys["address"] = make_address(keys["public_key"])
    tip = int(_get(args.l1, "/get_latest_block")["block_number"])
    tx = construct_blob_tx(keys, payload, max_block=tip + 20, fee=args.fee,
                           min_block=tip + TX_INCLUSION_DELAY)
    print(f"submitting {payload['op']} blob tx {tx['txid'][:16]}… → {args.l1}")
    print(json.dumps(_post(args.l1, "/submit_transaction", tx), indent=2))
    if not args.upgrade:
        from execnode.state import ExecState
        cid = ExecState.contract_id(ExecState.__new__(ExecState), keys["address"], code, payload["nonce"])
        print(f"contract id (once mined): {cid}")


if __name__ == "__main__":
    main()
