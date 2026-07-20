"""
Dead-fork detection (ops/peer_ops.stranded_below_finality) — the autorecovery for a node stranded on a
minority fork AT OR BELOW its own finality floor.

THE LIVE WEDGE, 2026-07-20. This node finalized height 19988 with hash 7c7a7c08…; the network had
eb9d6de8… at the same height. Enforced finality then correctly refuses to roll back across 19988, so every
recovery path operates above a floor that is itself on the wrong chain:
  - rollback_one_block         -> FinalityViolation
  - _maybe_reanchor            -> gated on _heavier_chain_exists(), which reads consensus.status_pool and
                                  skips BENCHED peers; the peer set had collapsed to ONE, so no evidence
  - force_sync                 -> pinned to a good peer, still could not cross the floor
The node sat frozen 40+ minutes through a restart AND a force_sync. Only purge+resync moved it, run by
hand. So the detector must NOT depend on the status pool, weights, fork choice or benching — it asks peers
directly whether they have a different block where we are immutable.

Because the remedy destroys chain-derived data, the false-POSITIVE tests below matter more than the
positive one.

Run: python3 tests/test_dead_fork_escape.py
"""
import os, sys, tempfile, traceback
os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="nado_fork_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import peer_ops as P

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

OURS   = "7c7a7c08c5a77164c7a6ebed" + "0" * 40      # the real wedged hash, padded to 64
THEIRS = "eb9d6de853b94c47f79335a1" + "0" * 40      # what the network actually had at 19988
H = 19988


def probe(mapping):
    """Stub probe_block_hash: {peer: hash-or-None}."""
    return lambda peer, height, port=9173, timeout=6: mapping.get(peer)


class patched:
    def __init__(self, **kw): self.kw = kw; self.old = {}
    def __enter__(self):
        for k, v in self.kw.items(): self.old[k] = getattr(P, k); setattr(P, k, v)
        return self
    def __exit__(self, *a):
        for k, v in self.old.items(): setattr(P, k, v)


def t_the_live_wedge_is_detected():
    """The exact 2026-07-20 shape: everyone reachable has a different block at our finalized height."""
    peers = ["103.236.84.206", "103.236.77.251", "103.236.77.2"]
    with patched(probe_block_hash=probe({p: THEIRS for p in peers})):
        stranded, d = P.stranded_below_finality(OURS, H, peers, quorum=2)
    assert stranded, f"the live wedge MUST be detected: {d}"
    assert len(d["disagree"]) == 3 and not d["agree"]


def t_one_agreeing_peer_blocks_the_purge():
    """THE critical false-positive guard. If even ONE peer shares our finalized block, our prefix is not
    provably abandoned — we are just poorly connected. Wiping then would destroy a healthy node."""
    with patched(probe_block_hash=probe({"a": THEIRS, "b": THEIRS, "c": OURS})):
        stranded, d = P.stranded_below_finality(OURS, H, ["a", "b", "c"], quorum=2)
    assert not stranded, f"one agreeing peer must veto the purge: {d}"


def t_below_quorum_does_not_fire():
    """A single dissenting peer is not evidence — it could be the forked one."""
    with patched(probe_block_hash=probe({"a": THEIRS})):
        stranded, _ = P.stranded_below_finality(OURS, H, ["a"], quorum=2)
    assert not stranded, "one dissenter must not be enough to wipe the chain"


def t_unreachable_peers_are_not_evidence():
    """A network outage must never look like a fork. Unreachable peers count as unknown, not disagreement —
    otherwise losing connectivity would purge every node on the network simultaneously."""
    with patched(probe_block_hash=probe({})):
        stranded, d = P.stranded_below_finality(OURS, H, ["a", "b", "c", "d"], quorum=2)
    assert not stranded, "an offline node must NEVER purge itself"
    assert len(d["unknown"]) == 4 and not d["disagree"]


def t_partial_reachability_still_needs_quorum():
    """Most peers down, one dissenting: still not enough."""
    with patched(probe_block_hash=probe({"a": THEIRS, "b": None, "c": None})):
        stranded, _ = P.stranded_below_finality(OURS, H, ["a", "b", "c"], quorum=2)
    assert not stranded, "quorum is over ANSWERS, and one answer is not a quorum"


def t_healthy_node_never_fires():
    """Everyone agrees — the overwhelmingly common case. Must be silent."""
    with patched(probe_block_hash=probe({p: OURS for p in ("a", "b", "c")})):
        stranded, d = P.stranded_below_finality(OURS, H, ["a", "b", "c"], quorum=2)
    assert not stranded and len(d["agree"]) == 3


def t_detector_needs_no_status_pool_or_benching():
    """The property that makes this work where _maybe_reanchor did not: the signature takes only our hash,
    a height and a plain peer list. No consensus object, no weights, no bench state — so a collapsed peer
    set or a wrong bench cannot blind it."""
    import inspect
    params = list(inspect.signature(P.stranded_below_finality).parameters)
    assert params[:3] == ["our_hash", "height", "peers"], params
    for forbidden in ("consensus", "status_pool", "weight", "benched"):
        assert forbidden not in params, f"detector must not depend on {forbidden}"


for name, fn in [
    ("the live 2026-07-20 wedge IS detected", t_the_live_wedge_is_detected),
    ("ONE agreeing peer vetoes the purge", t_one_agreeing_peer_blocks_the_purge),
    ("a single dissenter is not enough", t_below_quorum_does_not_fire),
    ("unreachable peers are NOT evidence of a fork", t_unreachable_peers_are_not_evidence),
    ("partial reachability still needs quorum", t_partial_reachability_still_needs_quorum),
    ("healthy node never fires", t_healthy_node_never_fires),
    ("detector needs no status pool / benching", t_detector_needs_no_status_pool_or_benching),
]:
    check(name, fn)

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
