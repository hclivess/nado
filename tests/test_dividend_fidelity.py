"""
Dividend fraud-proof — historical fidelity/weight reconstruction (doc/dividend-fraud-proof.md, Part A).

The whole fraud proof rests on re-deriving each miner's fidelity-weight AS OF a past epoch from the immutable
recert history. This test PINS ops.dividend_ops.fidelity_at_epoch to the LIVE ops.account_ops.apply_register
ramp: it drives a real recert sequence (continuous runs + a lapse) through apply_register, records the live
fidelity after each recert, then asserts the reconstruction reproduces it exactly. A drift here would make a
fraud proof false-slash honest settlers, so this is the load-bearing test.

Run: python3 tests/test_dividend_fidelity.py
"""
import os, sys, tempfile, logging, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_divfid_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "index/producer_sets", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logger = logging.getLogger("divfid"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import POSW_LEASE_EPOCHS as LEASE
from ops import kv_ops
from ops.account_ops import create_account, get_account, apply_register
from ops.mining_ops import open_shares
from ops.dividend_ops import fidelity_at_epoch, present_at_epoch, weights_at_epoch
from ops.key_ops import generate_keys

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

A = generate_keys()["address"]
create_account(A, registered=0)

# 3 CONTINUOUS recerts (gap == LEASE, the boundary that still counts as continuous) -> fidelity 1,2,3;
# then a LAPSE (gap == LEASE+5 > LEASE) -> reset to 1; then 1 continuous -> 2.
lapse = 10 + 2 * LEASE + LEASE + 5
SEQ = [10, 10 + LEASE, 10 + 2 * LEASE, lapse, lapse + LEASE]
LIVE = {}
for e in SEQ:
    apply_register(A, epoch=e, logger=logger)
    LIVE[e] = get_account(A)["fidelity"]

def t1_live_ramp_is_as_expected():
    assert [LIVE[e] for e in SEQ] == [1, 2, 3, 1, 2], f"live apply_register ramp {[LIVE[e] for e in SEQ]}"

def t2_reconstruction_matches_live_at_each_recert():
    for e in SEQ:
        assert fidelity_at_epoch(A, e) == LIVE[e], f"reconstruct fidelity@{e}: {fidelity_at_epoch(A,e)} != {LIVE[e]}"

def t3_between_and_before_recerts():
    assert fidelity_at_epoch(A, SEQ[0] - 1) == 0, "no recert yet -> 0"
    assert fidelity_at_epoch(A, SEQ[0] + 1) == 1, "holds the last recert's fidelity between recerts"
    assert fidelity_at_epoch(A, SEQ[2] + 1) == 3, "still 3 just after the third continuous recert"
    assert fidelity_at_epoch(A, lapse - 1) == 3, "the lapse hasn't happened yet at lapse-1"
    assert fidelity_at_epoch(A, lapse) == 1, "the lapse recert resets to 1"

def t4_present_set_tracks_the_lease_window():
    # Lease valid when (epoch - recert) < LEASE, identical to get_open_registry -> last valid epoch = recert+LEASE-1.
    assert A in present_at_epoch(SEQ[-1]), "present at its latest recert"
    assert A in present_at_epoch(SEQ[-1] + LEASE - 1), "still present on the last valid lease epoch"
    assert A not in present_at_epoch(SEQ[-1] + LEASE), "lease lapsed at recert+LEASE -> absent"
    assert A not in present_at_epoch(SEQ[0] - 1), "absent before the first recert"

def t4b_reconstruction_agrees_with_live_get_open_registry():
    # The reconstructed present set must match the live get_open_registry membership (which reads the current
    # recert index) for the CURRENT epoch — same source of truth, so they cannot disagree on membership.
    from ops.account_ops import get_open_registry
    e = SEQ[-1] + 3
    assert present_at_epoch(e) == set(get_open_registry(e).keys()), "present_at_epoch == get_open_registry membership"

def t5_weights_are_open_shares_of_reconstructed_fidelity():
    e = SEQ[-1]
    assert weights_at_epoch(e).get(A) == open_shares(fidelity_at_epoch(A, e)), "weight == open_shares(fidelity@e)"
    # a mid-history epoch weighs by THAT epoch's fidelity (3), not the current one (2)
    assert weights_at_epoch(SEQ[2]).get(A) == open_shares(3), "historical weight uses historical fidelity"

for name, fn in sorted(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
