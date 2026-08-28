#!/usr/bin/env python3
"""A REAL cross-chain swap: NADO (betanet L1) against ETH on ETHEREUM MAINNET, end to end, tiny.

Nothing is simulated. The NADO side runs on the live node with the live otc contract; the ETH side is
the audited HtlcEth on mainnet (0xcd8f…968f). Both parties are driven from this box:
  maker  = the operator wallet (keys.dat)      sells NADO_AMT NADO, receives ETH at a fresh address
  taker  = private/otc_e2e_taker.json           pays ETH from the deployer key, receives the NADO

  1 maker posts ASK          2 taker fills          3 maker locks NADO (L1 HTLC)   4 bind
  5 taker funds ETH (mainnet HtlcEth, key bound to hashlock+claimant+refundee+deadline+amount)
  6 maker CLAIMS the ETH -> the secret is now public on Ethereum
  7 the taker learns it the way a watchtower would (Claimed log), claims the NADO on L1, settles

Run: HOME=/srv/nado-home python3 scripts/testnet/otc_mainnet_eth_e2e.py
"""
import hashlib, json, os, subprocess, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "scripts"))
from ops.key_ops import load_keys                                          # noqa: E402
from ops.transaction_ops import construct_blob_tx, draft_transaction, create_transaction   # noqa: E402
from protocol import MIN_TX_FEE, TX_INCLUSION_DELAY, CHAIN_ID             # noqa: E402
from execnode.games import otc as O                                       # noqa: E402
import otc_watchtower as W                                                # noqa: E402

L1, EX = "http://127.0.0.1:9173", "http://127.0.0.1:9273"
OTC = "6bb0bd0d5dad478bb33d254e73cde85d"
ETH_RPC = "https://ethereum-rpc.publicnode.com"
HTLC = "0xcd8f71e75bb37f438c49a8011ae4037da5a8968f"
NADO_AMT = 10 ** 9                       # 0.1 NADO
ETH_WEI = 200_000_000_000_000            # 0.0002 ETH
ETH_STR = "0.0002"
passed = failed = 0


def ok(c, m):
    global passed, failed
    if c: passed += 1; print(f"  ok   {m}", flush=True)
    else: failed += 1; print(f"  FAIL {m}", flush=True)


def get(u):
    with urllib.request.urlopen(u, timeout=15) as r:
        return json.loads(r.read().decode())


def post_json(u, body):
    rq = urllib.request.Request(u, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(rq, timeout=25) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"result": False, "message": e.read().decode()[:200]}


def tip():
    return int(get(L1 + "/get_latest_block")["block_number"])


def wait(fn, label, secs=900):
    d = time.time() + secs
    while time.time() < d:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(4)
    print(f"  TIMEOUT: {label}", flush=True)
    return False


def sto():
    return get(EX + f"/exec/contract?ns=default&cid={OTC}&provisional=1").get("storage", {})


def order(o):
    s = sto()
    return {k: (s.get(k) or {}).get(str(o)) for k in ("st", "namt", "hid", "taker", "tadr")}


def l1_bal(a):
    try:
        return int((get(L1 + f"/get_account?address={a}") or {}).get("balance", 0))
    except Exception:
        return 0


def submit_blob(kd, payload, label):
    t = tip()
    tx = construct_blob_tx(kd, payload, max_block=t + 40, fee=MIN_TX_FEE, min_block=t + TX_INCLUSION_DELAY)
    r = post_json(L1 + "/submit_transaction", tx)
    assert r.get("result"), f"{label} refused: {r.get('message')}"
    return tx


def submit_l1(kd, recipient, amount, data, label, fee=MIN_TX_FEE):
    t = tip()
    d = draft_transaction(kd["address"], recipient, amount, kd["public_key"], int(time.time()), data, t + 40)
    d["chain_id"] = CHAIN_ID
    tx = create_transaction(d, kd["private_key"], fee)
    r = post_json(L1 + "/submit_transaction", tx)
    assert r.get("result"), f"{label} refused: {r.get('message')}"
    return tx


def eth_cli(*args):
    r = subprocess.run(["node", os.path.join(ROOT, "scripts", "otc_eth_leg.mjs"), *args], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"otc_eth_leg {args[0]}: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def eth_rpc(method, params):
    return W._sol_rpc(ETH_RPC, method, params)      # the tower's JSON-RPC helper works for any JSON-RPC


def main():
    maker = load_keys()
    taker = json.load(open(os.path.join(ROOT, "private", "otc_e2e_taker.json")))
    deployer = json.load(open(os.path.join(ROOT, "private", "eth_deployer.json")))[0]
    taker_eth_key = deployer["private_key"].replace("0x", "")
    taker_eth = deployer["address"]
    # the maker receives ETH at a fresh key, kept with the other private material
    mk_file = os.path.join(ROOT, "private", "otc_mainnet_maker_eth.json")
    if os.path.exists(mk_file):
        mk_eth = json.load(open(mk_file))
    else:
        mk_eth = eth_cli("key")
        fd = os.open(mk_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(mk_eth, f)
    maker_eth = mk_eth.get("addr") or mk_eth.get("address")
    print(f"[mainnet] maker {maker['address'][:14]}… receives ETH at {maker_eth}", flush=True)
    print(f"[mainnet] taker {taker['address'][:14]}… pays ETH from {taker_eth}", flush=True)
    ok(l1_bal(taker["address"]) >= 10 ** 8, "taker holds NADO for fees")

    s_bytes = os.urandom(32); s_hex = s_bytes.hex(); H = hashlib.sha256(s_bytes).hexdigest()
    oid = int.from_bytes(os.urandom(4), "big") or 7
    cur = tip(); expn = cur + 9000
    expf = int(time.time()) + (O.FOREIGN_MIN_S + (expn - cur) * O.BLOCK_SECS - O.FOREIGN_MARGIN_S) // 2
    # THE SECRET GOES TO DISK BEFORE ANY MONEY MOVES. The first run of this script died between the NADO
    # lock and the ETH claim; its secret died with it and both locks had to wait out their deadlines.
    rec = os.path.join(ROOT, "private", f"otc_mainnet_swap_{oid}.json")
    with open(os.open(rec, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
        json.dump({"oid": oid, "secret": s_hex, "hashlock": H, "expn": expn, "expf": expf, "maker_eth": maker_eth,
                   "taker_eth": taker_eth, "nado_amt": NADO_AMT, "eth_wei": ETH_WEI, "htlc": HTLC}, f)
    print(f"[mainnet] swap record: {rec}", flush=True)

    # 1 post
    submit_blob(maker, {"op": "call", "contract": OTC, "method": "post",
                        "args": [oid, O.ASK, NADO_AMT, "eth", ETH_STR, maker_eth, H, *O.vm_hashlock_parts(s_hex), expn, expf]}, "post")
    ok(wait(lambda: int(order(oid)["st"] or 0) == 1, "order open"), f"1. maker posted ASK #{oid}: {NADO_AMT/1e10} NADO for {ETH_STR} ETH on mainnet")
    # 2 fill
    submit_blob(taker, {"op": "call", "contract": OTC, "method": "fill", "args": [oid, taker_eth, "pending"]}, "fill")
    ok(wait(lambda: int(order(oid)["st"] or 0) == 2, "order filled"), "2. taker filled it (their ETH address is on the order)")
    # 3 lock NADO
    tbal0 = l1_bal(taker["address"])
    lock = submit_l1(maker, "htlc_lock", NADO_AMT, {"claimant": taker["address"], "hashlock": H, "expiry": tip() + 9000}, "htlc_lock")
    ok(wait(lambda: (get(L1 + f"/get_htlc?id={lock['txid']}") or {}).get("htlc"), "L1 lock landed"), f"3. maker locked {NADO_AMT/1e10} NADO in an L1 HTLC ({lock['txid'][:12]}…)")
    r0 = json.load(open(rec)); r0["l1_lock"] = lock["txid"]; json.dump(r0, open(rec, "w"))
    # 4 bind
    submit_blob(maker, {"op": "call", "contract": OTC, "method": "bind", "args": [oid, lock["txid"]]}, "bind")
    ok(wait(lambda: bool(order(oid)["hid"]), "bind landed"), "4. the L1 lock is recorded on the order")
    # the taker checks the NADO lock before spending real ETH
    h = get(L1 + f"/get_htlc?id={lock['txid']}")["htlc"]
    ok(h["claimant"] == taker["address"] and h["hashlock"] == H and int(h["amount"]) == NADO_AMT and h["status"] == "open",
       "   taker verified the NADO lock: amount, hashlock, claimant, open")
    # 5 fund ETH on MAINNET
    f = eth_cli("fund", "--rpc", ETH_RPC, "--key", taker_eth_key, "--htlc", HTLC, "--claimant", maker_eth,
                "--hash", H, "--deadline", str(expf), "--value", str(ETH_WEI))
    print(f"     mainnet fund tx {f.get('txid', f)}", flush=True)
    shown = None
    ok(wait(lambda: (lambda s: s.get("matchesTerms") and (globals().__setitem__('shown', s) or True))(
        eth_cli("show", "--rpc", ETH_RPC, "--htlc", HTLC, "--hash", H, "--claimant", maker_eth, "--refundee", taker_eth,
                "--deadline", str(expf), "--value", str(ETH_WEI))), "ETH lock visible", 600),
       f"5. taker locked {ETH_STR} ETH on Ethereum mainnet under the exact terms (key {str((shown or {}).get('key',''))[:14]}…)")
    # 6 maker claims the ETH — reveals s on Ethereum. The caller pays gas; the ETH goes to the recorded claimant.
    c = eth_cli("claim", "--rpc", ETH_RPC, "--key", taker_eth_key, "--htlc", HTLC, "--hash", H, "--claimant", maker_eth,
                "--refundee", taker_eth, "--deadline", str(expf), "--value", str(ETH_WEI), "--secret", s_hex)
    print(f"     mainnet claim tx {c.get('txid', c)}", flush=True)
    ok(wait(lambda: int(eth_rpc("eth_getBalance", [maker_eth, "latest"]), 16) >= ETH_WEI, "maker paid on mainnet", 600),
       f"6. the maker's fresh address holds {ETH_STR} ETH on mainnet — the secret is now public")
    # 7 the taker learns the secret from Ethereum exactly as the watchtower does, then takes the NADO
    found = None
    def scan():
        nonlocal found
        got = W.eth_claim_secrets(ETH_RPC, HTLC, [(oid, H)], {}, "eth")
        found = got.get(oid); return bool(found)
    ok(wait(scan, "secret on Ethereum", 300) and found == s_hex, "7. taker read the secret back from the mainnet Claimed log")
    submit_l1(taker, "htlc_claim", 0, {"htlc_id": lock["txid"], "preimage": found}, "htlc_claim", fee=0)
    ok(wait(lambda: l1_bal(taker["address"]) >= tbal0 + NADO_AMT, "taker paid on NADO"), f"   taker claimed the {NADO_AMT/1e10} NADO on L1 with it")
    submit_blob(taker, {"op": "call", "contract": OTC, "method": "settle", "args": [oid] + O.preimage_limbs(found)}, "settle")
    ok(wait(lambda: int(order(oid)["st"] or 0) == 3, "settled"), "   order settled on the book")
    print(f"\n[mainnet e2e] {passed} passed, {failed} failed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
