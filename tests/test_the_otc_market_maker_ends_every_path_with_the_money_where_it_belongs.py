import os, sys, tempfile; os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-otcmm-")   # BEFORE any nado import
"""Every path of scripts/otc_mm.py step() against a simulated chain: what it sends, and that each path ends with the money
where it belongs. No network, no keys: PRIV is a temp dir and every chain read/write is a stub.

Why: on 2026-11-03 the market maker was put on mainnet with real orders while its claim path had never run; the first
live e2e crashed on a fractional amount, and review found no refund of an unpaid lock, no retry of a reverted claim and
no close of an expired order. Each of those is a scenario here. Run: python3 tests/<this file>
"""
import json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import otc_mm as M                                                                    # noqa: E402

fails = 0


def check(name, good, detail=""):
    global fails
    print(("PASS  " if good else "FAIL  ") + name + ("" if good else f": {detail}"))
    fails += 0 if good else 1


class Chain:
    def __init__(s):
        s.cur = 1000; s.od = {}; s.locks = {}; s.sent = []; s.eth_match = False; s.receipt = None; s.n = 0

    def install(s):
        M.PRIV = tempfile.mkdtemp(prefix="otcmm-")
        json.dump([{"private_key": "0x" + "11" * 32}], open(os.path.join(M.PRIV, "eth_deployer.json"), "w"))
        M.order = lambda o: dict(s.od)
        M.root = lambda: {"cursor": s.cur}
        M.htlc = lambda hid: dict(s.locks.get(hid, {}))
        s.receipts = {}                                       # per txid; s.receipt is the default for an unlisted one
        M.eth_receipt = lambda txid: s.receipts.get(txid, s.receipt)
        M.log = lambda *a: None

        def l1(kd, rcp, amount, data, label, fee=M.MIN_TX_FEE):
            s.n += 1; tid = f"l1tx{s.n}"; s.sent.append((rcp, amount, data, fee))
            if rcp == "htlc_lock":
                s.locks[tid] = {"status": "open", "expiry": data["expiry"], "amount": amount}
            return {"txid": tid}
        M.l1 = l1
        M.blob = lambda kd, p, label: s.sent.append((p["method"], p["args"]))

        def eth(cmd, *a):
            s.sent.append(("eth_" + cmd,))
            if cmd == "show":
                return {"matchesTerms": s.eth_match}
            s.n += 1; return {"txid": "0xclaim" if s.n == 1 else f"0xclaim{s.n}"}
        M.eth = eth


def rec(**k):
    r = {"oid": 5, "kind": "ask", "hashlock": "ab" * 32, "secret": "cd" * 32, "net": "eth", "nado": "0.1", "foreign": "0.00496",
         "addr": M.PAYOUT, "expn": 2000, "expf": 10 ** 10, "maker": "m", "mm": "otc_mm.py"}
    r.update(k); M.save(r, new=True); return r


def sent(c, kind):
    return [x for x in c.sent if x[0] == kind]


def run(c, r, n=1, now=1):
    for _ in range(n):
        M.step(None, r, now=now)
    return r


# 1. open, then the window passes: expire is sent (once per 5 min, not every pass); st 4 -> done, nothing to refund
c = Chain(); c.install(); r = rec()
c.od = {"st": 1, "expn": 2000, "namt": 10 ** 9}
run(c, r); check("open before expiry: nothing sent", c.sent == [], c.sent)
c.cur = 2000; run(c, r, 3)
check("open past expiry: expire sent once, not every pass", len(sent(c, "expire")) == 1, c.sent)
c.od["st"] = 4; run(c, r)
check("expired with no lock: done", r.get("done") == "expired")

# 2. filled, locked, bound, the buyer never pays: expire, then refund OUR lock, then done
c = Chain(); c.install(); r = rec()
c.od = {"st": 2, "expn": 2000, "namt": 10 ** 9, "taker": "T", "tadr": "0xrefund", "hid": None}
run(c, r)
lk = sent(c, "htlc_lock")
check("a fill locks the order's own namt (0.1 NADO, fractional) to the taker until expn",
      len(lk) == 1 and lk[0][1] == 10 ** 9 and lk[0][2]["claimant"] == "T" and lk[0][2]["expiry"] == 2000, lk)
run(c, r); check("then binds that lock", sent(c, "bind") == [("bind", [5, r["l1_lock"]])], c.sent)
run(c, r); check("a bind is not resent within 5 min", len(sent(c, "bind")) == 1)
c.od["hid"] = r["l1_lock"]; c.eth_match = False; run(c, r, 3)
check("bound, no ETH yet: only looks", not sent(c, "eth_claim") and len(sent(c, "eth_show")) == 3)
c.cur = 2000; run(c, r); check("past expiry: expire sent", len(sent(c, "expire")) == 1)
c.od["st"] = 4; run(c, r)
rf = sent(c, "htlc_refund")
check("then OUR lock is refunded (fee-exempt)", len(rf) == 1 and rf[0][2] == {"htlc_id": r["l1_lock"]} and rf[0][3] == 0, rf)
check("not done while the lock is open", not r.get("done"))
c.locks[r["l1_lock"]]["status"] = "refunded"; run(c, r)
check("lock refunded: done", r.get("done") == "expired" and r.get("lock_end") == "refunded", r)

# 3. the happy path: ETH matches -> claim -> receipt ok -> settle ourselves -> done (the taker claimed the NADO)
c = Chain(); c.install(); r = rec(l1_lock="L", taker="T", refundee="0xrefund")
c.locks["L"] = {"status": "open", "expiry": 2000}
c.od = {"st": 2, "expn": 2000, "namt": 10 ** 9, "taker": "T", "tadr": "0xrefund", "hid": "L"}
c.eth_match = True; run(c, r)
check("matching ETH lock: claimed", len(sent(c, "eth_claim")) == 1 and r.get("claim_tx") == "0xclaim")
c.receipt = None; run(c, r, 2, now=100)
check("claim pending: no second claim, no settle yet", len(sent(c, "eth_claim")) == 1 and not sent(c, "settle"))
c.receipt = 1; run(c, r, now=200)
st = sent(c, "settle")
check("claim confirmed: we settle the order ourselves with the secret's limbs",
      r.get("claim_ok") and len(st) == 1 and st[0][1] == [5, *M.O.vm_hashlock_parts("cd" * 32)], st)
c.od["st"] = 3; c.locks["L"]["status"] = "claimed"; run(c, r)
check("settled, taker claimed the NADO: done", r.get("done") == "settled" and r.get("lock_end") == "claimed", r)

# 4. a claim that reverts (or never mines) is retried while there is time
c = Chain(); c.install(); r = rec(l1_lock="L", taker="T", refundee="0xr")
c.locks["L"] = {"status": "open", "expiry": 2000}
c.od = {"st": 2, "expn": 2000, "namt": 10 ** 9, "taker": "T", "tadr": "0xr", "hid": "L"}
c.eth_match = True; run(c, r, now=10)
first = r["claim_tx"]; c.receipts[first] = 0; run(c, r, now=20); run(c, r, now=30)
check("a reverted claim is retried, once", len(sent(c, "eth_claim")) == 2 and r["claim_tx"] != first, c.sent)
run(c, r, now=40 + 901)
check("a claim not mined after 15 min is retried", len(sent(c, "eth_claim")) == 3, c.sent)
c.receipts[r["claim_tx"]] = 1; run(c, r, now=2000)
check("the retried claim confirmed: settle follows", r.get("claim_ok") and len(sent(c, "settle")) == 1)
r2 = rec(oid=6, l1_lock="L", taker="T", refundee="0xr", expf=5000)
c.sent = []; c.receipt = None; M.step(None, r2, now=5000 - 100)
check("no claim within 30 min of the ETH deadline", not sent(c, "eth_claim"), c.sent)

# 5. paid, but the taker never claims the NADO by its expiry: NOT refunded — flagged for the operator
c = Chain(); c.install(); r = rec(l1_lock="L", taker="T", refundee="0xr", claim_tx="0xclaim", claim_ok=True)
c.locks["L"] = {"status": "open", "expiry": 2000}
c.od = {"st": 3, "expn": 2000, "namt": 10 ** 9, "taker": "T", "tadr": "0xr", "hid": "L"}
run(c, r); check("paid, settled, taker yet to claim: waits", not r.get("done") and not sent(c, "htlc_refund"))
c.cur = 2000; run(c, r)
check("paid and the taker never claimed: never refunded, flagged", not sent(c, "htlc_refund") and r.get("done") == "paid_taker_unclaimed", r)

# 6. filled too late to lock safely: no lock, logged once, then the expiry path
c = Chain(); c.install(); r = rec()
c.cur = 2000 - 20; c.od = {"st": 2, "expn": 2000, "namt": 10 ** 9, "taker": "T", "tadr": "0xr", "hid": None}
run(c, r, 3); check("a fill too late to lock: nothing locked", not sent(c, "htlc_lock") and r.get("flag_late"))

# 7. the ETH amount is exact
c = Chain(); c.install(); r = rec(l1_lock="L", taker="T", refundee="0xr", foreign="0.00496")
c.locks["L"] = {"status": "open", "expiry": 2000}
c.od = {"st": 2, "expn": 2000, "namt": 10 ** 9, "taker": "T", "tadr": "0xr", "hid": "L"}
seen = []
M.eth = lambda cmd, *a: seen.append(a) or {"matchesTerms": False}
run(c, r); check("ETH value is exact wei (4960000000000000)", seen and seen[0][seen[0].index("--value") + 1] == "4960000000000000", seen)

# 8. one ETH tx in flight at a time: a second order's claim waits for the first to mine (a load-balanced RPC handed two
#    txs sent 30 s apart the same nonce on 2026-11-04, and the second replaced the first)
c = Chain(); c.install()
ra = rec(oid=7, l1_lock="LA", taker="T", refundee="0xr"); rb = rec(oid=8, l1_lock="LB", taker="T", refundee="0xr")
for k in ("LA", "LB"):
    c.locks[k] = {"status": "open", "expiry": 2000}
c.od = {"st": 2, "expn": 2000, "namt": 10 ** 9, "taker": "T", "tadr": "0xr", "hid": "L"}
c.eth_match = True; c.receipt = None
M.step(None, ra, now=10); M.step(None, rb, now=10)
check("a second claim is not sent while ours is unmined", len(sent(c, "eth_claim")) == 1 and not rb.get("claim_tx"), c.sent)
c.receipts[ra["claim_tx"]] = 1; M.step(None, ra, now=20); M.step(None, rb, now=20)
check("once the first claim mined, the second goes out", len(sent(c, "eth_claim")) == 2 and rb.get("claim_tx"), c.sent)

print("ALL PASS — every otc_mm path ends with the money where it belongs" if not fails else f"{fails} FAILED")
raise SystemExit(1 if fails else 0)
