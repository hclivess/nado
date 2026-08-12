"""Generate real exec-call load on a LIVE chain: N calls to faucet.fund(), which requires only value > 0.

Written to produce a busy span for tools/bench_settle_fri.py, because betanet-2 has long stretches with
zero contract traffic and a zero-call span cannot measure anything call-dependent.

THE SENDER MUST HAVE A BRIDGE BALANCE. A native call value escrows from the EXEC-side bridge balance
(settlement_proofs: `bridge.get(caller,0) < value` -> the chain SKIPS the call), not from L1. Calls sent
without one are accepted by L1, land in the DA calldata, and are then no-ops -- and the settle prover
REFUSES the whole span ("sender cannot cover the native call value ... the span is unprovable"). Fund
first with construct_bridge_deposit_tx, confirm the credit in a stash, then run this.

Every call is a genuine on-chain blob tx, so it lands in the DA calldata the settle prover reads.
faucet.fund is chosen because it takes no args, cannot revert for a funded sender, and the value
tops up the faucet prize bank rather than being burned.
"""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, "/srv/nado-home/nado")
from ops.key_ops import load_keys
from ops.transaction_ops import construct_blob_tx
from protocol import MIN_TX_FEE, TX_INCLUSION_DELAY

L1 = "http://127.0.0.1:9173"
VALUE = 10 ** 5              # 0.00001 NADO per call — enough to satisfy value>0, trivial in total
N = int(sys.argv[1]) if len(sys.argv) > 1 else 60
GAP = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0


def get(p):
    with urllib.request.urlopen(L1 + p, timeout=15) as r:
        return json.loads(r.read().decode())


def post(p, body):
    req = urllib.request.Request(L1 + p, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


keys = load_keys()
start_tip = int(get("/get_latest_block")["block_number"])
print(f"sender {keys['address']} | start tip {start_tip} | submitting {N} faucet.fund calls", flush=True)
ok = bad = 0
for i in range(N):
    tip = int(get("/get_latest_block")["block_number"])
    payload = {"op": "call", "contract": "faucet", "method": "fund", "args": [], "value": VALUE}
    tx = construct_blob_tx(keys, payload, max_block=tip + 20, fee=MIN_TX_FEE,
                           min_block=tip + TX_INCLUSION_DELAY)
    try:
        r = post("/submit_transaction", tx)
        good = "txid" in json.dumps(r) or "success" in json.dumps(r).lower()
        ok += good
        bad += (not good)
        if i % 10 == 0 or not good:
            print(f"  [{i:>3}] tip={tip} {json.dumps(r)[:120]}", flush=True)
    except Exception as e:
        bad += 1
        print(f"  [{i:>3}] ERROR {type(e).__name__}: {str(e)[:120]}", flush=True)
    time.sleep(GAP)
end_tip = int(get("/get_latest_block")["block_number"])
print(f"done: {ok} accepted, {bad} rejected | blocks {start_tip}..{end_tip}", flush=True)
