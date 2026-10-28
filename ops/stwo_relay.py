"""THE STWO SPEND RELAY: every node publishes wallets' private Stwo spends under its OWN account (doc/stwo-migration.md
§5.1, "Who publishes a spend"). ON BY DEFAULT ON EVERY NODE; a node opts out with "stwo_relay": false in
private/config.json (read with .get(..., True): get_config() does not merge new defaults, CLAUDE.md rule 9).

WHY (ZK review 2026-10-11, reproduced by tests/test_a_stwo_spend_is_not_published_under_the_spenders_own_account.mjs).
A Stwo proof hides which note is spent and whose it is — and the wallet then published it in a `field_transfer` blob
that the spender's own account signed and paid for, tying every nullifier to an account. Someone has to sign the L1
transaction that carries a spend; if it is the spender, the proof's privacy is gone. So a node signs it instead, and
is paid inside the proof: the wallet proves its spend with unshield = the relay's fee and withdraw_addr = the relay's
address, which the proof BINDS (aux), so the relay can be paid and cannot be paid more or redirected. The L1 tx then
names the node, never the spender. No consensus change: to the exec layer this is an ordinary unshield to an address.

WHAT THE NODE CHECKS BEFORE IT SPENDS ANYTHING (its fee, its DA store), in cost order:
  1. it relays at all: enabled, not in emergency/recovery (a blob built off a stale tip seeded fork h67088 — the
     auto-collect rule), a per-IP rate and a bounded in-flight set;
  2. the bundle reads as the exec layer reads it — shielded_stwo.parse_transfer, the SAME function
     ExecState._apply_stwo_transfer calls (never a second reading here);
  3. it pays THIS node: withdraw_addr == the node's address and unshield >= STWO_RELAY_FEE_RAW;
  4. its nullifier is not already in flight here (dedupe: two tabs, a retry, a replay);
  5. the exec node would apply it in the next block, proof aside: /exec/stwo_spendable, which answers through
     ExecState.stwo_spend_refusal — the same method the apply path asks (anchor, nullifier, duplicates, room, value);
  6. the proof verifies: execnode/stwo_js_native.verify, the exec layer's own verifier. A node without the
     library refuses (NativeMissing) — and says so in /stwo/relay_info, so wallets never pick it.
Then it publishes the bundle to its exec node's DA store, signs a `field_transfer` blob with the node key
(transaction_ops.construct_blob_tx, the path its own collect blob takes) and submits it through merge_transaction +
push gossip, exactly as a user's submit is handled. THE KEY IS THE NODE OPERATOR'S NODE KEY (memserver.keydict) —
never a user's; a user's key never reaches this module (CLAUDE.md rule 8).

The relay learns the spend's public inputs and the requester's IP, nothing else: no note, no owner, no amount beyond
the public unshield (its own fee). A wallet that distrusts one relay uses another.
"""
import json
import threading
import time

from protocol import MIN_TX_FEE, TX_INCLUSION_DELAY, TX_TARGET_MARGIN

# THE FEE. What one relayed spend costs this node: the field_transfer blob's L1 fee (MIN_TX_FEE, burned) plus the DA
# store's bytes (~3 MiB of proof, no protocol fee) and, later, the fee-exempt `unshield` claim that brings the fee to
# L1. 100 x MIN_TX_FEE (1e5 raw = 0.00001 NADO) covers the burned fee a hundred times over — margin for the CPU of a
# verify and a DA write, and for the spends that are refused only after the node paid (a lost race on a nullifier) —
# while staying far below anything a user notices. ONE value on every node, so a relayed spend's public unshield is
# the same number whoever relays it (a per-node fee would be one more thing that tells spends apart).
STWO_RELAY_FEE_RAW = 100 * MIN_TX_FEE
# a stwo_js bundle is ~2.9 MB of proof, hex-encoded ~5.8 MB in JSON; nginx in front of a relay allows 20 MiB
STWO_RELAY_MAX_BODY = 16 * 1024 * 1024
STWO_RELAY_PER_IP = 12            # relayed spends per IP per window: a payment over several banknotes is one each
STWO_RELAY_WINDOW_S = 600
STWO_RELAY_INFLIGHT_MAX = 64      # nullifiers this node is publishing at once (bounds memory and fee exposure)
# a nullifier stays "in flight" as long as its blob can still land (TX_TARGET_MARGIN blocks at ~6.8 s, with margin);
# after that the exec view (step 5) is what refuses a replay
STWO_RELAY_HOLD_S = 45 * 60
# the handler's pre-read bounds: bodies in flight at once, and the most `[`/`{` bytes a real bundle can carry (a stwo_js
# bundle is {"bundle": {"stark": {"stwo_js": {…}}, …}} — a handful of objects, no arrays of note data)
_BODIES_AT_ONCE = 2
_MAX_BRACKETS = 64


class Refused(Exception):
    """A relay request that is refused: (status, reason). Nothing has been spent when one is raised before publish."""

    def __init__(self, status, reason):
        super().__init__(reason)
        self.status, self.reason = status, reason


class StwoRelay:
    """The relay's decisions, independent of HTTP (make_handlers wires it to aiohttp; nado.py to the node).

    keydict_fn() -> the node's keydict; tip_fn() -> its tip height; exec_get(path) -> JSON from this host's exec node
    or None; da_publish(bytes) -> the DA commitment string (raises on failure); submit(tx) -> merge_transaction's
    result dict; enabled_fn()/healthy_fn() -> bool; allow(key, limit, window) -> bool (ops.ratelimit.allow)."""

    def __init__(self, *, keydict_fn, tip_fn, exec_get, da_publish, submit, enabled_fn=lambda: True,
                 healthy_fn=lambda: True, allow=None, clock=time.time, balance_fn=None):
        if allow is None:
            from ops.ratelimit import allow
        self.keydict_fn, self.tip_fn, self.exec_get, self.da_publish, self.submit = \
            keydict_fn, tip_fn, exec_get, da_publish, submit
        self.enabled_fn, self.healthy_fn, self.allow, self.clock = enabled_fn, healthy_fn, allow, clock
        self.balance_fn = balance_fn      # -> the node account's L1 balance in raw, or None when unknown
        self.inflight = {}                # nf -> expiry time
        self.lock = threading.Lock()

    # ---- availability ---------------------------------------------------------------------------------------------
    def _verifier_ready(self):
        from execnode import stwo_js_native
        from execnode.native_guard import NativeMissing
        try:
            stwo_js_native.ensure_loaded()
            return True
        except NativeMissing:
            return False

    def info(self):
        """What GET /stwo/relay_info answers: whether this node relays right now, to which address, for what fee."""
        out = {"available": False, "fee": STWO_RELAY_FEE_RAW, "address": None, "reason": ""}
        try:
            out["address"] = self.keydict_fn()["address"]
        except Exception:
            out["reason"] = "no node key"
            return out
        if not self.enabled_fn():
            out["reason"] = "this node does not relay (stwo_relay: false)"
        elif not self.healthy_fn():
            out["reason"] = "this node is recovering its chain view"
        elif not self._can_pay():
            out["reason"] = "this node cannot pay the L1 fee of a relayed spend"
        elif not self._verifier_ready():
            out["reason"] = "this node has no Stwo verifier"
        else:
            live = self.exec_get("/exec/field_shielded")
            if not isinstance(live, dict):
                out["reason"] = "this node runs no exec node"
            elif live.get("pool") != "stwo":
                out["reason"] = "the Stwo pool is not live"
            else:
                out["available"] = True
        return out

    def _can_pay(self):
        """The node can pay the blob's L1 fee: a node at zero balance advertised itself, published the proof to DA and
        only then got its own tx refused (502) — the wallet moved on, but the DA write and the user's wait were spent
        (loopback walk 2026-10-12). Unknown balance (no balance_fn, a read error) does not block: the submit still
        refuses honestly. Margin: a few fees, so a burst in one block does not run it dry mid-way."""
        if self.balance_fn is None:
            return True
        try:
            b = self.balance_fn()
        except Exception:
            return True
        return b is None or int(b) >= 4 * MIN_TX_FEE

    # ---- the relay ------------------------------------------------------------------------------------------------
    def _prune(self, now):
        for nf in [k for k, exp in self.inflight.items() if exp <= now]:
            del self.inflight[nf]

    def relay(self, req, ip):
        """req = {"bundle": <stwo_js bundle>} -> (response dict, HTTP status). Never raises."""
        try:
            return self._relay(req, ip), 200
        except Refused as r:
            return {"ok": False, "reason": r.reason}, r.status
        except Exception as e:                      # a bug here must not look like a relayed spend
            return {"ok": False, "reason": f"relay error: {str(e)[:200]}"}, 500

    def _relay(self, req, ip):
        from execnode import shielded_stwo as _S
        from execnode.state import MAX_EXIT_VALUE
        # 1. this node relays at all
        if not self.enabled_fn():
            raise Refused(503, "this node does not relay private spends")
        if not self.healthy_fn():
            raise Refused(503, "this node is recovering its chain view: try another relay")
        if not self._can_pay():
            raise Refused(503, "this relay cannot pay the L1 fee right now: try another relay")
        if not self.allow(f"stwo_relay|{ip}", STWO_RELAY_PER_IP, STWO_RELAY_WINDOW_S):
            raise Refused(429, "too many private spends from this address: slow down")
        bundle = req.get("bundle") if isinstance(req, dict) else None
        # 2. THE ONE READING (shielded_stwo.parse_transfer), the exec layer's own
        # fee_to read here whatever the height: whether the exec layer accepts it yet is asked in step 5 (fee_to=1)
        why, sp = _S.parse_transfer(bundle, MAX_EXIT_VALUE, fee_to_ok=True)
        if why:
            raise Refused(400, why.replace("skip field-transfer: ", ""))
        # 3. it pays THIS node, at least the fee
        # TWO WAYS TO PAY A RELAY: from STWO_FEE_TO_HEIGHT by the spend's `fee` with fee_to = this relay (the payout then
        # goes anywhere — a shadow account), or as before by the unshield itself (withdraw_addr = this relay)
        me = self.keydict_fn()["address"]
        if sp["fee_to"] is not None:
            if sp["fee_to"] != me:
                raise Refused(400, "the spend's fee does not pay this relay: prove it with fee_to = this relay's address")
            if sp["fee"] < STWO_RELAY_FEE_RAW:
                raise Refused(400, f"the relay fee is {STWO_RELAY_FEE_RAW} raw: prove the spend with fee >= it")
        else:
            if sp["addr"] != me:
                raise Refused(400, "the spend does not pay this relay: prove it with withdraw_addr = this relay's address")
            if sp["unshield"] < STWO_RELAY_FEE_RAW:
                raise Refused(400, f"the relay fee is {STWO_RELAY_FEE_RAW} raw: prove the spend with unshield >= it")
        nf = sp["nf"]
        # 4. dedupe + bound: claim the nullifier before any expensive step, release it on every refusal below
        now = self.clock()
        with self.lock:
            self._prune(now)
            if nf in self.inflight:
                raise Refused(409, "this spend is already being published")
            if len(self.inflight) >= STWO_RELAY_INFLIGHT_MAX:
                raise Refused(429, "this relay is busy: try another relay")
            self.inflight[nf] = now + STWO_RELAY_HOLD_S
        published = False
        try:
            # 5. the exec node would apply it next block (ExecState.stwo_spend_refusal, the apply path's own method)
            # `land`: the LAST block this relay's blob can land in (its max_block, tip + TX_TARGET_MARGIN below). The exec
            # node judges the anchor there too, so a root that ages out before the blob can land is refused here, before
            # a fee is paid (review 2026-10-12: anchors on the edge of the window made relays pay for doomed spends).
            land = int(self.tip_fn()) + TX_TARGET_MARGIN
            q = (f"/exec/stwo_spendable?root={sp['root']}&nf={nf}&cm1={sp['cm1']}&cm2={sp['cm2']}"
                 f"&unshield={sp['unshield']}&fee={sp['fee']}&land={land}"
                 + ("&fee_to=1" if sp["fee_to"] is not None else ""))
            v = self.exec_get(q)
            if not isinstance(v, dict):
                raise Refused(503, "this relay's exec node is unreachable: try another relay")
            if not v.get("live"):
                raise Refused(409, "the Stwo pool is not live")
            if not v.get("ok"):
                raise Refused(409, str(v.get("reason") or "the exec layer would refuse this spend")
                              .replace("skip field-transfer: ", ""))
            # 6. the proof, by the exec layer's own verifier
            from execnode import stwo_js_native
            from execnode.native_guard import NativeMissing
            try:
                # at the config of the height it is targeted to land at (STWO_JS_128_HEIGHT). A spend can straddle the
                # gate only on a chain where it is a real height; on gen 28 it is 2^62 and on gen 29 it is 1, so never.
                ok, reason = stwo_js_native.verify(sp["proof"], sp["root"], nf, sp["cm1"], sp["cm2"], sp["unshield"],
                                                   sp["fee"], sp["dest"], int(land))
            except NativeMissing:
                raise Refused(503, "this relay has no Stwo verifier: try another relay")
            if not ok:
                raise Refused(400, f"the proof does not verify: {reason}")
            # ---- every check passed: from here the node spends (DA bytes, then its L1 fee) ----
            commitment = self.da_publish(json.dumps(bundle, separators=(",", ":")).encode())
            if not commitment:
                raise Refused(503, "this relay could not publish the proof to DA")
            from ops.transaction_ops import construct_blob_tx
            tip = land - TX_TARGET_MARGIN                    # the tip the anchor was judged at: max_block == land, exactly
            # min_block (tip + TX_INCLUSION_DELAY): gossips to every producer before any may include it (identical
            # mempools -> identical blocks); a wide max lets it land through a slow stretch, as the node's own blobs
            tx = construct_blob_tx(self.keydict_fn(), {"op": "field_transfer", "proof_da": commitment},
                                   tip + TX_TARGET_MARGIN, MIN_TX_FEE, min_block=tip + TX_INCLUSION_DELAY)
            res = self.submit(tx)
            published = True
            if not (isinstance(res, dict) and res.get("result")):
                raise Refused(502, "the node refused its own transaction: "
                              + str((res or {}).get("message") if isinstance(res, dict) else res)[:200])
            return {"ok": True, "txid": tx["txid"], "commitment": commitment, "relay": me, "fee": sp["unshield"]}
        except BaseException:
            # a refusal BEFORE the node submitted frees the nullifier for a retry (here or elsewhere); after a submit,
            # whatever the pool said, the hold stays: a second copy of this spend must not cost a second fee
            if not published:
                with self.lock:
                    self.inflight.pop(nf, None)
            raise


def make_handlers(relay, ip_of, max_body=STWO_RELAY_MAX_BODY):
    """aiohttp handlers for GET /stwo/relay_info and POST /stwo/relay over a StwoRelay; ip_of(request) -> the caller's
    IP (nado.py passes its proxy-aware _ip)."""
    import asyncio
    from aiohttp import web
    cors = {"Access-Control-Allow-Origin": "*"}
    _inflight = [0]                  # bodies being read/decoded right now (one event loop: no lock needed)

    async def relay_info(request):
        out = await asyncio.to_thread(relay.info)
        return web.json_response(out, headers=cors)

    async def relay_post(request):
        if request.method == "OPTIONS":
            return web.Response(status=204, headers={**cors, "Access-Control-Allow-Methods": "POST, OPTIONS",
                                                     "Access-Control-Allow-Headers": "Content-Type"})
        cl = request.content_length
        if cl is not None and cl > max_body:
            return web.json_response({"ok": False, "reason": "body too large"}, status=413, headers=cors)
        # BEFORE THE BODY IS READ OR DECODED (review 2026-10-12): a 16 MiB `[[],[],…]` cost 18 s of CPU and ~430 MB on
        # the event loop, and the per-IP limit only ran afterwards. Now: the rate limit (its own bucket, so the relay's
        # own count below is unchanged), at most _BODIES_AT_ONCE bodies in flight, and a shape check by byte count —
        # a real bundle is a few objects around one long hex string, so a body with more brackets than that is refused
        # without parsing (json.loads holds the GIL, so a worker thread alone would not have helped).
        ip = ip_of(request)
        if not relay.allow(f"stwo_relay_body|{ip}", STWO_RELAY_PER_IP, STWO_RELAY_WINDOW_S):
            return web.json_response({"ok": False, "reason": "too many private spends from this address: slow down"},
                                     status=429, headers=cors)
        if _inflight[0] >= _BODIES_AT_ONCE:
            return web.json_response({"ok": False, "reason": "this relay is busy: try another relay"}, status=429,
                                     headers=cors)
        _inflight[0] += 1
        try:
            try:
                body = await request.read()
                if len(body) > max_body:
                    return web.json_response({"ok": False, "reason": "body too large"}, status=413, headers=cors)
                if body.count(b"[") + body.count(b"{") > _MAX_BRACKETS:
                    return web.json_response({"ok": False, "reason": "not a Stwo spend bundle"}, status=400, headers=cors)
                req = await asyncio.to_thread(json.loads, body)
            except Exception:
                return web.json_response({"ok": False, "reason": "the body is not JSON"}, status=400, headers=cors)
            out, status = await asyncio.to_thread(relay.relay, req, ip)
            return web.json_response(out, status=status, headers=cors)
        finally:
            _inflight[0] -= 1

    return relay_info, relay_post
