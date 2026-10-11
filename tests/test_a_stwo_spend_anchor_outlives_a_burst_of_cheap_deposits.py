"""A Stwo spend's anchor must outlive the deposits that land while it is proved and finalized — a stranger's burst of
1-raw deposits must not invalidate every pending spend (execnode/shielded_stwo.py ANCHOR_WINDOW, knows_root).

REVIEW 2026-10-11 (integration, reproduced, NOT FIXED — consensus code; the operator's call). The anchor window is
counted in APPENDS (128 roots), not in blocks. A wallet proves against the FINALIZED pool (/exec/field_leaves reads the
finalized state, so the root is already ~finality_depth blocks old), proves in the browser, publishes to DA and lands
the blob TX_INCLUSION_DELAY later; the exec layer applies it only once THAT block is final. Every deposit and every
spend output (2 appends) in the whole span counts against the 128. A shield deposit costs amount >= 1 raw plus
MIN_TX_FEE (1000 raw), paid txs have no per-sender pool cap, so ~128 x 1001 raw (~1.3e-5 NADO) per span makes every
in-flight Stwo spend fail "unknown anchor root" — and ordinary traffic of ~128 notes per span does the same with no
attacker at all. (The wide pool has the same append-counted window; the Stwo pool inherits it.)

Pins, on the real exec state with the native verifier stood in by an always-accept fake (the anchor check runs
before the proof, so the verdict does not matter): a victim's spend anchored to the root after its deposit, then 128
one-raw deposits by someone else in the SAME block, then the spend — it must still apply.

Run: python3 tests/test_a_stwo_spend_anchor_outlives_a_burst_of_cheap_deposits.py
"""
import os, sys, tempfile, types, copy
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-stwo-anchor-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
H = os.environ["HOME"]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
fake = types.ModuleType("execnode.stark.stwo_js_native")
fake.verify = lambda *a: (True, "")
sys.modules["execnode.stark.stwo_js_native"] = fake
import execnode.stark as _stk
_stk.stwo_js_native = fake
import protocol as P
from execnode.state import ExecState
from execnode import shielded_stwo as SP
from ops.address_ops import make_address

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


GATE = 1000
live = P.STWO_POOL_HEIGHT
P.STWO_POOL_HEIGHT = GATE
st = ExecState(os.path.join(tempfile.mkdtemp(dir=H), "s.json"))
st.cursor = GATE
st._applying = GATE + 1                         # every append below lands in ONE block
victim_nsk = "11" * 32
st.apply_field_shield(5 * 10 ** 10, SP.owner_of(victim_nsk), 7)
anchor = st.stwo_pool.root()                    # what the victim's wallet proves against
griefer = SP.owner_of("22" * 32)
for i in range(SP.ANCHOR_WINDOW):
    st.apply_field_shield(1, griefer, 10_000 + i)   # 1 raw each (+ MIN_TX_FEE on L1)
check("setup: the burst is 128 one-raw deposits", len(st.stwo_pool.commitments) == 1 + SP.ANCHOR_WINDOW)
bundle = {"stark": {"stwo_js": {"proof": "ab" * 8, "root": anchor, "nf": SP.nullifier(victim_nsk, 7),
                                "cm_out1": SP.commit(4 * 10 ** 10, SP.owner_of(victim_nsk), 8),
                                "cm_out2": SP.commit(10 ** 10 - 100, SP.owner_of(victim_nsk), 9),
                                "unshield": 0, "fee": 100}}}
r = st.apply_field_transfer(copy.deepcopy(bundle))
check("a spend anchored one block ago still applies after a burst of 128 one-raw deposits", r.startswith("field-transfer stwo"), r)
P.STWO_POOL_HEIGHT = live
print("ALL PASS — a Stwo anchor outlives a burst of deposits" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
