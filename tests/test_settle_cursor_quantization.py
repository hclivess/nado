"""Settle cursor quantization (2026-08-20): bare attestations must target the latest recorded
EPOCH-BOUNDARY (cursor, root) so independent settlers meet on identical pairs. Measured failure:
f58d attested 84585 and 7174 attested 84584 with the SAME root — one cursor apart, forever —
while share concentration (10/4/1) left every non-coinciding pair under the strict 2/3, freezing
the derived settled tip at 68299 with all roots agreeing."""
import os

_SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "execnode", "execnode.py")).read()
_MS = _SRC[_SRC.index("async def maybe_settle"):]
_Q = _MS[_MS.index("CURSOR QUANTIZATION"):]


def t1_bare_settles_quantize_to_boundary():
    seg = _Q[:1800]
    assert "if proof is None:" in seg, "quantization applies to BARE settles only"
    assert "st.boundary_roots" in seg and "max(_bcs)" in seg, \
        "the attested pair must come from the recorded epoch-boundary ring"
    assert "c <= cur" in seg, "never attest a boundary above the snapshot cursor"
    assert "cur, root = _bc, _br" in seg, "the tx must carry the boundary pair, not the live cursor"


def t2_already_attested_boundary_skipped():
    seg = _Q[:1800]
    k = seg.index("st.attested.get(_bc) == _br")
    assert "continue" in seg[k:k + 80], \
        "an already-attested boundary must be skipped, not re-submitted every tick"


def t3_proof_path_keeps_live_cursor():
    # the quantization block must be INSIDE the bare branch: the proof's span endpoints bind the
    # cursor, so a proof settle must never have its cursor rewritten.
    q = _MS.index("CURSOR QUANTIZATION")
    tx = _MS.index("tx = construct_settle_tx(keys, cur, root, target, ns=ns, proof=proof")
    assert q < tx, "quantization must run before the tx is constructed"
    assert "if proof is None:" in _MS[q:tx], "only the proof-less branch may rewrite (cur, root)"


if __name__ == "__main__":
    fails = 0
    for name in ("t1_bare_settles_quantize_to_boundary", "t2_already_attested_boundary_skipped",
                 "t3_proof_path_keeps_live_cursor"):
        try:
            globals()[name]()
            print(f"PASS  {name}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL  {name}: {e}")
    print("ALL PASS" if not fails else f"{fails} FAILURE(S)")
    raise SystemExit(1 if fails else 0)
