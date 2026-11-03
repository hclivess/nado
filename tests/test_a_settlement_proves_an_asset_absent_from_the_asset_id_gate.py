"""A Stwo settlement proves an asset ABSENT from protocol.EXEC_ASSET_ID_ROOT_HEIGHT (execnode/settle_b2.py FAMILIES
"assets", exec_root_b2.T_ASSET_ID), and the rule before the gate is unchanged.

An asset's T_ASSET_META record is positioned by its metadata digest, so "no asset has this id" named no leaf and every span
whose transition asked for a missing asset was unprovable: the shadow run measured four such spans on the live chain
(85500, 86040, 86220, 93240, 2026-11-03), each an ordinary asset read. From the gate every asset also commits its id alone.
  1. BELOW the gate (the old rules): an asset_create, and a transfer of an id nobody issued, are UNPROVABLE (never proven);
  2. FROM the gate: the same spans prove, and verify_span, holding no exec state, lands on exactly the exec node's root;
     the new asset's id record is inserted, the skipped transfer changes nothing;
  3. forgeries: an existing asset claimed absent is refused (from the gate: the tree disagrees; below it: no leaf can
     show absence), and the id leaf's insert cannot be left out (a post root without it is not the replay's);
  4. the root commits every asset's id exactly from the gate: none at gate - 1, one per asset at the gate, nothing else
     changed;
  5. a span crossing the gate is unprovable (prover) and refused (verifier): its first root inserts every id record;
  6. an exec node that mutates nothing at the gate still moves its memoised root there (block_apply.close's touch).
No toolchain: these spans run no contract call, so no VM proof is made or checked.
Run: python3 tests/test_a_settlement_proves_an_asset_absent_from_the_asset_id_gate.py
"""
import os
import _harness
HOME = _harness.isolate("nado-test-asset-id-gate-")
os.environ["NADO_EXEC_STATE"] = os.path.join(HOME, "exec_state")
os.environ["NADO_EXEC_DA"] = os.path.join(HOME, "exec_da")
import copy

from execnode import block_apply, exec_root_b2 as B2, settle_b2 as S
from execnode.state import ExecState, asset_id
from protocol import EPOCH_LENGTH

T = _harness.Report()
A = "ndo" + "A" * 45
B = "ndo" + "B" * 45
OFF = 1 << 62


class World:
    """an exec state driven by L1-shaped blocks (the shape tests/test_a_stwo_settlement_of_a_span_... uses)"""

    def __init__(self, h0):
        self.st = ExecState(os.path.join(HOME, "st%d.json" % h0))
        self.st.cursor = self.h = h0
        self.st.last_div_epoch = h0 // EPOCH_LENGTH - 1
        self.n = 0

    def blob(self, who, payload):
        self.n += 1
        return {"recipient": "blob", "sender": who, "txid": "t%d" % self.n, "data": payload}

    def block(self, txs):
        self.h += 1
        return {"block_number": self.h, "block_hash": "%064x" % (0xa55e7000 + self.h), "block_transactions": txs}

    def apply(self, blocks, st):
        states = {"default": st}
        for b in blocks:
            h = b["block_number"]
            while st.last_div_epoch < h // EPOCH_LENGTH - 1:
                st.last_div_epoch += 1
                st.accrue_dividend_epoch(0, {}, epoch=st.last_div_epoch)
            block_apply.begin(states, h)
            block_apply.dispatch(states, st, b, {}, set(), verbose=False)
            block_apply.close(states, h, b["block_hash"])

    def chain(self):
        return S.Chain(lambda E: (0, {}), 0, lambda kind, key, h: None)


def world():
    """a cursor just past an epoch start, holding one asset (seed 1) created before the span"""
    w = World(7201)
    w.apply([w.block([{"recipient": "bridge", "sender": A, "amount": 10**6},
                      w.blob(A, {"op": "asset_create", "seed": 1, "name": "Old", "sym": "OLD", "dec": 0, "supply": 50})])],
            w.st)
    return w


def create(w, seed=9):
    return [w.block([w.blob(A, {"op": "asset_create", "seed": seed, "name": "N", "sym": "N", "dec": 0, "supply": 5})])]


def stranger(w):
    """a transfer of an asset id nobody issued (the transition skips it after asking whether the asset exists)"""
    return [w.block([w.blob(A, {"op": "asset_transfer", "asset": str(asset_id(B, 77)), "to": B, "amount": 1})])]


def prove_and_verify(w, mk):
    pre = w.st.clone()
    blocks = mk(w)
    real = pre.clone()
    w.apply(blocks, real)
    bundle = S.prove_span(pre, blocks, w.chain(), None)
    pre_root = B2.state_root_hex(pre.contracts, pre)
    ok, why, post = S.verify_span(pre.cursor, pre_root, blocks, w.chain(), bundle, None)
    return pre, blocks, real, bundle, pre_root, (ok, why, post)


def asset_openings(b):
    return [o for o in b["openings"] if o[0] == "assets"]


# ---- 1: below the gate, the old rule: a missing asset is unprovable ---------------------------------------------------------
with _harness.pinned(EXEC_ASSET_ID_ROOT_HEIGHT=OFF):
    for name, mk in (("an asset_create", create), ("a transfer of an id nobody issued", stranger)):
        w = world()
        try:
            prove_and_verify(w, mk)
            T.check(f"1. below the gate {name} is unprovable", False, "it proved")
        except S.Unprovable as e:
            T.check(f"1. below the gate {name} is unprovable", "absence is not provable" in str(e), str(e))

# ---- 2: from the gate the same spans prove and land on the exec node's root ---------------------------------------------------
w = world()
G = w.st.cursor                                          # the gate AT the span's start: its pre root commits the ids
with _harness.pinned(EXEC_ASSET_ID_ROOT_HEIGHT=G):
    pre, blocks, real, bundle, pre_root, (ok, why, post) = prove_and_verify(w, create)
    new_aid = str(asset_id(A, 9))
    k_new = B2.record_key(B2.T_ASSET_ID, new_aid)
    T.check("2a. from the gate an asset_create proves and verifies on exactly the exec node's root, opening the new id "
            "as absent", ok and post == real.state_root() and new_aid in real.assets
            and [o[1:] for o in asset_openings(bundle)] == [[[new_aid], None]], (why, asset_openings(bundle)))
    T.check("2b. ...and its root commits the new asset's id record", B2.records_projection(real).get(k_new) == B2.ONE
            and k_new not in B2.records_projection(pre))
    w2 = world()
    pre2, blocks2, real2, bundle2, pre_root2, (ok2, why2, post2) = prove_and_verify(w2, stranger)
    T.check("2c. a transfer of an id nobody issued proves (the skip) and lands on the exec node's root, which it leaves "
            "unchanged", ok2 and post2 == real2.state_root() == B2.state_root_hex(pre2.contracts, pre2), why2)

    # ---- 3: forgeries ------------------------------------------------------------------------------------------------------
    def edit(f, b=bundle, p=pre, bl=blocks, pr=pre_root):
        b = copy.deepcopy(b)
        f(b)
        return S.verify_span(p.cursor, pr, bl, w.chain(), b, None)
    w3 = world()
    old_aid = str(asset_id(A, 1))
    pre3, blocks3, real3, bundle3, pre_root3, (ok3, why3, _p3) = prove_and_verify(w3, lambda w: create(w, seed=1))
    T.check("3a. re-creating an existing asset proves as the skip it is, opening the existing record",
            ok3 and [o[1] for o in asset_openings(bundle3)] == [[old_aid]] and asset_openings(bundle3)[0][2] is not None,
            why3)
    r = edit(lambda b: asset_openings(b)[0].__setitem__(2, None), bundle3, pre3, blocks3, pre_root3)
    T.check("3b. refused: an existing asset claimed absent (its id leaf is in the tree)",
            not r[0] and "tree disagrees" in r[1], r[1])
    r = edit(lambda b: b.__setitem__("post_root", B2.state_root_hex(pre.contracts, pre)))
    T.check("3c. refused: a post root that leaves the new asset out", not r[0] and "post root" in r[1], r[1])
    r = edit(lambda b: b["proofs"]["rec"].pop(k_new.hex()))
    T.check("3d. refused: the id leaf's absence proof dropped", not r[0], r[1])
with _harness.pinned(EXEC_ASSET_ID_ROOT_HEIGHT=OFF):
    w3o = world()                                        # the same skip, proven under the old rules
    pre3o, blocks3o, _r, bundle3o, pre_root3o, (ok3o, why3o, _p) = prove_and_verify(w3o, lambda w: create(w, seed=1))
    r = edit(lambda b: asset_openings(b)[0].__setitem__(2, None), bundle3o, pre3o, blocks3o, pre_root3o)
    T.check("3e. below the gate an existing asset is still provable, and claiming it absent is refused: no leaf can "
            "show it", ok3o and not r[0] and "no leaf" in r[1], (why3o, r[1]))

# ---- 4: the root commits every id exactly from the gate ---------------------------------------------------------------------
st4 = real.clone()
with _harness.pinned(EXEC_ASSET_ID_ROOT_HEIGHT=st4.cursor + 1):
    below = B2.records_projection(st4)
with _harness.pinned(EXEC_ASSET_ID_ROOT_HEIGHT=st4.cursor):
    at = B2.records_projection(st4)
ids = {B2.record_key(B2.T_ASSET_ID, a) for a in st4.assets}
T.check("4. the root commits every asset's id exactly from the gate: none one block below, one per asset at it, "
        "nothing else changed", len(ids) == 2 and not ids & set(below) and all(at.get(k) == B2.ONE for k in ids)
        and {k: v for k, v in at.items() if k not in ids} == below, len(ids))

# ---- 5: a span crossing the gate ------------------------------------------------------------------------------------------
w5 = world()
pre5 = w5.st.clone()
blocks5 = create(w5) + [w5.block([]), w5.block([])]
with _harness.pinned(EXEC_ASSET_ID_ROOT_HEIGHT=pre5.cursor + 2):         # the gate falls inside the span
    try:
        S.prove_span(pre5, blocks5, w5.chain(), None)
        T.check("5a. a span that crosses the asset id gate is unprovable", False, "it proved")
    except S.Unprovable as e:
        T.check("5a. a span that crosses the asset id gate is unprovable", "EXEC_ASSET_ID_ROOT_HEIGHT" in str(e), str(e))
    r = S.verify_span(pre5.cursor, B2.state_root_hex(pre5.contracts, pre5), blocks5, w5.chain(),
                      {"v": 1, "cursor": pre5.cursor, "kv_pre": "00" * 32, "rec_pre": "00" * 32, "proofs": {}, "opens": {},
                       "openings": [], "runs": [], "post_root": ""}, None)
    T.check("5b. ...and the verifier refuses a bundle for it", not r[0], r[1])

# ---- 6: the memoised root moves at the gate --------------------------------------------------------------------------------
from unittest import mock  # noqa: E402
w6 = world()
g6 = w6.h + 1
with _harness.pinned(EXEC_ASSET_ID_ROOT_HEIGHT=g6):
    r_before = w6.st.state_root()
    w6.apply([w6.block([])], w6.st)
    warm, cold = w6.st.state_root(), B2.state_root_hex(w6.st.contracts, w6.st)
    w7 = world()
    w7.st.state_root()
    with mock.patch.object(B2, "projection_gate_at", lambda c: False):    # the touch removed
        w7.apply([w7.block([])], w7.st)
    stale = w7.st.state_root()
T.check("6. an exec node that mutates nothing at the gate still commits the ids there: its memoised root equals the cold "
        "projection (without block_apply.close's touch it keeps the previous cursor's root)",
        warm == cold != r_before and stale == r_before, (warm[:12], cold[:12], r_before[:12], stale[:12]))
with _harness.pinned(EXEC_ASSET_ID_ROOT_HEIGHT=5000, EXEC_CARRY_ROOT_HEIGHT=3000):
    T.check("6b. projection_gate_at names both root-shape gates and nothing between them",
            B2.projection_gate_at(5000) and B2.projection_gate_at(3000) and not B2.projection_gate_at(4000))
T.done()
