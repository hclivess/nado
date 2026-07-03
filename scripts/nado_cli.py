#!/usr/bin/env python3
"""
NADO CLI — every wallet/interface operation from the terminal, authenticated by your local keys.dat.

Design (lean + secure): each command just builds the SAME signed transaction the web interface builds
(reusing ops.transaction_ops.construct_* / create_transaction), then POSTs it to the node's existing public
`/submit_transaction`. The private key never leaves this process and there is NO new signing endpoint or trust
surface — the node validates a CLI tx exactly like a browser one (signature, PoSW, fees, quorum, …).

    python3 scripts/nado_cli.py <cmd> ...       # HOME=<node data home> selects private/keys.dat
    python3 scripts/nado_cli.py --node http://127.0.0.1:9173 send ndo… 12.5

Commands: info · send · register · bond · unbond · alias · propose · vote · execute · collect · bridge-deposit
"""
import argparse, json, os, sys, time, urllib.request
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops.key_ops import load_keys, keyfile_found
from ops import transaction_ops as T
from ops import posw
from config import get_timestamp_seconds
from hashing import create_nonce
from protocol import CHAIN_ID, MIN_TX_FEE, POSW_T, POSW_S, POSW_K, POSW_ANCHOR_OFFSET

DEC = 10 ** 10  # NADO has 10 decimals
MARGIN = 6      # target_block headroom: small so the tx lands in its exact target block (the node's own txs
                # use +2..+5); this also keeps the register PoSW anchor (target-30) in a settled epoch.


def raw(nado):            # "12.5" NADO -> raw int
    return int((Decimal(str(nado)) * DEC).to_integral_value())


def _get(node, path):
    with urllib.request.urlopen(node + path, timeout=20) as r:
        return json.load(r)


def _submit(node, tx):
    data = json.dumps(tx).encode()
    req = urllib.request.Request(node + "/submit_transaction", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        out = json.load(r)
    ok = bool(out.get("result")) if isinstance(out, dict) else False
    print(("✓ " if ok else "✗ ") + json.dumps(out)[:300])
    print("txid:", tx.get("txid"))
    return ok


def _tip(node):
    return int(_get(node, "/get_latest_block")["block_number"])


def _draft(kd, recipient, amount, data, target_block):
    return {"sender": kd["address"], "recipient": recipient, "amount": int(amount),
            "timestamp": get_timestamp_seconds(), "data": data, "nonce": create_nonce(),
            "public_key": kd["public_key"], "target_block": int(target_block), "chain_id": CHAIN_ID}


# ---- commands ------------------------------------------------------------------------------------
def c_info(kd, node, a):
    acc = _get(node, "/get_account?address=" + kd["address"])
    ms = _get(node, "/mining_status")
    print("address  ", kd["address"])
    print("balance  ", Decimal(acc.get("balance", 0)) / DEC, "NADO   bonded", Decimal(acc.get("bonded", 0)) / DEC)
    print("registered", acc.get("registered", 0), " present", ms.get("registered_present"),
          " open_weight", ms.get("my_open_weight"), " bonded_shares", ms.get("my_bonded_shares"))


def c_send(kd, node, a):
    tx = T.create_transaction(_draft(kd, a.to, raw(a.amount), a.memo or "", _tip(node) + MARGIN),
                              kd["private_key"], raw(a.fee) if a.fee else MIN_TX_FEE)
    _submit(node, tx)


def c_bond(kd, node, a):
    _submit(node, T.construct_bond_tx(kd, raw(a.amount), MIN_TX_FEE, _tip(node) + MARGIN))


def c_unbond(kd, node, a):
    _submit(node, T.construct_unbond_tx(kd, raw(a.amount), _tip(node) + MARGIN))


def c_alias(kd, node, a):
    _submit(node, T.construct_alias_tx(kd, a.op, a.name, _tip(node) + MARGIN, MIN_TX_FEE, to=a.to))


def c_collect(kd, node, a):
    # presence-dividend collection: a blob op the exec node accrues + settles (doc/presence-dividend.md)
    _submit(node, T.construct_blob_tx(kd, {"op": "collect_dividend"}, _tip(node) + MARGIN, MIN_TX_FEE))


def c_register(kd, node, a):
    tb = _tip(node) + MARGIN
    anchor_num = max(0, tb - POSW_ANCHOR_OFFSET)
    anchor = _get(node, "/get_block_number?number=%d" % anchor_num).get("block_hash")
    if not anchor:
        sys.exit("no anchor block %d yet" % anchor_num)
    req_t = POSW_T
    try:
        req_t = int(_get(node, "/posw_difficulty").get("required_t", POSW_T))
    except Exception:
        pass
    print("proving PoSW (T=%d, ~sequential) …" % req_t)
    proof = posw.prove(posw.challenge_bytes(kd["address"], anchor), T=req_t, S=POSW_S, k=POSW_K)
    _submit(node, T.construct_register_tx(kd, tb, proof))


def _spend(a):   # shared treasury spend fields
    return dict(recipient=a.to, amount=raw(a.amount), memo=a.memo or "", nonce=a.nonce, expiry=int(a.expiry))


def c_propose(kd, node, a):   # propose == cast a 'yes' vote that also opens the proposal (matches the web UI)
    s = _spend(a)
    _submit(node, T.construct_treasury_vote_tx(kd, s["recipient"], s["amount"], s["memo"], s["nonce"],
                                               _tip(node) + MARGIN, s["expiry"], choice="yes"))


def c_vote(kd, node, a):
    s = _spend(a)
    _submit(node, T.construct_treasury_vote_tx(kd, s["recipient"], s["amount"], s["memo"], s["nonce"],
                                               _tip(node) + MARGIN, s["expiry"], choice=a.choice))


def c_execute(kd, node, a):
    s = _spend(a)
    _submit(node, T.construct_treasury_execute_tx(kd, s["recipient"], s["amount"], s["memo"], s["nonce"],
                                                  _tip(node) + MARGIN, s["expiry"]))


def c_bridge_deposit(kd, node, a):
    _submit(node, T.construct_bridge_deposit_tx(kd, raw(a.amount), _tip(node) + MARGIN, MIN_TX_FEE))


def main():
    p = argparse.ArgumentParser(prog="nado_cli", description="NADO wallet ops from the terminal (signs with keys.dat).")
    p.add_argument("--node", default=os.environ.get("NADO_NODE", "http://127.0.0.1:9173"), help="node base URL")
    p.add_argument("--keys", default=None, help="path to keys.dat (default: $HOME/nado/private/keys.dat)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info")
    s = sub.add_parser("send"); s.add_argument("to"); s.add_argument("amount"); s.add_argument("--memo"); s.add_argument("--fee")
    s = sub.add_parser("bond"); s.add_argument("amount")
    s = sub.add_parser("unbond"); s.add_argument("amount")
    s = sub.add_parser("alias"); s.add_argument("op", choices=["register", "transfer", "unregister"]); s.add_argument("name"); s.add_argument("--to")
    sub.add_parser("register")
    sub.add_parser("collect")
    for name in ("propose", "vote", "execute"):
        s = sub.add_parser(name); s.add_argument("--to", required=True); s.add_argument("--amount", required=True)
        s.add_argument("--memo", default=""); s.add_argument("--nonce", required=True); s.add_argument("--expiry", required=True)
        if name == "vote": s.add_argument("--choice", choices=["yes", "no"], default="yes")
    s = sub.add_parser("bridge-deposit"); s.add_argument("amount")

    a = p.parse_args()
    kf = a.keys or None
    if kf and not os.path.exists(kf):
        sys.exit("keys.dat not found: " + kf)
    if not kf and not keyfile_found():
        sys.exit("no keys.dat — start a node once (or pass --keys) to generate one.")
    kd = load_keys(kf) if kf else load_keys()

    cmds = {"info": c_info, "send": c_send, "bond": c_bond, "unbond": c_unbond, "alias": c_alias,
            "register": c_register, "collect": c_collect, "propose": c_propose, "vote": c_vote,
            "execute": c_execute, "bridge-deposit": c_bridge_deposit}
    cmds[a.cmd](kd, a.node.rstrip("/"), a)


if __name__ == "__main__":
    main()
