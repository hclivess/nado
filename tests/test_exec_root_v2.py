"""
EXEC_ROOT_V2_HEIGHT (security review 2026-09-23, S1 + C5 + the TIME-context gap) — the reroll-only change that
puts a contract's deployer / lock flag / runtime into the exec root as a META leaf, carries the four CODE EVENTS
(deploy / upgrade / lock / transfer_contract) in the DA calls binding, makes the settlement verifier DERIVE the
code- and meta-leaf updates those events cause, and stamps every call with chain_clock(h) so a TIME-reading call
proves what the chain applied.

The gate (EXEC_ROOT_V2_HEIGHT, with EXEC_CTX_CURRENT_HEIGHT for the call context) was 2^62 on gen 25 and 1 from gen
26; both were deleted after the betanet-8 reroll, so the rules below hold from block 1 and only height 0 — the exec
state before and at genesis — still has the v1 layout. Properties:
  * the empty root still equals EXEC_GENESIS_ROOT (a fresh state is at cursor -1, v1 layout);
  * the KV half commits deployer, lock flag and runtime — changing any one moves the root (C5);
  * block_calls carries the code events in tx order with the chain clock; at block 0 calls only;
  * exec_state_bind.apply_event reaches the same records as ExecState.apply_blob for the same blobs (the mirror
    the verifier's derivation rests on), including every refusal;
  * a TIME-reading call reads the block's own chain clock;
  * a reverting constructor deploys with empty storage on chain.
(The Goldilocks settle-proof halves — a span proving to the chain root, its forgeries, a TIME call proving, a reverting
constructor being unprovable — retired in G9 with settlement_sparse / settlement_proofs; gen 29 settles by quorum and
the C5 meta leaf is pinned on the live BLAKE2s root, execnode/exec_root_b2.py.)

Run: NADO_ALLOW_PYTHON_KERNELS=1 python3 tests/test_exec_root_v2.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-exec-root-v2-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")   # ASSIGN: the exec state path is CWD-relative, so a test run from the live checkout reads the live exec files
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")   # ASSIGN: CWD-relative too, and a generation mismatch rmtree()s it on import
os.environ.setdefault("NADO_ALLOW_PYTHON_KERNELS", "1")
import sys, copy, asyncio, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol
from execnode import exec_root as ER, exec_root_b2 as R2, csmt, zkvm, zkvmasm
from execnode.code_codec import contract_id, FIXED_CIDS
from execnode.state import ExecState
from execnode.stark import exec_state_bind as ESB, calls_commit as CC, field as F

import _harness
_report = _harness.Report()
check = _report.run


NQ, DEPTH, H = 8, 16, 300_000          # any height >= 1 runs the same rules since the gen-25 gates were deleted
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
def t_the_gate_is_gone_and_only_genesis_keeps_the_v1_layout():
    assert not hasattr(protocol, "EXEC_ROOT_V2_HEIGHT") and not hasattr(protocol, "EXEC_CTX_CURRENT_HEIGHT")
    assert ESB.root_v2(1) and ESB.root_v2(10 ** 9) and not ESB.root_v2(0) and not ESB.root_v2(-1), \
        "v2 from block 1; the state before and at genesis keeps the v1 layout"
    from protocol import EXEC_GENESIS_ROOT
    assert ER.state_root_hex({}, ExecState(os.path.join(os.environ["HOME"], "e.json"))) == EXEC_GENESIS_ROOT
    contracts = {"c" * 32: {"code": BUMP1, "storage": {"slots": {"0": 5}}, "deployer": ALICE, "runtime": "zkvm"}}
    plain = ER.kv_projection(contracts)
    assert ER.kv_projection(contracts, v2=False) == plain and ESB.meta_key("c" * 32, ER.DEPTH) not in plain
    # (the settlement_sparse v1-projection assert retired in G9: the Goldilocks settle-proof pin was deleted)
    blk = _block(0, [_tx(ALICE, {"op": "deploy", "code": BUMP1}, "t1"),
                     _tx(ALICE, {"op": "call", "contract": "x", "method": "m", "args": []}, "t2")])
    calls = CC.block_calls(blk)
    assert [c.get("op") for c in calls] == [None] and calls[0]["timestamp"] == 0, "block 0: calls only, ts 0"


def _kv_root(contracts):
    """the KV half of the live (gen-29, BLAKE2s) exec root"""
    return csmt.root_of(R2.kv_projection(contracts))


def t_meta_leaf_commits_deployer_lock_and_runtime():
    cid = "c" * 32
    base = {cid: {"code": BUMP1, "storage": {"slots": {}}, "deployer": ALICE, "runtime": "zkvm", "upgradable": True}}
    p = ER.kv_projection(base, v2=True)
    assert ESB.meta_key(cid, ER.DEPTH) in p and p[ESB.meta_key(cid, ER.DEPTH)] != 0
    # the live root carries the same meta leaf (C5 holds on the BLAKE2s root generation 29 settles)
    assert R2.meta_key(cid) in R2.kv_projection(base)
    roots = set()
    for mut in ({}, {"deployer": BOB}, {"upgradable": False}, {"runtime": "other"}):
        c = copy.deepcopy(base); c[cid].update(mut)
        roots.add(_kv_root(c))
    assert len(roots) == 4, "deployer, lock flag and runtime must each move the root"
    # (the settlement_sparse-pin-agrees-with-the-KV-half assert retired in G9: the Goldilocks settle-proof pin was deleted)
    # a legacy record with no flags commits the exec layer's defaults (upgradable, zkvm)
    legacy = {cid: {"code": BUMP1, "storage": {"slots": {}}, "deployer": ALICE, "runtime": "zkvm"}}
    assert _kv_root(legacy) == _kv_root(base)


def t_block_calls_carries_code_events():
    import base64, json, zstandard
    codez = base64.b64encode(zstandard.ZstdCompressor().compress(json.dumps(BUMP2).encode())).decode()
    txs = [_tx(ALICE, {"op": "deploy", "code": BUMP1, "nonce": "n1"}, "t1"),
           _tx(ALICE, {"op": "call", "contract": "x", "method": "m", "args": []}, "t2"),
           _tx(ALICE, {"op": "upgrade", "contract": "x", "codez": codez}, "t3"),
           _tx(ALICE, {"op": "lock", "contract": "x"}, "t4"),
           _tx(ALICE, {"op": "transfer_contract", "contract": "x", "to": BOB}, "t5"),
           _tx(ALICE, {"op": "emit", "to_ns": "y"}, "t6"),
           _tx(ALICE, {"op": "deploy", "code": {"m": "not-a-list"}, "at": {"weird": 1}, "upgradable": "no"}, "t7")]
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
    assert [c.get("op") for c in CC.block_calls(_block(0, txs))] == [None], "block 0 (genesis, below the deleted gate): calls only"


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
    assert _kv_root(st.contracts) == _kv_root(
        {cid: dict(c, storage=st.contracts[cid]["storage"]) for cid, c in mirror.items()})


# span_with_code_events_proves_to_the_chain_root retired in G9: settlement_sparse.prove/verify_bound_epoch were deleted


def t_time_reading_call_reads_the_blocks_own_clock():
    cid = contract_id(ALICE, TIMER, "n1")
    pre_txs = [_tx(ALICE, {"op": "deploy", "code": TIMER, "nonce": "n1"}, "p1")]
    span_txs = [_tx(BOB, {"op": "call", "contract": cid, "method": "stamp", "args": []}, "s1")]
    # (gen 25 handed the VM the PREVIOUS block's clock below the gate; that half went with the gate)
    st = _chain([_block(H - 1, pre_txs)])
    _chain([_block(H, span_txs)], st)
    assert st.contracts[cid]["storage"]["slots"]["1"] == protocol.chain_clock(H) % F.P, "F3: the block's own clock"
    # the DA binding stamps the same clock on the call, so whatever proves the span reads what the chain applied
    assert CC.block_calls(_block(H, span_txs))[0]["timestamp"] == protocol.chain_clock(H)
    # (the settlement_sparse prove/verify of this span retired in G9: the Goldilocks settle proof was deleted)


def t_reverting_constructor_deploys_with_empty_storage():
    cid = contract_id(ALICE, REVERT_CTOR, "n1")
    span_txs = [_tx(ALICE, {"op": "deploy", "code": REVERT_CTOR, "nonce": "n1"}, "s1")]
    st = _chain([_block(H, span_txs)])
    assert cid in st.contracts and not st.contracts[cid]["storage"].get("slots"), "chain: deployed, empty storage"
    # (the "unprovable, never mis-proven" half retired in G9: settlement_proofs.first_unprovable_call was deleted)


def t_faucet_seed_is_off():
    owner = FIXED_CIDS["faucet"]
    defund = {"defund": zkvmasm.assemble("movi r0 1\n ret r0")}
    # (the gen-25 seed below the gate went with the gate: it can only run at height 0, which carries no blobs)
    st = _chain([_block(H - 1, [_tx(owner, {"op": "deploy", "code": BUMP1, "at": "faucet"}, "p1")])])
    st.bridge["faucet"] = 777
    _chain([_block(H, [_tx(owner, {"op": "upgrade", "contract": "faucet", "code": defund}, "s1")])], st)
    slot7 = st.contracts["faucet"]["storage"].get("slots", {}).get("7")
    assert slot7 is None, f"slot 7 = {slot7}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_"):
            check(name[2:].replace("_", " "), fn)
    print("ALL PASS" if not _report.fails else f"{_report.fails} FAILURES")
    sys.exit(1 if _report.fails else 0)
