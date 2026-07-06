"""
Generate private/genesis_alloc.dat from the CURRENT chain's account state, so a relaunch (fresh genesis)
preserves every holder's balance + bonded stake. Run this ONCE against the live data dir BEFORE wiping the
chain. Output is a sorted, deterministic JSON list [{address, balance, bonded}, ...] — share it verbatim
with every node that will join the new chain, or their genesis state will fork.

Usage:  HOME=/root  python3 tools/relaunch_carry_forward.py
        (HOME must be the live node's home so get_home() -> /root/nado)
"""
import os, sys, json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import kv_ops
from ops.data_ops import get_home

def main():
    """Walk every account in the live LMDB state, keep those with any balance or bonded stake, and
    write the sorted allocation list to private/genesis_alloc.dat (printing totals for eyeballing).
    Read-only against the chain — safe to run on a live node."""
    kv_ops.init_env()
    alloc = []
    total_balance = total_bonded = 0
    for address, doc in kv_ops.iter_accounts():
        bal = int(doc.get("balance", 0) or 0)
        bonded = int(doc.get("bonded", 0) or 0)
        if bal <= 0 and bonded <= 0:
            continue                         # skip empty/dust-free accounts (registration re-establishes)
        alloc.append({"address": address, "balance": bal, "bonded": bonded})
        total_balance += bal
        total_bonded += bonded
    alloc.sort(key=lambda e: e["address"])   # deterministic == genesis seeding order

    out_path = f"{get_home()}/private/genesis_alloc.dat"
    tmp = out_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(alloc, f, indent=0, sort_keys=True)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, out_path)

    print(f"wrote {out_path}")
    print(f"  accounts carried : {len(alloc)}")
    print(f"  total balance     : {total_balance}")
    print(f"  total bonded      : {total_bonded}")
    # show the top few by balance for a human sanity check
    for e in sorted(alloc, key=lambda x: -x["balance"])[:8]:
        print(f"    {e['address']}  bal={e['balance']}  bonded={e['bonded']}")

if __name__ == "__main__":
    main()
