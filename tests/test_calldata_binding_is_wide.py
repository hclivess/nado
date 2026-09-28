"""THE SETTLE CALLDATA BINDING IS FOUR FIELD ELEMENTS FROM ZK_HARDEN_HEIGHT (audit 2026-09-24/25 HIGH, "settle
calldata binding is ONE field element").

A settle-with-proof binds the calls it proves to the calldata on L1 through calls_commitment: L1 folds the per-block
exec-summary leaves (calls_commit.verify_calls_bound_to_summaries) and the verifier recomputes the commitment from the
bundle's calls (settlement_sparse.verify_bound_epoch), and the two must be equal. Below the gate a leaf is
blake2b % P and the chain is the width-2 / capacity-1 alghash sponge, so the whole binding is ONE Goldilocks
element: a settler who lands call A and proves call B needs only a 64-bit collision (~2^32 work, the settler
controls both sides). From the gate the leaves are 256-bit and the chain is the 4-element alghash2 fold.

Pins, under BOTH rule sets (CLAUDE.md rule 11):
  * below the gate (gen 27 as shipped) leaves and commitments are byte-identical to the legacy formula, and the
    narrow binding still accepts the honest commitment — history replays;
  * from the gate the commitment is 4 canonical field elements, a leaf is the full 256-bit digest, and
    - a commitment agreeing with the honest one in element 0 only is refused (L1 and bundle side),
    - changing ANY one element is refused,
    - the narrow (one-element) commitment of the same calls is refused,
    - two calldata leaves agreeing in their first field element but not the rest do NOT bind to each other,
    - a segment straddling the gate is refused,
    - 256-bit leaves survive the exec-summary store (kv_ops) and fold to the prover's commitment;
  * an HONEST settle proof from the gate verifies end to end (non-recursive and per-block recursive segments):
    the exec proofs, the sparse transition, the DA binding — and the same proof with one element of its
    calls_commitment changed is refused by both.
Run: python3 tests/test_calldata_binding_is_wide.py
"""
import os, sys, tempfile, traceback, copy

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_cdwide_")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
from genesis import create_indexers
create_indexers()

import protocol
from hashing import blake2b_hash
from ops import kv_ops
from execnode import zkvmasm
from execnode.stark import settlement_sparse as SS, calls_commit as CC, alghash, field as F

fails = 0
def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        fails += 1

D, NQ, NS = 16, 2, "default"
CID = "c" * 32
ALICE = "ndoAAAA" + "A" * 41
COUNTER = {"bump": zkvmasm.assemble("movi r1 0\n sload r2 r1\n movi r3 1\n add r2 r3\n sstore r1 r2\n ret r2"),
           "add": zkvmasm.assemble("movi r1 0\n sload r2 r1\n add r2 r0\n sstore r1 r2\n ret r2")}
GATE = 1000
LIVE_GATE = protocol.ZK_HARDEN_HEIGHT          # gen 27's value (2^62): the narrow binding


def _pre():
    return {CID: {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}}


def _block(h, args=None, method="bump"):
    data = {"op": "call", "contract": CID, "method": method, "args": list(args or []), "ns": NS}
    return {"block_number": h, "block_hash": f"{h % 256:02x}" * 32,
            "block_transactions": [{"recipient": "blob", "sender": ALICE, "data": data}]}


def _summaries(*blocks):
    out = {}
    for b in blocks:
        inert, cbn = CC.block_summary(b)
        out[int(b["block_number"])] = {"inert": 1 if inert else 0, "calls": cbn}
    return out


def _legacy_leaf(call):
    """The pre-fix call_leaf formula, written out: blake2b of the canonical payload, % P — ONE element."""
    return int(blake2b_hash(_payload_of(call)), 16) % F.P


def _payload_of(call):
    """call_leaf's canonical payload, written out independently of the module under test."""
    return ["call", str(call.get("cid", "")), str(call.get("method", "")), str(call.get("caller", "epoch")),
            [CC._arg_field(a) for a in call.get("args", [])], int(call.get("value", 0)),
            int(call.get("cursor", 0)), int(call.get("timestamp", 0)), CC._asset_field(call.get("asset", 0))]


def _seg(cursor, cc):
    return {"segments": [{"cursor": cursor, "calls_commitment": cc}]}


def below_the_gate():
    protocol.ZK_HARDEN_HEIGHT = LIVE_GATE
    b = _block(500, args=[7], method="add")
    calls = CC.block_calls(b, NS)
    check("below the gate a call leaf is the legacy one-element formula (byte-identical)",
          CC.entry_leaf(calls[0]) == _legacy_leaf(calls[0]) and CC.entry_leaf(calls[0]) < F.P)
    legacy = alghash.merkle_node(alghash.IV, _legacy_leaf(calls[0]))
    cc = CC.calls_commitment(calls, cursor=500)
    check("below the gate calls_commitment is the legacy alghash fold (one int)", cc == legacy and isinstance(cc, int))
    sums = _summaries(b)
    ok, why = CC.verify_calls_bound_to_summaries(_seg(500, cc), NS, 499, 500, sums.get, 240)
    check(f"below the gate the narrow binding accepts the honest commitment ({why})", ok)
    ok, _ = CC.verify_calls_bound_to_summaries(_seg(500, (cc + 1) % F.P), NS, 499, 500, sums.get, 240)
    check("below the gate a different narrow commitment is still refused", not ok)
    check("below the gate the bundle check is the exact `!=` it was", CC.commitment_matches(cc, cc)
          and not CC.commitment_matches(cc + 1, cc))


def from_the_gate():
    protocol.ZK_HARDEN_HEIGHT = GATE
    b1, b2 = _block(GATE, args=[7], method="add"), _block(GATE + 1)
    calls = CC.block_calls(b1, NS) + CC.block_calls(b2, NS)
    lf = CC.entry_leaf(calls[0])
    check("from the gate a call leaf is the full 256-bit digest (not reduced % P)",
          lf == int(blake2b_hash(["wide", _payload_of(calls[0])]), 16) and lf != _legacy_leaf(calls[0]))
    ev = {"op": "deploy", "caller": ALICE, "cursor": GATE, "at": "x", "nonce": "n"}
    check("from the gate a code-event leaf (same chain) is 256-bit too",
          CC.event_leaf(ev) == CC.event_leaf(ev, wide=True) and CC.event_leaf(ev).bit_length() > 64
          and CC.event_leaf(dict(ev, cursor=GATE - 1)) < F.P)
    cc = CC.calls_commitment(calls, cursor=GATE + 1)
    check("from the gate the binding has >= 4 field elements", CC.WIDE >= 4 and CC.wide_commitment(cc) == cc
          and len(cc) == CC.WIDE, repr(cc))
    sums = _summaries(b1, b2)
    get = sums.get
    ok, why = CC.verify_calls_bound_to_summaries(_seg(GATE + 1, cc), NS, GATE - 1, GATE + 1, get, 240)
    check(f"from the gate the honest wide commitment binds to the summaries ({why})", ok)

    elem0_only = [cc[0]] + [(x + 1) % F.P for x in cc[1:]]
    ok, _ = CC.verify_calls_bound_to_summaries(_seg(GATE + 1, elem0_only), NS, GATE - 1, GATE + 1, get, 240)
    check("a commitment agreeing with the honest one in element 0 only is refused on L1", not ok)
    check("...and by the bundle-side check", not CC.commitment_matches(elem0_only, cc))
    for j in range(CC.WIDE):
        bad = list(cc); bad[j] = (bad[j] + 1) % F.P
        ok, _ = CC.verify_calls_bound_to_summaries(_seg(GATE + 1, bad), NS, GATE - 1, GATE + 1, get, 240)
        check(f"changing element {j} alone is refused", not ok and not CC.commitment_matches(bad, cc))
    narrow = CC.fold_leaves(alghash.IV, [_legacy_leaf(c) for c in calls])
    for form, v in (("the narrow one-element commitment", narrow), ("element 0 alone", cc[0]),
                    ("a 3-element prefix", cc[:3]), ("non-canonical (+P) elements", [x + F.P for x in cc]),
                    ("string elements", [str(x) for x in cc])):
        ok, _ = CC.verify_calls_bound_to_summaries(_seg(GATE + 1, v), NS, GATE - 1, GATE + 1, get, 240)
        check(f"from the gate {form} is refused", not ok and not CC.commitment_matches(v, cc))

    # TWO CALLDATA LEAVES AGREEING IN ELEMENT 0 ONLY. A 64-bit collision on real payloads costs ~2^32 hashes — too
    # slow for a test — so the collision is forced by structure: a leaf whose first field element (low 64-bit word)
    # equals the honest leaf's and whose other words differ. Under the narrow binding that is the WHOLE binding; here
    # the summary carrying it must not bind the honest commitment.
    forged_leaf = lf ^ (1 << 100) ^ (1 << 200)
    check("the forged leaf agrees with the honest one in field element 0",
          CC._leaf_limbs(forged_leaf)[0] == CC._leaf_limbs(lf)[0] and forged_leaf != lf)
    forged = copy.deepcopy(sums)
    forged[GATE]["calls"][NS][0] = forged_leaf
    ok, _ = CC.verify_calls_bound_to_summaries(_seg(GATE + 1, cc), NS, GATE - 1, GATE + 1, forged.get, 240)
    check("calldata agreeing in element 0 only does not bind to the honest commitment", not ok)
    check("...and folds to a different wide commitment",
          CC.fold_leaves(CC.chain_start(True), forged[GATE]["calls"][NS] + forged[GATE + 1]["calls"][NS]) != cc)

    # the straddle: blocks GATE-1 (narrow) and GATE (wide) in one segment
    b0 = _block(GATE - 1)
    s2 = _summaries(b0, b1)
    straddle = CC.calls_commitment(CC.block_calls(b0, NS) + CC.block_calls(b1, NS), cursor=GATE)
    ok, why = CC.verify_calls_bound_to_summaries(_seg(GATE, straddle), NS, GATE - 2, GATE, s2.get, 240)
    check(f"a segment straddling the gate is refused ({why})", not ok and "straddles" in why)
    ok, why = CC.verify_calls_bound_to_summaries(
        {"segments": [{"cursor": GATE - 1, "calls_commitment": CC.calls_commitment(CC.block_calls(b0, NS), GATE - 1)},
                      {"cursor": GATE, "calls_commitment": CC.calls_commitment(CC.block_calls(b1, NS), GATE)}]},
        NS, GATE - 2, GATE, s2.get, 240)
    check(f"...while segments split AT the gate bind, narrow then wide ({why})", ok)

    # the body-derived gate (verify_calls_bound_to_da) agrees with the summary gate
    ok, why = CC.verify_calls_bound_to_da(_seg(GATE + 1, cc), NS, GATE - 1, GATE + 1,
                                          {GATE: b1, GATE + 1: b2}.get)
    check(f"the body-derived DA gate binds the same wide commitment ({why})", ok)
    ok, _ = CC.verify_calls_bound_to_da(_seg(GATE + 1, elem0_only), NS, GATE - 1, GATE + 1,
                                        {GATE: b1, GATE + 1: b2}.get)
    check("...and refuses the element-0-only commitment", not ok)

    # 256-bit leaves through the real exec-summary store
    for h, blk in ((GATE, b1), (GATE + 1, b2)):
        inert, cbn = CC.block_summary(blk)
        kv_ops.exec_summary_put(h, inert, cbn)
    stored = kv_ops.exec_summary_get(GATE)
    check("a 256-bit leaf survives the exec-summary store unchanged", stored["calls"][NS][0] == lf)
    ok, why = CC.verify_calls_bound_to_summaries(_seg(GATE + 1, cc), NS, GATE - 1, GATE + 1,
                                                 kv_ops.exec_summary_get, 240)
    check(f"stored wide summaries fold to the prover's commitment ({why})", ok)


def honest_proof_end_to_end():
    protocol.ZK_HARDEN_HEIGHT = GATE
    b1, b2 = _block(GATE, args=[7], method="add"), _block(GATE + 1)
    span_calls = CC.block_calls(b1, NS) + CC.block_calls(b2, NS)
    sums = _summaries(b1, b2)
    for label, kw in (("non-recursive", {}), ("recursive per-block", {"recursive": True, "fold": False})):
        proof = SS.prove_settlement_sparse(_pre(), span_calls, cursor=GATE + 1, rec_hex="00" * 32,
                                           num_queries=NQ, depth=D, **kw)
        ccs = [s["calls_commitment"] for s in proof["segments"]]
        check(f"{label}: every segment carries a 4-element commitment",
              all(CC.wide_commitment(c) == c for c in ccs), repr(ccs))
        ok, why = CC.verify_calls_bound_to_summaries(proof, NS, GATE - 1, GATE + 1, sums.get, 240)
        check(f"{label}: the honest proof binds to the on-chain calldata ({why})", ok)
        ok, why, _pre_hex, _post_hex = SS.verify_settlement_sparse(proof, num_queries=NQ, depth=D)
        check(f"{label}: the honest proof verifies end to end ({why})", ok)
        bad = copy.deepcopy(proof)
        c = bad["segments"][-1]["calls_commitment"]
        c[3] = (c[3] + 1) % F.P
        ok, why, _a, _b = SS.verify_settlement_sparse(bad, num_queries=NQ, depth=D)
        check(f"{label}: one element of calls_commitment changed -> the bundle check refuses ({why})",
              not ok and "calls_commitment" in why)
        ok, _ = CC.verify_calls_bound_to_summaries(bad, NS, GATE - 1, GATE + 1, sums.get, 240)
        check(f"{label}: ...and the L1 DA binding refuses", not ok)


if __name__ == "__main__":
    try:
        below_the_gate()
        from_the_gate()
        honest_proof_end_to_end()
    except Exception as e:
        fails += 1; print(f"FAIL  exception: {e}"); traceback.print_exc()
    finally:
        protocol.ZK_HARDEN_HEIGHT = LIVE_GATE
    print("\nALL PASS — the settle calldata binding is four field elements from ZK_HARDEN_HEIGHT"
          if fails == 0 else f"\n{fails} FAILURES")
    sys.exit(1 if fails else 0)
