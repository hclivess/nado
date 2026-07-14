"""
alphanet-5 carry-forward builder (issue #85 cutover). Reads the LIVE L1 chain + exec_state.json and writes
private/genesis_alloc.dat so the reboot preserves everyone's coins under the owner's cutover rules:

  * L1 account balances + bonded stake carry forward verbatim (the base relaunch guarantee).
  * Exec-side USER bridge balances, uncollected DIVIDENDS, and already-collected-but-unclaimed dividend
    withdrawals are FOLDED into each holder's L1 balance.
  * Contract POTS are REFUNDED TO PLAYERS: the banked-game ledger conserves as
        pot == Σ tk[table] (banker bankroll)  +  Σ gs[g] over UNSETTLED games (bettor stake),
    so bankers get their bankroll back and open bettors get their stake back. Non-banked pots are
    refunded to their recorded staker(s). Every contract's attribution is checked to sum to its pot
    EXACTLY; a residual (rounding / unrecognised schema) refunds to the contract deployer.
  * To avoid inflating supply, the folded amounts are DEBITED from the L1 escrow reserved accounts
    (`bridge`, `dividend`) by the same totals. Undistributed remainder stays locked in those accounts.

READ-ONLY on the chain. Prints a full ledger + a hard total-supply conservation check, and only writes
genesis_alloc.dat when --write is passed AND conservation holds.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import kv_ops
from ops.data_ops import get_home

EXEC_STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "exec_state.json")


def _num(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def attribute_pot(cid, contract, pot):
    """Return {address: refund_raw} summing EXACTLY to `pot`, refunding each contract's escrow to its players.

    Banked games (roulette/dice/mines/slots): `tp[table]` is the authoritative OPEN-table pot (stale closed
    tables keep a `tk` entry but drop out of `tp`, so we iterate `tp` only). Per open table, open bettors
    (`ga`/`gs` on an UNSETTLED `gd` game for that table) get their stake back; the banker (`ta[table]`) gets
    the remaining bankroll — these sum to `tp[table]`.
    PvP games (farkle/reversi/coinflip): `pt[game]` is a funded game's pot; each seated player (`p1`/`p2`)
    gets their `st[game]` stake back, remainder to the first seat.
    Anything unreconciled (an operator-run staking pool with no clean per-player escrow ledger) refunds to
    the contract deployer — the operator of record — so Σ == pot exactly."""
    sto = contract.get("storage", {})
    refunds = {}

    def add(addr, amt):
        if addr and amt:
            refunds[addr] = refunds.get(addr, 0) + int(amt)

    tp, tk, ta = sto.get("tp", {}), sto.get("tk", {}), sto.get("ta", {})
    ga, gs, gd, gg = sto.get("ga", {}), sto.get("gs", {}), sto.get("gd", {}), sto.get("gg", {})
    if tp:                                              # banked game — tp = open-table pots
        for table, tpot in tp.items():
            tpot = _num(tpot); got = 0
            for g, addr in ga.items():                 # open (unsettled) bets on this table
                if str(gg.get(g)) == str(table) and not _num(gd.get(g, 0)):
                    amt = _num(gs.get(g, 0)); add(addr, amt); got += amt
            add(ta.get(table), tpot - got)             # banker keeps the bankroll remainder
    else:
        pt, st, p1, p2 = sto.get("pt", {}), sto.get("st", {}), sto.get("p1", {}), sto.get("p2", {})
        for g, gpot in pt.items():                      # PvP — split each funded game's pot to its stakers
            gpot = _num(gpot); got = 0; stake = _num(st.get(g, 0))
            for seat in (p1, p2):
                a = seat.get(g)
                if a and stake and got + stake <= gpot:
                    add(a, stake); got += stake
            if gpot - got:
                add(p1.get(g) or contract.get("deployer"), gpot - got)

    residual = pot - sum(refunds.values())
    if residual != 0:                                  # operator-run pool w/o a clean ledger -> deployer
        add(contract.get("deployer"), residual)
    assert sum(refunds.values()) == pot, f"{cid}: attribution {sum(refunds.values())} != pot {pot}"
    return refunds


def build():
    kv_ops.init_env()
    d = json.load(open(EXEC_STATE))
    contracts = d.get("contracts", {})
    bridge = d.get("bridge", {})
    dividend = d.get("dividend", {})
    dws = d.get("dividend_withdrawals", {})
    cids = set(contracts)

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
    # 3) refund POTS to players
    pot_refunds = {}
    for cid, pot in pot_bridge.items():
        for addr, amt in attribute_pot(cid, contracts[cid], pot).items():
            pot_refunds[addr] = pot_refunds.get(addr, 0) + amt
            credit(addr, amt)
    # 4) fold uncollected dividends + collected-but-unclaimed dividend withdrawals
    for a, v in dividend.items():
        credit(a, _num(v))
    for _n, w in dws.items():
        credit(w["addr"], _num(w["amount"]))

    # 5) debit the escrow reserved accounts by exactly what we folded (conserve supply)
    bridge_out = sum(user_bridge.values()) + sum(pot_bridge.values())
    dividend_out = sum(_num(v) for v in dividend.values()) + sum(_num(w["amount"]) for w in dws.values())
    debit_reserved("bridge", bridge_out)
    debit_reserved("dividend", dividend_out)

    # conservation: total carried supply must equal the L1 total (folds were internal transfers)
    carried = sum(e["balance"] + e["bonded"] for e in alloc.values())
    print("=== alphanet-5 carry-forward ===")
    print(f"L1 accounts total (balance+bonded):     {l1_total:>18} raw")
    print(f"  folded user bridge:                   {sum(user_bridge.values()):>18} raw -> users, -bridge escrow")
    print(f"  refunded contract pots:               {sum(pot_bridge.values()):>18} raw -> players, -bridge escrow")
    print(f"  folded dividends (uncollected):       {sum(_num(v) for v in dividend.values()):>18} raw -> users, -dividend pool")
    print(f"  folded dividend withdrawals (pending):{sum(_num(w['amount']) for w in dws.values()):>18} raw -> users, -dividend pool")
    print(f"carried total after folds:              {carried:>18} raw")
    print(f"CONSERVATION: {'OK' if carried == l1_total else 'FAIL'} (Δ={carried - l1_total})")
    print(f"accounts in alloc: {len(alloc)}  (pot refunds to {len(pot_refunds)} players)")
    if carried != l1_total:
        raise SystemExit("conservation failed — refusing to write")

    out = sorted(({"address": a, "balance": e["balance"], "bonded": e["bonded"]}
                  for a, e in alloc.items() if e["balance"] or e["bonded"]),
                 key=lambda e: e["address"])
    return out


def main():
    alloc = build()
    if "--write" in sys.argv:
        path = f"{get_home()}/private/genesis_alloc.dat"
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(alloc, f, indent=0, sort_keys=True)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
        # also update the git-tracked copy so joining peers build the identical genesis
        repo = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "genesis_data", "genesis_alloc.dat")
        with open(repo, "w") as f:
            json.dump(alloc, f, indent=0, sort_keys=True)
        print(f"\nWROTE {path} and genesis_data/genesis_alloc.dat  ({len(alloc)} accounts)")
    else:
        print("\n(dry run — pass --write to persist genesis_alloc.dat)")


if __name__ == "__main__":
    main()
