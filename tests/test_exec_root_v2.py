"""
EXEC_ROOT_V2_HEIGHT (security review 2026-09-23, S1 + C5 + the TIME-context gap) — the reroll-only change that
puts a contract's deployer / lock flag / runtime into the exec root as a META leaf, carries the four CODE EVENTS
(deploy / upgrade / lock / transfer_contract) in the DA calls binding, makes the settlement verifier DERIVE the
code- and meta-leaf updates those events cause, and stamps every call with chain_clock(h) so a TIME-reading call
proves what the chain applied.

Properties, each shown flipping at the gate and nowhere else:
  * the gen-25 root is byte-unchanged (the live gate is 2^62; the empty root still equals EXEC_GENESIS_ROOT);
  * from the gate the KV half commits deployer, lock flag and runtime — changing any one moves the root (C5);
  * from the gate block_calls carries the code events in tx order with the chain clock; below it, calls only;
  * exec_state_bind.apply_event reaches the same records as ExecState.apply_blob for the same blobs (the mirror
    the verifier's derivation rests on), including every refusal;
  * a span with an in-span upgrade, a deploy with a constructor and a lock proves and verifies to EXACTLY the
    root the chain holds; forging the upgrade's code, its sender, or dropping the event updates from the
    transition is refused; below the gate the same span cannot reach the chain's root;
  * a TIME-reading call proves to the chain's root from the gate, and not below it;
  * a reverting constructor deploys with empty storage on chain and is unprovable (quorum), never mis-proven.

Run: NADO_ALLOW_PYTHON_KERNELS=1 python3 tests/test_exec_root_v2.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-exec-root-v2-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ.setdefault("NADO_ALLOW_PYTHON_KERNELS", "1")
import sys, copy, asyncio, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol
from execnode import exec_root as ER, settlement_proofs as SP, zkvm, zkvmasm
from execnode.code_codec import contract_id, FIXED_CIDS
from execnode.state import ExecState
from execnode.stark import settlement_sparse as SS, exec_state_bind as ESB, calls_commit as CC, field as F

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


LIVE_GATE = protocol.EXEC_ROOT_V2_HEIGHT
LIVE_CTX = protocol.EXEC_CTX_CURRENT_HEIGHT


class gate:
    """Move the (reroll-only) gates for one test; F3 must be in force wherever the root gate is."""
    def __init__(self, h):
        self.h = h
    def __enter__(self):
        protocol.EXEC_ROOT_V2_HEIGHT = self.h
        protocol.EXEC_CTX_CURRENT_HEIGHT = min(self.h, LIVE_CTX) if self.h < LIVE_CTX else LIVE_CTX
    def __exit__(self, *a):
        protocol.EXEC_ROOT_V2_HEIGHT = LIVE_GATE
        protocol.EXEC_CTX_CURRENT_HEIGHT = LIVE_CTX


NQ, DEPTH, H = 8, 16, 300_000          # above every live gate: the rules a gen-26 block runs under
ALICE = "ndoAAAA" + "A" * 41
BOB = "ndoBBBB" + "B" * 41
BUMP1 = {"bump": zkvmasm.assemble("movi r1 0\n sload r2 r1\n movi r3 1\n add r2 r3\n sstore r1 r2\n ret r2")}
BUMP2 = {"bump": zkvmasm.assemble("movi r1 0\n sload r2 r1\n movi r3 2\n add r2 r3\n sstore r1 r2\n ret r2")}
CTOR = {"constructor": zkvmasm.assemble("movi r1 3\n movi r2 42\n sstore r1 r2\n ret r2"),
        "get": zkvmasm.assemble("movi r1 3\n sload r2 r1\n ret r2")}
TIMER = {"stamp": zkvmasm.assemble("ctx r1 time\n movi r2 1\n sstore r2 r1\n ret r1")}
REVERT_CTOR = {"constructor": zkvmasm.assemble("movi r1 0\n require r1\n ret r1")}


def _tx(sender, data, txid):
    return {"recipient": "blob", "sender": sender, "txid": txid, "data": dict(data)}


def _block(h, txs):
    return {"block_number": h, "block_hash": "ab" * 32, "block_timestamp": 0, "block_transactions": txs}


def _chain(blocks, st=None):
    """Apply blocks through the real exec path (_apply_block sets _applying / cursor / block_ts)."""
    from execnode.execnode import _apply_block
    st = st or ExecState(os.path.join(os.environ["HOME"], f"s{id(blocks)}.json"))
    loop = asyncio.new_event_loop()
    for b in blocks:
        assert loop.run_until_complete(_apply_block(None, {"default": st}, st, b, verbose=False)) is True
    return st


def _pre_state_at(h_before, txs_before):
    """A chain state holding the pre-span contracts, applied at an earlier height."""
    return _chain([_block(h_before, txs_before)])


# ---------------------------------------------------------------------------------------------------------
def t_live_gate_is_off_and_roots_unchanged():
    assert LIVE_GATE == (1 << 62) and not ESB.root_v2(10 ** 9), "the gate must be OFF on gen 25"
    from protocol import EXEC_GENESIS_ROOT
    assert ER.state_root_hex({}, ExecState(os.path.join(os.environ["HOME"], "e.json"))) == EXEC_GENESIS_ROOT
    contracts = {"c" * 32: {"code": BUMP1, "storage": {"slots": {"0": 5}}, "deployer": ALICE, "runtime": "zkvm"}}
    plain = ER.kv_projection(contracts)
    assert ER.kv_projection(contracts, v2=False) == plain and ESB.meta_key("c" * 32, ER.DEPTH) not in plain
    assert SS.sparse_projection(contracts, DEPTH) == {ESB.code_key("c" * 32, DEPTH): ESB.code_commitment(BUMP1),
                                                      ESB.slot_key("c" * 32, 0, DEPTH): 5}
    blk = _block(H, [_tx(ALICE, {"op": "deploy", "code": BUMP1}, "t1"),
                     _tx(ALICE, {"op": "call", "contract": "x", "method": "m", "args": []}, "t2")])
    calls = CC.block_calls(blk)
    assert [c.get("op") for c in calls] == [None] and calls[0]["timestamp"] == 0, "below the gate: calls only, ts 0"


def t_meta_leaf_commits_deployer_lock_and_runtime():
    cid = "c" * 32
    base = {cid: {"code": BUMP1, "storage": {"slots": {}}, "deployer": ALICE, "runtime": "zkvm", "upgradable": True}}
    with gate(1):
        p = ER.kv_projection(base, v2=True)
        assert ESB.meta_key(cid, ER.DEPTH) in p and p[ESB.meta_key(cid, ER.DEPTH)] != 0
        roots = set()
        for mut in ({}, {"deployer": BOB}, {"upgradable": False}, {"runtime": "other"}):
            c = copy.deepcopy(base); c[cid].update(mut)
            roots.add(SS.root_hex(SS.sparse_root(c, DEPTH, v2=True)))
        assert len(roots) == 4, "deployer, lock flag and runtime must each move the root"
        # the sparse pin and the exec root's KV half agree leaf-for-leaf at the same depth
        assert set(SS.sparse_projection(base, ER.DEPTH, v2=True)) == set(ER.kv_projection(base, v2=True))
        # a legacy record with no flags commits the exec layer's defaults (upgradable, zkvm)
        legacy = {cid: {"code": BUMP1, "storage": {"slots": {}}, "deployer": ALICE, "runtime": "zkvm"}}
        assert SS.sparse_root(legacy, DEPTH, v2=True) == SS.sparse_root(base, DEPTH, v2=True)


def t_block_calls_carries_code_events_from_the_gate():
    import base64, json, zstandard
    codez = base64.b64encode(zstandard.ZstdCompressor().compress(json.dumps(BUMP2).encode())).decode()
    txs = [_tx(ALICE, {"op": "deploy", "code": BUMP1, "nonce": "n1"}, "t1"),
           _tx(ALICE, {"op": "call", "contract": "x", "method": "m", "args": []}, "t2"),
           _tx(ALICE, {"op": "upgrade", "contract": "x", "codez": codez}, "t3"),
           _tx(ALICE, {"op": "lock", "contract": "x"}, "t4"),
           _tx(ALICE, {"op": "transfer_contract", "contract": "x", "to": BOB}, "t5"),
           _tx(ALICE, {"op": "emit", "to_ns": "y"}, "t6"),
           _tx(ALICE, {"op": "deploy", "code": {"m": "not-a-list"}, "at": {"weird": 1}, "upgradable": "no"}, "t7")]
    with gate(1):
        calls = CC.block_calls(_block(H, txs))
        assert [c.get("op") for c in calls] == ["deploy", None, "upgrade", "lock", "transfer_contract", "deploy"]
        assert all(c["cursor"] == H and c["timestamp"] == protocol.chain_clock(H) for c in calls)
        assert calls[2]["code"] == BUMP2, "codez decodes to the code the exec layer applies"
        assert calls[5]["at"] is None and calls[5]["upgradable"] is False
        raw = dict(calls[2]); raw["code"] = BUMP2
        assert CC.event_leaf(raw) == CC.event_leaf(calls[2])
        inert, by_ns = CC.block_summary(_block(H, txs))
        assert by_ns["default"] == [CC.entry_leaf(c) for c in calls]
        leaves = {CC.entry_leaf(c) for c in calls}
        assert len(leaves) == 6, "every entry has its own leaf"
        # an event leaf and a call leaf never collide even with identical fields
        assert CC.event_leaf({"op": "deploy", "caller": ALICE, "cursor": H}) != CC.call_leaf({"cid": "", "caller": ALICE, "cursor": H})
        assert not inert, "an emit moves records"
    assert [c.get("op") for c in CC.block_calls(_block(H, txs))] == [None], "the gate is off live"


def t_apply_event_mirrors_the_chain():
    """The verifier's replay (apply_event) must reach the SAME records as ExecState.apply_blob for the same
    blobs — admitted and refused alike — because it is what the settle proof's transition is checked against."""
    cid1 = contract_id(ALICE, BUMP1, "n1")
    faucet_owner = FIXED_CIDS["faucet"]
    txs = [_tx(ALICE, {"op": "deploy", "code": BUMP1, "nonce": "n1"}, "t1"),
           _tx(ALICE, {"op": "deploy", "code": BUMP1, "nonce": "n1"}, "t1b"),                  # exists -> skip
           _tx(BOB, {"op": "upgrade", "contract": cid1, "code": BUMP2}, "t2"),                    # not deployer
           _tx(ALICE, {"op": "upgrade", "contract": cid1, "code": BUMP2, "runtime": None}, "t3"),  # keep runtime
           _tx(ALICE, {"op": "upgrade", "contract": cid1, "code": BUMP1, "runtime": ""}, "t3b"),   # v2: not a name
           _tx(ALICE, {"op": "transfer_contract", "contract": cid1, "to": BOB}, "t4"),
           _tx(ALICE, {"op": "lock", "contract": cid1}, "t5"),                                    # no longer owner
           _tx(BOB, {"op": "lock", "contract": cid1}, "t6"),
           _tx(BOB, {"op": "upgrade", "contract": cid1, "code": BUMP1}, "t7"),                    # locked
           _tx(BOB, {"op": "deploy", "code": CTOR, "at": "faucet"}, "t8"),                        # not allowlisted
           _tx(faucet_owner, {"op": "deploy", "code": CTOR, "at": "faucet", "upgradable": "no"}, "t9"),
           _tx(ALICE, {"op": "deploy", "code": {"m": "junk"}, "nonce": "n2"}, "t10"),             # invalid code
           _tx(ALICE, {"op": "deploy", "code": BUMP1, "nonce": "n3", "runtime": "nope"}, "t11"),  # unknown runtime
           _tx(ALICE, {"op": "transfer_contract", "contract": cid1, "to": ""}, "t12"),
           _tx(ALICE, {"op": "deploy", "code": REVERT_CTOR, "nonce": "n4"}, "t13")]                # empty storage
    with gate(1):
        st = _chain([_block(H, txs)])
        mirror = {}
        entries = CC.block_calls(_block(H, txs))
        for e in entries:
            ESB.apply_event(mirror, e)
        strip = lambda cs: {cid: (c["code"], c.get("deployer"), c.get("upgradable", True) is not False, c.get("runtime"))
                            for cid, c in cs.items()}
        assert strip(mirror) == strip(st.contracts), f"\nchain  {strip(st.contracts)}\nmirror {strip(mirror)}"
        assert set(mirror) == {cid1, "faucet", contract_id(ALICE, REVERT_CTOR, "n4")}
        assert mirror[cid1]["code"] == BUMP2 and mirror[cid1]["deployer"] == BOB and mirror[cid1]["upgradable"] is False
        assert mirror["faucet"]["upgradable"] is False
        assert st.contracts[contract_id(ALICE, REVERT_CTOR, "n4")]["storage"] == {} or \
            st.contracts[contract_id(ALICE, REVERT_CTOR, "n4")]["storage"].get("slots", {}) == {}
        # the meta leaves the chain now holds are the ones the mirror derives
        assert SS.sparse_root(st.contracts, DEPTH, v2=True) == SS.sparse_root(
            {cid: dict(c, storage=st.contracts[cid]["storage"]) for cid, c in mirror.items()}, DEPTH, v2=True)


def _span():
    cid1 = contract_id(ALICE, BUMP1, "n1")
    cid2 = contract_id(ALICE, CTOR, "n2")
    pre_txs = [_tx(ALICE, {"op": "deploy", "code": BUMP1, "nonce": "n1"}, "p1")]
    span_txs = [_tx(BOB, {"op": "call", "contract": cid1, "method": "bump", "args": []}, "s1"),
                _tx(ALICE, {"op": "upgrade", "contract": cid1, "code": BUMP2}, "s2"),
                _tx(BOB, {"op": "call", "contract": cid1, "method": "bump", "args": []}, "s3"),
                _tx(ALICE, {"op": "deploy", "code": CTOR, "nonce": "n2"}, "s4"),
                _tx(BOB, {"op": "call", "contract": cid2, "method": "get", "args": []}, "s5"),
                _tx(ALICE, {"op": "lock", "contract": cid1}, "s6")]
    return cid1, cid2, pre_txs, span_txs


def t_span_with_code_events_proves_to_the_chain_root():
    cid1, cid2, pre_txs, span_txs = _span()
    with gate(1):
        st = _chain([_block(H - 1, pre_txs)])
        pre_contracts = copy.deepcopy(st.contracts)
        pre_root = SS.sparse_root(st.contracts, DEPTH, v2=True)
        _chain([_block(H, span_txs)], st)
        assert st.contracts[cid1]["storage"]["slots"]["0"] == 3, "1 then 2: the second bump ran the UPGRADED code"
        assert st.contracts[cid2]["storage"]["slots"]["3"] == 42, "the constructor ran"
        chain_root = SS.sparse_root(st.contracts, DEPTH, v2=True)
        entries = CC.block_calls(_block(H, span_txs))
        assert [e.get("op") for e in entries] == [None, "upgrade", None, "deploy", None, "lock"]
        bundle = SS.prove_bound_epoch(pre_contracts, entries, cursor=H, num_queries=NQ, depth=DEPTH)
        assert bundle["sparse_pre_root"] == pre_root
        ok, why, post = SS.verify_bound_epoch(bundle, num_queries=NQ)
        assert ok, why
        assert post == chain_root, "the proof settles EXACTLY the root the chain holds"
        assert len([u for u in ESB.vm_units(bundle["pre_contracts"], bundle["calls"], H, 0)]) == 4, "3 calls + 1 constructor"
        # the DA binding: L1's per-block summary folds to the bundle's commitment
        _inert, by_ns = CC.block_summary(_block(H, span_txs))
        assert CC.fold_leaves(CC.alghash.IV, by_ns["default"]) == bundle["calls_commitment"]
        # the lock is in the root: the transition carried a meta update for cid1 and a code+meta pair for cid2
        lead = ESB.event_updates(pre_contracts, entries, DEPTH)
        assert {k for k, _o, _n in lead} == {ESB.code_key(cid1, DEPTH), ESB.meta_key(cid1, DEPTH),
                                             ESB.code_key(cid2, DEPTH), ESB.meta_key(cid2, DEPTH)}
        assert [tuple(u[:1]) for u in bundle["transition"]["updates"][:len(lead)]] == [(k,) for k, _o, _n in lead]

        # FORGERIES. The upgrade's code swapped (a call proven against code the chain replaced):
        bad = copy.deepcopy(bundle); bad["calls"][1]["code"] = BUMP1
        assert not SS.verify_bound_epoch(bad, num_queries=NQ)[0], "swapped upgrade code must be refused"
        # the upgrade's sender forged to the deployer by a non-deployer (the leaf commits the caller):
        bad = copy.deepcopy(bundle); bad["calls"][1]["caller"] = BOB
        assert not SS.verify_bound_epoch(bad, num_queries=NQ)[0], "a forged event sender must be refused"
        # the pre-state's deployer forged so a non-deployer's upgrade would be admitted: the META pin catches it
        bad = copy.deepcopy(bundle); bad["pre_contracts"][cid1]["deployer"] = BOB
        okb, whyb, _ = SS.verify_bound_epoch(bad, num_queries=NQ)
        assert not okb, whyb                    # (the upgrade is then refused in the replay, so the exec statement fails first)
        # the transition without the event updates (a prover that ignores the events):
        bad = copy.deepcopy(bundle); bad["transition"]["updates"] = bad["transition"]["updates"][len(lead):]
        assert not SS.verify_bound_epoch(bad, num_queries=NQ)[0], "a transition missing the event updates must be refused"
        # the whole-span dry run agrees the span is provable, and the records half sees the four VM units
        assert SP.first_unprovable_call(pre_contracts, entries, H) == (None, None)
        from execnode.stark import records_bind as RB
        assert RB.pay_effects_from_segment(bundle, {}) == [], "no payouts in the span; the io splits per VM unit"


def t_below_the_gate_the_same_span_cannot_reach_the_chain_root():
    cid1, cid2, pre_txs, span_txs = _span()
    span_txs = [t for t in span_txs if t["data"].get("contract") != cid2 and t["data"].get("op") != "deploy"]
    st = _chain([_block(H - 1, pre_txs)])
    pre_contracts = copy.deepcopy(st.contracts)
    _chain([_block(H, span_txs)], st)
    assert st.contracts[cid1]["storage"]["slots"]["0"] == 3
    entries = CC.block_calls(_block(H, span_txs))
    assert [e.get("op") for e in entries] == [None, None], "gen 25: the upgrade and the lock are invisible to the binding"
    bundle = SS.prove_bound_epoch(pre_contracts, entries, cursor=H, num_queries=NQ, depth=DEPTH)
    ok, why, post = SS.verify_bound_epoch(bundle, num_queries=NQ)
    assert ok, why
    assert post != SS.sparse_root(st.contracts, DEPTH), "gen 25: an honest proof lands beside the chain (the S1 finding)"


def t_time_reading_call_proves_the_chain_transition_from_the_gate():
    cid = contract_id(ALICE, TIMER, "n1")
    pre_txs = [_tx(ALICE, {"op": "deploy", "code": TIMER, "nonce": "n1"}, "p1")]
    span_txs = [_tx(BOB, {"op": "call", "contract": cid, "method": "stamp", "args": []}, "s1")]
    for on in (True, False):
        with gate(1 if on else LIVE_GATE):
            st = _chain([_block(H - 1, pre_txs)])
            pre_contracts = copy.deepcopy(st.contracts)
            _chain([_block(H, span_txs)], st)
            # gen 25 hands the VM the PREVIOUS block's clock (F3 is what moves it to h); either way it is not 0
            assert st.contracts[cid]["storage"]["slots"]["1"] == protocol.chain_clock(H if on else H - 1) % F.P
            entries = CC.block_calls(_block(H, span_txs))
            bundle = SS.prove_bound_epoch(pre_contracts, entries, cursor=H, num_queries=NQ, depth=DEPTH)
            ok, why, post = SS.verify_bound_epoch(bundle, num_queries=NQ)
            assert ok, why
            same = post == SS.sparse_root(st.contracts, DEPTH, v2=on)
            assert same == on, f"gate {'on' if on else 'off'}: proof {'must' if on else 'cannot'} match the chain (TIME context)"


def t_reverting_constructor_is_unprovable_not_misproven():
    cid = contract_id(ALICE, REVERT_CTOR, "n1")
    span_txs = [_tx(ALICE, {"op": "deploy", "code": REVERT_CTOR, "nonce": "n1"}, "s1")]
    with gate(1):
        st = _chain([_block(H, span_txs)])
        assert cid in st.contracts and not st.contracts[cid]["storage"].get("slots"), "chain: deployed, empty storage"
        entries = CC.block_calls(_block(H, span_txs))
        idx, why = SP.first_unprovable_call({}, entries, H)
        assert idx == 0 and "reverted" in why, (idx, why)


def t_faucet_seed_is_off_from_the_gate():
    owner = FIXED_CIDS["faucet"]
    defund = {"defund": zkvmasm.assemble("movi r0 1\n ret r0")}
    for on in (True, False):
        with gate(1 if on else LIVE_GATE):
            st = _chain([_block(H - 1, [_tx(owner, {"op": "deploy", "code": BUMP1, "at": "faucet"}, "p1")])])
            st.bridge["faucet"] = 777
            _chain([_block(H, [_tx(owner, {"op": "upgrade", "contract": "faucet", "code": defund}, "s1")])], st)
            slot7 = st.contracts["faucet"]["storage"].get("slots", {}).get("7")
            assert (slot7 is None) == on, f"gate {'on' if on else 'off'}: slot 7 = {slot7}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_"):
            check(name[2:].replace("_", " "), fn)
    print("ALL PASS" if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
