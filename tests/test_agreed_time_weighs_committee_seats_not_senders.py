"""The certificate clock weighs duty-committee seats, not distinct senders (ops/transaction_ops.agreed_time,
AGREED_TIME_SEATS_HEIGHT: dormant on gen 28, 1 from gen 29, inlined in G9).

agreed_time — the agreed clock certificate validity reads — took the median of one sample per distinct duty sender. One
holder splitting its stake into many B_MIN accounts therefore bought that many clock samples, and a seatless reveal-only
duty counted too (2026-10-27 incident survey; cometbft CSA-2026-001 "Tachyon": a time median taken over a different set
or weight than the votes it borrows its trust from). From the gate each sender's latest SEATED sample weighs its seats in
that tx's landing-epoch duty committee, and the answer is the weighted median.

Pins, by RUNNING the real agreed_time over a synthetic window (block and committee reads stubbed; the per-sender half
of generation 28 is retired in G9):
  - the window answers the honest seats' time: nine one-seat accounts cannot outvote ten seats;
  - a sender with no seat in its landing epoch weighs nothing;
  - two heights of one epoch get one answer; epoch 0's window (end 0) keeps the per-sender rule (`>= 1`).

Run: python3 tests/test_agreed_time_weighs_committee_seats_not_senders.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-agreed-time-")
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import protocol as P
from ops import transaction_ops as T
from ops import block_ops as B

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


check("the gate constant is gone (inlined in G9)", not hasattr(P, "AGREED_TIME_SEATS_HEIGHT"))

EPOCH = P.EPOCH_LENGTH
H = 20 * EPOCH                       # the height whose clock is asked: window [H - CERT_CLOCK_WINDOW, H)
lo, hi = T.agreed_time_window(H)
TRUE, LIE = 1_800_000_000, 1_800_100_000      # the honest clock, and a time 100,000 s in the future
HONEST = {"aa" * 25: (TRUE, 10), "bb" * 25: (TRUE + 10, 5)}           # address -> (its duty timestamp, its seats)
SPLIT = {f"{i:02x}" * 25: (LIE, 1) for i in range(1, 10)}           # one holder as nine B_MIN accounts, a seat each
SEATLESS = {"ee" * 25: (LIE, 0)}                                     # a reveal-only duty with no seat this epoch
SENDERS = {**HONEST, **SPLIT, **SEATLESS}

blocks = {}
for i, (who, (ts, _seats)) in enumerate(sorted(SENDERS.items())):
    h = lo + 3 + i
    blocks[h] = {"block_number": h, "block_transactions": [{"recipient": "duty", "sender": who, "timestamp": ts,
                                                             "max_block": h + 2}]}
T.get_block_number = lambda h: blocks.get(h) or {"block_number": h, "block_transactions": []}
B.get_block_hash_by_number = lambda h: f"hash-{h}"
B.duty_committee_for_epoch = lambda e: {who: seats for who, (_ts, seats) in SENDERS.items() if seats}


def ask(height):
    T._agreed_time_cache.clear()
    return T.agreed_time(height)


# the pre-gate half (per-sender median: nine split accounts carried it) is retired in G9: generation 28's rules
new = ask(H)
check("the weighted median is the honest seats' time: nine one-seat accounts cannot outvote ten seats",
      new in (TRUE, TRUE + 10), new)
del SEATLESS["ee" * 25]
SENDERS.pop("ee" * 25)
check("...and a seatless sender weighs nothing (removing it changes no answer)", ask(H) == new)

# the rule is decided by the window end: two heights of one epoch share a window and its answer
a, b = ask(H + 1), ask(H + EPOCH - 1)                                 # each asked cold, as two nodes would
check("two heights of one epoch get one answer, each asked cold as two nodes would", a == b, (a, b))
src = open(T.__file__).read()
check("the rule is keyed on the window end (>= 1: epoch 0's window keeps the per-sender rule) and the cache key carries it",
      "seated = int(hi) >= 1" in src and "else None, seated)" in src)

print("\nALL PASS — the certificate clock weighs committee seats, not senders" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
