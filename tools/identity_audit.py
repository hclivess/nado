#!/usr/bin/env python3
"""identity_audit.py — are the registered identities really individual? Reads this node's identity log
(ops/identity_log: <home>/identity_log.jsonl, every register tx seen at /submit) and prints the groupings that
expose a non-individual identity: many senders behind one IP, one device certificate behind many senders, the
device-class and authenticator-model mix.

    python3 tools/identity_audit.py                 # last 36 h (one lease), accepted registrations only
    python3 tools/identity_audit.py --hours 168     # last week
    python3 tools/identity_audit.py --min 3         # only show groups of 3+ identities
    python3 tools/identity_audit.py --file /path/identity_log.jsonl

READ-ONLY. Nothing here touches the chain DB — it can run beside a live node. (Set HOME to the node's home if
the tool runs as another user; the log is <home>/identity_log.jsonl.)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hours", type=float, default=36.0, help="window in hours (default 36 = one lease)")
    ap.add_argument("--min", type=int, default=2, help="only print groups with at least this many identities")
    ap.add_argument("--file", default=None, help="log file (default: <home>/identity_log.jsonl)")
    a = ap.parse_args()
    from ops.identity_log import iter_records, audit, log_path
    path = a.file or log_path()
    recs = list(iter_records(path))
    if not recs:
        print(f"no records in {path}")
        return 0
    rep = audit(recs, window_s=a.hours * 3600.0)
    print(f"{path}: {len(recs)} lines, {rep['identities']} distinct accepted identities in the last {a.hours:g} h")
    print("\nby device class:")
    for fmt, n in rep["by_fmt"]:
        print(f"  {str(fmt):14s} {n}")
    print("\nby authenticator model (AAGUID):")
    for ag, n in rep["by_aaguid"][:20]:
        print(f"  {ag}  {n}")
    print(f"\nIPs with >= {a.min} identities (of {len(rep['by_ip'])} IPs):")
    shown = 0
    for ip, senders in rep["by_ip"]:
        if len(senders) < a.min:
            break
        shown += 1
        print(f"  {ip:42s} {len(senders):4d}  {', '.join(s[:10] + '…' for s in senders[:6])}{' …' if len(senders) > 6 else ''}")
    if not shown:
        print("  none")
    print(f"\ndevice certificates (fmt:leaf) with >= {a.min} identities — a TPM AIK leaf shared by senders IS one PC:")
    shown = 0
    for leaf, senders in rep["by_leaf"]:
        if len(senders) < a.min:
            break
        shown += 1
        print(f"  {leaf:34s} {len(senders):4d}  {', '.join(s[:10] + '…' for s in senders[:6])}{' …' if len(senders) > 6 else ''}")
    if not shown:
        print("  none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
