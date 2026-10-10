"""A RANDAO commitment made while seated can be revealed without a seat in the reveal epoch, and an unrevealed
commitment leaves the TPM challenger pool (protocol.REVEAL_SEATLESS_HEIGHT, RANDAO_MISS_POOL_HEIGHT).

  * below REVEAL_SEATLESS_HEIGHT a reveal-only duty from a validator holding no seat in its landing epoch is refused
    (the old rule, replayed as it was); from the gate it is accepted;
  * from the gate a duty that also carries an attest or commit section still needs the seat;
  * a seatless reveal still has to open the sender's own commitment;
  * the node's duty loop builds a reveal-only duty when it holds no seat (source pin: no attest/commit unseated);
  * below RANDAO_MISS_POOL_HEIGHT tpm_pool_v2 ignores reveals; from it an address whose commitment for the pool's
    epoch was not revealed is left out, a revealed one and one with no commitment stay.

Real validate_transaction on signed duty txs over a throwaway state DB.
Run: python3 tests/test_a_committed_secret_can_always_be_revealed.py
"""
import logging
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-seatless-reveal-")   # never the live database (assign)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers", "private"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

import protocol as P                                                   # noqa: E402
import ops.block_ops as B                                              # noqa: E402
import ops.transaction_ops as T                                        # noqa: E402
from ops import kv_ops                                                 # noqa: E402
from ops.mining_ops import beacon_commitment                           # noqa: E402
from signatures import generate_keydict                                # noqa: E402

FAILED = []
L = P.EPOCH_LENGTH
GATE = 3000 * L


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


kv_ops.init_env()
seated, unseated = generate_keydict(), generate_keydict()
for kd in (seated, unseated):
    kv_ops.account_set(kd["address"], "bonded", P.B_MIN * 3)
B.duty_committee_for_epoch = lambda e: {seated["address"]: 1}
T.get_block_number = lambda n: {"block_hash": "ab" * 32, "block_number": n}
P.REVEAL_SEATLESS_HEIGHT = GATE


def verdict(kd, X, reveal_secret=None, attest=False, commit=False):
    """A duty tx landing in epoch X (window inside the reveal window of X+1)."""
    E = X + 1
    hi = E * L - P.FINALITY_DEPTH - 1
    lo = X * L + 2
    rv = {"target_epoch": E, "secret": reveal_secret} if reveal_secret else None
    at = {"target_epoch": X, "target_hash": "ab" * 32} if attest else None
    cm = {"target_epoch": X + 2, "commitment": "cd" * 32} if commit else None
    tx = T.construct_duty_tx(kd, hi, attest=at, commit=cm, reveal=rv, min_block=lo)
    try:
        T.validate_transaction(tx, logging.getLogger("t"), block_height=lo)
        return "accepted"
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def committed(kd, E, secret):
    kv_ops.commit_put(kd["address"], E, beacon_commitment(secret))


# below the gate
X0 = GATE // L - 10
committed(unseated, X0 + 1, "s-below")
v = verdict(unseated, X0, "s-below")
check("below the gate a seatless reveal-only duty is refused", "holds no seat" in v, v)
committed(seated, X0 + 1, "s-seated")
v = verdict(seated, X0, "s-seated")
check("a seated reveal is accepted below the gate", v == "accepted", v)

# from the gate
X1 = GATE // L + 10
committed(unseated, X1 + 1, "s-after")
v = verdict(unseated, X1, "s-after")
check("from the gate a seatless reveal-only duty is accepted", v == "accepted", v)
v = verdict(unseated, X1, "s-after", commit=True)
check("from the gate a seatless duty carrying a commit is still refused", "holds no seat" in v, v)
v = verdict(unseated, X1, "s-after", attest=True)
check("from the gate a seatless duty carrying an attest is still refused", "holds no seat" in v, v)
v = verdict(unseated, X1, "not-the-secret")
check("a seatless reveal must open the sender's own commitment", "does not open" in v, v)
X2 = X1 + 5
v = verdict(unseated, X2, "s-none")
check("a seatless reveal with no commitment is refused", "No matching commit" in v, v)

# the node's duty loop
src = open(os.path.join(ROOT, "loops", "core_loop.py")).read()
seg = src[src.index("def maybe_epoch_duty"):src.index("def _restore_canonical_chain")]
check("the duty loop keeps going without a seat from REVEAL_SEATLESS_HEIGHT",
      "seated = me in duty_committee_for_epoch(X)" in seg and "REVEAL_SEATLESS_HEIGHT" in seg)
check("the unseated duty carries no attest and no commit",
      "if seated and X >= 1 and not kv_ops.attestation_exists(X, me):" in seg
      and "if seated and kv_ops.commit_get(me, e_commit) is None:" in seg)

# the TPM challenger pool: an unrevealed commitment excludes only a validator ABSENT from the reveal epoch
P.RANDAO_MISS_POOL_HEIGHT = GATE
a_miss, a_late, a_rev, a_none = ("miss" + "q" * 46), ("late" + "q" * 46), ("rev" + "q" * 47), ("none" + "q" * 46)
for a in (a_miss, a_late, a_rev, a_none):
    kv_ops.account_set(a, "bonded", P.B_MIN * 2)
T._duty_presence = lambda h: {a_miss: 99, a_late: 99, a_rev: 99, a_none: 99}
T._tpm_excluded = lambda h: set()
for Ep in (GATE // L - 3, GATE // L + 3):
    kv_ops.commit_put(a_miss, Ep, beacon_commitment("never-revealed-%d" % Ep))
    kv_ops.commit_put(a_late, Ep, beacon_commitment("late-never-revealed-%d" % Ep))
    kv_ops.commit_put(a_rev, Ep, beacon_commitment("revealed-%d" % Ep))
    kv_ops.reveal_put(Ep, "revealed-%d" % Ep)
# epoch E-1 blocks: a_late landed a duty (present, but its reveal missed the window); a_miss landed nothing
T.get_block_number = lambda n: {"block_number": n, "block_hash": "ab" * 32,
                                "block_transactions": ([{"recipient": "duty", "sender": a_late}] if n % L == 20 else [])}
pool_below = T.tpm_pool_v2((GATE // L - 3) * L + 5)
check("below the gate an unrevealed commitment changes nothing", set(pool_below) == {a_miss, a_late, a_rev, a_none}, pool_below)
pool_after = T.tpm_pool_v2((GATE // L + 3) * L + 5)
check("from the gate a validator ABSENT from the reveal epoch with an unrevealed commitment leaves the pool",
      a_miss not in pool_after, pool_after)
check("a validator PRESENT in the reveal epoch whose reveal still missed stays (a timing casualty, not absence)",
      a_late in pool_after and a_rev in pool_after and a_none in pool_after, pool_after)
check("the exclusion is per epoch: the next epoch without a commitment counts again",
      a_miss in T.tpm_pool_v2((GATE // L + 4) * L + 5))
_held = T.get_block_number
T._epoch_duty_cache[0] = None
T.get_block_number = lambda n: None
try:
    T.tpm_pool_v2((GATE // L + 3) * L + 5); _deferred = False
except T.WindowUnavailable:
    _deferred = True
check("a missing block of the reveal epoch defers (never guesses presence)", _deferred)
T.get_block_number = _held

print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILURES")
sys.exit(1 if FAILED else 0)
