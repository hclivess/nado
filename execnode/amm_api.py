"""The DEX's in-chain markets as a TRADING API: the AMM pools (swap + liquidity) and the launchpad curves.

Operator, 2026-11-25: "all sumbarkets need to be fully covered". execnode/otc_api.py covers the cross-chain book and the
intra-chain limit orders that live in the same `otc` contract; this module covers the other contract the DEX page runs,
`dex` (execnode/games/dex.py): constant-product pools traded in one-price-per-block batches, staged liquidity positions,
and launch curves that graduate into locked pools. History (trades, candles, 24 h stats) was already served by
/exec/dex_trades, /exec/dex_candles and /exec/dex_stats (execnode/dex_trades.py) and is linked, not duplicated.

Same rules as otc_api: reads are free pure functions of storage (+ cursor); writes are transactions the caller signs
with its own key (static/nadodex.mjs); no float in anything a client computes with. The contract counts BOTH sides in
UNITs of 10^8 raw, so every amount here is given in units AND as a decimal in the asset's own decimals.

INVARIANT: quote() is the contract's formula, byte for byte (dex.py _pclear for a pool, _clear for a curve; the page's
quoteOut / lpQuote mirror the same). Drift here is a swap that reverts on its minOut, or one that accepts a worse fill
than the bot meant to — tests/test_the_dex_api_covers_every_market_* pins it against the real contract.
"""
from decimal import Decimal

from execnode.games import dex as D

DEX_CID = "08b256c6278ef1f6eed766c08095b460"        # static/dex.js CID — pinned against it by the tests
UNIT = D.UNIT
KINDS = {0: "pool", D.CURVE: "curve", D.GRADUATED: "graduated"}


def _m(storage, name):
    v = (storage or {}).get(name)
    return dict(v) if isinstance(v, list) else (v or {})


def _dec_of(assets, aid):
    """The asset's decimals (native NADO, id 0, has 10); an unknown asset reads as 0 and says so in its symbol."""
    if str(aid) in ("0", ""):
        return 10
    a = (assets or {}).get(str(aid)) or (assets or {}).get(int(aid) if str(aid).isdigit() else aid) or {}
    return int(a.get("dec", 0) or 0)


def _sym_of(assets, aid):
    if str(aid) in ("0", ""):
        return "NADO"
    a = (assets or {}).get(str(aid)) or (assets or {}).get(int(aid) if str(aid).isdigit() else aid) or {}
    return a.get("sym") or "?"


def units_str(units, dec):
    """Pool units as an exact decimal in an asset of `dec` decimals (one unit = 10^8 raw)."""
    return format((Decimal(int(units) * UNIT) / (Decimal(10) ** dec)).normalize(), "f")


def to_units(amount, dec):
    """A decimal string of an asset with `dec` decimals -> pool units, floored (as the page's tokToUnits)."""
    s = str(amount).strip()
    i, _, f = s.partition(".")
    if (i and not i.isdigit()) or (f and not f.isdigit()) or not (i or f):
        raise ValueError(f"not an amount: {amount}")
    raw = int((i or "0") + (f + "0" * dec)[:dec]) if dec else int(i or "0")
    return raw // UNIT


def _price(num_units, num_dec, den_units, den_dec):
    """(num / den) in whole coins, from unit counts: how many `num` coins one `den` coin is worth. None if unpriced."""
    if not num_units or not den_units:
        return None
    q = (Decimal(int(num_units)) / Decimal(10) ** num_dec) / (Decimal(int(den_units)) / Decimal(10) ** den_dec)
    return format(q.quantize(Decimal("1e-18")).normalize(), "f")


def pools(storage, assets, cursor=None):
    """Every pool and curve as a self-describing row. price_nado = NADO per ONE coin, price_coin = coins per ONE NADO."""
    ast = _m(storage, "ast")
    g = {k: _m(storage, k) for k in ("rn", "rt", "sup", "kind", "cn", "ct", "vn", "grad", "lblk", "open", "creator")}
    out = []
    for pid in sorted(ast, key=lambda x: int(x)):
        aid = str(ast[pid])
        dec, kind = _dec_of(assets, aid), int(g["kind"].get(pid) or 0)
        f = lambda k: int(g[k].get(pid) or 0)
        row = {"id": int(pid), "kind": KINDS.get(kind, str(kind)), "asset": aid, "coin": _sym_of(assets, aid), "decimals": dec}
        if kind == D.CURVE:
            x, ct = f("vn") + f("cn"), f("ct")
            supply = f("grad") * 5
            in_window = cursor is not None and 0 <= int(cursor) - f("lblk") < D.WINDOW
            row.update({"raised_units": f("cn"), "raised_nado": units_str(f("cn"), 10), "coins_left_units": ct,
                        "virtual_nado_units": f("vn"), "supply_units": supply,
                        "graduates_at_raise_nado": units_str(4 * f("vn"), 10),
                        # the page's lpSold: the curve graduates at 4/5 sold, so 80 % of supply reads as 100 %
                        "sold_pct": format(min(Decimal(100), max(Decimal(0), Decimal((supply - ct) * 125) / supply if supply else Decimal(0))).quantize(Decimal("0.01")), "f"),
                        "price_nado": _price(x, 10, ct, dec), "price_coin": _price(ct, dec, x, 10),
                        "launch_block": f("lblk"), "opening_batch": in_window, "creator": str(g["creator"].get(pid) or ""),
                        "live": ct > 0})
        else:
            rn, rt = f("rn"), f("rt")
            row.update({"reserve_nado_units": rn, "reserve_coin_units": rt, "reserve_nado": units_str(rn, 10),
                        "reserve_coin": units_str(rt, dec), "shares": f("sup"),
                        "price_nado": _price(rn, 10, rt, dec), "price_coin": _price(rt, dec, rn, 10),
                        "live": rn > 0 and rt > 0 and (f("sup") > 0 or kind == D.GRADUATED),
                        "locked_liquidity": kind == D.GRADUATED})
        out.append(row)
    return out


def quote(storage, pid, side, units):
    """What ONE order of `units` gets if it is alone in its batch — the contract's exact clearing (batches net buys and
    sells first, so a real fill can only be the same or better on the side with fewer orders). side: 'buy' spends NADO
    for the coin, 'sell' spends the coin for NADO. Returns {out_units, fee_units} or raises ValueError."""
    pid, units = str(int(pid)), int(units)
    if units <= 0:
        raise ValueError("amount must be > 0")
    if side not in ("buy", "sell"):
        raise ValueError("side is buy or sell")
    if pid not in _m(storage, "ast"):
        raise ValueError("no such pool")
    f = lambda k: int(_m(storage, k).get(pid) or 0)
    if f("kind") == D.CURVE:
        fee = units // D.ORDER_FEE                          # dex.py: 1 % of every order, in its own coin
        net, x, ct = units - fee, f("vn") + f("cn"), f("ct")
        if net <= 0 or ct <= 0:
            return {"out_units": 0, "fee_units": fee}
        return {"out_units": (ct * net) // (x + net) if side == "buy" else (x * net) // (ct + net), "fee_units": fee}
    rin, rout = (f("rn"), f("rt")) if side == "buy" else (f("rt"), f("rn"))
    if rin <= 0 or rout <= 0:
        raise ValueError("pool has no liquidity")
    dxf = units * D.FEE_NUM // D.FEE_DEN                  # 30 bps stays in the pool for the LPs
    return {"out_units": (rout * dxf) // (rin + dxf) if dxf > 0 else 0, "fee_units": units - dxf}


def _slots(contract):
    return ((contract or {}).get("storage") or {}).get("slots") or {}


def _slot(slots, field, key):
    return int(slots.get(str(field * (1 << 32) + int(key)), 0) or 0)


def order(contract, oid, cursor, storage=None):
    """A swap/launch order by its id (the trader chose it): side, amount, its batch's block, whether it can be claimed,
    and — once its batch has cleared — exactly what claim() pays.

    CLAIMABLE is dex.py claim()'s own test: cleared, or closed (the cursor has left the batch's block) — and a curve's
    OPENING batch (key = the launch block) stays shut for the whole WINDOW, not one block. Saying "claimable" there
    sent a bot into a claim the contract refuses."""
    s, o = _slots(contract), int(oid)
    amt = _slot(s, D.OAMT, o)
    b = _slot(s, D.OBAT, o)
    if not b and not amt:
        return None
    pid, key, done = _slot(s, D.BPOOL, b), _slot(s, D.BKEY, b), _slot(s, D.BDONE, b)
    side = "sell" if _slot(s, D.OSIDE, o) == 2 else "buy"
    closed = int(cursor) != key
    if storage is not None and not done:
        f = lambda k: int(_m(storage, k).get(str(pid)) or 0)
        if f("kind") == D.CURVE and key == f("lblk") and 0 <= int(cursor) - f("lblk") < D.WINDOW:
            closed = False                              # the opening batch: one price for the whole window
    row = {"id": o, "pool": pid, "side": side, "amount_units": amt, "batch_block": key, "claimed": amt == 0,
           "cleared": bool(done), "claimable": amt > 0 and (bool(done) or closed)}
    if done and amt:
        tot, inn = (_slot(s, D.BTOUT, b), _slot(s, D.BNIN, b)) if side == "buy" else (_slot(s, D.BNOUT, b), _slot(s, D.BTIN, b))
        row["payout_units"] = amt * tot // inn if inn else 0
    row["owner_digest"] = str(_slot(s, D.OOWN, o))
    return row


def reserved(contract, pid):
    """The creator digest a prelaunch() reserved this id for, or None. prelaunch writes only the CREATOR slot — the id
    joins the pools list at launch() — so no decoded map shows a reserved launch; a bot waiting to send its supply
    needs to see it land (2026-11-25: the SDK's launch() timed out waiting on the decoded view)."""
    v = _slot(_slots(contract), D.CREATOR, int(pid))
    return str(v) if v else None


def position(contract, storage, pos, digest_of=None):
    """A liquidity position by its id: pool, shares, what they withdraw now, and any staged (pending) sides."""
    s, p = _slots(contract), int(pos)
    pid = _slot(s, D.PPOOL, p)
    sh, pn, ptk = _slot(s, D.PSH, p), _slot(s, D.PPN, p), _slot(s, D.PPT, p)
    if not (pid or sh or pn or ptk):
        return None
    f = lambda k: int(_m(storage, k).get(str(pid)) or 0)
    sup = f("sup")
    return {"id": p, "pool": pid, "shares": sh, "pending_nado_units": pn, "pending_coin_units": ptk,
            "withdraw_nado_units": sh * f("rn") // sup if sup else 0, "withdraw_coin_units": sh * f("rt") // sup if sup else 0,
            "pool_shares": sup, "owner_digest": str(_slot(s, D.POW, p))}


def index(base=""):
    return {
        "pools": base + "/exec/amm/pools",
        "pool": base + "/exec/amm/pool?id=<pool>",
        "quote": base + "/exec/amm/quote?pool=<pool>&side=buy|sell&amount=<decimal>",
        "order": base + "/exec/amm/order?id=<order id>",
        "position": base + "/exec/amm/position?id=<position id>",
        "trades": base + "/exec/dex_trades?pid=<pool>&trader=<address>&limit=200",
        "candles": base + "/exec/dex_candles?pid=<pool>&tf=300",
        "stats": base + "/exec/dex_stats",
    }
