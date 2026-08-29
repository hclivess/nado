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

WHERE THE MONEY SITS (the security-critical part). A cross-chain swap's NADO leg is escrowed in an **L1
HTLC** (`htlc_lock`/`htlc_claim`/`htlc_refund`), NOT in this contract. That is not a style choice: L1
verifies `sha256(preimage) == hashlock` natively, so the NADO leg and the foreign leg are locked by literally
the SAME SHA-256 image and one revealed secret provably opens both. This contract only ever holds the
maker's COLLATERAL and any tips — never the swap principal.

An earlier version escrowed the principal here, gated on an alghash image the maker supplied ALONGSIDE the
SHA-256 one. Nothing forced the two to come from the same secret (the VM cannot compute SHA-256 to check),
so a maker could post two unrelated hashlocks, claim the foreign coin with one, and leave the NADO side
permanently unclaimable — keeping both sides. An audit proved it. Moving the principal to the L1 HTLC
removes the class outright: there is ONE hashlock, checked by code that can actually compute it.

The four alghash digests survive, but now they gate only the COLLATERAL: proving knowledge of the secret
returns the maker their own deposit. Forging that image would let an attacker hand the maker their money
back — nothing to steal, so the weaker hash is harmless exactly here.

`preimage_limbs`/`vm_hashlocks` below are the single shared definition (wallet + tests): s split
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
  digest)  10 hvm + 31/32/33 hv1..hv3(the FOUR alghash hashlocks — one field element each)  11 expn(NADO refund height)  12 expf(foreign deadline,
  opaque)  13 st(1 open 2 filled 3 settled 4 refunded 5 cancelled)  14 taker(digest)  15 tadr(taker's
  foreign addr digest)  16 fref(foreign HTLC txid/outpoint digest)  18 LIST  20..24 s0..s4(revealed limbs)
  25 gast/26 wast/27 want(SWAP_INTRA: give-asset, want-asset — 0 = native — and want amount)
  28 bnty(§8 bounty) 29 prem/30 pheld(§9.1 maker collateral: promised / held).
Methods: post(o,kind,namt,wch,wamt,wadr,hsha,hi0,lo0,hi1,lo1,hi2,lo2,hi3,lo3,expn,expf) — the four
  alghash hashlocks ride as 32-bit halves because a JS JSON number only holds 2^53 exactly. NO VALUE —
  the principal is in the L1 HTLC · cancel(o) maker/open · fill(o,tadr,fref)[no VALUE] ·
  bind(o,htlcId) records the L1 HTLC holding the NADO leg · settle(o,l0..l4) anyone with the preimage,
  closes the order and returns the collateral · expire(o) anyone late ·
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
HV1, HV2, HV3 = 31, 32, 33         # the other three digests of the WIDE hashlock (HVM/10 holds the first)
HID = 34                           # the L1 HTLC that actually carries the NADO leg (txid digest)
FILLH = 35                         # the block the fill landed in — starts the taker's window to bind their side
FILL_WINDOW = 600                  # blocks (~1 h) a taker has to bind the NADO leg before the maker may release the order
BNTY = 28                          # attached NADO bounty (§8) — first correct actor (settle/fill_intra/expire) wins it
PREM, PHELD = 29, 30               # §9.1 free-option premium: required (maker-set) / escrowed by the taker at fill
ASK, BID, INTRA = 1, 2, 3
OPEN, FILLED, SETTLED, REFUNDED, CANCELLED = 1, 2, 3, 4, 5
ID_MAX = 1 << 32
LIMB_BITS, LIMBS = 52, 5           # 5x52 = 260 >= 256 secret bits; each limb < 2^52 (LT-safe)
# WIDE HASHLOCK. One alghash digest is a single field element (~64 bits) and the sponge's state is only
# 128 bits wide, so an audit put a forged preimage at roughly 2^44 work — far below the SHA-256 side of
# the same swap. The VM has no wider hash opcode, so the lock is FOUR digests of the same secret, each
# over a differently-offset first limb: a forger must satisfy four independent 64-bit constraints with
# one tuple of limbs, which puts the generic cost back out of reach. Costs four HASH blocks per settle.
HDOM = [0, 0x10000000001, 0x20000000003, 0x30000000007]
# §6.3 TIMELOCK ORDERING, now enforced in-circuit (it used to be a wallet-side promise the wallet never
# kept). The foreign leg must be refundable well BEFORE the NADO escrow unlocks, or a maker can reclaim
# their NADO and still claim the foreign coin. The VM knows the chain clock (TIME) and the block cadence,
# so the whole inequality is checkable here.
FOREIGN_MIN_S = 3600               # the foreign leg needs at least this long to be funded and confirmed
FOREIGN_MARGIN_S = 7200            # ... and must expire this far before the NADO side does
BLOCK_SECS = 6
HTLC_MIN_TIMELOCK = 10             # mirror the L1 HTLC bounds (ops/transaction_ops.py)
HTLC_MAX_TIMELOCK = 1_000_000


def preimage_limbs(s_hex):
    """The 32-byte secret as five little-endian 52-bit field limbs — the settle() argument vector."""
    assert len(s_hex) == 64, "swap secret must be 32 bytes hex"
    v = int(s_hex, 16)
    return [(v >> (LIMB_BITS * i)) & ((1 << LIMB_BITS) - 1) for i in range(LIMBS)]


def vm_hashlocks(s_hex):
    """The FOUR alghash digests that lock the secret in-contract (see WIDE HASHLOCK above)."""
    limbs = preimage_limbs(s_hex)
    return [alghash.hashn([limbs[0] + d] + limbs[1:]) for d in HDOM]


def vm_hashlock_parts(s_hex):
    """The four hashlocks as the eight (hi32, lo32) halves post() takes — a JS JSON number is exact only
    to 2^53, so each field element crosses the wire in two 32-bit pieces and the contract recombines."""
    out = []
    for h in vm_hashlocks(s_hex):
        out.extend(divmod(h, 1 << 32))
    return out


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
            add(g(MAKER, o), esc)                              # only SWAP_INTRA escrows here, always the maker's
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
        # the four hashlock halves (args 7..14); each is bounded and each RECOMBINED element must be
        # non-zero — guarding the halves alone missed hi=2^32-1, lo=1, which wraps to exactly 0 mod P.
        for _i in range(4):
            m.require(m.arg(7 + _i * 2) < ID_MAX)
            m.require(m.arg(8 + _i * 2) < ID_MAX)
            m.require(m.arg(7 + _i * 2) * (1 << 32) + m.arg(8 + _i * 2) != 0)
        m.require(m.cursor() + HTLC_MIN_TIMELOCK < m.arg(15) + 1)         # expn >= cursor + MIN
        m.require(m.arg(15) < m.cursor() + (HTLC_MAX_TIMELOCK + 1))       # expn <= cursor + MAX
        # §6.3 IN-CIRCUIT, and it depends on WHO HOLDS THE SECRET. The maker generates it for both kinds.
        # The leg the secret-holder CLAIMS must expire first, so the counterparty still has time to use the
        # revealed secret on the other leg; the leg the secret-holder FUNDS must therefore last longer.
        #   ASK: maker funds NADO (expn), claims the foreign leg (expf)  =>  expf + margin < expn
        #   BID: maker funds the foreign leg (expf), claims NADO (expn)  =>  expn + margin < expf
        # An earlier version applied the ASK inequality to both: a BID maker could refund the foreign leg
        # at expf and still claim the taker's NADO before expn — both sides, no secret ever at risk.
        m.require(m.time() + FOREIGN_MIN_S < m.arg(16))                   # far enough out to be fundable
        m.jnz(m.arg(1) == BID, "bid")
        m.require(m.arg(16) + FOREIGN_MARGIN_S
                  < m.time() + (m.arg(15) - m.cursor()) * BLOCK_SECS)     # ASK: foreign safely before expn
        m.jmp("ordered")
        m.label("bid")
        m.require(m.time() + (m.arg(15) - m.cursor()) * BLOCK_SECS + FOREIGN_MARGIN_S
                  < m.arg(16))                                            # BID: NADO safely before foreign
        m.label("ordered")
        # NO PRINCIPAL HERE. The NADO leg is escrowed in an L1 HTLC under the same SHA-256 hashlock as the
        # foreign leg (see WHERE THE MONEY SITS). `namt` is the advertised amount, not an escrow.
        m.require(m.value() == 0)
        m.slot(KIND, o).set(m.arg(1))
        m.slot(MAKER, o).set(m.caller())
        m.slot(NAMT, o).set(m.arg(2))
        m.slot(WCH, o).set(m.arg(3))
        m.slot(WAMT, o).set(m.arg(4))
        m.slot(WADR, o).set(m.arg(5))
        m.slot(HSHA, o).set(m.arg(6))
        m.slot(HVM, o).set(m.arg(7) * (1 << 32) + m.arg(8))
        m.slot(HV1, o).set(m.arg(9) * (1 << 32) + m.arg(10))
        m.slot(HV2, o).set(m.arg(11) * (1 << 32) + m.arg(12))
        m.slot(HV3, o).set(m.arg(13) * (1 << 32) + m.arg(14))
        m.slot(EXPN, o).set(m.arg(15))
        m.slot(EXPF, o).set(m.arg(16))
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
        # the NADO leg is locked AFTER the fill with expiry expn, so there must still be room for a lock
        m.require(m.cursor() + HTLC_MIN_TIMELOCK < m.slot(EXPN, o).get() + 1)
        m.require(m.slot(MAKER, o).get() != m.caller())         # self-fill would farm third-party bounties
        # §6.3 again at FILL, in the same kind-dependent direction as post: the NADO window shrinks in
        # real time while the foreign deadline stays put, so an ASK that was safe to post can become
        # unsafe to fill (the taker is the one who loses). A BID's inequality only gets looser with time,
        # but stating it here keeps one rule in one shape.
        m.jnz(m.slot(KIND, o).get() == BID, "bid")
        m.require(m.slot(EXPF, o).get() + FOREIGN_MARGIN_S
                  < m.time() + (m.slot(EXPN, o).get() - m.cursor()) * BLOCK_SECS)
        m.jmp("ordered")
        m.label("bid")
        m.require(m.time() + (m.slot(EXPN, o).get() - m.cursor()) * BLOCK_SECS + FOREIGN_MARGIN_S
                  < m.slot(EXPF, o).get())
        m.label("ordered")
        m.require(m.in_asset() == 0)
        m.require(m.arg(1) != 0)                                # taker's foreign receiving address
        m.require(m.arg(2) != 0)                                # foreign HTLC txid/outpoint
        m.require(m.value() == 0)                               # the NADO leg lives in the L1 HTLC, not here
        m.slot(TAKER, o).set(m.caller())
        m.slot(TADR, o).set(m.arg(1))
        m.slot(FREF, o).set(m.arg(2))
        m.slot(FILLH, o).set(m.cursor())
        m.slot(ST, o).set(m.const(FILLED))
        m.ret(o)

    # set_premium(o) [VALUE = the maker's collateral] — maker only, while open. A self-escrowed deposit that
    # comes back on every terminal state (settle, cancel, expire). It is a SIGNAL of commitment, nothing
    # more: this contract cannot observe the foreign chain, so it can never judge who walked, and any rule
    # that forfeited it to the taker was a bounty for filling and doing nothing (see expire). Kept so
    # existing orders drain cleanly; the dApp no longer offers it.
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

    # bind(o, htlcId) — either party records the L1 HTLC carrying the NADO leg, so the counterparty and any
    # watchtower can find and verify it (amount, hashlock, expiry) before funding the foreign side.
    with c.method("bind") as m:
        o = m.arg(0)
        m.require(o > 0)
        m.require(o < ID_MAX)
        m.require(m.slot(MK, o).get() == 1)
        m.require(m.slot(ST, o).get() == FILLED)
        # only the party who OWES the NADO leg may record it (ASK: maker, BID: taker). Set-once by either
        # party let the counterparty squat the slot with garbage and strand the real lock unrecorded.
        m.require(zkpy.select(m.slot(KIND, o).get() == ASK, m.slot(MAKER, o).get(), m.slot(TAKER, o).get())
                  == m.caller())
        m.require(m.in_asset() == 0)
        m.require(m.value() == 0)
        m.require(m.arg(1) != 0)
        m.require(m.slot(HID, o).get() == 0)                    # recorded once — it is what the taker verifies
        m.slot(HID, o).set(m.arg(1))
        m.ret(m.arg(1))

    # settle(o, l0..l4) — the swap COMPLETED: whoever holds the preimage proves it and the order closes.
    # The principal is not here (it moved through the L1 HTLC), so this returns the maker's collateral and
    # pays the tip. Publishing the limbs also puts the secret on NADO, where the counterparty or a
    # watchtower can read it — which is how the other leg still gets claimed if someone goes offline.
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
        # all four constraints, on the SAME limbs — see WIDE HASHLOCK
        m.require(zkpy.hash(m.arg(1) + HDOM[0], m.arg(2), m.arg(3), m.arg(4), m.arg(5)) == m.slot(HVM, o).get())
        m.require(zkpy.hash(m.arg(1) + HDOM[1], m.arg(2), m.arg(3), m.arg(4), m.arg(5)) == m.slot(HV1, o).get())
        m.require(zkpy.hash(m.arg(1) + HDOM[2], m.arg(2), m.arg(3), m.arg(4), m.arg(5)) == m.slot(HV2, o).get())
        m.require(zkpy.hash(m.arg(1) + HDOM[3], m.arg(2), m.arg(3), m.arg(4), m.arg(5)) == m.slot(HV3, o).get())
        m.jnz(m.slot(PHELD, o).get() == 0, "pskip")             # COMPLETION: the collateral goes home
        m.pay(m.slot(MAKER, o).get(), m.slot(PHELD, o).get())
        m.label("pskip")
        m.slot(PHELD, o).set(m.const(0))
        m.slot(S0 + 0, o).set(m.arg(1))
        m.slot(S0 + 1, o).set(m.arg(2))
        m.slot(S0 + 2, o).set(m.arg(3))
        m.slot(S0 + 3, o).set(m.arg(4))
        m.slot(S0 + 4, o).set(m.arg(5))
        m.slot(ST, o).set(m.const(SETTLED))
        b = m.set(m.slot(BNTY, o).get(), "b")                   # the §8 bounty goes to WHOEVER settled
        m.slot(BNTY, o).set(m.const(0))
        m.jnz(b == 0, "bdone")
        m.pay(m.caller(), b)
        m.label("bdone")
        m.ret(o)                                                # (`esc` here would be another method's register)

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
        m.ret(o)                                                # HID is always 0 for an intra order

    # expire(o) — anyone, at/after expn. The no-authority safety valve: a stuck order always drains back to
    # whoever funded its escrow (ASK -> maker, filled BID -> taker), callable by anybody, never trapped.
    # release(o) — maker only: a fill costs nothing, so a taker who fills and never performs would otherwise
    # lock the order (and, for a BID, the maker's foreign lock) for the whole window. If NO NADO leg has been
    # bound within FILL_WINDOW blocks of the fill, the maker may put the order back to OPEN. Safe in both
    # kinds: for a BID the taker owes the NADO lock (none bound = they did nothing); for an ASK the maker
    # owes it and locks FIRST, so with none bound no taker can have funded a foreign leg against it yet.
    # 2026-08-29: the first real taker filled a mainnet bid and walked; this is what that taught.
    with c.method("release") as m:
        o = m.arg(0)
        m.require(o > 0)
        m.require(o < ID_MAX)
        m.require(m.slot(MK, o).get() == 1)
        m.require(m.slot(ST, o).get() == FILLED)
        m.require(m.slot(MAKER, o).get() == m.caller())
        m.require(m.slot(HID, o).get() == 0)                    # nothing bound: nobody has anything at risk here
        m.require(m.slot(FILLH, o).get() + FILL_WINDOW < m.cursor() + 1)   # the taker had their window
        m.slot(TAKER, o).set(m.const(0))
        m.slot(TADR, o).set(m.const(0))
        m.slot(FREF, o).set(m.const(0))
        m.slot(FILLH, o).set(m.const(0))
        m.slot(ST, o).set(m.const(OPEN))
        m.ret(o)

    with c.method("expire") as m:
        o = m.arg(0)
        m.require(o > 0)
        m.require(o < ID_MAX)                                   # slots alias above 2^32 (audit)
        m.require(m.slot(MK, o).get() == 1)
        st = m.set(m.slot(ST, o).get(), "st")
        m.require((st - OPEN) * (st - FILLED) == 0)
        m.require(m.slot(EXPN, o).get() < m.cursor() + 1)       # cursor >= expn
        # The collateral goes HOME, filled or not. It used to forfeit to the taker when an order expired
        # filled ("the maker walked") — but this contract cannot see the foreign chain, so it cannot tell
        # a walking maker from a taker who filled and never performed. A fill costs nothing, so that
        # forfeit was free money for any taker, and the maker's only escape (settle) revealed the secret
        # while the L1 lock was still claimable. A deposit judged on a fact nobody here can observe is
        # not a deposit; it is a bounty for griefing.
        m.jnz(m.slot(PHELD, o).get() == 0, "pskip")
        m.pay(m.slot(MAKER, o).get(), m.slot(PHELD, o).get())
        m.label("pskip")
        m.slot(PHELD, o).set(m.const(0))
        esc = m.set(m.slot(ESC, o).get(), "esc")                # only a SWAP_INTRA order escrows here
        m.slot(ESC, o).set(m.const(0))
        m.slot(ST, o).set(m.const(REFUNDED))
        m.jnz(esc == 0, "done")
        tgt = m.set(m.slot(MAKER, o).get(), "tgt")              # intra escrow is always the maker's
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
    "post":   {"args": ["orderId", "kind", "nadoAmt", "wantChain", "wantAmt", "wantAddr", "shaHashlock",
                        "vmHi0", "vmLo0", "vmHi1", "vmLo1", "vmHi2", "vmLo2", "vmHi3", "vmLo3",
                        "expiryN", "expiryF"], "value": True},
    "cancel": {"args": ["orderId"]},
    "fill":   {"args": ["orderId", "takerAddr", "foreignRef"], "value": True},
    "settle": {"args": ["orderId", "l0", "l1", "l2", "l3", "l4"]},
    "bind":   {"args": ["orderId", "l1HtlcId"]},
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
                 "hv1": {"field": HV1, "index": "orders"}, "hv2": {"field": HV2, "index": "orders"},
                 "hv3": {"field": HV3, "index": "orders"},
                 "expn": {"field": EXPN, "index": "orders"}, "expf": {"field": EXPF, "index": "orders"},
                 "st": {"field": ST, "index": "orders"}, "taker": {"field": TAKER, "index": "orders"},
                 "tadr": {"field": TADR, "index": "orders"}, "fref": {"field": FREF, "index": "orders"}, "hid": {"field": HID, "index": "orders"}, "fillh": {"field": FILLH, "index": "orders"},
                 "s0": {"field": S0, "index": "orders"}, "s1": {"field": S0 + 1, "index": "orders"},
                 "s2": {"field": S0 + 2, "index": "orders"}, "s3": {"field": S0 + 3, "index": "orders"},
                 "s4": {"field": S0 + 4, "index": "orders"},
                 "gast": {"field": GAST, "index": "orders"}, "wast": {"field": WAST, "index": "orders"},
                 "want": {"field": WANT, "index": "orders"},
                 "bnty": {"field": BNTY, "index": "orders"},
                 "prem": {"field": PREM, "index": "orders"}, "pheld": {"field": PHELD, "index": "orders"}},
        "indexes": {"orders": {"cnt": 0, "list": LIST}},
        "addr": ["maker", "taker", "wch", "wamt", "wadr", "tadr", "hsha", "fref", "hid"],
    },
}
