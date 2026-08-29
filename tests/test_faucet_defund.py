#!/usr/bin/env python3
"""faucet.defund(amount): the operator takes back only what the operator put in — never treasury money.

Offline ExecState, real assembled contract. Run: HOME=$(mktemp -d) python3 tests/test_faucet_defund.py"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState                     # noqa: E402
from execnode.games import faucet as F                    # noqa: E402

passed = failed = 0
def ok(c, m):
    global passed, failed
    if c: passed += 1
    else: failed += 1; print("  FAIL:", m)

OP, STR, TREAS = F.OPERATOR, "ndoSTRANGER000000000000000000000000000000000", "treasury"
st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json")); st.cursor = 100
st.bridge[OP] = 10 ** 13; st.bridge[STR] = 10 ** 13
from execnode import zkvmasm                              # noqa: E402
OLD_FUND = "\n    ctx r1 value\n    movi r2 0\n    lt r2 r1\n    require r2\n    ret r0\n"      # the fund() that is live today: records nothing
old = zkvmasm.assemble_contract({"fund": OLD_FUND, "reward": F.REWARD})
st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": old, "abi": {"fund": {"args": [], "value": True}}, "nonce": "n", "at": "faucet"}, OP, "d")
ok("faucet" in st.contracts, "fixed-name faucet deployed offline")
slot = lambda k: int((st.contracts["faucet"]["storage"].get("slots") or {}).get(str(k), 0))
def call(who, method, args, value=None, tag=[0]):
    tag[0] += 1; p = {"op": "call", "contract": "faucet", "method": method, "args": args}
    if value: p["value"] = value
    st.apply_blob(p, who, f"{method}-{tag[0]}")
def refused(who, method, args, value=None):
    before = json.dumps({"s": st.contracts["faucet"]["storage"], "b": st.bridge}, sort_keys=True, default=str)
    try: call(who, method, args, value)
    except Exception: pass
    return before == json.dumps({"s": st.contracts["faucet"]["storage"], "b": st.bridge}, sort_keys=True, default=str)

# the situation on chain: the operator funded the faucet before defund existed (nothing recorded), then the upgrade lands
call(OP, "fund", [], 300 * 10 ** 10)
ok(slot(7) == 0, "pre-upgrade code records nothing (as today)")
st.apply_blob({"op": "upgrade", "contract": "faucet", "code": F.build(), "abi": F.ABI}, OP, "u")
ok("defund" in st.contracts["faucet"]["code"], "1. upgrade lands defund()")
ok(slot(7) == 300 * 10 ** 10, "   the seed records the balance at the upgrade block as the operator's donations (treasury never paid in)")

# from now on: operator fund() records, stranger fund() does not, treasury credits do not
call(OP, "fund", [], 100 * 10 ** 10);   ok(slot(7) == 400 * 10 ** 10, "2. operator fund() adds to DONATED")
call(STR, "fund", [], 50 * 10 ** 10);   ok(slot(7) == 400 * 10 ** 10, "   a stranger's fund() does NOT")
st.credit_deposit("faucet", 500 * 10 ** 10)                                   # a treasury->faucet payout, as the node mirrors it
ok(slot(7) == 400 * 10 ** 10 and st.bridge["faucet"] == 950 * 10 ** 10, "   a treasury payout raises the balance, not DONATED")

# the cap
ok(refused(STR, "defund", [1]), "3. a stranger cannot defund")
ok(refused(OP, "defund", [0]), "   zero refused")
ok(refused(OP, "defund", [401 * 10 ** 10]), "   more than the operator's own donations refused (treasury money stays)")
b0 = st.bridge[OP]; call(OP, "defund", [250 * 10 ** 10])
ok(st.bridge[OP] - b0 == 250 * 10 ** 10 and slot(8) == 250 * 10 ** 10, "4. defund pays the operator and records DEFUNDED")
ok(refused(OP, "defund", [151 * 10 ** 10]), "   the remaining allowance is DONATED - DEFUNDED (150): 151 refused")
call(OP, "defund", [150 * 10 ** 10]); ok(slot(8) == 400 * 10 ** 10, "   150 taken — allowance exhausted")
ok(refused(OP, "defund", [1]), "5. nothing more can leave: the 550 left in the faucet (stranger + treasury) is untouchable by the operator")
ok(st.bridge["faucet"] == 550 * 10 ** 10, "   faucet balance is exactly the non-operator money")
# a later L1-style operator donation through the node's mirror path
st.bump_contract_slot("faucet", 7, 10 ** 10); st.credit_deposit("faucet", 10 ** 10)
call(OP, "defund", [10 ** 10]); ok(slot(8) == 401 * 10 ** 10, "6. an L1 donation the node mirrored is take-backable too")
print(f"\n[faucet-defund] {passed} passed, {failed} failed"); sys.exit(1 if failed else 0)
