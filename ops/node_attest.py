"""node_attest.py — a NODE gets its open-lane identity attested by its operator's real device.

WHY (2026-09-07, gen 25): from betanet-7 every register tx carries a hardware attestation (doc/device-attestation.md),
and a headless node has no secure element and no hand to tap, so the old hands-free auto-register is gone. A node
with no coins therefore earned nothing — until this. The operator attests the node's ADDRESS with their phone,
Windows PC or security key, one tap per lease, exactly what every other open-lane identity pays.

WHY THE BLOB TRAVELS THROUGH A RELAY. WebAuthn only runs on an HTTPS page, and a fresh node has no TLS, so the
phone cannot post to http://<node>:9173 (mixed content) and the node cannot serve the wallet securely. The challenge,
however, binds only (chain id, sender, anchor block hash, max_block) — nothing node-specific — so the wallet on ANY
HTTPS relay can attest for the node's address and DROP the statement on that relay (POST /node_attest_drop). The
relay forwards the drop one hop to its peers, and the node, which is polling its own peers for a drop addressed to
itself whenever it wants a lease (peer loop, every POLL_EVERY s), PICKS it up, builds and SIGNS its own register tx
and merges it like any wallet submission. Nobody but the node can use the blob: the tx must be signed by the
sender's key, and the attestation is bound to that sender + anchor + max_block.

WHAT A DROP CANNOT DO. It is not a transaction, it is never consensus, never persisted, never served except to a
caller that asks for that sender. A stranger dropping a valid attestation for someone else's node only spends their
own tap on that node's benefit. Bounded (MAX_DROPS) and expiring (a drop dies when its max_block passes the tip),
rate-limited at the endpoint like every other wallet-facing route.
"""
import threading
import time

from protocol import EPOCH_LENGTH, FIDELITY_MIN_GAP_EPOCHS, POSW_TARGET_MARGIN

MAX_DROPS = 2000                 # senders held at once (a relay serving many nodes)
MAX_PER_SENDER = 4               # distinct statements kept per sender (a griefer cannot overwrite the real one)
MAX_BYTES = 8 * 1024 * 1024      # total budget of the store — real statements are 1-8 KB; 2000 × 200 KB was a 400 MiB lever
RENEW_TARGET_MARGIN = 30       # blocks ahead a statement-free renewal lands (the wallet's REG_TARGET_MARGIN)
POLL_EVERY = 20.0                # s between a wanting node's peer polls
_MAX_ATT, _MAX_CDJ, _MAX_RP = 16_000, 4_000, 253   # a TPM statement is ~5.4 KB base64, Android ~4 KB, Ledger/Trezor < 8 KB

_lock = threading.Lock()
_drops: dict = {}                # sender -> [ {"device": {att,cdj,rp}, "max_block": int, "at": float, "h": sha256(att)} ... ]
_bytes = [0]


def _is_ek_shape(device) -> bool:
    """The vendor-endorsed TPM statement (doc/tpm-attestation-without-a-ca.md): a certify under an
    attestation key an on-chain enrolment already proved, NOT a WebAuthn blob. It reaches this store by the
    same road and for the same reason — the machine that holds the chip cannot sign for the identity it is
    vouching for, so the finished proof waits here for that wallet to collect."""
    return (isinstance(device, dict)
            and isinstance(device.get("ek"), str) and 0 < len(device["ek"]) <= 128
            and isinstance(device.get("id"), str) and 0 < len(device["id"]) <= 64
            and isinstance(device.get("certinfo"), str) and 0 < len(device["certinfo"]) <= 4096
            and isinstance(device.get("sig"), str) and 0 < len(device["sig"]) <= 2048)


def _valid_device(device) -> bool:
    return _is_ek_shape(device) or (isinstance(device, dict)
            and isinstance(device.get("att"), str) and 0 < len(device["att"]) <= _MAX_ATT
            and isinstance(device.get("cdj"), str) and 0 < len(device["cdj"]) <= _MAX_CDJ
            and isinstance(device.get("rp"), str) and 0 < len(device["rp"]) <= _MAX_RP)


def _identity_and_size(device):
    """(dedupe key, byte size) for either shape. Keyed on the STATEMENT's own bytes so a forwarded echo of
    the same drop is recognised as a duplicate rather than stored twice."""
    import hashlib
    if _is_ek_shape(device):
        blob = "|".join((device["ek"], device["id"], device["certinfo"], device["sig"]))
    else:
        blob = device["att"]
        return hashlib.sha256(blob.encode()).hexdigest(), len(device["att"]) + len(device["cdj"]) + len(device["rp"])
    return hashlib.sha256(blob.encode()).hexdigest(), len(blob)


def drop(sender: str, max_block, device, tip: int) -> dict:
    """Accept a wallet's attestation for `sender`. Shape-checked only — the kernel verdict happens when the node
    builds its tx (memserver.merge_transaction -> transaction_ops.verify_register_device). Returns {ok, reason}."""
    from ops.address_ops import is_address
    if not is_address(sender):
        return {"ok": False, "reason": "sender is not an address"}
    try:
        mb = int(max_block)
    except Exception:
        return {"ok": False, "reason": "max_block missing"}
    # the tx must still be able to land: at most the wallet's proving budget ahead, and not already past
    if not (int(tip) < mb <= int(tip) + POSW_TARGET_MARGIN + 30):
        return {"ok": False, "reason": f"max_block {mb} not within ({tip}, {tip + POSW_TARGET_MARGIN + 30}]"}
    if not _valid_device(device):
        return {"ok": False, "reason": "device statement malformed or too large"}
    h, size = _identity_and_size(device)
    with _lock:
        _prune(int(tip))
        lst = _drops.get(sender)
        if lst is None:
            if len(_drops) >= MAX_DROPS:
                return {"ok": False, "reason": "drop store full"}
            lst = _drops[sender] = []
        if any(b["h"] == h for b in lst):
            return {"ok": True, "dup": True}                       # the same statement again (a forward echo)
        if len(lst) >= MAX_PER_SENDER:
            return {"ok": False, "reason": "too many pending statements for this sender"}
        if _bytes[0] + size > MAX_BYTES:
            return {"ok": False, "reason": "drop store byte budget exhausted"}
        lst.append({"device": {"att": device["att"], "cdj": device["cdj"], "rp": device["rp"]},
                    "max_block": mb, "at": time.time(), "h": h, "size": size})
        _bytes[0] += size
    return {"ok": True}


def _prune(tip: int):
    for s in list(_drops):
        keep = [b for b in _drops[s] if b["max_block"] > tip]
        _bytes[0] -= sum(b["size"] for b in _drops[s] if b["max_block"] <= tip)
        if keep:
            _drops[s] = keep
        else:
            _drops.pop(s, None)
    if _bytes[0] < 0:
        _bytes[0] = 0


def pickup(sender: str, tip: int, consume: bool = False):
    """The NEWEST drop for `sender`, or None (compat). `consume` removes every drop of the sender."""
    lst = pickup_all(sender, tip, consume)
    return lst[-1] if lst else None


def pickup_all(sender: str, tip: int, consume: bool = False):
    """Every live drop for `sender` (oldest first). `consume` removes them (the node that owns the key takes them)."""
    with _lock:
        _prune(int(tip))
        lst = _drops.get(sender) or []
        out = [dict(b) for b in lst]
        if lst and consume:
            _bytes[0] -= sum(b["size"] for b in lst)
            _drops.pop(sender, None)
        return out


def count() -> int:
    with _lock:
        return sum(len(v) for v in _drops.values())


# --- the node's side ------------------------------------------------------------------------------------------

def lease_state(address: str, tip: int) -> dict:
    """{registered, last_recert_epoch, epoch, renewable, wants} for the node's own identity.
    wants = no lease at all, or a timely renewal is possible (FIDELITY_MIN_GAP_EPOCHS since the last recert — the
    same spacing the fidelity step rewards, so a tap is never wasted on a renewal that earns nothing)."""
    from ops.account_ops import get_account
    from ops import kv_ops
    try:
        acc = get_account(address, create_on_error=False) or {}
    except Exception:
        acc = {}
    try:
        last = int(kv_ops.recert_latest(address))
    except Exception:
        last = -1
    epoch = int(tip) // EPOCH_LENGTH
    registered = int(acc.get("registered", 0) or 0) == 1
    renewable = last >= 0 and epoch - last >= FIDELITY_MIN_GAP_EPOCHS
    return {"address": address, "registered": registered, "last_recert_epoch": last, "epoch": epoch,
            "fidelity": int(acc.get("fidelity", 0) or 0), "renewable": renewable,
            "wants": (not registered) or renewable, **bind_info(address, acc)}


def bind_info(address: str, acc: dict | None = None) -> dict:
    """{bind_mode, bind_cls, bind_live, bind_epoch} for an identity (doc/device-attestation.md §"Binding modes"):
    bind_mode "perm" when the account's `devkey` row still points back at it in permanent mode (it renews without a
    statement), "lease" otherwise. Read-only, never raises."""
    from ops import kv_ops
    out = {"bind_mode": "lease", "bind_cls": None, "bind_live": False, "bind_epoch": -1}
    try:
        if acc is None:
            from ops.account_ops import get_account
            acc = get_account(address, create_on_error=False) or {}
        dk = acc.get("devkey")
        if isinstance(dk, str) and dk:
            out["bind_cls"] = dk.split(":", 1)[0]
            row = kv_ops.devbind_get(dk)
            if row and row[0] == address and row[2] == "perm":
                out.update({"bind_mode": "perm", "bind_live": True, "bind_epoch": int(row[1])})
    except Exception:
        pass
    return out


def renew_without_statement(memserver, tip: int, logger=None) -> dict:
    """A node bound for life to a hardware wallet renews its presence lease with a register tx that carries NO
    statement (accepted by validation only while its devbind row points back at it). Same merge + gossip path as
    a dropped statement; the identity log records it as bind "renew"."""
    from ops.transaction_ops import construct_register_tx
    from protocol import DEVICE_BIND_PERMANENT_HEIGHT
    target = int(tip) + RENEW_TARGET_MARGIN
    if not DEVICE_BIND_PERMANENT_HEIGHT or target < DEVICE_BIND_PERMANENT_HEIGHT:
        return {"result": False, "message": "permanent bindings are not live yet"}
    tx = construct_register_tx(memserver.keydict, target)
    result = memserver.merge_transaction(tx, user_origin=True)
    ok = bool(isinstance(result, dict) and result.get("result"))
    try:
        from ops import identity_log
        identity_log.record("self", tx, ok, None if ok else (result.get("message") if isinstance(result, dict) else result))
    except Exception:
        pass
    if ok:
        try:
            memserver.enqueue_gossip(tx)
        except Exception:
            pass
    if logger:
        (logger.warning if ok else logger.error)(
            f"node attest: {'renewed' if ok else 'renewal REJECTED for'} own hardware-bound identity "
            f"{memserver.address[:12]}… without a statement (max_block {target})"
            + ("" if ok else f": {result.get('message') if isinstance(result, dict) else result}"))
    return result if isinstance(result, dict) else {"result": ok}


def _own_register_pending(memserver) -> bool:
    try:
        pool = memserver.transaction_pool
        txs = pool.values() if isinstance(pool, dict) else pool
        return any(isinstance(t, dict) and t.get("recipient") == "register" and t.get("sender") == memserver.address
                   for t in txs)
    except Exception:
        return False


def poll_peers(address: str, peers, port: int, timeout: float = 4.0, limit: int = 8, skip=None):
    """Ask up to `limit` peers for drops addressed to `address`; the first peer holding one the node has not already
    refused (`skip`: set of "max_block:sha256(att)") wins. Plain urllib — call it from a helper thread, never from
    the peer loop itself (a blocking probe there starved block sync on 2026-09-07)."""
    import hashlib
    import json
    import urllib.request as _rq
    from config import hostport
    skip = skip or set()
    for peer in list(peers)[:limit]:
        try:
            with _rq.urlopen(f"http://{hostport(peer, port)}/node_attest_pickup?sender={address}", timeout=timeout) as r:
                d = json.loads(r.read().decode())
            cands = d.get("drops") if isinstance(d, dict) and isinstance(d.get("drops"), list) else ([d.get("drop")] if isinstance(d, dict) else [])
            for b in reversed(cands):
                if not (isinstance(b, dict) and _valid_device(b.get("device")) and b.get("max_block")):
                    continue
                key = f"{int(b['max_block'])}:{hashlib.sha256(str(b['device']['att']).encode()).hexdigest()}"
                if key in skip:
                    continue
                return {"device": b["device"], "max_block": int(b["max_block"]), "from": peer, "key": key}
        except Exception:
            continue
    return None


def register_from_drop(memserver, blob: dict, logger=None) -> dict:
    """Build + sign the node's own register tx around the dropped attestation and merge it like a wallet submission
    (the merge runs the full consensus validation, kernel included). Gossips on accept; logs to the identity log."""
    from ops.transaction_ops import construct_register_tx
    tx = construct_register_tx(memserver.keydict, blob["max_block"], device=blob["device"])
    result = memserver.merge_transaction(tx, user_origin=True)
    ok = bool(isinstance(result, dict) and result.get("result"))
    try:
        from ops import identity_log
        identity_log.record("self", tx, ok)
    except Exception:
        pass
    if ok:
        try:
            memserver.enqueue_gossip(tx)
        except Exception:
            pass
    if logger:
        (logger.warning if ok else logger.error)(
            f"node attest: {'registered' if ok else 'REJECTED'} own open-lane identity {memserver.address[:12]}… "
            f"from a dropped attestation (max_block {blob['max_block']}, via {blob.get('from', 'local')})"
            + ("" if ok else f": {result.get('message') if isinstance(result, dict) else result}"))
    return result if isinstance(result, dict) else {"result": ok}


class NodeAttestPoller:
    """Peer-loop helper: when the node wants a lease, look for a drop (local store first, then peers) every
    POLL_EVERY s and register from it. Cheap when nothing is wanted (one account read per poll).

    NEVER BLOCK THE CALLER. The first version polled up to 8 peers with 4 s timeouts INLINE on the peer loop; an
    unregistered relay (this box, 2026-09-07 13:14) therefore spent 21-33 s per peer-loop pass on it, the pass that
    also syncs blocks, and fell 100 blocks behind the fleet while wallets hit a stale relay. The peer poll now runs
    on its own daemon thread (one in flight at a time, short timeouts, a few peers per round, round-robin), and tick()
    returns immediately."""

    def __init__(self, memserver, logger, port: int):
        self.memserver, self.logger, self.port = memserver, logger, port
        self._last = 0.0
        self._thread = None
        self._rr = 0
        self.last_state: dict = {}
        self.refused: dict = {}      # "max_block:sha256(att)" -> refused-at tip — never rebuild a statement the mempool refused

    def tick(self):
        now = time.time()
        if now - self._last < POLL_EVERY:
            return
        if self._thread is not None and self._thread.is_alive():
            return                                          # a poll is still running: never stack them
        self._last = now
        try:
            tip = int(self.memserver.latest_block["block_number"])
        except Exception:
            return
        try:
            st = lease_state(self.memserver.address, tip)
        except Exception:
            return
        self.last_state = st
        if not st["wants"] or _own_register_pending(self.memserver):
            return
        # BOUND FOR LIFE (doc/device-attestation.md §"Binding modes"): the operator attested this node once with a
        # hardware wallet; from then on the node renews its own lease with a statement-free register — no drop, no
        # operator. One attempt per poll; a refusal (e.g. the device was rebound elsewhere) falls through to the drop
        # path, which is how a fresh statement reaches it.
        if st.get("bind_mode") == "perm" and st.get("bind_live"):
            r = renew_without_statement(self.memserver, tip, self.logger)
            if r.get("result"):
                return
        # forget refusals whose statement can no longer land
        for k in [k for k in self.refused if int(k.split(":")[0]) <= tip]:
            self.refused.pop(k, None)
        import hashlib
        for blob in pickup_all(self.memserver.address, tip, consume=True):
            key = f"{blob['max_block']}:{hashlib.sha256(str(blob['device']['att']).encode()).hexdigest()}"
            if key in self.refused:
                continue
            r = register_from_drop(self.memserver, blob, self.logger)
            if r.get("result"):
                return
            self.refused[key] = tip
        peers = list(self.memserver.peers)
        if not peers:
            return
        # a slice of 3 peers per round, rotating, so a dead peer costs at most one short timeout per minute
        self._rr = (self._rr + 3) % max(1, len(peers))
        batch = (peers + peers)[self._rr:self._rr + 3]
        self._thread = threading.Thread(target=self._poll_bg, args=(batch,), daemon=True, name="node-attest-poll")
        self._thread.start()

    def _poll_bg(self, batch):
        try:
            blob = poll_peers(self.memserver.address, batch, self.port, timeout=1.5, limit=3, skip=set(self.refused))
            if blob is not None:
                r = register_from_drop(self.memserver, blob, self.logger)
                if not r.get("result"):
                    self.refused[blob["key"]] = int(self.memserver.latest_block["block_number"])
        except Exception as e:
            if self.logger:
                self.logger.debug(f"node attest poll: {e}")
