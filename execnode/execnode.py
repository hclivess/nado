"""
NADO execution node (Phase 1) — the "beside the node" process.

It TAILS an L1 NADO node over plain HTTP, pulls the ordered `blob` payloads out of FINALIZED blocks,
replays them through the deterministic VM (execnode.state / execnode.vm), and persists the resulting
contract state. It also serves a small READ-ONLY query API so wallets and tools can read contract state
and run view methods. It never speaks to L1 consensus — a VM bug here can't fork the chain
(doc/execution-layer.md §3.2). Run one per operator who wants programmability; phones do not.

Env:
  NADO_L1_URL      L1 node base URL     (default http://127.0.0.1:9173)
  NADO_EXEC_STATE  state file path      (default ./exec_state.json)
  NADO_EXEC_PORT   query API port       (default 9273)
  NADO_EXEC_POLL   poll seconds         (default 5)

Run:  python execnode/execnode.py
Query:  curl localhost:9273/exec/root
        curl 'localhost:9273/exec/view?cid=<id>&method=balanceOf&args=["ndo…"]'
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp
from aiohttp import web

from execnode.state import ExecState

L1 = os.environ.get("NADO_L1_URL", "http://127.0.0.1:9173").rstrip("/")
STATE_PATH = os.environ.get("NADO_EXEC_STATE", "exec_state.json")
PORT = int(os.environ.get("NADO_EXEC_PORT", "9273"))
POLL = float(os.environ.get("NADO_EXEC_POLL", "5"))
# Phase 2: if this node is a BONDED validator, post settlement attestations of its computed state root
# (needs its keys.dat via HOME). NADO_EXEC_SETTLE=1 to enable; settles at most every SETTLE_EVERY blocks.
SETTLE = os.environ.get("NADO_EXEC_SETTLE", "").strip().lower() in ("1", "true", "yes", "on")
SETTLE_EVERY = int(os.environ.get("NADO_EXEC_SETTLE_EVERY", "5"))

state = ExecState(STATE_PATH)
_last_settled_cursor = -1


async def maybe_settle(session):
    """If enabled, post a `settle` attestation of the current (cursor, state_root) to L1 — but only once
    the cursor has advanced SETTLE_EVERY blocks since the last one. Best-effort; never fatal."""
    global _last_settled_cursor
    if _last_settled_cursor >= 0 and state.cursor - _last_settled_cursor < SETTLE_EVERY:
        return
    try:
        from ops.transaction_ops import construct_settle_tx
        from ops.key_ops import load_keys
        keys = load_keys()
        latest = await _get_json(session, "/get_latest_block")
        tx = construct_settle_tx(keys, state.cursor, state.state_root(), int(latest["block_number"]) + 2)
        async with session.post(L1 + "/submit_transaction", json=tx,
                                timeout=aiohttp.ClientTimeout(total=15)) as r:
            out = await r.json(content_type=None)
        if isinstance(out, dict) and out.get("result"):
            _last_settled_cursor = state.cursor
            print(f"[execnode] SETTLE cursor {state.cursor} root {state.state_root()[:16]}… → L1", flush=True)
        else:
            print(f"[execnode] settle not accepted: {out}", flush=True)
    except Exception as e:
        print(f"[execnode] settle error: {e}", flush=True)


async def _get_json(session, path):
    async with session.get(L1 + path, timeout=aiohttp.ClientTimeout(total=15)) as r:
        return await r.json(content_type=None)


async def tail_loop():
    print(f"[execnode] tailing {L1} · state={STATE_PATH} · cursor={state.cursor}", flush=True)
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                status = await _get_json(session, "/status")
                finalized = int(status.get("finalized_height", 0))
                applied = 0
                while state.cursor < finalized:
                    h = state.cursor + 1
                    block = await _get_json(session, f"/get_block_number?number={h}")
                    if not isinstance(block, dict) or "block_transactions" not in block:
                        break                                  # not available yet; retry next poll
                    for tx in block.get("block_transactions", []):
                        if tx.get("recipient") == "blob":
                            res = state.apply_blob(tx.get("data"), tx.get("sender"), tx.get("txid"))
                            print(f"[execnode] block {h}: {res}", flush=True)
                    state.cursor = h
                    applied += 1
                if applied:
                    state.save()
                    print(f"[execnode] +{applied} block(s) → cursor {state.cursor} · "
                          f"root {state.state_root()[:16]}… · {len(state.contracts)} contract(s)", flush=True)
                    if SETTLE:
                        await maybe_settle(session)
            except Exception as e:
                print(f"[execnode] tail error: {e}", flush=True)
            await asyncio.sleep(POLL)


# --- read-only query API ---------------------------------------------------------------------------
async def h_root(request):
    return web.json_response({"state_root": state.state_root(), "cursor": state.cursor,
                              "contracts": len(state.contracts), "l1": L1})


async def h_contracts(request):
    return web.json_response({"contracts": [
        {"cid": cid, "deployer": c["deployer"], "methods": list(c["code"].keys())}
        for cid, c in state.contracts.items()]})


async def h_contract(request):
    cid = request.query.get("cid", "")
    c = state.contracts.get(cid)
    if not c:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response({"cid": cid, "deployer": c["deployer"],
                              "methods": list(c["code"].keys()), "storage": c["storage"]})


async def h_view(request):
    import json
    cid = request.query.get("cid", "")
    method = request.query.get("method", "")
    try:
        args = json.loads(request.query.get("args", "[]"))
    except Exception:
        args = []
    return web.json_response({"cid": cid, "method": method, "result": state.view(cid, method, args)})


async def main():
    app = web.Application()
    app.add_routes([web.get("/exec/root", h_root),
                    web.get("/exec/contracts", h_contracts),
                    web.get("/exec/contract", h_contract),
                    web.get("/exec/view", h_view)])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    print(f"[execnode] query API on :{PORT}", flush=True)
    await tail_loop()


if __name__ == "__main__":
    asyncio.run(main())
