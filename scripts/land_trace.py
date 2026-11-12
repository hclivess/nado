#!/usr/bin/env python3
"""scripts/land_trace.py <address> [--data DIR] [-n N] — the last N events a player's page traced (#194: boarding and
leaving a craft with both poses, every move of the body the player did not make, hurt, death, page errors), oldest
first, from <data>/trace/<address>.jsonl as scripts/land_server.py keeps it. Read-only."""
import argparse, json, os, sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("address")
    ap.add_argument("--data", default="/srv/nado-home/land/planet0")
    ap.add_argument("-n", type=int, default=40)
    a = ap.parse_args()
    path = os.path.join(a.data, "trace", a.address + ".jsonl")
    if not os.path.exists(path):
        print("no trace for", a.address, "at", path); return 1
    with open(path) as f:
        lines = f.readlines()[-a.n:]
    for ln in lines:
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        t = e.pop("t", 0); k = e.pop("k", "?"); e.pop("srv", None)
        print(f"{t / 1000:.3f} {k:14s} {json.dumps(e, separators=(',', ':'))[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
