"""A NODE MAY NOT CORROBORATE ITS OWN FINALITY FLOOR.

The depth floor (tip - FINALITY_DEPTH) is an ENFORCED, un-crossable barrier: rollback_one_block raises
FinalityViolation below it. So a node that advances it while alone on a fork becomes permanently unable to
roll back and rejoin — the partition wedge — and the only remaining exit is the dead-fork purge, which
destroys chain-derived data.

_depth_floor_corroborated is the guard against that, and it used to ask exactly one question: "is the
HEAVIEST advertised tip on our canonical chain?" For a node alone on a fork the answer is trivially yes —
it mines every slot unopposed, so its own tip IS the heaviest. The guard agreed with itself and failed open
in precisely the situation it exists for.

Live instance, alphanet-13 h5924 (2026-07-29): .131 built the same winner's block, same parent, same
state_root, four seconds earlier, without a blob tx whose min_block was that very height. It then mined
alone, corroborated its own floor 50 blocks past the fork, and could no longer rejoin.

These checks are cheap and pure — two KV reads, no network — so there is no excuse for not pinning them.
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile
os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="nado_corrob_"))
os.environ.setdefault("NADO_TESTNET", "1")
for _d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{_d}", exist_ok=True)
from loops.core_loop import majority_on_our_canonical

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


# A tiny fake chain: heights 0..10 canonical, plus one orphan block on a different fork.
CANON = {h: f"canon{h:02d}" for h in range(11)}
BLOCKS = {h_: {"block_number": n} for n, h_ in CANON.items()}
BLOCKS["forked07"] = {"block_number": 7}          # same height, different branch


def get_block(h):
    return BLOCKS.get(h)


def canon_at(n):
    return CANON.get(n)


# ---------------------------------------------------------------- the extracted predicate itself
check(majority_on_our_canonical("canon10", get_block, canon_at),
      "our own tip is 'on our canonical chain' — which is why it can never be the ONLY witness")
check(majority_on_our_canonical("canon08", get_block, canon_at),
      "a peer lagging a couple of blocks still corroborates (it is an ancestor of our tip)")
check(not majority_on_our_canonical("forked07", get_block, canon_at),
      "a same-height block on another branch does NOT corroborate")
check(not majority_on_our_canonical("unknown99", get_block, canon_at),
      "a tip we do not hold does NOT corroborate (we are behind another chain)")


# ---------------------------------------------------------------- the guard, as core_loop applies it
def corroborated(pool, heaviest, me):
    """Mirror of CoreLoop._depth_floor_corroborated's decision, over injectable inputs."""
    if not pool:
        return True                                    # solo / bootstrap: nothing to disagree with
    if not heaviest:
        return True
    if not majority_on_our_canonical(heaviest, get_block, canon_at):
        return False
    for peer, h in pool.items():                       # an INDEPENDENT witness is required
        if peer in me or not h:
            continue
        if majority_on_our_canonical(h, get_block, canon_at):
            return True
    return False


ME = {"10.0.0.1"}

check(corroborated({}, "canon10", ME),
      "no peers at all: solo/bootstrap still advances (unchanged behaviour)")

# THE REGRESSION. A lone forker: the pool holds only peers on some OTHER chain, and our own tip is heaviest
# because we mine unopposed. The old guard returned True here and let the floor climb past the fork.
lone = {"10.0.0.2": "forked07", "10.0.0.3": "forked07"}
check(not corroborated(lone, "canon10", ME),
      "LONE FORKER: heaviest is our own tip and every peer is elsewhere — floor must NOT advance")

# One honest peer on our chain is enough — this must not become so strict that healthy nodes freeze.
check(corroborated({"10.0.0.2": "canon09", "10.0.0.3": "forked07"}, "canon10", ME),
      "ONE independent peer on our chain corroborates (a healthy node is not frozen by a stray forker)")

# Our own advertisement in the pool must not count as the witness.
check(not corroborated({"10.0.0.1": "canon10"}, "canon10", ME),
      "our OWN entry in the pool is not evidence about our own tip")

# Someone else being heavier and elsewhere: refuse, as before.
check(not corroborated({"10.0.0.2": "canon09"}, "forked07", ME),
      "heaviest tip on another branch still refuses, exactly as before")

print()
if fails:
    print(f"{len(fails)} CHECK(S) FAILED:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("ALL DEPTH-FLOOR CORROBORATION CHECKS PASSED")
