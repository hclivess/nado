#!/usr/bin/env python3
"""Post a cross-chain order on the otc book from this box's operator key, headless.

  HOME=/srv/nado-home python3 scripts/otc_post.py --kind bid --net eth --nado 0.0046 --foreign 0.000265 \
      --addr 0x406Ed37679f237EA099985D8C9CE96B538F916b0 [--days 3]

kind ask = sell NADO for the foreign coin (maker locks NADO first); bid = buy NADO with the foreign coin
(maker locks the foreign coin first). --addr is the maker's address on the foreign network: where an ASK
maker receives, and the address a BID maker funds the foreign lock FROM (its refundee).

THE SECRET GOES TO DISK BEFORE THE ORDER IS POSTED (private/otc_position_<oid>.json): whoever completes
the maker's side later — this box's CLI, or a browser that imports the record — needs it. §6.3 is
kind-dependent: an ASK's foreign deadline sits inside the NADO window, a BID's sits past it."""
import argparse, hashlib, json, os, sys, time, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ops.key_ops import load_keys                                          # noqa: E402
from ops.transaction_ops import construct_blob_tx                          # noqa: E402
from protocol import MIN_TX_FEE, TX_INCLUSION_DELAY                        # noqa: E402
from execnode.games import otc as O                                        # noqa: E402

L1, EX = "http://127.0.0.1:9173", "http://127.0.0.1:9273"
OTC = "6bb0bd0d5dad478bb33d254e73cde85d"


def get(u):
    with urllib.request.urlopen(u, timeout=15) as r:
        return json.loads(r.read().decode())


def post_json(u, body):
    rq = urllib.request.Request(u, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(rq, timeout=25) as r:
        return json.loads(r.read().decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["ask", "bid"], required=True)
    ap.add_argument("--net", required=True, help="network key as the dex names it: btc, btct, eth, eths, sol, sold (token: net|address)")
    ap.add_argument("--nado", required=True, help="NADO amount, e.g. 0.0046")
    ap.add_argument("--foreign", required=True, help="foreign amount as a decimal string, e.g. 0.000265")
    ap.add_argument("--addr", required=True, help="your address on the foreign network")
    ap.add_argument("--days", type=float, default=3.0, help="NADO-side expiry in days (6 s blocks)")
    a = ap.parse_args()
    maker = load_keys()
    tip = int(get(L1 + "/get_latest_block")["block_number"])
    blocks = int(a.days * 86400 / O.BLOCK_SECS)
    expn = tip + blocks
    now = int(time.time()); win = blocks * O.BLOCK_SECS
    if a.kind == "ask":
        expf = now + (O.FOREIGN_MIN_S + win - O.FOREIGN_MARGIN_S) // 2
    else:
        expf = now + win + O.FOREIGN_MARGIN_S + 3600
        if expf > now + 29 * 86400:
            sys.exit("a BID's foreign deadline must outlast the NADO window and stay under the foreign templates' 30 days — shorten --days")
    s_hex = os.urandom(32).hex(); H = hashlib.sha256(bytes.fromhex(s_hex)).hexdigest()
    oid = int.from_bytes(os.urandom(4), "big") or 7
    namt = int(round(float(a.nado) * 10 ** 10))
    rec = os.path.join(ROOT, "private", f"otc_position_{oid}.json")
    with open(os.open(rec, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
        json.dump({"oid": oid, "kind": a.kind, "secret": s_hex, "hashlock": H, "net": a.net, "nado": a.nado, "foreign": a.foreign,
                   "addr": a.addr, "expn": expn, "expf": expf, "maker": maker["address"], "posted": now}, f)
    kind = O.ASK if a.kind == "ask" else O.BID
    payload = {"op": "call", "contract": OTC, "method": "post",
               "args": [oid, kind, namt, a.net, a.foreign, a.addr, H, *O.vm_hashlock_parts(s_hex), expn, expf]}
    tx = construct_blob_tx(maker, payload, max_block=tip + 40, fee=MIN_TX_FEE, min_block=tip + TX_INCLUSION_DELAY)
    r = post_json(L1 + "/submit_transaction", tx)
    if not r.get("result"):
        sys.exit(f"relay refused the post: {r.get('message')}")
    print(json.dumps({"order": oid, "kind": a.kind, "nado": a.nado, "foreign": a.foreign, "net": a.net, "expn": expn, "expf": expf,
                      "txid": tx["txid"], "record": rec, "market_url": f"https://dex.nadochain.com/?market={'ETH' if a.net == 'eth' else a.net}&mode=cross"}, indent=2))


if __name__ == "__main__":
    main()
