"""An exec node mutes itself when L1 settles a cursor it attested with a DIFFERENT root (execnode.settled_contradicts_attestation,
maybe_settle's self-disqualification; betanet-3's frozen quorum, 2026-08-19).

WHY (2026-10-28). The check read `exec_root` from /get_settled, a key that endpoint never served (it answers
{ns, exec_cursor, state_root}), so it could not fire — while tests/test_exec_state_provenance.py, which pinned only the
source text ("SELF-DISQUALIFIED" ... "st.replay_gap = True"), stayed green. Pins, on the decision itself:
  1. the document nado.get_settled actually returns carries exactly the keys the decision reads (read from its source);
  2. with that shape: a contradicted attestation is detected; an agreeing one, a cursor we never attested, a document
     without a cursor or root, and a non-dict are not;
  3. the old shape (`exec_root` instead of `state_root`) is NOT how L1 answers — the regression this guards;
  4. maybe_settle reaches replay_gap through this helper.

Run: python3 tests/test_an_exec_node_mutes_itself_when_l1_settles_a_root_it_did_not_attest.py
"""
import os, sys, tempfile, ast
_T = tempfile.mkdtemp(prefix="nado-test-self-disq-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, _T, ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import execnode.execnode as EN

import _harness
_report = _harness.Report()
check = _report.check

src = open(os.path.join(ROOT, "nado.py")).read()
fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_settled")
keys = set()
for n in ast.walk(fn):
    if isinstance(n, ast.Dict) and n.keys and all(isinstance(k, ast.Constant) for k in n.keys):
        ks = {k.value for k in n.keys}
        if "exec_cursor" in ks:
            keys |= ks
check("1. nado.get_settled answers {ns, exec_cursor, state_root}", keys == {"ns", "exec_cursor", "state_root"}, keys)

A, B = "aa" * 32, "bb" * 32
doc = lambda c, r: {"ns": "default", "exec_cursor": c, "state_root": r}  # noqa: E731
f = EN.settled_contradicts_attestation
check("2a. a contradicted attestation is detected", f(doc(600, B), {600: A}) is True)
check("2b. an agreeing attestation is not", f(doc(600, A), {600: A}) is False)
check("2c. a cursor we never attested is not", f(doc(660, B), {600: A}) is False)
check("2d. a document without a cursor, without a root, or not a dict is not",
      not f({"ns": "default", "state_root": B}, {600: A}) and not f(doc(600, ""), {600: A}) and not f(None, {600: A}))
check("3. the old `exec_root` shape is not L1's answer, and reading it would see nothing",
      "exec_root" not in keys and f({"ns": "default", "exec_cursor": 600, "exec_root": B}, {600: A}) is False)
ms = open(EN.__file__).read()
body = ms[ms.index("async def maybe_settle("):]
body = body[:body.index("\nasync def ", 10)]
check("4. maybe_settle sets replay_gap through settled_contradicts_attestation",
      "settled_contradicts_attestation(_sd, st.attested)" in body and "st.replay_gap = True" in body)
_report.done()
