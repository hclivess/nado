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

def call(who, method, args, value=None, asset=None):
    _n[0] += 1
    p = {"op": "call", "contract": cid, "method": method, "args": args}
    if value: p["value"] = value
    if asset: p["asset"] = asset
    st.apply_blob(p, who, f"{method}-{_n[0]}")

def snap():
    return json.dumps({"s": st.contracts[cid]["storage"], "b": st.bridge}, sort_keys=True, default=str)

def refused(who, method, args, value=None, asset=None):
    before = snap()
    try: call(who, method, args, value, asset)
    except Exception: pass
    return snap() == before

def secret(o): return hashlib.sha256(f"secret{o}".encode()).hexdigest()
def hsha(o):   return hashlib.sha256(bytes.fromhex(secret(o))).hexdigest()
def amt(o):    return o * 10 ** 10

def post(o, kind, expn=600, who=A, value=None):
    v = amt(o) if (kind == O.ASK and value is None) else (value or 0)
    call(who, "post", [o, kind, amt(o), "btc", f"0.00{o}", f"bc1qmaker{o}", hsha(o), *O.vm_hashlock_parts(secret(o)), expn, 999], v or None)

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
ok(refused(A, "post", [1, O.ASK, amt(1), "btc", "x", "y", hsha(1), *O.vm_hashlock_parts(secret(1)), 600, 999], amt(1)), "duplicate id refused")
ok(refused(A, "post", [0, O.ASK, 5, "btc", "x", "y", hsha(9), 0, 7, 600, 999], 5), "id 0 refused")
ok(refused(A, "post", [1 << 32, O.ASK, 5, "btc", "x", "y", hsha(9), 0, 7, 600, 999], 5), "id >= 2^32 refused")
ok(refused(A, "post", [9, 3, 5, "btc", "x", "y", hsha(9), 0, 7, 600, 999], 5), "kind 3 refused")
ok(refused(A, "post", [9, O.ASK, 0, "btc", "x", "y", hsha(9), 0, 7, 600, 999]), "zero amount refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), 0, 7, 600, 999]), "ask without escrow refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), 0, 7, 600, 999], 4), "ask with wrong value refused")
ok(refused(A, "post", [9, O.BID, 5, "btc", "x", "y", hsha(9), 0, 7, 600, 999], 5), "bid with value refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), 0, 7, 105, 999], 5), "expiry below MIN_TIMELOCK refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), 0, 7, 100 + O.HTLC_MAX_TIMELOCK + 1, 999], 5), "expiry past MAX_TIMELOCK refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), 0, 0, 600, 999], 5), "zero vm hashlock refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), 1 << 32, 7, 600, 999], 5), "oversized vm hashlock high half refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), 7, 1 << 32, 600, 999], 5), "oversized vm hashlock low half refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", 0, 0, 7, 600, 999], 5), "zero sha hashlock refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), 0, 7, 600, 0], 5), "zero foreign deadline refused")
ok(refused(A, "post", [9, O.ASK, 5, 0, "x", "y", hsha(9), 0, 7, 600, 999], 5), "zero want_chain refused")

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

# ---- H. SWAP_INTRA (§7): both legs on the exec layer, one atomic call -----------------------------
from execnode.state import asset_id
st.apply_blob({"op": "asset_create", "seed": 1, "name": "Token", "sym": "TKN", "dec": 0,
               "supply": 10 ** 9, "mintable": False}, A, "ac")
aid = int(asset_id(A, 1))
ok(st.asset_balance(aid, A) == 10 ** 9, "asset created, supply to the maker")
# H1: A gives 100 TKN, wants 3 NADO — C fills with native value
call(A, "post_intra", [10, aid, 100, 0, 3 * 10 ** 10, 600], 100, asset=aid)
ok(rd(O.MK, 10) == 1 and rd(O.KIND, 10) == O.INTRA and rd(O.ESC, 10) == 100, "intra ask posted (asset give escrowed)")
ok(st.asset_balance(aid, cid) == 100, "contract holds the asset escrow")
ok(refused(C, "fill", [10, "x", "y"]), "HTLC fill() on an intra order refused (freeze-griefing gate)")
ok(refused(C, "fill_intra", [10], 3 * 10 ** 10 - 1), "intra fill with wrong value refused")
ok(refused(C, "fill_intra", [10], 100, asset=aid), "intra fill with wrong asset refused")
ab = st.bridge[A]
call(C, "fill_intra", [10], 3 * 10 ** 10)
ok(rd(O.ST, 10) == O.SETTLED, "intra fill settles directly (no middle state)")
ok(st.bridge[A] == ab + 3 * 10 ** 10 and st.asset_balance(aid, C) == 100, "BOTH legs moved atomically: maker got NADO, taker got TKN")
# H2: C gives 2 NADO (native), wants 40 TKN — A fills with the asset
call(C, "post_intra", [11, 0, 2 * 10 ** 10, aid, 40, 600], 2 * 10 ** 10)
ok(rd(O.ESC, 11) == 2 * 10 ** 10 and rd(O.GAST, 11) == 0, "intra native-give posted")
ab2 = st.bridge[A]
call(A, "fill_intra", [11], 40, asset=aid)
ok(rd(O.ST, 11) == O.SETTLED and st.asset_balance(aid, C) == 140 and st.bridge[A] == ab2 + 2 * 10 ** 10,
   "native<->asset intra swap settled (maker got the TKN, taker got the escrowed NADO)")
ok(refused(A, "fill_intra", [2]), "fill_intra on an HTLC order refused")
ok(refused(A, "post_intra", [12, 0, 5, 0, 5, 600], 5), "NADO-for-NADO refused")
# H3: cancel + expire refund the ASSET escrow
call(A, "post_intra", [13, aid, 30, 0, 10 ** 10, 600], 30, asset=aid)
a_tkn = st.asset_balance(aid, A)
call(A, "cancel", [13])
ok(rd(O.ST, 13) == O.CANCELLED and st.asset_balance(aid, A) == a_tkn + 30, "cancel refunds the ASSET escrow")
call(A, "post_intra", [14, aid, 25, 0, 10 ** 10, 600], 25, asset=aid)
st.cursor = 600
a_tkn = st.asset_balance(aid, A)
call(R, "expire", [14])
ok(rd(O.ST, 14) == O.REFUNDED and st.asset_balance(aid, A) == a_tkn + 25, "expire refunds the ASSET escrow (called by anyone)")
st.cursor = 100
# H4: reroll attribution — native intra escrow attributes to the maker; asset escrow is skipped
call(A, "post_intra", [15, 0, 10 ** 10, aid, 5, 600], 10 ** 10)          # native give, left open
call(A, "post_intra", [16, aid, 10, 0, 10 ** 10, 600], 10, asset=aid)    # asset give, left open
ref2 = O.escrow_refunds(st.contracts[cid]["storage"], st.zk_addrs)
ok(ref2 == {A: amt(6) + amt(7) + 10 ** 10, C: amt(8)}, f"attribution includes native intra, skips asset intra: {ref2}")
ok(sum(ref2.values()) == st.bridge.get(cid, 0), "attribution still sums EXACTLY to the contract's native pot")
ok(sum(st.bridge.values()) == supply0, "native supply conserved across the intra section too")

# ---- I. §8 bounties: boost() funds the permissionless safety roles ---------------------------------
post(20, O.ASK)
call(A, "boost", [20], 10 ** 9)
call(R, "boost", [20], 5 * 10 ** 8)                       # a STRANGER may fund the safety of any order
ok(rd(O.BNTY, 20) == 15 * 10 ** 8, "bounties accumulate (anyone may attach)")
ok(refused(A, "boost", [20]), "zero-value boost refused")
ok(refused(A, "boost", [2], 10 ** 9), "boost on a settled order refused")
call(C, "fill", [20, "bc1qtaker20", "btc:lock:20"])
rb, cb = st.bridge[R], st.bridge.get(C, 0)
call(R, "settle", [20] + O.preimage_limbs(secret(20)))    # the WATCHTOWER settles...
ok(st.bridge[R] == rb + 15 * 10 ** 8, "...and wins the whole bounty")
ok(st.bridge[C] == cb + amt(20) and rd(O.BNTY, 20) == 0, "the taker still gets exactly the escrow")
post(21, O.ASK)
call(A, "boost", [21], 10 ** 9)
st.cursor = 600
rb, ab = st.bridge[R], st.bridge[A]
call(R, "expire", [21])
ok(st.bridge[R] == rb + 10 ** 9 and st.bridge[A] == ab + amt(21), "expire: sweeper wins the bounty, maker gets the escrow")
st.cursor = 100
post(22, O.ASK)
call(R, "boost", [22], 5 * 10 ** 8)
ab = st.bridge[A]
call(A, "cancel", [22])
ok(st.bridge[A] == ab + amt(22) + 5 * 10 ** 8 and rd(O.BNTY, 22) == 0,
   "cancel: nothing was performed — escrow AND bounty land with the maker")
call(A, "post_intra", [23, aid, 60, 0, 10 ** 10, 600], 60, asset=aid)
call(A, "boost", [23], 10 ** 9)
cb = st.bridge[C]
call(C, "fill_intra", [23], 10 ** 10)
ok(st.bridge[C] == cb - 10 ** 10 + 10 ** 9 and st.asset_balance(aid, C) == 200,
   "fill_intra: completing the swap wins the bounty atomically with both legs")
# reroll attribution: live bounties refund to the order's owner of record — even on an asset-intra order
post(24, O.ASK)
call(R, "boost", [24], 7 * 10 ** 8)
call(A, "boost", [16], 3 * 10 ** 8)                        # o16 = the asset-intra order left open in H4
ref3 = O.escrow_refunds(st.contracts[cid]["storage"], st.zk_addrs)
ok(ref3 == {A: amt(6) + amt(7) + 10 ** 10 + amt(24) + 7 * 10 ** 8 + 3 * 10 ** 8, C: amt(8)},
   f"attribution: escrows + live bounties, asset esc still skipped: {ref3}")
ok(sum(ref3.values()) == st.bridge.get(cid, 0), "attribution == the contract's native pot, exactly")
ok(sum(st.bridge.values()) == supply0, "native supply conserved through the bounty section")

# ---- J. §9.1 free-option premium: the second mover's walk is priced --------------------------------
post(30, O.ASK)
ok(refused(C, "set_premium", [30, 10 ** 9]), "premium: stranger refused")
ok(refused(A, "set_premium", [23, 10 ** 9]), "premium: intra order refused (no window, no option)")
call(A, "set_premium", [30, 10 ** 9])
ok(rd(O.PREM, 30) == 10 ** 9, "maker prices the option")
ok(refused(C, "fill", [30, "bc1qt30", "btc:lock:30"]), "fill without the premium refused")
call(C, "fill", [30, "bc1qt30", "btc:lock:30"], 10 ** 9)          # ASK fill now carries VALUE = premium
ok(rd(O.PHELD, 30) == 10 ** 9 and rd(O.ESC, 30) == amt(30), "premium escrowed apart from the trade escrow")
ok(refused(A, "set_premium", [30, 5]), "premium: locked once filled")
cb = st.bridge[C]
call(C, "settle", [30] + O.preimage_limbs(secret(30)))
ok(st.bridge[C] == cb + amt(30) + 10 ** 9, "COMPLETION: taker gets the escrow AND the premium back")
post(31, O.ASK)
call(A, "set_premium", [31, 10 ** 9])
call(C, "fill", [31, "bc1qt31", "btc:lock:31"], 10 ** 9)
st.cursor = 600
ab, cb = st.bridge[A], st.bridge[C]
call(R, "expire", [31])
ok(st.bridge[A] == ab + amt(31) + 10 ** 9 and st.bridge[C] == cb,
   "WALK: the maker gets their escrow back plus the forfeited premium; the taker eats the price of the option")
st.cursor = 100
post(32, O.BID)
call(A, "set_premium", [32, 5 * 10 ** 8])
ok(refused(C, "fill", [32, "bc1qt32", "btc:lock:32"], amt(32)), "BID fill at trade-only value refused when a premium is set")
call(C, "fill", [32, "bc1qt32", "btc:lock:32"], amt(32) + 5 * 10 ** 8)
ok(rd(O.ESC, 32) == amt(32) and rd(O.PHELD, 32) == 5 * 10 ** 8, "BID: trade escrow and premium ride one value, split in storage")
# attribution: a live PHELD is the TAKER's money-in-flight
ref4 = O.escrow_refunds(st.contracts[cid]["storage"], st.zk_addrs)
ok(ref4.get(C, 0) == amt(8) + amt(32) + 5 * 10 ** 8, f"attribution: filled-BID escrow + live premium return to the taker: {ref4.get(C)}")
ok(sum(ref4.values()) == st.bridge.get(cid, 0), "attribution == the contract pot, exactly (premiums included)")
ab = st.bridge[A]
call(A, "settle", [32] + O.preimage_limbs(secret(32)))
ok(st.bridge[A] == ab + amt(32) and rd(O.PHELD, 32) == 0, "BID completion: maker paid, premium released")
ok(sum(st.bridge.values()) == supply0, "native supply conserved through the premium section")

print(f"\n[otc] {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
