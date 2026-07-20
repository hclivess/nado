"""
The asset layer (doc/assets.md): a second value type on the exec layer, and the five zkVM opcodes that let
a CONTRACT hold, move, mint and burn it — ASEL/AMINT/ABURN/ABAL/ACTX.

What this pins down, in the order the money can go wrong:
  * the ledger itself — create/transfer/burn/mint/renounce through the blob path, supply conservation,
    canonical absence-at-zero, and the fact that an unknown asset and a zero balance are the same thing;
  * AUTHORITY — only an issuer mints, only while mintable, and renouncing is one-way;
  * SOLVENCY — a contract can no more overpay an asset than it can overpay NADO, and a call that would is
    reverted WHOLE (the native and asset halves commit together or not at all);
  * the PAIRING that makes a 2-register instruction able to move a 3-value asset transfer: an ASEL binds
    exactly the instruction after it, enforced at the deploy gate AND again in the verifier's log replay,
    because an unpaired PAY moves NADO where the contract meant to move a token;
  * the DIFFERENTIAL guarantee for the new opcodes — natively-applied call, interpreter, and the PROVEN
    call's replayed io log all agree (doc/nado-dev-approaches: money code verified 3 ways).

Run: python3 tests/test_assets.py                  (~40s: includes one real proof)
"""
import os, sys, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState, asset_id, ASSET_SUPPLY_CAP
from execnode import runtimes, zkvm, zkvmasm
from execnode.zkpy import Contract, hash as zhash
from execnode.stark import vm_circuit, field as F

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


ALICE = "mldsa44" + "a" * 42
BOB = "mldsa44" + "b" * 42
CAROL = "mldsa44" + "c" * 42


def fresh():
    """An ExecState on a throwaway path (never load()s anything, never save()s)."""
    d = tempfile.mkdtemp()
    return ExecState(os.path.join(d, "exec_state.json"))


def create(st, sender=ALICE, seed=1, supply=1000, mintable=False, sym="TKN"):
    st.apply_blob({"op": "asset_create", "seed": seed, "name": "Token", "sym": sym,
                   "dec": 4, "supply": supply, "mintable": mintable}, sender, "tx")
    return str(asset_id(sender, seed))


# ---- 1. the ledger ---------------------------------------------------------------------------------
def t_create_and_transfer():
    st = fresh()
    aid = create(st)
    assert aid in st.assets, "asset not created"
    m = st.assets[aid]
    assert (m["issuer"], m["supply"], m["mintable"], m["sym"]) == (ALICE, 1000, False, "TKN"), m
    assert st.asset_balance(aid, ALICE) == 1000
    assert st.asset_balance(aid, BOB) == 0, "an unheld asset must read 0, not raise"

    st.apply_blob({"op": "asset_transfer", "asset": aid, "to": BOB, "amount": 400}, ALICE, "tx")
    assert (st.asset_balance(aid, ALICE), st.asset_balance(aid, BOB)) == (600, 400)
    # canonical absence: a row that reaches zero is DELETED, or two nodes with the same balances would
    # commit different roots (the same rule bridge balances and storage slots already follow).
    st.apply_blob({"op": "asset_transfer", "asset": aid, "to": BOB, "amount": 600}, ALICE, "tx")
    assert ALICE not in st.abal.get(aid, {}), "zero balance must be pruned, not stored as 0"
    assert st.asset_balance(aid, BOB) == 1000

    # id is DERIVED, so a second create with the same seed is a no-op, not a second asset
    before = dict(st.assets[aid])
    st.apply_blob({"op": "asset_create", "seed": 1, "name": "Evil", "sym": "EVL", "dec": 0,
                   "supply": 10 ** 6, "mintable": True}, ALICE, "tx")
    assert st.assets[aid] == before, "re-creating an existing id must not overwrite it"


def t_transfer_guards():
    st = fresh()
    aid = create(st, supply=100)
    for bad, why in (({"op": "asset_transfer", "asset": aid, "to": BOB, "amount": 101}, "overdraft"),
                     ({"op": "asset_transfer", "asset": aid, "to": BOB, "amount": 0}, "zero"),
                     ({"op": "asset_transfer", "asset": aid, "to": BOB, "amount": -5}, "negative"),
                     ({"op": "asset_transfer", "asset": aid, "to": "", "amount": 5}, "no recipient"),
                     ({"op": "asset_transfer", "asset": "999", "to": BOB, "amount": 5}, "unknown asset")):
        r = st.apply_blob(bad, ALICE, "tx")
        assert r.startswith("skip"), f"{why} was accepted: {r}"
    assert st.asset_balance(aid, ALICE) == 100 and st.asset_balance(aid, BOB) == 0
    # a sender who holds nothing cannot move anything
    assert st.apply_blob({"op": "asset_transfer", "asset": aid, "to": ALICE, "amount": 1},
                         CAROL, "tx").startswith("skip")


def t_mint_authority_and_renounce():
    st = fresh()
    aid = create(st, supply=10, mintable=True)
    assert st.apply_blob({"op": "asset_mint", "asset": aid, "to": BOB, "amount": 5},
                         BOB, "tx").startswith("skip"), "a non-issuer minted"
    st.apply_blob({"op": "asset_mint", "asset": aid, "to": BOB, "amount": 5}, ALICE, "tx")
    assert (st.assets[aid]["supply"], st.asset_balance(aid, BOB)) == (15, 5)
    assert st.apply_blob({"op": "asset_mint", "asset": aid, "to": BOB, "amount": ASSET_SUPPLY_CAP},
                         ALICE, "tx").startswith("skip"), "supply cap not enforced"

    assert st.apply_blob({"op": "asset_renounce", "asset": aid}, BOB, "tx").startswith("skip")
    st.apply_blob({"op": "asset_renounce", "asset": aid}, ALICE, "tx")
    assert st.assets[aid]["mintable"] is False
    assert st.apply_blob({"op": "asset_mint", "asset": aid, "to": BOB, "amount": 1},
                         ALICE, "tx").startswith("skip"), "renounce is not one-way"

    # a FIXED-supply asset is never mintable, not even by its issuer, not even at creation+1
    fixed = create(st, seed=2, supply=7, mintable=False, sym="FIX")
    assert st.apply_blob({"op": "asset_mint", "asset": fixed, "to": ALICE, "amount": 1},
                         ALICE, "tx").startswith("skip")


def t_burn_lowers_supply():
    st = fresh()
    aid = create(st, supply=100)
    st.apply_blob({"op": "asset_burn", "asset": aid, "amount": 40}, ALICE, "tx")
    assert (st.assets[aid]["supply"], st.asset_balance(aid, ALICE)) == (60, 60)
    assert st.apply_blob({"op": "asset_burn", "asset": aid, "amount": 61}, ALICE, "tx").startswith("skip")
    # supply always equals the sum of balances — the one invariant that makes the ledger money
    assert st.assets[aid]["supply"] == sum(st.abal[aid].values())


def t_create_validation():
    st = fresh()
    for bad in ({"seed": 1, "name": "", "sym": "X", "dec": 0, "supply": 1},
                {"seed": 1, "name": "n", "sym": "", "dec": 0, "supply": 1},
                {"seed": 1, "name": "n", "sym": "X", "dec": 19, "supply": 1},
                {"seed": 1, "name": "n", "sym": "X", "dec": 0, "supply": ASSET_SUPPLY_CAP},
                {"seed": 1, "name": "n", "sym": "X", "dec": 0, "supply": -1},
                {"seed": -1, "name": "n", "sym": "X", "dec": 0, "supply": 1},
                {"seed": 1, "name": "n" * 65, "sym": "X", "dec": 0, "supply": 1}):
        r = st.apply_blob(dict(bad, op="asset_create"), ALICE, "tx")
        assert r.startswith("skip"), f"bad create accepted: {bad} -> {r}"
    assert not st.assets


def t_root_commits_assets():
    """An asset balance must MOVE the settled root, or it isn't really on the chain."""
    st = fresh()
    r0 = st.state_root()
    aid = create(st, supply=5)
    r1 = st.state_root()
    st.apply_blob({"op": "asset_transfer", "asset": aid, "to": BOB, "amount": 2}, ALICE, "tx")
    r2 = st.state_root()
    assert len({r0, r1, r2}) == 3, "creating/moving an asset did not change the state root"
    # and it round-trips through persistence byte-identically
    st.save()
    st2 = ExecState(st.path)
    assert st2.state_root() == r2 and st2.assets == st.assets and st2.abal == st.abal


# ---- 2. the opcodes --------------------------------------------------------------------------------
# A minimal "shop": takes an asset deposit, reports what it holds, pays it back out, mints its OWN asset
# (derived from its own digest, exactly as a launchpad or an AMM's LP token would be), and burns.
def shop_code():
    c = Contract()
    with c.method("held") as m:                        # r0 = asset id -> this contract's balance of it
        m.ret(m.abal(m.arg(0)))
    with c.method("note") as m:                        # RECORD which asset arrived (a view has no call
        # context of its own, so the only honest way to observe ACTX_ASSET is to have a real call store it;
        # +1 keeps "a native call arrived" (0) distinguishable from "no call has ever arrived" (empty slot).
        m.slot(1, m.const(0)).set(m.in_asset() + 1)
        m.ret(m.const(1))
    with c.method("noted") as m:
        m.ret(m.slot(1, m.const(0)).get())
    with c.method("payout") as m:                      # arg0 = asset, arg1 = to, arg2 = amount
        m.apay(m.arg(0), m.arg(1), m.arg(2))
        m.ret(m.const(1))
    with c.method("sweep") as m:                       # arg0 = asset, arg1 = to — pays out ALL of it.
        # Deliberately touches every new opcode in one method: ABAL (how much), ACTX_SELF (folded into a
        # tag it then REQUIREs, so the self digest is genuinely constrained by the trace and not merely
        # a periodic column nobody reads), and the ASEL+PAY pair.
        bal = m.set(m.abal(m.arg(0)), None)
        tag = m.set(zhash(m.me(), m.const(7)), None)
        m.require(tag != 0)
        m.apay(m.arg(0), m.arg(1), bal)
        m.ret(bal)
    with c.method("issue") as m:                       # mint the contract's OWN asset (seed 1) to arg1
        aid = m.set(zhash(m.me(), m.const(1)), None)
        m.amint(aid, m.arg(1), m.arg(2))
        m.ret(m.const(1))
    with c.method("issue_at") as m:                     # mint an asset named by the CALLER (arg0)
        m.amint(m.arg(0), m.arg(1), m.arg(2))
        m.ret(m.const(1))
    with c.method("scorch") as m:                      # burn arg2 of arg0 from its own holding
        m.aburn(m.arg(0), m.arg(2))
        m.ret(m.const(1))
    with c.method("pay_then_read") as m:               # pay arg2, then report what is left
        m.apay(m.arg(0), m.arg(1), m.arg(2))
        m.ret(m.abal(m.arg(0)))
    return c.build()


def deploy_shop(st):
    st.apply_blob({"op": "deploy", "code": shop_code(), "nonce": 1}, ALICE, "tx")
    return next(iter(st.contracts))


def t_actx_and_abal():
    st = fresh()
    cid = deploy_shop(st)
    aid = create(st, supply=1000)
    # deposit 250 of the asset INTO the contract by calling with asset-denominated value
    st.apply_blob({"op": "call", "contract": cid, "method": "note", "args": [], "value": 250,
                   "asset": aid}, ALICE, "tx")
    assert st.asset_balance(aid, cid) == 250, "asset call value was not escrowed to the contract"
    assert st.asset_balance(aid, ALICE) == 750
    # ACTX_ASSET saw which currency arrived; ABAL sees the holding
    assert st.view(cid, "noted", []) == (int(aid) + 1) % F.P
    assert st.view(cid, "held", [int(aid)]) == 250
    assert st.view(cid, "held", [12345]) == 0, "an asset the contract never held must read 0"
    # a NATIVE call still reports asset 0 — every pre-asset contract is untouched by this
    st.bridge[ALICE] = 10 ** 9
    st.apply_blob({"op": "call", "contract": cid, "method": "note", "args": [], "value": 7}, ALICE, "tx")
    assert st.view(cid, "noted", []) == 1, "a native call must report asset 0"


def t_contract_pays_and_is_solvent():
    st = fresh()
    cid = deploy_shop(st)
    aid = create(st, supply=1000)
    st.apply_blob({"op": "call", "contract": cid, "method": "note", "args": [], "value": 300,
                   "asset": aid}, ALICE, "tx")
    r = st.apply_blob({"op": "call", "contract": cid, "method": "payout",
                       "args": [int(aid), BOB, 120]}, ALICE, "tx")
    assert r.endswith("-> ok"), r
    assert (st.asset_balance(aid, cid), st.asset_balance(aid, BOB)) == (180, 120)
    # SOLVENCY: the contract cannot pay out what it does not hold — same rule as native NADO
    r = st.apply_blob({"op": "call", "contract": cid, "method": "payout",
                       "args": [int(aid), BOB, 181]}, ALICE, "tx")
    assert "revert" in r, r
    assert (st.asset_balance(aid, cid), st.asset_balance(aid, BOB)) == (180, 120), "reverted pay leaked"
    # and the total is conserved across every one of those moves
    assert sum(st.abal[aid].values()) == st.assets[aid]["supply"] == 1000


def t_contract_mints_its_own_asset():
    """The launchpad/LP-token shape: a contract owns an asset whose id it derives IN-CIRCUIT from its own
    digest, so nobody had to tell it the id and nobody else can mint it.

    THE CREATION PATH IS THE POINT, and this test originally faked it: it passed `cid` as the blob sender,
    which cannot happen — a blob sender is an L1 address derived from a pubkey and a cid is a 32-hex hash,
    so no transaction can ever carry one. Under the real rules a contract could not be an issuer at all,
    which made AMINT unreachable in production while this test reported it working. The contract's
    DEPLOYER now creates the asset FOR it (`for`: cid), and the assertions below pin the authority split
    that makes that safe."""
    st = fresh()
    cid = deploy_shop(st)
    # only the deployer, and only for a contract that exists
    assert st.apply_blob({"op": "asset_create", "seed": 1, "name": "LP", "sym": "LP", "dec": 0,
                          "supply": 0, "mintable": True, "for": cid}, BOB, "tx").startswith("skip")
    assert st.apply_blob({"op": "asset_create", "seed": 1, "name": "LP", "sym": "LP", "dec": 0,
                          "supply": 0, "mintable": True, "for": "nosuch"}, ALICE, "tx").startswith("skip")
    st.apply_blob({"op": "asset_create", "seed": 1, "name": "LP", "sym": "LP", "dec": 0,
                   "supply": 0, "mintable": True, "for": cid}, ALICE, "tx")
    aid = str(asset_id(cid, 1))
    assert st.assets[aid]["issuer"] == cid
    r = st.apply_blob({"op": "call", "contract": cid, "method": "issue",
                       "args": [0, BOB, 500]}, ALICE, "tx")
    assert r.endswith("-> ok"), r
    assert st.asset_balance(aid, BOB) == 500 and st.assets[aid]["supply"] == 500

    # the in-circuit derivation must equal the ledger's — this is the whole trick, so pin it
    from execnode.stark import alghash
    assert int(aid) == alghash.hashn([runtimes.zkvm_addr_digest(cid), 1]) % F.P

    # a DIFFERENT contract cannot mint it. Two distinct attacks, and both must fail:
    st.apply_blob({"op": "deploy", "code": shop_code(), "nonce": 2}, BOB, "tx")
    other = [k for k in st.contracts if k != cid][0]
    #   (a) deriving "its own" asset 1 — a different digest, so a different id that does not exist
    r = st.apply_blob({"op": "call", "contract": other, "method": "issue",
                       "args": [0, BOB, 1]}, BOB, "tx")
    assert "revert" in r and "no such asset" in r, r
    #   (b) naming the victim's id outright — the id is public, so THIS is the attack that matters, and
    #       what stops it is the issuer field, not the secrecy of the derivation
    r = st.apply_blob({"op": "call", "contract": other, "method": "issue_at",
                       "args": [int(aid), BOB, 1]}, BOB, "tx")
    assert "revert" in r and "issuer" in r, r
    #   (c) and neither can a plain user, straight through the blob path
    assert st.apply_blob({"op": "asset_mint", "asset": aid, "to": BOB, "amount": 1},
                         BOB, "tx").startswith("skip")
    assert st.assets[aid]["supply"] == 500 and st.asset_balance(aid, BOB) == 500

    #   (d) the DEPLOYER — who created it — still cannot mint it or move the contract's holdings. Creating
    #       and renouncing are theirs; minting and moving belong to the contract's code alone.
    assert st.apply_blob({"op": "asset_mint", "asset": aid, "to": ALICE, "amount": 1},
                         ALICE, "tx").startswith("skip"), "the deployer minted a contract's asset"
    st.apply_blob({"op": "call", "contract": cid, "method": "issue", "args": [0, cid, 40]}, ALICE, "tx")
    held = st.asset_balance(aid, cid)
    assert held == 40
    assert st.apply_blob({"op": "asset_transfer", "asset": aid, "to": ALICE, "amount": 1},
                         ALICE, "tx").startswith("skip"), "the deployer moved a contract's holding"
    assert st.asset_balance(aid, cid) == held

    # renouncing shuts the contract's mint down too — done by the deployer, since the contract cannot
    # send a blob. Safe to grant: renouncing only ever REMOVES power.
    assert st.apply_blob({"op": "asset_renounce", "asset": aid}, BOB, "tx").startswith("skip")
    st.apply_blob({"op": "asset_renounce", "asset": aid}, ALICE, "tx")
    r = st.apply_blob({"op": "call", "contract": cid, "method": "issue", "args": [0, BOB, 1]}, ALICE, "tx")
    assert "revert" in r, r


def t_abal_sees_its_own_pending_moves():
    """`apay(x) ; abal(x)` must report the REDUCED holding. The exec layer settles a call's effects in
    order, so if ABAL read the untouched ledger instead, the VM and the settlement replay would disagree
    about the very same number and the call would revert on a balance check it believed it had passed."""
    st = fresh()
    cid = deploy_shop(st)
    aid = create(st, supply=1000)
    st.apply_blob({"op": "call", "contract": cid, "method": "note", "args": [], "value": 400,
                   "asset": aid}, ALICE, "tx")
    code = st.contracts[cid]["code"]
    cf, fargs = runtimes.zkvm_statement(ALICE, [int(aid), BOB, 150], dict(st.zk_addrs))
    ok, ret, _ns, io = zkvm.run(code, "pay_then_read", cf, fargs, {},
                                selfd=runtimes.zkvm_addr_digest(cid), abal=st.holder_assets(cid))
    assert ok and ret == 250, (ok, ret, "ABAL did not see the pay that preceded it")

    # and the whole call applies — the ABAL read the VM logged must survive the layer's own re-derivation
    r = st.apply_blob({"op": "call", "contract": cid, "method": "pay_then_read",
                       "args": [int(aid), BOB, 150]}, ALICE, "tx")
    assert r.endswith("-> ok"), r
    assert (st.asset_balance(aid, cid), st.asset_balance(aid, BOB)) == (250, 150)

    # paying ITSELF leaves the holding alone on both sides of that agreement
    r = st.apply_blob({"op": "call", "contract": cid, "method": "pay_then_read",
                       "args": [int(aid), cid, 100]}, ALICE, "tx")
    assert r.endswith("-> ok"), r
    assert st.asset_balance(aid, cid) == 250


def t_contract_burns():
    st = fresh()
    cid = deploy_shop(st)
    aid = create(st, supply=1000)
    st.apply_blob({"op": "call", "contract": cid, "method": "note", "args": [], "value": 400,
                   "asset": aid}, ALICE, "tx")
    r = st.apply_blob({"op": "call", "contract": cid, "method": "scorch",
                       "args": [int(aid), 0, 150]}, ALICE, "tx")
    assert r.endswith("-> ok"), r
    assert st.asset_balance(aid, cid) == 250 and st.assets[aid]["supply"] == 850
    assert sum(st.abal[aid].values()) == 850
    r = st.apply_blob({"op": "call", "contract": cid, "method": "scorch",
                       "args": [int(aid), 0, 251]}, ALICE, "tx")
    assert "revert" in r and st.assets[aid]["supply"] == 850, "over-burn was not reverted"


def t_asset_call_value_refunds_on_revert():
    """An asset-denominated call value must refund EXACTLY on revert — the same guarantee native value has,
    or a reverting call would silently eat the caller's tokens."""
    st = fresh()
    cid = deploy_shop(st)
    aid = create(st, supply=1000)
    r = st.apply_blob({"op": "call", "contract": cid, "method": "payout",
                       "args": [int(aid), BOB, 999999], "value": 100, "asset": aid}, ALICE, "tx")
    assert "revert" in r, r
    assert st.asset_balance(aid, ALICE) == 1000 and st.asset_balance(aid, cid) == 0
    assert aid not in st.abal or cid not in st.abal[aid]
    # and a call whose asset does not exist never runs at all
    assert st.apply_blob({"op": "call", "contract": cid, "method": "note", "args": [], "value": 1,
                          "asset": "404"}, ALICE, "tx").startswith("skip")


# ---- 3. the pairing rule ---------------------------------------------------------------------------
def t_deploy_gate_enforces_pairing():
    """ASEL binds the instruction AFTER it. Hand-written bytecode that separates them is the
    fund-substitution bug (the PAY moves NADO, not the token), so the deploy gate must refuse it."""
    ok = lambda code: zkvm.validate_code({"m": code})

    def rejects(code, why):
        try:
            ok(code)
        except zkvm.ZkVMError:
            return
        raise AssertionError(f"validate_code accepted {why}")

    rejects([["ASEL", 0, 1, 0], ["RET", 0, 0, 0]], "ASEL followed by something that is not a spend")
    rejects([["ASEL", 0, 1, 0]], "ASEL as the last instruction")
    rejects([["AMINT", 1, 2, 0], ["RET", 0, 0, 0]], "AMINT with no ASEL before it")
    rejects([["ASEL", 0, 1, 0], ["PAY", 2, 3, 0], ["JMP", 0, 0, 1], ["RET", 0, 0, 0]],
            "a jump landing on the spend (skipping its selection)")
    # the legal forms
    ok([["ASEL", 0, 1, 0], ["PAY", 2, 3, 0], ["RET", 0, 0, 0]])
    ok([["ASEL", 0, 1, 0], ["AMINT", 2, 3, 0], ["RET", 0, 0, 0]])
    ok([["PAY", 2, 3, 0], ["RET", 0, 0, 0]])                    # a bare PAY is still native NADO
    rejects([["ACTX", 0, 0, 4], ["RET", 0, 0, 0]], "an ACTX index outside the mux")


def t_asel_zero_reverts():
    """`asel r0` with r0 = 0 would mean 'select native' — which is exactly the substitution the pairing
    rule exists to prevent, so the VM reverts rather than quietly paying NADO."""
    code = {"m": [["ASEL", 0, 0, 0], ["PAY", 1, 2, 0], ["RET", 0, 0, 0]]}
    ok, *_ = zkvm.run(code, "m", 7, [0, 5, 3], {}, abal={0: 10, 9: 10})
    assert not ok, "ASEL of asset 0 must revert"
    ok, *_ = zkvm.run(code, "m", 7, [9, 5, 3], {}, abal={9: 10})
    assert ok, "a real asset id must select fine"
    # and a selection the contract cannot afford reverts too, rather than emitting a log the exec layer
    # would only have to throw away
    ok, *_ = zkvm.run(code, "m", 7, [9, 5, 3], {}, abal={9: 2})
    assert not ok, "an unaffordable asset pay must revert in the VM"


def t_replay_io_pairing_and_failclosed():
    """replay_io verifies a LOG, not a program, so it re-checks the pairing itself — and by default it
    refuses asset logs outright rather than silently dropping half a state transition."""
    log = [(zkvm.IO_ASEL, 9, 0), (zkvm.IO_PAY, 5, 3), (zkvm.IO_RET, 1, 0)]
    ok, *_ = zkvm.replay_io(log, {})
    assert not ok, "asset io must be rejected when the caller has not opted in"
    ok, _ret, _st, payouts, _chain, fx = zkvm.replay_io(log, {}, with_assets=True)
    assert ok and payouts == [] and fx == [("pay", 9, 5, 3)], (ok, payouts, fx)

    for bad, why in (([(zkvm.IO_ASEL, 9, 0), (zkvm.IO_RET, 1, 0)], "selection never spent"),
                     ([(zkvm.IO_ASEL, 0, 0), (zkvm.IO_PAY, 5, 3), (zkvm.IO_RET, 1, 0)], "ASEL of 0"),
                     ([(zkvm.IO_AMINT, 5, 3), (zkvm.IO_RET, 1, 0)], "mint with no selection"),
                     ([(zkvm.IO_ASEL, 9, 0), (zkvm.IO_SSTORE, 1, 1), (zkvm.IO_PAY, 5, 3),
                       (zkvm.IO_RET, 1, 0)], "an entry wedged between selection and spend")):
        ok, *_ = zkvm.replay_io(bad, {}, with_assets=True)
        assert not ok, f"replay_io accepted a log with {why}"


# ---- 4. the differential guarantee -------------------------------------------------------------------
def t_proven_call_matches_native():
    """Native apply == interpreter == PROVEN call replayed from its io log, for a call that uses every one
    of the new opcodes. This is the check that the AIR columns actually constrain what the VM did."""
    st = fresh()
    cid = deploy_shop(st)
    aid = create(st, supply=1000)
    st.apply_blob({"op": "call", "contract": cid, "method": "note", "args": [], "value": 500,
                   "asset": aid}, ALICE, "tx")

    code = st.contracts[cid]["code"]
    slots = {int(k): int(v) for k, v in (st.contracts[cid]["storage"].get("slots") or {}).items()}
    reg = dict(st.zk_addrs)
    # `sweep` reads its amount from ABAL and folds ACTX_SELF into a REQUIREd tag, so this one call exercises
    # every new opcode AND makes both of the new public columns load-bearing.
    cf, fargs = runtimes.zkvm_statement(ALICE, [int(aid), BOB], reg)
    selfd = runtimes.zkvm_addr_digest(cid)
    abal = st.holder_assets(cid)

    # 1) the interpreter
    ok, ret, new_slots, io = zkvm.run(code, "sweep", cf, fargs, slots, cursor=st.cursor,
                                      selfd=selfd, abal=abal)
    assert ok and ret == 500, (ok, ret)
    assert [e[0] for e in io if e[0] in zkvm.IO_ASSET_KINDS] == [zkvm.IO_ABAL, zkvm.IO_ASEL], io

    # 2) the proof — and the verifier accepts it for exactly this public statement
    proof, pio, pret, _ns = vm_circuit.prove_call(code, "sweep", cf, fargs, slots, cursor=st.cursor,
                                                  selfd=selfd, abal=abal, num_queries=8)
    assert pret == ret and list(pio) == list(io)
    okv, why = vm_circuit.verify_call(proof, code, "sweep", cf, fargs, pio, cursor=st.cursor,
                                      selfd=selfd, num_queries=8)
    assert okv, why
    # a verifier that is told the WRONG self digest must reject: ACTX_SELF is a public column, so lying
    # about it changes the statement the proof was made for
    okv2, _ = vm_circuit.verify_call(proof, code, "sweep", cf, fargs, pio, cursor=st.cursor,
                                     selfd=selfd + 1, num_queries=8)
    assert not okv2, "verify accepted a forged ACTX_SELF"

    # 3) the log replay — no execution at all, and it names the same asset move
    ok3, ret3, st3, pays3, _ch, fx3 = zkvm.replay_io(pio, slots, with_assets=True)
    assert ok3 and ret3 == ret and st3 == new_slots and pays3 == []
    assert fx3 == [("bal", int(aid) % F.P, 0, 500),
                   ("pay", int(aid) % F.P, runtimes.zkvm_addr_digest(BOB), 500)], fx3

    # 4) and the exec layer settles that replayed effect to the same balances the native apply reaches
    named = [(k, str(a), reg.get(str(t)) if t else None, amt) for k, a, t, amt in fx3]
    ok4, why4, deltas, sup = st.stage_asset_effects(cid, named)
    assert ok4, why4
    assert deltas == {(aid, cid): -500, (aid, BOB): 500} and sup == {}
    # a log whose ABAL read does NOT match the ledger is refused — that read is a claim about state, and
    # this is where a stranger's proof gets checked against what this node actually holds
    lied = [("bal", aid, None, 499)] + named[1:]
    ok5, _why5, _d, _s = st.stage_asset_effects(cid, lied)
    assert not ok5, "a forged ABAL read was accepted"


def t_supply_invariant_catches_a_mismatch():
    """ops/invariants: an asset's supply must equal the sum of its balances. The other invariant domains
    reconcile against an L1 escrow; an asset has none, so INTERNAL consistency is the whole guarantee —
    and a detector nobody has watched fail is not a detector."""
    from ops import invariants
    st = fresh()
    aid = create(st, supply=1000)
    st.apply_blob({"op": "asset_transfer", "asset": aid, "to": BOB, "amount": 400}, ALICE, "tx")
    ok, d = invariants.check_assets(lambda *a, **k: None, st)
    assert ok and d["status"] == "ok" and d["mismatched"] == 0, d

    # supply inflated with no balance behind it: the total is overstated, but nobody can SPEND the
    # difference — so it is unaccounted, not a mint. Both still fail; the status has to tell them apart.
    st.assets[aid]["supply"] += 7
    ok, d = invariants.check_assets(lambda *a, **k: None, st)
    assert not ok and d["status"] == "unaccounted" and d["worst_delta"] == -7 and d["worst_asset"] == aid, d
    st.assets[aid]["supply"] -= 7

    # a balance the supply does not account for IS a mint — those units are spendable
    st.abal[aid][CAROL] = 5
    ok, d = invariants.check_assets(lambda *a, **k: None, st)
    assert not ok and d["status"] == "mint" and d["worst_delta"] == 5, d
    del st.abal[aid][CAROL]

    # a balance row for an asset that does not exist would otherwise be invisible (the walk is over assets)
    st.abal["999999"] = {CAROL: 1}
    ok, d = invariants.check_assets(lambda *a, **k: None, st)
    assert not ok and d["orphan_ledgers"] == 1, d
    del st.abal["999999"]
    ok, _d = invariants.check_assets(lambda *a, **k: None, st)
    assert ok, "the check did not go green again"


def _pre(st, *cids):
    return {c: {"code": st.contracts[c]["code"], "storage": st.contracts[c]["storage"], "runtime": "zkvm"}
            for c in cids}


def t_settlement_prover_settles_asset_io():
    """§8 CLOSED: the epoch prover now carries an asset shadow, so an asset-touching call is PROVEN (and its
    proof verifies), not refused. Two shapes: an asset-DENOMINATED call (its `asset` rides in the public
    statement, the escrow path), and a held-asset PAYOUT (moves the ledger; storage post_root matches a
    native apply)."""
    import copy
    from execnode import settlement_proofs as SP
    st = fresh()
    cid = deploy_shop(st)
    aid = create(st, supply=1000)

    # (1) an asset-denominated call — `note` deposits 500 of `aid`. pre-state is BEFORE the deposit; the
    #     call's asset must appear in the public statement (it drives ACTX_ASSET / ABAL).
    pre = _pre(st, cid)
    bundle = SP.prove_epoch(pre, [{"cid": cid, "method": "note", "caller": ALICE, "args": [],
                                   "value": 500, "asset": int(aid)}], cursor=st.cursor,
                            pre_abal=copy.deepcopy(st.abal), pre_assets=copy.deepcopy(st.assets), num_queries=8)
    okv, why, _ = SP.verify_epoch(bundle, num_queries=8)
    assert okv, why
    assert bundle["calls"][0]["asset"] == int(aid), "the call-value asset is not in the public statement"
    st.apply_blob({"op": "call", "contract": cid, "method": "note", "args": [], "value": 500, "asset": aid}, ALICE, "tx")
    assert bundle["post_root"] == SP.zkvm_root({cid: st.contracts[cid]}), "post_root != native storage root"

    # (2) a held-asset payout — moves the ledger (asset=0 on the call, since nothing is sent WITH it).
    bundle2 = SP.prove_epoch(_pre(st, cid), [{"cid": cid, "method": "payout", "caller": ALICE,
                                             "args": [int(aid), BOB, 120]}], cursor=st.cursor,
                             pre_abal=copy.deepcopy(st.abal), pre_assets=copy.deepcopy(st.assets), num_queries=8)
    okv2, why2, _ = SP.verify_epoch(bundle2, num_queries=8)
    assert okv2, why2
    st.apply_blob({"op": "call", "contract": cid, "method": "payout", "args": [int(aid), BOB, 120]}, ALICE, "tx")
    assert bundle2["post_root"] == SP.zkvm_root({cid: st.contracts[cid]})
    assert (st.asset_balance(aid, cid), st.asset_balance(aid, BOB)) == (380, 120)


def t_settlement_prover_mint_burn():
    """The prover settles a contract minting its OWN asset and burning from its holding — the launchpad
    shapes. Authority (issuer==cid, mintable) is enforced by the shadow, which the VM does not check."""
    import copy
    from execnode import settlement_proofs as SP
    st = fresh()
    cid = deploy_shop(st)
    st.apply_blob({"op": "asset_create", "seed": 1, "name": "LP", "sym": "LP", "dec": 0,
                   "supply": 0, "mintable": True, "for": cid}, ALICE, "tx")
    aid = str(asset_id(cid, 1))
    st.apply_blob({"op": "call", "contract": cid, "method": "issue", "args": [0, cid, 400]}, ALICE, "tx")  # cid holds 400
    # prove a burn of 150 of its own holding
    bundle = SP.prove_epoch(_pre(st, cid), [{"cid": cid, "method": "scorch", "caller": ALICE,
                                             "args": [int(aid), 0, 150]}], cursor=st.cursor,
                            pre_abal=copy.deepcopy(st.abal), pre_assets=copy.deepcopy(st.assets), num_queries=8)
    okv, why, _ = SP.verify_epoch(bundle, num_queries=8)
    assert okv, why
    # prove a mint of 500 to BOB (the contract issuing its own token)
    bundle2 = SP.prove_epoch(_pre(st, cid), [{"cid": cid, "method": "issue", "caller": ALICE,
                                             "args": [0, BOB, 500]}], cursor=st.cursor,
                             pre_abal=copy.deepcopy(st.abal), pre_assets=copy.deepcopy(st.assets), num_queries=8)
    okv2, why2, _ = SP.verify_epoch(bundle2, num_queries=8)
    assert okv2, why2


def t_settlement_prover_rejects_overdraw():
    """A payout exceeding the contract's holding is a VM revert — the prover raises, exactly as the native
    apply reverts. (Holder-side solvency IS enforced by the VM.)"""
    import copy
    from execnode import settlement_proofs as SP
    st = fresh()
    cid = deploy_shop(st)
    aid = create(st, supply=1000)
    st.apply_blob({"op": "call", "contract": cid, "method": "note", "args": [], "value": 100, "asset": aid}, ALICE, "tx")
    try:
        SP.prove_epoch(_pre(st, cid), [{"cid": cid, "method": "payout", "caller": ALICE,
                                        "args": [int(aid), BOB, 101]}], cursor=st.cursor,
                       pre_abal=copy.deepcopy(st.abal), pre_assets=copy.deepcopy(st.assets), num_queries=8)
    except ValueError:
        return
    raise AssertionError("the prover proved a payout larger than the holding")


def t_settlement_prover_enforces_mint_authority():
    """THE CRITICAL ASSERTION. The VM emits a well-formed AMINT for ANY asset — it does NOT check who may
    mint. Only stage_asset_effects does, and on the proof path the shadow is the SOLE enforcer. A second
    contract naming a victim's asset (issue_at) produces a valid mint log the shadow must reject on issuer,
    and a renounced asset a mint the shadow must reject on mintable — either would let the prover prove a
    transition the chain reverts if the shadow stopped mirroring authority."""
    import copy
    from execnode import settlement_proofs as SP
    st = fresh()
    cid = deploy_shop(st)
    st.apply_blob({"op": "asset_create", "seed": 1, "name": "LP", "sym": "LP", "dec": 0,
                   "supply": 0, "mintable": True, "for": cid}, ALICE, "tx")
    aid = str(asset_id(cid, 1))
    st.apply_blob({"op": "deploy", "code": shop_code(), "nonce": 2}, BOB, "tx")
    other = [k for k in st.contracts if k != cid][0]

    # (a) a DIFFERENT contract mints the victim's asset by naming it — the shadow rejects on issuer
    try:
        SP.prove_epoch(_pre(st, other), [{"cid": other, "method": "issue_at", "caller": BOB,
                                          "args": [int(aid), BOB, 1]}], cursor=st.cursor,
                       pre_abal=copy.deepcopy(st.abal), pre_assets=copy.deepcopy(st.assets), num_queries=8)
        raise AssertionError("the prover minted a victim's asset from another contract")
    except ValueError as e:
        assert "issuer" in str(e), e

    # (b) the issuer contract itself, but AFTER renounce — the shadow rejects on mintable
    st.apply_blob({"op": "asset_renounce", "asset": aid}, ALICE, "tx")
    try:
        SP.prove_epoch(_pre(st, cid), [{"cid": cid, "method": "issue", "caller": ALICE,
                                        "args": [0, BOB, 1]}], cursor=st.cursor,
                       pre_abal=copy.deepcopy(st.abal), pre_assets=copy.deepcopy(st.assets), num_queries=8)
        raise AssertionError("the prover minted a renounced asset")
    except ValueError as e:
        assert "renounced" in str(e), e


def t_uri_metadata():
    """A metadata/logo pointer: optional at create, issuer-updatable, bounded, and COMMITTED in the root
    (so a wallet showing a logo is showing committed state, not an off-chain claim it made up)."""
    from execnode.state import ASSET_URI_MAX
    st = fresh()
    st.apply_blob({"op": "asset_create", "seed": 1, "name": "Token", "sym": "TKN", "dec": 4,
                   "supply": 1000, "mintable": False, "uri": "ipfs://QmLogo"}, ALICE, "tx")
    aid = str(asset_id(ALICE, 1))
    assert st.assets[aid]["uri"] == "ipfs://QmLogo"
    r0 = st.state_root()

    # issuer updates it -> the root MOVES (it is committed, not a hint)
    st.apply_blob({"op": "asset_set_uri", "asset": aid, "uri": "https://x.io/t.png"}, ALICE, "tx")
    assert st.assets[aid]["uri"] == "https://x.io/t.png"
    assert st.state_root() != r0, "uri is not committed in the state root"

    # only the issuer may set it
    st.apply_blob({"op": "asset_set_uri", "asset": aid, "uri": "https://evil"}, BOB, "tx")
    assert st.assets[aid]["uri"] == "https://x.io/t.png", "a non-issuer changed the uri"

    # bounds + type
    st.apply_blob({"op": "asset_set_uri", "asset": aid, "uri": "x" * (ASSET_URI_MAX + 1)}, ALICE, "tx")
    assert st.assets[aid]["uri"] == "https://x.io/t.png", "an over-long uri was accepted"
    r = st.apply_blob({"op": "asset_create", "seed": 2, "name": "T2", "sym": "T2", "dec": 0,
                       "supply": 1, "uri": 123}, ALICE, "tx")
    assert "skip" in r and str(asset_id(ALICE, 2)) not in st.assets, "a non-string uri was accepted"

    # DEFAULT is empty, and an asset created without a uri still commits deterministically (backward compat)
    st.apply_blob({"op": "asset_create", "seed": 3, "name": "T3", "sym": "T3", "dec": 0, "supply": 1}, ALICE, "tx")
    aid3 = str(asset_id(ALICE, 3))
    assert st.assets[aid3]["uri"] == ""
    st.state_root()   # must not raise on a mix of uri and no-uri assets


def t_allowance_approve_transfer_from():
    """Delegated spend (approve / allowance / transferFrom), account-to-account. The two gates that make it
    safe: the standing allowance AND the owner's live balance, each independently, and the allowance
    decrements by exactly what moves."""
    st = fresh()
    aid = create(st, supply=1000)                       # ALICE holds 1000
    assert st.asset_allowance(aid, ALICE, BOB) == 0, "an unset allowance must read 0"

    # ALICE approves BOB for 400
    st.apply_blob({"op": "asset_approve", "asset": aid, "spender": BOB, "amount": 400}, ALICE, "tx")
    assert st.asset_allowance(aid, ALICE, BOB) == 400

    # BOB pulls 250 ALICE -> CAROL
    r = st.apply_blob({"op": "asset_transfer_from", "asset": aid, "from": ALICE, "to": CAROL, "amount": 250}, BOB, "tx")
    assert not r.startswith("skip"), r
    assert (st.asset_balance(aid, ALICE), st.asset_balance(aid, CAROL)) == (750, 250)
    assert st.asset_allowance(aid, ALICE, BOB) == 150, "allowance did not decrement by exactly what moved"

    # over-allowance is refused, nothing moves
    r = st.apply_blob({"op": "asset_transfer_from", "asset": aid, "from": ALICE, "to": CAROL, "amount": 151}, BOB, "tx")
    assert "skip" in r and st.asset_balance(aid, ALICE) == 750 and st.asset_allowance(aid, ALICE, BOB) == 150

    # allowance is a CEILING, not a promise: approve more than the balance, the pull is still bounded by balance
    st.apply_blob({"op": "asset_approve", "asset": aid, "spender": BOB, "amount": 10 ** 9}, ALICE, "tx")  # overwrite, not add
    assert st.asset_allowance(aid, ALICE, BOB) == 10 ** 9, "approve must OVERWRITE, not accumulate"
    r = st.apply_blob({"op": "asset_transfer_from", "asset": aid, "from": ALICE, "to": CAROL, "amount": 751}, BOB, "tx")
    assert "skip" in r and st.asset_balance(aid, ALICE) == 750, "a pull exceeding the balance leaked"

    # revoke (approve 0) and the row is pruned to absence
    st.apply_blob({"op": "asset_approve", "asset": aid, "spender": BOB, "amount": 0}, ALICE, "tx")
    assert st.asset_allowance(aid, ALICE, BOB) == 0
    assert ALICE not in st.allow.get(aid, {}), "a zeroed allowance must be pruned, not stored as 0"

    # you cannot approve yourself; unknown asset / bad amounts are refused
    assert "skip" in st.apply_blob({"op": "asset_approve", "asset": aid, "spender": ALICE, "amount": 5}, ALICE, "tx")
    assert "skip" in st.apply_blob({"op": "asset_approve", "asset": "deadbeef", "spender": BOB, "amount": 5}, ALICE, "tx")


def t_allowance_committed_in_root():
    """An allowance is provable against the settled root, like a balance — setting one moves the root, and a
    reloaded snapshot reproduces it exactly."""
    import tempfile, os as _os
    st = fresh()
    aid = create(st, supply=1000)
    r0 = st.state_root()
    st.apply_blob({"op": "asset_approve", "asset": aid, "spender": BOB, "amount": 400}, ALICE, "tx")
    assert st.state_root() != r0, "an allowance is not committed in the state root"
    # persist + reload round-trips the allowance and the root
    d = tempfile.mkdtemp(); p = _os.path.join(d, "s.json")
    st.path = p; st.save()
    st2 = ExecState(p)
    assert st2.asset_allowance(aid, ALICE, BOB) == 400
    assert st2.state_root() == st.state_root(), "allowance did not survive a save/load round-trip"


if __name__ == "__main__":
    check("metadata uri: optional, issuer-only, committed", t_uri_metadata)
    check("allowance: approve / transfer_from, two gates, exact decrement", t_allowance_approve_transfer_from)
    check("allowance committed in root + survives reload", t_allowance_committed_in_root)
    check("asset create + transfer + canonical absence", t_create_and_transfer)
    check("transfer guards (overdraft/zero/negative/unknown)", t_transfer_guards)
    check("mint authority + supply cap + one-way renounce", t_mint_authority_and_renounce)
    check("burn lowers supply; supply == sum of balances", t_burn_lowers_supply)
    check("asset_create validation", t_create_validation)
    check("assets are committed in the state root + persist", t_root_commits_assets)
    check("ACTX asset/self + ABAL through a real contract", t_actx_and_abal)
    check("contract pays an asset and stays solvent", t_contract_pays_and_is_solvent)
    check("contract mints its OWN derived asset; nobody else can", t_contract_mints_its_own_asset)
    check("ABAL sees the call's own pending moves", t_abal_sees_its_own_pending_moves)
    check("contract burns from its own holding", t_contract_burns)
    check("asset call value refunds exactly on revert", t_asset_call_value_refunds_on_revert)
    check("deploy gate enforces the ASEL pairing", t_deploy_gate_enforces_pairing)
    check("ASEL of asset 0 reverts", t_asel_zero_reverts)
    check("replay_io: pairing re-checked, fail-closed by default", t_replay_io_pairing_and_failclosed)
    check("native == interpreter == proven-and-replayed", t_proven_call_matches_native)
    check("supply invariant catches a mismatch", t_supply_invariant_catches_a_mismatch)
    check("settlement prover SETTLES asset io (§8 closed)", t_settlement_prover_settles_asset_io)
    check("settlement prover: mint + burn", t_settlement_prover_mint_burn)
    check("settlement prover: overdraw reverts", t_settlement_prover_rejects_overdraw)
    check("settlement prover: shadow enforces mint authority", t_settlement_prover_enforces_mint_authority)
    print("ALL PASS" if not fails else f"{fails} FAILURE(S)")
    sys.exit(1 if fails else 0)
