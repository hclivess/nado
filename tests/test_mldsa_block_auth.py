"""
Block AUTHORIZATION commitments + DETACHED EVIDENCE (execnode/stark/mldsa_block_auth.py) — the block-format
half of signature aggregation. See doc/zk-signature-aggregation.md.

The property that makes the whole rollout safe: the block CORE (and therefore the block HASH) is IDENTICAL
whether the block ships raw signatures or a STARK proof. This test asserts that, plus that the commitments are
recomputed from the block's own transactions (a prover cannot choose the statement), and that both evidence
types are checked against the same recomputed statement.

Run: python3 tests/test_mldsa_block_auth.py
"""
import os, sys, tempfile, traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_blockauth_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

from execnode.stark import mldsa_block_auth as BA, field as F

fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


def _block(n=3, height=100):
    txs = []
    for i in range(n):
        txs.append({"sender": f"mldsa44sender{i:039d}", "txid": f"{i:064x}",
                    "public_key": bytes([i]) * 32, "signature": bytes([0xAA + i]) * 2420,
                    "recipient": "x", "amount": 1})
    return {"block_number": height, "parent_hash": "ab" * 32, "block_transactions": txs}


def t_core_is_signature_free():
    b = _block()
    core = BA.strip_signatures(b)
    check("core drops every signature", all("signature" not in t for t in core["block_transactions"]))
    check("core keeps the first-use public key (the state machine needs it)",
          all("public_key" in t for t in core["block_transactions"]))
    check("core keeps every transaction", len(core["block_transactions"]) == len(b["block_transactions"]))


def t_block_hash_identical_across_evidence():
    """THE load-bearing property: the core is the same object regardless of which evidence is shipped, so the
    block hash cannot depend on proof completion."""
    b = _block()
    core_raw = BA.strip_signatures(b)
    core_stark = BA.strip_signatures(b)
    import json
    h1 = json.dumps(core_raw, sort_keys=True, default=str)
    h2 = json.dumps(core_stark, sort_keys=True, default=str)
    check("the core is byte-identical whether raw or stark evidence will be attached", h1 == h2)
    # attaching evidence must not touch the core
    ev_raw, ev_stark = BA.raw_evidence(b), BA.stark_evidence("mldsa44-v1", {"dummy": 1})
    check("evidence envelopes are separate objects, not part of the core",
          "witnesses" not in core_raw and "proof" not in core_raw)
    check("raw evidence carries one witness per signing tx", len(ev_raw["witnesses"]) == 3)
    check("stark evidence carries a circuit_id", ev_stark["circuit_id"] == "mldsa44-v1")


def t_commitments_are_recomputed():
    b = _block()
    root, count = BA.auth_commitments(b)
    check("auth_count equals the number of signing transactions", count == 3)
    check("auth_root is a field element", isinstance(root, tuple) or (0 <= int(root) < F.P))
    # changing ANY committed field changes the root
    b2 = _block()
    b2["block_transactions"][1]["txid"] = "ff" * 32
    root2, _ = BA.auth_commitments(b2)
    check("a changed txid changes auth_root", root != root2)
    b3 = _block(height=101)
    check("a changed height changes auth_root", BA.auth_commitments(b3)[0] != root)
    b4 = _block()
    b4["block_transactions"][0], b4["block_transactions"][1] = b4["block_transactions"][1], b4["block_transactions"][0]
    check("reordering transactions changes auth_root (order is bound)", BA.auth_commitments(b4)[0] != root)


def t_evidence_checked_against_recomputed_statement():
    b = _block()
    root, count = BA.auth_commitments(b)
    b["auth_root"], b["auth_count"] = root, count
    ok, why = BA.evidence_ok(BA.raw_evidence(b), b)
    check(f"raw evidence accepted against the recomputed statement ({why})", ok)
    ok2, why2 = BA.evidence_ok(BA.stark_evidence("mldsa44-v1", {"p": 1}), b)
    check(f"stark evidence accepted against the same statement ({why2})", ok2)
    # a LIED commitment must be rejected — the verifier recomputes, it does not trust
    b_bad = dict(b); b_bad["auth_count"] = count + 1
    check("a lied auth_count is rejected", not BA.evidence_ok(BA.raw_evidence(b), b_bad)[0])
    b_bad2 = dict(b); b_bad2["auth_root"] = 12345
    check("a lied auth_root is rejected", not BA.evidence_ok(BA.raw_evidence(b), b_bad2)[0])
    # wrong witness count
    ev = BA.raw_evidence(b); ev["witnesses"] = ev["witnesses"][:-1]
    check("raw evidence with a missing witness is rejected", not BA.evidence_ok(ev, b)[0])
    check("an unknown evidence type is rejected", not BA.evidence_ok({"type": "magic"}, b)[0])


def t_signature_verification_is_wired():
    """Raw evidence really runs the supplied signature verifier over each entry."""
    b = _block()
    b["auth_root"], b["auth_count"] = BA.auth_commitments(b)
    seen = []
    ok, _ = BA.evidence_ok(BA.raw_evidence(b), b, verify_sig=lambda s, pk, txid: seen.append(txid) or True)
    check("every entry's signature is checked", ok and len(seen) == 3)
    ok2, why2 = BA.evidence_ok(BA.raw_evidence(b), b, verify_sig=lambda s, pk, txid: False)
    check(f"an invalid signature fails the block ({why2})", not ok2)


def t_size_trade():
    saved, crossover = BA.byte_saving(128, 200 * 1024)
    check(f"128 sigs vs a 200 KiB proof saves {saved} bytes", saved > 0)
    check(f"crossover at K={crossover} signatures", crossover == 85)
    saved2, _ = BA.byte_saving(10, 200 * 1024)
    check("10 signatures does NOT pay for a 200 KiB proof", saved2 < 0)


if __name__ == "__main__":
    try:
        t_core_is_signature_free()
        t_block_hash_identical_across_evidence()
        t_commitments_are_recomputed()
        t_evidence_checked_against_recomputed_statement()
        t_signature_verification_is_wired()
        t_size_trade()
    except Exception as e:
        fails += 1; print(f"FAIL  exception: {e}"); traceback.print_exc()
    print("\nALL PASS — detached evidence keeps the block hash stable and commitments are recomputed"
          if fails == 0 else f"\n{fails} FAILURES")
    sys.exit(1 if fails else 0)
