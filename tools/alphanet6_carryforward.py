"""
alphanet-6 carry-forward builder (the FROZEN-sparse-root reroll). Reads the LIVE L1 chain + exec_state.json and
writes genesis_alloc.dat so the reboot preserves everyone's coins under the same cutover rules as alphanet-5
(tools/alphanet5_carryforward.py), plus the pending-exit folds the new reroll needs:

  * L1 account balances + bonded stake carry forward verbatim.
  * Exec-side USER bridge balances, uncollected DIVIDENDS and pending DIVIDEND withdrawals fold into L1 balances.
  * Contract POTS refund to players where the ledger identifies them; the zkVM digest-slot games carry no named
    escrow maps, so their (small) pots refund to the deployer/operator of record.
  * PENDING BRIDGE + UNSHIELD withdrawals fold into their owners' L1 balances — their exit proofs are against the
    OLD root scheme and would be unverifiable after the reroll, so they are paid out at genesis instead.
  * Every fold is DEBITED from the matching L1 escrow reserved account (bridge / dividend / shield): supply is
    conserved EXACTLY (Δ must be 0 or the tool refuses to write). Shield-escrow residual with an EMPTY pool
    stays locked in the reserved account.

READ-ONLY on the chain; --write persists private/genesis_alloc.dat + genesis_data/genesis_alloc.dat.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import kv_ops
from ops.data_ops import get_home
from tools.alphanet5_carryforward import attribute_pot, _num

EXEC_STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "exec_state.json")


def build():
    kv_ops.init_env()
    d = json.load(open(EXEC_STATE))
    contracts = d.get("contracts", {})
    bridge = d.get("bridge", {})
    dividend = d.get("dividend", {})
    dws = d.get("dividend_withdrawals", {})
    bws = d.get("withdrawals", {})                   # pending bridge exits (old-root proofs die at reroll)
    uws = d.get("unshield_withdrawals", {})          # pending unshield exits (ditto)
    shielded = d.get("shielded", {})
    cids = set(contracts)

    assert not shielded.get("commitments"), \
        "shielded pool is NOT empty — holders would lose notes; have them unshield before the reroll"

    # 1) base: every L1 account's balance + bonded
    alloc = {}
    l1_total = 0
    for address, doc in kv_ops.iter_accounts():
        bal, bonded = _num(doc.get("balance")), _num(doc.get("bonded"))
        if bal or bonded:
            alloc[address] = {"balance": bal, "bonded": bonded}
            l1_total += bal + bonded

    def credit(addr, amt):
        e = alloc.setdefault(addr, {"balance": 0, "bonded": 0})
        e["balance"] += int(amt)

    def debit_reserved(addr, amt):
        e = alloc.get(addr)
        if not e or e["balance"] < amt:
            raise SystemExit(f"escrow {addr} balance {e['balance'] if e else 0} < obligation {amt}")
        e["balance"] -= int(amt)

    # 2) fold exec-side USER bridge balances (skip contract pots — handled below)
    user_bridge = {a: _num(v) for a, v in bridge.items() if a not in cids}
    pot_bridge = {a: _num(v) for a, v in bridge.items() if a in cids}
    for a, v in user_bridge.items():
        credit(a, v)
    # 3) refund POTS to players (digest-slot games: residual -> deployer/operator of record)
    pot_refunds = {}
    for cid, pot in pot_bridge.items():
        for addr, amt in attribute_pot(cid, contracts[cid], pot).items():
            pot_refunds[addr] = pot_refunds.get(addr, 0) + amt
            credit(addr, amt)
    # 4) fold uncollected dividends + pending dividend withdrawals
    for a, v in dividend.items():
        credit(a, _num(v))
    for _n, w in dws.items():
        credit(w["addr"], _num(w["amount"]))
    # 5) fold PENDING bridge + unshield withdrawals (their proofs are old-scheme — pay them at genesis)
    for _n, w in bws.items():
        credit(w["addr"], _num(w["amount"]))
    for _n, w in uws.items():
        credit(w["addr"], _num(w["amount"]))

    # 6) debit the escrow reserved accounts by exactly what was folded (conserve supply)
    bridge_out = sum(user_bridge.values()) + sum(pot_bridge.values()) + sum(_num(w["amount"]) for w in bws.values())
    dividend_out = sum(_num(v) for v in dividend.values()) + sum(_num(w["amount"]) for w in dws.values())
    shield_out = sum(_num(w["amount"]) for w in uws.values())
    debit_reserved("bridge", bridge_out)
    debit_reserved("dividend", dividend_out)
    if shield_out:
        debit_reserved("shield", shield_out)

    carried = sum(e["balance"] + e["bonded"] for e in alloc.values())
    print("=== alphanet-6 carry-forward ===")
    print(f"L1 accounts total (balance+bonded):     {l1_total:>18} raw")
    print(f"  folded user bridge:                   {sum(user_bridge.values()):>18} raw -> users, -bridge escrow")
    print(f"  refunded contract pots:               {sum(pot_bridge.values()):>18} raw -> players/operator, -bridge escrow")
    print(f"  folded dividends (uncollected):       {sum(_num(v) for v in dividend.values()):>18} raw -> users, -dividend pool")
    print(f"  folded dividend withdrawals (pending):{sum(_num(w['amount']) for w in dws.values()):>18} raw -> users, -dividend pool")
    print(f"  folded bridge withdrawals (pending):  {sum(_num(w['amount']) for w in bws.values()):>18} raw -> users, -bridge escrow")
    print(f"  folded unshield withdrawals (pending):{shield_out:>18} raw -> users, -shield escrow")
    print(f"carried total after folds:              {carried:>18} raw")
    print(f"CONSERVATION: {'OK' if carried == l1_total else 'FAIL'} (Δ={carried - l1_total})")
    print(f"accounts in alloc: {len(alloc)}  (pot refunds to {len(pot_refunds)} recipients)")
    if carried != l1_total:
        raise SystemExit("conservation failed — refusing to write")

    return sorted(({"address": a, "balance": e["balance"], "bonded": e["bonded"]}
                   for a, e in alloc.items() if e["balance"] or e["bonded"]),
                  key=lambda e: e["address"])


def main():
    alloc = build()
    if "--write" in sys.argv:
        path = f"{get_home()}/private/genesis_alloc.dat"
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(alloc, f, indent=0, sort_keys=True)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
        repo = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "genesis_data", "genesis_alloc.dat")
        with open(repo, "w") as f:
            json.dump(alloc, f, indent=0, sort_keys=True)
        print(f"\nWROTE {path} and genesis_data/genesis_alloc.dat  ({len(alloc)} accounts)")
    else:
        print("\n(dry run — pass --write to persist genesis_alloc.dat)")


if __name__ == "__main__":
    main()
