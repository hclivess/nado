"""
RE-ANCHOR must be able to target a snapshot BELOW our finality floor when that snapshot is a block WE
ALSO HOLD (loops/core_loop.snapshot_on_our_chain + reanchor_candidates).

THE WEDGE THIS FIXES. A fork wedge is exactly the case where our own finality floor was established ON
THE FORK. The floor then defends history the network never agreed with, while every honest peer's
snapshot sits below it — so the floor test can never be satisfied and re-anchor has no candidate, forever.

Measured live on alphanet-15, 2026-08-03. This node forked at 3261 and finalised 3218; every peer
advertised snapshot_height=3000:

    local  tip=3261  weight=1060176  finalized=3218  snapshot_height=3000
    .131   tip=3825  weight=1244040  finalized=3780  snapshot_height=3000
    .210   tip=3825  weight=1244040  finalized=3780  snapshot_height=3000

All three recovery paths were shut at the same time: sync donors were disqualified because our fork tip is
a hash no peer knows, normal re-anchor found nothing above 3218, and the ESCALATED path that would ignore
the floor is documented as operator-only and is never set by the fork-state machine. The node sat at 3261
with finality frozen for ~54 minutes and could not have recovered on its own.

WHY ALTITUDE IS THE WRONG TEST, AND IDENTITY IS THE RIGHT ONE. Height 3000 was a block all five nodes
agreed on (8cfb02f7...). Re-anchoring to it discards only our OWN forked tail; it crosses no history the
network disputes. So the safe question is not "is the target above the height we finalised?" but "is the
target a block we ourselves hold?" — if it is, the import is a rewind through SHARED history, and the tail
is re-fetched and re-verified block by block like any other sync.

The helper must also never widen the gate on a guess: with no accessor, a missing field, or a lookup that
raises, it returns False and the strict floor test stands.

Run: python3 tests/test_reanchor_shared_history.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_reanchor_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loops.core_loop import snapshot_on_our_chain, reanchor_candidates

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


PROTO = 99
SHARED = "8cfb02f7c3895fb3"          # the block at 3000 that every node agreed on
FOREIGN = "deadbeefdeadbeef"         # a snapshot hash that is NOT on our chain
OUR_WEIGHT, FLOOR = 1060176, 3218    # live values: our fork's weight and its finality floor

# our chain: we hold the shared block at 3000, and our own forked tail above it
OURS = {3000: SHARED, 3218: "ffffffffffffffff", 3261: "4e83c4d33ebd8ba9"}


def our_hash_at(h):
    return OURS.get(h)


def peer(weight=1244040, sh=3000, shash=SHARED, proto=PROTO):
    return {"latest_block_weight": weight, "snapshot_height": sh, "snapshot_hash": shash,
            "protocol": proto}


# ---- the predicate itself ----------------------------------------------------------------------------
check("a snapshot we hold at the same height and hash is on our chain",
      snapshot_on_our_chain(3000, SHARED, our_hash_at) is True)
check("a snapshot hash we do NOT hold at that height is not",
      snapshot_on_our_chain(3000, FOREIGN, our_hash_at) is False)
check("a height we do not hold at all is not",
      snapshot_on_our_chain(2500, SHARED, our_hash_at) is False)

# It must never widen the gate on a guess — every unprovable case falls back to the strict floor test.
check("no accessor -> cannot prove -> False", snapshot_on_our_chain(3000, SHARED, None) is False)
check("no height -> False", snapshot_on_our_chain(None, SHARED, our_hash_at) is False)
check("no snapshot hash -> False", snapshot_on_our_chain(3000, None, our_hash_at) is False)


def _raises(h):
    raise RuntimeError("db closed")


check("an accessor that RAISES is contained, not propagated",
      snapshot_on_our_chain(3000, SHARED, _raises) is False)

# ---- THE LIVE WEDGE: reanchor_candidates before and after ---------------------------------------------
peers = ["185.100.232.131", "185.184.192.210"]
statuses = [peer(), peer()]

before = reanchor_candidates(peers, statuses, OUR_WEIGHT, FLOOR, min_protocol=PROTO)
check("REPRODUCES THE WEDGE: with only the floor test there is NO candidate (3000 < 3218)", before == [])

after = reanchor_candidates(peers, statuses, OUR_WEIGHT, FLOOR, min_protocol=PROTO,
                            our_block_hash_at=our_hash_at)
check("with the identity test, the shared-history snapshot becomes a candidate", len(after) == 2)
check("...and it is the height-3000 block both sides hold",
      all(c[1] == 3000 and c[2] == SHARED for c in after))

# ---- the gate must not become a free pass -------------------------------------------------------------
# A snapshot below our floor that we do NOT hold stays refused: that WOULD be a rollback into history we
# never agreed with, which is exactly what the finality floor exists to prevent.
foreign = reanchor_candidates(peers, [peer(shash=FOREIGN), peer(shash=FOREIGN)], OUR_WEIGHT, FLOOR,
                              min_protocol=PROTO, our_block_hash_at=our_hash_at)
check("a below-floor snapshot we do NOT hold is still refused", foreign == [])

# Every other guard still applies on top of the relaxed floor.
lighter = reanchor_candidates(peers, [peer(weight=OUR_WEIGHT), peer(weight=OUR_WEIGHT)], OUR_WEIGHT, FLOOR,
                              min_protocol=PROTO, our_block_hash_at=our_hash_at)
check("a chain that is NOT strictly heavier is still refused", lighter == [])

foreign_net = reanchor_candidates(peers, [peer(proto=PROTO - 1), peer(proto=PROTO - 1)], OUR_WEIGHT, FLOOR,
                                  min_protocol=PROTO, our_block_hash_at=our_hash_at)
check("a foreign-protocol peer is still refused", foreign_net == [])

lone = reanchor_candidates(["1.2.3.4"], [peer()], OUR_WEIGHT, FLOOR, min_protocol=PROTO,
                           our_block_hash_at=our_hash_at)
check("a LONE non-seed corroborator is still refused (weak-subjectivity guard intact)", lone == [])

# ---- and the normal above-floor path is unchanged ------------------------------------------------------
above = reanchor_candidates(peers, [peer(sh=3400, shash="aaaa"), peer(sh=3400, shash="aaaa")],
                            OUR_WEIGHT, FLOOR, min_protocol=PROTO)
check("an above-floor snapshot still qualifies with no accessor at all", len(above) == 2)

print()
print("ALL PASS — identity, not altitude: a snapshot we ourselves hold is a safe re-anchor target"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
