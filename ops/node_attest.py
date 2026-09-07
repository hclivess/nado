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
POLL_EVERY = 20.0                # s between a wanting node's peer polls
_MAX_ATT, _MAX_CDJ, _MAX_RP = 200_000, 8_000, 253

_lock = threading.Lock()
_drops: dict = {}                # sender -> {"device": {att,cdj,rp}, "max_block": int, "at": float}


def _valid_device(device) -> bool:
    return (isinstance(device, dict)
            and isinstance(device.get("att"), str) and 0 < len(device["att"]) <= _MAX_ATT
            and isinstance(device.get("cdj"), str) and 0 < len(device["cdj"]) <= _MAX_CDJ
            and isinstance(device.get("rp"), str) and 0 < len(device["rp"]) <= _MAX_RP)


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
    with _lock:
        _prune(int(tip))
        if sender not in _drops and len(_drops) >= MAX_DROPS:
            return {"ok": False, "reason": "drop store full"}
        _drops[sender] = {"device": {"att": device["att"], "cdj": device["cdj"], "rp": device["rp"]},
                          "max_block": mb, "at": time.time()}
    return {"ok": True}


def _prune(tip: int):
    dead = [s for s, b in _drops.items() if b["max_block"] <= tip]
    for s in dead:
        _drops.pop(s, None)


def pickup(sender: str, tip: int, consume: bool = False):
    """The drop for `sender`, or None. `consume` removes it (the node that owns the key takes it once)."""
    with _lock:
        _prune(int(tip))
        b = _drops.get(sender)
        if b and consume:
            _drops.pop(sender, None)
        return dict(b) if b else None


def count() -> int:
    with _lock:
        return len(_drops)


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
            "wants": (not registered) or renewable}


def _own_register_pending(memserver) -> bool:
    try:
        pool = memserver.transaction_pool
        txs = pool.values() if isinstance(pool, dict) else pool
        return any(isinstance(t, dict) and t.get("recipient") == "register" and t.get("sender") == memserver.address
                   for t in txs)
    except Exception:
        return False


def poll_peers(address: str, peers, port: int, timeout: float = 4.0, limit: int = 8):
    """Ask up to `limit` peers for a drop addressed to `address`; first hit wins. Plain urllib on the peer-loop
    thread (never the core loop — a blocking probe there stalls block application)."""
    import json
    import urllib.request as _rq
    from config import hostport
    for peer in list(peers)[:limit]:
        try:
            with _rq.urlopen(f"http://{hostport(peer, port)}/node_attest_pickup?sender={address}", timeout=timeout) as r:
                d = json.loads(r.read().decode())
            b = d.get("drop") if isinstance(d, dict) else None
            if b and _valid_device(b.get("device")) and b.get("max_block"):
                return {"device": b["device"], "max_block": int(b["max_block"]), "from": peer}
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
    POLL_EVERY s and register from it. Cheap when nothing is wanted (one account read per poll)."""

    def __init__(self, memserver, logger, port: int):
        self.memserver, self.logger, self.port = memserver, logger, port
        self._last = 0.0
        self.last_state: dict = {}

    def tick(self):
        now = time.time()
        if now - self._last < POLL_EVERY:
            return
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
        blob = pickup(self.memserver.address, tip, consume=True)
        if blob is None:
            blob = poll_peers(self.memserver.address, self.memserver.peers, self.port)
        if blob is None:
            return
        register_from_drop(self.memserver, blob, self.logger)
