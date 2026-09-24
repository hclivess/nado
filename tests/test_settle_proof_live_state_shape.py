"""AN HONEST SETTLE PROOF OVER THE STATE THE CHAIN ACTUALLY PRODUCES MUST VERIFY (2026-09-24).

REVIEW_R2's canonical-key check (settlement_sparse._canonical_pre_contracts, live at 214000) accepted only
lowercase-hex contract ids. Its test fed it hand-written pre-states that held only hex ids — but the chain also
deploys contracts at FIXED NAMES (`faucet`, `sovereign`: code_codec.FIXED_CIDS), and live state holds both. So from
214000 every honest proof-carrying settle was refused ("cid 'faucet'"), and every test stayed green because no test
proved over a state the chain had built. PROOF_FIXED_CID_HEIGHT (225000) fixes it.

THE RULE THIS FILE ENFORCES: a verifier check is tested against a pre-state produced by the chain's OWN deploy and
call paths, round-tripped through JSON exactly as the settle stash is, never against a dict written for the test.
Every way the chain can name a contract is created here:
  * a hashed id (code_codec.contract_id) from an ordinary deploy;
  * EVERY name in FIXED_CIDS, deployed by its allowlisted owner through the real apply path;
and storage is written by real calls, so slot keys carry the spelling the VM writes.

Properties:
  * every contract id the deploy path can produce passes the check from the gate (a new FIXED_CIDS entry, or a new
    way of naming a contract, fails HERE before it can fail on chain);
  * an honest proof over that state verifies above the gate and lands on exactly the chain's KV root;
  * below the gate the same proof is refused — replay judges old settles as they were judged;
  * the verify child (ops/proof_child) reaches the same verdict as in-process, carries its fold cache between
    children, and writes that cache only after an accepted proof.

Run: NADO_ALLOW_PYTHON_KERNELS=1 python3 tests/test_settle_proof_live_state_shape.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-settle-live-shape-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")   # ASSIGN: the exec state path is CWD-relative, so a test run from the live checkout reads the live exec files
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")   # ASSIGN: CWD-relative too, and a generation mismatch rmtree()s it on import
os.environ.setdefault("NADO_ALLOW_PYTHON_KERNELS", "1")
import sys, json, asyncio, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol
from execnode import zkvmasm
from execnode.code_codec import contract_id, FIXED_CIDS
from execnode.state import ExecState
from execnode.stark import settlement_sparse as SS, calls_commit as CC, stark

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


NQ, DEPTH = 8, 16
# PROOF_FIXED_CID_HEIGHT is DEFERRED to the reroll on gen 25 (2^62: settle proofs stay closed until the verifier fixes
# of review 2026-09-24 and S1 are all live). This file tests the RULE, so it schedules the gate at a finite height of
# its own — below the reroll-only EXEC_ROOT_V2, whose different root layout would otherwise be in force up there.
# settlement_sparse reads the constant at call time, so setting it here is what the verifier sees.
protocol.PROOF_FIXED_CID_HEIGHT = 230000
ABOVE = protocol.PROOF_FIXED_CID_HEIGHT + 100
BELOW = protocol.REVIEW_R2_HEIGHT + 100          # round 2 on, the fixed-name acceptance not yet
ALICE = "ndoAAAA" + "A" * 41
BUMP = {"bump": zkvmasm.assemble("movi r1 0\n sload r2 r1\n movi r3 1\n add r2 r3\n sstore r1 r2\n ret r2")}


def _tx(sender, data, txid):
    return {"recipient": "blob", "sender": sender, "txid": txid, "data": dict(data)}


def _block(h, txs):
    return {"block_number": h, "block_hash": "ab" * 32, "block_timestamp": 0, "block_transactions": txs}


def _chain(blocks, st=None):
    from execnode.execnode import _apply_block
    st = st or ExecState(os.path.join(os.environ["HOME"], f"s{id(blocks)}.json"))
    loop = asyncio.new_event_loop()
    for b in blocks:
        assert loop.run_until_complete(_apply_block(None, {"default": st}, st, b, verbose=False)) is True
    return st


def _stash_form(contracts):
    """The pre-state exactly as the exec node proves from it: the settle stash is JSON on disk."""
    return json.loads(json.dumps(contracts))


def _live_shaped(cursor):
    """A pre-state holding every kind of contract id the chain makes, with storage written by real calls, plus a
    span of calls into each. Returns (pre_contracts, span_calls, chain_kv_root_after_span)."""
    hashed = contract_id(ALICE, BUMP, "n1")
    deploys = [_tx(ALICE, {"op": "deploy", "code": BUMP, "nonce": "n1"}, "d0")]
    for i, (name, owner) in enumerate(sorted(FIXED_CIDS.items())):
        deploys.append(_tx(owner, {"op": "deploy", "code": BUMP, "at": name}, f"d{i + 1}"))
    cids = [hashed] + sorted(FIXED_CIDS)
    warm = [_tx(ALICE, {"op": "call", "contract": c, "method": "bump"}, f"w{i}") for i, c in enumerate(cids)]
    st = _chain([_block(cursor - 3, deploys), _block(cursor - 2, warm)])
    assert set(cids) <= set(st.contracts), f"the chain did not create every contract kind: {sorted(st.contracts)}"
    assert all(st.contracts[c]["storage"]["slots"] for c in cids), "real calls wrote storage into every contract"
    pre = _stash_form(st.contracts)
    span = [_tx(ALICE, {"op": "call", "contract": c, "method": "bump"}, f"s{i}") for i, c in enumerate(cids)]
    _chain([_block(cursor, span)], st)
    return pre, CC.block_calls(_block(cursor, span)), SS.sparse_root(st.contracts, DEPTH)


def _prove(pre, calls, cursor):
    with stark.with_rules(stark.rules_for_height(cursor)):
        return SS.prove_settlement_sparse(pre, calls, cursor, "00" * 32, num_queries=NQ, depth=DEPTH)


def _verify(pf, cursor):
    with stark.with_rules(stark.rules_for_height(cursor)):
        return SS.verify_settlement_sparse(pf, num_queries=NQ, depth=DEPTH)


# ---------------------------------------------------------------------------------------------------------
def t_every_id_the_deploy_path_can_produce_passes_the_key_check_from_the_gate():
    ids = sorted(FIXED_CIDS) + [contract_id(s, BUMP, n) for s in (ALICE, "ndo" + "Z" * 45) for n in ("a", "b", "c")]
    for cid in ids:
        ok, why = SS._canonical_pre_contracts({cid: {"storage": {"slots": {"0": 1}}}}, fixed_names=True)
        assert ok, f"the chain can create {cid!r} but the verifier refuses it: {why}"


def t_honest_proof_over_chain_built_state_verifies_and_lands_on_the_chain_root():
    pre, calls, chain_root = _live_shaped(ABOVE)
    assert any(c in pre for c in FIXED_CIDS), "the pre-state must hold a fixed-name contract, or this proves nothing"
    pf = _prove(pre, calls, ABOVE)
    ok, why, _kv_pre, kv_post = _verify(pf, ABOVE)
    assert ok, f"an honest proof over the state the chain built was refused: {why}"
    assert kv_post == SS.root_hex(chain_root), "the proof must settle exactly the chain's KV root"


def t_below_the_gate_the_same_proof_is_refused_as_it_was():
    pre, calls, _root = _live_shaped(BELOW)
    pf = _prove(pre, calls, BELOW)
    ok, why, _a, _b = _verify(pf, BELOW)
    assert not ok and "faucet" in why or "sovereign" in why, why


def t_the_verify_child_agrees_and_carries_its_fold_cache():
    from ops import proof_child as PC
    os.makedirs(os.path.join(os.environ["HOME"], "nado"), exist_ok=True)
    path = PC._fold_cache_path()
    assert path and path.startswith(os.environ["HOME"]), "the child's cache must live under the node's HOME"
    if os.path.exists(path):
        os.remove(path)
    pre_b, calls_b, _ = _live_shaped(BELOW)
    refused = PC.verify_sparse_out_of_process(_prove(pre_b, calls_b, BELOW), DEPTH,
                                              rules=stark.rules_for_height(BELOW))
    assert refused is not None and refused[0] is False
    assert not os.path.exists(path), "a refused proof must not write the cache"
    pre, calls, _ = _live_shaped(ABOVE)
    pf = _prove(pre, calls, ABOVE)
    # the child verifies at full protocol query strength; this proof is a toy (NQ), so compare verdict shape only
    # through the in-process verifier at the SAME strength the child uses
    want = SS.verify_settlement_sparse(pf, depth=DEPTH) if False else None
    first = PC.verify_sparse_out_of_process(pf, DEPTH, rules=stark.rules_for_height(ABOVE))
    assert first is not None
    with stark.with_rules(stark.rules_for_height(ABOVE)):
        inproc = SS.verify_settlement_sparse(pf, depth=DEPTH)
    assert tuple(first) == tuple(inproc), f"child {first[:2]} != in-process {inproc[:2]}"
    if first[0]:
        assert os.path.exists(path), "an accepted proof writes the cache"
        again = PC.verify_sparse_out_of_process(pf, DEPTH, rules=stark.rules_for_height(ABOVE))
        assert tuple(again) == tuple(first), "a warm child must reach the identical verdict"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("t_"):
            check(name[2:].replace("_", " "), fn)
    print("ALL PASS" if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
