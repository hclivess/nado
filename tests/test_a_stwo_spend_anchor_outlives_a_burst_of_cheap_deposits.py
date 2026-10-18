"""A Stwo spend's anchor must outlive the deposits that land while it is proved and finalized — a stranger's burst of
1-raw deposits must not invalidate every pending spend (execnode/shielded_stwo.py ANCHOR_WINDOW, knows_root).

REVIEW 2026-10-11 (integration, reproduced; FIXED by block-closing anchors, shielded_stwo ANCHOR_BLOCKS). The anchor window is
counted in APPENDS (128 roots), not in blocks. A wallet proves against the FINALIZED pool (/exec/field_leaves reads the
finalized state, so the root is already ~finality_depth blocks old), proves in the browser, publishes to DA and lands
the blob TX_INCLUSION_DELAY later; the exec layer applies it only once THAT block is final. Every deposit and every
spend output (2 appends) in the whole span counts against the 128. A shield deposit costs amount >= 1 raw plus
MIN_TX_FEE (1000 raw), paid txs have no per-sender pool cap, so ~128 x 1001 raw (~1.3e-5 NADO) per span makes every
in-flight Stwo spend fail "unknown anchor root" — and ordinary traffic of ~128 notes per span does the same with no
attacker at all. (The wide pool has the same append-counted window; the Stwo pool inherits it.)

Pins, on the real exec state with the native verifier stood in by an always-accept fake (the anchor check runs
before the proof, so the verdict does not matter): a victim's spend anchored to the root its deposit's block closed
on, then 128+ one-raw deposits by someone else in the next block, then the spend — it applies. And the bound is real:
a block-closing root older than ANCHOR_BLOCKS is refused; the marks survive a snapshot round trip and clone; a
snapshot with forged marks moves the exec root; malformed marks are refused at load.

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


def fresh():
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=H), "s.json"))
    st.cursor = GATE
    return st


def at(st, h):
    st._applying = h


victim_nsk = "11" * 32
griefer = SP.owner_of("22" * 32)


def spend_bundle(anchor, rho_in, rho1, rho2):
    return {"stark": {"stwo_js": {"proof": "ab" * 8, "root": anchor, "nf": SP.nullifier(victim_nsk, rho_in),
                                  "cm_out1": SP.commit(4 * 10 ** 10, SP.owner_of(victim_nsk), rho1),
                                  "cm_out2": SP.commit(10 ** 10 - 100, SP.owner_of(victim_nsk), rho2),
                                  "unshield": 0, "fee": 100}}}


st = fresh()
at(st, GATE + 1)
st.apply_field_shield(5 * 10 ** 10, SP.owner_of(victim_nsk), 7)
anchor = st.stwo_pool.root()                    # the root block GATE+1 closed on: what the finalized view serves
at(st, GATE + 2)
for i in range(2 * SP.ANCHOR_WINDOW):
    st.apply_field_shield(1, griefer, 10_000 + i)   # 1 raw each (+ MIN_TX_FEE on L1)
check("setup: the burst pushed the anchor out of the append window", anchor not in st.stwo_pool.anchors)
at(st, GATE + 3)
r = st.apply_field_transfer(copy.deepcopy(spend_bundle(anchor, 7, 8, 9)))
check("a spend anchored to an earlier block's closing root still applies after a burst of one-raw deposits",
      r.startswith("field-transfer stwo"), r)

# the bound: ANCHOR_BLOCKS later the same kind of root is refused
st = fresh()
at(st, GATE + 1)
st.apply_field_shield(5 * 10 ** 10, SP.owner_of(victim_nsk), 7)
old = st.stwo_pool.root()
at(st, GATE + 2)
for i in range(SP.ANCHOR_WINDOW):
    st.apply_field_shield(1, griefer, 20_000 + i)
at(st, GATE + 1 + SP.ANCHOR_BLOCKS)
check("a closing root exactly ANCHOR_BLOCKS old is still accepted", st.stwo_pool.knows_root(old, st.applying_height()))
at(st, GATE + 2 + SP.ANCHOR_BLOCKS)
r = st.apply_field_transfer(copy.deepcopy(spend_bundle(old, 7, 8, 9)))
check("a closing root older than ANCHOR_BLOCKS is refused", "unknown anchor root" in r, r)
check("marks stay bounded: appends far later prune the old blocks",
      (st.apply_field_shield(1, griefer, 99) or True) and all(h >= st.applying_height() - SP.ANCHOR_BLOCKS
                                                              for h, _ in st.stwo_pool.marks), st.stwo_pool.marks)

# snapshot, clone, exec root
st = fresh()
at(st, GATE + 1)
st.apply_field_shield(5 * 10 ** 10, SP.owner_of(victim_nsk), 7)
a1 = st.stwo_pool.root()
at(st, GATE + 2)
for i in range(SP.ANCHOR_WINDOW + 5):
    st.apply_field_shield(1, griefer, 30_000 + i)
p2 = SP.StwoShieldedPool.from_dict(st.stwo_pool.to_dict())
check("the marks survive a snapshot round trip", p2.marks == st.stwo_pool.marks and p2.knows_root(a1, GATE + 3)
      and p2.anchors == st.stwo_pool.anchors and p2.root() == st.stwo_pool.root())
c = st.clone()
check("and a clone (the provisional view)", c.stwo_pool.knows_root(a1, GATE + 3) and c.stwo_pool.marks == st.stwo_pool.marks)
from execnode import exec_root as ER
d = st.stwo_pool.to_dict()
d["marks"] = [[GATE + 1, 1], [GATE + 2, len(d["commitments"]) - 1]]
forged = fresh()
forged.stwo_pool = SP.StwoShieldedPool.from_dict(d)
forged.pool_value, forged.cursor = st.pool_value, st.cursor
st2 = fresh()
st2.stwo_pool = SP.StwoShieldedPool.from_dict(st.stwo_pool.to_dict())
st2.pool_value, st2.cursor = st.pool_value, st.cursor
check("a snapshot whose marks differ projects a different exec root",
      ER.records_projection(forged) != ER.records_projection(st2))
for bad, why in (([[5, 2], [4, 3]], "heights fall"), ([[5, 3], [6, 3]], "counts repeat"),
                 ([[5, 10 ** 9]], "count beyond the pool"), ([[5, 0]], "an empty block mark")):
    try:
        SP.StwoShieldedPool(d["commitments"], [], bad)
        check(f"malformed marks are refused at load ({why})", False)
    except ValueError:
        check(f"malformed marks are refused at load ({why})", True)
# A QUIET POOL (review 2026-10-12): a root stays every block's closing root until the next append, so it is acceptable
# for ANCHOR_BLOCKS after it was LAST current — not after the block that created it. A pool quiet for longer than the
# window, then one deposit: a spend proved against the pre-deposit root (what every wallet saw) still applies.
st = fresh()
at(st, GATE + 1)
st.apply_field_shield(5 * 10 ** 10, SP.owner_of(victim_nsk), 7)
quiet = st.stwo_pool.root()
at(st, GATE + 1 + 3 * SP.ANCHOR_BLOCKS)                     # long quiet stretch, then someone deposits
for i in range(SP.ANCHOR_WINDOW + 1):                     # one deposit, then enough more in the same block to push
    st.apply_field_shield(1, griefer, 40_000 + i)           # the quiet root out of the append window: only its span remains
check("setup: the quiet root is out of the append window", quiet not in st.stwo_pool.anchors)
check("a quiet pool's root is still acceptable right after the next deposit", st.stwo_pool.knows_root(quiet, st.applying_height()))
check("...and for ANCHOR_BLOCKS after it stopped being current",
      st.stwo_pool.knows_root(quiet, GATE + 1 + 3 * SP.ANCHOR_BLOCKS - 1 + SP.ANCHOR_BLOCKS)
      and not st.stwo_pool.knows_root(quiet, GATE + 1 + 3 * SP.ANCHOR_BLOCKS + SP.ANCHOR_BLOCKS))
check("root_valid_through: the current root at least ANCHOR_BLOCKS past the cursor, an intra-block root never vouched",
      st.stwo_pool.root_valid_through(st.stwo_pool.root(), 500) == 500 + SP.ANCHOR_BLOCKS
      and st.stwo_pool.root_valid_through("ab" * 32, 500) is None)
P.STWO_POOL_HEIGHT = live
print("ALL PASS — a Stwo anchor outlives a burst of deposits" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
