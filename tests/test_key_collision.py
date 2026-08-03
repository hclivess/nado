"""
DUPLICATED VALIDATOR KEY detection (loops/message_loop.key_collision).

WHY THIS EXISTS. A duplicated key is invisible to every consensus rule, because nothing either copy does
is individually illegal: both copies are entitled to the same slots, so each builds its OWN block for that
slot and signs it validly. The fleet then sees one creator emitting two different blocks at the same
height. The halves that accept different copies diverge on STATE while agreeing on the block BODY — which
is indistinguishable, from the logs, from a non-block-derived write, and sends the operator hunting for a
stray writer that does not exist.

THE TRAP THIS PINS, learned the expensive way. "A peer reports our address" is NOT proof of a clone: the
status pool is keyed by ENDPOINT, so this node reached via its own public IP reports our address and is a
twin of ITSELF. On 2026-08-03 an investigation on alphanet-15 concluded from an address match alone that
38.242.201.206 was a byte-for-byte clone of this node, wallet included:

    local  address=ebd27698662f14ee2389e509781d5ff57487f4289a4d67  version=alphanet-14-36-g661b0900
    .206   address=ebd27698662f14ee2389e509781d5ff57487f4289a4d67  version=alphanet-14-36-g661b0900

38.242.201.206 is this box's own public IP. It routes over `lo`, and both endpoints reported the same
uptime, the same tip and the same transaction-pool hash — one process, reached two ways. The identical
address and identical build string carried NO information, and the two endpoints never once disagreed at
any sampled height, which is exactly the evidence that was missing.

So the only admissible proof is EQUIVOCATION — the same address holding a different block hash at the
SAME height, which a single process cannot do. Escalating on an address match alone would fire on every
correctly configured node with a public IP.

THE SECOND TRAP, learned the same day and one layer down. Knowing the match was not proof, the first cut
still reported it as a *suspicion* — and the running node then logged, every 10 seconds, forever:

    [ WARN ] Identity   1 endpoint(s) report our address (38.242.201.206) — harmless if that is this
                        node's own public IP, a duplicated key if it is not

The condition it warns on is the NORMAL configuration, so the line can never clear, and a health line that
is permanently red is one the operator is trained to skip. A check that cannot distinguish the healthy
case from the broken one is not a weak check, it is a broken one. `local_addresses` (from
`message_loop.own_addresses()`: configured IP + loopback + bound interfaces) now removes what we can prove
is ourselves BEFORE anything is reported, so the healthy fleet reports "ok" and a warn means something.

Run: python3 tests/test_key_collision.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_keycoll_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loops.message_loop import key_collision, own_addresses

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

# ---- THE CASE THAT ACTUALLY OCCURRED: our own public IP is a twin, but NOT proof ---------------------
# The same process reached by two endpoints agrees with itself at every height, so there is nothing to
# escalate on. This is the exact configuration that was misread as a clone.
twins, proven = key_collision({"38.242.201.206": peer(US), "peer": peer(OTHER)}, US, H, OURS)
check("this node reached via its own public IP is seen as a twin", twins == ["38.242.201.206"])
check("...but agreeing with ourselves is NOT proof of a clone", proven == [])

# ...and once we can PROVE the endpoint is this box, it is not even a suspicion. This is the regression
# for the permanent [ WARN ] Identity line the live node logged every 10s on a perfectly healthy fleet.
twins, proven = key_collision({"38.242.201.206": peer(US), "peer": peer(OTHER)}, US, H, OURS,
                              local_addresses={"38.242.201.206"})
check("a twin that is provably THIS box is not reported at all", (twins, proven) == ([], []))
check("...so a healthy node with a public IP reports Identity ok, not a standing warn", not twins)

# loopback is always ours, and an endpoint carrying a :port suffix must still be recognised
twins, _ = key_collision({"127.0.0.1:9173": peer(US)}, US, H, OURS, local_addresses=own_addresses())
check("loopback with a port suffix is recognised as ourselves", twins == [])

# the filter must NEVER swallow proof: two processes on this box sharing a key still equivocate
twins, proven = key_collision({"127.0.0.1": peer(US, H, RIVAL)}, US, H, OURS,
                              local_addresses=own_addresses())
check("an own address that EQUIVOCATES is still proven (a second local process)", proven == ["127.0.0.1"])

# a real remote clone is not masked by the filter
twins, proven = key_collision({"38.242.201.206": peer(US), "10.0.0.9": peer(US, H, RIVAL)}, US, H, OURS,
                              local_addresses={"38.242.201.206"})
check("filtering ourselves does not hide a real remote clone", proven == ["10.0.0.9"])
check("and the remote clone is the only twin reported", twins == ["10.0.0.9"])

# own_addresses() must actually find this machine's own addresses, or the filter is decorative
check("own_addresses() includes loopback", "127.0.0.1" in own_addresses())
check("own_addresses() folds in the configured public IP", "1.2.3.4" in own_addresses("1.2.3.4"))
check("own_addresses() does not leak the configured IP into the cache",
      "1.2.3.4" not in own_addresses())

# ---- a rival block at the same height IS proof (a real clone would look like this) -------------------
twins, proven = key_collision(
    {"10.0.0.9": peer(US, H, RIVAL), "185.100.232.131": peer(OTHER)}, US, H, OURS)
check("a clone holding a RIVAL block at our height is proven", proven == ["10.0.0.9"])
check("and a proven clone is also counted as a twin", twins == ["10.0.0.9"])

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
