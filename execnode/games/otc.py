"""OTC — the cross-chain order book (doc/dex-bridge.md §4). Maker/taker swaps of NADO against a foreign
chain (BTC, ETH, ...) with NO pooled liquidity, no owner, no admin method: every order's escrow can only ever
move back to whoever funded it (cancel/expire) or forward to the counterparty on proof of the swap secret.

HOW A SWAP WORKS (ASK_NADO: Alice sells NADO for BTC):
  Alice generates a 32-byte secret s and posts the order, escrowing her NADO here under TWO commitments to
  the SAME secret: SHA-256(s) for the Bitcoin leg (Bitcoin script can only check SHA-256) and the zkVM's
  alghash of s's limbs for this contract (the VM's only in-circuit hash — see DUAL HASHLOCK below). Bob
  fill()s, pinning his Bitcoin HTLC's outpoint; Alice verifies that lock on Bitcoin, claims it, and by
  claiming REVEALS s on Bitcoin. Bob (or any watchtower) now calls settle(o, s-limbs) here: the contract
  checks alghash(limbs) == the posted hashlock and pays the escrow to Bob. One secret, two chains, no oracle:
  the preimage IS the bridge (§6.4). BID_NADO is the mirror (the NADO comes from the taker at fill time and
  settle pays the maker — who knows s — so revealing s on NADO is what lets the taker claim the foreign leg).

DUAL HASHLOCK: the zkVM has no SHA-256 (its only hash is the alghash sponge), so the foreign chain and this
contract each get a hashlock in their OWN native hash of the one secret: H_sha = SHA-256(s) locks the foreign
HTLC, H_vm = alghash.hashn(limbs(s)) locks the escrow here. Both bind at post time; revealing s anywhere
opens both. `preimage_limbs`/`vm_hashlock` below are the single shared definition (wallet + tests): s split
little-endian into five 52-bit field limbs (5x52 >= 256; each limb < 2^52 so every range gate is LT-safe).

TIMELOCKS: expiry_n is the NADO-side refund height — fill and settle require cursor < expiry_n, expire()
requires cursor >= expiry_n, so claim and refund can never race. It must sit in
[cursor+HTLC_MIN_TIMELOCK, cursor+HTLC_MAX_TIMELOCK] (mirrors the L1 HTLC bounds). expiry_f is the FOREIGN
leg's deadline — an opaque number on a chain whose clock this VM cannot see, so the §6.3 ordering invariant
(foreign refund strictly earlier than expiry_n, with claim margin) is enforced by the wallet/watchtower at
fill-accept time, never in-circuit. The contract stores it so both parties signed the same window.

RE-ROLL SURVIVABILITY (doc/updates-and-rerolls.md): every escrowed raw is ATTRIBUTABLE on-chain — orders are
enumerable (slot 0 count + LIST field) and each carries maker/taker digests and its live escrow `esc`, so at
a genesis reroll the carry-forward refunds every open/filled order exactly to whoever funded it
(`escrow_refunds` below is that attribution, the contract module owning its own schema). Orders themselves
are NOT carried: their expiry heights belong to the dead chain and the foreign leg falls back to its own
refund path — makers simply re-post. Funds always survive; intents are re-stated.

Storage (order id `o` = a frontend random int < 2^32; all slot-keyed => enumerable by the storage view):
  1 mk  2 kind(1=ASK_NADO maker gives NADO / 2=BID_NADO maker wants NADO)  3 maker(caller digest)
  4 esc(live NADO escrow, raw)  5 namt(the NADO side amount, raw)  6 wch(foreign chain digest)
  7 wamt(foreign amount digest)  8 wadr(maker's foreign receiving addr digest)  9 hsha(SHA-256 hashlock
  digest)  10 hvm(alghash hashlock, field element)  11 expn(NADO refund height)  12 expf(foreign deadline,
  opaque)  13 st(1 open 2 filled 3 settled 4 refunded 5 cancelled)  14 taker(digest)  15 tadr(taker's
  foreign addr digest)  16 fref(foreign HTLC txid/outpoint digest)  18 LIST  20..24 s0..s4(revealed limbs)
  25 gast/26 wast/27 want(SWAP_INTRA: give-asset, want-asset — 0 = native — and want amount)
  28 bnty(§8 bounty) 29 prem/30 pheld(§9.1 maker collateral: promised / held).
Methods: post(o,kind,namt,wch,wamt,wadr,hsha,hvmHi,hvmLo,expn,expf) — the alghash hashlock rides as two
  32-bit halves because a JS JSON number only holds 2^53 exactly (hvm = hi·2^32 + lo mod P) —[VALUE=namt for ASK] · cancel(o) maker/open ·
  fill(o,tadr,fref)[VALUE=namt for BID] · settle(o,l0..l4) anyone with the preimage · expire(o) anyone late ·
  boost(o)[VALUE=NADO bounty] anyone, while open/filled — first correct actor wins it (§8) ·
  set_premium(o)[VALUE] maker/open/HTLC-only — the §9.1 free-option price: the MAKER posts collateral,
  completion/cancel returns it, and walking (expire after a fill) forfeits it to the taker ·
  post_intra(o,ga,gv,wa,wv,expn)[VALUE=gv of ga] / fill_intra(o)[VALUE=wv of wa] — SWAP_INTRA (§7): both
  sides on the exec layer, both legs in one atomic call, no hashlock, open→settled directly.
Amounts are RAW NADO throughout: no products, no pro-rata — only EQ/escrow moves — and the `namt > 0` range
gate bounds every amount below the 2^62 LT window at the door.
"""
from execnode import zkpy
from execnode.stark import alghash

MK, KIND, MAKER, ESC, NAMT, WCH, WAMT, WADR, HSHA, HVM = 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
EXPN, EXPF, ST, TAKER, TADR, FREF, LIST = 11, 12, 13, 14, 15, 16, 18
S0 = 20                            # fields 20..24: the revealed preimage limbs (public after settle)
GAST, WAST, WANT = 25, 26, 27      # SWAP_INTRA sides: give-asset, want-asset (0 = native), want amount
BNTY = 28                          # attached NADO bounty (§8) — first correct actor (settle/fill_intra/expire) wins it
PREM, PHELD = 29, 30               # §9.1 free-option premium: required (maker-set) / escrowed by the taker at fill
ASK, BID, INTRA = 1, 2, 3
OPEN, FILLED, SETTLED, REFUNDED, CANCELLED = 1, 2, 3, 4, 5
ID_MAX = 1 << 32
LIMB_BITS, LIMBS = 52, 5           # 5x52 = 260 >= 256 secret bits; each limb < 2^52 (LT-safe)
HTLC_MIN_TIMELOCK = 10             # mirror the L1 HTLC bounds (ops/transaction_ops.py)
HTLC_MAX_TIMELOCK = 1_000_000


def preimage_limbs(s_hex):
    """The 32-byte secret as five little-endian 52-bit field limbs — the settle() argument vector."""
    assert len(s_hex) == 64, "swap secret must be 32 bytes hex"
    v = int(s_hex, 16)
    return [(v >> (LIMB_BITS * i)) & ((1 << LIMB_BITS) - 1) for i in range(LIMBS)]


def vm_hashlock(s_hex):
    """H_vm — the in-contract hashlock of the secret (the alghash side of the dual hashlock)."""
    return alghash.hashn(preimage_limbs(s_hex))


def vm_hashlock_parts(s_hex):
    """H_vm as the (hi32, lo32) halves post() takes — a JS JSON number is exact only to 2^53, so the
    field element crosses the wire in two 32-bit pieces and the contract recombines hi*2^32+lo."""
    return divmod(vm_hashlock(s_hex), 1 << 32)


def escrow_refunds(storage, zk_addrs):
    """{address: raw} refunding every order's LIVE escrow to whoever funded it — the reroll carry-forward's
    attribution for this contract (tools/*_carryforward.py). ASK escrow is the maker's; a filled BID's is
    the taker's. Digests resolve through the exec state's zk_addrs registry; anything unresolvable is left
    out and lands in the carry-forward's residual->deployer rule (should be empty: both parties enter as
    callers, so their digests are always registered)."""
    slots = storage.get("slots") or {}
    g = lambda f, k: int(slots.get(str(f * (1 << 32) + int(k)), 0))
    out = {}
    def add(digest, amt):
        addr = zk_addrs.get(str(digest))
        if addr and amt:
            out[addr] = out.get(addr, 0) + amt
    for i in range(g(0, 0)):
        o = g(LIST, i)
        esc = g(ESC, o)
        if esc and not (g(KIND, o) == INTRA and g(GAST, o)):   # an ASSET escrow has no native attribution —
            #                                                    exec assets die with the generation
            add(g(TAKER, o) if (g(KIND, o) == BID and g(ST, o) == FILLED) else g(MAKER, o), esc)
        add(g(MAKER, o), g(BNTY, o))       # a live bounty (always native) refunds to the order's owner of record
        add(g(MAKER, o), g(PHELD, o))      # the maker posted the collateral — a reroll is not a walk
    return out


def build():
    c = zkpy.Contract()

    # post(o, kind, namt, wch, wamt, wadr, hsha, hvmHi, hvmLo, expn, expf) [VALUE = namt for ASK_NADO]
    # The VM hashlock arrives as two 32-bit halves (JS JSON numbers are exact only to 2^53) — recombined
    # and stored as the single field element settle() compares against.
    with c.method("post") as m:
        o = m.arg(0)
        m.require(o > 0)
        m.require(o < ID_MAX)
        m.require(m.slot(MK, o).get() == 0)                     # id fresh
        m.require(m.in_asset() == 0)                            # native NADO only (SWAP_INTRA is phase 3)
        m.require((m.arg(1) - ASK) * (m.arg(1) - BID) == 0)     # kind ∈ {ASK, BID}
        m.require(m.arg(2) > 0)                                 # namt > 0; RANGE bounds it < 2^62
        m.require(m.arg(3) != 0)                                # want_chain     (EQ, not lt: full-field digests)
        m.require(m.arg(4) != 0)                                # want_amt
        m.require(m.arg(5) != 0)                                # maker's foreign receiving address
        m.require(m.arg(6) != 0)                                # SHA-256 hashlock (foreign leg)
        m.require(m.arg(7) < ID_MAX)                            # hvm high half fits 32 bits
        m.require(m.arg(8) < ID_MAX)                            # hvm low half fits 32 bits
        # Guard the RECOMBINED element, not the halves: hi*2^32+lo is reduced mod P, and P = 2^64-2^32+1,
        # so hi=2^32-1 with lo=1 lands on exactly 0 while hi+lo is plainly non-zero (audit finding).
        m.require(m.arg(7) * (1 << 32) + m.arg(8) != 0)         # alghash hashlock non-zero
        m.require(m.cursor() + HTLC_MIN_TIMELOCK < m.arg(9) + 1)          # expn >= cursor + MIN
        m.require(m.arg(9) < m.cursor() + (HTLC_MAX_TIMELOCK + 1))        # expn <= cursor + MAX
        m.require(m.arg(10) != 0)                               # foreign deadline (opaque — see TIMELOCKS)
        # the escrow rule per kind, branchless: ASK escrows exactly namt now, BID escrows nothing (the
        # NADO side arrives with the taker's fill).
        m.require(m.value() == zkpy.select(m.arg(1) == ASK, m.arg(2), m.const(0)))
        m.slot(KIND, o).set(m.arg(1))
        m.slot(MAKER, o).set(m.caller())
        m.slot(NAMT, o).set(m.arg(2))
        m.slot(ESC, o).set(m.value())
        m.slot(WCH, o).set(m.arg(3))
        m.slot(WAMT, o).set(m.arg(4))
        m.slot(WADR, o).set(m.arg(5))
        m.slot(HSHA, o).set(m.arg(6))
        m.slot(HVM, o).set(m.arg(7) * (1 << 32) + m.arg(8))
        m.slot(EXPN, o).set(m.arg(9))
        m.slot(EXPF, o).set(m.arg(10))
        m.slot(ST, o).set(m.const(OPEN))
        m.slot(MK, o).set(m.const(1))
        cnt = m.set(m.slot(0, m.const(0)).get(), "cnt")
        m.slot(LIST, cnt).set(o)
        m.slot(0, m.const(0)).set(cnt + 1)
        m.ret(o)

    # cancel(o) — maker only, only while open. The escrow (ASK) drains back to the maker.
    with c.method("cancel") as m:
        o = m.arg(0)
        m.require(o > 0)
        m.require(o < ID_MAX)                                   # slots alias above 2^32 (audit)
        m.require(m.slot(MK, o).get() == 1)
        m.require(m.slot(ST, o).get() == OPEN)
        m.require(m.slot(MAKER, o).get() == m.caller())
        esc = m.set(m.slot(ESC, o).get(), "esc")
        m.slot(ESC, o).set(m.const(0))
        m.slot(ST, o).set(m.const(CANCELLED))
        m.jnz(esc == 0, "done")                                 # a BID has no escrow while open
        m.jnz(m.slot(GAST, o).get() != 0, "asset")              # an intra order may escrow an exec ASSET
        m.pay(m.slot(MAKER, o).get(), esc)
        m.jmp("done")
        m.label("asset")
        m.apay(m.slot(GAST, o).get(), m.slot(MAKER, o).get(), esc)
        m.label("done")
        b = m.set(m.slot(BNTY, o).get() + m.slot(PHELD, o).get(), "b")   # nothing was performed: the bounty
        m.slot(BNTY, o).set(m.const(0))                                  # AND the maker's own collateral
        m.slot(PHELD, o).set(m.const(0))                                 # both go back to the maker
        m.jnz(b == 0, "bdone")
        m.pay(m.slot(MAKER, o).get(), b)
        m.label("bdone")
        m.ret(esc)

    # fill(o, tadr, fref) [VALUE = namt for BID_NADO] — first valid taker wins (the tx inclusion delay +
    # deterministic mempool make the race fair, §9). Pins the taker's foreign HTLC reference so the maker
    # can verify that lock before revealing the secret.
    with c.method("fill") as m:
        o = m.arg(0)
        m.require(o > 0)
        m.require(o < ID_MAX)                                   # slots alias above 2^32 (audit)
        m.require(m.slot(MK, o).get() == 1)
        m.require(m.slot(ST, o).get() == OPEN)
        # HTLC kinds only: an intra order settles atomically through fill_intra. Without this gate a
        # 0-value fill() could flip an intra order to FILLED and freeze its escrow until expiry.
        m.require((m.slot(KIND, o).get() - ASK) * (m.slot(KIND, o).get() - BID) == 0)
        m.require(m.cursor() < m.slot(EXPN, o).get())           # a fill can never race the refund window
        m.require(m.in_asset() == 0)
        m.require(m.arg(1) != 0)                                # taker's foreign receiving address
        m.require(m.arg(2) != 0)                                # foreign HTLC txid/outpoint
        m.require(m.value() == zkpy.select(m.slot(KIND, o).get() == BID, m.slot(NAMT, o).get(), m.const(0)))
        m.slot(ESC, o).set(m.slot(ESC, o).get() + m.value())    # BID: the taker's NADO enters escrow here
        m.slot(TAKER, o).set(m.caller())
        m.slot(TADR, o).set(m.arg(1))
        m.slot(FREF, o).set(m.arg(2))
        m.slot(ST, o).set(m.const(FILLED))
        m.ret(o)

    # set_premium(o) [VALUE = the maker's collateral] — maker only, while open: price the FREE OPTION
    # (§9.1). The MAKER posts it, because the maker generates the secret and is therefore the party who
    # can walk away after seeing the price move; completing (settle) or never being filled (cancel /
    # expire-while-open) returns it, and a walk — expire AFTER a fill — forfeits it to the taker. An
    # earlier version had the taker post it and the maker collect on a walk, which paid the walker: an
    # audit proved a maker could farm takers' deposits risk-free by simply never revealing the secret.
    # HTLC kinds only — an intra swap settles in one call, so it has no window and no option.
    with c.method("set_premium") as m:
        o = m.arg(0)
        m.require(o > 0)
        m.require(o < ID_MAX)
        m.require(m.slot(MK, o).get() == 1)
        m.require(m.slot(ST, o).get() == OPEN)
        m.require(m.slot(MAKER, o).get() == m.caller())
        m.require((m.slot(KIND, o).get() - ASK) * (m.slot(KIND, o).get() - BID) == 0)
        m.require(m.in_asset() == 0)
        m.require(m.slot(PREM, o).get() == 0)                   # set once — changing it would need a refund path
        m.require(m.value() > 0)
        m.require(m.value() < m.const(1 << 61))                 # LT-safe sanity bound
        m.slot(PREM, o).set(m.value())
        m.slot(PHELD, o).set(m.value())                         # held from the moment it is promised
        m.ret(m.value())

    # boost(o) [VALUE = added NADO bounty] — §8 watchtower/relayer bounties: ANYONE may attach NADO that
    # whoever performs the order's next required action wins (settle / fill_intra pays it to the caller,
    # expire pays the sweeper; cancel returns it to the maker). Funds the permissionless safety roles
    # without appointing anyone: first-come, and only for a CORRECT action the contract itself verifies.
    with c.method("boost") as m:
        o = m.arg(0)
        m.require(o > 0)
        m.require(o < ID_MAX)                                   # slots alias above 2^32 (audit)
        m.require(m.slot(MK, o).get() == 1)
        st = m.set(m.slot(ST, o).get(), "st")
        m.require((st - OPEN) * (st - FILLED) == 0)
        m.require(m.in_asset() == 0)                            # bounties are native NADO
        m.require(m.value() > 0)
        m.slot(BNTY, o).set(m.slot(BNTY, o).get() + m.value())
        m.ret(m.slot(BNTY, o).get())

    # settle(o, l0..l4) — ANYONE holding the preimage (the counterparty, a watchtower). Payment goes to the
    # recorded party, never the caller: ASK pays the taker (they bought the NADO), BID pays the maker.
    # Submitting the limbs publishes the secret on NADO — for a BID that is exactly what hands the taker
    # their claim on the foreign leg (the limbs are also stored, so clients read them from a view).
    with c.method("settle") as m:
        o = m.arg(0)
        m.require(o > 0)
        m.require(o < ID_MAX)                                   # slots alias above 2^32 (audit)
        m.require(m.slot(MK, o).get() == 1)
        m.require(m.slot(ST, o).get() == FILLED)
        m.require(m.cursor() < m.slot(EXPN, o).get())           # claim and refund can never overlap
        m.require(m.arg(1) < m.const(1 << LIMB_BITS))
        m.require(m.arg(2) < m.const(1 << LIMB_BITS))
        m.require(m.arg(3) < m.const(1 << LIMB_BITS))
        m.require(m.arg(4) < m.const(1 << LIMB_BITS))
        m.require(m.arg(5) < m.const(1 << LIMB_BITS))
        m.require(zkpy.hash(m.arg(1), m.arg(2), m.arg(3), m.arg(4), m.arg(5)) == m.slot(HVM, o).get())
        m.jnz(m.slot(PHELD, o).get() == 0, "pskip")             # COMPLETION: the collateral goes home
        m.pay(m.slot(MAKER, o).get(), m.slot(PHELD, o).get())
        m.label("pskip")
        m.slot(PHELD, o).set(m.const(0))
        m.slot(S0 + 0, o).set(m.arg(1))
        m.slot(S0 + 1, o).set(m.arg(2))
        m.slot(S0 + 2, o).set(m.arg(3))
        m.slot(S0 + 3, o).set(m.arg(4))
        m.slot(S0 + 4, o).set(m.arg(5))
        esc = m.set(m.slot(ESC, o).get(), "esc")
        m.slot(ESC, o).set(m.const(0))
        m.slot(ST, o).set(m.const(SETTLED))
        m.pay(zkpy.select(m.slot(KIND, o).get() == ASK, m.slot(TAKER, o).get(), m.slot(MAKER, o).get()), esc)
        b = m.set(m.slot(BNTY, o).get(), "b")                   # the §8 bounty goes to WHOEVER settled
        m.slot(BNTY, o).set(m.const(0))
        m.jnz(b == 0, "bdone")
        m.pay(m.caller(), b)
        m.label("bdone")
        m.ret(esc)

    # post_intra(o, giveAsset, giveAmt, wantAsset, wantAmt, expn) [VALUE = giveAmt of giveAsset]
    # SWAP_INTRA (§7): both sides live on NADO's exec layer, so atomicity is free — no hashlock, no
    # foreign chain, no middle state. The maker escrows the GIVE side; fill_intra moves both legs at once.
    with c.method("post_intra") as m:
        o = m.arg(0)
        m.require(o > 0)
        m.require(o < ID_MAX)
        m.require(m.slot(MK, o).get() == 0)
        m.require(m.arg(2) > 0)                                 # give amount (RANGE-bounds < 2^62)
        m.require(m.arg(4) > 0)                                 # want amount
        m.require(m.value() == m.arg(2))
        m.require(m.in_asset() == m.arg(1))                     # the stated give side == what arrived
        m.jnz(m.arg(1) != 0, "sided")                           # NADO for NADO is not a swap:
        m.require(m.arg(3) != 0)                                #   a native give must want an asset
        m.label("sided")
        m.require(m.cursor() + HTLC_MIN_TIMELOCK < m.arg(5) + 1)
        m.require(m.arg(5) < m.cursor() + (HTLC_MAX_TIMELOCK + 1))
        m.slot(KIND, o).set(m.const(INTRA))
        m.slot(MAKER, o).set(m.caller())
        m.slot(ESC, o).set(m.value())
        m.slot(GAST, o).set(m.arg(1))
        m.slot(WAST, o).set(m.arg(3))
        m.slot(WANT, o).set(m.arg(4))
        m.slot(EXPN, o).set(m.arg(5))
        m.slot(ST, o).set(m.const(OPEN))
        m.slot(MK, o).set(m.const(1))
        cnt = m.set(m.slot(0, m.const(0)).get(), "cnt")
        m.slot(LIST, cnt).set(o)
        m.slot(0, m.const(0)).set(cnt + 1)
        m.ret(o)

    # fill_intra(o) [VALUE = the wanted amount of the wanted asset] — both legs in ONE atomic call: the
    # taker's value goes to the maker and the maker's escrow to the taker; if either PAY cannot be made
    # the whole call reverts (the VM's all-or-nothing escrow settlement). open -> settled directly.
    with c.method("fill_intra") as m:
        o = m.arg(0)
        m.require(o > 0)
        m.require(o < ID_MAX)                                   # slots alias above 2^32 (audit)
        m.require(m.slot(MK, o).get() == 1)
        m.require(m.slot(ST, o).get() == OPEN)
        m.require(m.slot(KIND, o).get() == INTRA)
        m.require(m.cursor() < m.slot(EXPN, o).get())
        m.require(m.value() == m.slot(WANT, o).get())
        m.require(m.in_asset() == m.slot(WAST, o).get())
        esc = m.set(m.slot(ESC, o).get(), "esc")
        m.slot(ESC, o).set(m.const(0))
        m.slot(TAKER, o).set(m.caller())
        m.slot(ST, o).set(m.const(SETTLED))
        m.jnz(m.slot(WAST, o).get() != 0, "wasset")             # leg 1: the taker's value -> the maker
        m.pay(m.slot(MAKER, o).get(), m.value())
        m.jmp("leg2")
        m.label("wasset")
        m.apay(m.slot(WAST, o).get(), m.slot(MAKER, o).get(), m.value())
        m.label("leg2")
        m.jnz(m.slot(GAST, o).get() != 0, "gasset")             # leg 2: the maker's escrow -> the taker
        m.pay(m.slot(TAKER, o).get(), esc)
        m.jmp("done")
        m.label("gasset")
        m.apay(m.slot(GAST, o).get(), m.slot(TAKER, o).get(), esc)
        m.label("done")
        b = m.set(m.slot(BNTY, o).get(), "b")                   # completing the swap IS the bountied action
        m.slot(BNTY, o).set(m.const(0))
        m.jnz(b == 0, "bdone")
        m.pay(m.caller(), b)
        m.label("bdone")
        m.ret(esc)

    # expire(o) — anyone, at/after expn. The no-authority safety valve: a stuck order always drains back to
    # whoever funded its escrow (ASK -> maker, filled BID -> taker), callable by anybody, never trapped.
    with c.method("expire") as m:
        o = m.arg(0)
        m.require(o > 0)
        m.require(o < ID_MAX)                                   # slots alias above 2^32 (audit)
        m.require(m.slot(MK, o).get() == 1)
        st = m.set(m.slot(ST, o).get(), "st")
        m.require((st - OPEN) * (st - FILLED) == 0)
        m.require(m.slot(EXPN, o).get() < m.cursor() + 1)       # cursor >= expn
        m.jnz(m.slot(PHELD, o).get() == 0, "pskip")             # collateral: a WALK (expired while filled)
        m.pay(zkpy.select(st == FILLED, m.slot(TAKER, o).get(), m.slot(MAKER, o).get()),
              m.slot(PHELD, o).get())                           # pays the taker; unfilled returns it home
        m.label("pskip")
        m.slot(PHELD, o).set(m.const(0))
        esc = m.set(m.slot(ESC, o).get(), "esc")
        m.slot(ESC, o).set(m.const(0))
        m.slot(ST, o).set(m.const(REFUNDED))
        m.jnz(esc == 0, "done")                                 # an open BID holds nothing
        tgt = m.set(zkpy.select(m.slot(KIND, o).get() == BID, m.slot(TAKER, o).get(), m.slot(MAKER, o).get()), "tgt")
        m.jnz(m.slot(GAST, o).get() != 0, "asset")              # an intra order may escrow an exec ASSET
        m.pay(tgt, esc)
        m.jmp("done")
        m.label("asset")
        m.apay(m.slot(GAST, o).get(), tgt, esc)
        m.label("done")
        b = m.set(m.slot(BNTY, o).get(), "b")                   # the sweep bounty — pays the CALLER (§8)
        m.slot(BNTY, o).set(m.const(0))
        m.jnz(b == 0, "bdone")
        m.pay(m.caller(), b)
        m.label("bdone")
        m.ret(esc)

    return c.build()


ABI = {
    "post":   {"args": ["orderId", "kind", "nadoAmt", "wantChain", "wantAmt", "wantAddr",
                        "shaHashlock", "vmHashHi", "vmHashLo", "expiryN", "expiryF"], "value": True},
    "cancel": {"args": ["orderId"]},
    "fill":   {"args": ["orderId", "takerAddr", "foreignRef"], "value": True},
    "settle": {"args": ["orderId", "l0", "l1", "l2", "l3", "l4"]},
    "expire": {"args": ["orderId"]},
    "boost":  {"args": ["orderId"], "value": True},
    "set_premium": {"args": ["orderId"], "value": True},
    "post_intra": {"args": ["orderId", "giveAsset", "giveAmt", "wantAsset", "wantAmt", "expiryN"], "value": True},
    "fill_intra": {"args": ["orderId"], "value": True},
    "_view": {
        "maps": {"mk": {"field": MK, "index": "orders"}, "kind": {"field": KIND, "index": "orders"},
                 "maker": {"field": MAKER, "index": "orders"}, "esc": {"field": ESC, "index": "orders"},
                 "namt": {"field": NAMT, "index": "orders"}, "wch": {"field": WCH, "index": "orders"},
                 "wamt": {"field": WAMT, "index": "orders"}, "wadr": {"field": WADR, "index": "orders"},
                 "hsha": {"field": HSHA, "index": "orders"}, "hvm": {"field": HVM, "index": "orders"},
                 "expn": {"field": EXPN, "index": "orders"}, "expf": {"field": EXPF, "index": "orders"},
                 "st": {"field": ST, "index": "orders"}, "taker": {"field": TAKER, "index": "orders"},
                 "tadr": {"field": TADR, "index": "orders"}, "fref": {"field": FREF, "index": "orders"},
                 "s0": {"field": S0, "index": "orders"}, "s1": {"field": S0 + 1, "index": "orders"},
                 "s2": {"field": S0 + 2, "index": "orders"}, "s3": {"field": S0 + 3, "index": "orders"},
                 "s4": {"field": S0 + 4, "index": "orders"},
                 "gast": {"field": GAST, "index": "orders"}, "wast": {"field": WAST, "index": "orders"},
                 "want": {"field": WANT, "index": "orders"},
                 "bnty": {"field": BNTY, "index": "orders"},
                 "prem": {"field": PREM, "index": "orders"}, "pheld": {"field": PHELD, "index": "orders"}},
        "indexes": {"orders": {"cnt": 0, "list": LIST}},
        "addr": ["maker", "taker", "wch", "wamt", "wadr", "tadr", "hsha", "fref"],
    },
}
