"""
Example exec-node contracts (execnode/contract_lib.py) built from generalized method patterns: a counter,
a per-caller accumulator (tip jar), and a fair 2-player commit-reveal coin flip. Deploys + drives each
through ExecState exactly as an L1 blob stream would.

Run: python3 tests/test_contract_lib.py
"""
import os, sys, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode.vm import validate_code, _hash_value
from execnode import contract_lib as C

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

A, B = "ndoAlice", "ndoBob"
def _st(): return ExecState(tempfile.mktemp(prefix="nado_clib_", suffix=".json"))
def _deploy(st, code, who=A, nonce="n1"):
    cid = st.contract_id(who, code, nonce)
    st.apply_blob({"op": "deploy", "code": code, "nonce": nonce}, sender=who, txid="d")
    assert cid in st.contracts, "deployed"
    return cid
def _call(st, cid, method, args, who=A, txid="c"):
    return st.apply_blob({"op": "call", "contract": cid, "method": method, "args": args}, sender=who, txid=txid)


def t0_all_examples_validate():
    """Every library contract is well-formed bytecode (deploy would accept it)."""
    for name, code in C.EXAMPLES.items():
        assert validate_code(code), name


def t1_counter():
    """inc() bumps a shared integer; get() reads it."""
    st = _st(); cid = _deploy(st, C.COUNTER)
    assert st.view(cid, "get", []) == 0
    _call(st, cid, "inc", [], txid="i1"); _call(st, cid, "inc", [], txid="i2")
    assert st.view(cid, "get", []) == 2, "two increments -> 2"


def t2_tip_jar_accumulator():
    """add(amount) accrues per caller; of/mine read totals; add(0) reverts (no change)."""
    st = _st(); cid = _deploy(st, C.TIP_JAR)
    _call(st, cid, "add", [10], who=A, txid="a1")
    _call(st, cid, "add", [20], who=A, txid="a2")
    _call(st, cid, "add", [5],  who=B, txid="b1")
    assert st.view(cid, "of", [A]) == 30, "A accrued 30"
    assert st.view(cid, "of", [B]) == 5,  "B accrued 5, isolated per caller"
    _call(st, cid, "add", [0], who=A, txid="a3")               # require amount>0 -> revert
    assert st.view(cid, "of", [A]) == 30, "add(0) reverted, no change"


def t3_coin_flip_fair_and_deterministic():
    """Two players commit HASH(secret), reveal, and flip() returns the parity of HASH(secret0‖secret1)."""
    st = _st(); cid = _deploy(st, C.COIN_FLIP)
    g, sa, sb = 1, 12345, 67890
    _call(st, cid, "commit", [g, _hash_value(sa)], who=A, txid="ca")
    _call(st, cid, "commit", [g, _hash_value(sb)], who=B, txid="cb")
    assert st.view(cid, "flip", [g]) is None, "no result before both reveal (REQUIRE nrev==2)"
    _call(st, cid, "reveal", [g, sa], who=A, txid="ra")
    _call(st, cid, "reveal", [g, sb], who=B, txid="rb")
    expected = _hash_value(str(sa) + str(sb)) % 2                # A revealed first -> slot 0
    got = st.view(cid, "flip", [g])
    assert got in (0, 1) and got == expected, f"fair coin = {expected}, got {got}"


def t4_coin_flip_reveal_mismatch_and_double_commit_rejected():
    """A reveal whose HASH != the commit reverts; a second commit by the same player reverts."""
    st = _st(); cid = _deploy(st, C.COIN_FLIP)
    g, sa = 7, 999
    _call(st, cid, "commit", [g, _hash_value(sa)], who=A, txid="ca")
    _call(st, cid, "commit", [g, _hash_value(sa)], who=A, txid="ca2")   # double commit by A -> revert
    assert st.contracts[cid]["storage"].get("ncom", {}).get(str(g)) == 1, "A committed once; double-commit rejected"
    _call(st, cid, "reveal", [g, 111], who=A, txid="bad")              # wrong secret -> revert
    assert str(g) not in st.contracts[cid]["storage"].get("nrev", {}), "no reveal after a mismatched secret"
    _call(st, cid, "reveal", [g, sa], who=A, txid="ok")               # correct secret -> recorded
    assert st.contracts[cid]["storage"]["nrev"][str(g)] == 1, "correct reveal recorded"

def t5_coin_flip_phase_and_player_binding():
    """The 2nd mover can't commit AFTER a reveal (can't choose the outcome); a non-committer can't reveal
    (can't hijack/DoS the game). These are the audit's H-2/H-3 fixes."""
    st = _st(); cid = _deploy(st, C.COIN_FLIP)
    g, sa, sb = 3, 111, 222
    _call(st, cid, "commit", [g, _hash_value(sa)], who=A, txid="ca")
    _call(st, cid, "reveal", [g, sa], who=A, txid="ra")               # A reveals -> commit phase closes
    _call(st, cid, "commit", [g, _hash_value(sb)], who=B, txid="cb")  # B commits after a reveal -> REVERT
    assert st.contracts[cid]["storage"].get("ncom", {}).get(str(g)) == 1, "no commit after a reveal (2nd mover can't choose)"
    _call(st, cid, "reveal", [g, 999], who="ndoCarol", txid="rc")     # non-committer reveal -> REVERT
    assert st.contracts[cid]["storage"]["nrev"][str(g)] == 1, "non-committer reveal rejected (no hijack/DoS)"


def t6_vm_operand_cap_reverts_not_ooms():
    """A DUP;MUL squaring blowup (2^(2^n)) is capped -> the call REVERTS fast (no gigabyte bignum / OOM).
    Gas counts instructions, not operand size, so this is the audit's H-1 fix."""
    from execnode.contract_lib import PUSH, DUP, MUL, MSTORE, HALT
    boom = [PUSH(2)] + [DUP(), MUL()] * 40 + [PUSH("k"), PUSH(1), MSTORE("m"), HALT()]
    st = _st(); cid = _deploy(st, {"boom": boom})
    r = _call(st, cid, "boom", [], txid="b")           # capped at _MAX_INT_BITS -> revert before any huge alloc
    assert "revert" in r.lower(), r
    assert not st.contracts[cid]["storage"].get("m"), "blowup reverted -> nothing stored"


for name, fn in sorted(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
