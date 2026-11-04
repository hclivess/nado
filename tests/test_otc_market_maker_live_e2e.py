import os, sys, tempfile; os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-otcmm-e2e-")   # BEFORE any nado import
"""LIVE — END-TO-END run of scripts/otc_mm.py on mainnet (operator-approved 2026-11-04): one tiny ASK (0.1 NADO for 0.0002 ETH) posted
by the market maker and taken by a throwaway taker, playing the taker exactly as static/dex.js does. The RUNNING watcher
(otc_mm.py watch) must do the maker's half on its own: lock, bind, see the ETH, claim it. Every hop is read back from
the chain. State is persisted to private/ before each money step, so a crash resumes instead of losing a secret.

  tests/test_otc_market_maker_live_e2e.py pay   — the buyer pays: the watcher claims the ETH and SETTLES the order itself (the taker never settles)
  tests/test_otc_market_maker_live_e2e.py walk  — the buyer fills and walks away: the watcher must expire the order and REFUND its NADO lock
                                                 (a short order: ~2100 blocks, near the shortest window the contract allows, ~4 h)
Resumable: each mode has its own state file, and every wait accepts the states that come after it.
LIVE: real transactions with the operator's keys, so scripts/run_tests.sh never runs it; run one mode by hand, knowingly,
with the nado-otc-mm service running (it does the maker's half). Both modes PASSED on mainnet 2026-11-04 (#407264239 pay,
#2837342091 walk).
"""
import json, time, hashlib, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import otc_mm as M                                   # noqa: E402
from signatures import generate_keydict              # noqa: E402

MODE = sys.argv[1] if len(sys.argv) > 1 else ""
if MODE not in ("pay", "walk"):
    raise SystemExit("LIVE test: python3 tests/test_otc_market_maker_live_e2e.py pay|walk")
ST = os.path.join(M.PRIV, f"otc_mm_e2e_{MODE}_state.json")
NADO_AMT, ETH_AMT = "0.1", "0.0002"                  # 0.1 NADO (raw 1e9) for 0.0002 ETH
RAW_AMT = 10 ** 9
WEI = 200000000000000


def save(s):
    fd = os.open(ST, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(s, f)
    st = os.stat(M.PRIV); os.chown(ST, st.st_uid, st.st_gid)


def load():
    try:
        return json.load(open(ST))
    except FileNotFoundError:
        return {}


def wait(pred, what, timeout=1800, every=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            v = pred()
            if v:
                return v
        except Exception as e:
            M.log(f"  ({what}: {e})")
        time.sleep(every)
    raise SystemExit(f"TIMEOUT waiting for: {what}")


def step(msg):
    M.log("STEP " + msg)


def eth_call(data):
    import urllib.request
    r = urllib.request.Request(M.ETH_RPC, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                               "params": [{"to": M.HTLC, "data": data}, "latest"]}).encode(),
                               headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(r, timeout=20))["result"]


def main():
    s = load()
    maker = M.load_keys(file=os.path.join(M.PRIV, "keys.dat"))
    dep = json.load(open(os.path.join(M.PRIV, "eth_deployer.json")))[0]["private_key"].replace("0x", "")

    # 0. the throwaway taker (a fresh key of its own; never a user's)
    if not s.get("taker"):
        s["taker"] = generate_keydict(); save(s)
    tk = s["taker"]
    step(f"taker {tk['address'][:14]}…")
    if not s.get("funded"):
        M.l1(maker, tk["address"], 2 * 10 ** 9, "", "fund taker"); s["funded"] = True; save(s)
    wait(lambda: int((M.get(M.L1 + f"/get_account?address={tk['address']}") or {}).get("balance", 0)) >= 2 * 10 ** 9,
         "taker funded 0.2 NADO")
    step("taker holds 0.2 NADO")

    # 1. the maker posts ONE ask through otc_mm's own post code path (secret on disk first)
    if not s.get("oid"):
        r = M.root(); cur, now = int(r["cursor"]), int(r["block_ts"])
        sec = os.urandom(32).hex(); H = hashlib.sha256(bytes.fromhex(sec)).hexdigest()
        o = int.from_bytes(os.urandom(4), "big") or 7
        blocks = M.BLOCKS if MODE == "pay" else (M.O.FOREIGN_MIN_S + M.O.FOREIGN_MARGIN_S) // 6 + 300   # ~2100: room for the fill to still pass its window check
        expn = cur + blocks
        expf = min(now + (M.O.FOREIGN_MIN_S + blocks * 6 - M.O.FOREIGN_MARGIN_S) // 2, now + 29 * 24 * 3600)
        rec = {"oid": o, "kind": "ask", "hashlock": H, "secret": sec, "net": "eth", "nado": NADO_AMT, "foreign": ETH_AMT,
               "addr": M.PAYOUT, "expn": expn, "expf": expf, "maker": maker["address"], "posted": now, "mm": "otc_mm.py",
               "e2e": True}
        M.save(rec, new=True)
        s["oid"] = o; save(s)
        M.blob(maker, {"op": "call", "contract": M.OTC, "method": "post",
                       "args": [o, M.O.ASK, RAW_AMT, "eth", ETH_AMT, M.PAYOUT, H, *M.O.vm_hashlock_parts(sec), expn, expf]}, "post")
    o = s["oid"]
    wait(lambda: int(M.order(o)["st"] or 0) >= 1, "order on the book")
    od = M.order(o)
    step(f"#{o} on the book: st={od['st']} namt={od['namt']} expn={od['expn']} expf={od['expf']}")

    # 2. the taker fills, as dex.js does: [o, my ETH address, "pending"]; the ETH funder is the refundee
    if not s.get("filled"):
        M.blob(tk, {"op": "call", "contract": M.OTC, "method": "fill", "args": [o, M.PAYOUT, "pending"]}, "fill")
        s["filled"] = True; save(s)
    wait(lambda: int(M.order(o)["st"] or 0) >= 2, "order filled")
    step("filled by the taker")

    # 3. the WATCHER must lock 0.1 NADO to the taker and bind it — the taker verifies the lock as the dApp does
    hid = wait(lambda: M.order(o)["hid"], "watcher bound the NADO lock", timeout=1800)
    s["hid"] = hid; save(s)
    h = wait(lambda: (M.get(M.L1 + f"/get_htlc?id={hid}") or {}).get("htlc"), "lock readable")
    od = M.order(o)
    good = (h["claimant"] == tk["address"] and int(h["amount"]) == RAW_AMT and h["hashlock"] == od["hsha"]
            and int(h["expiry"]) == int(od["expn"]))
    step(f"watcher locked + bound {hid[:12]}…: claimant/amount/hashlock/expiry match = {good}")
    if not good:
        raise SystemExit(f"FAIL: the NADO lock does not match the order: {h} vs {od}")

    if MODE == "walk":
        # the buyer walks: no ETH. The watcher must expire the order at expn and refund OUR lock to the node wallet.
        step(f"buyer walks away; waiting for expn {od['expn']} (~{(int(od['expn']) - int(M.root()['cursor'])) * 6.5 / 3600:.1f} h)")
        wait(lambda: int(M.order(o)["st"] or 0) == 4, "watcher expired the order (st 4)", timeout=6 * 3600, every=60)
        step("order expired on the book")
        lk = wait(lambda: (lambda h: h if h.get("status") == "refunded" else None)(M.htlc(hid)), "watcher refunded our NADO lock",
                  timeout=1800, every=20)
        step(f"our NADO lock is {lk['status']}")
        wait(lambda: json.load(open(M.rec_path(o))).get("done") == "expired", "watcher marked the position done", timeout=600)
        step("watcher marked the position expired")
        return finish(s, tk, maker)

    # 4. the taker funds the ETH leg under the order's exact terms (claimant = maker payout, deadline = expf)
    if not s.get("eth_fund"):
        r = subprocess.run(["node", os.path.join(M.REPO, "scripts", "otc_eth_leg.mjs"), "fund", "--rpc", M.ETH_RPC,
                            "--key", dep, "--htlc", M.HTLC, "--hash", od["hsha"], "--claimant", M.PAYOUT,
                            "--deadline", str(od["expf"]), "--value", str(WEI)], capture_output=True, text=True, timeout=600)
        out = (r.stdout.strip().splitlines() or [""])[-1]
        s["eth_fund"] = out or r.stderr[-300:]; save(s)
        if r.returncode != 0:
            raise SystemExit(f"FAIL: ETH fund: {r.stderr[-400:]}")
    step(f"ETH lock funded: {s['eth_fund']}")

    # 5. the WATCHER must see it and claim the ETH (revealing the secret on Ethereum)
    rec = wait(lambda: (lambda r: r if r.get("claim_tx") else None)(json.load(open(M.rec_path(o)))),
               "watcher claimed the ETH", timeout=2400, every=15)
    step(f"watcher claimed: {rec['claim_tx']}")

    # 6. the taker reads the revealed secret from the contract (revealed(key)), exactly as dex.js ethRevealed does
    show = M.eth("show", "--rpc", M.ETH_RPC, "--htlc", M.HTLC, "--hash", od["hsha"], "--claimant", M.PAYOUT,
                 "--refundee", M.PAYOUT, "--deadline", str(od["expf"]), "--value", str(WEI))
    key = show["key"].replace("0x", "")
    data = subprocess.run(["node", "--input-type=module", "-e",
                           f"import {{ htlcAbi }} from {json.dumps('file://' + os.path.join(M.REPO, 'static/ethsign.js'))}; "
                           f"console.log(htlcAbi.revealed({json.dumps(key)}))"], capture_output=True, text=True, timeout=60).stdout.strip()
    secret = wait(lambda: (lambda x: x if len(x) == 64 and int(x, 16) and hashlib.sha256(bytes.fromhex(x)).hexdigest() == od["hsha"] else None)(
        str(eth_call(data) or "").replace("0x", "")[-64:]), "secret readable from revealed(key)", timeout=900, every=15)
    step(f"taker read the secret from Ethereum (revealed(key)), sha256 matches the order: {secret[:8]}…")

    # 7. the taker claims the NADO with it (L1 htlc_claim, fee-exempt), then settles the order
    if not s.get("nado_claim"):
        tx = M.l1(tk, "htlc_claim", 0, {"htlc_id": hid, "preimage": secret}, "htlc_claim", fee=0)
        s["nado_claim"] = tx["txid"]; save(s)
    wait(lambda: int((M.get(M.L1 + f"/get_account?address={tk['address']}") or {}).get("balance", 0)) >= RAW_AMT + 10 ** 9,
         "taker received the 0.1 NADO")
    step(f"taker claimed the NADO: {s['nado_claim'][:12]}…")
    # the TAKER does not settle here: the watcher must close the order itself once its claim is confirmed
    wait(lambda: int(M.order(o)["st"] or 0) == 3, "watcher settled the order (st 3)", timeout=1800, every=15)
    step("order settled on the book (by the watcher)")
    wait(lambda: json.load(open(M.rec_path(o))).get("done") == "settled", "watcher marked its record done", timeout=600)
    step("watcher marked the position settled")

    return finish(s, tk, maker)


def finish(s, tk, maker):
    """Return the throwaway taker's NADO to the node wallet (after its pending txs land) and forget its key."""
    def bal():
        return int((M.get(M.L1 + f"/get_account?address={tk['address']}") or {}).get("balance", 0))
    for _ in range(30):
        b = bal()
        try:
            M.l1(tk, maker["address"], b - M.MIN_TX_FEE, "", "return", fee=M.MIN_TX_FEE)
            break
        except RuntimeError as e:                    # a still-pending tx of the taker counts against its balance
            M.log(f"  (return: {e}; retrying)"); time.sleep(30)
    wait(lambda: bal() == 0, "taker emptied")
    s.pop("taker"); s["returned"] = b - M.MIN_TX_FEE; s["taker_retired"] = tk["address"]; save(s)
    step(f"returned {s['returned'] / 1e10} NADO to the node wallet; taker key deleted")
    M.log(f"E2E {MODE.upper()} PASS")

if __name__ == "__main__":
    main()
