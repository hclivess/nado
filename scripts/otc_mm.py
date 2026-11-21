#!/usr/bin/env python3
"""Operator market-maker for the cross-chain book: ASK orders (sell NADO for mainnet ETH) from the node wallet.

  post   — post the ladder (each secret written to private/ BEFORE its order is posted)
  watch  — the daemon (deploy/units/nado-otc-mm.service, operator machine): on a fill, lock the NADO in an L1 HTLC
           to the taker + bind; when the taker's ETH lock matches the terms exactly, claim it (reveals the secret),
           confirm the receipt and settle the order; an order nobody pays is expired and our lock refunded (step()).
Every path is pinned by tests/test_the_otc_market_maker_ends_every_path_with_the_money_where_it_belongs.py and was
run on mainnet by tests/test_otc_market_maker_live_e2e.py (pay + walk, 2026-11-04). Keys: private/keys.dat (the node
wallet) and private/eth_deployer.json (pays the claim gas); HOME is a temp dir, never the live DB.
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-otcmm-")      # BEFORE any node import (CLAUDE.md rule 4)
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import hashlib, json, subprocess, time, urllib.request, glob

from ops.key_ops import load_keys                                                     # noqa: E402
from ops.transaction_ops import construct_blob_tx, draft_transaction, create_transaction  # noqa: E402
from protocol import MIN_TX_FEE, TX_INCLUSION_DELAY, CHAIN_ID                         # noqa: E402
from execnode.games import otc as O                                                   # noqa: E402

PRIV = os.path.join(REPO, "private")
L1, EX = "http://127.0.0.1:9173", "http://127.0.0.1:9273"
OTC = "83562ce0cf5ee023d98b366bfcbc6e57"                 # static/dex.js OTC_CID
ETH_RPC = "https://ethereum-rpc.publicnode.com"
HTLC = "0x16a2714026cf9ace31cf4fd9b20fcedc3721e71b"     # static/dex.js NETS.eth.htlc (mainnet)
PAYOUT = "0x406Ed37679f237EA099985D8C9CE96B538F916b0"    # operator-chosen proceeds address (also pays claim gas)
BLOCKS = 28330                                           # ≈ 48 h at 6.1 s
# THE LADDER (operator 2026-11-21: "fill the order book"; centred where the last real interest was — 1 NADO for 0.00067 ETH,
# the order then being taken — asks only, 80 NADO of the node wallet): eight asks of 10 NADO, each rung 5 % over the one
# below, so the price has room to find itself. ETH amounts exact to the wei (Decimal), never a float.
from decimal import Decimal as _D
# FUNDED (operator 2026-11-22: the treasury's "dex funding" — 452 NADO — sent to the node wallet: "please open orders in dex
# reasonably"): eight asks of 50 NADO, 400 in all, the rest kept for fees and a rung re-posted after a fill.
CENTRE, STEP_PCT, RUNG_NADO, RUNGS = _D("0.00067"), _D("1.05"), 50, 8
LADDER = [(RUNG_NADO, format((RUNG_NADO * CENTRE * STEP_PCT ** i).quantize(_D("1e-8")).normalize(), "f")) for i in range(RUNGS)]   # (NADO, ETH)
# THE BUDGET (operator 2026-11-22, the dex funding in the wallet): 400 NADO — the whole ladder. It was 0 from 2026-11-21
# ("put them into staking" — the wallet's own NADO off the book); `cancel` still takes the open asks off.
BUDGET_NADO = 400                   # the most the ladder's live positions may hold
REFILL_S = 60                       # how often the watcher tops the ladder up — one rung a pass
NOT_POSTED_BLOCKS = 200             # a position whose order is still not on the book this long after posting never landed
RAW = 10 ** 10


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def get(u):
    with urllib.request.urlopen(u, timeout=15) as r:  # nosec B310 # loopback node URLs only
        return json.loads(r.read().decode())


def post_json(u, body):
    rq = urllib.request.Request(u, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(rq, timeout=25) as r:  # nosec B310 # loopback node URL
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"result": False, "message": e.read().decode()[:200]}


def tip():
    return int(get(L1 + "/get_latest_block")["block_number"])


def root():
    return get(EX + "/exec/root?ns=default&provisional=1")


def order(o):
    s = get(EX + f"/exec/contract?ns=default&cid={OTC}&provisional=1").get("storage", {})
    return {k: (s.get(k) or {}).get(str(o)) for k in ("st", "namt", "hid", "taker", "tadr", "expn", "expf", "hsha")}


def blob(kd, payload, label):
    t = tip()
    tx = construct_blob_tx(kd, payload, max_block=t + 40, fee=MIN_TX_FEE, min_block=t + TX_INCLUSION_DELAY)
    r = post_json(L1 + "/submit_transaction", tx)
    if not r.get("result"):
        raise RuntimeError(f"{label} refused: {r.get('message')}")
    return tx


def l1(kd, recipient, amount, data, label, fee=MIN_TX_FEE):
    t = tip()
    d = draft_transaction(kd["address"], recipient, amount, kd["public_key"], int(time.time()), data, t + 40)
    d["chain_id"] = CHAIN_ID
    tx = create_transaction(d, kd["private_key"], fee)
    r = post_json(L1 + "/submit_transaction", tx)
    if not r.get("result"):
        raise RuntimeError(f"{label} refused: {r.get('message')}")
    return tx


def eth(*args):
    r = subprocess.run(["node", os.path.join(REPO, "scripts", "otc_eth_leg.mjs"), *args], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"otc_eth_leg {args[0]}: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def rec_path(o):
    return os.path.join(PRIV, f"otc_position_{o}.json")


def save(rec, new=False):
    p = rec_path(rec["oid"])
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | (os.O_EXCL if new else os.O_TRUNC), 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(rec, f)
    os.chown(p, *(lambda s: (s.st_uid, s.st_gid))(os.stat(PRIV)))


def post_one(kd, nado, ethamt, rung=None):
    """Post one ASK: its record (with the secret) written to disk BEFORE the order exists, then the order."""
    r = root(); cur, now = int(r["cursor"]), int(r["block_ts"])     # CHAIN time, as the dApp does
    s = os.urandom(32).hex(); H = hashlib.sha256(bytes.fromhex(s)).hexdigest()
    o = int.from_bytes(os.urandom(4), "big") or 7
    expn = cur + BLOCKS
    expf = min(now + (O.FOREIGN_MIN_S + BLOCKS * 6 - O.FOREIGN_MARGIN_S) // 2, now + 29 * 24 * 3600)
    rec = {"oid": o, "kind": "ask", "hashlock": H, "secret": s, "net": "eth", "nado": str(nado), "foreign": ethamt,
           "addr": PAYOUT, "expn": expn, "expf": expf, "maker": kd["address"], "posted": now, "posted_cur": cur, "mm": "otc_mm.py"}
    if rung is not None:
        rec["rung"] = rung
    save(rec, new=True)                                   # the secret is on disk BEFORE the order exists
    blob(kd, {"op": "call", "contract": OTC, "method": "post",
              "args": [o, O.ASK, nado * RAW, "eth", ethamt, PAYOUT, H, *O.vm_hashlock_parts(s), expn, expf]}, "post")
    log(f"posted ASK #{o}{'' if rung is None else f' (rung {rung})'}: {nado} NADO for {ethamt} ETH (1 NADO = {float(ethamt)/nado:.6g} ETH), expn {expn}")
    return rec


def balance(addr):
    """The wallet's SPENDABLE NADO, raw (bonded stake is not spendable)."""
    a = get(L1 + "/get_account?address=" + addr)
    return int((a.get("account") or a).get("balance", 0))


def book(addr):
    """The wallet's orders on the book as the contract holds them: [(oid, st, namt raw)]."""
    s = get(EX + f"/exec/contract?ns=default&cid={OTC}&provisional=1").get("storage", {})
    m = lambda k: dict(s[k]) if isinstance(s.get(k), list) else (s.get(k) or {})
    mk, st, maker, namt = m("mk"), m("st"), m("maker"), m("namt")
    return [(int(o), int(st.get(o) or 0), int(namt.get(o) or 0)) for o in mk if maker.get(o) == addr]


def refill(kd):
    """KEEP THE BOOK FILLED (operator 2026-11-21): post the lowest rung of LADDER that no live position of ours holds — one
    a pass — while BOTH hold after it:
      * the ladder's live positions carry at most BUDGET_NADO, and
      * the wallet's spendable balance covers every NADO it may yet have to lock: an ask's NADO is locked only when it
        is TAKEN, so every order of ours still open or taken-but-unlocked on the book (the ladder's, and any posted by
        hand — a BTC ask this service does not handle) is owed, plus the new rung and its fees.
    A rung frees when its position ends (step: settled, expired, cancelled, or never posted). Returns the record or None."""
    live = mine()
    held = {r.get("rung") for r in live if r.get("rung") is not None}
    committed = sum(_D(r["nado"]) for r in live if r.get("rung") is not None)
    locked = {r["oid"] for r in live if r.get("l1_lock")}
    bk = book(kd["address"]); onbook = {o for o, _, _ in bk}
    owed = sum(n for o, st, n in bk if st == 1 or (st == 2 and o not in locked))
    owed += sum(int(_D(r["nado"]) * RAW) for r in live if r["oid"] not in onbook)   # posted, not on the book yet
    spend = balance(kd["address"])
    for i, (nado, ethamt) in enumerate(LADDER):
        if i in held:
            continue
        if committed + nado > BUDGET_NADO:
            return _hold(f"budget: {committed} of {BUDGET_NADO} NADO on the ladder")
        if spend - owed < nado * RAW + 10 * MIN_TX_FEE:
            # SAID, NOT SILENT (2026-11-21: one rung went up and the rest never did, with nothing in the log — the wallet
            # had 15 NADO spendable, and an hour went to finding that out)
            return _hold(f"wallet: {spend / RAW:.2f} NADO spendable, {owed / RAW:.2f} owed to orders that may yet lock — "
                         f"rung {i} ({nado} NADO) waits for more")
        _hold(None)
        return post_one(kd, nado, ethamt, rung=i)
    return _hold("the ladder is full")


_held_why = None
def _hold(why):
    """Log why the ladder is not growing — once per change of reason, not every pass."""
    global _held_why
    if why != _held_why and why is not None:
        log("refill holds: " + why)
    _held_why = why
    return None


def cancel(kd):
    """Take every OPEN ask of ours off the book (a cancel only works while nobody has taken it; a taken one runs its
    course in watch). Each position then ends as "cancelled" in step(). Returns how many were sent."""
    n = 0
    for rec in mine():
        o = rec["oid"]
        if int(order(o)["st"] or 0) == 1:
            blob(kd, {"op": "call", "contract": OTC, "method": "cancel", "args": [o]}, "cancel")
            log(f"#{o} cancel sent ({rec['nado']} NADO for {rec['foreign']} ETH)"); n += 1
    log(f"{n} open ask(s) cancelled")
    return n


def post(kd):
    for nado, ethamt in LADDER:
        post_one(kd, nado, ethamt)
        time.sleep(2)
    t0 = time.time()
    while time.time() - t0 < 600:
        sts = {r["oid"]: order(r["oid"])["st"] for r in mine()}
        if all(int(v or 0) == 1 for v in sts.values()):
            log("all open on the book:", sts); return 0
        time.sleep(10)
    log("NOT all open after 10 min:", sts); return 1


def mine():
    out = []
    for p in glob.glob(os.path.join(PRIV, "otc_position_*.json")):
        try:
            r = json.load(open(p))
        except Exception:
            continue
        if r.get("mm") == "otc_mm.py" and not r.get("done"):
            out.append(r)
    return out


def htlc(hid):
    return (get(L1 + f"/get_htlc?id={hid}") or {}).get("htlc") or {}


def eth_receipt(txid):
    """1 = mined and succeeded, 0 = mined and reverted, None = not mined (or unknown to the RPC)."""
    rq = urllib.request.Request(ETH_RPC, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionReceipt",
                                "params": [txid]}).encode(), headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(rq, timeout=20) as r:  # nosec B310 # the public ETH RPC above
        res = json.loads(r.read().decode()).get("result")
    return None if not res else int(res["status"], 16)


def once(rec, key, msg):
    """Log a condition once per record, not every 20 s."""
    if not rec.get(key):
        rec[key] = True; save(rec); log(msg)


def due(rec, key, every=300):
    """True at most once per `every` seconds per record: a sent tx gets that long to land before it is sent again."""
    if time.time() - rec.get(key, 0) < every:
        return False
    rec[key] = time.time(); save(rec)
    return True


def step(kd, rec, now=None):
    """One pass over one of our orders. EVERY PATH ENDS WITH THE MONEY WHERE IT BELONGS (e2e 2026-11-04):
      open, then expired          -> expire the order (it leaves the book) -> done
      filled                      -> lock the order's own namt to the taker, bind it
      taker's ETH matches         -> claim it, verify the receipt (a reverted or vanished claim is retried while
                                     there is time), then settle the order ourselves (we hold the secret)
      expired with our lock open  -> expire the order, refund our NADO lock (the buyer never paid)
      paid, taker never claimed   -> NOT refunded: the NADO is theirs; flagged for the operator
    """
    now = int(time.time()) if now is None else now
    o = rec["oid"]; od = order(o); st = int(od["st"] or 0); cur = int(root()["cursor"])
    lock = htlc(rec["l1_lock"]) if rec.get("l1_lock") else {}
    paid = rec.get("claim_ok")
    if st in (3, 4, 5):                                       # the order is closed; our L1 lock must be too
        if lock.get("status") == "open":
            if paid:
                if cur >= int(lock["expiry"]):
                    once(rec, "flag_unclaimed", f"#{o} PAID but the taker never claimed the NADO by its expiry — "
                         f"lock {rec['l1_lock'][:12]}… left for the operator (refunding would take what they paid for)")
                    rec["done"] = "paid_taker_unclaimed"; save(rec)
                return                                        # the taker can still claim it before expiry
            if cur >= int(lock["expiry"]) and due(rec, "refund_sent"):
                l1(kd, "htlc_refund", 0, {"htlc_id": rec["l1_lock"]}, "htlc_refund", fee=0)
                log(f"#{o} refund of the NADO lock sent ({rec['l1_lock'][:12]}…)")
            return
        rec["done"] = {3: "settled", 4: "expired", 5: "cancelled"}[st]
        if lock.get("status"):
            rec["lock_end"] = lock["status"]
        save(rec); log(f"#{o} {rec['done']}" + (f", our lock {lock['status']}" if lock else ""))
        return
    if st not in (1, 2):
        # NEVER POSTED: the record is written before its order is sent, so a refused or dropped post leaves a record with
        # no order — it held its ladder rung (refill) for good. Not on the book NOT_POSTED_BLOCKS after posting: done.
        if st == 0 and not rec.get("l1_lock") and cur > int(rec.get("posted_cur", cur)) + NOT_POSTED_BLOCKS:
            rec["done"] = "not_posted"; save(rec); log(f"#{o} never reached the book — rung freed")
        return
    if cur >= int(od["expn"] or rec["expn"]):                 # past the order's window: close it (anyone may)
        if due(rec, "expire_sent"):
            blob(kd, {"op": "call", "contract": OTC, "method": "expire", "args": [o]}, "expire")
            log(f"#{o} expired — expire sent")
        return
    if st == 1:
        return
    taker = od["taker"]; refundee = (od["tadr"] or "").split("|")[-1]
    if not rec.get("l1_lock"):
        if cur + O.HTLC_MIN_TIMELOCK + 30 > rec["expn"]:
            once(rec, "flag_late", f"#{o} filled too late to lock safely; it will expire")
            return
        # the lock is the order's OWN amount (namt, raw) — int(rec["nado"]) crashed on a fractional order (e2e 2026-11-04)
        lk = l1(kd, "htlc_lock", int(od["namt"]), {"claimant": taker, "hashlock": rec["hashlock"], "expiry": rec["expn"]}, "htlc_lock")
        rec["l1_lock"] = lk["txid"]; rec["taker"] = taker; rec["refundee"] = refundee; save(rec)
        log(f"#{o} filled by {taker[:12]}… — locked {int(od['namt']) / RAW} NADO ({lk['txid'][:12]}…)")
        return
    if not od["hid"]:
        if lock.get("status") and due(rec, "bind_sent"):
            blob(kd, {"op": "call", "contract": OTC, "method": "bind", "args": [o, rec["l1_lock"]]}, "bind")
            log(f"#{o} bind sent")
        return
    from decimal import Decimal
    wei = str(int(Decimal(rec["foreign"]) * 10 ** 18))      # exact: a float of "0.00496" is not 0.00496
    terms = ["--rpc", ETH_RPC, "--htlc", HTLC, "--hash", rec["hashlock"], "--claimant", PAYOUT,
             "--refundee", refundee, "--deadline", str(rec["expf"]), "--value", wei]
    if rec.get("claim_tx") and not paid:                      # a claim is out: did it succeed?
        r = eth_receipt(rec["claim_tx"])
        if r == 1:
            rec["claim_ok"] = paid = True; save(rec); log(f"#{o} ETH claim confirmed ({rec['claim_tx'][:12]}…)")
        elif r == 0 or (r is None and now - rec.get("claim_at", now) > 900):
            log(f"#{o} ETH claim {'reverted' if r == 0 else 'not mined after 15 min'} — retrying")
            rec.pop("claim_tx"); save(rec)
        else:
            return
    if paid:                                                  # we hold the secret: close the order ourselves
        if due(rec, "settle_sent"):
            blob(kd, {"op": "call", "contract": OTC, "method": "settle", "args": [o, *O.vm_hashlock_parts(rec["secret"])]}, "settle")
            log(f"#{o} settle sent")
        return
    try:
        sh = eth("show", *terms)
    except Exception as e:
        log(f"#{o} eth show: {e}"); return
    if not sh.get("matchesTerms"):
        return
    if now > rec["expf"] - 1800:
        once(rec, "flag_close", f"#{o} ETH lock found but too close to its deadline to claim safely"); return
    # ONE ETH tx of ours in flight at a time: the public RPC is load-balanced, and a backend that has not seen our last
    # tx hands out the same "pending" nonce, so the second tx REPLACES the first (measured 2026-11-04: two refunds sent
    # 30 s apart shared nonce 12 and only the second mined). A claim waits for the other order's claim to mine.
    if any(r["oid"] != o and r.get("claim_tx") and not r.get("claim_ok") for r in mine()):
        return
    key = json.load(open(os.path.join(PRIV, "eth_deployer.json")))[0]["private_key"].replace("0x", "")
    c = eth("claim", "--key", key, *terms, "--secret", rec["secret"])
    rec["claim_tx"] = c.get("txid") or str(c); rec["claim_at"] = now; save(rec)
    log(f"#{o} CLAIMED {rec['foreign']} ETH -> {PAYOUT} ({rec['claim_tx']})")


def watch(kd):
    """Never exits: a service with no live order waits for the next one (an exit would be a restart loop). Every
    REFILL_S it tops the ladder up by one rung (refill)."""
    log("watching", [r["oid"] for r in mine()])
    last = 0.0
    while True:
        for rec in mine():
            try:
                step(kd, rec)
            except Exception as e:
                log(f"#{rec['oid']} error: {e}")
        if time.time() - last >= REFILL_S:
            last = time.time()
            try:
                refill(kd)
            except Exception as e:
                log(f"refill error: {e}")
        time.sleep(20)


if __name__ == "__main__":
    kd = load_keys(file=os.path.join(PRIV, "keys.dat"))
    cmd = sys.argv[1]
    sys.exit(post(kd) if cmd == "post" else (0 if cancel(kd) >= 0 else 1) if cmd == "cancel" else watch(kd))
