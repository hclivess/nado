#!/usr/bin/env python3
"""LIVE end-to-end of the otc order book on the running chain (doc/dex-bridge.md §13 phase 1 acceptance).

Uses the node operator's key as the MAKER and a freshly generated, freshly funded key as the TAKER; drives
post -> fill -> settle (ASK_NADO, dual-hashlock preimage) plus post -> cancel with ~0.05 NADO, verifying
every transition and every escrow move through the exec node's HTTP API. Foreign leg refs are placeholder
strings (the BTC side is phase 2); everything NADO-side is the real deployed contract.

Run: HOME=/srv/nado-home python3 scripts/testnet/otc_live_e2e.py
"""
import hashlib
import json
import os
import secrets as pysecrets
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from ops.key_ops import load_keys                                              # noqa: E402
from ops.transaction_ops import (draft_transaction, create_transaction,        # noqa: E402
                                 construct_blob_tx, construct_bridge_deposit_tx)
from signatures import generate_keydict                                        # noqa: E402
from protocol import MIN_TX_FEE, CHAIN_ID, TX_INCLUSION_DELAY                  # noqa: E402
from execnode.games import otc as O                                            # noqa: E402

L1, EX = "http://127.0.0.1:9173", "http://127.0.0.1:9273"
OTC = "1652698f36b2741fa622e1973fe1b157"
AMT = 500_000_000                    # 0.05 NADO
passed = failed = 0


def ok(c, m):
    global passed, failed
    if c: passed += 1; print(f"  ok   {m}", flush=True)
    else: failed += 1; print(f"  FAIL {m}", flush=True)


def get(u):
    with urllib.request.urlopen(u, timeout=10) as r:
        return json.loads(r.read().decode())


def post_json(u, body):
    req = urllib.request.Request(u, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"result": False, "message": e.read().decode()[:200]}


def l1_balance(addr):
    try:                                  # /get_account 404s for an address the chain has never seen
        return int((get(L1 + f"/get_account?address={addr}") or {}).get("balance", 0))
    except Exception:
        return 0


def tip():
    return int(get(L1 + "/get_latest_block")["block_number"])


def bridge():
    return get(EX + f"/exec/bridge?ns=default&provisional=1").get("balances", {})


def sto():
    return get(EX + f"/exec/contract?ns=default&cid={OTC}&provisional=1").get("storage", {})


def row(o):
    s = sto()
    g = lambda m: (s.get(m) or {}).get(str(o))
    return {k: g(k) for k in ("mk", "st", "esc", "namt", "maker", "taker", "hvm", "expn", "fref")}


def submit(kd, payload, value_note):
    t = tip()
    tx = construct_blob_tx(kd, payload, max_block=t + 40, fee=MIN_TX_FEE, min_block=t + TX_INCLUSION_DELAY)
    r = post_json(L1 + "/submit_transaction", tx)
    assert r.get("result"), f"relay refused {value_note}: {r.get('message')}"
    return tx


def wait(fn, label, patience=200):
    d = time.time() + patience
    while time.time() < d:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(3)
    print(f"  TIMEOUT waiting: {label}", flush=True)
    return False


def main():
    op = load_keys()
    print(f"[e2e] maker (operator): {op['address']}", flush=True)
    # --- taker: fresh key, L1-funded by the operator, then bridge-deposited into exec ---------------
    keyfile = os.path.expanduser("~/nado/private/otc_e2e_taker.json")
    if os.path.exists(keyfile):
        tk = json.load(open(keyfile))
    else:
        tk = generate_keydict()
        fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(tk, f)
    print(f"[e2e] taker: {tk['address']} (persisted at {keyfile})", flush=True)
    if int(bridge().get(tk["address"], 0)) < 2 * 10 ** 9:
        t = tip()
        if l1_balance(tk['address']) < 3 * 10 ** 9:
            d = draft_transaction(op["address"], tk["address"], 3 * 10 ** 9, op["public_key"], int(time.time()), "", t + 40)
            d["chain_id"] = CHAIN_ID
            r = post_json(L1 + "/submit_transaction", create_transaction(d, op["private_key"], MIN_TX_FEE))
            assert r.get("result"), f"taker funding refused: {r.get('message')}"
            ok(wait(lambda: l1_balance(tk['address']) >= 3 * 10 ** 9,
                    "taker L1 funded", 300), "taker L1 funded (0.3 NADO)")
        r = post_json(L1 + "/submit_transaction",
                      construct_bridge_deposit_tx(tk, 2 * 10 ** 9, tip() + 40, MIN_TX_FEE))
        assert r.get("result"), f"taker deposit refused: {r.get('message')}"
    ok(wait(lambda: int(bridge().get(tk["address"], 0)) >= 2 * 10 ** 9, "taker exec deposit", 420),
       "taker exec balance credited (0.2 NADO)")
    if int(bridge().get(op["address"], 0)) < 2 * AMT:                 # the maker needs exec balance too
        r = post_json(L1 + "/submit_transaction",
                      construct_bridge_deposit_tx(op, 2 * 10 ** 9, tip() + 40, MIN_TX_FEE))
        assert r.get("result"), f"maker deposit refused: {r.get('message')}"
        ok(wait(lambda: int(bridge().get(op["address"], 0)) >= 2 * AMT, "maker exec deposit", 420),
           "maker exec balance credited")

    maker_x0, taker_x0 = int(bridge().get(op["address"], 0)), int(bridge().get(tk["address"], 0))
    assert maker_x0 >= 2 * AMT, f"operator exec balance {maker_x0} too low — deposit first"

    # --- post -> fill -> settle (ASK: maker sells NADO, taker 'pays BTC' and takes the escrow) ------
    s_hex = pysecrets.token_hex(32)
    o = int.from_bytes(pysecrets.token_bytes(4), "big") or 7
    hsha = hashlib.sha256(bytes.fromhex(s_hex)).hexdigest()
    hi, lo = O.vm_hashlock_parts(s_hex)
    expn = tip() + 600
    submit(op, {"op": "call", "contract": OTC, "method": "post",
                "args": [o, O.ASK, AMT, "btc", "0.0001", "bc1q-e2e-maker", hsha, hi, lo, expn, 999_999],
                "value": AMT}, "post")
    ok(wait(lambda: row(o)["st"] == 1, "order open"), f"posted ASK #{o} (0.05 NADO escrowed)")
    ok(int(row(o)["esc"] or 0) == AMT, "escrow recorded")
    submit(tk, {"op": "call", "contract": OTC, "method": "fill",
                "args": [o, "bc1q-e2e-taker-refund", "btc:e2e:lockref"]}, "fill")
    ok(wait(lambda: row(o)["st"] == 2, "order filled"), "taker filled")
    submit(tk, {"op": "call", "contract": OTC, "method": "settle",
                "args": [o] + O.preimage_limbs(s_hex)}, "settle")
    ok(wait(lambda: row(o)["st"] == 3, "order settled"), "settled with the preimage")
    ok(wait(lambda: int(bridge().get(tk["address"], 0)) == taker_x0 + AMT, "taker paid"),
       "escrow paid to the taker, exactly")
    limbs = [int((sto().get(f"s{i}") or {}).get(str(o), 0)) for i in range(5)]
    ok(limbs == O.preimage_limbs(s_hex), "revealed limbs readable (foreign-leg claim data)")

    # --- post -> cancel ------------------------------------------------------------------------------
    o2 = int.from_bytes(pysecrets.token_bytes(4), "big") or 9
    s2 = pysecrets.token_hex(32)
    hi2, lo2 = O.vm_hashlock_parts(s2)
    submit(op, {"op": "call", "contract": OTC, "method": "post",
                "args": [o2, O.ASK, AMT, "eth", "0.001", "0xe2e", hashlib.sha256(bytes.fromhex(s2)).hexdigest(),
                         hi2, lo2, tip() + 600, 999_999], "value": AMT}, "post2")
    ok(wait(lambda: row(o2)["st"] == 1, "order2 open"), f"posted ASK #{o2}")
    submit(op, {"op": "call", "contract": OTC, "method": "cancel", "args": [o2]}, "cancel")
    ok(wait(lambda: row(o2)["st"] == 5, "order2 cancelled"), "cancelled")
    maker_x1 = int(bridge().get(op["address"], 0))
    ok(maker_x1 == maker_x0 - AMT, f"maker net = exactly the settled swap (Δ {maker_x1 - maker_x0})")

    print(f"\n[e2e] {passed} passed, {failed} failed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
