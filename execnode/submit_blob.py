"""
CLI to submit a `blob` to L1 — build a SIGNED blob tx (deploy or call) and POST it to /submit_transaction.
The execution node then picks it up from the finalized block and runs it through the VM.

Usage (HOME must point at the wallet's data dir so keys.dat is found):
  HOME=/root/nado-solo python execnode/submit_blob.py deploy contract.json           [--l1 URL] [--fee N]
  HOME=/root/nado-solo python execnode/submit_blob.py call <cid> <method> '<args-json>' [--l1 URL] [--fee N]

`contract.json` is the {method: bytecode} object (see execnode/examples/token.json).
"""
import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops.transaction_ops import construct_blob_tx
from ops.key_ops import load_keys
from protocol import MIN_TX_FEE


def _get(l1, path):
    """GET l1+path and decode the JSON body (15s timeout)."""
    with urllib.request.urlopen(l1 + path, timeout=15) as r:
        return json.loads(r.read().decode())


def _post(l1, path, body):
    """POST `body` as JSON to l1+path and decode the JSON reply (15s timeout)."""
    req = urllib.request.Request(l1 + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def main():
    """Parse the CLI, build a signed blob tx (deploy: fresh random nonce; call: cid/method/args) targeted
    2 blocks ahead of the L1 tip, submit it, and for a deploy echo the deterministic contract id the
    execution node will assign once the blob is mined."""
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["deploy", "call"])
    ap.add_argument("rest", nargs="+")
    ap.add_argument("--l1", default=os.environ.get("NADO_L1_URL", "http://127.0.0.1:9173").rstrip("/"))
    ap.add_argument("--fee", type=int, default=MIN_TX_FEE)
    args = ap.parse_args()

    keys = load_keys()
    if args.action == "deploy":
        code = json.load(open(args.rest[0]))
        payload = {"op": "deploy", "code": code, "nonce": os.urandom(6).hex()}
    else:  # call: <cid> <method> <args-json>
        cid, method = args.rest[0], args.rest[1]
        call_args = json.loads(args.rest[2]) if len(args.rest) > 2 else []
        payload = {"op": "call", "contract": cid, "method": method, "args": call_args}

    latest = _get(args.l1, "/get_latest_block")
    target_block = int(latest["block_number"]) + 2
    tx = construct_blob_tx(keys, payload, target_block=target_block, fee=args.fee)
    print(f"submitting blob tx {tx['txid'][:16]}… (target_block {target_block}) → {args.l1}")
    print(json.dumps(_post(args.l1, "/submit_transaction", tx), indent=2))
    if args.action == "deploy":
        # echo the deterministic contract id the execution node will assign
        from execnode.state import ExecState
        cid = ExecState.contract_id(ExecState.__new__(ExecState), keys["address"], payload["code"], payload["nonce"])
        print(f"contract id (once mined): {cid}")


if __name__ == "__main__":
    main()
