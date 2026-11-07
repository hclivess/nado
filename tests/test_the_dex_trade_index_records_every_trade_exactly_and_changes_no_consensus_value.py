"""
The node-local DEX trade index (execnode/dex_trades.py, ExecState.call_sink) records every trade EXACTLY — and changes
NO consensus value. It is what the DEX page's candles, recent trades, volume and transaction counts are built from
("a DEX price/chart dashboard like Dexscreener", operator 2026-11-07), so both halves matter:

  1. exact: the real dex contract (execnode/games/dex.py) runs a pool (seed, swaps both ways, a partial exit) and a launch
     curve (fee, launch, two buys in the opening window, a claim that clears it, a sell in a later batch, buys to
     graduation); every recorded swap's NADO and coins equal what the trader's balances actually moved, every curve
     fill equals what the trader's claim actually paid, and the launch and graduation are recorded;
  2. neutral: the SAME blocks applied with no sink, with the real sqlite-backed sink, and with a sink that raises on
     every call give identical apply_blob strings, identical state roots after every block and identical snapshots;
     a clone never inherits the sink;
  3. rewind-exact: trimming the index to a mid cursor and applying the rest again onto a state at that cursor gives the
     very same rows (a curve fill whose orders sit below the trim is re-derived, never lost or doubled); and the index
     claims a complete history only from where the DEX capture began — not from the older asset history it shares a
     file with (the first deploy reported the asset history's start, 2026-11-07);
  4. reads: candles are OHLC of the spot with volume and buy/sell counts per bucket, and the stats count buys, sells,
     volume and makers per window;
  5. wiring: the exec node attaches the sink with the store, passes the block's timestamp, and serves /exec/dex_trades,
     /exec/dex_candles and /exec/dex_stats; the index follows the page's own DEX contract id.

Run: python3 tests/test_the_dex_trade_index_records_every_trade_exactly_and_changes_no_consensus_value.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): a throwaway HOME and exec files, never the live node's
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-dex-trade-index-")
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import json
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from execnode.state import ExecState, asset_id
from execnode.code_codec import contract_id
from execnode import block_apply as BA
from execnode.asset_history import AssetHistoryStore
from execnode.dex_trades import DexCallSink, dex_cids
from execnode.games import dex as D

import _harness
_report = _harness.Report()
check = _report.check

OWNER = "ndoAAAA" + "A" * 41
BUYER = "ndoBBBB" + "B" * 41
SELLER = "ndoCCCC" + "C" * 41
FUND = 10 ** 15
U = D.UNIT
CODE = D.build()
CID = contract_id(OWNER, CODE, "d")
TOK = int(asset_id(OWNER, 1))
COIN = int(asset_id(OWNER, 2))
POOL, CURVE = 5, 7
H0 = 1000
TS0 = 1_800_000_000


def scenario(nbuys=14):
    n = [0]

    def call(who, method, args, value=0, asset=0):
        n[0] += 1
        b = {"op": "call", "contract": CID, "method": method, "args": args}
        if value:
            b["value"] = value
        if asset:
            b["asset"] = str(asset)
        return (b, who, f"c{n[0]:04d}")

    h = H0
    blocks = [(h, [({"op": "deploy", "runtime": "zkvm", "code": CODE, "abi": D.ABI, "nonce": "d"}, OWNER, "dep"),
                   ({"op": "asset_create", "seed": 1, "name": "Tok", "sym": "TOK", "dec": 8, "supply": 1_000_000 * U,
                     "mintable": False}, OWNER, "mk-tok"),
                   ({"op": "asset_create", "seed": 2, "name": "Coin", "sym": "CN", "dec": 8, "supply": 10_000 * U,
                     "mintable": False}, OWNER, "mk-coin")])]
    blocks.append((h + 1, [({"op": "asset_transfer", "asset": str(TOK), "to": SELLER, "amount": 5_000 * U}, OWNER, "x1"),
                           call(OWNER, "open", [POOL, TOK]),
                           call(OWNER, "fundn", [1, POOL, 2_000], 2_000 * U),
                           call(OWNER, "fundt", [1, POOL, 4_000], 4_000 * U, TOK),
                           call(OWNER, "join", [1, POOL])]))
    blocks.append((h + 2, [call(BUYER, "swapn", [POOL, 100, 1, TOK], 100 * U),
                           call(SELLER, "swapt", [POOL, 300, 1], 300 * U, TOK),
                           call(BUYER, "swapn", [POOL, 100, 10 ** 9, TOK], 100 * U),          # REVERT: minOut too high
                           call(BUYER, "swapn", [POOL, 40, 1, TOK], 40 * U)]))
    blocks.append((h + 3, [call(OWNER, "exit", [1, POOL, 500, TOK]),
                           call(OWNER, "prelaunch", [CURVE], D.CREATE_FEE * U),
                           call(OWNER, "launch", [CURVE, 10_000, 1_000], 10_000 * U, COIN)]))
    blocks.append((h + 4, [call(BUYER, "buy", [CURVE, 1, 150], 150 * U),
                           call(SELLER, "buy", [CURVE, 2, 150], 150 * U)]))
    w = h + 3 + D.WINDOW + 1                                                           # the opening window is over
    blocks.append((w, [call(BUYER, "claim", [1, COIN]),                                # clears the opening batch
                       call(SELLER, "claim", [2, COIN])]))
    blocks.append((w + 1, [call(SELLER, "sell", [CURVE, 3, 400], 400 * U, COIN)]))
    blocks.append((w + 2, [call(SELLER, "claim", [3, COIN])]))
    hh, o = w + 3, 10
    for _ in range(nbuys):                                                              # buys until it graduates
        blocks.append((hh, [call(BUYER, "buy", [CURVE, o, 700], 700 * U)]))
        blocks.append((hh + 1, [call(BUYER, "claim", [o, COIN])]))
        hh, o = hh + 2, o + 1
    blocks.append((hh, [call(SELLER, "swapn", [CURVE, 20, 1, COIN], 20 * U)]))       # trade on the graduated pool
    return blocks


def fresh(tag):
    return ExecState(os.path.join(tempfile.mkdtemp(prefix=f"nado_dex_{tag}_"), "s.json"))


def run(st, blocks, store=None, upto=None, frm=None, balances=None):
    """Apply the blocks as the exec node's tail does; flush the store after each (ts = TS0 + 7 s per block)."""
    outs, roots = [], []
    if frm is None:
        st.cursor = H0 - 1
        for who in (OWNER, BUYER, SELLER):
            st.credit_deposit(who, FUND)
    at = dict(blocks)
    # EVERY height, empty ones too, as the exec node's tail does: the store reads a skipped flush as a gap (and restarts)
    for h in range(H0, blocks[-1][0] + 1):
        if (upto is not None and h > upto) or (frm is not None and h <= frm):
            continue
        BA.begin({"default": st}, h)
        for payload, sender, txid in at.get(h, ()):
            before = (st.bridge.get(sender, 0), st.asset_balance(TOK, sender), st.asset_balance(COIN, sender))
            outs.append(st.apply_blob(json.loads(json.dumps(payload)), sender, txid))
            if balances is not None:
                balances[txid] = (sender, payload.get("method"), before,
                                  (st.bridge.get(sender, 0), st.asset_balance(TOK, sender), st.asset_balance(COIN, sender)))
        BA.close({"default": st}, h, f"{h:064x}")
        if store is not None:
            store.flush_block(h, ["default"], TS0 + 7 * (h - H0))
        roots.append(st.state_root())
    return outs, roots


# the loop buys until the curve graduates: probe where it does, then build the scenario with exactly that many buys
_probe = fresh("probe")
_o = dict(zip([t for _h, bl in scenario() for _p, _s, t in bl], run(_probe, scenario())[0]))
NB = next(i for i in range(14) if "revert" in _o[f"c{18 + 2 * i:04d}"])         # c0018 is the first loop buy
blocks = scenario(NB)
plain = fresh("plain")
outs0, roots0 = run(plain, blocks)

idx = fresh("idx")
store = AssetHistoryStore(os.path.join(os.environ["HOME"], "h.sqlite"))
idx.asset_sink = store.sink("default")
idx.call_sink = DexCallSink(store, "default", {CID})
moved = {}
outs1, roots1 = run(idx, blocks, store, balances=moved)


class Boom:
    calls = 0

    def before(self, st, p):
        Boom.calls += 1
        raise RuntimeError("disk full")


boom = fresh("boom")
boom.call_sink = Boom()
outs2, roots2 = run(boom, blocks)

txids = [t for _h, bl in blocks for _p, _s, t in bl]
out = dict(zip(txids, outs0))

# ---- 2. neutral ----------------------------------------------------------------------------------------------------
check("the fixture runs: every call applies except the one meant to revert",
      all(o.endswith("-> ok") for t, o in out.items() if t.startswith("c") and t != "c0007") and "revert" in out["c0007"],
      {t: o for t, o in out.items() if t.startswith("c") and not o.endswith("-> ok")})
check("every apply_blob return string is identical with the index on", outs0 == outs1)
check("the state root after EVERY block is identical with the index on", roots0 == roots1)
check("the full snapshot is identical with the index on",
      json.dumps(plain._snapshot(), sort_keys=True) == json.dumps(idx._snapshot(), sort_keys=True))
check("a sink that raises on every call changes no string, no root and no snapshot byte",
      outs0 == outs2 and roots0 == roots2
      and json.dumps(plain._snapshot(), sort_keys=True) == json.dumps(boom._snapshot(), sort_keys=True))
check("...and it was called (the comparison is not vacuous)", Boom.calls > 20, Boom.calls)
check("a clone never inherits the sink", idx.clone().call_sink is None and ExecState.call_sink is None)

# ---- 1. exact ------------------------------------------------------------------------------------------------------
rows, nb = store.dex_trades("default", CID, limit=1000)
rows.reverse()                                                    # oldest first
by_tx = {}
for r in rows:
    by_tx.setdefault(r["txid"], []).append(r)
check("the reverted swap left no row", "c0007" not in by_tx)
swaps = [r for r in rows if r["side"] in ("buy", "sell") and r["kind"] != D.CURVE]
ok_swaps = []
for r in swaps:
    sender, method, b, a = moved[r["txid"]]
    coin_d = (a[1] - b[1]) if r["pid"] == POOL else (a[2] - b[2])
    if r["side"] == "buy":
        ok_swaps.append(b[0] - a[0] == r["nado"] * U and coin_d == r["tokens"] * U)
    else:
        ok_swaps.append(a[0] - b[0] == r["nado"] * U and -coin_d == r["tokens"] * U)
check("every swap's NADO and coins are exactly what the trader's balances moved",
      len(swaps) == 4 and all(ok_swaps), (len(swaps), ok_swaps))
fills = [r for r in rows if r["kind"] == D.CURVE and r["side"] in ("buy", "sell")]
claims = {}
for t, (sender, method, b, a) in moved.items():
    if method == "claim":
        claims[t] = (sender, b, a)
paid = []
for r in fills:
    # the claim of order oid paid it: coins to a buyer, NADO to a seller
    ct = next(t for t, (_s, p) in ((t, (bl[1], bl[0])) for _h, bls in blocks for bl in bls for t in [bl[2]])
              if p.get("method") == "claim" and p["args"][0] == r["oid"])
    sender, b, a = claims[ct]
    paid.append((a[2] - b[2]) == r["tokens"] * U if r["side"] == "buy" else (a[0] - b[0]) == r["nado"] * U)
check("every launch fill equals what its claim actually paid (the contract's own claim formula)",
      len(fills) == 3 + NB and all(paid), (len(fills), NB, paid.count(False)))
first = [r for r in fills if r["oid"] in (1, 2)]
check("both opening-window buyers filled at ONE price, at the block the window's batch cleared",
      len(first) == 2 and first[0]["tokens"] == first[1]["tokens"] and first[0]["cursor"] == first[1]["cursor"] == H0 + 3 + D.WINDOW + 1,
      first)
check("the launch and the graduation are recorded, in order",
      [r["side"] for r in rows if r["side"] in ("launch", "graduate")] == ["launch", "graduate"])
check("liquidity is recorded as add and remove", [r["side"] for r in rows if r["pid"] == POOL and r["side"] in ("add", "remove")] == ["add", "remove"])
check("each row carries its block's time", all(r["ts"] == TS0 + 7 * (r["cursor"] - H0) for r in rows))
gp = [r for r in rows if r["pid"] == CURVE and r["side"] == "graduate"][0]
last = [r for r in rows if r["pid"] == CURVE][-1]                  # the swap on the graduated pool, after it
_sl = idx.contracts[CID]["storage"]["slots"]
rn, rt = (int(_sl.get(str(f * 2 ** 32 + CURVE), 0)) for f in (D.RN, D.RT))
check("after graduation the spot is the share-less pool's reserves (and the swap on it moves them exactly)",
      last["side"] == "buy" and (last["pn"], last["pt"]) == (rn, rt) and (gp["pn"], gp["pt"]) == (rn - last["nado"], rt + last["tokens"]),
      (gp, last, rn, rt))

# ---- 3. rewind-exact -----------------------------------------------------------------------------------------------
mid = H0 + 3 + D.WINDOW                                            # orders below, their clearing above
part = fresh("part")
run(part, blocks, upto=mid)
store.trim("default", part.cursor)
left, _ = store.dex_trades("default", CID, limit=1000)
check("a trim removes every row above the cursor", all(r["cursor"] <= mid for r in left) and len(left) < len(rows))
part.asset_sink = store.sink("default")
part.call_sink = DexCallSink(store, "default", {CID})
run(part, blocks, store, frm=mid)
again, _ = store.dex_trades("default", CID, limit=1000)
again.reverse()
check("applying the rest again gives the very same rows (fills re-derived from orders below the trim)", again == rows)

check("the index claims completeness from the first block it captured", store.dex_indexed_from("default") == H0,
      store.dex_indexed_from("default"))
# a file that predates the capture: asset history from H0, the DEX capture from a later block
old = AssetHistoryStore(os.path.join(os.environ["HOME"], "old.sqlite"))
pre = fresh("pre")
pre.asset_sink = old.sink("default")
run(pre, blocks, old, upto=H0 + 2)
old._db.execute("DELETE FROM dex_meta"); old.close()            # the file as an exec node without the capture left it
old = AssetHistoryStore(os.path.join(os.environ["HOME"], "old.sqlite"))
pre.asset_sink = old.sink("default"); pre.call_sink = DexCallSink(old, "default", {CID})
run(pre, blocks, old, frm=H0 + 2, upto=H0 + 4)
check("…so a file whose asset history is older reports the DEX capture's start, not the asset history's",
      old.indexed_from("default") == H0 and old.dex_indexed_from("default") == H0 + 3,
      (old.indexed_from("default"), old.dex_indexed_from("default")))
old.trim("default", H0 + 1)
check("…and a trim below it lowers it to the first block that will be applied again (with the capture)",
      old.dex_indexed_from("default") == H0 + 2, old.dex_indexed_from("default"))

# ---- 4. reads ------------------------------------------------------------------------------------------------------
import execnode.dex_trades as DX
_now = DX.time.time
DX.time.time = lambda: TS0 + 7 * (blocks[-1][0] - H0) + 10
cs = store.dex_candles("default", CID, CURVE, 60, 100)
check("candles: one per active minute, open = the previous close, high/low bound open and close",
      len(cs) >= 2 and all(c[2] >= max(c[1], c[4]) and c[3] <= min(c[1], c[4]) for c in cs)
      and all(cs[i][1] == cs[i - 1][4] for i in range(1, len(cs))))
check("…with the volume and buy/sell counts of the trades inside",
      sum(c[5] for c in cs) == sum(r["nado"] for r in rows if r["pid"] == CURVE and r["side"] in ("buy", "sell"))
      and sum(c[6] + c[7] for c in cs) == len([r for r in rows if r["pid"] == CURVE and r["side"] in ("buy", "sell")]))
st_ = store.dex_stats("default", CID)
s = st_.get(CURVE, {})
check("stats: buys, sells and volume over 24 h, and makers",
      s and s["h24"]["buys"] == len([r for r in rows if r["pid"] == CURVE and r["side"] == "buy"])
      and s["h24"]["sells"] == len([r for r in rows if r["pid"] == CURVE and r["side"] == "sell"])
      and s["makers"] == 2 and s["created"] == min(r["ts"] for r in rows if r["pid"] == CURVE), s)
DX.time.time = _now

# ---- 5. wiring -----------------------------------------------------------------------------------------------------
src = open(os.path.join(ROOT, "execnode", "execnode.py"), encoding="utf-8").read()
check("the exec node attaches the sink with the store and flushes with the block's time",
      "st.call_sink = DexCallSink(store, ns, _DEX_CIDS)" in src and '_asset_history_flush(h, block.get("block_timestamp") or 0)' in src)
check("…and serves the three endpoints",
      all(f'web.get("/exec/{e}", h_{e})' in src for e in ("dex_trades", "dex_candles", "dex_stats")))
page = open(os.path.join(ROOT, "static", "dex.js"), encoding="utf-8").read()
check("the index follows the page's own DEX contract", dex_cids() and next(iter(dex_cids())) in page)
hsrc = open(os.path.join(ROOT, "execnode", "asset_history.py"), encoding="utf-8").read()
check("every DEX table is trimmed, reset and gap-restarted with the asset history",
      '_NS_TABLES = ("moves",) + DX.TABLES' in hsrc and hsrc.count("for t in _NS_TABLES") >= 4)

_report.done()
