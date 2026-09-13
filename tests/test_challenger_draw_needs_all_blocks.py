"""THE CHALLENGER DRAW MUST NOT DEPEND ON WHAT THIS NODE HAPPENS TO HAVE ON DISK.

_proven_challengers scans a DEVICE_ATTEST_EK_PROVEN_WINDOW-block window and counts who acted as a
challenger. It did:

    block = get_block_number(h)
    if not block:
        continue

— so a node missing blocks in that window silently counted a SMALLER pool, drew different challengers,
and wrote a different state root. The draw feeds validation, and validation feeds the state root, so this
is a consensus answer computed from local disk contents.

MEASURED LIVE 2026-09-13, and it halted the chain. Sampling 163 heights of the window [71880, 77880) that
block 77901 scans:

    this relay (9-node majority)   0 blocks missing   -> state_root e9e02dab, block 79c5fad2
    185.238.249.208                8 blocks missing   -> state_root 26d432d4, block 0b022062
    208.87.242.141 (psychz)        partial gaps       -> agreed with 185.238.249.208

Both sides were byte-identical through 77901 — same hash, same state root — and diverged at 77902 on the
same parent. The two gap-ridden nodes then raced to 77970 unopposed while nine correct nodes sat frozen,
because a minority alone on a fork mines every slot.

The fix is not a better fallback. There is no safe value: a node that cannot read the window cannot
evaluate the rule, and must say so rather than answer. It raises ProofUnavailable — the codebase's
existing "not valid, not invalid, NOT YET" category, whose own docstring names this failure: "rejecting it
would fork the fleet along the axis of who happened to have the data." The node stalls and backfills.

A plain exception would have been worse than the bug: on OWN block assembly the caller drops the offending
transaction and keeps building, so a gap-ridden node would quietly omit the enrolment and diverge a second
way. That is what the last check here pins.

Run: python3 tests/test_challenger_draw_needs_all_blocks.py
"""
import os, sys, tempfile

os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="nado_cdraw_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops import transaction_ops as TO  # noqa: E402
from protocol import DEVICE_ATTEST_EK_PROVEN_WINDOW, EPOCH_LENGTH  # noqa: E402

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


HEIGHT = 77901
HI = (HEIGHT // EPOCH_LENGTH) * EPOCH_LENGTH
LO = max(1, HI - DEVICE_ATTEST_EK_PROVEN_WINDOW)


def world(missing=()):
    """A window where a handful of addresses acted, with `missing` heights absent from local disk."""
    missing = set(missing)

    def get_block_number(h):
        if h in missing:
            return None                      # this node does not hold it
        # One challenger action every 100 blocks, by a rotating cast; duty senders in between.
        if h % 100 == 0:
            return {"block_transactions": [{"recipient": "tpm_challenge", "sender": f"acted{h % 700}"}]}
        return {"block_transactions": [{"recipient": "duty", "sender": f"duty{h % 13}"}]}

    return get_block_number


def run(missing=()):
    TO._tpm_proven_cache[0] = None           # the cache is keyed on (lo, hi); clear it between worlds
    original = TO.get_block_number
    TO.get_block_number = world(missing)
    try:
        return TO._proven_challengers(HEIGHT), None
    except Exception as e:
        return None, e
    finally:
        TO.get_block_number = original


# ---------------------------------------------------------------- complete history answers
full, err = run()
check(err is None and full, f"a node with the whole window computes a set (err={err})")
complete_set = set(full or ())
check(len(complete_set) > 1, f"...and it is not trivially empty ({len(complete_set)} challengers)")

# ---------------------------------------------------------------- a gap must NOT quietly answer
gap_at = LO + 137                            # a height that carries a challenger action in this world
gapped, err = run(missing=[gap_at])
check(gapped is None, "a node MISSING a block in the window does not return a set")
check(err is not None, f"...it raises instead (got {type(err).__name__ if err else None})")

# ---------------------------------------------------------------- and it raises the DEFERRAL kind
check(isinstance(err, TO.ProofUnavailable),
      f"it raises ProofUnavailable — defer, do not reject (got {type(err).__name__ if err else None})")
check("do not guess" in str(err) and str(gap_at) in str(err),
      f"the message names the missing height and says not to guess ({str(err)[:90]})")

# THE DEFERRAL NAMES THE WINDOW. A node stuck in recovery never reaches the production gate that starts a
# fill, so the exception validation trips over is the one place it can learn what to fetch. The subclass
# carries exactly the window the draw scans — the same one proven_window() names for the gate.
check(isinstance(err, TO.WindowUnavailable), "...and it is a WindowUnavailable, so the node can start filling")
check((getattr(err, "lo", None), getattr(err, "hi", None)) == (LO, HI),
      f"...carrying the exact window [{LO},{HI}) (got {getattr(err, 'lo', None)}, {getattr(err, 'hi', None)})")

# WHY ProofUnavailable SPECIFICALLY. validate_transaction's caller re-raises it to defer the whole block,
# but swallows a generic Exception during OWN assembly — dropping the transaction and building without it.
# A gap-ridden node would then omit the enrolment and diverge a second way, so the exception TYPE is the
# behaviour, not decoration.
check(not isinstance(err, AssertionError),
      "it is not an AssertionError — that reads as 'invalid', which would fork on who holds the data")

# ---------------------------------------------------------------- the silent-divergence regression itself
# Before the fix this returned a SMALLER set than the complete one instead of raising. If a future change
# reintroduces a fallback, this is the check that catches it: two nodes must never answer differently.
if gapped is not None:
    check(set(gapped) == complete_set,
          f"a gap must never change the answer (complete {len(complete_set)}, gapped {len(set(gapped))})")

print(("\nFAILED: " + "; ".join(fails)) if fails else "\nall checks passed")
sys.exit(1 if fails else 0)
