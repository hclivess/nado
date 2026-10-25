"""
alphanet-6 carry-forward builder (the FROZEN-sparse-root reroll). Reads the LIVE L1 chain + exec_state.json and
writes genesis_alloc.dat so the reboot preserves everyone's coins under the same cutover rules as alphanet-5
(tools/alphanet5_carryforward.py), plus the pending-exit folds the new reroll needs:

  * L1 account balances + bonded stake carry forward verbatim.
  * Exec-side USER bridge balances, uncollected DIVIDENDS and pending DIVIDEND withdrawals fold into L1 balances.
  * EVERY CONTRACT carries with all of its storage and its pot (tools/carry.py; operator rule 2026-10-20: no reset, no
    refund in place of a carry). A contract that cannot carry losslessly — something in flight, or a slot the carry
    cannot re-encode — REFUSES the whole carry, naming why; it is settled on the old chain and the carry runs again.
  * PENDING BRIDGE + UNSHIELD withdrawals fold into their owners' L1 balances — their exit proofs are against the
    OLD root scheme and would be unverifiable after the reroll, so they are paid out at genesis instead.
  * Every fold is DEBITED from the matching L1 escrow reserved account (bridge / dividend / shield): supply is
    conserved EXACTLY (Δ must be 0 or the tool refuses to write).
  * The STWO SHIELDED POOL carries (exec_shield_doc): its notes stay private, SHIELD_ESCROW keeps backing them, and
    whatever else the escrow holds (fees burned in-pool, stranded deposits) is carried as the new layer's pool_fees,
    so escrow == stwo_value + pool_fees exactly on the new chain. A deficit refuses.

READ-ONLY on the chain; --write persists private/genesis_alloc.dat + genesis_data/genesis_alloc.dat.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import kv_ops
from ops.data_ops import get_home
from tools.alphanet5_carryforward import _num
from tools import carry as _carry


EXEC_STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "exec_state.json")


def open_escrow_refunds(invites: dict, htlcs: dict):
    """({funder: raw}, {escrow account: raw}) for every OPEN invite (kv_ops.invite_all rows [sender, amount, expiry,
    status, claimant]) and OPEN HTLC lock (kv_ops.htlc_all docs): each goes back to whoever funded it, debited from its
    escrow. The records themselves do not survive a reroll, so without this the coins would carry as the escrow
    account's balance with nothing left that could ever release them."""
    refunds, out = {}, {"invite": 0, "htlc": 0}
    for _iid, rec in sorted(invites.items()):
        if rec[3] == "open" and _num(rec[1]) > 0:
            refunds[rec[0]] = refunds.get(rec[0], 0) + _num(rec[1])
            out["invite"] += _num(rec[1])
    for _hid, doc in sorted(htlcs.items()):
        if doc.get("status") == "open" and _num(doc.get("amount")) > 0:
            refunds[doc["sender"]] = refunds.get(doc["sender"], 0) + _num(doc["amount"])
            out["htlc"] += _num(doc["amount"])
    return refunds, out


CARRY_BLOCKERS = {}       # cid -> [reasons] for contracts that would carry but hold something in flight (printed)


def game_module_of(contract: dict):
    """The execnode.games module whose build() is exactly this contract's code, or None. Matching by code, not by a
    table of ids, so a contract whose code changed without its module being reviewed is never carried by accident."""
    import importlib, pkgutil
    import execnode.games as _g
    code = contract.get("code")
    for m in pkgutil.iter_modules(_g.__path__):
        if m.name.startswith("_") or m.name in ("deploy", "redeploy"):
            continue
        mod = importlib.import_module(f"execnode.games.{m.name}")
        if not hasattr(mod, "build") or not (getattr(mod, "CARRY_STORAGE", False) or hasattr(mod, "carry_in_flight")
                                             or hasattr(mod, "carry_rebase")):
            continue
        try:
            if json.loads(json.dumps(mod.build())) == code:
                return mod
        except Exception:
            continue
    return None


def _in_flight(mod, storage, tip):
    """mod.carry_in_flight, given the old tip when the hook takes one (pets judges whether a pinned roll's outcome is
    already visible at the tip; a banked game's open bet needs no tip)."""
    import inspect
    if tip is not None and "tip" in inspect.signature(mod.carry_in_flight).parameters:
        return mod.carry_in_flight(storage, tip=int(tip))
    return mod.carry_in_flight(storage)


def carry_policy(cid: str, contract: dict, tip=None) -> str:
    """What the module's own hooks say about carrying this contract NOW: "keep" when it runs exactly its game module's
    code AND that module says its storage is at rest — CARRY_STORAGE = True (nothing stored names the old chain), or
    carry_in_flight(storage[, tip]) == [] (nothing in flight: no open bet, no pets roll already visible at `tip`);
    otherwise "blocked", with the in-flight reasons in CARRY_BLOCKERS. A blocked contract no longer falls back to a
    reset: the carry (exec_genesis -> tools/carry.carry_contracts) REFUSES, and the operator settles it on the old
    chain and runs the carry again. Kept for inspection; the carry decides through tools/carry.py itself."""
    mod = game_module_of(contract)
    if mod is None:
        return "blocked"
    if getattr(mod, "CARRY_STORAGE", False) or (hasattr(mod, "carry_rebase") and not hasattr(mod, "carry_in_flight")):
        return "keep"
    why = _in_flight(mod, contract.get("storage") or {}, tip)
    if why:
        CARRY_BLOCKERS[cid] = list(why)
        return "blocked"
    return "keep"


def exec_genesis(contracts: dict, pots: dict, zk_addrs=None, tip: int = 0, dst=None, amap=None) -> tuple:
    """(genesis records for execnode/exec_genesis.py, {cid: pot} kept in escrow, the re-keyed zk_addrs registry). `tip`
    is the old chain's height the new chain's block 0 replaces (the drained exec cursor); a module's carry_rebase moves
    stored heights by it. EVERY contract carries under its id with ALL of its storage, re-encoded from the running
    generation's ISA to `dst` (None = the same ISA: nothing re-encoded), and EVERY pot stays in escrow with it — or
    tools/carry.Refused names every contract that cannot (operator rule 2026-10-20; the reset-and-refund path that stood
    here is gone)."""
    from execnode import zkvmasm
    src = zkvmasm.default_isa()
    out, reg, _counts = _carry.carry_contracts(contracts, zk_addrs or {}, int(tip), src=src, dst=dst or src, amap=amap)
    stray = sorted(c for c, p in pots.items() if p and c not in out)
    if stray:
        raise _carry.Refused(f"pots of contracts the state does not hold: {stray}")
    for cid in out:
        out[cid]["storage"] = int_slots(out[cid]["storage"])
    return out, {c: int(p) for c, p in sorted(pots.items()) if p}, reg


def exec_genesis_doc(contracts: dict, pots: dict, tip: int = 0, zk_addrs=None, dst=None) -> tuple:
    """exec_genesis without the registry: (records, kept pots)."""
    out, kept, _reg = exec_genesis(contracts, pots, zk_addrs, tip, dst)
    return out, kept


def int_slots(storage: dict) -> dict:
    """`storage` with every "slots" value an int. INVARIANT (review 2026-10-11): a carried slot is an INT, because
    exec_root.kv_projection commits only int-valued slots at their slot positions (anything else becomes a KVX record)
    while the settle proof's settlement_sparse.sparse_projection int()s every slot — a rebase hook that wrote strings
    gave a genesis root no settle proof could extend. The hooks write ints; this is the backstop for every contract. A
    value that is not an integer RAISES: the carry never guesses."""
    out = dict(storage or {})
    if "slots" in out:
        out["slots"] = {str(k): int(v) for k, v in (out["slots"] or {}).items()}
    return out


def exec_assets_doc(d: dict, amap=None) -> dict:
    """The exec ASSETS of a snapshot as the exec genesis carries them (execnode/exec_genesis.apply): asset records,
    holdings and allowances — an asset record holds no height — with zero holdings dropped and amounts as decimal
    strings (never floats). An asset's id derives from (issuer, seed) through the VM hash, so a carry that changes the
    hash re-keys all three by `amap` (tools/carry.asset_map); None keeps the ids."""
    assets, abal, allow = d.get("assets") or {}, d.get("abal") or {}, d.get("allow") or {}
    if amap is not None:
        assets, abal, allow = _carry.carry_assets(assets, abal, allow, amap)
    return {"assets": json.loads(json.dumps(assets)),
            "abal": {a: {h: str(_num(n)) for h, n in sorted(hs.items()) if _num(n)} for a, hs in sorted(abal.items())},
            "allow": json.loads(json.dumps(allow))}


_EXEC_GENESIS = [None]


SHIELDED_POOLS = ("shielded", "field_pool", "wide_pool", "stwo_pool", "app_state")   # every ExecState note pool
CARRIED_POOLS = ("stwo_pool",)        # carried into the exec genesis (exec_shield_doc); every other pool must be empty


def stwo_deposit_records(txs, prev, commitments) -> list:
    """The PUBLIC records of carried deposit notes (execnode/exec_genesis.py "CARRIED DEPOSITS STAY RESTORABLE"):
    {addr, amount, owner, rho} for every carried commitment that came from a Stwo deposit. `txs` are the old chain's L1
    shield transactions (recipient "shield", data.pool "stwo"); `prev` the records the old chain's own exec genesis
    carried (a note carried twice keeps its record — its transaction is two chains back). A wallet restores a deposit
    note from its recovery phrase by re-deriving the owner from (its spend key, rho), so without these a carried note
    could not be found on the new chain. Each record is kept only when commit(amount, owner, rho) is a carried
    commitment (a deposit the exec layer refused made no note), once per commitment, sorted by (addr, owner, rho).
    INVARIANT: only what the old chain published is written — never a note's spend key or a nullifier."""
    from execnode import shielded_stwo as _S
    have, out = set(commitments), {}

    def _int(v):
        return _S.wire_u64(v)

    for addr, amount, owner, rho in ([(r.get("addr"), r.get("amount"), r.get("owner"), r.get("rho")) for r in prev or []]
                                     + [(t.get("sender"), t.get("amount"), (t.get("data") or {}).get("owner"),
                                         (t.get("data") or {}).get("rho"))
                                        for t in txs or [] if isinstance(t, dict) and t.get("recipient") == "shield"
                                        and isinstance(t.get("data"), dict) and t["data"].get("pool") == "stwo"]):
        a, r = _int(amount), _int(rho)
        if not isinstance(addr, str) or not addr or a is None or r is None or not _S.is_digest(owner):
            continue
        if not (0 < a < (1 << 64)) or r >= (1 << 64):
            continue
        cm = _S.commit(a, owner, r)
        if cm in have and cm not in out:
            out[cm] = {"addr": addr, "amount": str(a), "owner": owner, "rho": str(r)}
    return sorted(out.values(), key=lambda x: (x["addr"], x["owner"], int(x["rho"])))


def exec_shield_doc(d: dict, shield_escrow: int, deposits=None) -> dict:
    """The shielded section of the exec genesis (execnode/exec_genesis.py): the Stwo pool's commitments IN ORDER (a
    note's leaf position is part of its spend witness), its nullifier set (sorted; an already-spent note stays spent),
    `stwo_value`, and `pool_fees` = everything else SHIELD_ESCROW holds. NO marks: they name old-chain heights
    (exec_genesis docstring), so the new chain's anchors are the carried root and its append window.

    `shield_escrow` is SHIELD_ESCROW's L1 balance AFTER the pending unshield exits were folded out of it. On the old
    chain the shielded invariant (ops/invariants.check_shielded) is escrow == pool_value + pending exits + pool_fees,
    with any surplus a stranded deposit (STRANDED, no note backs it). Exec_value_the_carry_would_drop has already
    refused unless pool_value == stwo_value, so here escrow must hold at least stwo_value + pool_fees:
      * LESS refuses — notes the escrow does not back; carrying them would carry an unbacked mint (or the snapshot
        and the L1 balance are from different heights);
      * the surplus over stwo_value (old pool_fees + stranded deposits, 1,123,000 raw on betanet-9, locked since an
        earlier generation) is carried as the new layer's pool_fees: it stays in SHIELD_ESCROW, locked exactly as it
        was, and the new chain's invariant is exact (OK, not STRANDED) from block 0. Supply is untouched (Δ = 0): no
        coin moves between L1 accounts here.
    INVARIANT: after the carry, SHIELD_ESCROW == stwo_value + pool_fees (genesis.py refuses to build a chain where it is
    not). `deposits` (stwo_deposit_records) are the public records that keep carried deposit notes restorable."""
    sv, old_fees, esc = int(d.get("stwo_value") or 0), int(d.get("pool_fees") or 0), int(shield_escrow)
    if esc < sv + old_fees:
        raise SystemExit(f"REFUSING: SHIELD_ESCROW holds {esc} raw after the pending unshield exits, but the Stwo pool "
                         f"carries {sv} raw of notes and {old_fees} raw of in-pool fees — the escrow does not back the "
                         "carried notes (the shielded invariant does not hold on the source chain, or the exec "
                         "snapshot and the L1 balance are from different heights); reconcile before carrying")
    sp = d.get("stwo_pool") or {}
    cms = [str(c) for c in (sp.get("commitments") or [])]
    nfs = sorted(str(n) for n in (sp.get("nullifiers") or []))
    out = {"stwo_value": str(sv), "pool_fees": str(esc - sv)}
    if cms or nfs:
        out["stwo_pool"] = {"commitments": cms, "nullifiers": nfs}
    if deposits:
        out["stwo_deposits"] = list(deposits)
    return out


def exec_value_the_carry_would_drop(d: dict, tip=None, policy=None) -> list:
    """Reasons this exec snapshot holds value the carry cannot move yet ([] = nothing would be lost). The carry used to
    check only the LEGACY pool (`shielded`), while every shield deposit from block 1 lands in the WIDE pool and some in
    the field pool and app_state; and it ignored exec-side ASSETS (`abal`) entirely, so a held token died with the
    generation (assets now carry in the exec genesis). INVARIANT: every place exec value can sit is either folded or
    carried by this tool or listed here, because a reroll that silently drops a holder's note or token is a theft by the
    protocol.

    Review 2026-10-11 closed two more:
      * the Stwo pool (`stwo_pool`) was added after this list and was not in it; and `pool_value` — the exec layer's
        own running total of value inside every pool — is checked too, so a pool this list does not name yet is
        still refused rather than dropped;
      * an exec ASSET held BY A CONTRACT that the carry would reset: assets carry verbatim, but a reset contract starts
        from fresh-deploy storage, so the ledger that said whose those tokens are is gone and nothing can release them.
        `policy` (default carry_policy, with `tip`) decides which contracts reset."""
    out = []
    for name in SHIELDED_POOLS:
        if name in CARRIED_POOLS:
            continue
        pool = d.get(name) or {}
        if pool.get("commitments") or pool.get("trees"):
            out.append(f"{name} holds notes — holders must unshield before the reroll (or the pool must be carried)")
    # THE STWO POOL CARRIES (exec_shield_doc; 2026-10-12): a forced unshield would publish every holder's amount and
    # destination. INVARIANT: the carry moves exactly `stwo_value` of shielded value, so pool_value — the exec layer's
    # total over EVERY pool — must be fully explained by it; anything else sits in a pool the carry does not move.
    sv, pv = int(d.get("stwo_value") or 0), int(d.get("pool_value") or 0)
    if pv != sv:
        out.append(f"pool_value is {pv} raw but the Stwo pool carries {sv} — {pv - sv} raw sits in a shielded pool the "
                   "carry does not move; holders must unshield it before the reroll")
    sp = d.get("stwo_pool") or {}
    if sv and not sp.get("commitments"):
        out.append(f"stwo_value is {sv} raw but the Stwo pool holds no note — the snapshot is inconsistent")
    try:
        from execnode.shielded_stwo import StwoShieldedPool
        StwoShieldedPool.from_dict(sp)
    except Exception as e:                                  # a pool the exec layer itself would not load cannot carry
        out.append(f"the Stwo pool cannot be carried as it stands: {e}")
    # exec ASSETS are carried verbatim in the exec genesis (assets, abal, allow) — but only a holder that survives can
    # use them: a contract holding assets must itself carry ("keep")
    contracts = d.get("contracts") or {}
    held = {}
    for aid, hs in sorted((d.get("abal") or {}).items()):
        for holder, n in sorted((hs or {}).items()):
            if holder in contracts and _num(n):
                held.setdefault(holder, []).append(f"{aid}:{_num(n)}")
    if held:
        pol = policy or (lambda cid, c: carry_policy(cid, c, tip=tip))
        for cid in sorted(held):
            if pol(cid, contracts[cid]) != "keep":
                out.append(f"contract {cid[:16]} holds exec assets ({', '.join(held[cid][:4])}) but cannot carry — its "
                           "ledger of whose they are would be lost; settle it on the old chain (or make it carry)")
    return out


def build():
    kv_ops.init_env()
    d = json.load(open(EXEC_STATE))
    contracts = d.get("contracts", {})
    bridge = d.get("bridge", {})
    dividend = d.get("dividend", {})
    dws = d.get("dividend_withdrawals", {})
    bws = d.get("withdrawals", {})                   # pending bridge exits (old-root proofs die at reroll)
    uws = d.get("unshield_withdrawals", {})          # pending unshield exits (ditto)
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

    _lost = exec_value_the_carry_would_drop(d, tip=int(d.get("cursor", 0)))
    if _lost:
        raise SystemExit("REFUSING: the carry would drop exec value:\n  " + "\n  ".join(_lost))

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
    # 3) EVERY CONTRACT CARRIES with all its storage, re-encoded into the new generation's VM formats, and EVERY pot
    # stays in escrow with it (tools/carry.py; operator rule 2026-10-20). A contract that cannot carry losslessly
    # refuses the carry here — nothing is reset, nothing refunded in its place.
    from execnode import zkvmasm as _zasm
    _src = _zasm.default_isa()
    _amap = _carry.asset_map(d.get("assets"), _src, "v2")
    try:
        _gen_contracts, kept_pots, _reg = exec_genesis(contracts, pot_bridge, d.get("zk_addrs") or {},
                                                       int(d.get("cursor", 0)), dst="v2", amap=_amap)
    except _carry.Refused as e:
        raise SystemExit(f"REFUSING: {e}")
    from protocol import CHAIN_GENERATION as _G
    _EXEC_GENESIS[0] = {"generation": int(_G) + 1, "contracts": _gen_contracts,
                        "bridge": {c: str(v) for c, v in sorted(kept_pots.items())},
                        **exec_assets_doc(d, _amap),
                        # the payee registry carried storage resolves its digests through (execnode/exec_genesis.apply),
                        # keyed by each string's NEW digest — the one carried storage now holds
                        "zk_addrs": {str(k): str(v) for k, v in sorted(_reg.items())}}
    # ALREADY-CLAIMED EXITS ARE NOT PAID AGAIN (review 2026-09-25, measured). The exec node applies only FINALIZED L1
    # blocks, so exec_state trails L1 by ~45 blocks: a withdrawal claimed on L1 in that gap is already in its owner's
    # L1 balance while its exec record still exists. Folding it again paid it twice — and Δ stayed 0, because the
    # debit lands on the reserved escrow account. Drop every record whose L1 nullifier is set.
    dws = {n: w for n, w in dws.items() if not kv_ops.dividend_nullifier_exists(w["addr"], str(n))}
    bws = {n: w for n, w in bws.items() if not kv_ops.bridge_nullifier_exists("default", w["addr"], str(n))}
    uws = {n: w for n, w in uws.items() if not kv_ops.shield_nullifier_exists(w["addr"], str(n))}
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

    # 5b) OPEN INVITES AND HTLC LOCKS go back to whoever funded them (their records do not carry)
    esc_refunds, esc_out = open_escrow_refunds(kv_ops.invite_all(), kv_ops.htlc_all())
    for a, v in esc_refunds.items():
        credit(a, v)
    for acct, v in esc_out.items():
        if v:
            debit_reserved(acct, v)

    # 6) debit the escrow reserved accounts by exactly what was folded (conserve supply)
    bridge_out = sum(user_bridge.values()) + sum(_num(w["amount"]) for w in bws.values())
    dividend_out = sum(_num(v) for v in dividend.values()) + sum(_num(w["amount"]) for w in dws.values())
    shield_out = sum(_num(w["amount"]) for w in uws.values())
    debit_reserved("bridge", bridge_out)
    debit_reserved("dividend", dividend_out)
    if shield_out:
        debit_reserved("shield", shield_out)
    # 6b) THE STWO POOL CARRIES (exec_shield_doc): SHIELD_ESCROW keeps backing its notes; a deficit refuses here
    from protocol import SHIELD_ESCROW as _SHIELD_ESCROW
    _shield_left = alloc.get(_SHIELD_ESCROW, {"balance": 0})["balance"]
    # CARRIED DEPOSITS STAY RESTORABLE (stwo_deposit_records): the old chain's Stwo deposit transactions, and the records
    # its own exec genesis carried, so a wallet on the new chain can still re-derive each deposit note's owner
    from ops import transaction_ops as _tops
    from execnode import exec_genesis as _old_eg
    _shield_txs = _tops.get_transactions_of_account("shield", 0, limit=1 << 40)["transactions"]
    _deps = stwo_deposit_records(_shield_txs, (_old_eg.load() or {}).get("stwo_deposits") or [],
                                 (d.get("stwo_pool") or {}).get("commitments") or [])
    _EXEC_GENESIS[0].update(exec_shield_doc(d, _shield_left, _deps))

    carried = sum(e["balance"] + e["bonded"] for e in alloc.values())
    print("=== alphanet-6 carry-forward ===")
    print(f"L1 accounts total (balance+bonded):     {l1_total:>18} raw")
    print(f"  folded user bridge:                   {sum(user_bridge.values()):>18} raw -> users, -bridge escrow")
    print(f"  carried contract pots (stay escrowed): {sum(kept_pots.values()):>18} raw in {len(kept_pots)} contract(s); "
          f"{len(_gen_contracts)} contracts carried by id")
    print(f"  folded dividends (uncollected):       {sum(_num(v) for v in dividend.values()):>18} raw -> users, -dividend pool")
    print(f"  folded dividend withdrawals (pending):{sum(_num(w['amount']) for w in dws.values()):>18} raw -> users, -dividend pool")
    print(f"  folded bridge withdrawals (pending):  {sum(_num(w['amount']) for w in bws.values()):>18} raw -> users, -bridge escrow")
    print(f"  folded unshield withdrawals (pending):{shield_out:>18} raw -> users, -shield escrow")
    print(f"  refunded open invites / HTLC locks:   {esc_out['invite'] + esc_out['htlc']:>18} raw -> funders, -invite/-htlc escrow")
    print(f"  carried Stwo pool (stays escrowed):   {int(_EXEC_GENESIS[0]['stwo_value']):>18} raw in "
          f"{len((_EXEC_GENESIS[0].get('stwo_pool') or {}).get('commitments') or [])} notes, "
          f"{len((_EXEC_GENESIS[0].get('stwo_pool') or {}).get('nullifiers') or [])} spent; "
          f"{_EXEC_GENESIS[0]['pool_fees']} raw more in SHIELD_ESCROW carried as burned (pool_fees); "
          f"{len(_EXEC_GENESIS[0].get('stwo_deposits') or [])} deposit records kept restorable")
    print(f"carried total after folds:              {carried:>18} raw")
    print(f"CONSERVATION: {'OK' if carried == l1_total else 'FAIL'} (Δ={carried - l1_total})")
    print(f"accounts in alloc: {len(alloc)}")
    if carried != l1_total:
        raise SystemExit("conservation failed — refusing to write")
    # INVARIANT: what stays in BRIDGE_ESCROW is exactly the carried pots, because L1 genesis seeds the escrow counter
    # from them and refuses a mismatch (genesis.py) — a residual would be unbacked coins or a failed first exit.
    _esc = alloc.get("bridge", {"balance": 0})["balance"]
    if _esc != sum(kept_pots.values()):
        raise SystemExit(f"bridge escrow would hold {_esc} raw but the carried pots total {sum(kept_pots.values())} — "
                         "the exec bridge invariant does not hold on the source chain; reconcile before carrying")

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
    # INTO ADDRESS FORMAT 2 (the gen 27 -> 28 carry, betanet-9): every account and every piece of carried state moved to
    # the format-2 address of its recorded key (tools/rekey_v2.py). That is the ONLY carry that crosses the format switch:
    # from gen 28 on, format 2 is unconditional (protocol.ADDRESS_FORMAT deleted after the betanet-9 reroll), so a carry
    # from gen 28 to 29 RE-KEYS NOTHING — every keyed address already is its key's format-2 address, and a keyless row
    # still at its 46-char format-1 address carries unchanged, where legacy_claim keeps finding it. The re-key step is
    # kept, keyed on the SOURCE generation, so the tooling that did it stays runnable and reviewable.
    from protocol import CHAIN_GENERATION as _G
    _crosses_format_switch = int(_G) == 27
    _seeds_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "genesis_data", "genesis_open.dat")
    _seeds = json.load(open(_seeds_path)) if os.path.exists(_seeds_path) else []
    extra = None
    if _crosses_format_switch:
        from tools.rekey_v2 import rekey
        extra = build_extra() if "--l1-tip" in sys.argv else {}
        # KEYS FROM OLDER GENERATIONS (tools/recover_keys.py over the old backups): an account that never sent on this
        # chain but did on an older one re-keys like any other, and its owner's wallet derives the new address by itself.
        # Required so the step cannot be forgotten; `--known-keys none` states deliberately that there are none.
        _kk = next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--known-keys" and i + 1 < len(sys.argv)), None)
        if _kk is None:
            raise SystemExit("format 2: pass --known-keys <tools/recover_keys.py output> (or --known-keys none)")
        _known = {} if _kk == "none" else json.load(open(_kk))
        alloc, extra, _seeds, rep = rekey(alloc, extra, _seeds, _known)
        print(f"ADDRESS FORMAT 2: {rep['rekeyed']} accounts re-keyed ({rep['recovered_from_older_generations']} with a key "
              f"from an older generation), {rep['keyless_kept_at_old_address']} with no "
              f"recorded key kept at their old address (their key claims them: legacy_claim), "
              f"{rep['bond_released_raw']} raw of keyless bond released into balance")
        for a in rep.get("dropped_seeds", []):
            print(f"  relay seed {a} dropped: no chain recorded its key, so it cannot produce (its coins carry at its old address)")
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
        if extra is None:
            extra = build_extra()
        with open(_seeds_path, "w") as f:
            json.dump(_seeds, f, indent=1)
        xpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "genesis_data", "genesis_carry.dat")
        with open(xpath, "w") as f:
            json.dump(extra, f, indent=0, sort_keys=True)
        print("WROTE genesis_data/genesis_carry.dat")
        epath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "genesis_data", "exec_genesis.json")
        with open(epath, "w") as f:
            json.dump(_EXEC_GENESIS[0], f, indent=0, sort_keys=True)
        print(f"WROTE genesis_data/exec_genesis.json ({len(_EXEC_GENESIS[0]['contracts'])} contracts)")
    else:
        print("\n(dry run — pass --write to persist genesis_alloc.dat)")


if __name__ == "__main__":
    main()
