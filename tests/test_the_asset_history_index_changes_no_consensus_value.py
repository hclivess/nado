"""
The node-local asset history index (execnode/asset_history.py, ExecState.asset_sink) changes NO consensus value.

The index records who moved which asset while a block applies. It is a convenience for an NFT page and nothing more, so
the one thing it must never do is change what a block's application computes — a state root that differs with the index
on is a fork between nodes that opted out and nodes that did not. Pinned here, by applying the SAME blocks to three
states — no sink, a real sqlite-backed sink, and a sink that raises on every call — and comparing:

  * state_root() after every block, the full _snapshot() at the end, and EVERY apply_blob return string;
  * across a scenario that moves assets every way the ledger can: asset_create (initial supply), asset_mint,
    asset_transfer, asset_approve + asset_transfer_from, asset_burn, the NFT market's escrow (list/buy/unlist,
    offer/accept, English auction bid/settle) — a contract call escrowing the asset (`asset` field) and the contract's
    APAY effects out — a REVERTED escrowing call (refund), and a reverted native call;
  * a raising sink: apply_blob still returns the same strings and nothing escapes into block application;
  * inertness: a state without a sink never grows `_hist_buf`, and a clone (the provisional tail, settle_b2.prove_span)
    never inherits the sink; settle_b2 and tools/replay_exec.py never attach one; the exec node enables it only in
    main() and the opt-out env is honoured.

Run: python3 tests/test_the_asset_history_index_changes_no_consensus_value.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): a throwaway HOME and exec files, never the live node's
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-asset-history-consensus-")
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import json
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from execnode.state import ExecState, asset_id
from execnode.code_codec import contract_id
from execnode import block_apply as BA
from execnode.asset_history import AssetHistoryStore
from execnode.games import nft as N

import _harness
_report = _harness.Report()
check = _report.check

ARTIST = "ndoAAAA" + "A" * 41
COLLECTOR = "ndoCCCC" + "C" * 41
BIDDER = "ndoBBBB" + "B" * 41
OTHER = "ndoOOOO" + "O" * 41
FUND = 10 ** 15
NADO = 10 ** 8
CODE = N.build()
H0 = 1000


def scenario():
    """[(height, [(payload, sender, txid), ...]), ...] — deterministic, so every state gets byte-identical input."""
    cid = contract_id(ARTIST, CODE, "n")
    art = int(asset_id(ARTIST, 1))
    tok = int(asset_id(ARTIST, 2))
    n = [0]

    def call(who, method, args, value=0, asset=0):
        n[0] += 1
        b = {"op": "call", "contract": cid, "method": method, "args": args}
        if value:
            b["value"] = value
        if asset:
            b["asset"] = str(asset)
        return (b, who, f"c{n[0]:04d}")

    h = H0
    blocks = [(h, [({"op": "deploy", "runtime": "zkvm", "code": CODE, "abi": N.ABI, "nonce": "n"}, ARTIST, "dep"),
                   ({"op": "asset_create", "seed": 1, "name": "Art 1", "sym": "ART", "dec": 0, "supply": 10,
                     "mintable": False, "uri": "ipfs://bafy1"}, ARTIST, "mint-art"),
                   ({"op": "asset_create", "seed": 2, "name": "Tok", "sym": "TOK", "dec": 2, "supply": 1000,
                     "mintable": True}, ARTIST, "mint-tok")])]
    blocks.append((h + 1, [
        ({"op": "asset_mint", "asset": str(tok), "to": OTHER, "amount": 50}, ARTIST, "amint"),
        ({"op": "asset_transfer", "asset": str(art), "to": COLLECTOR, "amount": 3}, ARTIST, "xfer1"),
        ({"op": "asset_approve", "asset": str(tok), "spender": BIDDER, "amount": 100}, ARTIST, "appr"),
        ({"op": "asset_transfer_from", "asset": str(tok), "from": ARTIST, "to": OTHER, "amount": 40}, BIDDER, "xfrom"),
        ({"op": "asset_burn", "asset": str(tok), "amount": 7}, OTHER, "burn"),
        ({"op": "asset_transfer", "asset": str(tok), "to": COLLECTOR, "amount": 20}, ARTIST, "xfer-tok"),
        ({"op": "asset_transfer", "asset": str(art), "to": COLLECTOR, "amount": 999}, ARTIST, "xfer-too-much"),
        call(ARTIST, "register", [1, art, 1, 1000, 0])]))
    blocks.append((h + 2, [
        call(ARTIST, "list", [11, art, 3 * NADO], value=4, asset=art),          # escrow 4 ART into the market
        call(COLLECTOR, "buy", [11, 2], value=6 * NADO),                         # APAY 2 ART out to the buyer
        call(COLLECTOR, "buy", [11, 2], value=5 * NADO),                         # REVERT (wrong amount, native value)
        call(ARTIST, "list", [12, art, NADO], value=2, asset=art),               # 2 more in escrow
        call(ARTIST, "unlist", [12])]))                                          # APAY 5 ART back
    blocks.append((h + 3, [
        call(BIDDER, "offer", [21, art, 0, 1, 4 * NADO, 0], value=4 * NADO),
        call(COLLECTOR, "accept", [21], value=1, asset=tok),                     # REVERT with an ASSET escrow + refund
        call(COLLECTOR, "accept", [21], value=1, asset=art),                     # escrow in, APAY out to the bidder
        call(ARTIST, "unlist", [11])]))
    blocks.append((h + 4, [call(COLLECTOR, "auction", [31, art, 10 * NADO, N.MIN_DUR], value=1, asset=art),
                           call(BIDDER, "bid", [31], value=10 * NADO),
                           call(OTHER, "bid", [31], value=11 * NADO)]))
    blocks.append((h + 4 + N.MIN_DUR + N.EXTEND, [call(OTHER, "settle_auction", [31]),
                                                  ({"op": "asset_burn", "asset": str(art), "amount": 1}, OTHER, "burn-art")]))
    return blocks


def run(st, blocks):
    """Apply the blocks the way the exec node's tail does (block_apply.begin, the blobs, close); return every
    apply_blob string and the root after each block."""
    outs, roots = [], []
    st.cursor = H0 - 1
    for who in (ARTIST, COLLECTOR, BIDDER, OTHER):
        st.credit_deposit(who, FUND)
    for h, blobs in blocks:
        BA.begin({"default": st}, h)
        for payload, sender, txid in blobs:
            outs.append(st.apply_blob(json.loads(json.dumps(payload)), sender, txid))
        BA.close({"default": st}, h, f"{h:064x}")
        roots.append(st.state_root())
    return outs, roots


def fresh(tag):
    return ExecState(os.path.join(tempfile.mkdtemp(prefix=f"nado_hist_{tag}_"), "s.json"))


blocks = scenario()

plain = fresh("plain")
outs0, roots0 = run(plain, blocks)

hist = fresh("hist")
store = AssetHistoryStore(os.path.join(os.environ["HOME"], "h.sqlite"))
seen = []
_sink = store.sink("default")


def recording_sink(recs):
    seen.extend(recs)
    _sink(recs)


hist.asset_sink = recording_sink
outs1 = []
roots1 = []
hist.cursor = H0 - 1
for who in (ARTIST, COLLECTOR, BIDDER, OTHER):
    hist.credit_deposit(who, FUND)
for h, blobs in blocks:
    BA.begin({"default": hist}, h)
    for payload, sender, txid in blobs:
        outs1.append(hist.apply_blob(json.loads(json.dumps(payload)), sender, txid))
    BA.close({"default": hist}, h, f"{h:064x}")
    store.flush_block(h, ["default"])
    roots1.append(hist.state_root())

boom = fresh("boom")
_calls = [0]


def raising_sink(recs):
    _calls[0] += 1
    raise RuntimeError("disk full")


boom.asset_sink = raising_sink
outs2, roots2 = run(boom, blocks)

check("the fixture moves assets every way: creates, mints, transfers, escrows, pays out, burns",
      {r["op"] for r in seen} >= {"asset_create", "asset_mint", "asset_transfer", "asset_transfer_from",
                                  "asset_burn", "call"}, sorted({r["op"] for r in seen}))
check("...including a contract call that escrows an asset and one the contract pays out of",
      any(r["op"] == "call" and r["call_asset"] and int(r["delta"]) > 0 and r["holder"] not in
          (ARTIST, COLLECTOR, BIDDER, OTHER) for r in seen)
      and any(r["op"] == "call" and int(r["delta"]) < 0 and r["holder"] not in (ARTIST, COLLECTOR, BIDDER, OTHER)
              for r in seen))
_all_txids = [txid for _h, bl in blocks for _p, _s, txid in bl]
_out = dict(zip(_all_txids, outs0))
check("...a reverted native call, and a reverted call that ESCROWED an asset (moved it in, refunded it)",
      "revert" in _out["c0004"] and "revert" in _out["c0008"],
      (_out["c0004"], _out["c0008"]))
check("...and every other call applied (the fixture is what it says)",
      all(o.endswith("-> ok") for t, o in _out.items() if t.startswith("c") and t not in ("c0004", "c0008")),
      {t: o for t, o in _out.items() if t.startswith("c") and not o.endswith("-> ok")})
check("every apply_blob return string is identical with the index on", outs0 == outs1,
      [(a, b) for a, b in zip(outs0, outs1) if a != b])
check("the state root after EVERY block is identical with the index on", roots0 == roots1)
check("the full snapshot is identical with the index on",
      json.dumps(plain._snapshot(), sort_keys=True) == json.dumps(hist._snapshot(), sort_keys=True))
check("a sink that raises on every call changes no return string", outs0 == outs2,
      [(a, b) for a, b in zip(outs0, outs2) if a != b])
check("...no root and no snapshot byte (its failures stay inside _emit_history)",
      roots0 == roots2 and json.dumps(plain._snapshot(), sort_keys=True) == json.dumps(boom._snapshot(), sort_keys=True))
check("...and it was actually called (the comparison above is not vacuous)", _calls[0] > 5, _calls[0])

# a reverted call leaves no record: the asset-escrowing accept of the wrong asset (tok) moved tok in and back
reverted = {t for t, o in zip(_all_txids, outs1) if "revert" in o or o.startswith("skip")}
check("a reverted or skipped blob hands the sink nothing", not any(r["txid"] in reverted for r in seen),
      sorted({r["txid"] for r in seen if r["txid"] in reverted}))
check("every record's delta is a signed decimal string and its cursor the block it applied in",
      all(re.fullmatch(r"-?[1-9][0-9]*", r["delta"]) for r in seen)
      and {r["cursor"] for r in seen} <= {h for h, _ in blocks})
# the records reconstruct the ledger exactly: the sum of every recorded delta per (asset, holder) is the final balance
net = {}
for r in seen:
    net[(r["aid"], r["holder"])] = net.get((r["aid"], r["holder"]), 0) + int(r["delta"])
ledger = {(a, h): v for a, row in hist.abal.items() for h, v in row.items()}
check("the recorded moves sum to the ledger, holder by holder (nothing missed, nothing extra)",
      {k: v for k, v in net.items() if v} == ledger, (net, ledger))

# ---- inertness -----------------------------------------------------------------------------------------------------
check("a state with no sink never grows a history buffer", "_hist_buf" not in plain.__dict__
      and ExecState.asset_sink is None and plain.asset_sink is None)
check("a clone (provisional tail, settle_b2.prove_span) never inherits the sink",
      hist.clone().asset_sink is None and "asset_sink" not in hist._snapshot())
for rel in ("execnode/settle_b2.py", "tools/replay_exec.py", "execnode/block_apply.py"):
    src = open(os.path.join(ROOT, rel)).read()
    check(f"{rel} never attaches an asset-history sink", "asset_sink" not in src and "asset_history" not in src)
en = open(os.path.join(ROOT, "execnode", "execnode.py")).read()
_main = en[en.index("async def main():"):]
check("the exec node enables the index only from main() (importing it — as tests do — opens nothing)",
      en.count("_asset_history_enable()") >= 1 and "if _ASSET_HISTORY_ON:\n        _asset_history_enable()" in _main
      and en[:en.index("async def main():")].count("if _ASSET_HISTORY_ON") == 0)
check("it is ON by default with an opt-out (NADO_EXEC_ASSET_HISTORY=0)",
      'os.environ.get("NADO_EXEC_ASSET_HISTORY", "1")' in en and '"0"' in en.split("_ASSET_HISTORY_ON =", 1)[1][:200])

_report.done()
