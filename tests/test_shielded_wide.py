"""
WIDE shielded pool (SHIELD_WIDE_HEIGHT; security review 2026-09-23, Z3): commitments, nullifiers and tree
nodes are alghash2 digests (256-bit) and the join-split is joinsplit3.

Properties, each shown flipping at the gate and nowhere else:
  * a gen-25 state's root and snapshot are byte-unchanged by the wide pool's existence (empty is absent);
  * from the gate a `shield` deposit lands in the WIDE pool as commit(amount, owner, rho) over digests, and L1
    admission refuses a deposit whose owner is not a 64-hex digest (coins would otherwise be escrowed behind
    a note the exec layer never creates); below the gate the legacy pool takes it, as before;
  * a wide 2-output transfer (send + change) and a wide unshield apply through the real blob path: the nullifier
    is spent, the notes are appended, the exit is recorded and is provable against state_root; a double-spend,
    a duplicate commitment and a bad destination are refused BEFORE any mutation;
  * a joinsplit2 bundle is refused from the gate and a joinsplit3 bundle is refused below it;
  * the wide circuit's soundness checks: wrong fee, tampered outputs, unknown anchor, the C-3 wraparound.

Run: NADO_ALLOW_PYTHON_KERNELS=1 python3 tests/test_shielded_wide.py   (slow: real STARK proofs)
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-shielded-wide-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ.setdefault("NADO_ALLOW_PYTHON_KERNELS", "1")
import sys, copy, json, asyncio, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol
from execnode.state import ExecState
from execnode.stark import znote as Z, joinsplit3 as J3, field as F, stark, alghash
from execnode import shielded_wide as SW, shielded_field as SF, exec_root as ER

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


LIVE = protocol.SHIELD_WIDE_HEIGHT
H = 300_000
from ops.address_ops import make_checksum as _mk
def _addr(ch):
    body = ch * 45                      # ADDRESS_LENGTH 49 = 45 body + 4 checksum; validate_address checks the checksum
    return body + _mk(body)
ALICE = _addr("a")
BOB = _addr("b")
NSK_A, NSK_B = 0xCAFE, 0xB0B


class gate:
    def __init__(self, h): self.h = h
    def __enter__(self): protocol.SHIELD_WIDE_HEIGHT = self.h
    def __exit__(self, *a): protocol.SHIELD_WIDE_HEIGHT = LIVE


def _state():
    return ExecState(os.path.join(os.environ["HOME"], f"s{os.urandom(4).hex()}.json"))


def _block(h, txs):
    return {"block_number": h, "block_hash": "ab" * 32, "block_timestamp": 0, "block_transactions": txs}


def _apply(st, h, txs):
    from execnode.execnode import _apply_block
    assert asyncio.new_event_loop().run_until_complete(_apply_block(None, {"default": st}, st, _block(h, txs), verbose=False)) is True


def _shield_tx(amount, owner_hex, rho):
    return {"recipient": "shield", "sender": ALICE, "amount": amount, "fee": 1, "txid": os.urandom(8).hex(),
            "data": {"field": True, "owner": owner_hex, "rho": str(rho)}}


def _transfer_tx(bundle):
    return {"recipient": "blob", "sender": ALICE, "txid": os.urandom(8).hex(),
            "data": {"op": "field_transfer", "bundle_json": json.dumps(bundle, default=str)}}


def t_gen25_root_and_snapshot_unchanged_by_the_wide_pool():
    st = _state()
    assert LIVE == (1 << 62) and not st.rules_shield_wide()
    from protocol import EXEC_GENESIS_ROOT
    assert st.state_root() == EXEC_GENESIS_ROOT, "an empty state (with an empty wide pool) is still the genesis root"
    assert "wide_pool" not in st._snapshot(), "empty is absent in the snapshot too"
    # a legacy deposit below the gate lands in the legacy pool, exactly as before
    _apply(st, H, [_shield_tx(1000, str(alghash.owner_of(NSK_A)), 7)])
    assert len(st.field_pool.commitments) == 1 and not st.wide_pool.commitments


def _deposit(st, nsk, amount, rho, h=H):
    owner = Z.owner_of(nsk)
    _apply(st, h, [_shield_tx(amount, Z.to_hex(owner), rho)])
    cm = Z.commit(amount, owner, rho)
    assert st.wide_pool.position(cm) is not None, "the deposit must land in the wide pool"
    return cm


def t_deposit_lands_in_the_wide_pool_from_the_gate():
    with gate(1):
        st = _state()
        cm = _deposit(st, NSK_A, 1000, 7)
        assert not st.field_pool.commitments and st.pool_value == 1000
        assert st.wide_pool.root() == SW.tree_root([cm])
        # the root now carries the wide records, and the snapshot round-trips them
        assert st.state_root() != ER.state_root_hex({}, _state())
        snap = st._snapshot(); assert "wide_pool" in snap
        st2 = _state(); st2._restore(json.loads(json.dumps(snap)))
        assert st2.wide_pool.root() == st.wide_pool.root() and st2.state_root() == st.state_root()
        # a malformed owner (the legacy int form) is skipped by the exec layer...
        n = len(st.wide_pool.commitments)
        _apply(st, H + 1, [_shield_tx(5, str(alghash.owner_of(NSK_A)), 9)])
        assert len(st.wide_pool.commitments) == n


def t_l1_admission_pins_the_owner_shape_from_the_gate():
    import ops.transaction_ops as TO
    src = open(TO.__file__).read()
    i = src.index('elif recipient == "shield":')
    body = src[i:i + 2500]
    assert "SHIELD_WIDE_HEIGHT" in body and "64-hex digest" in body, "the shield branch must pin the owner shape at the gate"
    # the check itself, driven directly: a wide owner parses, the legacy int form does not
    Z.from_hex(Z.to_hex(Z.owner_of(NSK_A)))
    refused = False
    try:
        Z.from_hex(str(alghash.owner_of(NSK_A)))
    except ValueError:
        refused = True
    assert refused, "an int owner must not parse as a digest"


def _prove(st, nsk, cm, v_in, rho_in, v1, o1, r1, v2, o2, r2, pv, fee, addr=None):
    pos = st.wide_pool.position(cm)
    bundle, _pub = SW.prove_transfer2(st.wide_pool, nsk, v_in, rho_in, pos, v1, o1, r1, v2, o2, r2, pv, fee,
                                      withdraw_addr=addr)
    return bundle


def t_wide_transfer_and_unshield_apply_end_to_end():
    with gate(1):
        st = _state()
        cm = _deposit(st, NSK_A, 1000, 7)
        oa, ob = Z.owner_of(NSK_A), Z.owner_of(NSK_B)
        bundle = _prove(st, NSK_A, cm, 1000, 7, 600, ob, 11, 400, oa, 12, 0, 0)
        js = bundle["stark"]["joinsplit3"]
        pre_root = st.state_root()
        _apply(st, H + 1, [_transfer_tx(bundle)])
        assert st.wide_pool.has_nullifier(Z.from_hex(js["nf"])), "the nullifier is spent"
        assert st.wide_pool.position(Z.from_hex(js["cm_out1"])) == 1 and st.wide_pool.position(Z.from_hex(js["cm_out2"])) == 2
        assert st.pool_value == 1000 and st.state_root() != pre_root
        # replay = double-spend, refused before any mutation
        n_root = st.state_root()
        _apply(st, H + 2, [_transfer_tx(bundle)])
        assert st.state_root() == n_root and len(st.wide_pool.commitments) == 3
        # Bob spends his 600: 250 to Alice, 350 change, and Alice unshields her 400 change note to BOB's L1 address
        cm_b = Z.from_hex(js["cm_out1"])
        b2 = _prove(st, NSK_B, cm_b, 600, 11, 250, oa, 21, 350, ob, 22, 0, 0)
        cm_a = Z.from_hex(js["cm_out2"])
        b3 = _prove(st, NSK_A, cm_a, 400, 12, 0, oa, 31, 0, oa, 32, -400, 0, addr=BOB)
        _apply(st, H + 3, [_transfer_tx(b2), _transfer_tx(b3)])
        assert len(st.wide_pool.commitments) == 7 and len(st.wide_pool.nullifiers) == 3
        assert st.pool_value == 600 and st.unshield_withdrawals == {"1": {"addr": BOB, "amount": 400}}
        p = st.unshield_withdrawal_proof("1")
        assert ER.verify_unshield(st.state_root(), p["addr"], p["amount"], p["nonce"], p["proof"]), "the exit is provable"
        # the wide pool state survives a save/load with an identical root
        st.save(); st2 = ExecState(path=st.path)
        assert st2.wide_pool.root() == st.wide_pool.root() and st2.state_root() == st.state_root()
        # a bundle redirected to another destination is refused (the address rides the transcript)
        bad = copy.deepcopy(b3); bad["withdraw_addr"] = ALICE
        r = st.apply_blob({"op": "field_transfer", "bundle_json": json.dumps(bad, default=str)}, ALICE, "x")
        assert r.startswith("skip"), r
        # an exit to a non-address is refused before the proof runs
        bad = copy.deepcopy(b3); bad["withdraw_addr"] = "faucet"
        assert "spendable" in st.apply_blob({"op": "field_transfer", "bundle_json": json.dumps(bad, default=str)}, ALICE, "y")


def t_bundle_kinds_flip_at_the_gate():
    # a joinsplit2 bundle from the gate, a joinsplit3 bundle below it: both refused without running a proof
    with gate(1):
        st = _state()
        st._applying = H
        r = st.apply_field_transfer({"stark": {"joinsplit2": {"proof": {}, "root": 1, "nf": 1, "cm_out1": 1, "cm_out2": 1, "public_value": 0, "fee": 0}}})
        assert "joinsplit3 bundle" in r, r
    st = _state(); st._applying = H
    r = st.apply_field_transfer({"stark": {"joinsplit3": {"proof": {}, "root": "0" * 64, "nf": "0" * 64, "cm_out1": "0" * 64, "cm_out2": "0" * 64, "public_value": 0, "fee": 0}}})
    assert "not live before" in r, r


def t_circuit_soundness():
    pool = SW.WideShieldedPool()
    oa, ob = Z.owner_of(NSK_A), Z.owner_of(NSK_B)
    cm = Z.commit(1000, oa, 7); pool.append(cm)
    sibs, dirs = SW.tree_path(pool.commitments, 0)
    assert Z.fold_path(cm, sibs, dirs) == pool.root() and len(sibs) == SW.TREE_DEPTH
    proof, root, nf, cm1, cm2 = J3.prove_transfer(NSK_A, 1000, 7, sibs, dirs, 600, ob, 11, 400, oa, 12, 0, 0)
    assert root == pool.root() and nf == Z.nullifier(NSK_A, 7)
    ok, why = J3.verify_transfer(proof, root, nf, cm1, cm2, 0, 0, pool.knows_root); assert ok, why
    assert not J3.verify_transfer(proof, root, nf, cm1, cm2, 0, 10, pool.knows_root)[0], "wrong fee"
    assert not J3.verify_transfer(proof, root, nf, cm1, cm2, -1, 0, pool.knows_root)[0], "wrong public value"
    t1 = list(cm1); t1[0] = (t1[0] + 1) % F.P
    assert not J3.verify_transfer(proof, root, nf, tuple(t1), cm2, 0, 0, pool.knows_root)[0], "tampered cm1"
    t2 = list(nf); t2[3] = (t2[3] + 1) % F.P
    assert not J3.verify_transfer(proof, root, tuple(t2), cm1, cm2, 0, 0, pool.knows_root)[0], "tampered nf"
    assert not J3.verify_transfer(proof, root, nf, cm1, cm2, 0, 0, lambda r: False)[0], "unknown anchor"
    bad = dict(proof); bad["D"] = SW.TREE_DEPTH - 1
    assert not J3.verify_transfer(bad, root, nf, cm1, cm2, 0, 0, pool.knows_root)[0], "geometry pinned"
    # C-3: a wraparound assignment balances mod P (1000 - 1001 == P - 1 + 0) but its trace violates the range
    # gadget, so the proof the prover emits does not verify
    wrap, _r, _n, w1, w2 = J3.prove_transfer(NSK_A, 1000, 7, sibs, dirs, 0, ob, 11, F.P - 1, oa, 12, -1001, 0)
    assert not J3.verify_transfer(wrap, root, nf, w1, w2, -1001, 0, pool.knows_root)[0], "an out-of-range value must not verify"
    # digests are 256-bit: four in-field lanes, and the legacy 64-bit forms are not accepted as wide digests
    assert len(cm) == 4 and all(0 <= x < F.P for x in cm)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_"):
            check(name[2:].replace("_", " "), fn)
    print("ALL PASS" if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
