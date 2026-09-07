"""identity_log.py — every registration this node receives, one JSON line, so "are these identities really
individual?" can be ANSWERED from data instead of assumed.

Operator decision (2026-09-07, the real-device reroll): the per-IP budgets and identity cap were retired because an
identity now costs an attested device and a human tap — but the OBSERVATION stays. A farm that somehow attests
(a compromised model key, a leaked vendor intermediate, a device class we mis-pinned) would show up here first: many
senders behind one IP, one AIK certificate across many identities, one AAGUID dominating a subnet. The log is the
evidence; tools/identity_audit.py is the reading glass.

What is written (node-local, NEVER consensus, NEVER served): an append-only JSONL file at <home>/identity_log.jsonl —
OUTSIDE <home>/index so a generation purge (ops/data_ops.purge_chain_data) does not erase the history that makes a
reroll's first day comparable with the last one. One line per register tx seen at the /submit ingress:

    ts, ip (Cloudflare-resolved client IP), sender, kind (entry|renewal), max_block, accepted (mempool verdict),
    device: fmt, aaguid, cred_id_sha256, leaf_sha256, root_sha256, origin, x5c_count

leaf_sha256 is the strongest linkage signal per class: for `tpm` the leaf is the AIK certificate, issued once per
Windows account on one physical TPM — the same leaf across several senders IS one PC; for `apple` / `android-key` the
leaf is minted per credential (no linkage, by vendor design); for `packed` the leaf is a batch certificate shared by
~100k units of one model (linkage says "same model", not "same key"). cred_id is per credential, always unique.

Nothing here is a verdict and nothing here rejects: it is the dataset behind the next decision, taken WITH the user.
Cheap by construction: a dependency-free CBOR/base64 parse (ops/device_attest), no kernel call, no DB read beyond the
sender's own recert history (is_entry_registration — the same derivation the old per-IP budget used).
"""
import hashlib
import json
import os
import threading
import time

_LOCK = threading.Lock()
_FILE = "identity_log.jsonl"


def log_path() -> str:
    from ops.data_ops import get_home
    return os.path.join(get_home(), _FILE)


def _device_summary(device) -> dict:
    """The linkage-relevant fields of a `device` attestation, or {} when absent/unparseable. Pure parsing."""
    if not isinstance(device, dict):
        return {}
    try:
        from ops.device_attest import parse_attestation
        s = parse_attestation(str(device.get("att", "")), str(device.get("cdj", "")))
    except Exception as e:                        # a malformed statement is itself worth a line (the kernel will reject it)
        return {"fmt": None, "parse_error": str(e)[:80]}
    ad = s.get("auth_data") or {}
    cred = ad.get("cred_id") or ad.get("credential_id") or ""
    return {
        "fmt": s.get("fmt"),
        "aaguid": ad.get("aaguid"),
        "cred_id_sha256": hashlib.sha256(cred.encode() if isinstance(cred, str) else bytes(cred)).hexdigest()[:16] if cred else None,
        "leaf_sha256": (s.get("leaf_sha256") or "")[:16] or None,
        "root_sha256": (s.get("root_sha256") or "")[:16] or None,
        "origin": (s.get("client_data") or {}).get("origin"),
        "x5c_count": s.get("x5c_count"),
        "rp": device.get("rp"),
    }


def registration_kind(sender: str, max_block) -> str:
    """entry (no valid lease at the tx's anchor epoch) or renewal — the consensus entry derivation, read-only."""
    try:
        from ops.reg_difficulty import is_entry_registration
        from ops.mining_ops import epoch_of
        from protocol import POSW_ANCHOR_OFFSET
        anchor = epoch_of(max(0, int(max_block or 0) - POSW_ANCHOR_OFFSET))
        return "entry" if is_entry_registration(str(sender), anchor) else "renewal"
    except Exception:
        return "unknown"


def record(ip: str, transaction: dict, accepted, message=None) -> dict | None:
    """Append one line for a register tx. Returns the record (for tests/logging) or None for non-register txs.
    `message` is the mempool's verdict text (why a rejected tx was rejected) — without it the log could say
    "accepted False" but not why, which is exactly what an operator needs when a device class fails en masse.
    Never raises: a logging failure must never turn into a 403 for the wallet."""
    try:
        # a register tx is identified by its RECIPIENT ("register"), like every identity tx (msgkey, ...) — there is
        # no `type` field; tests/test_node_attest.py caught the first version checking one and logging nothing.
        if not isinstance(transaction, dict) or transaction.get("recipient") != "register":
            return None
        sender = str(transaction.get("sender", ""))
        rec = {
            "ts": round(time.time(), 3),
            "ip": ip,
            "sender": sender,
            "kind": registration_kind(sender, transaction.get("max_block")),
            "max_block": transaction.get("max_block"),
            "accepted": bool(accepted),
            "message": (str(message)[:200] if message and not accepted else None),
            "device": _device_summary(transaction.get("device")),
        }
        line = json.dumps(rec, separators=(",", ":"), sort_keys=True) + "\n"
        with _LOCK:
            with open(log_path(), "a") as f:
                f.write(line)
        return rec
    except Exception:
        return None


def iter_records(path: str | None = None):
    """Yield the log's records oldest-first, skipping torn/corrupt lines (a crash mid-write must not hide the rest)."""
    p = path or log_path()
    if not os.path.exists(p):
        return
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def audit(records, window_s: float = 36 * 3600.0, now: float | None = None) -> dict:
    """Group the last `window_s` of ACCEPTED registrations into the views that expose a non-individual identity:
       by_ip:   {ip: sorted distinct senders}          — many senders behind one address
       by_leaf: {leaf_sha256: sorted distinct senders} — one device certificate (TPM AIK) behind many senders
       by_fmt:  {fmt: distinct senders count}          — which device classes the population is made of
       by_aaguid: {aaguid: distinct senders count}     — which authenticator models
    Returned sorted so the largest groups come first; a group of size 1 is the normal case and is kept (the
    denominator matters as much as the outliers)."""
    now = time.time() if now is None else now
    by_ip, by_leaf, by_fmt, by_aaguid, senders = {}, {}, {}, {}, set()
    for r in records:
        if not r.get("accepted") or (now - float(r.get("ts", 0))) > window_s:
            continue
        s, d = r.get("sender"), r.get("device") or {}
        senders.add(s)
        by_ip.setdefault(r.get("ip"), set()).add(s)
        if d.get("leaf_sha256"):
            by_leaf.setdefault((d.get("fmt"), d["leaf_sha256"]), set()).add(s)
        by_fmt.setdefault(d.get("fmt"), set()).add(s)
        if d.get("aaguid"):
            by_aaguid.setdefault(d["aaguid"], set()).add(s)

    def _top(groups):
        return sorted(((k, sorted(v)) for k, v in groups.items()), key=lambda kv: (-len(kv[1]), str(kv[0])))
    return {
        "window_s": window_s,
        "identities": len(senders),
        "by_ip": _top(by_ip),
        "by_leaf": [(f"{k[0]}:{k[1]}", v) for k, v in _top(by_leaf)],
        "by_fmt": sorted(((k, len(v)) for k, v in by_fmt.items()), key=lambda kv: -kv[1]),
        "by_aaguid": sorted(((k, len(v)) for k, v in by_aaguid.items()), key=lambda kv: -kv[1]),
    }
