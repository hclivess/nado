#!/usr/bin/env python3
"""auth_cli — account authentication for a NODE identity (doc/key-rotation.md).

Talks HTTP to a node (default the local one) and reads/writes $HOME/nado/private/keys.dat. Every change is an
`auth` transaction signed by the keys you hold; nothing here touches the chain database.

  status                      show the account's auth config, pending change, freeze, and which key keys.dat holds
  protect  --recovery-out F   install the "protected" preset: spend with the current key, reconfigure only with
                              current + recovery. Generates the recovery key into F (0600). KEEP F OFFLINE.
  rotate   [--recovery F]     move the account to a FRESH hot key. With --recovery it lands immediately and
                              keys.dat is swapped at once; without it the change PENDS for AUTH_DELAY (~1 day):
                              the new keyfile is written next to keys.dat as keys.dat.next and `adopt` swaps it
                              once the chain shows it effective.
  adopt                       swap keys.dat.next into place once its key is effective on chain (restart the node after)
  cancel   --recovery F       cancel a pending change with the recovery key (freezes partial changes for AUTH_FREEZE)
  cancel                      cancel a pending change with the current key (no freeze)

Usage: HOME=/srv/nado-home python3 scripts/auth_cli.py <command> [--l1 http://127.0.0.1:9173] [--fee N]
After rotate/adopt, RESTART the node: it loads keys.dat once at startup.
"""
import argparse
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops.key_ops import load_keys, save_keys                      # noqa: E402
from ops.transaction_ops import construct_auth_tx, auth_pop       # noqa: E402
from ops import auth_ops as A                                     # noqa: E402
from signatures import generate_keydict                           # noqa: E402
from protocol import MIN_TX_FEE, AUTH_DELAY, TX_INCLUSION_DELAY   # noqa: E402
from ops.data_ops import get_home                                 # noqa: E402


def _get(l1, path):
    with urllib.request.urlopen(l1 + path, timeout=15) as r:
        return json.loads(r.read().decode())


def _post(l1, path, body):
    req = urllib.request.Request(l1 + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"result": False, "message": e.read().decode()[:300]}


def tip(l1):
    return int(_get(l1, "/get_latest_block")["block_number"])


def account(l1, address):
    return _get(l1, f"/get_account?address={address}") or {}


def keyfile():
    return f"{get_home()}/private/keys.dat"


def load_recovery(path):
    kd = json.load(open(path))
    assert kd.get("private_key") and kd.get("public_key"), "recovery keyfile needs private_key + public_key"
    return kd


def protected_cfg(v, hot_pub, rec_pub):
    return {"v": v, "keys": [hot_pub, rec_pub], "sign": ["ID", 0], "reconf": ["THRESHOLD", 2, [["ID", 0], ["ID", 1]]]}


def effective(l1, address):
    acc = account(l1, address)
    return A.effective_config(address, acc, tip(l1)), acc


def submit_and_wait(l1, tx, address, want, label, patience=600):
    """Submit an auth tx and wait until `want(account_doc)` holds (or the tx's max_block passes)."""
    r = _post(l1, "/submit_transaction", tx)
    if not r.get("result"):
        sys.exit(f"{label}: relay refused the transaction: {r.get('message')}")
    print(f"{label}: submitted {tx['txid'][:16]}… (max_block {tx['max_block']})", flush=True)
    deadline = time.time() + patience
    while time.time() < deadline:
        time.sleep(6)
        acc = account(l1, address)
        if want(acc):
            print(f"{label}: landed ✓", flush=True)
            return acc
        if tip(l1) > tx["max_block"]:
            sys.exit(f"{label}: the transaction expired without landing (max_block passed) — retry")
    sys.exit(f"{label}: gave up waiting")


def cmd_status(a):
    kd = load_keys()
    cfg, acc = effective(a.l1, kd["address"])
    print(f"account   {kd['address']}")
    print(f"keys.dat  key ...{kd['public_key'][-16:]}  authorizes: {A.key_authorized(kd['public_key'], kd['address'], height=tip(a.l1), acc=acc)}")
    if cfg.get("implicit"):
        print("config    none (legacy single key — run `protect` to add a recovery key)")
    else:
        print(f"config    v{cfg['v']}  keys={[k[-12:] for k in cfg['keys']]}  sign={cfg['sign']}  reconf={cfg['reconf']}")
    p = acc.get("auth_pending")
    if p:
        print(f"pending   v{p['cfg']['v']} keys={[k[-12:] for k in p['cfg']['keys']]} effective at block {p['eff']} (tip {tip(a.l1)})")
    if acc.get("auth_freeze"):
        print(f"freeze    partial changes refused until block {acc['auth_freeze']}")


def cmd_protect(a):
    kd = load_keys()
    cfg, acc = effective(a.l1, kd["address"])
    assert cfg.get("implicit"), "already configured — use rotate / cancel"
    if os.path.exists(a.recovery_out):
        sys.exit(f"{a.recovery_out} exists — refusing to overwrite a recovery key")
    rec = generate_keydict()
    fd = os.open(a.recovery_out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(rec, f)
    print(f"recovery key written to {a.recovery_out} — move it OFFLINE; it can never spend, only cancel/reconfigure", flush=True)
    new = protected_cfg(int(cfg.get("v", 0)) + 1, kd["public_key"], rec["public_key"])
    data = {"op": "set", "cfg": new, "pop": {rec["public_key"]: auth_pop(kd["address"], new, rec)}}
    t = tip(a.l1)
    tx = construct_auth_tx(kd["address"], [kd], data, a.fee, t + 30, min_block=t + TX_INCLUSION_DELAY)
    submit_and_wait(a.l1, tx, kd["address"], lambda d: (d.get("auth") or {}).get("v") == new["v"], "protect")
    cmd_status(a)


def cmd_rotate(a):
    kd = load_keys()
    cfg, acc = effective(a.l1, kd["address"])
    rec = load_recovery(a.recovery) if a.recovery else None
    new_kd = generate_keydict()
    if cfg.get("implicit") or len(cfg["keys"]) == 1:
        new = {"v": int(cfg.get("v", 0)) + 1, "keys": [new_kd["public_key"]], "sign": ["ID", 0], "reconf": ["ID", 0]}
    else:
        new = dict(cfg); new = {"v": cfg["v"] + 1, "keys": [new_kd["public_key"]] + list(cfg["keys"][1:]),
                                "sign": cfg["sign"], "reconf": cfg["reconf"]}
    signers = [kd] + ([rec] if rec else [])
    data = {"op": "set", "cfg": new, "pop": {new_kd["public_key"]: auth_pop(kd["address"], new, new_kd)}}
    t = tip(a.l1)
    tx = construct_auth_tx(kd["address"], signers, data, a.fee * len(signers), t + 30, min_block=t + TX_INCLUSION_DELAY)
    full = A.policy_satisfied(cfg["reconf"], A.signer_indices(tx, kd["address"], cfg))
    next_path = keyfile() + ".next"
    new_kd["account"] = kd["address"]
    save_keys(new_kd, next_path)
    if full:
        submit_and_wait(a.l1, tx, kd["address"], lambda d: (d.get("auth") or {}).get("v") == new["v"], "rotate")
        _swap(next_path)
    else:
        submit_and_wait(a.l1, tx, kd["address"], lambda d: (d.get("auth_pending") or {}).get("txid") == tx["txid"], "rotate (pending)")
        eff = account(a.l1, kd["address"])["auth_pending"]["eff"]
        print(f"the new key becomes effective at block {eff} (~{AUTH_DELAY} blocks). It is saved as {next_path}.\n"
              f"Run `adopt` after that height to swap it into keys.dat. Until then the current key keeps working.", flush=True)


def _swap(next_path):
    kf = keyfile()
    retired = f"{kf}.retired.{int(time.time())}"
    os.replace(kf, retired)
    os.replace(next_path, kf)
    os.chmod(kf, 0o600)
    print(f"keys.dat swapped (old key kept at {retired}). RESTART THE NODE to sign with the new key.", flush=True)


def cmd_adopt(a):
    next_path = keyfile() + ".next"
    if not os.path.exists(next_path):
        sys.exit("no keys.dat.next — nothing to adopt")
    nk = json.load(open(next_path))
    address = nk.get("account") or nk["address"]
    acc = account(a.l1, address)
    if not A.key_authorized(nk["public_key"], address, height=tip(a.l1), acc=acc):
        p = acc.get("auth_pending")
        sys.exit(f"the new key is not effective yet" + (f" (pending until block {p['eff']}, tip {tip(a.l1)})" if p else " — was it cancelled?"))
    _swap(next_path)


def cmd_cancel(a):
    kd = load_keys()
    cfg, acc = effective(a.l1, kd["address"])
    assert acc.get("auth_pending"), "nothing pending"
    signer = load_recovery(a.recovery) if a.recovery else kd
    t = tip(a.l1)
    tx = construct_auth_tx(kd["address"], [signer], {"op": "cancel"}, a.fee, t + 30, min_block=t + TX_INCLUSION_DELAY)
    submit_and_wait(a.l1, tx, kd["address"], lambda d: not d.get("auth_pending"), "cancel")
    if os.path.exists(keyfile() + ".next"):
        os.remove(keyfile() + ".next")
    cmd_status(a)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["status", "protect", "rotate", "adopt", "cancel"])
    ap.add_argument("--l1", default=os.environ.get("NADO_L1_URL", "http://127.0.0.1:9173").rstrip("/"))
    ap.add_argument("--fee", type=int, default=MIN_TX_FEE)
    ap.add_argument("--recovery", default=None, help="path to the recovery keyfile (rotate/cancel)")
    ap.add_argument("--recovery-out", default=None, help="where `protect` writes the new recovery keyfile")
    a = ap.parse_args()
    if a.command == "protect" and not a.recovery_out:
        sys.exit("protect needs --recovery-out FILE")
    {"status": cmd_status, "protect": cmd_protect, "rotate": cmd_rotate, "adopt": cmd_adopt, "cancel": cmd_cancel}[a.command](a)


if __name__ == "__main__":
    main()
