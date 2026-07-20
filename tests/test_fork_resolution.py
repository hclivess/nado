"""
Fork resolution (ops/fork_resolution.py) — the single measurement that replaces inferred recovery.

Each scenario below is a state the live node was actually in on 2026-07-20, and the assertion is the action
it SHOULD have taken. The old code inferred recovery from weights/donor behaviour/bench state and got the
first one wrong, which is what produced the 40-minute wedge:

  it was BEHIND on the correct chain, decided "forked", tried to roll back, found no history beneath its
  imported snapshot, aborted, re-anchored, looped.

Run: python3 tests/test_fork_resolution.py
"""
import os, sys, tempfile, traceback
os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="nado_fr_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import fork_resolution as FR

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def chain(prefix):
    """Deterministic hash of a height on a named chain."""
    return lambda h: f"{prefix}-{h}"


def peers_on(prefix, n=3, silent=0, split=None):
    """A peer set: n peers on `prefix`, `silent` unreachable, optional `split` peers on another chain."""
    names, probe_map = [], {}
    for i in range(n):
        p = f"good{i}"; names.append(p); probe_map[p] = chain(prefix)
    for i in range(silent):
        p = f"down{i}"; names.append(p); probe_map[p] = lambda h: None
    for i in range(split or 0):
        p = f"odd{i}"; names.append(p); probe_map[p] = chain("other")
    return names, (lambda peer, h: probe_map[peer](h))


def t_behind_on_the_same_chain_is_NOT_a_fork():
    """THE bug. Our hash matches theirs at OUR tip — we are simply short. The only correct action is
    forward sync; a rollback here is what wedged the node against a snapshot with no history beneath it."""
    peers, probe = peers_on("main")
    v = FR.resolve(chain("main"), tip=20000, finalized=19988, peers=peers, probe=probe)
    assert v["state"] == FR.BEHIND, f"being behind must NEVER classify as a fork: {v}"
    assert v["ancestor"] == 20000, v


def t_fork_above_finality_is_a_reorg():
    """Diverged after the floor: a normal rollback to the common ancestor fixes it."""
    ours = lambda h: chain("main")(h) if h <= 19995 else chain("mine")(h)
    peers, probe = peers_on("main")
    v = FR.resolve(ours, tip=20000, finalized=19988, peers=peers, probe=probe)
    assert v["state"] == FR.REORG and v["ancestor"] == 19995, v


def t_fork_below_finality_is_a_dead_fork():
    """The live wedge: we disagree at and below our own finalized height, so finality forbids the rollback
    and no local remedy exists. Purge + resync is the ONLY correct answer."""
    ours = lambda h: chain("main")(h) if h <= 19000 else chain("mine")(h)
    peers, probe = peers_on("main")
    v = FR.resolve(ours, tip=20000, finalized=19988, peers=peers, probe=probe)
    assert v["state"] == FR.DEAD_FORK, f"a fork below the floor must be a DEAD_FORK: {v}"
    assert v["ancestor"] == 19000, v


def t_total_divergence_is_a_dead_fork():
    """Nothing in common at all (the post-purge 'mining my own chain from genesis' state)."""
    peers, probe = peers_on("main")
    v = FR.resolve(chain("mine"), tip=13, finalized=0, peers=peers, probe=probe)
    assert v["state"] == FR.DEAD_FORK, v


def t_silent_peers_yield_UNKNOWN_never_a_purge():
    """THE most important negative. If nobody answers we must do NOTHING. Reading an outage as a fork would
    purge every node on the network at once."""
    peers, probe = peers_on("main", n=0, silent=4)
    v = FR.resolve(chain("main"), tip=20000, finalized=19988, peers=peers, probe=probe)
    assert v["state"] == FR.UNKNOWN, f"silence must be UNKNOWN, not a fork: {v}"


def t_split_peers_without_majority_yield_UNKNOWN():
    """Peers evenly split across two chains: no majority, so no action. Acting on a coin flip is worse
    than waiting."""
    names = ["a", "b"]
    probe = lambda peer, h: (chain("main") if peer == "a" else chain("other"))(h)
    v = FR.resolve(chain("main"), tip=100, finalized=50, peers=names, probe=probe)
    assert v["state"] == FR.UNKNOWN, v


def t_a_minority_of_odd_peers_does_not_derail():
    """Two peers on a junk chain among four good ones must not change the verdict."""
    peers, probe = peers_on("main", n=4, split=2)
    v = FR.resolve(chain("main"), tip=20000, finalized=19988, peers=peers, probe=probe)
    assert v["state"] == FR.BEHIND, v


def t_search_is_logarithmic():
    """Cost must be ~log2(depth), or nobody can afford to run this every pass on a long chain."""
    ours = lambda h: chain("main")(h) if h <= 50_000 else chain("mine")(h)
    peers, probe = peers_on("main")
    v = FR.resolve(ours, tip=100_000, finalized=0, peers=peers, probe=probe)
    assert v["ancestor"] == 50_000, v
    assert v["probes"] <= 20, f"binary search must stay logarithmic, used {v['probes']} probes"


def t_classify_is_pure_arithmetic():
    """The decision itself depends on nothing but three integers — no weights, no bench, no forced peers."""
    assert FR.classify(100, 100, 50) == FR.BEHIND
    assert FR.classify(80, 100, 50) == FR.REORG
    assert FR.classify(40, 100, 50) == FR.DEAD_FORK
    assert FR.classify(None, 100, 50) == FR.UNKNOWN


for name, fn in [
    ("BEHIND on the same chain is not a fork (the live bug)", t_behind_on_the_same_chain_is_NOT_a_fork),
    ("fork above finality -> REORG to the ancestor", t_fork_above_finality_is_a_reorg),
    ("fork below finality -> DEAD_FORK (purge+resync)", t_fork_below_finality_is_a_dead_fork),
    ("no common history at all -> DEAD_FORK", t_total_divergence_is_a_dead_fork),
    ("silent peers -> UNKNOWN, never a purge", t_silent_peers_yield_UNKNOWN_never_a_purge),
    ("split peers with no majority -> UNKNOWN", t_split_peers_without_majority_yield_UNKNOWN),
    ("a minority of odd peers does not derail", t_a_minority_of_odd_peers_does_not_derail),
    ("ancestor search is logarithmic", t_search_is_logarithmic),
    ("classify is pure arithmetic", t_classify_is_pure_arithmetic),
]:
    check(name, fn)

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
