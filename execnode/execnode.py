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

# --- DA layer: erasure-coded availability for the shielded-transfer STARK proofs (too big for an L1 blob,
# so only the transfer STATEMENT + the proof's `commitment` ride on-chain). This node keeps a local DaStore;
# NADO_DA_URL is a peer DA node to fetch a proof from by commitment when we don't hold it locally.
from ops.da_store import DaStore, reconstruct_from
DA_DIR = os.environ.get("NADO_EXEC_DA", "exec_da")
DA_URL = os.environ.get("NADO_DA_URL", "").rstrip("/")
DA_K = int(os.environ.get("NADO_DA_K", "4"))
DA_N = int(os.environ.get("NADO_DA_N", "8"))
DA = DaStore(DA_DIR)
# H-7: cap concurrent proving/applying so a flood of POSTs can't exhaust CPU/memory (each prove is a full
# STARK; each apply verifies a ~1MB proof). Created lazily on the running loop.
_inflight = None
def _sem():
    """Lazily create the in-flight semaphore on the RUNNING event loop (import time has no loop)."""
    global _inflight
    if _inflight is None:
        _inflight = asyncio.Semaphore(MAX_INFLIGHT)
    return _inflight
# Phase 2: if this node is a BONDED validator, post settlement attestations of its computed state root
# (needs its keys.dat via HOME). NADO_EXEC_SETTLE=1 to enable; settles at most every SETTLE_EVERY blocks.
SETTLE = os.environ.get("NADO_EXEC_SETTLE", "").strip().lower() in ("1", "true", "yes", "on")
SETTLE_EVERY = int(os.environ.get("NADO_EXEC_SETTLE_EVERY", "5"))

# NAMESPACES this node maintains (multi-rollup). The DEFAULT namespace is the full canonical exec layer
# (contracts + bridge + shielded pool + presence dividend). Any EXTRA namespaces (NADO_EXEC_NAMESPACES,
# comma-separated, validated) are contract-only rollups fed by `blob`s tagged with their ns; each persists to
# its own state file and settles independently. `default` is always present so the wallet's shielded/bridge/
# dividend endpoints keep working.
def _ns_state_path(ns):
    return STATE_PATH if ns == "default" else f"{STATE_PATH}.{ns}"

from protocol import valid_namespace as _valid_ns
_extra_ns = [s.strip() for s in os.environ.get("NADO_EXEC_NAMESPACES", "").split(",")
             if s.strip() and s.strip() != "default" and _valid_ns(s.strip())]
NAMESPACES = ["default"] + _extra_ns
states = {ns: ExecState(_ns_state_path(ns)) for ns in NAMESPACES}
state = states["default"]   # the full-featured default layer; shielded/bridge/dividend endpoints use it
_last_settled_cursor = -1


def _state_for(request):
    """The ExecState for the request's ?ns= (default 'default'), or None if this node doesn't run that ns."""
    return states.get(request.query.get("ns", "default"))


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
        target = int(latest["block_number"]) + 2
        ok_any = False
        for ns, st in states.items():
            tx = construct_settle_tx(keys, st.cursor, st.state_root(), target, ns=ns)
            async with session.post(L1 + "/submit_transaction", json=tx,
                                    timeout=aiohttp.ClientTimeout(total=15)) as r:
                out = await r.json(content_type=None)
            if isinstance(out, dict) and out.get("result"):
                ok_any = True
                print(f"[execnode] SETTLE ns={ns} cursor {st.cursor} root {st.state_root()[:16]}… → L1", flush=True)
            else:
                print(f"[execnode] settle ns={ns} not accepted: {out}", flush=True)
        if ok_any:
            _last_settled_cursor = state.cursor
    except Exception as e:
        print(f"[execnode] settle error: {e}", flush=True)


async def _get_json(session, path):
    """GET an L1 endpoint and decode the JSON body regardless of content-type, with a 15s timeout."""
    async with session.get(L1 + path, timeout=aiohttp.ClientTimeout(total=15)) as r:
        return await r.json(content_type=None)


async def tail_loop():
    """Follow L1 forever: each poll, replay every newly FINALIZED block's exec-relevant txs (blob /
    bridge / shield) into `state` in block order — skipping pruned (body-less) finalized blocks — then
    accrue the presence dividend, persist, and settle if enabled. Only FINALIZED blocks are consumed, so
    the cursor never has to handle a reorg. Any error just waits out the poll interval; the loop never dies."""
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
                            # Route the blob to its namespace's state. A blob's ns lives inside its (opaque-to-L1)
                            # payload; default when absent. Blobs for a namespace this node doesn't run are ignored.
                            d = tx.get("data")
                            bns = d.get("ns", "default") if isinstance(d, dict) else "default"
                            tgt = states.get(bns)
                            if tgt is not None:
                                res = tgt.apply_blob(d, tx.get("sender"), tx.get("txid"))
                                print(f"[execnode] block {h} ns={bns}: {res}", flush=True)
                        elif r == "xmsg":                            # L1-verified cross-domain delivery -> receiver inbox
                            # L1 already verified the message against from_ns's SETTLED root + burned its
                            # nullifier; the exec node just records it in the receiving namespace's inbox.
                            d = tx.get("data") or {}
                            tgt = states.get(d.get("to_ns"))
                            if tgt is not None:
                                res = tgt.apply_xmsg(d.get("from_ns", "default"), d.get("message") or {})
                                print(f"[execnode] block {h} ns={d.get('to_ns')}: {res}", flush=True)
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
                    for _st in states.values():   # every namespace tails the same L1 → advance together
                        _st.cursor = h
                    applied += 1
                if applied:
                    # PRESENCE DIVIDEND (doc/presence-dividend.md) — DETERMINISTIC per-epoch accrual: for each
                    # fully-completed epoch not yet accrued, distribute that epoch's total DIVIDEND_POOL inflow
                    # (L1 /get_dividend_inflow?epoch=E) over weights_at_epoch(E) (L1 /get_open_weights?epoch=E).
                    # Both are epoch-bound, so accrual is a PURE FUNCTION of the finalized block stream —
                    # identical on every node, committed in state_root. (The old code read a LIVE pool balance +
                    # LIVE current-epoch weights per poll batch → non-deterministic → default-layer settlement
                    # divergence.) Dividend is a DEFAULT-layer feature, so it accrues on `state`.
                    try:
                        from protocol import EPOCH_LENGTH
                        cur_epoch = state.cursor // EPOCH_LENGTH
                        while state.last_div_epoch < cur_epoch - 1:      # only epochs the cursor has fully passed
                            E = state.last_div_epoch + 1
                            inf = await _get_json(session, f"/get_dividend_inflow?epoch={E}")
                            inflow = int(inf.get("inflow", 0)) if isinstance(inf, dict) else 0
                            ow = await _get_json(session, f"/get_open_weights?epoch={E}")
                            weights = (ow or {}).get("weights", {}) if isinstance(ow, dict) else {}
                            dist = state.accrue_dividend_epoch(inflow, weights)
                            state.last_div_epoch = E
                            if dist:
                                print(f"[execnode] dividend epoch {E}: +{dist} raw to {len(weights)} miner(s)", flush=True)
                    except Exception as e:
                        print(f"[execnode] dividend accrue error: {e}", flush=True)
                    for _st in states.values():
                        _st.save()
                    print(f"[execnode] +{applied} block(s) → cursor {state.cursor} · "
                          f"root {state.state_root()[:16]}… · {len(state.contracts)} contract(s)"
                          + (f" · +{len(states)-1} rollup ns" if len(states) > 1 else ""), flush=True)
                    if SETTLE:
                        await maybe_settle(session)
            except Exception as e:
                print(f"[execnode] tail error: {e}", flush=True)
            await asyncio.sleep(POLL)


# --- read-only query API ---------------------------------------------------------------------------
_NS404 = lambda: web.json_response({"error": "namespace not served by this node"}, status=404)


# ---- DA serving: publish / fetch erasure-coded objects by commitment -----------------------------
async def h_da_meta(request):
    """GET /da/meta?c=<commitment> — the manifest {commitment,k,n,stripes,length}, or 404 if unknown here."""
    m = DA.meta(request.query.get("c", ""))
    return web.json_response(m) if m else web.json_response({"error": "unknown commitment"}, status=404)


async def h_da_have(request):
    """GET /da/have?c=<commitment> — which shard indices this node currently holds."""
    c = request.query.get("c", "")
    return web.json_response({"commitment": c, "have": DA.have(c)})


async def h_da_shard(request):
    """GET /da/shard?c=<commitment>&i=<index> — one (shard, merkle-proof) the caller can verify against
    the commitment without trusting this node. 404 if not held."""
    c = request.query.get("c", "")
    try:
        i = int(request.query.get("i", ""))
    except (TypeError, ValueError):
        return web.json_response({"error": "bad index"}, status=400)
    r = DA.shard(c, i)
    if not r:
        return web.json_response({"error": "no such shard"}, status=404)
    return web.json_response({"index": i, "shard": r[0].hex(), "proof": r[1]})


async def h_da_publish(request):
    """POST /da/publish — body is the RAW object bytes; erasure-code + store, return the manifest. A
    publisher (prover/wallet) calls this so a shielded proof is available to every exec node by commitment.
    Bounded by MAX_BODY_BYTES and the in-flight semaphore."""
    async with _sem():
        data = await request.read()
        if not data:
            return web.json_response({"error": "empty body"}, status=400)
        meta = await asyncio.to_thread(DA.put, data, DA_K, DA_N)
        return web.json_response(meta)


async def h_da_accept(request):
    """POST /da/accept — {meta, index, shard(hex), proof}: store a single peer-supplied shard IFF it
    verifies against the commitment (spread k-of-n availability). Returns {ok}."""
    try:
        j = await request.json()
        ok = DA.accept(j["meta"], int(j["index"]), bytes.fromhex(j["shard"]), j["proof"])
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    return web.json_response({"ok": bool(ok)})


async def h_da_get(request):
    """GET /da/get?c=<commitment> — reconstruct + return the RAW bytes from locally-held shards (>=k), or
    404. Convenience for a client that trusts this node; the trustless path is /da/meta + /da/shard."""
    data = DA.get(request.query.get("c", ""))
    if data is None:
        return web.json_response({"error": "not reconstructible here"}, status=404)
    return web.Response(body=data, content_type="application/octet-stream")


async def da_fetch(session, commitment):
    """Resolve `commitment` to bytes: local store first, else pull k(+1) VERIFIED shards from the configured
    DA peer (NADO_DA_URL) and reconstruct trustlessly. Caches the result locally so we can re-serve it.
    Returns bytes or None if unavailable."""
    local = DA.get(commitment)
    if local is not None:
        return local
    if not DA_URL:
        return None
    try:
        async with session.get(f"{DA_URL}/da/meta?c={commitment}",
                               timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status != 200:
                return None
            meta = await r.json()
        pairs = []
        for i in range(int(meta["n"])):
            async with session.get(f"{DA_URL}/da/shard?c={commitment}&i={i}",
                                   timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    continue
                jj = await r.json()
            pairs.append((i, bytes.fromhex(jj["shard"]), jj["proof"]))
            if len(pairs) >= int(meta["k"]) + 1:            # +1 gives da.reconstruct its consistency check
                break
        data = reconstruct_from(meta, pairs)                # verifies every shard vs the commitment
        try:
            DA.put(data, int(meta["k"]), int(meta["n"]))    # cache under the same (deterministic) commitment
        except Exception:
            pass
        return data
    except Exception:
        return None


async def h_root(request):
    """Node summary for ?ns= (default): exec state_root, applied cursor, contract count, L1 tailed."""
    st = _state_for(request)
    if st is None:
        return _NS404()
    return web.json_response({"ns": request.query.get("ns", "default"), "state_root": st.state_root(),
                              "cursor": st.cursor, "contracts": len(st.contracts), "l1": L1})


async def h_settlement(request):
    """Settlement status for namespace ?ns= (default): its current (cursor, state_root), whether this node
    posts `settle` attestations (NADO_EXEC_SETTLE), the cadence, the last cursor it settled, and every
    namespace this node runs. The interface combines this with L1's /get_settled?ns= to show tip vs settled."""
    st = _state_for(request)
    if st is None:
        return _NS404()
    return web.json_response({
        "ns": request.query.get("ns", "default"),
        "namespaces": list(states.keys()),
        "cursor": st.cursor,
        "state_root": st.state_root(),
        "contracts": len(st.contracts),
        "settle_enabled": SETTLE,
        "settle_every": SETTLE_EVERY,
        "last_settled_cursor": _last_settled_cursor,
        "l1": L1,
    })


async def h_contracts(request):
    """List every deployed contract in ?ns= (cid, deployer, method names) — storage omitted, use /exec/contract."""
    st = _state_for(request)
    if st is None:
        return _NS404()
    return web.json_response({"ns": request.query.get("ns", "default"), "contracts": [
        {"cid": cid, "deployer": c["deployer"], "methods": list(c["code"].keys())}
        for cid, c in st.contracts.items()]})


async def h_contract(request):
    """One contract in full (?cid=&ns=): deployer, method names, and its ENTIRE storage. 404 if unknown."""
    st = _state_for(request)
    if st is None:
        return _NS404()
    cid = request.query.get("cid", "")
    c = st.contracts.get(cid)
    if not c:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response({"cid": cid, "deployer": c["deployer"],
                              "methods": list(c["code"].keys()), "storage": c["storage"]})


async def h_view(request):
    """Read-only contract call (?cid&method&args=<JSON list>&ns=) via ExecState.view — storage is never
    persisted; unparsable args degrade to []. Result is None for a missing contract/method or a revert."""
    import json
    st = _state_for(request)
    if st is None:
        return _NS404()
    cid = request.query.get("cid", "")
    method = request.query.get("method", "")
    try:
        args = json.loads(request.query.get("args", "[]"))
    except Exception:
        args = []
    return web.json_response({"cid": cid, "method": method, "result": st.view(cid, method, args)})


async def h_outbox(request):
    """List the cross-domain outbox messages emitted by namespace ?ns= (each {seq, from, to_ns, data})."""
    st = _state_for(request)
    if st is None:
        return _NS404()
    return web.json_response({"ns": request.query.get("ns", "default"), "outbox": st.outbox})


async def h_outbox_proof(request):
    """Merkle proof (?ns=&seq=) that outbox message `seq` is committed in the namespace's state_root (also
    returned). A consumer verifies it against the sender rollup's SETTLED root (L1 /get_settled?ns=). 404 if
    the seq is unknown."""
    st = _state_for(request)
    if st is None:
        return _NS404()
    p = st.outbox_proof(request.query.get("seq", ""))
    if p is None:
        return web.json_response({"error": "not found"}, status=404)
    p["ns"] = request.query.get("ns", "default")
    p["state_root"] = st.state_root()
    return web.json_response(p)


async def h_inbox(request):
    """List the cross-domain messages DELIVERED to namespace ?ns= (each {from_ns, seq, data}) — messages an
    L1-verified `xmsg` folded into this rollup's inbox."""
    st = _state_for(request)
    if st is None:
        return _NS404()
    return web.json_response({"ns": request.query.get("ns", "default"), "inbox": st.inbox})


async def h_bridge(request):
    """All exec-side bridge balances plus every recorded (still-claimable) withdrawal record."""
    return web.json_response({"balances": state.bridge, "withdrawals": state.withdrawals})


async def h_withdrawal_proof(request):
    """Merkle proof for a bridge-withdrawal record (?nonce=) against the CURRENT state_root (also
    returned); the claim only succeeds on L1 once a settled root covers it. 404 if the nonce is unknown."""
    # the Merkle proof a user submits to L1's bridge_withdraw to claim their exit against the settled root
    p = state.withdrawal_proof(request.query.get("nonce", ""))
    if not p:
        return web.json_response({"error": "not found"}, status=404)
    p["state_root"] = state.state_root()
    return web.json_response(p)


async def h_dividend(request):
    """Presence-dividend view: with ?address= one miner's accrued balance + pending (collected,
    unclaimed) withdrawals; without it, the whole accrual map."""
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
    """Merkle proof for a collected dividend withdrawal (?nonce=) against the CURRENT state_root,
    submitted to L1's dividend_withdraw once settled. 404 if the nonce is unknown."""
    # the Merkle proof a miner submits to L1's dividend_withdraw to claim a collection against the settled root
    p = state.dividend_withdrawal_proof(request.query.get("nonce", ""))
    if not p:
        return web.json_response({"error": "not found"}, status=404)
    p["state_root"] = state.state_root()
    return web.json_response(p)


@web.middleware
async def _cors(request, handler):
    """Middleware: stamp allow-any-origin CORS headers on every response (HTTP-exception responses
    included) and short-circuit OPTIONS preflights with 204 — required because the wallet page is served
    from the L1 port, making every /exec/* browser fetch cross-origin."""
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
    """Phase-1 pool status: root, note/nullifier counts, recent anchors — aggregate data only, nothing
    per-note."""
    # Public shielded-pool state: the current Merkle root (an anchor), note count, and spent-nullifier count.
    # Reveals NOTHING about individual notes/owners/values (doc/privacy.md).
    return web.json_response({"root": state.shielded.root(), "notes": state.shielded.size(),
                             "nullifiers": len(state.shielded.nullifiers), "cursor": state.cursor,
                             "anchors": state.shielded.anchor_list[-8:]})


async def h_field_shielded(request):
    """Field-native pool status; with ?cm=<int> also that commitment's leaf position (None if absent).
    Big field ints are returned as strings."""
    # Phase-2 field-native pool status + (optionally) a commitment's position.
    fp = state.field_pool
    cm = request.query.get("cm")
    pos = fp.position(int(cm)) if (cm and cm.lstrip("-").isdigit()) else None
    return web.json_response({"root": str(fp.root()), "notes": len(fp.commitments),
                              "nullifiers": len(fp.nullifiers), "cursor": state.cursor, "pos": pos})


async def h_prove_transfer(request):
    """Delegated prover, 1-output: the wallet POSTs its SECRET witness (nsk, note opening, output, amounts);
    we build the Merkle path, prove the join-split STARK off the event loop, then verify+APPLY it locally —
    the ~1MB proof never leaves this node, only the settled root does. Semaphore-bounded (H-7); mutating and
    UNAUTHENTICATED, hence the loopback-by-default bind."""
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
            """Blocking STARK prove, run in a worker thread via asyncio.to_thread."""
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
    """The field pool's full commitment list (public; big ints as strings) so a browser can build its own
    Merkle path and prove ON-DEVICE — the witness never reaches this node."""
    # the field pool's commitment list (public) so the browser can build the Merkle path itself and prove
    # ON-DEVICE (the node never sees the witness). Big ints as strings.
    return web.json_response({"leaves": [str(c) for c in state.field_pool.commitments]})


def _normalize_bundle(bundle):
    """Coerce a browser-generated joinsplit2 bundle's stringified big field ints back to Python ints,
    IN PLACE, everywhere the verifier expects numbers (statement, proof params, FRI, openings). JSON can't
    carry BigInt, so JS serializes them as strings. No-op for non-joinsplit2 bundles."""
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
    if "pow" in fr and fr["pow"] is not None:
        fr["pow"] = int(fr["pow"])                 # C-1 grinding nonce (JSON number -> int)
    if "final" in fr:
        fr["final"] = [int(x) for x in fr["final"]]
    for q in fr.get("queries", []):
        for s in q.get("steps", []):
            s["lo"] = int(s["lo"]); s["hi"] = int(s["hi"])
    for op in p.get("openings", []):
        for c in op.get("cols", []):
            c["cur"] = int(c["cur"]); c["nxt"] = int(c["nxt"])


async def h_apply_field_transfer(request):
    """ON-DEVICE path: the browser POSTs a finished proof bundle; we normalize its string ints, then only
    VERIFY + APPLY (semaphore-bounded) — no witness ever reaches this node. Mutating and unauthenticated,
    same exposure caveats as the prover endpoints."""
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
    """Delegated prover, 2-output (send v1 to recipient + keep v2 change) — otherwise identical to
    h_prove_transfer: prove off-loop, verify, apply, save, all semaphore-bounded."""
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
            """Blocking 2-output STARK prove, run in a worker thread via asyncio.to_thread."""
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
    """Spend witness for a Phase-1 note (?cm=): position + Merkle path (public data, leaks nothing);
    with ?nf= also whether that nullifier is already spent. 404 if the commitment isn't in the pool."""
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
    """Pending unshield exits for an L1 address (?addr=) — how a wallet finds the nonce(s) to claim."""
    # a wallet lists its own pending unshield exits (by L1 address) to find the nonce(s) to claim
    return web.json_response({"unshields": state.unshields_for(request.query.get("addr", ""))})


async def h_unshield_proof(request):
    """Merkle proof for a recorded unshield exit (?nonce=) against the CURRENT state_root, submitted to
    L1's `unshield` to release SHIELD_ESCROW coins once settled. 404 if the nonce is unknown."""
    # the Merkle proof a user submits to L1's `unshield` to release SHIELD_ESCROW coins against the settled root
    p = state.unshield_withdrawal_proof(request.query.get("nonce", ""))
    if not p:
        return web.json_response({"error": "not found"}, status=404)
    p["state_root"] = state.state_root()
    return web.json_response(p)


async def main():
    """Wire up the query API (CORS middleware, body-size cap), start it on BIND:PORT, then run the tail
    loop forever — the HTTP server and the L1 tail share one event loop."""
    app = web.Application(middlewares=[_cors], client_max_size=MAX_BODY_BYTES)   # H-7: cap POST body size
    app.add_routes([web.get("/exec/root", h_root),
                    web.get("/exec/settlement", h_settlement),
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
                    web.get("/exec/outbox", h_outbox),
                    web.get("/exec/outbox_proof", h_outbox_proof),
                    web.get("/exec/inbox", h_inbox),
                    web.get("/exec/bridge", h_bridge),
                    web.get("/exec/withdrawal_proof", h_withdrawal_proof),
                    web.get("/exec/dividend", h_dividend),
                    web.get("/exec/dividend_proof", h_dividend_proof),
                    web.get("/da/meta", h_da_meta),
                    web.get("/da/have", h_da_have),
                    web.get("/da/shard", h_da_shard),
                    web.get("/da/get", h_da_get),
                    web.post("/da/publish", h_da_publish),
                    web.post("/da/accept", h_da_accept)])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, BIND, PORT).start()
    print(f"[execnode] query API on {BIND}:{PORT}"
          + ("" if BIND != "0.0.0.0" else "  (PUBLIC — mutating /exec POSTs are unauthenticated; bounded by size cap + in-flight limit)"),
          flush=True)
    await tail_loop()


if __name__ == "__main__":
    asyncio.run(main())
