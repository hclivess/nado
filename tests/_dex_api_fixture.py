"""Shared stand-in chain for the DEX API end-to-end tests (tests/test_the_dex_api_*).

The REAL pieces: an ExecState with the real `otc` and `dex` contracts, the exec node's own /exec/otc, /exec/amm and
MCP handlers, and the node's own consensus checks on every submitted transaction (validate_txid, the key-derives-the-
sender binding, the ML-DSA signature, _validate_htlc_lock). The STAND-IN: an L1 that lands each accepted transaction in
its own block (cursor + 1) and keeps HTLCs and bridge balances in dicts — enough for the SDK, the MCP servers and the
API to be driven exactly as a bot drives them against the public relay.

Import after _harness.isolate(). It imports the exec node, so if nothing has isolated the process yet it isolates it
itself — imported on its own it must never reach the live node's HOME or exec state (CLAUDE.md rule 4).
"""
import os
import tempfile
import _harness
if not os.environ.get("NADO_EXEC_STATE", "").startswith(tempfile.gettempdir()):
    _harness.isolate("nado-test-dex-fixture-")
import asyncio
import hashlib
import json
import logging
import os
import tempfile
import time

from aiohttp import web
from aiohttp.test_utils import TestServer

import execnode.execnode as EN
from execnode.state import ExecState
from execnode.games import otc as O, dex as D
from execnode import otc_api, amm_api
from ops.transaction_ops import validate_txid, _validate_htlc_lock
from ops.address_ops import proof_sender
from signatures import verify, unhex
from protocol import CHAIN_ID

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(REPO, "static")


class Chain:
    def __init__(self, home):
        self.st = st = ExecState(os.path.join(tempfile.mkdtemp(dir=home), "s.json"))
        st.cursor, st.block_ts = 100, int(time.time())
        code = O.build()
        st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": O.ABI, "nonce": "n"}, "deployer", "d")
        self.otc = st.contract_id("deployer", code, "n")
        self.dex = st.apply_blob({"op": "deploy", "code": D.build(), "nonce": "x", "runtime": "zkvm", "abi": D.ABI},
                                 "deployer", "d2").split()[1]
        otc_api.OTC_CID, amm_api.DEX_CID = self.otc, self.dex      # the handlers default to these — point them here
        EN.states, EN.state, EN.prov_states = {"default": st}, st, None
        self.tip, self.htlcs, self.submitted, self.l1 = 5000, {}, [], {}
        self.results = []

    # ---- the L1: the node's own checks, then land the tx in its own block ----
    def accept(self, tx):
        st = self.st
        if not validate_txid(tx, logging.getLogger("t")):
            return "txid does not hash the body"
        if tx.get("chain_id") != CHAIN_ID:
            return "wrong chain_id"
        if not proof_sender(tx["public_key"], tx["sender"]):
            return "public key does not derive the sender"
        if not verify(tx["signature"], tx["public_key"], unhex(tx["txid"])):
            return "bad signature"
        if not int(tx["max_block"]) > self.tip:
            return "max_block already passed"
        if tx.get("min_block") is not None and int(tx["min_block"]) <= self.tip:
            return "min_block guard below the tip"
        r, d = tx["recipient"], tx.get("data")
        if r == "blob":
            if int(tx["fee"]) < 1000:
                return "fee below minimum"
            self.results.append(st.apply_blob(d, tx["sender"], tx["txid"]))
        elif r == "bridge":
            if int(tx["fee"]) < 1000 or int(tx["amount"]) <= 0 or self.l1.get(tx["sender"], 0) < int(tx["amount"]):
                return "bad deposit"
            self.l1[tx["sender"]] -= int(tx["amount"])
            st.bridge[tx["sender"]] = st.bridge.get(tx["sender"], 0) + int(tx["amount"])
        elif r == "bridge_withdraw":
            w = st.withdrawals.get(str(d.get("nonce")))
            if int(tx["fee"]) != 0 or d.get("addr") != tx["sender"] or not w or int(w["amount"]) != int(d["amount"]) or d.get("proof") != "P":
                return "bad bridge claim"
            del st.withdrawals[str(d["nonce"])]
            self.l1[tx["sender"]] = self.l1.get(tx["sender"], 0) + int(d["amount"])
        elif r == "htlc_lock":
            try:
                _validate_htlc_lock(tx)
            except AssertionError as e:
                return str(e)
            self.htlcs[tx["txid"]] = {"sender": tx["sender"], "claimant": d["claimant"], "amount": int(tx["amount"]),
                                      "hashlock": d["hashlock"], "expiry": d["expiry"], "status": "open"}
        elif r == "htlc_claim":
            h = self.htlcs.get(d.get("htlc_id"))
            if not h or h["status"] != "open" or tx["sender"] != h["claimant"] or int(tx["fee"]) != 0:
                return "bad claim"
            if hashlib.sha256(bytes.fromhex(d["preimage"])).hexdigest() != h["hashlock"]:
                return "preimage does not match the hashlock"
            h["status"] = "claimed"
        else:
            return "unexpected recipient " + r
        self.submitted.append(tx)
        st.cursor += 1                       # each tx lands in its own block: per-cursor caches and batches move on
        st.block_ts += 6
        self.tip += 1
        return None

    def app(self):
        async def submit(request):
            why = self.accept(json.loads(await request.text()))
            return web.json_response({"result": why is None, "message": why or "ok"})

        async def withdrawals(request):
            a = request.query.get("address")
            return web.json_response({"address": a, "pending": [
                {"nonce": n, "amount": str(int(w["amount"])), "proof": "P", "state_root": "R"}
                for n, w in self.st.withdrawals.items() if w.get("addr") == a]})
        j = web.json_response
        a = web.Application()
        a.add_routes([
            web.post("/submit_transaction", submit),
            web.get("/status", lambda r: j({"chain_id": CHAIN_ID})),
            web.get("/get_latest_block", lambda r: j({"block_number": self.tip})),
            web.get("/get_htlc", lambda r: j({"htlc": self.htlcs.get(r.query.get("id"))})),
            web.get("/get_settled", lambda r: j({"state_root": "R"})),
            web.get("/exec/withdrawals", withdrawals),
            web.get("/exec/root", lambda r: j({"ns": "default", "cursor": self.st.cursor, "block_ts": self.st.block_ts})),
            web.get("/exec/asset", EN.h_asset), web.get("/exec/contract", EN.h_contract),
            web.get("/exec/otc", EN.h_otc_index), web.get("/exec/dexapi", EN.h_otc_index),
            web.get("/exec/otc/markets", EN.h_otc_markets), web.get("/exec/otc/book", EN.h_otc_book),
            web.get("/exec/otc/order", EN.h_otc_order), web.get("/exec/otc/orders", EN.h_otc_orders),
            web.get("/exec/otc/trades", EN.h_otc_trades), web.get("/exec/otc/intra", EN.h_otc_intra),
            web.get("/exec/amm/pools", EN.h_amm_pools), web.get("/exec/amm/pool", EN.h_amm_pool),
            web.get("/exec/amm/quote", EN.h_amm_quote), web.get("/exec/amm/order", EN.h_amm_order),
            web.get("/exec/amm/position", EN.h_amm_position), web.get("/exec/amm/balance", EN.h_amm_balance),
            web.post("/exec/otc/mcp", EN.h_otc_mcp), web.get("/exec/otc/mcp", EN.h_otc_mcp)])
        return a

    async def serve(self):
        self.srv = TestServer(self.app(), port=0)
        await self.srv.start_server()
        return str(self.srv.make_url("")).rstrip("/")


async def node(js, env=None):
    """Run an ES module snippet against the SDK (`D` = static/nadodex.mjs); its last stdout line is JSON."""
    src = f'import * as D from "file://{STATIC}/nadodex.mjs";\n' + js
    p = await asyncio.create_subprocess_exec("node", "--input-type=module", "-e", src, stdout=asyncio.subprocess.PIPE,
                                             stderr=asyncio.subprocess.PIPE, env=dict(os.environ, **(env or {})))
    out, err = await asyncio.wait_for(p.communicate(), 300)
    if p.returncode != 0:
        raise RuntimeError(err.decode()[-800:])
    return json.loads(out.decode().strip().splitlines()[-1])


def sdk(base, seed):
    """The prefix that makes `dex` a NadoDex on this chain with `seed` (fast polling for the multi-step helpers)."""
    return (f'const dex = new D.NadoDex({{ relay: "{base}", key: "{seed}" }});\n'
            'const _w = dex.waitFor.bind(dex); dex.waitFor = (p, o) => _w(p, Object.assign({ everyMs: 200 }, o || {}));\n')


class Mcp:
    """The local MCP server over stdio, as an MCP client speaks to it."""
    def __init__(self, env):
        self.env, self.n = env, 0

    async def __aenter__(self):
        self.p = await asyncio.create_subprocess_exec("node", os.path.join(STATIC, "nadodex-mcp.mjs"), stdin=asyncio.subprocess.PIPE,
                                                      stdout=asyncio.subprocess.PIPE, env=dict(os.environ, **self.env))
        return self

    async def rpc(self, method, params=None, notify=False):
        m = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            self.n += 1
            m["id"] = self.n
        self.p.stdin.write((json.dumps(m) + "\n").encode())
        await self.p.stdin.drain()
        if notify:
            return None
        return json.loads(await asyncio.wait_for(self.p.stdout.readline(), 300))

    async def call(self, name, args=None):
        r = (await self.rpc("tools/call", {"name": name, "arguments": args or {}}))["result"]
        return r, r["content"][0]["text"]

    async def __aexit__(self, *a):
        self.p.stdin.close()
        try:
            await asyncio.wait_for(self.p.wait(), 10)
        except asyncio.TimeoutError:
            self.p.kill()
