#!/usr/bin/env python3
"""THE WHOLE SWAP, end to end: real Bitcoin (regtest) <-> real NADO (this node), one secret.

This exercises the architecture as it actually ships (doc/dex-bridge.md): the order book coordinates on
the exec layer, and the NADO principal is escrowed in an **L1 HTLC** under the SAME SHA-256 hashlock as the
Bitcoin leg — so one revealed secret provably opens both and neither side can take a leg without giving up
the other. Nothing here is simulated: a real bitcoind validates the P2WSH script, and the live node
validates the L1 HTLC and the contract calls.

  1  maker posts an ASK  (sell NADO for BTC)          exec contract, no escrow
  2  taker fills it                                    exec contract, no escrow
  3  maker LOCKS the NADO on L1                        htlc_lock, SHA-256 hashlock, claimant = taker
  4  maker binds that lock to the order                so the taker can find it
  5  taker VERIFIES the lock (amount/hashlock/expiry)   before risking anything
  6  taker funds the Bitcoin P2WSH HTLC                same hashlock, EARLIER deadline
  7  maker claims the BTC, revealing the secret         on Bitcoin
  8  taker reads the secret out of the witness          watchtower-style
  9  taker claims the L1 HTLC with it                   L1 verifies sha256(s) == hashlock
 10  the order is settled                               collateral released, secret published

Run: HOME=/srv/nado-home python3 tests/test_otc_swap_e2e.py     (needs /root/tools/bitcoin-28.1 + a live node)
"""
import hashlib, json, os, shutil, subprocess, sys, tempfile, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import otc_btc_leg as B                                                   # noqa: E402
from coincurve import PrivateKey                                          # noqa: E402
from ops.key_ops import load_keys                                         # noqa: E402
from ops.transaction_ops import construct_blob_tx                         # noqa: E402
from protocol import MIN_TX_FEE, TX_INCLUSION_DELAY, CHAIN_ID             # noqa: E402
from execnode.games import otc as O                                       # noqa: E402

L1, EX = "http://127.0.0.1:9173", "http://127.0.0.1:9273"
OTC = "1652698f36b2741fa622e1973fe1b157"
BTCD = "/root/tools/bitcoin-28.1/bin/bitcoind"
BCLI = "/root/tools/bitcoin-28.1/bin/bitcoin-cli"
RPCPORT = 18777
NADO_AMT = 3 * 10 ** 8              # 0.03 NADO — the swap's NADO side
passed = failed = 0


def ok(c, m):
    global passed, failed
    if c: passed += 1; print(f"  ok   {m}", flush=True)
    else: failed += 1; print(f"  FAIL {m}", flush=True)


def get(u):
    with urllib.request.urlopen(u, timeout=12) as r:
        return json.loads(r.read().decode())


def post_json(u, body):
    rq = urllib.request.Request(u, data=json.dumps(body).encode(),
                                headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(rq, timeout=25) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"result": False, "message": e.read().decode()[:200]}


def tip():
    return int(get(L1 + "/get_latest_block")["block_number"])


def wait(fn, label, secs=240):
    d = time.time() + secs
    while time.time() < d:
        try:
            if fn(): return True
        except Exception:
            pass
        time.sleep(3)
    print(f"  TIMEOUT: {label}", flush=True)
    return False


def sto():
    return get(EX + f"/exec/contract?ns=default&cid={OTC}&provisional=1").get("storage") or {}


def order(o):
    s = sto()
    return {k: (s.get(k) or {}).get(str(o)) for k in
            ("mk", "st", "kind", "hsha", "expn", "expf", "hid", "namt", "s0")}


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
    """A plain L1 transaction (htlc_lock / htlc_claim) — the layer that verifies SHA-256 natively."""
    from ops.transaction_ops import draft_transaction, create_transaction
    t = tip()
    d = draft_transaction(kd["address"], recipient, amount, kd["public_key"], int(time.time()), data, t + 40)
    d["chain_id"] = CHAIN_ID
    tx = create_transaction(d, kd["private_key"], fee)
    r = post_json(L1 + "/submit_transaction", tx)
    assert r.get("result"), f"{label} refused: {r.get('message')}"
    return tx


def main():
    work = tempfile.mkdtemp(prefix="otc_e2e_")
    btcdir = os.path.join(work, "btc"); os.makedirs(btcdir)
    procs = []
    try:
        maker = load_keys()
        taker = json.load(open(os.path.expanduser("~/nado/private/otc_e2e_taker.json")))
        print(f"[e2e] maker {maker['address'][:14]}…  taker {taker['address'][:14]}…", flush=True)

        # ---------- Bitcoin regtest ----------
        procs.append(subprocess.Popen([BTCD, "-regtest", f"-datadir={btcdir}", f"-rpcport={RPCPORT}",
                                       "-port=18778", "-listen=0", "-fallbackfee=0.0001", "-txindex=1"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        cli = lambda *a: subprocess.run([BCLI, "-regtest", f"-datadir={btcdir}", f"-rpcport={RPCPORT}",
                                         "-rpcwait", *a], capture_output=True, text=True, timeout=90)
        assert cli("createwallet", "w").returncode == 0
        mine = cli("getnewaddress").stdout.strip()
        cli("generatetoaddress", "101", mine)
        ok(True, "regtest bitcoind up")

        # ---------- the ONE secret ----------
        s_bytes = os.urandom(32)
        s_hex = s_bytes.hex()
        H = hashlib.sha256(s_bytes).digest()                 # the single hashlock BOTH legs use
        mk_btc, tk_btc = PrivateKey(), PrivateKey()          # per-swap Bitcoin keys

        # ---------- 1. post ----------
        oid = int.from_bytes(os.urandom(4), "big") or 7
        cur = tip()
        expn = cur + 9000                                    # ~15 h of NADO window
        expf = int(time.time()) + (O.FOREIGN_MIN_S + (expn - cur) * O.BLOCK_SECS - O.FOREIGN_MARGIN_S) // 2
        submit_blob(maker, {"op": "call", "contract": OTC, "method": "post",
                            "args": [oid, O.ASK, NADO_AMT, "btc", "0.01",
                                     "bc1q-maker|" + mk_btc.public_key.format(True).hex(),
                                     H.hex(), *O.vm_hashlock_parts(s_hex), expn, expf]}, "post")
        ok(wait(lambda: int(order(oid)["st"] or 0) == 1, "order open"), f"1. maker posted ASK #{oid} (no escrow taken)")
        ok(int(order(oid)["namt"] or 0) == NADO_AMT, "   the NADO amount is advertised, not escrowed")

        # ---------- 2. fill ----------
        submit_blob(taker, {"op": "call", "contract": OTC, "method": "fill",
                            "args": [oid, "bc1q-taker|" + tk_btc.public_key.format(True).hex(), "pending"]}, "fill")
        ok(wait(lambda: int(order(oid)["st"] or 0) == 2, "order filled"), "2. taker filled it")

        # ---------- 3. the maker locks the NADO on L1 ----------
        tbal0 = l1_bal(taker["address"])
        lock = submit_l1(maker, "htlc_lock", NADO_AMT,
                         {"claimant": taker["address"], "hashlock": H.hex(), "expiry": tip() + 9000},
                         "htlc_lock")
        # Assert the LOCK, not the maker's balance: this node's operator also produces blocks, so their
        # balance rises from rewards while the escrow leaves it.
        # generous: this is the run's first L1 transaction and has to clear the inclusion delay on a live chain
        ok(wait(lambda: (get(L1 + f"/get_htlc?id={lock['txid']}") or {}).get("htlc"), "L1 lock landed", 900),
           f"3. maker locked {NADO_AMT/1e10} NADO in an L1 HTLC ({lock['txid'][:12]}…)")

        # ---------- 4. bind it to the order ----------
        submit_blob(maker, {"op": "call", "contract": OTC, "method": "bind", "args": [oid, lock["txid"]]}, "bind")
        ok(wait(lambda: bool(order(oid)["hid"]), "binding landed"), "4. the L1 lock is recorded on the order")

        # ---------- 5. the taker VERIFIES the lock before risking anything ----------
        wait(lambda: (get(L1 + f"/get_htlc?id={lock['txid']}") or {}).get("htlc"), "htlc visible")
        htlc = (get(L1 + f"/get_htlc?id={lock['txid']}") or {}).get("htlc") or {}
        good = (htlc.get("hashlock") == H.hex() and int(htlc.get("amount", 0)) == NADO_AMT
                and htlc.get("claimant") == taker["address"] and htlc.get("status") == "open")
        ok(good, f"5. taker verified the lock on chain: amount, hashlock, claimant and status all match")

        # ---------- 6. the taker funds the Bitcoin leg, with an EARLIER deadline ----------
        btc_locktime = int(cli("getblockcount").stdout) + 20      # regtest stand-in for "well before expn"
        script = B.htlc_script(H, mk_btc.public_key.format(True), tk_btc.public_key.format(True), btc_locktime)
        addr = B.p2wsh_address(script)
        ftx = cli("sendtoaddress", addr, "0.01").stdout.strip()
        cli("generatetoaddress", "2", mine)
        raw = json.loads(cli("getrawtransaction", ftx, "true").stdout)
        spk = B.p2wsh_script(script).hex()
        vout = next(o_["n"] for o_ in raw["vout"] if o_["scriptPubKey"]["hex"] == spk)
        sats = int(round(next(o_["value"] for o_ in raw["vout"] if o_["n"] == vout) * 10 ** 8))
        ok(sats == 1000000, f"6. taker funded the Bitcoin HTLC at {addr[:20]}… ({sats} sat, same hashlock)")

        # ---------- 7. the maker claims the BTC, revealing the secret ----------
        claim = B.claim_tx(script, s_bytes, mk_btc.to_hex(), ftx, vout, sats,
                           B.p2wpkh_script(mk_btc.public_key.format(True)))
        ctxid = cli("sendrawtransaction", claim).stdout.strip()
        cli("generatetoaddress", "1", mine)
        ok(len(ctxid) == 64, "7. maker claimed the BTC — Bitcoin consensus accepted the preimage")

        # ---------- 8. the taker reads the secret off Bitcoin ----------
        seen = json.loads(cli("getrawtransaction", ctxid, "true").stdout)["hex"]
        found = B.extract_secret(seen, H)
        ok(found == s_hex, "8. taker extracted the secret from the claim witness")

        # ---------- 9. the taker claims the L1 HTLC with it ----------
        submit_l1(taker, "htlc_claim", 0, {"htlc_id": lock["txid"], "preimage": found}, "htlc_claim", fee=0)
        ok(wait(lambda: l1_bal(taker["address"]) >= tbal0 + NADO_AMT, "L1 claim landed", 300),
           f"9. taker claimed the L1 HTLC with that secret — {NADO_AMT/1e10} NADO received")

        # ---------- 10. close the order ----------
        submit_blob(taker, {"op": "call", "contract": OTC, "method": "settle",
                            "args": [oid] + O.preimage_limbs(found)}, "settle")
        ok(wait(lambda: int(order(oid)["st"] or 0) == 3, "order settled"), "10. the order is settled and the secret published")

        print(f"\n[swap-e2e] {passed} passed, {failed} failed", flush=True)
        return 1 if failed else 0
    finally:
        for p in procs:
            try: p.terminate(); p.wait(timeout=10)
            except Exception: pass
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
