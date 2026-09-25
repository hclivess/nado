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
from execnode.games import otc as _otc


def pot_refunds_for(cid, contract, pot, zk_addrs):
    """Route a contract's pot to its refund attribution. The OTC order book (doc/dex-bridge.md §4.4) keeps an
    ENUMERABLE maker/taker escrow ledger precisely so a reroll refunds every live order to whoever funded it —
    detect it by its ABI and use the contract module's own attribution; anything unattributed (should be 0)
    falls to the deployer so Σ == pot stays exact. Every other contract goes through the legacy attribute_pot."""
    if {"post", "fill", "settle", "expire"} <= set(contract.get("abi") or {}):
        refunds = _otc.escrow_refunds(contract.get("storage") or {}, zk_addrs)
        residual = pot - sum(refunds.values())
        assert residual >= 0, f"{cid}: otc escrow ledger {sum(refunds.values())} exceeds pot {pot}"
        if residual:
            dep = contract.get("deployer")
            refunds[dep] = refunds.get(dep, 0) + residual
        assert sum(refunds.values()) == pot, f"{cid}: otc attribution != pot"
        return refunds
    return attribute_pot(cid, contract, pot)

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
    # THE EXEC STATE MUST BE AT THE L1 TIP. Deposits (bridge, faucet, shield) and dividend inflow in blocks the exec
    # node has not applied yet would otherwise stay stranded in keyless escrow. The runbook stops the services only
    # after the exec cursor has caught up with the L1 tip (see doc/reroll.md step 5); refuse otherwise.
    # The L1 tip comes from the operator (`--l1-tip N`, read from /status just before the services stop): the store
    # keeps no tip accessor, and guessing one would defeat the check.
    _tip = None
    for i, arg in enumerate(sys.argv):
        if arg == "--l1-tip" and i + 1 < len(sys.argv):
            _tip = int(sys.argv[i + 1])
    if "--allow-gap" not in sys.argv:
        if _tip is None:
            raise SystemExit("pass --l1-tip <height from /status> (or --allow-gap after reconciling the gap by hand)")
        if int(d.get("cursor", -1)) < _tip:
            raise SystemExit(f"exec cursor {d.get('cursor')} is behind the L1 tip {_tip}: let exec catch up first")

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
        for addr, amt in pot_refunds_for(cid, contracts[cid], pot, d.get("zk_addrs") or {}).items():
            pot_refunds[addr] = pot_refunds.get(addr, 0) + amt
            credit(addr, amt)
    # ALREADY-CLAIMED EXITS ARE NOT PAID AGAIN (review 2026-09-25, measured). The exec node applies only FINALIZED L1
    # blocks, so exec_state trails L1 by ~45 blocks: a withdrawal claimed on L1 in that gap is already in its owner's
    # L1 balance while its exec record still exists. Folding it again paid it twice — and Δ stayed 0, because the
    # debit lands on the reserved escrow account. Drop every record whose L1 nullifier is set.
    dws = {n: w for n, w in dws.items() if not kv_ops.dividend_nullifier_exists(w["addr"], str(n))}
    bws = {n: w for n, w in bws.items() if not kv_ops.bridge_nullifier_exists("default", w["addr"], str(n))}
    uws = {n: w for n, w in uws.items() if not kv_ops.shield_nullifier_exists(w["addr"], str(n))}
    # PRINT EVERY NON-FAUCET POT that fell to the deployer, with the owners its table slots name (field 1 = owner
    # digest, field 2 = amount; zk_addrs maps a digest to an address), so the operator can refund them by hand after
    # the reroll. Printing only — the fold above is unchanged, so conservation is unaffected.
    _z = d.get("zk_addrs") or {}
    for cid, pot in sorted(pot_bridge.items()):
        if cid == "faucet" or not pot:
            continue
        sl = {int(k): int(v) for k, v in ((contracts[cid].get("storage") or {}).get("slots") or {}).items()}
        ids = sorted({k & 0xffffffff for k in sl if k >> 32 in (1, 2)})
        owners = [(_z.get(str(sl.get((1 << 32) + i))) or "?", sl.get((2 << 32) + i, 0)) for i in ids]
        print(f"  MANUAL REFUND? {cid[:16]} pot {pot} raw -> deployer; table owners/amounts: {owners[:8]}")
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

    # IDENTITY CARRY (gen 25 -> 26, operator decision 2026-09-25: "carry them"). Per account: the recorded public key
    # (keeps ADDRESS_KEY_BIND effective from block 1 — without it every account would be "never sent" again), the
    # messaging key, registration + fidelity, the device key/credential and any account-authentication config. Only
    # fields present on the old chain are written, so an entry without them is byte-identical to the old format.
    ids = {}
    for address, doc in kv_ops.iter_accounts():
        x = {}
        for f in CARRY_FIELDS:
            v = doc.get(f)
            if v not in (None, "", 0, "0"):
                x[f] = v
        if x:
            ids[address] = x
    out = []
    for a in sorted(set(alloc) | set(ids)):
        e = alloc.get(a, {"balance": 0, "bonded": 0})
        if not (e["balance"] or e["bonded"] or a in ids):
            continue
        row = {"address": a, "balance": e["balance"], "bonded": e["bonded"]}
        row.update(ids.get(a, {}))
        out.append(row)
    print(f"identity fields carried for {len(ids)} accounts")
    return out


# The account fields that carry across a reroll besides balance/bonded (genesis.CARRY_FIELDS must match).
CARRY_FIELDS = ("public_key", "kem_pub", "registered", "fidelity", "devkey", "devcred", "auth")


def build_extra():
    """State outside account records that carries too: device bindings (re-stamped at epoch 0, mode kept) and aliases.
    Written to genesis_data/genesis_carry.dat; genesis seeds it when present."""
    kv_ops.init_env()
    devbind = sorted([k, a, m] for (k, a, _e, m) in kv_ops.devbind_rows())
    aliases = sorted([n.decode() if isinstance(n, bytes) else n, o.decode() if isinstance(o, bytes) else o]
                     for n, o in kv_ops.iter_db_pairs("aliases"))
    hist = []
    for address, doc in kv_ops.iter_accounts():
        if doc.get("auth"):
            rows = kv_ops.auth_history(address)
            if rows:
                _h, ver, keys = rows[-1]                         # the CURRENT config, effective from block 0
                hist.append([address, int(ver), list(keys)])
    # PRESENT = the identities holding a live lease at the tip. Only these get a lease at the new genesis: seeding one for
    # every registered identity revived 33 lapsed ones on betanet-8 (79 collectors against 46 live), and a lapsed
    # identity drawn for an open-lane slot produces nothing for its whole lease (36 h to 7 days). The rest keep their
    # registration and devices and rejoin with their next renewal.
    from ops.account_ops import get_open_registry
    from protocol import EPOCH_LENGTH as _EL
    _tip = next(int(sys.argv[i + 1]) for i, a in enumerate(sys.argv) if a == "--l1-tip")
    present = sorted(get_open_registry(_tip // _EL))
    print(f"carried: {len(devbind)} device bindings, {len(aliases)} aliases, {len(hist)} auth histories, "
          f"{len(present)} present identities")
    from protocol import CHAIN_GENERATION as _G
    # "generation" = the chain this carry SEEDS (the next one); genesis refuses a file naming any other generation.
    return {"generation": int(_G) + 1, "devbind": devbind, "aliases": aliases, "auth_history": sorted(hist), "present": present}


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
        extra = build_extra()
        xpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "genesis_data", "genesis_carry.dat")
        with open(xpath, "w") as f:
            json.dump(extra, f, indent=0, sort_keys=True)
        print(f"WROTE genesis_data/genesis_carry.dat")
    else:
        print("\n(dry run — pass --write to persist genesis_alloc.dat)")


if __name__ == "__main__":
    main()
