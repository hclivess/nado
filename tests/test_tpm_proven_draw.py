"""The challenger draw must not seat an address that cannot answer.

A WALLET THAT MINES IS NOT A NODE. It bonds, registers, attests with its own TPM and lands the same FFG
duty transactions, so on chain it is indistinguishable from a validator — but it runs no daemon and so no
challenger loop. The owner's own mining wallet was drawn as a challenger for a stranger's enrolment and
could never answer: one slot of three dead on arrival, and the enrolment expired at 1/3.

The only signal that separates them is having DONE the job. Each test below is a way that rule fails:
  - draw from proven challengers once enough exist            (else wallets keep taking slots)
  - never seat a duty-only sender once k proven exist         (the actual bug)
  - fall back when fewer than k have proven                   (else a fresh chain deadlocks forever)
  - respect the height gate                                   (old blocks must replay under the old rule)

Run: python3 tests/test_tpm_proven_draw.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-proven-")   # never touch the live database
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol as P                                                          # noqa: E402
import ops.block_ops as B                                                     # noqa: E402
import ops.transaction_ops as T                                               # noqa: E402

# The beacon is a real chain read; this test is about WHO is eligible, not about the randomness source.
# Fixed per epoch so the draw stays deterministic, which one of the checks below relies on.
B.epoch_beacon = lambda epoch: ("%064x" % (epoch * 2654435761 % (1 << 256)))

FAILED = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


def build_chain(proven, duty_only, height):
    """A fake chain: `proven` senders post a tpm_challenge, `duty_only` senders post only duties."""
    blocks = {}
    for h in range(1, height + 1):
        txs = []
        for a in duty_only:
            txs.append({"recipient": "duty", "sender": a})
        if h % 7 == 0:
            for a in proven:
                txs.append({"recipient": "tpm_challenge", "sender": a})
        blocks[h] = {"block_transactions": txs}
    return blocks


def install(blocks):
    T.get_block_number = lambda n: blocks.get(int(n))
    T._tpm_proven_cache[0] = None
    T._tpm_producer_cache[0] = None


HEIGHT = P.DEVICE_ATTEST_EK_PROVEN_HEIGHT + 500
NODES = [f"{i:02x}" * 23 for i in range(1, 6)]        # five real nodes that answer
WALLETS = [f"{i:02x}" * 23 for i in range(100, 112)]  # twelve mining wallets that never answer

install(build_chain(NODES, WALLETS, HEIGHT))

proven = T._proven_challengers(HEIGHT)
check("a node that has acted as challenger is eligible", set(proven) == set(NODES),
      f"got {sorted(proven)[:2]}")
check("a mining wallet that only lands duties is not", not (set(proven) & set(WALLETS)))

# THE BUG ITSELF: across many enrolment ids, no wallet may ever be seated.
seated = set()
for i in range(300):
    seated |= set(T._tpm_challengers(f"{i:032x}", HEIGHT))
check("no duty-only wallet is ever drawn once k nodes have proven",
      not (seated & set(WALLETS)), f"seated wallets: {sorted(seated & set(WALLETS))[:3]}")
check("every seated challenger is a proven one", seated and seated <= set(NODES))
check("a full set is always drawn", all(
    len(T._tpm_challengers(f"{i:032x}", HEIGHT)) == P.DEVICE_ATTEST_EK_CHALLENGERS for i in range(50)))

# DEADLOCK GUARD: with too few proven, the draw must still seat somebody.
install(build_chain(NODES[:1], WALLETS, HEIGHT))
few = T._tpm_challengers("ab" * 16, HEIGHT)
check("falls back when fewer than k have proven", len(few) == P.DEVICE_ATTEST_EK_CHALLENGERS,
      f"drew {len(few)}")

# THE GATE: below it, the old pool decides, so old blocks replay unchanged.
install(build_chain(NODES, WALLETS, HEIGHT))
below = set()
for i in range(60):
    below |= set(T._tpm_challengers(f"{i:032x}", P.DEVICE_ATTEST_EK_PROVEN_HEIGHT - 1))
check("below the gate the old duty-sender pool is used", bool(below & set(WALLETS)),
      "no wallet drawn below the gate — the gate is not doing anything")

# DETERMINISM: the same inputs must give the same set, or nodes disagree about block validity.
a = T._tpm_challengers("cd" * 16, HEIGHT)
T._tpm_proven_cache[0] = None
b = T._tpm_challengers("cd" * 16, HEIGHT)
check("the draw is deterministic", a == b, f"{a} != {b}")

print("\n" + ("ALL OK" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}"))
sys.exit(1 if FAILED else 0)
