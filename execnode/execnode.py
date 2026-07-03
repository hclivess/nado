"""
NADO execution node (Phase 1) — the "beside the node" process.

It TAILS an L1 NADO node over plain HTTP, pulls the ordered `blob` payloads out of FINALIZED blocks,
replays them through the deterministic VM (execnode.state / execnode.vm), and persists the resulting
contract state. It also serves a small READ-ONLY query API so wallets and tools can read contract state
and run view methods. It never speaks to L1 consensus — a VM bug here can't fork the chain
(doc/execution-layer.md §3.2). Run one per operator who wants programmability; phones do not.

Env:
  NADO_L1_URL          L1 node base URL     (default http://127.0.0.1:9173)
  NADO_EXEC_STATE      state file path      (default ./exec_state.json)
  NADO_EXEC_PORT       query API port       (default 9273)
  NADO_EXEC_BIND       bind address         (default 127.0.0.1 — loopback-only; set 0.0.0.0 to let remote
                                             browsers reach the shielded pool. H-7: the mutating POST endpoints
                                             are unauthenticated, so exposing them is opt-in.)
  NADO_EXEC_MAX_INFLIGHT  concurrent prove/apply cap (default 2 — bounds CPU/memory under a POST flood)
  NADO_EXEC_POLL       poll seconds         (default 5)

Run:  python execnode/execnode.py
Query:  curl localhost:9273/exec/root
        curl 'localhost:9273/exec/view?cid=<id>&method=balanceOf&args=["ndo…"]'
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp
from aiohttp import web

from execnode.state import ExecState

L1 = os.environ.get("NADO_L1_URL", "http://127.0.0.1:9173").rstrip("/")
STATE_PATH = os.environ.get("NADO_EXEC_STATE", "exec_state.json")
PORT = int(os.environ.get("NADO_EXEC_PORT", "9273"))
# H-7: loopback by default — the /exec POST endpoints prove/verify/apply and mutate state without auth, so a
# public bind is opt-in (a browser-reachable shielded pool sets NADO_EXEC_BIND=0.0.0.0). Even when exposed, the
# STARK size bound (stark.MAX_TRACE_ROWS) and the in-flight cap below bound a single request and a flood.
BIND = os.environ.get("NADO_EXEC_BIND", "127.0.0.1")
MAX_INFLIGHT = max(1, int(os.environ.get("NADO_EXEC_MAX_INFLIGHT", "2")))
MAX_BODY_BYTES = int(os.environ.get("NADO_EXEC_MAX_BODY", str(16 * 1024 * 1024)))   # cap POST size (proofs are ~1-4MB)
POLL = float(os.environ.get("NADO_EXEC_POLL", "5"))
# H-7: cap concurrent proving/applying so a flood of POSTs can't exhaust CPU/memory (each prove is a full
# STARK; each apply verifies a ~1MB proof). Created lazily on the running loop.
_inflight = None
def _sem():
    global _inflight
    if _inflight is None:
        _inflight = asyncio.Semaphore(MAX_INFLIGHT)
    return _inflight
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
                    if not isinstance(block, dict):
                        break                                  # fetch problem; retry next poll
                    if "block_transactions" not in block:
                        # A FINALIZED block (h <= finalized) with no body is PRUNED (rolling mode drops old
                        # block bodies, leaving only {block_number}). Such blocks predate the exec features and
                        # carry nothing to replay, so SKIP them — otherwise a fresh exec node can never
                        # cold-start on a pruned chain. (A body that is merely lagging can't be finalized.)
                        state.cursor = h
                        continue
                    for tx in block.get("block_transactions", []):
                        r = tx.get("recipient")
                        if r == "blob":
                            res = state.apply_blob(tx.get("data"), tx.get("sender"), tx.get("txid"))
                            print(f"[execnode] block {h}: {res}", flush=True)
                        elif r == "bridge":                          # L1 deposit -> credit exec-side balance
                            state.credit_deposit(tx.get("sender"), tx.get("amount", 0))
                            print(f"[execnode] block {h}: bridge deposit {tx.get('amount')} by "
                                  f"{(tx.get('sender') or '')[:12]}…", flush=True)
                        elif r == "shield":                          # L1 shielded-pool deposit -> add the notes
                            d = tx.get("data") or {}
                            if d.get("field"):                       # Phase-2 field-native note
                                # C-2: value is bound to the L1 escrow — the exec node recomputes the note
                                # commitment from tx.amount + the depositor's (owner, rho), never a client cm.
                                res = state.apply_field_shield(tx.get("amount", 0), d.get("owner"), d.get("rho"))
                            else:
                                res = state.apply_shield(tx.get("amount", 0), d.get("out_commitments", []),
                                                         d.get("openings", []))
                            print(f"[execnode] block {h}: {res}", flush=True)
                    state.cursor = h
                    applied += 1
                if applied:
                    # PRESENCE DIVIDEND (doc/presence-dividend.md): distribute the DIVIDEND_POOL growth among
                    # the CURRENTLY-PRESENT open miners, fidelity-weighted. Read the pool balance + present
                    # weights from L1; accrue_dividend only credits miners in this epoch's present set.
                    try:
                        pool = await _get_json(session, "/get_account?address=dividend")
                        pool_bal = int(pool.get("balance", 0)) if isinstance(pool, dict) and "balance" in pool else 0
                        ow = await _get_json(session, "/get_open_weights")
                        weights = (ow or {}).get("weights", {}) if isinstance(ow, dict) else {}
                        dist = state.accrue_dividend(pool_bal, weights)
                        if dist:
                            print(f"[execnode] dividend +{dist} raw to {len(weights)} present miner(s)", flush=True)
                    except Exception as e:
                        print(f"[execnode] dividend accrue error: {e}", flush=True)
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


async def h_bridge(request):
    return web.json_response({"balances": state.bridge, "withdrawals": state.withdrawals})


async def h_withdrawal_proof(request):
    # the Merkle proof a user submits to L1's bridge_withdraw to claim their exit against the settled root
    p = state.withdrawal_proof(request.query.get("nonce", ""))
    if not p:
        return web.json_response({"error": "not found"}, status=404)
    p["state_root"] = state.state_root()
    return web.json_response(p)


async def h_dividend(request):
    # a miner's accrued (uncollected) presence dividend + any COLLECTED-but-not-yet-claimed withdrawals (each
    # provable against the settled root via /exec/dividend_proof). Off-L1 (doc/presence-dividend.md). No addr -> all.
    addr = request.query.get("address")
    if addr:
        pending = [{"nonce": n, "amount": w["amount"]} for n, w in sorted(state.dividend_withdrawals.items())
                   if w["addr"] == addr]
        return web.json_response({"address": addr, "accrued": int(state.dividend.get(addr, 0)),
                                  "pending": pending, "cursor": state.cursor})
    return web.json_response({"dividend": state.dividend, "cursor": state.cursor})


async def h_dividend_proof(request):
    # the Merkle proof a miner submits to L1's dividend_withdraw to claim a collection against the settled root
    p = state.dividend_withdrawal_proof(request.query.get("nonce", ""))
    if not p:
        return web.json_response({"error": "not found"}, status=404)
    p["state_root"] = state.state_root()
    return web.json_response(p)


@web.middleware
async def _cors(request, handler):
    # The light-miner page is served by the L1 node on a DIFFERENT port (:9173), so every /exec/* fetch from
    # the browser is cross-origin — without these headers the browser silently blocks the response (curl
    # doesn't, which is why it worked in tests but not in the wallet). Allow any origin. NOTE: most /exec/*
    # routes are read-only, but /exec/apply_field_transfer and /exec/prove_transfer[2] DO mutate the pool and
    # are UNAUTHENTICATED — they are safe to expose only because (a) the exec node binds loopback unless
    # NADO_EXEC_BIND is opened, (b) the STARK size bound rejects oversized proofs before allocation, and (c) an
    # in-flight semaphore caps concurrent proving/applying. Also answer the CORS preflight.
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as exc:
            resp = exc
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "*"
    return resp


async def h_shielded(request):
    # Public shielded-pool state: the current Merkle root (an anchor), note count, and spent-nullifier count.
    # Reveals NOTHING about individual notes/owners/values (doc/privacy.md).
    return web.json_response({"root": state.shielded.root(), "notes": state.shielded.size(),
                             "nullifiers": len(state.shielded.nullifiers), "cursor": state.cursor,
                             "anchors": state.shielded.anchor_list[-8:]})


async def h_field_shielded(request):
    # Phase-2 field-native pool status + (optionally) a commitment's position.
    fp = state.field_pool
    cm = request.query.get("cm")
    pos = fp.position(int(cm)) if (cm and cm.lstrip("-").isdigit()) else None
    return web.json_response({"root": str(fp.root()), "notes": len(fp.commitments),
                              "nullifiers": len(fp.nullifiers), "cursor": state.cursor, "pos": pos})


async def h_prove_transfer(request):
    # DELEGATED PROVER: the wallet POSTs its secret witness; we build the Merkle path from the field pool and
    # produce the full join-split STARK proof. Returns the bundle as an opaque JSON string (big field ints).
    try:
        w = await request.json()
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)
    fp = state.field_pool
    try:
        pos = fp.position(int(w["cm"]))
        if pos is None:
            return web.json_response({"error": "note not in the field pool"}, status=404)
        from execnode import shielded_field as SFP

        def _prove():
            return SFP.prove_transfer(fp, int(w["nsk"]), int(w["value_in"]), int(w["rho_in"]), pos,
                                      int(w["out_value"]), int(w["out_owner"]), int(w["out_rho"]),
                                      int(w["public_value"]), int(w["fee"]), withdraw_addr=w.get("withdraw_addr"))
        async with _sem():                                 # H-7: bound concurrent proving/applying
            bundle, public = await asyncio.to_thread(_prove)   # heavy STARK proving off the event loop
            if w.get("withdraw_addr"):
                bundle["withdraw_addr"] = w["withdraw_addr"]
            # The exec node is BOTH the delegated prover and the pool authority: prove -> verify -> APPLY. The
            # 900KB+ proof never touches L1 — only the small settled result does (via the bonded-quorum state
            # root, like the bridge). apply runs off the event loop; its nullifier critical section + save are
            # serialized by ExecState._mutate_lock (M-10).
            applied = await asyncio.to_thread(state.apply_field_transfer, bundle)
            await asyncio.to_thread(state.save)
        ok = "skip" not in applied
        return web.json_response({
            "applied": applied, "ok": ok,
            "root": str(public["root"]), "nf": str(public["nullifiers"][0]),
            "cm_out": str(public["out_commitments"][0]),
            "public_value": public["public_value"], "fee": public["fee"],
        })
    except KeyError as e:
        return web.json_response({"error": f"missing witness field {e}"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def h_field_leaves(request):
    # the field pool's commitment list (public) so the browser can build the Merkle path itself and prove
    # ON-DEVICE (the node never sees the witness). Big ints as strings.
    return web.json_response({"leaves": [str(c) for c in state.field_pool.commitments]})


def _normalize_bundle(bundle):
    # a browser-generated bundle carries big field ints as STRINGS (JSON can't hold BigInt) -> back to ints
    js = (bundle.get("stark") or {}).get("joinsplit2")
    if not js:
        return
    for k in ("root", "nf", "cm_out1", "cm_out2", "public_value", "fee"):
        if k in js and js[k] is not None:
            js[k] = int(js[k])
    p = js.get("proof") or {}
    for f in ("T", "W", "N", "blowup", "deg_bound", "D"):
        if f in p:
            p[f] = int(p[f])
    fr = p.get("fri") or {}
    if "offset" in fr:
        fr["offset"] = int(fr["offset"])
    if "final" in fr:
        fr["final"] = [int(x) for x in fr["final"]]
    for q in fr.get("queries", []):
        for s in q.get("steps", []):
            s["lo"] = int(s["lo"]); s["hi"] = int(s["hi"])
    for op in p.get("openings", []):
        for c in op.get("cols", []):
            c["cur"] = int(c["cur"]); c["nxt"] = int(c["nxt"])


async def h_apply_field_transfer(request):
    # ON-DEVICE path: the browser already proved; we only VERIFY + APPLY (the witness never reached us).
    try:
        bundle = await request.json()
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)
    try:
        _normalize_bundle(bundle)
        async with _sem():                                 # H-7: bound concurrent verify+apply
            applied = await asyncio.to_thread(state.apply_field_transfer, bundle)
            await asyncio.to_thread(state.save)
        js = (bundle.get("stark") or {}).get("joinsplit2") or {}
        return web.json_response({"applied": applied, "ok": "skip" not in applied,
                                  "cm_out1": str(js.get("cm_out1")), "cm_out2": str(js.get("cm_out2"))})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def h_prove_transfer2(request):
    # DELEGATED PROVER, 2-output: send v1 to a recipient + keep v2 change. Proves -> verifies -> applies.
    try:
        w = await request.json()
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)
    fp = state.field_pool
    try:
        pos = fp.position(int(w["cm"]))
        if pos is None:
            return web.json_response({"error": "note not in the field pool"}, status=404)
        from execnode import shielded_field as SFP

        def _prove():
            return SFP.prove_transfer2(fp, int(w["nsk"]), int(w["value_in"]), int(w["rho_in"]), pos,
                                       int(w["v1"]), int(w["o1"]), int(w["r1"]),
                                       int(w["v2"]), int(w["o2"]), int(w["r2"]),
                                       int(w["public_value"]), int(w["fee"]), withdraw_addr=w.get("withdraw_addr"))
        async with _sem():                                 # H-7: bound concurrent proving/applying
            bundle, public = await asyncio.to_thread(_prove)
            if w.get("withdraw_addr"):
                bundle["withdraw_addr"] = w["withdraw_addr"]
            applied = await asyncio.to_thread(state.apply_field_transfer, bundle)
            await asyncio.to_thread(state.save)
        return web.json_response({
            "applied": applied, "ok": "skip" not in applied,
            "root": str(public["root"]), "nf": str(public["nullifiers"][0]),
            "cm_out1": str(public["out_commitments"][0]), "cm_out2": str(public["out_commitments"][1]),
        })
    except KeyError as e:
        return web.json_response({"error": f"missing witness field {e}"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def h_shielded_note(request):
    # a wallet's spend witness: position + Merkle path for its note commitment (public data, leaks nothing),
    # plus whether the note's nullifier is already spent (the wallet passes its own nf).
    cm = request.query.get("cm", "")
    p = state.shielded_note_proof(cm)
    if not p:
        return web.json_response({"error": "not found"}, status=404)
    nf = request.query.get("nf")
    if nf:
        p["spent"] = state.shielded.has_nullifier(nf)
    return web.json_response(p)


async def h_unshields(request):
    # a wallet lists its own pending unshield exits (by L1 address) to find the nonce(s) to claim
    return web.json_response({"unshields": state.unshields_for(request.query.get("addr", ""))})


async def h_unshield_proof(request):
    # the Merkle proof a user submits to L1's `unshield` to release SHIELD_ESCROW coins against the settled root
    p = state.unshield_withdrawal_proof(request.query.get("nonce", ""))
    if not p:
        return web.json_response({"error": "not found"}, status=404)
    p["state_root"] = state.state_root()
    return web.json_response(p)


async def main():
    app = web.Application(middlewares=[_cors], client_max_size=MAX_BODY_BYTES)   # H-7: cap POST body size
    app.add_routes([web.get("/exec/root", h_root),
                    web.get("/exec/shielded", h_shielded),
                    web.get("/exec/field_shielded", h_field_shielded),
                    web.get("/exec/field_leaves", h_field_leaves),
                    web.post("/exec/apply_field_transfer", h_apply_field_transfer),
                    web.post("/exec/prove_transfer", h_prove_transfer),
                    web.post("/exec/prove_transfer2", h_prove_transfer2),
                    web.get("/exec/shielded_note", h_shielded_note),
                    web.get("/exec/unshields", h_unshields),
                    web.get("/exec/unshield_proof", h_unshield_proof),
                    web.get("/exec/contracts", h_contracts),
                    web.get("/exec/contract", h_contract),
                    web.get("/exec/view", h_view),
                    web.get("/exec/bridge", h_bridge),
                    web.get("/exec/withdrawal_proof", h_withdrawal_proof),
                    web.get("/exec/dividend", h_dividend),
                    web.get("/exec/dividend_proof", h_dividend_proof)])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, BIND, PORT).start()
    print(f"[execnode] query API on {BIND}:{PORT}"
          + ("" if BIND != "0.0.0.0" else "  (PUBLIC — mutating /exec POSTs are unauthenticated; bounded by size cap + in-flight limit)"),
          flush=True)
    await tail_loop()


if __name__ == "__main__":
    asyncio.run(main())
