"""The fork verdict is stake-weighted: a Sybil peer-set adds headcount, a validator adds SEATS.

Punch-list item: the fork-recovery verdict was Sybil-soft — per-IP headcount probes anchored only by
seeds-first. Now each probe answer may carry a signed claim (nado.py /hash_attest), verified by the
prober against ITS OWN committed bonded registry, and majority_hash counts 1 + seats per answer. No
signed answers degrades to exactly the old headcount (stake hardens the verdict, it is never a liveness
dependency); one real validator outweighs any number of seatless IPs; and a stale signature (as_of far
from the prober's tip) is counted as unsigned rather than restating a dead view forever.

Run: python3 tests/test_stake_signed_verdicts.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops.fork_resolution import majority_hash

FAILS = []
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check(name, fn):
    try:
        fn()
        print("PASS  " + name)
    except AssertionError as e:
        print("FAIL  " + name + " — " + str(e))
        FAILS.append(name)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"FAIL  {name} — {type(e).__name__}: {e}")
        FAILS.append(name)


def t_one_validator_outweighs_a_sybil_swarm():
    """Five seatless IPs say 'bbbb'; one bonded validator with 10 seats says 'aaaa'. Stake wins."""
    answers = {f"sybil{i}": ("bbbb", 0) for i in range(5)}
    answers["validator"] = ("aaaa", 10)
    got = majority_hash(7, list(answers), lambda p, h: answers[p], min_answers=2)
    assert got == "aaaa", f"a 10-seat validator lost to 5 seatless IPs (got {got!r})"


def t_no_signed_answers_degrades_to_the_old_headcount():
    """Legacy probes (bare hashes) must behave byte-identically to before the weighting."""
    answers = {"a": "xxxx", "b": "xxxx", "c": "xxxx", "d": "yyyy"}
    assert majority_hash(7, list(answers), lambda p, h: answers[p]) == "xxxx"
    answers = {"a": "xxxx", "b": "yyyy"}
    assert majority_hash(7, list(answers), lambda p, h: answers[p]) is None, "50/50 is not a majority"


def t_min_answers_counts_answers_not_weight():
    """Quorum liveness must never depend on stake: one giant validator alone is still one answer."""
    answers = {"validator": ("aaaa", 1000)}
    assert majority_hash(7, ["validator"], lambda p, h: answers[p], min_answers=2) is None, \
        "a single answer passed a min_answers=2 quorum because its WEIGHT was large"


def t_non_answers_are_still_nothing():
    answers = {"a": (None, 50), "b": ("cccc", 0), "c": ("cccc", 0)}
    assert majority_hash(7, list(answers), lambda p, h: answers[p]) == "cccc", \
        "a None claim must contribute nothing, seats or not"


def t_negative_or_garbage_seats_cannot_subtract():
    answers = {"a": ("aaaa", -100), "b": ("bbbb", 0), "c": ("bbbb", 0)}
    assert majority_hash(7, list(answers), lambda p, h: answers[p]) == "bbbb", \
        "negative seats subtracted weight — an attacker-controlled field must clamp at 0"


def t_the_attest_message_binds_chain_and_freshness():
    from ops.block_ops import hash_attest_message
    from protocol import CHAIN_ID
    m = hash_attest_message(100, "ab" * 32, 60000)
    assert CHAIN_ID.encode() in m, "a signature from another generation would verify"
    assert b"100" in m and (b"60000" in m), "height/as_of missing — replay/staleness unbindable"
    assert m != hash_attest_message(100, "ab" * 32, 60001), "freshness is not part of the preimage"


def t_the_verdict_actually_uses_the_signed_probe():
    s = open(os.path.join(ROOT, "loops", "core_loop.py"), encoding="utf8").read()
    fs = s[s.index("def _fork_state"):]
    fs = fs[:fs.index("def _fork_verdict")]
    assert "probe_block_hash_signed" in fs, "the verdict probes are headcount-only again"
    assert "tip_hint=tip" in fs, "the freshness window is not passed — stale signatures count forever"
    p = open(os.path.join(ROOT, "ops", "peer_ops.py"), encoding="utf8").read()
    fn = p[p.index("def probe_block_hash_signed"):]
    fn = fn[:fn.index("def probe_block_hash(")]
    assert "return h, 0" in fn, "an unverifiable claim must still COUNT (headcount) at zero weight"
    assert "get_bonded_registry" in fn and "selection_shares" in fn, \
        "seats no longer come from the prober's OWN committed registry"
    assert "2 * EPOCH_LENGTH" in fn, "the staleness window is gone"


for name, fn in [(n, f) for n, f in list(globals().items()) if n.startswith("t_")]:
    check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "VERDICTS ARE STAKE-WEIGHTED, LIVENESS IS NOT")
sys.exit(1 if FAILS else 0)
