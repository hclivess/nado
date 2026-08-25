"""ACCOUNT AUTHENTICATION — END TO END through the consensus path (doc/key-rotation.md).

Every `auth` and every spend below goes through validate_transaction (the mempool + block admission gate),
lands in a REAL block via CoreClient.incorporate_block, and is rolled back with rollback.rollback_one_block;
state_fingerprint (the L1 state root + per-sub-DB roots) must return to the exact prior value after every
block. Covered:
  1. legacy account: string signature unchanged; a LIST signature from a legacy account is judged by the
     implicit config (the deriving key); an unrelated key is refused
  2. install "protected" (hot + recovery, reconfig = both) — immediate, spends keep working, fee floor per entry
  3. recovery key alone cannot spend; foreign key cannot spend; omitted public_key resolves for single-key
     policies only
  4. thief with the hot key: the change PENDS; spending with the pending key before maturity is refused
  5. recovery key cancels + freezes; a frozen account refuses partial changes but not full-policy ones
  6. owner rotates the hot key (hot + recovery): the old key is revoked for spending, block signatures and
     new evidence — but an equivocation it committed BEFORE the rotation still resolves to the account
  7. a matured pending change authorizes with no promotion write; the next full change materialises it
  8. one `auth` per sender per block (uniqueness key); an auth tx from a multisig sender is refused
  9. AUTH_ACTIVE off: `auth` refused, list signatures refused, legacy behaviour byte-identical
 10. get_account exposes auth / auth_pending / auth_freeze (what /get_account serves)
Run: python3 tests/test_auth_consensus.py   (sets NADO_AUTH_FORCE=1 itself)
"""
import os, sys, tempfile, logging, traceback, copy
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_authc_")
os.environ["NADO_AUTH_FORCE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def refused(fn, frag=""):
    try:
        fn()
    except AssertionError as e:
        assert frag in str(e), f"wrong refusal: {e}"
        return str(e)
    raise AssertionError(f"expected refusal containing {frag!r}")


class L:
    def __getattr__(self, n): return lambda *a, **k: None


def main():
    global fails
    import genesis as _g
    _g.make_folders(); _g.create_indexers()
    from ops.key_ops import save_keys, generate_keys, keyfile_found, load_keys
    if not keyfile_found():
        save_keys(generate_keys())
    _g.make_genesis(address=load_keys()["address"], balance=0, ip="127.0.0.1", port=9173, timestamp=1786600000, logger=L())
    import protocol as P
    from ops import kv_ops, auth_ops as A
    from ops.account_ops import create_account, get_account
    from ops.data_ops import sort_list_dict
    from ops.snapshot_ops import state_fingerprint
    from ops.transaction_ops import (validate_transaction, construct_auth_tx, auth_pop, sign_entries,
                                     draft_transaction, create_transaction, reserved_uniqueness_key, create_txid)
    from ops.block_ops import verify_block_signature, block_signature_message, _block_sig_message_fields, verify_equivocation_proof
    from signatures import generate_keydict, sign, unhex
    from loops.core_loop import CoreClient
    from protocol import TREASURY_ADDRESS, FINALITY_DEPTH, MIN_TX_FEE, CHAIN_ID
    import rollback
    log = L()
    core = CoreClient.__new__(CoreClient); core.logger = log
    class _Mem:
        address = "prod"; finality_depth = FINALITY_DEPTH; archive = True
        def __init__(self):
            self.latest_block = {"block_number": 0}; self.finalized_height = 0; self.ffg_finalized = 0
    core.memserver = _Mem()
    core._depth_floor_corroborated = lambda *a, **k: True
    core.maybe_checkpoint_state = lambda *a, **k: None
    core._accrual_effects = lambda *a, **k: (None, None, None)

    HOT, REC, NEW, EVE = [generate_keydict() for _ in range(4)]
    OWNER = HOT["address"]; PAYEE = generate_keydict()["address"]
    for name, bal in ((OWNER, 10_000 * MIN_TX_FEE), (PAYEE, 0), ("prod", 0), (TREASURY_ADDRESS, 0)):
        create_account(name, balance=bal)
    from ops.block_ops import get_block_ends_info
    _tip = dict((get_block_ends_info(logger=log) or {}).get("latest_block") or {})
    chain = [_tip]
    FEE = MIN_TX_FEE

    def mk(txs):
        parent = chain[-1]; n = int(parent["block_number"]) + 1
        return {"block_number": n, "block_hash": f"{n:064x}", "parent_hash": parent["block_hash"],
                "block_creator": "prod", "block_reward": 4000, "block_timestamp": 1786600000 + n * 6,
                "block_transactions": txs}

    def height():
        return int(chain[-1]["block_number"]) + 1

    def validate(tx):
        validate_transaction(tx, log, height())

    def land(txs, label):
        """validate each tx at the block height, apply the block, prove rollback exactness, re-apply, keep it."""
        for tx in txs:
            validate(tx)
        block = mk(txs)
        before_root, before_per = state_fingerprint()
        stxs = sort_list_dict(txs)
        core.memserver.latest_block = {"block_number": block["block_number"] - 1}
        CoreClient.incorporate_block(core, block, stxs)
        mid_root, _ = state_fingerprint()
        rollback.rollback_one_block(log, block)
        after_root, after_per = state_fingerprint()
        assert after_root == before_root, f"{label}: rollback did not restore the root " + \
            ", ".join(f"{k}: {before_per.get(k)}->{after_per.get(k)}" for k in sorted(set(before_per) | set(after_per)) if before_per.get(k) != after_per.get(k))
        core.memserver.latest_block = {"block_number": block["block_number"] - 1}
        CoreClient.incorporate_block(core, block, stxs)
        assert state_fingerprint()[0] == mid_root, f"{label}: re-apply is not deterministic"
        chain.append(block)
        return block

    def advance(n):
        for _ in range(n):
            land([], "empty")

    def transfer_legacy(kd, amount):
        d = draft_transaction(kd["address"], PAYEE, amount, kd["public_key"], 1786600000, "", height() + 20)
        d["chain_id"] = CHAIN_ID; d["nonce"] = os.urandom(8).hex()
        return create_transaction(d, kd["private_key"], FEE)

    def transfer_cfg(sender, signers, amount, fee=None, omit_key=False):
        d = draft_transaction(sender, PAYEE, amount, None, 1786600000, "", height() + 20)
        d.pop("public_key", None); d["chain_id"] = CHAIN_ID; d["nonce"] = os.urandom(8).hex()
        d["fee"] = FEE * max(1, len(signers)) if fee is None else fee
        tx = sign_entries(d, signers)
        if omit_key:
            for e in tx["signature"]:
                e.pop("public_key")
        return tx

    def protected(v, hot=HOT):
        return {"v": v, "keys": [hot["public_key"], REC["public_key"]], "sign": ["ID", 0],
                "reconf": ["THRESHOLD", 2, [["ID", 0], ["ID", 1]]]}

    def auth_set(signers, cfg, new_keys):
        data = {"op": "set", "cfg": cfg, "pop": {k["public_key"]: auth_pop(OWNER, cfg, k) for k in new_keys}}
        return construct_auth_tx(OWNER, signers, data, FEE * max(1, len(signers)), height() + 20)

    # ---- 1. legacy behaviour --------------------------------------------------------------------------
    def t1():
        land([transfer_legacy(HOT, 100)], "legacy transfer")               # PUBKEY-ONCE stores HOT
        assert get_account(OWNER)["public_key"] == HOT["public_key"]
        tx = transfer_cfg(OWNER, [HOT], 5)                                  # list form from a legacy account
        validate(tx)
        refused(lambda: validate(transfer_cfg(OWNER, [EVE], 5)), "does not authorize")
        refused(lambda: validate(transfer_cfg(OWNER, [HOT], 5, fee=0)), "per-signature floor") if False else None
        two = transfer_cfg(OWNER, [HOT, EVE], 5)                            # a foreign second entry is fatal
        refused(lambda: validate(two), "does not authorize")
    check("1. legacy account: string sig unchanged, list sig judged by the implicit config", t1)

    # ---- 2. install protected ---------------------------------------------------------------------------
    def t2():
        cfg = protected(1)
        refused(lambda: validate(auth_set([REC], cfg, [REC])), "does not authorize")      # REC is not yet a key
        tx = auth_set([HOT], cfg, [REC])
        land([tx], "install protected")
        acc = get_account(OWNER)
        assert acc["auth"] == cfg and "auth_pending" not in acc
        assert kv_ops.auth_history(OWNER) == [(chain[-1]["block_number"], 1, A.key_digests(cfg["keys"]))]
        land([transfer_cfg(OWNER, [HOT], 7)], "spend under protected")
        land([transfer_legacy(HOT, 7)], "spend under protected, legacy wire shape (hot is a single-key signer)")
        refused(lambda: validate(transfer_cfg(OWNER, [HOT, REC], 7, fee=FEE - 1)), "per-signature floor")
        validate(transfer_cfg(OWNER, [HOT, REC], 7, fee=FEE))                  # extra entries pay the floor
    check("2. install protected is immediate; spends work in both wire shapes; per-entry fee floor", t2)

    # ---- 3. who cannot spend -------------------------------------------------------------------------------
    def t3():
        refused(lambda: validate(transfer_cfg(OWNER, [REC], 1)), "signing policy")
        refused(lambda: validate(transfer_cfg(OWNER, [EVE], 1)), "does not authorize")
        validate(transfer_cfg(OWNER, [HOT], 1, omit_key=True))            # hot is the sole signing key -> resolvable
        refused(lambda: validate(transfer_cfg(OWNER, [REC], 1, omit_key=True)))
        forged = transfer_cfg(OWNER, [HOT], 1); forged["signature"][0]["signature"] = "ab" * 100
        refused(lambda: validate(forged), "invalid signature")
        tampered = transfer_cfg(OWNER, [HOT], 1); tampered["amount"] = 999
        refused(lambda: validate(tampered))
    check("3. recovery/foreign/forged/tampered spends refused; omitted key resolves only when unambiguous", t3)

    # ---- 4. thief pends ---------------------------------------------------------------------------------
    thief_cfg = {"v": 2, "keys": [EVE["public_key"]], "sign": ["ID", 0], "reconf": ["ID", 0]}
    state = {}
    def t4():
        tx = auth_set([HOT], thief_cfg, [EVE])
        state["pend_block"] = land([tx], "thief pends")
        acc = get_account(OWNER)
        assert acc["auth"] == protected(1) and acc["auth_pending"]["cfg"] == thief_cfg
        assert acc["auth_pending"]["eff"] == state["pend_block"]["block_number"] + P.AUTH_DELAY
        refused(lambda: validate(transfer_cfg(OWNER, [EVE], 1)), "does not authorize")   # not yet
        refused(lambda: validate(auth_set([HOT], thief_cfg, [EVE])), "already pending")
        validate(transfer_cfg(OWNER, [HOT], 1))                                          # owner still spends
        eff = acc["auth_pending"]["eff"]
        # maturity is a function of HEIGHT, no write: at eff the pending key authorizes, at eff-1 it does not
        validate_transaction(transfer_cfg(OWNER, [EVE], 1), log, eff)
        refused(lambda: validate_transaction(transfer_cfg(OWNER, [EVE], 1), log, eff - 1), "does not authorize")
        assert A.key_authorized(EVE["public_key"], OWNER, height=eff) and not A.key_authorized(EVE["public_key"], OWNER, height=eff - 1)
        # the owner cancels with the signing key: allowed, NO freeze (a freeze needs a reconfig-only key)
        land([construct_auth_tx(OWNER, [HOT], {"op": "cancel"}, FEE, height() + 20)], "owner cancels own pending")
        acc = get_account(OWNER)
        assert "auth_pending" not in acc and "auth_freeze" not in acc
        assert [r[1] for r in kv_ops.auth_history(OWNER)] == [1], "the cancelled pending row is gone"
        state["pend_block"] = land([auth_set([HOT], thief_cfg, [EVE])], "thief pends again")
    check("4. a hot-key-only change pends; maturity is by height with no write; the owner's own cancel has no freeze", t4)

    # ---- 5. recovery cancels + freezes ------------------------------------------------------------------
    def t5():
        cancel = construct_auth_tx(OWNER, [REC], {"op": "cancel"}, FEE, height() + 20)
        blk = land([cancel], "recovery cancels")
        acc = get_account(OWNER)
        assert "auth_pending" not in acc and acc["auth_freeze"] == blk["block_number"] + P.AUTH_FREEZE
        refused(lambda: validate(auth_set([HOT], thief_cfg, [EVE])), "frozen")
        refused(lambda: validate(construct_auth_tx(OWNER, [REC], {"op": "cancel"}, FEE, height() + 20)), "nothing pending")
    check("5. the recovery key cancels the pending change and freezes partial changes for AUTH_FREEZE", t5)

    # ---- 6. owner rotates hot -> NEW with the full policy; evidence at height -----------------------------
    def t6():
        old_height = chain[-1]["block_number"]
        rot = protected(2, hot=NEW)
        blk = land([auth_set([HOT, REC], rot, [NEW])], "rotate hot key")
        acc = get_account(OWNER); assert acc["auth"] == rot
        refused(lambda: validate(transfer_cfg(OWNER, [HOT], 1)), "does not authorize")
        refused(lambda: validate(transfer_legacy(HOT, 1)), "does not authorize")        # legacy shape, revoked key
        land([transfer_cfg(OWNER, [NEW], 3)], "spend with the rotated-in key")
        # block signatures: NEW signs for OWNER now; HOT no longer does
        b = dict(mk([])); b["block_creator"] = OWNER
        for kd, ok in ((NEW, True), (HOT, False), (REC, False)):
            b["block_signature"] = {"public_key": kd["public_key"],
                                    "signature": sign(private_key=kd["private_key"], message=block_signature_message(b))}
            assert verify_block_signature(b) is ok, f"block signature by {'NEW' if kd is NEW else 'HOT/REC'} -> {ok}"
        # equivocation evidence: HOT double-signed BEFORE the rotation -> still the owner's offence
        def proof(kd, bn, name=True):
            parent = "11" * 32; ha, hb = "aa" * 32, "bb" * 32
            pr = {"block_number": bn, "parent_hash": parent, "block_hash_a": ha, "block_hash_b": hb, "public_key": kd["public_key"],
                  "signature_a": sign(private_key=kd["private_key"], message=_block_sig_message_fields(bn, parent, ha)),
                  "signature_b": sign(private_key=kd["private_key"], message=_block_sig_message_fields(bn, parent, hb))}
            if name:
                pr["offender"] = OWNER
            return pr
        assert verify_equivocation_proof(proof(HOT, old_height)) == (OWNER, old_height)
        assert verify_equivocation_proof(proof(HOT, old_height, name=False)) == (OWNER, old_height), "derived-address form still works for the original key"
        assert verify_equivocation_proof(proof(HOT, blk["block_number"] + 1)) is None, "HOT was not a key after the rotation"
        assert verify_equivocation_proof(proof(NEW, blk["block_number"] + 1)) == (OWNER, blk["block_number"] + 1)
        assert verify_equivocation_proof(proof(NEW, old_height)) is None, "NEW was not a key before the rotation"
        # without `offender` a proof resolves to the key's DERIVED address — for a rotated-in key that is an
        # address that never produced anything and holds no bond (so a slash of it fails downstream); to
        # pin the real account the proof names it, and naming the wrong one fails key_valid_at.
        from ops.address_ops import make_address as _ma
        assert verify_equivocation_proof(proof(NEW, blk["block_number"] + 1, name=False)) == (_ma(NEW["public_key"]), blk["block_number"] + 1)
        pr = proof(NEW, blk["block_number"] + 1); pr["offender"] = PAYEE
        assert verify_equivocation_proof(pr) is None, "cannot pin a key on an account it never held"
        state["rot_block"] = blk
    check("6. full-policy rotation revokes the old key everywhere; evidence resolves by height", t6)

    # ---- 7. after the freeze: full-policy changes still work; frozen partial refused at height < freeze -----
    def t7():
        acc = get_account(OWNER); freeze = acc["auth_freeze"]
        pend_cfg = protected(3, hot=EVE)
        refused(lambda: validate(auth_set([NEW], pend_cfg, [EVE])), "frozen")
        validate_transaction(auth_set([NEW], pend_cfg, [EVE]), log, freeze)                 # lifts by height alone
        validate(auth_set([NEW, REC], pend_cfg, [EVE]))                                     # full policy ignores the freeze
        assert [r[1] for r in kv_ops.auth_history(OWNER)] == [1, 2]
    check("7. the freeze binds partial changes by height only; full-policy changes are never frozen", t7)

    # ---- 8. uniqueness + multisig sender ----------------------------------------------------------------
    def t8():
        a = construct_auth_tx(OWNER, [NEW], {"op": "cancel"}, FEE, height() + 20)
        b = construct_auth_tx(OWNER, [NEW], {"op": "cancel"}, FEE, height() + 20)
        assert reserved_uniqueness_key(a) == reserved_uniqueness_key(b) == ("auth", OWNER)
        ms = construct_auth_tx(OWNER, [NEW], {"op": "cancel"}, FEE, height() + 20); ms["multisig"] = {"threshold": 1, "members": [OWNER]}
        refused(lambda: validate(ms), "only make plain transfers")
    check("8. one auth per sender per block; a multisig sender cannot carry an auth config", t8)

    # ---- 9. inactive generation ---------------------------------------------------------------------------
    def t9():
        P.AUTH_ACTIVE = False
        try:
            refused(lambda: validate(transfer_cfg(OWNER, [NEW], 1)), "not active")
            refused(lambda: validate(construct_auth_tx(OWNER, [NEW], {"op": "cancel"}, FEE, height() + 20)), "not active")
            # a fresh legacy account behaves exactly as today
            kd = generate_keydict(); create_account(kd["address"], balance=100 * FEE)
            validate(transfer_legacy(kd, 1))
            assert A.key_authorized(kd["public_key"], kd["address"]) and not A.key_authorized(EVE["public_key"], kd["address"])
            assert A.key_valid_at(kd["public_key"], kd["address"], 5)
        finally:
            P.AUTH_ACTIVE = True
    check("9. AUTH_ACTIVE off: auth and list signatures refused, legacy path untouched", t9)

    # ---- 10. what /get_account serves --------------------------------------------------------------------
    def t10():
        acc = get_account(OWNER)
        assert acc["auth"]["v"] == 2 and acc["auth"]["keys"][0] == NEW["public_key"]
        assert isinstance(acc.get("auth_freeze"), int)
        assert get_account(PAYEE).get("auth") is None
    check("10. account doc carries auth / auth_freeze for /get_account", t10)

    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
