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
from ops import da as _da
DA_DIR = os.environ.get("NADO_EXEC_DA", "exec_da")
DA_N_MAX = 64          # bound attacker-supplied meta.n so a lied manifest can't drive an unbounded fetch loop
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
    """The ExecState for the request's ?ns= (default 'default'), or None if this node doesn't run that ns.
    ?provisional=1 returns the fast PRE-FINALITY clone (unfinalized L1 tail speculatively applied), so a
    dApp sees moves within ~one block (~6s) instead of a full finality window; falls back to the finalized
    state when the provisional view isn't ready. Provisional is display-only — settlement/proofs read the
    finalized state (a plain fetch, no ?provisional)."""
    ns = request.query.get("ns", "default")
    if request.query.get("provisional") in ("1", "true", "yes"):
        pv = prov_states
        if pv is not None and ns in pv:
            return pv[ns]
    return states.get(ns)


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


# PROVISIONAL (fast, pre-finality) view: clones of the finalized states with the UNFINALIZED L1 tail
# speculatively applied. Rebuilt every poll from the finalized checkpoint, so a reorg self-heals on the next
# rebuild and no persistent/finalized state is ever touched. Readers opt in with ?provisional=1. None until
# the first refresh (readers then fall back to the finalized state).
prov_states = None
PROV_MAX_TAIL = 64          # cap the speculative tail depth (bounds work if this node is far behind the tip)


async def _apply_block(session, states_map, default_state, block, verbose=True):
    """Apply ONE L1 block's exec-relevant txs — blobs to their namespace in states_map, bridge/shield to
    default_state — then advance every state's cursor to this height. Returns False (applying NOTHING) if a
    field_transfer proof is unavailable via DA, so the block STALLS in L1 order. Shared by the finalized tail
    AND the provisional clone, so both apply identically."""
    h = block["block_number"]
    # DA PRE-RESOLVE (all-or-nothing): resolve every field_transfer proof BEFORE mutating, so one missing
    # proof stalls the whole block rather than half-applying it (every node fetches the same bundle -> no divergence).
    resolved = {}
    for tx in block.get("block_transactions", []):
        d = tx.get("data")
        if (tx.get("recipient") == "blob" and isinstance(d, dict)
                and d.get("op") == "field_transfer" and d.get("proof_da") and "bundle_json" not in d):
            bb = await da_fetch(session, d["proof_da"])
            if bb is None:
                if verbose:
                    print(f"[execnode] block {h}: a field_transfer proof is UNAVAILABLE via DA — stalling at {h}", flush=True)
                return False
            resolved[tx.get("txid")] = bb.decode()
    for tx in block.get("block_transactions", []):
        if tx.get("txid") in resolved and isinstance(tx.get("data"), dict):
            tx = {**tx, "data": {**tx["data"], "bundle_json": resolved[tx["txid"]]}}
        r = tx.get("recipient")
        if r == "blob":
            d = tx.get("data")
            bns = d.get("ns", "default") if isinstance(d, dict) else "default"
            tgt = states_map.get(bns)
            if tgt is not None:
                res = tgt.apply_blob(d, tx.get("sender"), tx.get("txid"))
                if verbose:
                    print(f"[execnode] block {h} ns={bns}: {res}", flush=True)
        elif r == "xmsg":
            d = tx.get("data") or {}
            tgt = states_map.get(d.get("to_ns"))
            if tgt is not None:
                res = tgt.apply_xmsg(d.get("from_ns", "default"), d.get("message") or {})
                if verbose:
                    print(f"[execnode] block {h} ns={d.get('to_ns')}: {res}", flush=True)
        elif r == "bridge":
            default_state.credit_deposit(tx.get("sender"), tx.get("amount", 0))
            if verbose:
                print(f"[execnode] block {h}: bridge deposit {tx.get('amount')} by {(tx.get('sender') or '')[:12]}…", flush=True)
        elif r == "shield":
            d = tx.get("data") or {}
            if d.get("field"):
                res = default_state.apply_field_shield(tx.get("amount", 0), d.get("owner"), d.get("rho"))
            else:
                res = default_state.apply_shield(tx.get("amount", 0), d.get("out_commitments", []), d.get("openings", []))
            if verbose:
                print(f"[execnode] block {h}: {res}", flush=True)
        elif r == "reveal":
            # RANDAO reveal (#randao): accumulate the secret into every namespace's beacon accumulator, so the
            # BEACON opcode can read the same grind-resistant chain randomness consensus derives.
            d = tx.get("data") or {}
            for _st in states_map.values():
                _st.record_reveal(d.get("target_epoch"), d.get("secret"))
    for _st in states_map.values():
        _st.cursor = h
        _st.advance_beacons(h)      # cache every epoch beacon now finalized at this height
        _st.record_block_hash(h, block.get("block_hash"))   # BLOCKHASH randomness for this finalized height
    return True


# key of the last COMPLETE provisional build: (finalized, tip, tip_hash, sum of base-state versions).
# tip_hash pins the whole unfinalized tail (parent-hash linkage), the version sum pins the base states —
# so an identical key proves the rebuild would reproduce the exact same clones. None -> always rebuild.
_prov_key = None


async def _refresh_provisional(session, finalized, tip, tip_hash=None):
    """Rebuild the provisional states: clone the finalized states and speculatively apply the UNFINALIZED
    tail (finalized+1 .. tip). Rebuilt from the finalized checkpoint every poll, so a reorg self-heals and no
    persistent state can be corrupted. Best-effort: leaves prov_states None (readers fall back to finalized)
    if there's nothing unfinalized."""
    global prov_states, _prov_key
    tip = min(tip, finalized + PROV_MAX_TAIL)
    if tip <= finalized:
        prov_states = None
        _prov_key = None
        return
    key = (finalized, tip, tip_hash, sum(st._mut_gen for st in states.values()))
    if prov_states is not None and tip_hash is not None and key == _prov_key:
        return                                   # nothing changed since the last COMPLETE build — keep it
    clones = {ns: st.clone() for ns, st in states.items()}
    default_clone = clones.get("default")
    h = finalized + 1
    while h <= tip:
        block = await _get_json(session, f"/get_block_number?number={h}")
        if not isinstance(block, dict) or "block_transactions" not in block:
            break                                # unfetchable / body-less -> stop the speculative tail here
        if not await _apply_block(session, clones, default_clone, block, verbose=False):
            break
        h += 1
    prov_states = clones
    # record the key only for a COMPLETE build; a partial one (fetch break) must retry next poll
    _prov_key = key if h > tip else None


async def tail_loop():
    """Follow L1 forever: each poll, replay every newly FINALIZED block's exec-relevant txs (blob /
    bridge / shield) into `state` in block order — skipping pruned (body-less) finalized blocks — then
    accrue the presence dividend, persist, settle if enabled, and rebuild the fast PROVISIONAL view over the
    unfinalized tail. Only FINALIZED blocks mutate the persistent state, so its cursor never handles a reorg;
    the provisional clone absorbs the tail (and any reorg) harmlessly. Any error waits out the poll; never dies."""
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
                        # cold-start on a pruned chain. Advance only the default cursor (the loop watermark);
                        # other ns cursors catch up on the next block with a body.
                        state.cursor = h
                        continue
                    if not await _apply_block(session, states, state, block, verbose=True):
                        break                                  # DA stall: do NOT advance the cursor; retry next poll
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
                # Rebuild the PROVISIONAL view EVERY poll (even with no newly-finalized block — the tip still
                # advances ~every block_time, so a just-included bet/reveal/deposit shows within ~one block
                # instead of a whole finality window). Best-effort; never breaks the finalized tail.
                try:
                    latest = await _get_json(session, "/get_latest_block")
                    tip = int(latest.get("block_number", state.cursor)) if isinstance(latest, dict) else state.cursor
                    tip_hash = latest.get("block_hash") if isinstance(latest, dict) else None
                    await _refresh_provisional(session, state.cursor, tip, tip_hash)
                except Exception as e:
                    print(f"[execnode] provisional refresh error: {e}", flush=True)
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


async def _da_sources(session):
    """DA endpoints to try for a shard, in order — UNIVERSAL, no single hardcoded provider:
    the live L1 PEER SET (each peer runs the exec/DA node on the same convention port), plus an optional
    NADO_DA_URL seed. Availability rides the peer network, so any node that holds a shard can serve it."""
    out, seen = [], set()
    try:
        async with session.get(L1 + "/peers", timeout=aiohttp.ClientTimeout(total=10)) as r:
            peers = await r.json() if r.status == 200 else []
    except Exception:
        peers = []
    for p in (peers or []):
        host = str(p).split(":")[0].strip()                 # peer IP, strip any :port
        url = f"http://{host}:{PORT}" if host else ""       # its exec/DA node (same host, exec port)
        if url and url not in seen:
            seen.add(url); out.append(url)
    if DA_URL and DA_URL not in seen:
        out.append(DA_URL)                                  # optional extra seed, NOT the only source
    return out


async def da_fetch(session, commitment):
    """Resolve `commitment` to bytes: local store first, else collect k(+1) VERIFIED shards from ACROSS the
    peer network (any peers that hold them) and reconstruct trustlessly. Caches the result locally so this
    node can then re-serve it (proofs spread organically as nodes fetch). Returns bytes or None if the whole
    reachable network can't supply k good shards."""
    local = DA.get(commitment)
    if local is not None:
        return local
    meta, pairs = None, {}
    for src in await _da_sources(session):
        try:
            if meta is None:
                async with session.get(f"{src}/da/meta?c={commitment}",
                                       timeout=aiohttp.ClientTimeout(total=10)) as r:
                    meta = await r.json() if r.status == 200 else None
                # meta is UNTRUSTED (from a peer). Bound k/n before iterating so a lied manifest can't drive
                # an unbounded fetch loop; the definitive check is the commitment round-trip after reconstruct.
                if isinstance(meta, dict) and not (1 <= int(meta.get("k", 0)) <= int(meta.get("n", 0)) <= DA_N_MAX):
                    meta = None
            if meta is None:
                continue
            need = int(meta["k"]) + 1                        # +1 gives da.reconstruct its consistency check
            for i in range(int(meta["n"])):
                if i in pairs:
                    continue
                async with session.get(f"{src}/da/shard?c={commitment}&i={i}",
                                       timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status != 200:
                        continue
                    jj = await r.json()
                pairs[i] = (i, bytes.fromhex(jj["shard"]), jj["proof"])
                if len(pairs) >= need:
                    break
            if len(pairs) >= need:
                break
        except Exception:
            continue
    if meta is None or len(pairs) < int(meta["k"]):
        return None
    try:
        k, n = int(meta["k"]), int(meta["n"])
        data = reconstruct_from(meta, list(pairs.values()))  # verifies every shard vs the commitment
        # The shards are bound to the commitment, but k/n/stripes/length came from an UNTRUSTED peer meta and
        # steer the decode (e.g. a smaller `length` truncates to different bytes that still pass the shard
        # checks). Round-trip: re-encode the result and require it to reproduce the ON-CHAIN commitment, so a
        # lied manifest is rejected and every honest node reconstructs identical bytes (determinism).
        if _da.encode(data, k, n)["commitment"] != commitment:
            return None
        DA.put(data, k, n)                                   # cache -> we can now serve it too
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


async def h_examples(request):
    """The starter contract library (execnode/contract_lib.py) as {name: {method: bytecode}} — the wallet's
    Rollup tab offers these as one-click deploys."""
    from execnode import contract_lib
    return web.json_response({"examples": contract_lib.LIBRARY})   # name -> {code, abi}


async def h_runtimes(request):
    """The contract runtimes this node can execute (pluggable — stackvm is the default). A deploy blob may
    name one via {"op":"deploy","runtime":"<name>",...}."""
    from execnode import runtimes
    return web.json_response({"runtimes": runtimes.names(), "default": runtimes.DEFAULT_RUNTIME})


async def h_contracts(request):
    """Contracts in ?ns= (cid, deployer, method names, runtime) — storage omitted, use /exec/contract.
    SCALABLE: bounded + filterable so a huge namespace doesn't dump everything. Query params:
      ?deployer=<addr>  only that deployer's contracts (the wallet's "my contracts")
      ?prefix=<hex>     only cids starting with <prefix> (search-as-you-type)
      ?limit=<n>        cap the returned rows (default 100, max 500)
    Returns {ns, contracts:[…], total, limit} where total is the full match count (may exceed limit)."""
    st = _state_for(request)
    if st is None:
        return _NS404()
    q_deployer = request.query.get("deployer")
    q_prefix = request.query.get("prefix", "")
    try:
        limit = max(1, min(500, int(request.query.get("limit", "100"))))
    except (TypeError, ValueError):
        limit = 100
    items, total = [], 0
    for cid, c in st.contracts.items():
        if q_deployer and c["deployer"] != q_deployer:
            continue
        if q_prefix and not cid.startswith(q_prefix):
            continue
        total += 1
        if len(items) < limit:
            items.append({"cid": cid, "deployer": c["deployer"], "methods": list(c["code"].keys()),
                          "runtime": c.get("runtime", "stackvm"), "abi": c.get("abi") or {}})
    return web.json_response({"ns": request.query.get("ns", "default"), "contracts": items,
                              "total": total, "limit": limit})


async def h_contract(request):
    """One contract in full (?cid=&ns=): deployer, method names, and its ENTIRE storage. 404 if unknown."""
    st = _state_for(request)
    if st is None:
        return _NS404()
    cid = request.query.get("cid", "")
    c = st.contracts.get(cid)
    if not c:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response({"cid": cid, "deployer": c["deployer"], "methods": list(c["code"].keys()),
                              "code": c["code"], "storage": c["storage"], "runtime": c.get("runtime", "stackvm"),
                              "abi": c.get("abi") or {}})


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


# (coinflip read endpoints removed — the Coin Flip dApp reads its state from the generic /exec/contract
# endpoint, since it is now an on-chain contract, not a native module)


async def h_blockhash(request):
    """One or more L1 block hashes for the BLOCKHASH randomness (?height=H  or  ?heights=H1,H2,…). Returns
    {height: hex|null} — null if the height is in the future or older than the node retains. Lets a game UI
    derive the same result the contract will (e.g. show the dice/wheel before anyone settles).

    DEFAULT is the FINALIZED state — a hash there can never reorg. This MUST be used for HIDDEN information
    (Hold'em hole cards): a provisional hash that reorged would silently show a player a different hand at
    showdown than they played. ?provisional=1 opts INTO the fast pre-finality tail — only safe for PUBLIC,
    on-chain-VALIDATED randomness (Farkle dice, wheel spins): if such a hash reorgs, the settling tx simply
    reverts and the player re-acts — a visible retry, never silent unfairness. It cuts the reveal wait from
    ~FINALITY_DEPTH blocks (~90s) to ~one block (~6-18s)."""
    ns = request.query.get("ns", "default")
    if request.query.get("provisional") in ("1", "true", "yes") and prov_states and ns in prov_states:
        st = prov_states[ns]           # fast pre-finality tail (opt-in; public+validated randomness only)
    else:
        st = states.get(ns)            # finalized: immutable, safe for hidden info
    if st is None:
        return _NS404()
    q = request.query
    hs = []
    if q.get("height"):
        hs = [q["height"]]
    elif q.get("heights"):
        hs = q["heights"].split(",")
    out = {}
    for h in hs:
        try:
            hi = int(h); v = st.block_hashes.get(hi)
            out[str(hi)] = (format(v, "x") if v is not None else None)
        except Exception:
            pass
    return web.json_response({"cursor": st.cursor, "hashes": out})


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
    """All exec-side bridge balances plus every recorded (still-claimable) withdrawal record.
    ?provisional=1 reads the fast pre-finality clone (display-only, like every other provisional read);
    bridge balances live on the DEFAULT layer regardless of ?ns=, so pick the default clone directly."""
    st = state
    if request.query.get("provisional") in ("1", "true", "yes"):
        pv = prov_states
        if pv is not None and "default" in pv:
            st = pv["default"]
    return web.json_response({"balances": st.bridge, "withdrawals": st.withdrawals, "cursor": st.cursor})


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
    # doesn't, which is why it worked in tests but not in the wallet). Allow any origin. NOTE: the /exec/*
    # routes are read-only or compute-only — the /exec/prove_transfer[2] delegated provers PROVE and RETURN a
    # proof, they don't mutate (DA-only: transfers apply solely via the L1-ordered blob stream). They are
    # UNAUTHENTICATED — safe to expose because (a) the exec node binds loopback unless NADO_EXEC_BIND is opened,
    # (b) the STARK size bound rejects oversized inputs before allocation, and (c) an in-flight semaphore caps
    # concurrent proving. /da/publish is likewise size-capped + semaphore-bounded. Also answer the CORS preflight.
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
    # Exec state is live + per-request (finalized vs ?provisional). NEVER let a proxy/CDN cache it, or two
    # clients can see divergent game/balance state. no-store beats any edge caching regardless of the fetch's
    # own cache mode.
    resp.headers["Cache-Control"] = "no-store"
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
    """Delegated prover, 1-output (DA-only): the wallet POSTs its SECRET witness (nsk, note opening, output,
    amounts); we build the Merkle path and prove the join-split STARK off the event loop, then RETURN the
    proof as bundle_json. The caller publishes it to /da/publish + submits the commitment blob; we NEVER apply
    out-of-band. Semaphore-bounded (H-7); UNAUTHENTICATED, hence the loopback-by-default bind."""
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
        async with _sem():                                 # H-7: bound concurrent proving
            bundle, public = await asyncio.to_thread(_prove)   # heavy STARK proving off the event loop
            if w.get("withdraw_addr"):
                bundle["withdraw_addr"] = w["withdraw_addr"]
        # DA-ONLY (alphanet, no legacy single-operator apply): the delegated prover RETURNS the proof; the
        # caller publishes it to /da/publish and submits an L1 blob carrying only the commitment, so every
        # exec node applies it in L1 order. The exec node NEVER applies a transfer out-of-band. The bundle
        # rides as an opaque JSON STRING (its big field ints survive re-parse).
        return web.json_response({
            "bundle_json": json.dumps(bundle),
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


async def h_prove_transfer2(request):
    """Delegated prover, 2-output (send v1 to recipient + keep v2 change) — otherwise identical to
    h_prove_transfer: prove off-loop, then RETURN bundle_json for the caller to DA-publish + blob (no apply)."""
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
        async with _sem():                                 # H-7: bound concurrent proving
            bundle, public = await asyncio.to_thread(_prove)
            if w.get("withdraw_addr"):
                bundle["withdraw_addr"] = w["withdraw_addr"]
        # DA-ONLY: return the proof; the caller publishes it to DA + submits the commitment blob (see
        # h_prove_transfer). No out-of-band apply.
        return web.json_response({
            "bundle_json": json.dumps(bundle),
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
                    web.post("/exec/prove_transfer", h_prove_transfer),
                    web.post("/exec/prove_transfer2", h_prove_transfer2),
                    web.get("/exec/shielded_note", h_shielded_note),
                    web.get("/exec/unshields", h_unshields),
                    web.get("/exec/unshield_proof", h_unshield_proof),
                    web.get("/exec/examples", h_examples),
                    web.get("/exec/runtimes", h_runtimes),
                    web.get("/exec/contracts", h_contracts),
                    web.get("/exec/contract", h_contract),
                    web.get("/exec/view", h_view),
                    web.get("/exec/blockhash", h_blockhash),
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
