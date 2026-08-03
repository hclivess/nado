"""
Which of our blocks a candidate sync donor is asked about (loops/core_loop.root_probe_candidates).

WHY THIS EXISTS. `_root_known_to` is the ONE network check in donor selection. If the blocks it offers are
wrong, `get_peer_to_sync_from` returns None, and a node that is behind a heavier chain never rolls back
even one block — it just keeps building its own fork, forever, with no error louder than a DEBUG line.

THE WEDGE THIS PINS, measured live on alphanet-15 2026-08-03. 185.100.232.131 forked at h=7143 and sat
431 blocks behind the majority for over an hour. Its height rose monotonically and NEVER dropped: not one
rollback was attempted. The gate offered exactly two blocks and both had to fail:

  - our TIP        -> the majority cannot know it. That is what "forked" MEANS. The reorg leg is even
                      DEFINED by this (_rollback_one_for_reorg: "the donor does NOT know our tip").
  - our EARLIEST   -> block 2735, below the majority's snapshot-bootstrapped history. Measured:
                      `majority hash at 2735 = None`.

So the fast-forward precondition was being used to gate donor selection generally, which excluded
precisely the donors the REORG needed. Our FINALIZED block is the criterion that works for that leg: the
finality floor is immutable on our side, so any chain we may legitimately reorg onto contains it, and
knows_block checks canonicality — a donor NOT carrying our prefix still answers False.

Measured for .131 at the time: finalized 7107, hash 7674b0e9af9bdd00..., and the majority held exactly
that block at that height. One extra candidate would have unwedged it.

Run: python3 tests/test_root_probe_candidates.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_rootcand_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loops.core_loop import root_probe_candidates

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


def blk(h, n):
    return {"block_hash": h, "block_number": n}


# The measured alphanet-15 configuration: forked tip, finality frozen at 7107, earliest below the
# majority's snapshot history.
TIP = blk("f763f66eecb5085a", 7544)
FIN = blk("7674b0e9af9bdd00", 7107)
EAR = blk("6e1a32e8edcc9b9c", 2735)

cands = root_probe_candidates(TIP, FIN, EAR)

check("the finalized block IS offered — without it a forked node can never pick a donor", FIN in cands)
check("the tip is still tried FIRST (fast-forward stays the cheap common case)", cands[0] is TIP)
check("the finalized block is tried before earliest (reorg beats full-sync-from-root)",
      cands.index(FIN) < cands.index(EAR))
check("earliest is still offered last (a donor able to full-sync us from root still counts)",
      cands[-1] is EAR)
check("all three are offered when they are distinct", len(cands) == 3)

# ---- the gate must never SHRINK: every block that used to be offered still is ------------------------
check("the tip is never dropped", TIP in root_probe_candidates(TIP, FIN, EAR))
check("earliest is never dropped", EAR in root_probe_candidates(TIP, FIN, EAR))

# ---- cost discipline: a node whose tip IS its finalized block costs ONE dial, not two ----------------
same = blk("aaaa", 500)
check("a tip that equals the finalized block is not dialled twice",
      root_probe_candidates(same, dict(same), None) == [same])
check("...and identity is by (hash, number), not object identity",
      len(root_probe_candidates(blk("z", 9), blk("z", 9), blk("z", 9))) == 1)

# ---- degraded inputs must not raise or inject junk ---------------------------------------------------
check("a missing finalized block simply falls through to earliest",
      root_probe_candidates(TIP, None, EAR) == [TIP, EAR])
check("all-None yields no candidates rather than raising", root_probe_candidates(None, None, None) == [])
check("a malformed block is skipped, not offered",
      root_probe_candidates({"nope": 1}, FIN, None) == [FIN])
check("a non-dict is skipped", root_probe_candidates("garbage", FIN, None) == [FIN])
check("an empty dict is skipped", root_probe_candidates({}, FIN, None) == [FIN])

# ---- ordering is stable (donor selection runs every ~1s; a churning order would reshuffle dials) -----
check("repeated calls give the same order",
      root_probe_candidates(TIP, FIN, EAR) == root_probe_candidates(TIP, FIN, EAR))

print()
print("ALL PASS — a forked node can now offer a donor its immutable prefix, so the reorg leg is reachable"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
