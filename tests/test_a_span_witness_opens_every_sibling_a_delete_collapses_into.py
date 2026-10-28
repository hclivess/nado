"""A settlement witness opens every subtree a delete collapses into, so the verifier lands on the tree's true post root
(execnode/settle_b2.span_post_root, the one construction prove_span and verify_span share).

WHY (2026-10-28). The G8 shadow run refused its own proof of span 8160 -> 8220: "a delete needs a sibling opened (leaf or
node) that the witness does not open". The prover built its partial tree from the proofs of EVERY key the span touched,
the verifier only from the CHANGED keys'. A read-only key's proof revealed a subtree, a delete collapsed into it with no
opening needed on the prover's side, so none was recorded; the verifier, which never merges that proof, met the same
subtree opaque and refused. Both now call span_post_root, built from the changed keys only.
Pins, on random csmt trees (sparse keys, deep shared prefixes) and random batches of deletes, updates and inserts:
  1. the prover's span_post_root equals csmt's own post root, and the verifier's span_post_root, given only the changed
     keys' proofs and the prover's openings, lands on the same root — on every batch;
  2. the OLD construction (the prover also merging read-only keys' proofs) leaves the verifier short of an opening on
     some batch: this file reproduces the bug it guards;
  3. both prove_span and verify_span reach their tree halves through span_post_root, and nothing else in settle_b2
     builds a PartialTree.

Run: python3 tests/test_a_span_witness_opens_every_sibling_a_delete_collapses_into.py
"""
import _harness
HOME = _harness.isolate("nado-test-span-witness-opens-")
import os
import random
import re

from execnode import csmt, settle_b2 as S
from execnode.csmt_partial import Missing, PartialTree, opener_for

T = _harness.Report()
rnd = random.Random(20261028)


def key(prefix_bits, rest):
    """A 32-byte key whose first bits are `prefix_bits` (a '0'/'1' string): clusters keys so subtrees are deep."""
    n = int(prefix_bits + format(rest, "0%db" % (256 - len(prefix_bits))), 2) if prefix_bits else rest
    return n.to_bytes(32, "big")


def random_tree():
    items = {}
    for _ in range(rnd.randint(4, 40)):
        pre = "".join(rnd.choice("01") for _ in range(rnd.randint(0, 12)))
        items[key(pre, rnd.getrandbits(256 - len(pre)))] = rnd.getrandbits(64).to_bytes(8, "big")
    return items


def verifier_root(pre_root, tree, changes, opens):
    return S.span_post_root(pre_root, changes, lambda k: (tree.get(k), tree.prove(k)), opens=opens)[0]


ok_all, batches, old_fails = True, 0, 0
for _ in range(600):
    items = random_tree()
    t = csmt.Tree(items)
    keys = sorted(items)
    dels = rnd.sample(keys, rnd.randint(1, max(1, len(keys) // 3)))
    changes = {k: None for k in dels}
    for k in rnd.sample(keys, min(len(keys), rnd.randint(0, 3))):
        if k not in changes:
            changes[k] = b"upd" + rnd.getrandbits(32).to_bytes(4, "big")
    for _ in range(rnd.randint(0, 3)):
        changes[key("", rnd.getrandbits(256))] = b"new"
    reads = [k for k in keys if k not in changes]
    want = dict(items)
    for k, v in changes.items():
        if v is None:
            want.pop(k, None)
        else:
            want[k] = v
    truth = csmt.root_of(want)
    root, opens = S.span_post_root(t.root(), changes, lambda k: (t.get(k), t.prove(k)), on_open=opener_for(t))
    try:
        vroot = verifier_root(t.root(), t, changes, opens)
    except (Missing, ValueError) as e:
        vroot = f"refused: {e}"
    ok_all &= root == truth and vroot == truth
    batches += 1
    # the old prover: read-only keys' proofs merged too, openings recorded only for what it still had to open
    pt = PartialTree(t.root(), on_open=opener_for(t))
    for k in sorted(set(reads) | set(changes)):
        pt.add_proof(k, t.get(k), t.prove(k))
    pt.apply(changes)
    try:
        verifier_root(t.root(), t, changes, pt.opens)
    except Missing:
        old_fails += 1

T.check(f"1. on {batches} random batches the witness lands on csmt's post root, prover and verifier alike", ok_all)
T.check(f"2. the old construction leaves the verifier short of an opening ({old_fails} of {batches} batches)",
        old_fails > 0, old_fails)
src = open(os.path.join(_harness.ROOT, "execnode", "settle_b2.py")).read()
body = lambda name: src[src.index(f"def {name}("):src.index("\ndef ", src.index(f"def {name}(") + 5)]  # noqa: E731
T.check("3. prove_span and verify_span both build their halves through span_post_root, and nothing else builds a tree",
        "span_post_root(" in body("prove_span") and "span_post_root(" in body("verify_span")
        and len(re.findall(r"PartialTree\(", src)) == 1 and "PartialTree(" in body("span_post_root"))
T.done()
