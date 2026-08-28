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

EXPN, EXPIRED = 9000, 9100        # a NADO window long enough for a real foreign leg

def P8(**kw):
    """A valid set of the eight hashlock halves, optionally with one broken."""
    v = list(O.vm_hashlock_parts(secret(9)))
    for k, x in kw.items():
        v[int(k[1:])] = x
    return v

def fdl(expn=EXPN, kind=None):
    """A foreign deadline on the right side of §6.3 for the kind: ASK inside the NADO window, BID past it."""
    win = (expn - st.cursor) * O.BLOCK_SECS
    if kind == O.BID:
        return st.block_ts + win + O.FOREIGN_MARGIN_S + 3600
    return st.block_ts + (O.FOREIGN_MIN_S + win - O.FOREIGN_MARGIN_S) // 2

def post(o, kind, expn=EXPN, who=A, value=None):
    # a cross-chain order carries NO value: the NADO leg is escrowed in an L1 HTLC (see the contract's
    # WHERE THE MONEY SITS). `value` stays a parameter only so the guard battery can prove that.
    call(who, "post", [o, kind, amt(o), "btc", f"0.00{o}", f"bc1qmaker{o}", hsha(o),
                       *O.vm_hashlock_parts(secret(o)), expn, fdl(expn, kind)], value)

supply0 = sum(st.bridge.values())

# ---- A. post + cancel (no principal in the contract) ----------------------------------------------
post(1, O.ASK)
ok(rd(O.MK, 1) == 1 and rd(O.ST, 1) == O.OPEN, "ask posted")
ok(rd(O.ESC, 1) == 0 and rd(O.NAMT, 1) == amt(1), "NOTHING is escrowed here — namt is only the advertised amount")
ok(st.bridge.get(cid, 0) == 0 and st.bridge[A] == START, "no NADO left the maker's balance")
ok(rd(O.KIND, 1) == O.ASK and rd(O.MAKER, 1) == zkvm_addr_digest(A), "kind+maker recorded")
ok(rd(O.HVM, 1) == O.vm_hashlocks(secret(1))[0] and rd(O.HV3, 1) == O.vm_hashlocks(secret(1))[3], "all four hashlocks stored")
ok(rd(O.EXPN, 1) == EXPN, "expiry recorded")
ok(rd(0, 0) == 1 and rd(O.LIST, 0) == 1, "order list index")
ok(refused(A, "post", [2, O.ASK, amt(2), "btc", "x", "y", hsha(2), *P8(), EXPN, fdl()], amt(2)),
   "a post that tries to escrow VALUE is refused")
ok(refused(C, "cancel", [1]), "cancel by a stranger refused")
call(A, "cancel", [1])
ok(rd(O.ST, 1) == O.CANCELLED, "cancel closes the order")
ok(refused(A, "cancel", [1]), "double cancel refused")

# ---- B. post guard battery ------------------------------------------------------------------------
ok(refused(A, "post", [1, O.ASK, amt(1), "btc", "x", "y", hsha(1), *O.vm_hashlock_parts(secret(1)), EXPN, fdl()]), "duplicate id refused")
ok(refused(A, "post", [0, O.ASK, 5, "btc", "x", "y", hsha(9), *P8(), EXPN, fdl()]), "id 0 refused")
ok(refused(A, "post", [1 << 32, O.ASK, 5, "btc", "x", "y", hsha(9), *P8(), EXPN, fdl()]), "id >= 2^32 refused")
ok(refused(A, "post", [9, 3, 5, "btc", "x", "y", hsha(9), *P8(), EXPN, fdl()]), "kind 3 refused")
ok(refused(A, "post", [9, O.ASK, 0, "btc", "x", "y", hsha(9), *P8(), EXPN, fdl()]), "zero amount refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), *P8(), 105, fdl(105)]), "expiry below MIN_TIMELOCK refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), *P8(), 100 + O.HTLC_MAX_TIMELOCK + 1, fdl()]), "expiry past MAX_TIMELOCK refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), 0, 0, 0, 0, 0, 0, 0, 0, EXPN, fdl()]), "an all-zero hashlock set is refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), *P8(h0=1 << 32), EXPN, fdl()]), "oversized hashlock half refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), *P8(h5=1 << 32), EXPN, fdl()]), "oversized hashlock half (later digest) refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", 0, *P8(), EXPN, fdl()]), "zero sha hashlock refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), *P8(), EXPN, 0]), "zero foreign deadline refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), *P8(), EXPN, st.block_ts + 60]),
   "a foreign deadline too soon to fund is refused")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), *P8(), EXPN, st.block_ts + 10 ** 7]),
   "a foreign deadline OUTLIVING the NADO window is refused (the maker could reclaim and still claim)")
ok(refused(A, "post", [9, O.ASK, 5, "btc", "x", "y", hsha(9), *P8(), EXPN,
                       st.block_ts + (EXPN - st.cursor) * O.BLOCK_SECS - 60]),
   "a foreign deadline inside the claim margin is refused")
ok(refused(A, "post", [9, O.ASK, 5, 0, "x", "y", hsha(9), *P8(), EXPN, fdl()]), "zero want_chain refused")

# ---- C. fill / bind / settle (the L1 HTLC carries the money) --------------------------------------
post(2, O.ASK)
ok(refused(C, "fill", [1, "bc1qtaker", "btc:txid:0"]), "fill on a cancelled order refused")
ok(refused(C, "fill", [2, "bc1qtaker", "btc:txid:0"], 5), "a fill that tries to escrow VALUE is refused")
ok(refused(C, "fill", [2, 0, "btc:txid:0"]), "fill without taker address refused")
ok(refused(C, "fill", [2, "bc1qtaker", 0]), "fill without foreign lock ref refused")
call(C, "fill", [2, "bc1qtaker2", "btc:lock:2"])
ok(rd(O.ST, 2) == O.FILLED and rd(O.TAKER, 2) == zkvm_addr_digest(C), "ask filled, taker recorded")
ok(st.bridge.get(cid, 0) == 0, "still nothing escrowed in the contract")
ok(refused(R, "bind", [2, "l1:htlc:2"]), "a stranger cannot bind the L1 HTLC")
call(A, "bind", [2, "l1:htlc:2"])
ok(rd(O.HID, 2) == zkvm_addr_digest("l1:htlc:2"), "the L1 HTLC carrying the NADO leg is recorded")
ok(refused(C, "bind", [2, "l1:other"]), "the binding is recorded once")
# §6.3 is KIND-DEPENDENT: the leg the secret-holder (always the maker) funds must outlast the one they claim
ask_bad = [7, O.ASK, amt(7), "btc", "x", "y", hsha(7), *P8(), EXPN, fdl(EXPN, O.BID)]
ok(refused(A, "post", ask_bad), "ASK with the foreign deadline PAST the NADO window refused (maker could reclaim NADO and still claim)")
bid_bad = [7, O.BID, amt(7), "btc", "x", "y", hsha(7), *P8(), EXPN, fdl(EXPN, O.ASK)]
ok(refused(A, "post", bid_bad), "BID with the foreign deadline INSIDE the NADO window refused (maker could reclaim foreign and still claim NADO)")
ok(refused(A, "fill", [2, "bc1qself", "btc:self"]) , "a maker cannot fill their own order")
ok(refused(R, "fill", [2, "bc1qother", "btc:lock:x"]), "second fill refused")
ok(refused(A, "cancel", [2]), "cancel after fill refused")
L2 = O.preimage_limbs(secret(2))
bad = list(L2); bad[0] ^= 1
ok(refused(R, "settle", [2] + bad), "settle with a wrong preimage refused")
ok(refused(R, "settle", [2, L2[0] + (1 << O.LIMB_BITS), L2[1], L2[2], L2[3], L2[4]]), "oversized limb refused")
call(R, "settle", [2] + L2)                                   # a WATCHTOWER can close a completed swap
ok(rd(O.ST, 2) == O.SETTLED, "settle closes the order")
ok([rd(O.S0 + i, 2) for i in range(5)] == L2, "the secret is published for the counterparty and watchtowers")
ok(refused(R, "settle", [2] + L2), "double settle refused")
post(6, O.ASK)
ok(refused(R, "settle", [6] + O.preimage_limbs(secret(6))), "settle of an unfilled order refused")
ok(refused(A, "bind", [6, "l1:x"]), "bind before a fill refused")

post(8, O.ASK, expn=st.cursor + 400)
st.cursor = st.cursor + 400 - O.HTLC_MIN_TIMELOCK + 1
ok(refused(C, "fill", [8, "bc1qlate", "btc:late"]), "a fill with no room left for the NADO lock refused")
st.cursor = 100

# ---- D. BID is symmetric ---------------------------------------------------------------------------
post(3, O.BID)
ok(rd(O.ESC, 3) == 0 and rd(O.ST, 3) == O.OPEN, "bid posts with no escrow")
ok(refused(C, "fill", [3, "bc1qtaker3", "btc:lock:3"], amt(3)), "a BID fill that sends VALUE is refused")
call(C, "fill", [3, "bc1qtaker3", "btc:lock:3"])
ok(refused(A, "bind", [3, "l1:htlc:3"]), "BID: the maker does not owe the NADO leg, so cannot bind it")
call(C, "bind", [3, "l1:htlc:3"])
ok(rd(O.HID, 3) == zkvm_addr_digest("l1:htlc:3"), "BID: the taker records the L1 HTLC they funded")
ok(rd(O.ST, 3) == O.FILLED and st.bridge.get(cid, 0) == 0, "bid fill escrows nothing here")
call(A, "settle", [3] + O.preimage_limbs(secret(3)))
ok(rd(O.ST, 3) == O.SETTLED, "bid closes on the preimage")

# ---- E. expiry -------------------------------------------------------------------------------------
post(4, O.ASK)
ok(refused(R, "expire", [4]), "expire before the deadline refused")
st.cursor = EXPIRED
ok(refused(C, "fill", [4, "bc1qt", "btc:l"]), "fill at/after expiry refused")
call(R, "expire", [4])
ok(rd(O.ST, 4) == O.REFUNDED, "expired order closes")
ok(refused(R, "expire", [4]), "double expire refused")
st.cursor = 100
post(5, O.BID)
call(C, "fill", [5, "bc1qtaker5", "btc:lock:5"])
st.cursor = EXPIRED
ok(refused(A, "settle", [5] + O.preimage_limbs(secret(5))), "settle at/after expiry refused")
call(R, "expire", [5])
ok(rd(O.ST, 5) == O.REFUNDED, "expired filled order closes")
st.cursor = 100

# ---- F. supply ------------------------------------------------------------------------------------
ok(sum(st.bridge.values()) == supply0, "supply conserved")

# ---- H. SWAP_INTRA (§7): both legs on the exec layer, one atomic call -----------------------------
from execnode.state import asset_id
st.apply_blob({"op": "asset_create", "seed": 1, "name": "Token", "sym": "TKN", "dec": 0,
               "supply": 10 ** 9, "mintable": False}, A, "ac")
aid = int(asset_id(A, 1))
ok(st.asset_balance(aid, A) == 10 ** 9, "asset created, supply to the maker")
# H1: A gives 100 TKN, wants 3 NADO — C fills with native value
call(A, "post_intra", [10, aid, 100, 0, 3 * 10 ** 10, EXPN], 100, asset=aid)
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
call(C, "post_intra", [11, 0, 2 * 10 ** 10, aid, 40, EXPN], 2 * 10 ** 10)
ok(rd(O.ESC, 11) == 2 * 10 ** 10 and rd(O.GAST, 11) == 0, "intra native-give posted")
ab2 = st.bridge[A]
call(A, "fill_intra", [11], 40, asset=aid)
ok(rd(O.ST, 11) == O.SETTLED and st.asset_balance(aid, C) == 140 and st.bridge[A] == ab2 + 2 * 10 ** 10,
   "native<->asset intra swap settled (maker got the TKN, taker got the escrowed NADO)")
ok(refused(A, "fill_intra", [2]), "fill_intra on an HTLC order refused")
ok(refused(A, "post_intra", [12, 0, 5, 0, 5, EXPN], 5), "NADO-for-NADO refused")
# H3: cancel + expire refund the ASSET escrow
call(A, "post_intra", [13, aid, 30, 0, 10 ** 10, EXPN], 30, asset=aid)
a_tkn = st.asset_balance(aid, A)
call(A, "cancel", [13])
ok(rd(O.ST, 13) == O.CANCELLED and st.asset_balance(aid, A) == a_tkn + 30, "cancel refunds the ASSET escrow")
call(A, "post_intra", [14, aid, 25, 0, 10 ** 10, EXPN], 25, asset=aid)
st.cursor = EXPIRED
a_tkn = st.asset_balance(aid, A)
call(R, "expire", [14])
ok(rd(O.ST, 14) == O.REFUNDED and st.asset_balance(aid, A) == a_tkn + 25, "expire refunds the ASSET escrow (called by anyone)")
st.cursor = 100
# H4: reroll attribution — native intra escrow attributes to the maker; asset escrow is skipped
call(A, "post_intra", [15, 0, 10 ** 10, aid, 5, EXPN], 10 ** 10)          # native give, left open
call(A, "post_intra", [16, aid, 10, 0, 10 ** 10, EXPN], 10, asset=aid)    # asset give, left open
ref2 = O.escrow_refunds(st.contracts[cid]["storage"], st.zk_addrs)
ok(ref2 == {A: 10 ** 10}, f"attribution: only the native intra escrow is held here now: {ref2}")
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
ok(st.bridge[C] == cb and rd(O.BNTY, 20) == 0, "the taker gets nothing HERE — their NADO came from the L1 HTLC")
post(21, O.ASK)
call(A, "boost", [21], 10 ** 9)
st.cursor = EXPIRED
rb, ab = st.bridge[R], st.bridge[A]
call(R, "expire", [21])
ok(st.bridge[R] == rb + 10 ** 9 and st.bridge[A] == ab, "expire: the sweeper wins the bounty; there is no principal here to return")
st.cursor = 100
post(22, O.ASK)
call(R, "boost", [22], 5 * 10 ** 8)
ab = st.bridge[A]
call(A, "cancel", [22])
ok(st.bridge[A] == ab + 5 * 10 ** 8 and rd(O.BNTY, 22) == 0,
   "cancel: nothing was performed — the bounty goes back to the maker")
call(A, "post_intra", [23, aid, 60, 0, 10 ** 10, EXPN], 60, asset=aid)
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
ok(ref3 == {A: 10 ** 10 + 7 * 10 ** 8 + 3 * 10 ** 8},
   f"attribution: the intra escrow plus live bounties, all to the maker: {ref3}")
ok(sum(ref3.values()) == st.bridge.get(cid, 0), "attribution == the contract's native pot, exactly")
ok(sum(st.bridge.values()) == supply0, "native supply conserved through the bounty section")

# ---- J. §9.1 free-option collateral: the MAKER posts it, a walk pays the TAKER ---------------------
# (audit finding: it used to be the taker's deposit, forfeited to the maker — i.e. paid to the walker,
#  since the maker holds the secret and decides whether the swap ever completes.)
post(30, O.ASK)
ok(refused(C, "set_premium", [30], 10 ** 9), "collateral: a stranger cannot set it")
ok(refused(A, "set_premium", [23], 10 ** 9), "collateral: intra order refused (no window, no option)")
ok(refused(A, "set_premium", [30]), "collateral: must actually be funded")
ab = st.bridge[A]
call(A, "set_premium", [30], 10 ** 9)
ok(rd(O.PREM, 30) == 10 ** 9 and rd(O.PHELD, 30) == 10 ** 9, "maker posts the collateral up front")
ok(st.bridge[A] == ab - 10 ** 9, "the collateral leaves the MAKER's balance")
ok(refused(A, "set_premium", [30], 5 * 10 ** 8), "collateral is set once")
cb = st.bridge.get(C, 0)
call(C, "fill", [30, "bc1qt30", "btc:lock:30"])                 # taker pays NOTHING extra now
ok(st.bridge[C] == cb and rd(O.PHELD, 30) == 10 ** 9, "the taker funds no deposit to fill")
ok(refused(A, "set_premium", [30], 10 ** 8), "collateral: locked once filled")
ab = st.bridge[A]
call(C, "settle", [30] + O.preimage_limbs(secret(30)))
ok(st.bridge[A] == ab + 10 ** 9, "COMPLETION returns the collateral to the maker")
# the walk: maker never reveals, order expires while FILLED -> the taker is compensated
post(31, O.ASK)
call(A, "set_premium", [31], 10 ** 9)
call(C, "fill", [31, "bc1qt31", "btc:lock:31"])
st.cursor = EXPIRED
ab, cb = st.bridge[A], st.bridge[C]
call(R, "expire", [31])
ok(st.bridge[A] == ab + 10 ** 9 and st.bridge[C] == cb, "expiry while FILLED returns the collateral to the MAKER — "
   "the contract cannot see the foreign chain, so a forfeit to the taker would pay a taker who filled and did nothing")
st.cursor = 100
# never filled -> the collateral comes home, by cancel and by expiry
post(32, O.BID)
call(A, "set_premium", [32], 5 * 10 ** 8)
ab = st.bridge[A]
call(A, "cancel", [32])
ok(st.bridge[A] == ab + 5 * 10 ** 8 and rd(O.PHELD, 32) == 0, "cancel returns the unrisked collateral")
post(33, O.ASK)
call(A, "set_premium", [33], 4 * 10 ** 8)
st.cursor = EXPIRED
ab = st.bridge[A]
call(R, "expire", [33])
ok(st.bridge[A] == ab + 4 * 10 ** 8, "expiry while UNFILLED returns the collateral to the maker")
st.cursor = 100
# BID fill needs the trade value only
post(34, O.BID)
call(A, "set_premium", [34], 3 * 10 ** 8)
ok(refused(C, "fill", [34, "x", "y"], amt(34)), "a BID fill that sends VALUE is refused")
call(C, "fill", [34, "bc1qt34", "btc:lock:34"])
ok(rd(O.ESC, 34) == 0 and rd(O.PHELD, 34) == 3 * 10 ** 8, "BID: nothing escrowed here, the collateral stays the maker's")

# ---- K. audit regressions ---------------------------------------------------------------------------
# the hashlock guard must catch the field wrap: hi=2^32-1, lo=1 recombines to exactly 0 mod P
P_FIELD = 2 ** 64 - 2 ** 32 + 1
ok(refused(A, "post", [40, O.ASK, amt(1), "btc", "x", "y", hsha(40), *P8(h0=(1 << 32) - 1, h1=1), EXPN, fdl()], amt(1)),
   "hashlock halves that wrap to exactly zero mod P are refused")
# every method bounds the order id — slots alias above 2^32
BIG = (1 << 32) + 7
for meth, args, val in (("cancel", [BIG], None), ("fill", [BIG, "x", "y"], None), ("expire", [BIG], None),
                        ("boost", [BIG], 10 ** 8), ("set_premium", [BIG], 10 ** 8),
                        ("settle", [BIG] + O.preimage_limbs(secret(1)), None), ("fill_intra", [BIG], None)):
    ok(refused(A, meth, args, val), f"{meth}: an id above 2^32 is refused (no slot aliasing)")

print(f"\n[otc] {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
