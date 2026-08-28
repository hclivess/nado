#!/usr/bin/env python3
"""otc_watchtower.py — the permissionless relayer for the OTC cross-chain order book (dex-bridge §10, phase 4).

Watches the deployed `otc` contract and does the two things a swap party shouldn't have to stay online for —
both already permissionless in the contract, so ANYONE may run this:

  * EXPIRE SWEEP — any order at/past its refund height is expired, releasing the maker's collateral to the
    party the contract names (never to this tower) and closing the row. NOTE the swap PRINCIPAL is not in
    this contract: a cross-chain swap's NADO leg is an L1 HTLC, refunded with `htlc_refund` by its own
    sender, so sweeping here settles the order's collateral and tips, not the trade.
  * SETTLE RELAY — for a FILLED order it scans new Bitcoin blocks (via a bitcoin-cli you point it at) for a
    claim witness whose SHA-256 matches the order's hashlock: the revealed secret is re-posted as
    settle(o, limbs), paying the RECORDED party (never the caller). A taker who went offline after the maker
    claimed still receives their NADO. `--secrets FILE` ({orderId: 64-hex}) settles from known secrets too.

SAFETY (this posts transactions): DRY-RUN by default — prints what it WOULD post and submits nothing. Add
--submit to post (fees come from $HOME's keys.dat; the tower earns nothing on-chain — §8 bounty economics
are phase 5). One pass per invocation; --loop SECONDS keeps it running.

Usage:
    HOME=/srv/nado-home python3 scripts/otc_watchtower.py scan                      # dry-run one pass
    HOME=/srv/nado-home python3 scripts/otc_watchtower.py scan --submit --loop 60   # the real daemon
        [--l1 URL] [--exec URL] [--cid CID] [--btc-cli "bitcoin-cli -rpcwait ..."] [--secrets FILE]
        [--sol-rpc URL --sol-program ID]
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import otc_btc_leg as B                                            # noqa: E402  (extract_secret)

OTC_METHODS = {"post", "fill", "settle", "expire"}                 # the shape that identifies the contract
CLIENT_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "dex.js")
OPEN, FILLED = 1, 2
LIMB_BITS, LIMBS = 52, 5                                           # must match execnode/games/otc.py


def _get(url, timeout=15):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _post(url, body, timeout=20):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ---- discovery (bet_oracle pattern: tried in order, loud on total failure — never a stale constant) ------
def _has_shape(exec_url, cid):
    try:
        c = _get(f"{exec_url}/exec/contract?ns=default&cid={cid}")
        return bool(c) and OTC_METHODS.issubset(set(c.get("methods") or []))
    except Exception:
        return False


def resolve_cid(exec_url, explicit=None):
    tried = []
    cids = [("--cid", explicit)]
    try:
        m = re.search(r'const\s+OTC_CID\s*=\s*"([0-9a-f]{32})"', open(CLIENT_JS).read())
        cids.append(("static/dex.js", m.group(1) if m else None))
    except Exception:
        pass
    for src, cid in cids:
        if not cid:
            continue
        tried.append(f"{src}={cid}")
        if _has_shape(exec_url, cid):
            return cid
    for c in (_get(f"{exec_url}/exec/contracts?ns=default").get("contracts") or []):
        if OTC_METHODS.issubset(set(c.get("methods") or [])):
            return c["cid"]
    raise SystemExit(f"no otc contract found (tried {tried} + a method-shape sweep)")


# ---- the pure core (unit-tested in tests/test_otc_watchtower.py) -----------------------------------------
def parse_orders(storage):
    """decode_view maps -> a list of order dicts (ints where the tower compares, strings where it matches)."""
    g = lambda m: storage.get(m) or {}
    out = []
    for o in g("mk"):
        out.append({"o": int(o), "kind": int(g("kind").get(o) or 0), "st": int(g("st").get(o) or 0),
                    "expn": int(g("expn").get(o) or 0), "esc": int(g("esc").get(o) or 0),
                    "hsha": str(g("hsha").get(o) or ""), "wch": str(g("wch").get(o) or ""),
                    "bnty": int(g("bnty").get(o) or 0), "pheld": int(g("pheld").get(o) or 0)})
    return out


def expire_candidates(orders, cursor):
    """Orders whose refund window is open: open/filled, at/past expn. Rows holding nothing are skipped —
    expiring them only tidies state and burns our fee."""
    live = [x for x in orders
            if x["st"] in (OPEN, FILLED) and cursor >= x["expn"]
            and (x["esc"] or x["bnty"] or x["pheld"])]
    return [x["o"] for x in sorted(live, key=lambda x: -x["bnty"])]   # §8: the paying work first


def watch_candidates(orders, cursor):
    """FILLED HTLC orders still inside the claim window, with a well-formed hashlock: (o, H_hex)."""
    return [(x["o"], x["hsha"].lower()) for x in orders
            if x["st"] == FILLED and x["kind"] in (1, 2) and cursor < x["expn"]
            and re.fullmatch(r"[0-9a-fA-F]{64}", x["hsha"] or "")]


def scan_txs(tx_hexes, watches):
    """{orderId: secret_hex} for every watched hashlock revealed by any of these transactions."""
    found = {}
    for o, H in watches:
        if o in found:
            continue
        Hb = bytes.fromhex(H)
        for txh in tx_hexes:
            s = B.extract_secret(txh, Hb)
            if s:
                found[o] = s
                break
    return found


def sol_claim_secrets(rpc, program, watches, state):
    """{orderId: secret} for every watched hashlock revealed by a claim in the Solana HTLC program.

    Solana needs no block walk: every transaction that touched the program is listed by address, and a
    claim carries the preimage in its instruction data (tag 1, then 32 bytes). We remember the newest
    signature seen so a later pass only reads what is new."""
    found, newest = {}, None
    want = {bytes.fromhex(H): o for o, H in watches}
    # Pages are newest-first and capped, so walk them with `before` until the page runs short — stopping
    # at the first page and remembering its top row would silently skip everything under the cap.
    before = None
    while True:
        params = {"limit": 200, "commitment": "confirmed"}
        if state.get("sol_until"):
            params["until"] = state["sol_until"]
        if before:
            params["before"] = before
        sigs = _sol_rpc(rpc, "getSignaturesForAddress", [program, params]) or []
        for row in sigs:
            if newest is None:
                newest = row.get("signature")
            if row.get("err"):
                continue
            tx = _sol_rpc(rpc, "getTransaction", [row["signature"],
                          {"encoding": "json", "commitment": "confirmed", "maxSupportedTransactionVersion": 0}])
            for ix in ((tx or {}).get("transaction", {}).get("message", {}) or {}).get("instructions", []) or []:
                d = _b58decode(ix.get("data") or "")
                if len(d) != 33 or d[0] != 1:
                    continue
                h = hashlib.sha256(d[1:]).digest()
                if h in want:
                    found[want[h]] = d[1:].hex()
        if len(sigs) < params["limit"]:
            break
        before = sigs[-1]["signature"]
    if newest:
        state["sol_until"] = newest
    return found


_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58decode(t):
    n = 0
    for ch in t:
        i = _B58.find(ch)
        if i < 0:
            return b""
        n = n * 58 + i
    out = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\x00" * (len(t) - len(t.lstrip("1"))) + out


def _sol_rpc(url, method, params):
    r = _post(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    if r.get("error"):
        raise RuntimeError(r["error"].get("message", "solana rpc error"))
    return r.get("result")


def preimage_limbs(s_hex):
    v = int(s_hex, 16)
    return [(v >> (LIMB_BITS * i)) & ((1 << LIMB_BITS) - 1) for i in range(LIMBS)]


# ---- chain I/O -------------------------------------------------------------------------------------------
def btc_block_txs(btc_cli, height):
    """Every raw tx hex in the BTC block at `height` (verbosity 2 carries the hex per tx)."""
    run = lambda *a: subprocess.run(btc_cli.split() + list(a), capture_output=True, text=True, timeout=60)
    bhash = run("getblockhash", str(height)).stdout.strip()
    blk = json.loads(run("getblock", bhash, "2").stdout)
    return [t.get("hex") for t in blk.get("tx", []) if t.get("hex")]


def submit_call(l1, method, args, label, apply_it):
    if not apply_it:
        print(f"[dry-run] would post {method}{args} — {label}. Add --submit to post.", flush=True)
        return
    from ops.transaction_ops import construct_blob_tx
    from ops.key_ops import load_keys
    from protocol import MIN_TX_FEE, TX_INCLUSION_DELAY
    tip = int(_get(f"{l1}/get_latest_block")["block_number"])
    tx = construct_blob_tx(load_keys(), {"op": "call", "contract": submit_call.cid, "method": method, "args": args},
                           max_block=tip + 40, fee=MIN_TX_FEE, min_block=tip + TX_INCLUSION_DELAY)
    r = _post(f"{l1}/submit_transaction", tx)
    print(f"{method}{args} -> {'submitted ' + tx['txid'][:16] + '…' if r.get('result') else r.get('message')}", flush=True)


def one_pass(a, state):
    cid = state.setdefault("cid", resolve_cid(a.exec, a.cid))
    submit_call.cid = cid
    c = _get(f"{a.exec}/exec/contract?ns=default&cid={cid}&provisional=1")
    orders = parse_orders(c.get("storage") or {})
    cursor = int(_get(f"{a.l1}/get_latest_block")["block_number"])
    for o in expire_candidates(orders, cursor):
        submit_call(a.l1, "expire", [o], f"refund order #{o} to its funder", a.submit)
    watches = watch_candidates(orders, cursor)
    by_id = {x["o"]: x for x in orders}
    secrets = {}
    if a.secrets and os.path.exists(a.secrets):
        known = {int(k): v for k, v in json.load(open(a.secrets)).items()}
        secrets.update({o: known[o] for o, _ in watches if o in known})
    if a.btc_cli and watches:
        run = lambda *x: subprocess.run(a.btc_cli.split() + list(x), capture_output=True, text=True, timeout=60)
        tip_b = int(run("getblockcount").stdout)
        start = state.get("btc_from", max(tip_b - a.btc_lookback, 1))
        for h in range(start, tip_b + 1):
            secrets.update(scan_txs(btc_block_txs(a.btc_cli, h), [w for w in watches if w[0] not in secrets]))
        state["btc_from"] = tip_b + 1
    if a.sol_rpc and a.sol_program:
        sol_watches = [(o, H) for o, H in watches
                       if o not in secrets and str(by_id.get(o, {}).get("wch", "")).split("|")[0].startswith("sol")]
        if sol_watches:
            secrets.update(sol_claim_secrets(a.sol_rpc, a.sol_program, sol_watches, state))
    for o, s in secrets.items():
        submit_call(a.l1, "settle", [o] + preimage_limbs(s), f"relay the revealed secret for #{o}", a.submit)
    bounty = sum(x["bnty"] for x in orders if x["st"] in (OPEN, FILLED))
    print(f"[tower] cursor {cursor}: {len(orders)} orders, {len(watches)} watched, "
          f"{len(secrets)} secrets found, {len(expire_candidates(orders, cursor))} expirable, "
          f"{bounty} raw in live bounties", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["scan"])
    ap.add_argument("--l1", default=os.environ.get("NADO_L1_URL", "http://127.0.0.1:9173").rstrip("/"))
    ap.add_argument("--exec", default=os.environ.get("NADO_EXEC_URL", "http://127.0.0.1:9273").rstrip("/"))
    ap.add_argument("--cid", default=None)
    ap.add_argument("--btc-cli", default=None, help='e.g. "bitcoin-cli -rpcwait" — enables the BTC secret scan')
    ap.add_argument("--btc-lookback", type=int, default=144, help="blocks to scan back on first run (default ~1 day)")
    ap.add_argument("--sol-rpc", default=None, help="Solana RPC URL — enables the Solana claim scan")
    ap.add_argument("--sol-program", default=None, help="the deployed HTLC program id on that cluster")
    ap.add_argument("--secrets", default=None, help="JSON file {orderId: 64-hex secret} to settle from")
    ap.add_argument("--submit", action="store_true", help="actually post (default: dry-run)")
    ap.add_argument("--loop", type=int, default=0, help="seconds between passes (0 = one pass and exit)")
    a = ap.parse_args()
    state = {}
    while True:
        try:
            one_pass(a, state)
        except SystemExit:
            raise
        except Exception as e:
            print(f"[tower] pass failed: {e}", flush=True)
        if not a.loop:
            break
        time.sleep(a.loop)


if __name__ == "__main__":
    main()
