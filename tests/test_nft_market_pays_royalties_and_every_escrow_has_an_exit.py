"""
The NFT marketplace (execnode/games/nft.py) pays royalties on every kind of sale, refuses every forged or out-of-order
action, and gives every escrowed unit and every escrowed raw an exit — driven through the real ExecState.apply_blob
path the exec node runs (deploy -> asset_create -> calls), never by reading the code.

What a marketplace can get wrong and lose money by, each pinned below:
  * the creator proof — only the asset's issuer may register it (royalty, collection), once, at <= 25 %;
  * the payout split — royalty to the creator and the rest to the seller, on a listing, an offer, an English and a
    Dutch auction alike (one _payout), with nothing left behind;
  * escrow exits — unlist / cancel_offer / expire_offer / cancel_auction / settle_auction (anyone, no bid) / dcancel each
    return exactly what is left to whoever funded it;
  * auction rules — reserve, the 5 % minimum raise, the outbid refund in the same call, no seller bids, anti-snipe,
    settle only at/after the end and by anyone;
  * Dutch pricing — linear in blocks, floored at the end price, and the buyer's ceiling change refunded;
  * collection offers — accept any asset registered in that collection and nothing else;
  * conservation — at the end the contract holds exactly the escrow its open entries account for (zero here);
  * ids >= 2^32 refused (storage aliasing, finding C2);
  * the carry — an open auction or an expiring offer refuses a reroll carry, a listing or an open-ended offer crosses.

Run: python3 tests/test_nft_market_pays_royalties_and_every_escrow_has_an_exit.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): a throwaway HOME and exec files, never the live node's
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-nft-market-")
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState, asset_id
from execnode.games import nft as N

import _harness
_report = _harness.Report()
check = _report.run

ARTIST = "ndoAAAA" + "A" * 41
COLLECTOR = "ndoCCCC" + "C" * 41
BIDDER = "ndoBBBB" + "B" * 41
OTHER = "ndoOOOO" + "O" * 41
FUND = 10 ** 15
NADO = 10 ** 8                 # raw per NADO in these sums (only ratios matter)


def _fresh():
    st = ExecState(os.path.join(tempfile.mkdtemp(prefix="nado_nft_"), "s.json"))
    st.cursor = 1000
    code = N.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": N.ABI, "nonce": "n"}, ARTIST, "d")
    cid = st.contract_id(ARTIST, code, "n")
    for who in (ARTIST, COLLECTOR, BIDDER, OTHER):
        st.credit_deposit(who, FUND)
    nonce = [0]

    def call(who, method, args, value=0, asset=0):
        nonce[0] += 1
        blob = {"op": "call", "contract": cid, "method": method, "args": args}
        if value:
            blob["value"] = value
        if asset:
            blob["asset"] = str(asset)
        return st.apply_blob(blob, who, f"n{nonce[0]}")

    def mint(who, seed, editions):
        st.apply_blob({"op": "asset_create", "seed": seed, "name": f"Art {seed}", "sym": "ART", "dec": 0,
                       "supply": editions, "mintable": False, "uri": f"ipfs://bafy{seed}"}, who, f"m{seed}")
        return int(asset_id(who, seed))

    rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
    return st, cid, call, mint, rd


def ok(res):
    s = str(res)
    assert not s.startswith("skip:") and "revert" not in s.lower(), f"call failed: {s}"
    return res


def reverts(res):
    s = str(res)
    assert s.startswith("skip:") or "revert" in s.lower(), f"expected a revert, got: {s}"


def nat(st, who):
    return int(st.bridge.get(who, 0))


def units(st, aid, who):
    return int(st.asset_balance(str(aid), who))


def t_only_the_issuer_registers_once_at_a_bounded_royalty():
    st, cid, call, mint, rd = _fresh()
    art = mint(ARTIST, 7, 10)
    ok(call(ARTIST, "create_collection", [5, "Genesis", "first drop"]))
    ok(call(OTHER, "create_collection", [6, "Not yours", "x"]))
    reverts(call(OTHER, "register", [1, art, 7, 1000, 0]))                 # not the issuer: hash(caller, seed) != art
    reverts(call(ARTIST, "register", [1, art, 8, 1000, 0]))                # the wrong seed
    reverts(call(ARTIST, "register", [1, art, 7, N.MAX_ROYALTY_BPS + 1, 0]))
    reverts(call(ARTIST, "register", [1, art, 7, 1000, 6]))                # someone else's collection
    reverts(call(ARTIST, "register", [1 << 32, art, 7, 1000, 5]))          # id aliasing (C2)
    ok(call(ARTIST, "register", [1, art, 7, 1000, 5]))
    reverts(call(ARTIST, "register", [2, art, 7, 0, 0]))                   # once per asset
    assert rd(N.T_ASSET, 1) == art and rd(N.T_BPS, 1) == 1000 and rd(N.T_COLL, 1) == 5
    v = st.decode_view(st.contracts[cid])
    assert v["c_name"]["5"] == "Genesis", v.get("c_name")                 # the string arg reads back as text


def t_a_listing_pays_royalty_and_seller_and_unlist_returns_the_rest():
    st, cid, call, mint, rd = _fresh()
    art = mint(ARTIST, 1, 10)
    ok(call(ARTIST, "register", [1, art, 1, 1000, 0]))                     # 10 %
    reverts(call(ARTIST, "list", [11, art, 3 * NADO], value=5))            # units must arrive as the asset
    ok(call(ARTIST, "list", [11, art, 3 * NADO], value=5, asset=art))
    assert units(st, art, cid) == 5
    c0, a0 = nat(st, COLLECTOR), nat(st, ARTIST)
    reverts(call(COLLECTOR, "buy", [11, 2], value=5 * NADO))               # wrong amount
    reverts(call(COLLECTOR, "buy", [11, 6], value=18 * NADO))              # more than is left
    ok(call(COLLECTOR, "buy", [11, 2], value=6 * NADO))
    assert units(st, art, COLLECTOR) == 2 and nat(st, COLLECTOR) == c0 - 6 * NADO
    assert nat(st, ARTIST) == a0 + 6 * NADO                                 # the artist is creator AND seller here
    # a SECONDARY sale: the collector lists 1, a bidder buys; the artist gets 10 %, the collector 90 %
    ok(call(COLLECTOR, "list", [12, art, 10 * NADO], value=1, asset=art))
    c1, a1 = nat(st, COLLECTOR), nat(st, ARTIST)
    ok(call(BIDDER, "buy", [12, 1], value=10 * NADO))
    assert nat(st, ARTIST) == a1 + 1 * NADO and nat(st, COLLECTOR) == c1 + 9 * NADO
    assert rd(N.L_ST, 12) == N.DONE
    reverts(call(COLLECTOR, "unlist", [11]))                               # not the seller
    reverts(call(ARTIST, "reprice", [11, 0]))
    ok(call(ARTIST, "reprice", [11, 4 * NADO]))
    ok(call(ARTIST, "unlist", [11]))
    assert units(st, art, ARTIST) == 10 - 5 + 3 and units(st, art, cid) == 0 and rd(N.L_ST, 11) == N.CANCELLED
    assert rd(0, N.CNT_SALES) == 2 and rd(N.S_AMT, 2) == 10 * NADO and rd(N.S_KIND, 2) == N.SALE_LISTING


def t_token_and_collection_offers_settle_and_refund():
    st, cid, call, mint, rd = _fresh()
    a1, a2, stray = mint(ARTIST, 1, 3), mint(ARTIST, 2, 3), mint(OTHER, 9, 3)
    ok(call(ARTIST, "create_collection", [5, "Set", ""]))
    ok(call(ARTIST, "register", [1, a1, 1, 500, 5]))                       # 5 %, in the collection
    ok(call(ARTIST, "register", [2, a2, 2, 500, 0]))                       # registered, NOT in it
    st.apply_blob({"op": "asset_transfer", "asset": str(a1), "to": COLLECTOR, "amount": 2}, ARTIST, "t1")
    reverts(call(BIDDER, "offer", [21, a1, 5, 1, NADO, 0], value=NADO))    # both targets
    reverts(call(BIDDER, "offer", [21, 0, 0, 1, NADO, 0], value=NADO))     # neither
    reverts(call(BIDDER, "offer", [21, a1, 0, 2, NADO, 0], value=NADO))    # escrow != units * price
    ok(call(BIDDER, "offer", [21, a1, 0, 2, 4 * NADO, 0], value=8 * NADO))
    c0, a0 = nat(st, COLLECTOR), nat(st, ARTIST)
    reverts(call(COLLECTOR, "accept", [21], value=1, asset=a2))            # not the offered asset
    ok(call(COLLECTOR, "accept", [21], value=1, asset=a1))
    assert units(st, a1, BIDDER) == 1
    assert nat(st, ARTIST) == a0 + NADO // 5 and nat(st, COLLECTOR) == c0 + 4 * NADO - NADO // 5   # 5 % royalty
    b0 = nat(st, BIDDER)
    reverts(call(COLLECTOR, "cancel_offer", [21]))
    ok(call(BIDDER, "cancel_offer", [21]))
    assert nat(st, BIDDER) == b0 + 4 * NADO and rd(N.O_ST, 21) == N.CANCELLED
    # collection-wide: any asset filed under collection 5, nothing else
    ok(call(BIDDER, "offer", [22, 0, 5, 1, 2 * NADO, 0], value=2 * NADO))
    reverts(call(ARTIST, "accept", [22], value=1, asset=a2))               # registered but in no collection
    reverts(call(OTHER, "accept", [22], value=1, asset=stray))             # unregistered
    ok(call(COLLECTOR, "accept", [22], value=1, asset=a1))
    assert rd(N.O_ST, 22) == N.DONE and units(st, a1, BIDDER) == 2
    # an expiring offer: nobody may expire it early, anyone may from its height
    ok(call(BIDDER, "offer", [23, a1, 0, 1, NADO, st.cursor + 10], value=NADO))
    reverts(call(OTHER, "expire_offer", [23]))
    st.cursor += 10
    reverts(call(COLLECTOR, "accept", [23], value=1, asset=a1))            # past its expiry
    b1 = nat(st, BIDDER)
    ok(call(OTHER, "expire_offer", [23]))
    assert nat(st, BIDDER) == b1 + NADO and nat(st, cid) == 0


def t_an_english_auction_refunds_the_outbid_extends_and_settles_by_anyone():
    st, cid, call, mint, rd = _fresh()
    art = mint(ARTIST, 1, 1)
    ok(call(ARTIST, "register", [1, art, 1, 1000, 0]))
    st.apply_blob({"op": "asset_transfer", "asset": str(art), "to": COLLECTOR, "amount": 1}, ARTIST, "t1")
    reverts(call(COLLECTOR, "auction", [31, art, 10 * NADO, N.MIN_DUR - 1], value=1, asset=art))
    ok(call(COLLECTOR, "auction", [31, art, 10 * NADO, 600], value=1, asset=art))
    end0 = rd(N.A_END, 31)
    reverts(call(BIDDER, "bid", [31], value=9 * NADO))                     # under the reserve
    reverts(call(COLLECTOR, "bid", [31], value=20 * NADO))                 # the seller
    reverts(call(OTHER, "cancel_auction", [31]))                           # not the seller
    b0 = nat(st, BIDDER)
    ok(call(BIDDER, "bid", [31], value=10 * NADO))
    reverts(call(COLLECTOR, "cancel_auction", [31]))                       # a bid stands
    reverts(call(OTHER, "bid", [31], value=10 * NADO + 1))                 # under +5 %
    o0 = nat(st, OTHER)
    ok(call(OTHER, "bid", [31], value=105 * NADO // 10))
    assert nat(st, BIDDER) == b0                                            # refunded in the same call
    assert rd(N.A_END, 31) == end0                                          # far from the end: no extension
    st.cursor = end0 - 5
    ok(call(BIDDER, "bid", [31], value=12 * NADO))                          # within EXTEND of the end
    assert rd(N.A_END, 31) == st.cursor + N.EXTEND and nat(st, OTHER) == o0
    reverts(call(OTHER, "settle_auction", [31]))                            # not ended
    st.cursor = rd(N.A_END, 31)
    c0, a0 = nat(st, COLLECTOR), nat(st, ARTIST)
    reverts(call(BIDDER, "bid", [31], value=13 * NADO))                     # ended
    ok(call(OTHER, "settle_auction", [31]))                                 # anyone
    assert units(st, art, BIDDER) == 1 and nat(st, ARTIST) == a0 + 12 * NADO // 10
    assert nat(st, COLLECTOR) == c0 + 12 * NADO - 12 * NADO // 10 and nat(st, cid) == 0
    reverts(call(OTHER, "settle_auction", [31]))                            # once
    # no bid: the lot goes back to the seller, by anyone
    ok(call(BIDDER, "auction", [32, art, NADO, N.MIN_DUR], value=1, asset=art))
    st.cursor += N.MIN_DUR
    ok(call(OTHER, "settle_auction", [32]))
    assert units(st, art, BIDDER) == 1 and units(st, art, cid) == 0


def t_a_dutch_auction_falls_linearly_and_refunds_the_ceiling_change():
    st, cid, call, mint, rd = _fresh()
    art = mint(ARTIST, 1, 4)
    ok(call(ARTIST, "register", [1, art, 1, 0, 0]))                        # 0 % royalty: all to the seller
    reverts(call(ARTIST, "dutch", [41, art, NADO, 2 * NADO, 100], value=4, asset=art))   # end above start
    ok(call(ARTIST, "dutch", [41, art, 10 * NADO, 2 * NADO, 100], value=4, asset=art))
    st.cursor += 50                                                          # halfway: 6 NADO
    reverts(call(COLLECTOR, "dbuy", [41, 1, 5 * NADO], value=5 * NADO))    # ceiling under the price
    c0, a0 = nat(st, COLLECTOR), nat(st, ARTIST)
    ok(call(COLLECTOR, "dbuy", [41, 1, 8 * NADO], value=8 * NADO))
    assert nat(st, COLLECTOR) == c0 - 6 * NADO and nat(st, ARTIST) == a0 + 6 * NADO
    st.cursor += 500                                                         # long past: floored at 2 NADO
    ok(call(BIDDER, "dbuy", [41, 2, 2 * NADO], value=4 * NADO))
    assert units(st, art, BIDDER) == 2 and rd(N.D_LEFT, 41) == 1
    reverts(call(COLLECTOR, "dcancel", [41]))
    ok(call(ARTIST, "dcancel", [41]))
    assert units(st, art, ARTIST) == 1 and units(st, art, cid) == 0 and nat(st, cid) == 0
    assert rd(N.S_KIND, 1) == N.SALE_DUTCH and rd(N.S_AMT, 1) == 6 * NADO


def t_profiles_belong_to_their_caller():
    st, cid, call, mint, rd = _fresh()
    ok(call(ARTIST, "set_profile", [9, "Ada", "painter", "ipfs://avatar"]))
    reverts(call(OTHER, "set_profile", [9, "squat", "", ""]))               # someone else's id
    reverts(call(ARTIST, "set_profile", [10, "Ada2", "", ""]))              # one profile per caller
    ok(call(ARTIST, "set_profile", [9, "Ada L.", "painter", "ipfs://avatar2"]))
    v = st.decode_view(st.contracts[cid])
    assert v["p_name"]["9"] == "Ada L." and v["p_av"]["9"] == "ipfs://avatar2"


def t_the_carry_waits_for_anything_that_counts_blocks():
    st, cid, call, mint, rd = _fresh()
    art = mint(ARTIST, 1, 5)
    ok(call(ARTIST, "list", [11, art, NADO], value=1, asset=art))
    ok(call(BIDDER, "offer", [21, art, 0, 1, NADO, 0], value=NADO))
    sto = lambda: st.contracts[cid]["storage"]
    assert N.carry_in_flight(sto()) == []                                    # at rest: crosses
    ok(call(ARTIST, "auction", [31, art, NADO, N.MIN_DUR], value=1, asset=art))
    ok(call(BIDDER, "offer", [22, art, 0, 1, NADO, st.cursor + 100], value=NADO))
    ok(call(ARTIST, "dutch", [41, art, 2 * NADO, NADO, N.MIN_DUR], value=1, asset=art))
    why = N.carry_in_flight(sto())
    assert len(why) == 3 and any("auction 31" in w for w in why) and any("offer 22" in w for w in why), why
    st.cursor += N.MIN_DUR
    ok(call(OTHER, "settle_auction", [31]))
    ok(call(BIDDER, "cancel_offer", [22]))
    ok(call(ARTIST, "dcancel", [41]))
    assert N.carry_in_flight(sto()) == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("t_") and callable(fn):
            check(name[2:].replace("_", " "), fn)
    _report.done()
