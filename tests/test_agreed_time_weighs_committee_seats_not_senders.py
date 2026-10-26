"""The certificate clock weighs duty-committee seats, not distinct senders (ops/transaction_ops.agreed_time,
protocol.AGREED_TIME_SEATS_HEIGHT).

agreed_time — the agreed clock certificate validity reads — took the median of one sample per distinct duty sender. One
holder splitting its stake into many B_MIN accounts therefore bought that many clock samples, and a seatless reveal-only
duty counted too (2026-10-27 incident survey; cometbft CSA-2026-001 "Tachyon": a time median taken over a different set
or weight than the votes it borrows its trust from). From the gate each sender's latest SEATED sample weighs its seats in
that tx's landing-epoch duty committee, and the answer is the weighted median.

Pins, by RUNNING the real agreed_time over a synthetic window (block and committee reads stubbed — both rule sets):
  - below the gate (the live chain) the per-sender median is unchanged, and a split holder moves it: the old behaviour
    every committed block was judged under;
  - from the gate the same window answers the honest seats' time: nine one-seat accounts cannot outvote ten seats;
  - a sender with no seat in its landing epoch weighs nothing;
  - the rule is decided by the window end, so two heights of one epoch never get different rules from the cache;
  - the gate is dormant on gen 28 and live from block 1 on the next generation.

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


check("the gate is dormant on generation 28 and live from block 1 on the next",
      eval(open(os.path.join(os.path.dirname(P.__file__), "protocol.py")).read().split("AGREED_TIME_SEATS_HEIGHT = ")[1].split("\n")[0],
           {"CHAIN_GENERATION": 28}) == 1 << 62
      and eval(open(os.path.join(os.path.dirname(P.__file__), "protocol.py")).read().split("AGREED_TIME_SEATS_HEIGHT = ")[1].split("\n")[0],
               {"CHAIN_GENERATION": 29}) == 1)

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


P.AGREED_TIME_SEATS_HEIGHT = 1 << 62                                  # generation 28 as it runs
old = ask(H)
check("below the gate the per-sender median is unchanged: nine split accounts (and a seatless one) carry it",
      old == LIE, old)

P.AGREED_TIME_SEATS_HEIGHT = 1                                        # the next generation
new = ask(H)
check("from the gate the weighted median is the honest seats' time: nine one-seat accounts cannot outvote ten seats",
      new in (TRUE, TRUE + 10), new)
del SEATLESS["ee" * 25]
SENDERS.pop("ee" * 25)
check("...and a seatless sender weighs nothing (removing it changes no answer)", ask(H) == new)

# the rule is decided by the window end: a gate inside an epoch cannot split that epoch's heights
P.AGREED_TIME_SEATS_HEIGHT = H + 10                                   # BETWEEN the two heights below: keyed on height they would differ
a, b = ask(H + 1), ask(H + EPOCH - 1)                                 # two heights of one epoch, each asked by a node with
check("two heights of one epoch get one rule, each asked cold as two nodes would (window end, not height, decides)",
      a == b, (a, b))                                                 # an empty cache: keyed on height they would differ
src = open(T.__file__).read()
check("the rule is keyed on the window end and the cache key carries it",
      "seated = int(hi) >= int(AGREED_TIME_SEATS_HEIGHT)" in src and "else None, seated)" in src)

print("\nALL PASS — the certificate clock weighs committee seats, not senders" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
