"""FORK RESOLUTION WHEN *WE* ARE THE PRUNED ONE.

test_fork_resolution_pruned.py models a fleet that pruned its history — but it lets `our_hash_at` answer at
every height, so it never exercised the other half of the asymmetry: WE prune too, and an archive peer can
answer at a height WE no longer hold.

`agrees(h)` compared `our_hash_at(h) == theirs`. A pruned height makes `our_hash_at(h)` None, and
`None == "<hash>"` is False — so the absence of our own block was recorded as a CLAIM OF DISAGREEMENT.
At the floor that returns `floor - 1`, which classify() reads as DEAD_FORK.

MEASURED LIVE 2026-09-13. Four nodes sat frozen for hours with `recovery: {state: dead_fork, ancestor: -1}`
and `recovery_fail: "walk missed the ancestor"`:

    node             tip     lowest retained block   verdict
    208.87.242.141   73463   23411                   dead_fork, ancestor -1
    185.184.192.210  73455   -                       dead_fork, ancestor -1
    85.222.175.102   73661   23615                   dead_fork, ancestor -1
    2001:b07:...     73165   -                       dead_fork, ancestor -1

They were not forked at all — they were BEHIND a fleet tip of 73956 on the same chain. But this node
(38.242.201.206) is an ARCHIVE node and DEFAULT_SEED_PEERS[0], so seeds-first put it in every probe set and
it answered at h0. The stuck nodes held nothing at h0, scored that as disagreement at the floor, and
published a permanent dead-fork verdict that blocked every recovery route they had.

DEAD_FORK is the one verdict whose remedy is destructive. It must never be reachable from a height we
cannot see. Absence of our own block is absence of evidence — exactly what the module says about a peer
that does not answer.

Run: python3 tests/test_fork_resolution_self_pruned.py
"""
import os, sys, tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_frsp_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops import fork_resolution as FR

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


PEERS = ["archive", "p2", "p3"]


def world(our_floor, fork_at=None, peer_tip=10**9):
    """We retain only [our_floor, tip]; an ARCHIVE peer answers everywhere down to h0.

    With fork_at=None we are on the peers' chain and merely short of it — the live case."""
    def our_hash_at(h):
        if h < our_floor:
            return None                                   # WE pruned it: we cannot answer, at all
        return f"C{h}" if fork_at is None or h <= fork_at else f"A{h}"

    def probe(_peer, h):
        if h > peer_tip:
            return None
        return f"C{h}" if fork_at is None or h <= fork_at else f"B{h}"

    return our_hash_at, probe


# ---------------------------------------------------------------- the live wedge
our_hash_at, probe = world(our_floor=23411)
v = FR.resolve(our_hash_at=our_hash_at, tip=73463, finalized=73380, peers=PEERS, probe=probe)
check(v["state"] != FR.DEAD_FORK,
      f"a node merely BEHIND is never dead-forked by its own prune floor (got {v['state']}, "
      f"ancestor={v['ancestor']})")
check(v["state"] == FR.BEHIND and v["ancestor"] == 73463,
      f"...it is BEHIND at its own tip, and forward sync is the action (got {v['state']}, "
      f"ancestor={v['ancestor']})")

# ---------------------------------------------------------------- the destructive verdict stays earned
# A REAL divergence inside the range we can still see must still be found, at the exact height.
our_hash_at, probe = world(our_floor=23411, fork_at=73400)
v = FR.resolve(our_hash_at=our_hash_at, tip=73463, finalized=73380, peers=PEERS, probe=probe)
check(v["state"] == FR.REORG and v["ancestor"] == 73400,
      f"a real fork above the floor is still found exactly (got {v['state']}, ancestor={v['ancestor']})")

our_hash_at, probe = world(our_floor=23411, fork_at=73300)
v = FR.resolve(our_hash_at=our_hash_at, tip=73463, finalized=73380, peers=PEERS, probe=probe)
check(v["state"] == FR.DEAD_FORK,
      f"a real fork below the floor is still DEAD_FORK (got {v['state']})")

# ---------------------------------------------------------------- the honest unknown
# We diverge somewhere beneath our own retention. We cannot see it, so we cannot name it. The verdict must
# be UNKNOWN ("change nothing") and NOT a purge -- unless resolve()'s finalized-height rescue proves it,
# which it can, because we always hold our own finalized block.
our_hash_at, probe = world(our_floor=23411, fork_at=20000)
v = FR.resolve(our_hash_at=our_hash_at, tip=73463, finalized=73380, peers=PEERS, probe=probe)
check(v["state"] in (FR.DEAD_FORK, FR.UNKNOWN),
      f"divergence beneath our retention: proven by the finalized height, or UNKNOWN (got {v['state']})")
check(v["state"] != FR.DEAD_FORK or v.get("via"),
      "...and if it IS dead_fork it was proven at the finalized height, not inferred from a missing block")

# ---------------------------------------------------------------- no self-inflicted floor
# The pathological shape: the archive peer answers at h0 and we hold nothing there. Before the fix this
# alone produced ancestor=-1 from a node that agreed with the fleet at every height it could see.
our_hash_at, probe = world(our_floor=23411)
anc, _ = FR.find_common_ancestor(our_hash_at, tip=73463, peers=PEERS, probe=probe, floor=0)
check(anc != -1, f"an archive peer answering at h0 cannot drive the ancestor to -1 (got {anc})")

print(("FAILED: " + "; ".join(fails)) if fails else "\nall checks passed")
sys.exit(1 if fails else 0)
