"""Every reserved recipient reaches exactly one validation rule, and every rule is reachable.

validate_transaction dispatches on the recipient through one `if recipient == ... elif ...` chain whose bodies are the
_validate_<kind> functions (consolidation stage 3, 2026-10-19: the 28 branches were MOVED VERBATIM out of a 1,227-line
function). A chain like that fails silently in two ways, and this test pins both:
  * a recipient listed twice — the second branch is dead code that looks like a live rule;
  * a new reserved recipient with no branch — it falls through to the plain-transfer `else` and is admitted under the
    fee floor alone. The four that do that today (bond, dividend, htlc, treasury: value sinks whose rules live in
    reflect_transaction, or bare names a lock tx pays INTO) are pinned here, so a fifth must be a decision, not a miss.
It also drives a few real transactions through the chain, so a dispatch that compiles but routes wrongly is caught.

Run: python3 tests/test_every_reserved_recipient_has_exactly_one_validation_rule.py
"""
import _harness
HOME = _harness.isolate("nado-test-reserved-recipient-rules-")
import ast
import os

T = _harness.Report()
SRC = open(os.path.join(_harness.ROOT, "ops", "transaction_ops.py")).read()
tree = ast.parse(SRC)
defs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
vt = defs["validate_transaction"]
chain = next(x for x in vt.body if isinstance(x, ast.If) and ast.unparse(x.test) == "recipient == 'slash'")

seen, rules, cur = [], [], chain
while isinstance(cur, ast.If):
    c = cur.test.comparators[0]
    seen += [c.value] if isinstance(c, ast.Constant) else [e.value for e in c.elts]
    body = cur.body
    rules.append(body[0].value.func.id if len(body) == 1 and isinstance(body[0], ast.Expr)
                 and isinstance(body[0].value, ast.Call) and isinstance(body[0].value.func, ast.Name) else None)
    cur = cur.orelse[0] if len(cur.orelse) == 1 and isinstance(cur.orelse[0], ast.If) else None

from protocol import RESERVED_RECIPIENTS
dupes = sorted({r for r in seen if seen.count(r) > 1})
T.check("no recipient appears in two branches of the chain", not dupes, dupes)
T.check("every branch is one call to its own _validate_<kind> rule", all(r and r.startswith("_validate_") for r in rules), rules)
T.check("no rule is shared by two branches", len(set(rules)) == len(rules), rules)
T.check("every rule the chain calls is defined in transaction_ops", all(r in defs for r in rules),
        [r for r in rules if r not in defs])
# _validate_<x>_fields are the shared field checks the duty rules call (attest/commit/reveal), not branch rules
stray = sorted(n for n in defs if n.startswith("_validate_") and not n.endswith("_fields") and n not in rules)
T.check("every _validate_<kind> rule is reached from the chain (none orphaned)", not stray, stray)
T.check("the chain names only reserved recipients", set(seen) <= set(RESERVED_RECIPIENTS), sorted(set(seen) - set(RESERVED_RECIPIENTS)))
T.check("the reserved recipients without a branch are exactly the four known value sinks",
        sorted(set(RESERVED_RECIPIENTS) - set(seen)) == ["bond", "dividend", "htlc", "treasury"],
        sorted(set(RESERVED_RECIPIENTS) - set(seen)))

# ---- the chain routes real transactions: a malformed tx of each kind dies in ITS OWN rule
from ops import transaction_ops as TX
calls = []
for name in rules:
    orig = getattr(TX, name)
    def spy(*a, _n=name, _o=orig, **k):
        calls.append(_n)
        raise AssertionError("stop")                  # the shared checks already ran; this kind's rule was reached
    setattr(TX, name, spy)
for kind, want in (("settle", "_validate_settle"), ("htlc_claim", "_validate_htlc_claim"),
                   ("tpm_commit", "_validate_tpm_ceremony"), ("invite_refund", "_validate_invite"),
                   ("undelegate", "_validate_pool_delegation")):
    calls.clear()
    recipient = kind
    # the dispatch alone, as validate_transaction runs it, with every rule spied
    src = ast.unparse(chain)
    try:
        exec(compile(src, "<chain>", "exec"), vars(TX) | {"transaction": {}, "block_height": 1, "recipient": recipient, "deep": False})
    except AssertionError:
        pass
    T.check(f"a {kind} tx reaches {want} and nothing else", calls == [want], calls)
calls.clear()
try:
    exec(compile(ast.unparse(chain), "<chain>", "exec"),
         vars(TX) | {"transaction": {"fee": 0}, "block_height": 1, "recipient": "ndo" + "a" * 45, "deep": False})
except AssertionError:
    pass
T.check("an ordinary transfer reaches no reserved rule (the fee-floor else)", calls == [], calls)
T.done("ALL PASS — every reserved recipient has exactly one validation rule")
