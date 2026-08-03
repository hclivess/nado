"""
DUPLICATED VALIDATOR KEY detection (loops/message_loop.key_collision).

WHY THIS EXISTS. A duplicated key is invisible to every consensus rule, because nothing either copy does
is individually illegal: both copies are entitled to the same slots, so each builds its OWN block for that
slot and signs it validly. The fleet then sees one creator emitting two different blocks at the same
height. The halves that accept different copies diverge on STATE while agreeing on the block BODY — which
is indistinguishable, from the logs, from a non-block-derived write, and sends the operator hunting for a
stray writer that does not exist.

Measured live on alphanet-15 (2026-08-03). Node 38.242.201.206 was a byte-for-byte clone of this node,
wallet included — identical 46-char address AND identical build string:

    local  address=ebd27698662f14ee2389e509781d5ff57487f4289a4d67  version=alphanet-14-36-g661b0900
    .206   address=ebd27698662f14ee2389e509781d5ff57487f4289a4d67  version=alphanet-14-36-g661b0900

All five nodes agreed through block 3261; at 3262 two rival blocks existed with the SAME creator, the same
empty body and the same exec_root, differing only in state_root. Four earlier wedges carried that same
signature and were each written off as a mystery non-block write.

THE TRAP THIS PINS. "A peer reports our address" is NOT proof of a clone: the status pool is keyed by
ENDPOINT, so this node reached via its own public IP reports our address too. Escalating on that alone
would fire on every correctly configured node with a public IP. Proof requires EQUIVOCATION — the same
address holding a different block hash at the SAME height, which a single process cannot do.

Run: python3 tests/test_key_collision.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_keycoll_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loops.message_loop import key_collision

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


US = "ebd27698662f14ee2389e509781d5ff57487f4289a4d67"
OTHER = "ba04cbbb7c1ffc17ed67b62e3100f25789f3738998af6b"
H, OURS = 3262, "4345a433e1212454"
RIVAL = "09fad3a06d91cdaf"


def peer(addr, height=H, bhash=OURS):
    return {"address": addr, "latest_block_height": height, "latest_block_hash": bhash}


# ---- the healthy fleet: nobody else holds our key ---------------------------------------------------
twins, proven = key_collision({"a": peer(OTHER), "b": peer(OTHER + "x")}, US, H, OURS)
check("a fleet of distinct keys reports no twin and no proof", (twins, proven) == ([], []))

# ---- our own public IP is a twin, but NOT proof ------------------------------------------------------
# The same process reached by two endpoints agrees with itself, so there is nothing to escalate on.
twins, proven = key_collision({"1.2.3.4": peer(US), "peer": peer(OTHER)}, US, H, OURS)
check("this node reached via its own public IP is seen as a twin", twins == ["1.2.3.4"])
check("...but agreeing with ourselves is NOT proof of a clone", proven == [])

# ---- THE LIVE CASE: a rival block at the same height IS proof -----------------------------------------
twins, proven = key_collision(
    {"38.242.201.206": peer(US, H, RIVAL), "185.100.232.131": peer(OTHER)}, US, H, OURS)
check("a clone holding a RIVAL block at our height is proven", proven == ["38.242.201.206"])
check("and a proven clone is also counted as a twin", twins == ["38.242.201.206"])

# ---- a clone that merely LAGS is not yet provable -----------------------------------------------------
# Different heights are ordinary lag; only equal height with a different hash is equivocation.
twins, proven = key_collision({"clone": peer(US, H - 5, RIVAL)}, US, H, OURS)
check("a twin at a DIFFERENT height is a suspicion, not proof", (twins, proven) == (["clone"], []))

# ---- robustness: the pool is peer-supplied and must never crash the health report ---------------------
twins, proven = key_collision(
    {"junk": "not-a-dict", "empty": {}, "nohash": {"address": US, "latest_block_height": H},
     "none": {"address": None}}, US, H, OURS)
check("malformed pool entries are ignored, not raised on", proven == [] and twins == ["nohash"])
check("an absent hash cannot prove equivocation", "nohash" not in proven)
check("an empty pool is handled", key_collision({}, US, H, OURS) == ([], []))
check("a None pool is handled", key_collision(None, US, H, OURS) == ([], []))

# ---- results are deterministic ordering, so the operator-facing string is stable ----------------------
twins, _ = key_collision({"z": peer(US), "a": peer(US), "m": peer(US)}, US, H, OURS)
check("twins come back sorted (a stable health line, not a churning one)", twins == ["a", "m", "z"])

print()
print("ALL PASS — a shared key is detected, and only EQUIVOCATION is treated as proof"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
