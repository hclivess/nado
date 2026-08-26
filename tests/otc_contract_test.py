"""OTC order book (doc/dex-bridge.md §4): differential test against the real zkVM — author-in-test.
Covers both order kinds end to end (post/fill/settle with the dual-hashlock preimage, cancel, expire), the
full revert-guard battery (every guard proven by a state-unchanged check), the claim/refund window split,
and the reroll attribution (`escrow_refunds` must hand every live escrow back to its funder, summing exactly
to the contract's balance).
Run: HOME=$(mktemp -d) python3 tests/otc_contract_test.py
"""
import hashlib, json, os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode.runtimes import zkvm_addr_digest
from execnode.games import otc as O

A, C, R = "ndoMAKER", "ndoTAKER", "ndoWATCH"          # maker, taker, uninvolved watchtower
START = 10 ** 14
passed = failed = 0

def ok(c, m):
    global passed, failed
    if c: passed += 1
    else: failed += 1; print("  FAIL:", m)

st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json")); st.cursor = 100
st.block_ts = int(time.time())
for w in (A, C, R): st.bridge[w] = START
code = O.build()
st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": O.ABI, "nonce": "n"}, A, "d")
cid = st.contract_id(A, code, "n")
rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
_n = [0]

def call(who, method, args, value=None):
    _n[0] += 1
    p = {"op": "call", "contract": cid, "method": method, "args": args}
    if value: p["value"] = value
    st.apply_blob(p, who, f"{method}-{_n[0]}")

def snap():
    return json.dumps({"s": st.contracts[cid]["storage"], "b": st.bridge}, sort_keys=True, default=str)

def refused(who, method, args, value=None):
    before = snap()
    try: call(who, method, args, value)
    except Exception: pass
    return snap() == before

def secret(o): return hashlib.sha256(f"secret{o}".encode()).hexdigest()
def hsha(o):   return hashlib.sha256(bytes.fromhex(secret(o))).hexdigest()
def amt(o):    return o * 10 ** 10

def post(o, kind, expn=600, who=A, value=None):
    v = amt(o) if (kind == O.ASK and value is None) else (value or 0)
    call(who, "post", [o, kind, amt(o), "btc", f"0.00{o}", f"bc1qmaker{o}", hsha(o), O.vm_hashlock(secret(o)), expn, 999], v or None)

supply0 = sum(st.bridge.values())

# ---- A. ASK post + cancel -------------------------------------------------------------------------
post(1, O.ASK)
ok(rd(O.MK, 1) == 1 and rd(O.ST, 1) == O.OPEN, "ask posted")
ok(rd(O.ESC, 1) == amt(1) and rd(O.NAMT, 1) == amt(1), "ask escrowed exactly namt")
ok(rd(O.KIND, 1) == O.ASK and rd(O.MAKER, 1) == zkvm_addr_digest(A), "kind+maker recorded")
ok(rd(O.HVM, 1) == O.vm_hashlock(secret(1)) and rd(O.EXPN, 1) == 600, "hashlock+expiry recorded")
ok(st.bridge.get(cid, 0) == amt(1) and st.bridge[A] == START - amt(1), "escrow moved maker->contract")
ok(rd(0, 0) == 1 and rd(O.LIST, 0) == 1, "order list index")
ok(refused(C, "cancel", [1]), "cancel by a stranger refused")
call(A, "cancel", [1])
ok(rd(O.ST, 1) == O.CANCELLED and rd(O.ESC, 1) == 0 and st.bridge[A] == START, "cancel refunds the maker")
ok(refused(A, "cancel", [1]), "double cancel refused")

# ---- B. post guard battery ------------------------------------------------------------------------
ok(refused(A, "post", [1, O.ASK, amt(1), "btc", "x", "y", hsha(1), O.vm_hashlock(secret(1)), 600, 999], amt(1)), "duplicate id refused")
ok(refused(A, "post", [0, O.ASK, 5, "btc", "x", "y", hsha(9), 7, 600, 999], 5), "id 0 refused")
ok(refused(A, "post", [1 << 32, O.ASK, 5, "btc", "x", "y", hsha(9), 7, 600, 999], 5), "id >= 2^32 refused")
ok(refused(A, "post", [9, 3, 5, "btc", "x", "y", hsha(9), 7, 600, 999], 5), "kind 3 refused")
ok(refused(A, "post", [9, O.ASK, 0, "btc", "x", "y", hsha(9), 7, 600, 999]), "zero amount refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), 7, 600, 999]), "ask without escrow refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), 7, 600, 999], 4), "ask with wrong value refused")
ok(refused(A, "post", [9, O.BID, 5, "btc", "x", "y", hsha(9), 7, 600, 999], 5), "bid with value refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), 7, 105, 999], 5), "expiry below MIN_TIMELOCK refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), 7, 100 + O.HTLC_MAX_TIMELOCK + 1, 999], 5), "expiry past MAX_TIMELOCK refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), 0, 600, 999], 5), "zero vm hashlock refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", 0, 7, 600, 999], 5), "zero sha hashlock refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), 7, 600, 0], 5), "zero foreign deadline refused")
ok(refused(A, "post", [9, O.ASK, 5, 0, "x", "y", hsha(9), 7, 600, 999], 5), "zero want_chain refused")

# ---- C. ASK fill + settle -------------------------------------------------------------------------
post(2, O.ASK)
ok(refused(C, "fill", [1, "bc1qtaker", "btc:txid:0"]), "fill on a cancelled order refused")
ok(refused(C, "fill", [2, "bc1qtaker", "btc:txid:0"], 5), "fill of an ask with value refused")
ok(refused(C, "fill", [2, 0, "btc:txid:0"]), "fill without taker address refused")
ok(refused(C, "fill", [2, "bc1qtaker", 0]), "fill without foreign lock ref refused")
call(C, "fill", [2, "bc1qtaker2", "btc:lock:2"])
ok(rd(O.ST, 2) == O.FILLED and rd(O.TAKER, 2) == zkvm_addr_digest(C), "ask filled, taker recorded")
ok(rd(O.FREF, 2) == zkvm_addr_digest("btc:lock:2"), "foreign lock ref pinned")
ok(refused(R, "fill", [2, "bc1qother", "btc:lock:x"]), "second fill refused")
ok(refused(A, "cancel", [2]), "cancel after fill refused")
L2 = O.preimage_limbs(secret(2))
bad = list(L2); bad[0] ^= 1
ok(refused(R, "settle", [2] + bad), "settle with a wrong preimage refused")
ok(refused(R, "settle", [2, L2[0] + (1 << O.LIMB_BITS), L2[1], L2[2], L2[3], L2[4]]), "oversized limb refused")
cb = st.bridge.get(C, 0)
call(R, "settle", [2] + L2)                                   # a WATCHTOWER settles; payment goes to the taker
ok(rd(O.ST, 2) == O.SETTLED and rd(O.ESC, 2) == 0, "ask settled")
ok(st.bridge[C] == cb + amt(2), "ask escrow paid to the TAKER (not the caller)")
ok([rd(O.S0 + i, 2) for i in range(5)] == L2, "revealed limbs stored for the counterparty's view")
ok(refused(R, "settle", [2] + L2), "double settle refused")
post(6, O.ASK)
ok(refused(R, "settle", [6] + O.preimage_limbs(secret(6))), "settle of an unfilled order refused")

# ---- D. BID fill + settle -------------------------------------------------------------------------
post(3, O.BID)
ok(rd(O.ESC, 3) == 0 and rd(O.ST, 3) == O.OPEN, "bid posts with no escrow")
ok(refused(C, "fill", [3, "bc1qtaker3", "btc:lock:3"]), "bid fill without value refused")
ok(refused(C, "fill", [3, "bc1qtaker3", "btc:lock:3"], amt(3) - 1), "bid fill with wrong value refused")
call(C, "fill", [3, "bc1qtaker3", "btc:lock:3"], amt(3))
ok(rd(O.ESC, 3) == amt(3) and rd(O.ST, 3) == O.FILLED, "bid fill escrows the taker's NADO")
ab = st.bridge[A]
call(A, "settle", [3] + O.preimage_limbs(secret(3)))          # the maker knows s and reveals it on NADO
ok(rd(O.ST, 3) == O.SETTLED and st.bridge[A] == ab + amt(3), "bid escrow paid to the MAKER")

# ---- E. expiry windows ----------------------------------------------------------------------------
post(4, O.ASK)
ok(refused(R, "expire", [4]), "expire before the deadline refused")
st.cursor = 600
ok(refused(C, "fill", [4, "bc1qt", "btc:l"]), "fill at/after expiry refused")
ma = st.bridge[A]
call(R, "expire", [4])
ok(rd(O.ST, 4) == O.REFUNDED and st.bridge[A] == ma + amt(4), "expired open ask refunds the maker (called by anyone)")
ok(refused(R, "expire", [4]), "double expire refused")
st.cursor = 100
post(5, O.BID)
call(C, "fill", [5, "bc1qtaker5", "btc:lock:5"], amt(5))
st.cursor = 600
ok(refused(A, "settle", [5] + O.preimage_limbs(secret(5))), "settle at/after expiry refused")
tb = st.bridge[C]
call(R, "expire", [5])
ok(rd(O.ST, 5) == O.REFUNDED and st.bridge[C] == tb + amt(5), "expired filled bid refunds the TAKER")
st.cursor = 100

# ---- F. reroll attribution ------------------------------------------------------------------------
post(7, O.ASK)                                                # live: open ask (maker A)
call(C, "fill", [7, "bc1qtaker7", "btc:lock:7"])              # -> filled ask, escrow still the maker's
post(8, O.BID)
call(C, "fill", [8, "bc1qtaker8", "btc:lock:8"], amt(8))      # filled bid, escrow is the TAKER's
ref = O.escrow_refunds(st.contracts[cid]["storage"], st.zk_addrs)
ok(ref == {A: amt(6) + amt(7), C: amt(8)}, f"escrow_refunds attributes every live escrow to its funder: {ref}")
ok(sum(ref.values()) == st.bridge.get(cid, 0), "attribution sums EXACTLY to the contract's balance")
ok(rd(0, 0) == 8, "order count")
ok(sum(st.bridge.values()) == supply0, "supply conserved across the whole run")

print(f"\n[otc] {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
