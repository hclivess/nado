"""NFT — the marketplace for native-asset NFTs (nft.nadochain.com, 2026-11-01): royalties, collections, profiles,
fixed-price listings, token and collection offers, English and Dutch auctions, and a sales log. objkt.com is the bar.

AN NFT IS A NATIVE ASSET. A creator issues it with an ordinary `asset_create` blob — `dec` 0, `supply` = the edition count,
`mintable` false, `uri` the IPFS link of its metadata — so it lives in every wallet's Assets tab, moves with
`asset_transfer` like any token and carries across a reroll with the asset ledger. This contract never owns the ledger;
it ESCROWS units while they are listed or auctioned and moves them with `apay` when a trade completes. (The alternative,
ownership in contract storage the way pets keeps it, was rejected: such an NFT exists only inside one app.)

ROYALTIES ARE PROVEN, NOT CLAIMED. An asset id is `hash(issuer_digest, seed)` (execnode/state.asset_id), so `register`
checks `hash(caller, seed) == asset` IN-CIRCUIT: only the account that issued the asset can attach a royalty to it,
choose its collection, or register it at all, and it can do so once. The royalty is then paid on EVERY sale this
contract settles — listing, offer, English or Dutch auction — before the seller is paid. An unregistered asset trades
with no royalty. As on objkt, a royalty binds trades through this marketplace; a direct `asset_transfer` is the
owner's own business.

EVERY PAYOUT, in one place (_payout): royalty = amount·bps // 10000 to the creator, then the marketplace fee
(FEE_BPS, 0 — no rake today, like the DEX; turning one on is an operator decision and a code change), then the rest to the
seller. Amounts are raw NADO bounded below 2^62 at every entry, so amount·bps is exact on the 256-bit word.

NOTHING LOOPS. A call's work is bounded (zkvm2 GAS_LIMIT; a block's step budget), so every action settles in O(1): an
outbid bidder is refunded inside the bid that beats them, a collection offer is accepted one asset per call, a Dutch
price is one subtraction and one division. Every escrowed unit and every escrowed raw has an exit for whoever funded
it: unlist / cancel_auction (no bids) / dcancel return the seller's units, cancel_offer and expire_offer refund a
bidder, and settle_auction — callable by ANYONE once the auction ends — pays out or returns the lot.

NO STRINGS IN THE VM: names, descriptions, bios and avatar links are string ARGS, which the call boundary digests and
registers (runtimes.zkvm_statement); the page reads them back as text through the view schema's `addr` list. Media lives
off-chain (IPFS), named by the asset's `uri`.

IDS: every listing, offer, auction, collection, token and profile id is a frontend-chosen int in (0, 2^32) — a larger
one would alias another field's slots (the storage-aliasing class, finding C2). Asset ids are 256-bit words passed
whole (the SDK sends them as {$big}). Per-asset lookups (an asset's token entry, an account's profile) are hash-keyed
cells; everything the page lists is index-keyed and enumerable.

Storage (field * 2^32 + id; counts at field 0):
  counts: 1 colls 2 tokens 3 profiles 4 listings 5 offers 6 auctions 7 dutch 8 sales; scratch 16 17 18 (0 between calls)
  collection c: 40 mk 41 owner 42 name 43 desc 44 LIST
  token t:      50 mk 51 asset 52 creator 53 bps 54 coll 55 height 56 LIST   (+ hash(K_TOK, asset) -> t)
  profile p:    60 mk 61 addr 62 name 63 bio 64 avatar 65 LIST               (+ hash(K_PRO, caller) -> p)
  listing l:    70 mk 71 seller 72 asset 73 left 74 price(per unit) 75 st 76 height 77 LIST
  offer o:      80 mk 81 bidder 82 asset(0 = collection offer) 83 coll 84 left 85 price(per unit) 86 exp(0 = none)
                87 st 88 LIST
  auction a:    90 mk 91 seller 92 asset 93 qty 94 reserve 95 end 96 bid 97 bidder 98 st 99 LIST
  dutch d:      100 mk 101 seller 102 asset 103 left 104 start price 105 end price 106 start height 107 duration
                108 st 109 LIST
  sale s (1..): 120 kind(1 listing 2 offer 3 auction 4 dutch) 121 asset 122 units 123 amount 124 buyer 125 seller
                126 height 127 LIST
"""
from execnode import zkpy
from execnode.games import _lib

CNT_COLLS, CNT_TOKENS, CNT_PROFILES, CNT_LISTINGS, CNT_OFFERS, CNT_AUCTIONS, CNT_DUTCH, CNT_SALES = 1, 2, 3, 4, 5, 6, 7, 8
SCR_T, SCR_R, SCR_E = 16, 17, 18             # scratch cells at field 0, always 0 between calls (see _payout)
C_MK, C_OWNER, C_NAME, C_DESC, C_LIST = 40, 41, 42, 43, 44
T_MK, T_ASSET, T_CREATOR, T_BPS, T_COLL, T_H, T_LIST = 50, 51, 52, 53, 54, 55, 56
P_MK, P_ADDR, P_NAME, P_BIO, P_AV, P_LIST = 60, 61, 62, 63, 64, 65
L_MK, L_SELLER, L_ASSET, L_LEFT, L_PRICE, L_ST, L_H, L_LIST = 70, 71, 72, 73, 74, 75, 76, 77
O_MK, O_BIDDER, O_ASSET, O_COLL, O_LEFT, O_PRICE, O_EXP, O_ST, O_LIST = 80, 81, 82, 83, 84, 85, 86, 87, 88
A_MK, A_SELLER, A_ASSET, A_QTY, A_RESERVE, A_END, A_BID, A_BIDDER, A_ST, A_LIST = 90, 91, 92, 93, 94, 95, 96, 97, 98, 99
D_MK, D_SELLER, D_ASSET, D_LEFT, D_SP, D_EP, D_H0, D_DUR, D_ST, D_LIST = 100, 101, 102, 103, 104, 105, 106, 107, 108, 109
S_KIND, S_ASSET, S_N, S_AMT, S_BUYER, S_SELLER, S_H, S_LIST = 120, 121, 122, 123, 124, 125, 126, 127

K_TOK, K_PRO = 0x4E46544B, 0x4E465450        # hash-key tags ("NFTK", "NFTP"); a hash never lands on a field*2^32+id slot
OPEN, DONE, CANCELLED, EXPIRED = 1, 2, 3, 4    # DONE: sold out / filled / settled
SALE_LISTING, SALE_OFFER, SALE_AUCTION, SALE_DUTCH = 1, 2, 3, 4

ID_MAX = 1 << 32
AMT_MAX = 1 << 62                  # every NADO amount, price and unit count is below this (asset supply cap is 2^62)
BPS = 10_000
MAX_ROYALTY_BPS = 2_500            # 25 %, objkt's ceiling
FEE_BPS = 0                        # the marketplace fee: none (see EVERY PAYOUT above)
MIN_RAISE_BPS = 500                # a bid must beat the current one by 5 %
EXTEND = 50                        # blocks (~5 min): a bid this close to the end pushes the end out to here
MIN_DUR, MAX_DUR = 60, 201_600     # auction length in blocks: ~6 min .. ~2 weeks at the 6 s cadence


def _id(m, i):
    """Arg i is a fresh-or-known entity id in (0, 2^32): above it the id aliases another field's slots (finding C2)."""
    m.require(m.arg(i) > 0)
    m.require(m.arg(i) < ID_MAX)


def _amt(m, v):
    m.require(v > 0)
    m.require(v < m.const(AMT_MAX))


def _push(m, cnt_key, list_field, ident):
    """Append `ident` to an index: list[count] = ident, count += 1."""
    m.slot(list_field, m.slot(0, m.const(cnt_key)).get()).set(ident)
    m.slot(0, m.const(cnt_key)).set(m.slot(0, m.const(cnt_key)).get() + 1)


def _payout(m, amount, asset, seller, tag):
    """Pay `amount` (raw NADO) for units of `asset`: royalty to its registered creator, the fee, the rest to `seller`.
    ONE definition for every way a trade completes, so the split cannot drift between them. Its two intermediates (the
    token id, the royalty) live in scratch cells it clears before returning, so it pins no register — the zkpy pool has
    six, and a sale's own values already hold some of them."""
    tok = lambda: m.slot(0, m.const(SCR_T)).get()
    roy = lambda: m.slot(0, m.const(SCR_R)).get()
    m.slot(0, m.const(SCR_T)).set(m.at(zkpy.hash(K_TOK, asset)).get())     # 0 = unregistered (T_BPS of 0 is 0)
    m.slot(0, m.const(SCR_R)).set(amount * m.slot(T_BPS, tok()).get() // BPS)
    m.jnz(roy() == 0, f"{tag}_nroy")
    m.pay(m.slot(T_CREATOR, tok()).get(), roy())
    m.label(f"{tag}_nroy")
    if FEE_BPS:                                                  # compiled out at 0: no fee recipient exists today
        raise NotImplementedError("a marketplace fee needs a recipient decision (operator)")
    m.jnz(amount - roy() == 0, f"{tag}_nsel")
    m.pay(seller, amount - roy())
    m.label(f"{tag}_nsel")
    m.slot(0, m.const(SCR_T)).set(m.const(0))                    # writing 0 deletes the cell: no storage left behind
    m.slot(0, m.const(SCR_R)).set(m.const(0))


def _log_sale(m, kind, asset, units, amount, buyer, seller):
    """Append one sale: the activity feed and the price history read these (there are no events on the exec layer)."""
    m.slot(0, m.const(CNT_SALES)).set(m.slot(0, m.const(CNT_SALES)).get() + 1)
    s = lambda: m.slot(0, m.const(CNT_SALES)).get()             # the new sale's id (1-based)
    m.slot(S_KIND, s()).set(m.const(kind))
    m.slot(S_ASSET, s()).set(asset)
    m.slot(S_N, s()).set(units)
    m.slot(S_AMT, s()).set(amount)
    m.slot(S_BUYER, s()).set(buyer)
    m.slot(S_SELLER, s()).set(seller)
    m.slot(S_H, s()).set(m.cursor())
    m.slot(S_LIST, s() - 1).set(s())


def build():
    c = zkpy.Contract()

    # ---- collections, tokens, profiles -------------------------------------------------------------------------
    # create_collection(c, name, desc) — anyone; the caller owns it and is the only one who may file tokens under it.
    with c.method("create_collection") as m:
        _id(m, 0)
        m.require(m.in_asset() == 0)
        m.require(m.value() == 0)
        m.require(m.slot(C_MK, m.arg(0)).get() == 0)
        m.slot(C_MK, m.arg(0)).set(m.const(1))
        m.slot(C_OWNER, m.arg(0)).set(m.caller())
        m.slot(C_NAME, m.arg(0)).set(m.arg(1))
        m.slot(C_DESC, m.arg(0)).set(m.arg(2))
        _push(m, CNT_COLLS, C_LIST, m.arg(0))
        m.ret(m.arg(0))

    # edit_collection(c, name, desc) — its owner.
    with c.method("edit_collection") as m:
        _id(m, 0)
        m.require(m.in_asset() == 0)
        m.require(m.value() == 0)
        m.require(m.slot(C_MK, m.arg(0)).get() == 1)
        m.require(m.slot(C_OWNER, m.arg(0)).get() == m.caller())
        m.slot(C_NAME, m.arg(0)).set(m.arg(1))
        m.slot(C_DESC, m.arg(0)).set(m.arg(2))
        m.ret(m.arg(0))

    # register(t, asset, seed, bps, coll) — the asset's ISSUER, once per asset: proves hash(caller, seed) == asset, fixes
    # its royalty (<= 25 %) and files it under one of the caller's collections (0 = none).
    with c.method("register") as m:
        _id(m, 0)
        m.require(m.in_asset() == 0)
        m.require(m.value() == 0)
        m.require(m.slot(T_MK, m.arg(0)).get() == 0)
        m.require(m.arg(1) != 0)
        m.require(zkpy.hash(m.caller(), m.arg(2)) == m.arg(1))           # THE CREATOR PROOF (asset_id's derivation)
        m.require(m.at(zkpy.hash(K_TOK, m.arg(1))).get() == 0)           # once per asset
        m.require(m.arg(3) < MAX_ROYALTY_BPS + 1)
        m.jnz(m.arg(4) == 0, "nocoll")
        m.require(m.arg(4) < ID_MAX)
        m.require(m.slot(C_MK, m.arg(4)).get() == 1)
        m.require(m.slot(C_OWNER, m.arg(4)).get() == m.caller())
        m.label("nocoll")
        m.slot(T_MK, m.arg(0)).set(m.const(1))
        m.slot(T_ASSET, m.arg(0)).set(m.arg(1))
        m.slot(T_CREATOR, m.arg(0)).set(m.caller())
        m.slot(T_BPS, m.arg(0)).set(m.arg(3))
        m.slot(T_COLL, m.arg(0)).set(m.arg(4))
        m.slot(T_H, m.arg(0)).set(m.cursor())
        m.at(zkpy.hash(K_TOK, m.arg(1))).set(m.arg(0))
        _push(m, CNT_TOKENS, T_LIST, m.arg(0))
        m.ret(m.arg(0))

    # set_profile(p, name, bio, avatar) — the caller's one profile: the first call claims the fresh id p, later calls
    # must name the same p.
    with c.method("set_profile") as m:
        _id(m, 0)
        m.require(m.in_asset() == 0)
        m.require(m.value() == 0)
        m.jnz(m.at(zkpy.hash(K_PRO, m.caller())).get() != 0, "have")
        m.require(m.slot(P_MK, m.arg(0)).get() == 0)
        m.slot(P_MK, m.arg(0)).set(m.const(1))
        m.slot(P_ADDR, m.arg(0)).set(m.caller())
        m.at(zkpy.hash(K_PRO, m.caller())).set(m.arg(0))
        _push(m, CNT_PROFILES, P_LIST, m.arg(0))
        m.label("have")
        m.require(m.at(zkpy.hash(K_PRO, m.caller())).get() == m.arg(0))
        m.slot(P_NAME, m.arg(0)).set(m.arg(1))
        m.slot(P_BIO, m.arg(0)).set(m.arg(2))
        m.slot(P_AV, m.arg(0)).set(m.arg(3))
        m.ret(m.arg(0))

    # ---- fixed-price listings ----------------------------------------------------------------------------------
    # list(l, asset, price) [VALUE = the units, of `asset`] — escrows the units at `price` raw NADO each.
    with c.method("list") as m:
        _id(m, 0)
        m.require(m.slot(L_MK, m.arg(0)).get() == 0)
        m.require(m.arg(1) != 0)
        m.require(m.in_asset() == m.arg(1))
        _amt(m, m.value())
        _amt(m, m.arg(2))
        m.slot(L_MK, m.arg(0)).set(m.const(1))
        m.slot(L_SELLER, m.arg(0)).set(m.caller())
        m.slot(L_ASSET, m.arg(0)).set(m.arg(1))
        m.slot(L_LEFT, m.arg(0)).set(m.value())
        m.slot(L_PRICE, m.arg(0)).set(m.arg(2))
        m.slot(L_ST, m.arg(0)).set(m.const(OPEN))
        m.slot(L_H, m.arg(0)).set(m.cursor())
        _push(m, CNT_LISTINGS, L_LIST, m.arg(0))
        m.ret(m.arg(0))

    # buy(l, n) [VALUE = n * price, native] — n units, paid out at once (royalty, seller); the units go to the caller.
    with c.method("buy") as m:
        _id(m, 0)
        m.require(m.slot(L_MK, m.arg(0)).get() == 1)
        m.require(m.slot(L_ST, m.arg(0)).get() == OPEN)
        m.require(m.in_asset() == 0)
        _amt(m, m.arg(1))
        m.require(m.arg(1) < m.slot(L_LEFT, m.arg(0)).get() + 1)
        amt = m.set(m.value(), "amt")
        m.require(amt == m.arg(1) * m.slot(L_PRICE, m.arg(0)).get())   # both < 2^62: the product is exact
        _payout(m, amt, m.slot(L_ASSET, m.arg(0)).get(), m.slot(L_SELLER, m.arg(0)).get(), "p")
        m.apay(m.slot(L_ASSET, m.arg(0)).get(), m.caller(), m.arg(1))
        m.slot(L_LEFT, m.arg(0)).set(m.slot(L_LEFT, m.arg(0)).get() - m.arg(1))
        m.jnz(m.slot(L_LEFT, m.arg(0)).get() != 0, "more")
        m.slot(L_ST, m.arg(0)).set(m.const(DONE))
        m.label("more")
        _log_sale(m, SALE_LISTING, m.slot(L_ASSET, m.arg(0)).get(), m.arg(1), amt, m.caller(),
                  m.slot(L_SELLER, m.arg(0)).get())
        m.ret(m.slot(L_LEFT, m.arg(0)).get())

    # reprice(l, price) — the seller, while open.
    with c.method("reprice") as m:
        _id(m, 0)
        m.require(m.in_asset() == 0)
        m.require(m.value() == 0)
        m.require(m.slot(L_MK, m.arg(0)).get() == 1)
        m.require(m.slot(L_ST, m.arg(0)).get() == OPEN)
        m.require(m.slot(L_SELLER, m.arg(0)).get() == m.caller())
        _amt(m, m.arg(1))
        m.slot(L_PRICE, m.arg(0)).set(m.arg(1))
        m.ret(m.arg(1))

    # unlist(l) — the seller, while open: every unit still escrowed goes back.
    with c.method("unlist") as m:
        _id(m, 0)
        m.require(m.in_asset() == 0)
        m.require(m.value() == 0)
        m.require(m.slot(L_MK, m.arg(0)).get() == 1)
        m.require(m.slot(L_ST, m.arg(0)).get() == OPEN)
        m.require(m.slot(L_SELLER, m.arg(0)).get() == m.caller())
        m.apay(m.slot(L_ASSET, m.arg(0)).get(), m.caller(), m.slot(L_LEFT, m.arg(0)).get())
        m.slot(L_LEFT, m.arg(0)).set(m.const(0))
        m.slot(L_ST, m.arg(0)).set(m.const(CANCELLED))
        m.ret(m.arg(0))

    # ---- offers ------------------------------------------------------------------------------------------------
    # offer(o, asset, coll, n, price, exp) [VALUE = n * price, native] — for n units of ONE asset (coll = 0), or of
    # ANY asset registered in collection `coll` (asset = 0). exp is a block height (0 = until cancelled).
    with c.method("offer") as m:
        _id(m, 0)
        m.require(m.slot(O_MK, m.arg(0)).get() == 0)
        m.require(m.in_asset() == 0)
        m.require((m.arg(1) == 0) + (m.arg(2) == 0) == 1)               # exactly one target
        m.jnz(m.arg(2) == 0, "one")
        m.require(m.arg(2) < ID_MAX)
        m.require(m.slot(C_MK, m.arg(2)).get() == 1)
        m.label("one")
        _amt(m, m.arg(3))
        _amt(m, m.arg(4))
        m.require(m.value() == m.arg(3) * m.arg(4))
        m.jnz(m.arg(5) == 0, "noexp")
        m.require(m.cursor() < m.arg(5))
        m.label("noexp")
        m.slot(O_MK, m.arg(0)).set(m.const(1))
        m.slot(O_BIDDER, m.arg(0)).set(m.caller())
        m.slot(O_ASSET, m.arg(0)).set(m.arg(1))
        m.slot(O_COLL, m.arg(0)).set(m.arg(2))
        m.slot(O_LEFT, m.arg(0)).set(m.arg(3))
        m.slot(O_PRICE, m.arg(0)).set(m.arg(4))
        m.slot(O_EXP, m.arg(0)).set(m.arg(5))
        m.slot(O_ST, m.arg(0)).set(m.const(OPEN))
        _push(m, CNT_OFFERS, O_LIST, m.arg(0))
        m.ret(m.arg(0))

    # accept(o) [VALUE = k units of the offered asset, or of any asset of the offered collection] — the caller sells k
    # units into the offer: paid out at once, the units go to the bidder.
    with c.method("accept") as m:
        _id(m, 0)
        m.require(m.slot(O_MK, m.arg(0)).get() == 1)
        m.require(m.slot(O_ST, m.arg(0)).get() == OPEN)
        a = m.set(m.in_asset(), "a")
        m.require(a != 0)
        _amt(m, m.value())
        m.require(m.value() < m.slot(O_LEFT, m.arg(0)).get() + 1)
        m.jnz(m.slot(O_EXP, m.arg(0)).get() == 0, "live")
        m.require(m.cursor() < m.slot(O_EXP, m.arg(0)).get())
        m.label("live")
        m.jnz(m.slot(O_ASSET, m.arg(0)).get() == 0, "coll")
        m.require(a == m.slot(O_ASSET, m.arg(0)).get())
        m.jmp("matched")
        m.label("coll")                                                  # a collection offer: any of its assets
        m.require(m.slot(T_COLL, m.at(zkpy.hash(K_TOK, a)).get()).get() == m.slot(O_COLL, m.arg(0)).get())
        m.require(m.at(zkpy.hash(K_TOK, a)).get() != 0)
        m.label("matched")
        amt = m.set(m.value() * m.slot(O_PRICE, m.arg(0)).get(), "amt")
        _payout(m, amt, a, m.caller(), "p")
        m.apay(a, m.slot(O_BIDDER, m.arg(0)).get(), m.value())
        m.slot(O_LEFT, m.arg(0)).set(m.slot(O_LEFT, m.arg(0)).get() - m.value())
        m.jnz(m.slot(O_LEFT, m.arg(0)).get() != 0, "more")
        m.slot(O_ST, m.arg(0)).set(m.const(DONE))
        m.label("more")
        _log_sale(m, SALE_OFFER, a, m.value(), amt, m.slot(O_BIDDER, m.arg(0)).get(), m.caller())
        m.ret(m.slot(O_LEFT, m.arg(0)).get())

    # cancel_offer(o) — the bidder, while open: the unspent escrow comes back.
    with c.method("cancel_offer") as m:
        _id(m, 0)
        m.require(m.in_asset() == 0)
        m.require(m.value() == 0)
        m.require(m.slot(O_MK, m.arg(0)).get() == 1)
        m.require(m.slot(O_ST, m.arg(0)).get() == OPEN)
        m.require(m.slot(O_BIDDER, m.arg(0)).get() == m.caller())
        m.pay(m.caller(), m.slot(O_LEFT, m.arg(0)).get() * m.slot(O_PRICE, m.arg(0)).get())
        m.slot(O_LEFT, m.arg(0)).set(m.const(0))
        m.slot(O_ST, m.arg(0)).set(m.const(CANCELLED))
        m.ret(m.arg(0))

    # expire_offer(o) — ANYONE, at/after the offer's expiry: the unspent escrow goes back to the bidder.
    with c.method("expire_offer") as m:
        _id(m, 0)
        m.require(m.in_asset() == 0)
        m.require(m.value() == 0)
        m.require(m.slot(O_MK, m.arg(0)).get() == 1)
        m.require(m.slot(O_ST, m.arg(0)).get() == OPEN)
        m.require(m.slot(O_EXP, m.arg(0)).get() != 0)
        m.require(m.slot(O_EXP, m.arg(0)).get() < m.cursor() + 1)
        m.pay(m.slot(O_BIDDER, m.arg(0)).get(), m.slot(O_LEFT, m.arg(0)).get() * m.slot(O_PRICE, m.arg(0)).get())
        m.slot(O_LEFT, m.arg(0)).set(m.const(0))
        m.slot(O_ST, m.arg(0)).set(m.const(EXPIRED))
        m.ret(m.arg(0))

    # ---- English auctions ---------------------------------------------------------------------------------------
    # auction(a, asset, reserve, dur) [VALUE = the units, of `asset`] — one lot of all the units, ends `dur` blocks out.
    with c.method("auction") as m:
        _id(m, 0)
        m.require(m.slot(A_MK, m.arg(0)).get() == 0)
        m.require(m.arg(1) != 0)
        m.require(m.in_asset() == m.arg(1))
        _amt(m, m.value())
        _amt(m, m.arg(2))
        m.require(m.const(MIN_DUR) < m.arg(3) + 1)
        m.require(m.arg(3) < MAX_DUR + 1)
        m.slot(A_MK, m.arg(0)).set(m.const(1))
        m.slot(A_SELLER, m.arg(0)).set(m.caller())
        m.slot(A_ASSET, m.arg(0)).set(m.arg(1))
        m.slot(A_QTY, m.arg(0)).set(m.value())
        m.slot(A_RESERVE, m.arg(0)).set(m.arg(2))
        m.slot(A_END, m.arg(0)).set(m.cursor() + m.arg(3))
        m.slot(A_ST, m.arg(0)).set(m.const(OPEN))
        _push(m, CNT_AUCTIONS, A_LIST, m.arg(0))
        m.ret(m.arg(0))

    # bid(a) [VALUE = the bid, native] — at least the reserve and 5 % over the current bid; the bid it beats is refunded
    # in this same call, and a bid within EXTEND blocks of the end pushes the end out to EXTEND blocks from now.
    with c.method("bid") as m:
        _id(m, 0)
        m.require(m.slot(A_MK, m.arg(0)).get() == 1)
        m.require(m.slot(A_ST, m.arg(0)).get() == OPEN)
        m.require(m.in_asset() == 0)
        m.require(m.cursor() < m.slot(A_END, m.arg(0)).get())
        m.require(m.slot(A_SELLER, m.arg(0)).get() != m.caller())
        v = m.set(m.value(), "v")
        _amt(m, v)
        m.require(m.slot(A_RESERVE, m.arg(0)).get() < v + 1)
        m.require(m.slot(A_BID, m.arg(0)).get() * (BPS + MIN_RAISE_BPS) < v * BPS + 1)
        m.jnz(m.slot(A_BID, m.arg(0)).get() == 0, "first")
        m.pay(m.slot(A_BIDDER, m.arg(0)).get(), m.slot(A_BID, m.arg(0)).get())   # the outbid refund
        m.label("first")
        m.slot(A_BID, m.arg(0)).set(v)
        m.slot(A_BIDDER, m.arg(0)).set(m.caller())
        m.jnz(m.cursor() + EXTEND < m.slot(A_END, m.arg(0)).get(), "noext")
        m.slot(A_END, m.arg(0)).set(m.cursor() + EXTEND)                         # anti-snipe
        m.label("noext")
        m.ret(m.slot(A_END, m.arg(0)).get())

    # settle_auction(a) — ANYONE, at/after the end: the winner gets the lot and the seller is paid; with no bid the lot
    # goes back to the seller.
    with c.method("settle_auction") as m:
        _id(m, 0)
        m.require(m.in_asset() == 0)
        m.require(m.value() == 0)
        m.require(m.slot(A_MK, m.arg(0)).get() == 1)
        m.require(m.slot(A_ST, m.arg(0)).get() == OPEN)
        m.require(m.slot(A_END, m.arg(0)).get() < m.cursor() + 1)
        m.slot(A_ST, m.arg(0)).set(m.const(DONE))
        m.jnz(m.slot(A_BID, m.arg(0)).get() != 0, "sold")
        m.apay(m.slot(A_ASSET, m.arg(0)).get(), m.slot(A_SELLER, m.arg(0)).get(), m.slot(A_QTY, m.arg(0)).get())
        m.ret(m.const(0))
        m.label("sold")
        amt = m.set(m.slot(A_BID, m.arg(0)).get(), "amt")
        _payout(m, amt, m.slot(A_ASSET, m.arg(0)).get(), m.slot(A_SELLER, m.arg(0)).get(), "p")
        m.apay(m.slot(A_ASSET, m.arg(0)).get(), m.slot(A_BIDDER, m.arg(0)).get(), m.slot(A_QTY, m.arg(0)).get())
        _log_sale(m, SALE_AUCTION, m.slot(A_ASSET, m.arg(0)).get(), m.slot(A_QTY, m.arg(0)).get(), amt,
                  m.slot(A_BIDDER, m.arg(0)).get(), m.slot(A_SELLER, m.arg(0)).get())
        m.ret(amt)

    # cancel_auction(a) — the seller, while nobody has bid.
    with c.method("cancel_auction") as m:
        _id(m, 0)
        m.require(m.in_asset() == 0)
        m.require(m.value() == 0)
        m.require(m.slot(A_MK, m.arg(0)).get() == 1)
        m.require(m.slot(A_ST, m.arg(0)).get() == OPEN)
        m.require(m.slot(A_SELLER, m.arg(0)).get() == m.caller())
        m.require(m.slot(A_BID, m.arg(0)).get() == 0)
        m.apay(m.slot(A_ASSET, m.arg(0)).get(), m.caller(), m.slot(A_QTY, m.arg(0)).get())
        m.slot(A_ST, m.arg(0)).set(m.const(CANCELLED))
        m.ret(m.arg(0))

    # ---- Dutch auctions -----------------------------------------------------------------------------------------
    # dutch(d, asset, startPrice, endPrice, dur) [VALUE = the units] — the per-unit price falls linearly from start to
    # end over `dur` blocks and stays at end after that.
    with c.method("dutch") as m:
        _id(m, 0)
        m.require(m.slot(D_MK, m.arg(0)).get() == 0)
        m.require(m.arg(1) != 0)
        m.require(m.in_asset() == m.arg(1))
        _amt(m, m.value())
        _amt(m, m.arg(2))
        _amt(m, m.arg(3))
        m.require(m.arg(3) < m.arg(2))
        m.require(m.const(MIN_DUR) < m.arg(4) + 1)
        m.require(m.arg(4) < MAX_DUR + 1)
        m.slot(D_MK, m.arg(0)).set(m.const(1))
        m.slot(D_SELLER, m.arg(0)).set(m.caller())
        m.slot(D_ASSET, m.arg(0)).set(m.arg(1))
        m.slot(D_LEFT, m.arg(0)).set(m.value())
        m.slot(D_SP, m.arg(0)).set(m.arg(2))
        m.slot(D_EP, m.arg(0)).set(m.arg(3))
        m.slot(D_H0, m.arg(0)).set(m.cursor())
        m.slot(D_DUR, m.arg(0)).set(m.arg(4))
        m.slot(D_ST, m.arg(0)).set(m.const(OPEN))
        _push(m, CNT_DUTCH, D_LIST, m.arg(0))
        m.ret(m.arg(0))

    # dbuy(d, n, maxPrice) [VALUE = n * maxPrice, native] — n units at the CURRENT price (it moves every block, so the
    # buyer names a ceiling); the difference comes straight back to the buyer.
    with c.method("dbuy") as m:
        _id(m, 0)
        m.require(m.slot(D_MK, m.arg(0)).get() == 1)
        m.require(m.slot(D_ST, m.arg(0)).get() == OPEN)
        m.require(m.in_asset() == 0)
        _amt(m, m.arg(1))
        _amt(m, m.arg(2))
        m.require(m.arg(1) < m.slot(D_LEFT, m.arg(0)).get() + 1)
        m.require(m.value() == m.arg(1) * m.arg(2))
        el = lambda: m.slot(0, m.const(SCR_E)).get()                          # blocks elapsed, capped at dur
        m.slot(0, m.const(SCR_E)).set(m.cursor() - m.slot(D_H0, m.arg(0)).get())
        m.slot(0, m.const(SCR_E)).set(zkpy.select(m.slot(D_DUR, m.arg(0)).get() < el(), m.slot(D_DUR, m.arg(0)).get(),
                                                  el()))
        p = m.set(m.slot(D_SP, m.arg(0)).get()
                  - (m.slot(D_SP, m.arg(0)).get() - m.slot(D_EP, m.arg(0)).get()) * el() // m.slot(D_DUR, m.arg(0)).get(),
                  "p")
        m.slot(0, m.const(SCR_E)).set(m.const(0))
        m.require(p < m.arg(2) + 1)
        amt = m.set(m.arg(1) * p, "amt")
        _payout(m, amt, m.slot(D_ASSET, m.arg(0)).get(), m.slot(D_SELLER, m.arg(0)).get(), "q")
        m.jnz(m.value() == amt, "exact")
        m.pay(m.caller(), m.value() - amt)                                       # the ceiling's change
        m.label("exact")
        m.apay(m.slot(D_ASSET, m.arg(0)).get(), m.caller(), m.arg(1))
        m.slot(D_LEFT, m.arg(0)).set(m.slot(D_LEFT, m.arg(0)).get() - m.arg(1))
        m.jnz(m.slot(D_LEFT, m.arg(0)).get() != 0, "more")
        m.slot(D_ST, m.arg(0)).set(m.const(DONE))
        m.label("more")
        _log_sale(m, SALE_DUTCH, m.slot(D_ASSET, m.arg(0)).get(), m.arg(1), amt, m.caller(),
                  m.slot(D_SELLER, m.arg(0)).get())
        m.ret(p)

    # dcancel(d) — the seller, while open: every unit still escrowed goes back.
    with c.method("dcancel") as m:
        _id(m, 0)
        m.require(m.in_asset() == 0)
        m.require(m.value() == 0)
        m.require(m.slot(D_MK, m.arg(0)).get() == 1)
        m.require(m.slot(D_ST, m.arg(0)).get() == OPEN)
        m.require(m.slot(D_SELLER, m.arg(0)).get() == m.caller())
        m.apay(m.slot(D_ASSET, m.arg(0)).get(), m.caller(), m.slot(D_LEFT, m.arg(0)).get())
        m.slot(D_LEFT, m.arg(0)).set(m.const(0))
        m.slot(D_ST, m.arg(0)).set(m.const(CANCELLED))
        m.ret(m.arg(0))

    # ---- read-only views (/exec/view) ---------------------------------------------------------------------------
    # token_of(asset) -> its token id (0 = unregistered); profile_of(addr) -> the address's profile id (0 = none)
    with c.method("token_of") as m:
        m.ret(m.at(zkpy.hash(K_TOK, m.arg(0))).get())
    with c.method("profile_of") as m:
        m.ret(m.at(zkpy.hash(K_PRO, m.arg(0))).get())

    return c.build()


# ---- the carry (tools/carry.py, doc/stwo/g5-carry.md) --------------------------------------------------------------
def carry_in_flight(storage):
    """Why this contract cannot cross the reroll yet ([] = it can). Listings and offers without an expiry are AT REST:
    their escrow is attributed (seller / bidder) and nothing in them names an old-chain height, so they cross as they
    are and keep trading. Everything that counts blocks — an open English or Dutch auction (end, start height) and an
    open offer with an expiry — is tied to OLD-CHAIN heights, so it is settled, cancelled or expired first."""
    slots = (storage or {}).get("slots") or {}
    g = lambda f, k: int(slots.get(str((f << 32) + k), 0))
    out = []
    for a in _lib.carry_ids(slots, CNT_AUCTIONS, A_LIST):
        if g(A_ST, a) == OPEN:
            out.append(f"auction {a} is open (anyone settles it at/after height {g(A_END, a)}; "
                       "its seller may cancel it while nobody has bid)")
    for d in _lib.carry_ids(slots, CNT_DUTCH, D_LIST):
        if g(D_ST, d) == OPEN:
            out.append(f"Dutch auction {d} is open (its seller cancels it, or it sells out)")
    for o in _lib.carry_ids(slots, CNT_OFFERS, O_LIST):
        if g(O_ST, o) == OPEN and g(O_EXP, o):
            out.append(f"offer {o} is open with an expiry at height {g(O_EXP, o)} (its bidder cancels it, or anyone "
                       "expires it from then)")
    return out


_IX = {"colls": C_LIST, "tokens": T_LIST, "profiles": P_LIST, "listings": L_LIST, "offers": O_LIST,
       "auctions": A_LIST, "dutch": D_LIST, "sales": S_LIST}
_CNT = {"colls": CNT_COLLS, "tokens": CNT_TOKENS, "profiles": CNT_PROFILES, "listings": CNT_LISTINGS,
        "offers": CNT_OFFERS, "auctions": CNT_AUCTIONS, "dutch": CNT_DUTCH, "sales": CNT_SALES}


def _maps(index, **fields):
    return {name: {"field": f, "index": index} for name, f in fields.items()}


ABI = {
    "create_collection": {"args": ["collId", "name", "desc"]},
    "edit_collection":   {"args": ["collId", "name", "desc"]},
    "register":          {"args": ["tokenId", "asset", "seed", "royaltyBps", "collId"]},
    "set_profile":       {"args": ["profileId", "name", "bio", "avatar"]},
    "list":              {"args": ["listingId", "asset", "price"], "value": True},
    "buy":               {"args": ["listingId", "units"], "value": True},
    "reprice":           {"args": ["listingId", "price"]},
    "unlist":            {"args": ["listingId"]},
    "offer":             {"args": ["offerId", "asset", "collId", "units", "price", "expiry"], "value": True},
    "accept":            {"args": ["offerId"], "value": True},
    "cancel_offer":      {"args": ["offerId"]},
    "expire_offer":      {"args": ["offerId"]},
    "auction":           {"args": ["auctionId", "asset", "reserve", "duration"], "value": True},
    "bid":               {"args": ["auctionId"], "value": True},
    "settle_auction":    {"args": ["auctionId"]},
    "cancel_auction":    {"args": ["auctionId"]},
    "dutch":             {"args": ["dutchId", "asset", "startPrice", "endPrice", "duration"], "value": True},
    "dbuy":              {"args": ["dutchId", "units", "maxPrice"], "value": True},
    "dcancel":           {"args": ["dutchId"]},
    "token_of":          {"args": ["asset"]},
    "profile_of":        {"args": ["address"]},
    "_view": {
        "maps": {
            **_maps("colls", c_mk=C_MK, c_owner=C_OWNER, c_name=C_NAME, c_desc=C_DESC),
            **_maps("tokens", t_mk=T_MK, t_asset=T_ASSET, t_creator=T_CREATOR, t_bps=T_BPS, t_coll=T_COLL, t_h=T_H),
            **_maps("profiles", p_mk=P_MK, p_addr=P_ADDR, p_name=P_NAME, p_bio=P_BIO, p_av=P_AV),
            **_maps("listings", l_mk=L_MK, l_seller=L_SELLER, l_asset=L_ASSET, l_left=L_LEFT, l_price=L_PRICE,
                    l_st=L_ST, l_h=L_H),
            **_maps("offers", o_mk=O_MK, o_bidder=O_BIDDER, o_asset=O_ASSET, o_coll=O_COLL, o_left=O_LEFT,
                    o_price=O_PRICE, o_exp=O_EXP, o_st=O_ST),
            **_maps("auctions", a_mk=A_MK, a_seller=A_SELLER, a_asset=A_ASSET, a_qty=A_QTY, a_reserve=A_RESERVE,
                    a_end=A_END, a_bid=A_BID, a_bidder=A_BIDDER, a_st=A_ST),
            **_maps("dutch", d_mk=D_MK, d_seller=D_SELLER, d_asset=D_ASSET, d_left=D_LEFT, d_sp=D_SP, d_ep=D_EP,
                    d_h0=D_H0, d_dur=D_DUR, d_st=D_ST),
            **_maps("sales", s_kind=S_KIND, s_asset=S_ASSET, s_n=S_N, s_amt=S_AMT, s_buyer=S_BUYER,
                    s_seller=S_SELLER, s_h=S_H),
        },
        "indexes": {ix: {"cnt": _CNT[ix], "list": f} for ix, f in _IX.items()},
        "addr": ["c_owner", "c_name", "c_desc", "t_creator", "p_addr", "p_name", "p_bio", "p_av", "l_seller",
                 "o_bidder", "a_seller", "a_bidder", "d_seller", "s_buyer", "s_seller"],
    },
}
