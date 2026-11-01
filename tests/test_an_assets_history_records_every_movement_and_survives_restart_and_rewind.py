"""
An asset's history (GET /exec/asset_history) records every movement of it, and stays EXACT across a restart and a rewind.

An NFT page shows provenance from this index, so what it serves must be what the chain did — no more (a reverted call
is not a listing), no less (a plain wallet-to-wallet asset_transfer is provenance too), and never twice (a block
re-applied after a restart or a finality rewind must not appear again). Driven through the exec node's own pieces:
block_apply.begin/dispatch/close (what _apply_block runs), the node's _asset_history_* helpers, its real _rewind_to over a
real checkpoint file, its real _reset_states_to_genesis, and the h_asset_history handler. Pins:

  1. an NFT through mint -> transfer -> list (escrow INTO the market) -> buy (market -> buyer) -> offer accept (escrow
     in and the APAY out, in one event) reads back newest first, one event per (cursor, txid), with op / method / args
     (decimal strings) / value / call_asset and the signed moves; a reverted escrowing call adds nothing;
  2. `limit` + `next_before` page exactly; an unknown asset is a 404, a bad limit a 400; `indexed_from` and `cursor`;
  3. RESTART: a state reloaded at an older cursor trims the index above it, and re-applying the same blocks yields
     exactly the same rows — no duplicates, no leftovers;
  4. REWIND: _rewind_to(c) from a checkpoint trims above c; replaying the canonical blocks yields the same rows;
  5. a block re-flushed without a trim replaces its rows (UNIQUE (ns, cursor, seq)); a GAP restarts the index at the
     new block so `indexed_from` never spans an unknown block; a state replaced by a donor restarts it (reset);
  6. a corrupt file or a store that dies mid-flight never raises into block application — the state root is the same
     as with no index — and the endpoint says `enabled: false`; _reset_states_to_genesis reopens it empty.

Run: python3 tests/test_an_assets_history_records_every_movement_and_survives_restart_and_rewind.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): a throwaway HOME and exec files, never the live node's
_T = tempfile.mkdtemp(prefix="nado-test-asset-history-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
os.environ["NADO_EXEC_GENESIS"] = os.path.join(_T, "no_exec_genesis.json")   # this test's (empty) exec genesis
import atexit, shutil; atexit.register(shutil.rmtree, _T, ignore_errors=True)
import asyncio
import copy
import json
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState, asset_id
from execnode.code_codec import contract_id
from execnode.asset_history import AssetHistoryStore, open_store
from execnode.games import nft as N
import execnode.execnode as EN

import _harness
_report = _harness.Report()
check = _report.check

ARTIST = "ndoAAAA" + "A" * 41
COLLECTOR = "ndoCCCC" + "C" * 41
BIDDER = "ndoBBBB" + "B" * 41
FUND = 10 ** 15
NADO = 10 ** 8
CODE = N.build()
CID = contract_id(ARTIST, CODE, "n")
ART = str(asset_id(ARTIST, 1))
H0 = 1000

check("importing the exec node attaches nothing (only main() enables the index)",
      EN._asset_history is None and all(st.asset_sink is None for st in EN.states.values()))


def tx(payload, sender, txid):
    return {"recipient": "blob", "sender": sender, "txid": txid, "data": payload}


def call(who, txid, method, args, value=0, asset=None):
    b = {"op": "call", "contract": CID, "method": method, "args": args}
    if value:
        b["value"] = value
    if asset:
        b["asset"] = asset
    return tx(b, who, txid)


BLOCKS = {
    H0: [tx({"op": "deploy", "runtime": "zkvm", "code": CODE, "abi": N.ABI, "nonce": "n"}, ARTIST, "dep"),
         tx({"op": "asset_create", "seed": 1, "name": "Art", "sym": "ART", "dec": 0, "supply": 3, "mintable": False,
             "uri": "ipfs://art"}, ARTIST, "t-mint"),
         call(ARTIST, "t-reg", "register", [1, int(ART), 1, 1000, 0])],
    H0 + 1: [tx({"op": "asset_transfer", "asset": ART, "to": COLLECTOR, "amount": 1}, ARTIST, "t-xfer")],
    H0 + 2: [call(COLLECTOR, "t-list", "list", [12, int(ART), 3 * NADO], value=1, asset=ART)],
    H0 + 3: [call(BIDDER, "t-buy", "buy", [12, 1], value=3 * NADO)],
    H0 + 4: [call(BIDDER, "t-offer", "offer", [21, int(ART), 0, 1, 2 * NADO, 0], value=2 * NADO),
             call(ARTIST, "t-accept", "accept", [21], value=1, asset=ART)],
    H0 + 5: [call(ARTIST, "t-again", "accept", [21], value=1, asset=ART)],            # the offer is DONE: reverts
}


def apply_block(h):
    """What the tail does for one finalized block: block_apply (as _apply_block_inner) then the history flush."""
    blk = {"block_number": h, "block_hash": f"{h:064x}", "block_transactions": BLOCKS[h]}
    EN._BA.begin(EN.states, h)
    EN._BA.dispatch(EN.states, EN.state, blk, {}, set(), verbose=False)
    EN._BA.close(EN.states, h, blk["block_hash"])
    EN._asset_history_flush(h)


def rows():
    db = sqlite3.connect(EN.ASSET_HISTORY_PATH)
    try:
        return db.execute("SELECT * FROM moves ORDER BY ns, cursor, seq").fetchall()
    finally:
        db.close()


class _R:
    def __init__(self, **q):
        self.query = {k: str(v) for k, v in q.items()}


def ask(**q):
    r = asyncio.new_event_loop().run_until_complete(EN.h_asset_history(_R(**q)))
    return r.status, json.loads(r.body)


st = EN.state
st.cursor = H0 - 1
for who in (ARTIST, COLLECTOR, BIDDER):
    st.credit_deposit(who, FUND)
check("the exec node enables the index at <state>.asset_history.sqlite (inside the exec_state.json* glob)",
      EN._asset_history_enable() is not None and EN.ASSET_HISTORY_PATH == os.environ["NADO_EXEC_STATE"] + ".asset_history.sqlite"
      and st.asset_sink is not None)
snaps = {}
for h in sorted(BLOCKS):
    apply_block(h)
    snaps[h] = copy.deepcopy(st._snapshot())
check("the fixture: the accept moved the NFT to the bidder and the second accept reverted",
      st.asset_balance(ART, BIDDER) == 2 and st.asset_balance(ART, ARTIST) == 1 and st.asset_balance(ART, CID) == 0)

# ---- 1. the events --------------------------------------------------------------------------------------------------
code, body = ask(id=ART)
ev = body.get("events", [])
mv = lambda e: [(m["holder"], m["delta"]) for m in e["moves"]]
check("1. the JSON shape: asset, events, indexed_from, next_before, cursor, enabled",
      code == 200 and set(body) == {"asset", "events", "indexed_from", "next_before", "cursor", "enabled"}
      and body["asset"] == ART and body["cursor"] == H0 + 5 and body["indexed_from"] == H0 and body["enabled"] is True
      and body["next_before"] is None, body)
check("...each event carries exactly cursor, txid, sender, op, method, args, value, call_asset, moves",
      all(set(e) == {"cursor", "txid", "sender", "op", "method", "args", "value", "call_asset", "moves"} for e in ev))
check("...newest first: accept, buy, list, transfer, mint — the reverted accept is not there",
      [e["txid"] for e in ev] == ["t-accept", "t-buy", "t-list", "t-xfer", "t-mint"], [e["txid"] for e in ev])
by = {e["txid"]: e for e in ev}
check("...the mint credits the issuer's whole supply", by["t-mint"]["op"] == "asset_create"
      and mv(by["t-mint"]) == [(ARTIST, "3")] and by["t-mint"]["cursor"] == H0, by["t-mint"])
check("...a plain wallet-to-wallet asset_transfer is provenance too",
      mv(by["t-xfer"]) == [(ARTIST, "-1"), (COLLECTOR, "1")] and by["t-xfer"]["op"] == "asset_transfer"
      and by["t-xfer"]["sender"] == ARTIST and by["t-xfer"]["method"] == "" and by["t-xfer"]["args"] == [])
check("...a listing is the escrow INTO the market, with the call's method, decimal-string args, value and asset",
      mv(by["t-list"]) == [(COLLECTOR, "-1"), (CID, "1")] and by["t-list"]["op"] == "call"
      and by["t-list"]["method"] == "list" and by["t-list"]["args"] == ["12", ART, str(3 * NADO)]
      and by["t-list"]["value"] == "1" and by["t-list"]["call_asset"] == ART, by["t-list"])
check("...a sale is the market paying the buyer, and names the price paid in NADO",
      mv(by["t-buy"]) == [(CID, "-1"), (BIDDER, "1")] and by["t-buy"]["value"] == str(3 * NADO)
      and by["t-buy"]["call_asset"] == "" and by["t-buy"]["sender"] == BIDDER, by["t-buy"])
check("...an accepted offer is ONE event: the escrow in and the payout out, in order",
      mv(by["t-accept"]) == [(ARTIST, "-1"), (CID, "1"), (CID, "-1"), (BIDDER, "1")], by["t-accept"])
check("...the offer itself moved no NFT, so it is not this asset's history", "t-offer" not in by)

# ---- 2. paging and errors -------------------------------------------------------------------------------------------
c1, p1 = ask(id=ART, limit=2)
c2, p2 = ask(id=ART, limit=2, before=p1["next_before"])
c3, p3 = ask(id=ART, limit=2, before=p2["next_before"])
check("2. limit + next_before page through every event exactly once, newest first",
      [e["txid"] for e in p1["events"] + p2["events"] + p3["events"]] == [e["txid"] for e in ev]
      and p3["next_before"] is None, (p1["next_before"], p2["next_before"], p3["next_before"]))
check("...an unknown asset is a 404, a bad limit a 400, a missing id a 400",
      ask(id="12345")[0] == 404 and ask(id=ART, limit="x")[0] == 400 and ask()[0] == 400)
check("...an unknown namespace is the node's ns 404", ask(id=ART, ns="nope")[0] == 404)

# ---- 3. restart -----------------------------------------------------------------------------------------------------
full = rows()
st._restore(copy.deepcopy(snaps[H0 + 2]))          # what load() reads after the last save at H0 + 2
EN._asset_history.close()
EN._asset_history = None
EN._asset_history_enable()                         # as main() does on the next start
check("3. a restart at an older cursor trims the index to it",
      rows() == [r for r in full if r[1] <= H0 + 2] and EN._asset_history.indexed_from("default") == H0)
for h in (H0 + 3, H0 + 4, H0 + 5):
    apply_block(h)
check("...and re-applying the same blocks yields exactly the same rows (no duplicates, nothing left over)",
      rows() == full, (len(rows()), len(full)))
check("...and the same state", json.dumps(st._snapshot(), sort_keys=True) == json.dumps(snaps[H0 + 5], sort_keys=True))

# ---- 4. rewind ------------------------------------------------------------------------------------------------------
with open(EN._ckpt_path("default", H0 + 1), "w") as f:
    json.dump({"ns": "default", "cursor": H0 + 1, "state": snaps[H0 + 1]}, f)
check("4. _rewind_to restores the checkpoint", EN._rewind_to(H0 + 1) and st.cursor == H0 + 1)
check("...and trims the index above it", rows() == [r for r in full if r[1] <= H0 + 1] and ask(id=ART)[1]["events"][0]["txid"] == "t-xfer")
for h in (H0 + 2, H0 + 3, H0 + 4, H0 + 5):
    apply_block(h)
check("...replaying the canonical blocks yields exactly the same rows", rows() == full)

# ---- 5. idempotence, gaps, resets (the store itself) ----------------------------------------------------------------
s2 = AssetHistoryStore(os.path.join(_T, "s2.sqlite"))
rec = lambda c, d: {"cursor": c, "txid": f"x{c}", "sender": ARTIST, "op": "asset_transfer", "method": "", "args": [],
                    "value": "0", "call_asset": "", "aid": "7", "holder": ARTIST, "delta": d}
s2.sink("default")([rec(5, "1"), rec(5, "-1")])
s2.flush_block(5, ["default"])
s2.sink("default")([rec(5, "1"), rec(5, "-1")])
s2.flush_block(5, ["default"])
n_rows = lambda s: s._db.execute("SELECT COUNT(*) FROM moves").fetchone()[0]
check("5. a block flushed twice without a trim keeps ONE copy of its rows", n_rows(s2) == 2 and s2.indexed_from("default") == 5)
s2.flush_block(6, ["default"])
s2.sink("default")([rec(9, "4")])
s2.flush_block(9, ["default"])                       # 7 and 8 never flushed: a pruned body, a store outage, an adoption
check("...a GAP restarts the index at the new block (indexed_from never spans an unknown block)",
      s2.indexed_from("default") == 9 and n_rows(s2) == 1)
s2.reset("default")
check("...a state replaced by a donor resets it whole", s2.indexed_from("default") is None and n_rows(s2) == 0)
s2.sink("default")([rec(3, "1")])
s2.flush_block(4, ["default"])
check("...a record that is not of the flushed block is dropped, not written under the wrong cursor", n_rows(s2) == 0)

# ---- 6. failure never reaches block application ---------------------------------------------------------------------
bad = os.path.join(_T, "corrupt.sqlite")
with open(bad, "wb") as f:
    f.write(b"this is not a database" * 100)
check("6. a corrupt index file opens as nothing (logged), never an exception", open_store(bad) is None)
EN._asset_history.close()
EN._asset_history = None
check("...and the exec node then runs with no sink", EN._asset_history_enable(bad) is None and st.asset_sink is None)
ref = ExecState(os.path.join(_T, "ref.json"))
ref._restore(copy.deepcopy(snaps[H0 + 5]))
EN._asset_history_enable()
EN._asset_history._db.close()                      # the store dies under the running node (disk gone, file locked)
BLOCKS[H0 + 6] = [tx({"op": "asset_transfer", "asset": ART, "to": COLLECTOR, "amount": 1}, BIDDER, "t-late")]
apply_block(H0 + 6)
BLOCKS[H0 + 7] = [tx({"op": "asset_transfer", "asset": ART, "to": ARTIST, "amount": 1}, COLLECTOR, "t-later")]
apply_block(H0 + 7)
for h in (H0 + 6, H0 + 7):
    blk = {"block_number": h, "block_hash": f"{h:064x}", "block_transactions": BLOCKS[h]}
    EN._BA.begin({"default": ref}, h)
    EN._BA.dispatch({"default": ref}, ref, blk, {}, set(), verbose=False)
    EN._BA.close({"default": ref}, h, blk["block_hash"])
check("...a store that fails mid-flight disables itself and the blocks still apply, to the same root",
      EN._asset_history.disabled and st.cursor == H0 + 7 and st.state_root() == ref.state_root()
      and st.asset_balance(ART, ARTIST) == 2)
code, body = ask(id=ART)
check("...and the endpoint says so instead of serving a stale history",
      code == 200 and body["enabled"] is False and body["events"] == [] and body["indexed_from"] is None, body)
EN._asset_history = None
EN._asset_history_enable()
EN._reset_states_to_genesis(reason="test", keep_da=True)
check("_reset_states_to_genesis reopens the index EMPTY on the fresh states (the wipe deleted the file)",
      EN._asset_history is not None and not EN._asset_history.disabled
      and EN._asset_history.indexed_from("default") is None and rows() == []
      and EN.states["default"].asset_sink is not None and EN.state.cursor == -1)

_report.done()
