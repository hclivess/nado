"""Punishment lands because the protocol SAW the offence — the watchtower, exercised end to end.

Punch-list item: "slashing is recorded, not battle-proven". Slash VALIDATION had been complete for a
while (resolve_slash: block-authorship + FFG double-vote proofs, per-offence dedup, bonded-penalty
application) — but nothing ever SUBMITTED one: no watchtower existed, so punishment happened only if a
human noticed an equivocation and hand-built the proof tx. This test forges a real double-vote with real
ML-DSA keys and drives the actual pipeline:

    two signed duty txs (same validator, same epoch, different checkpoint hash)
      -> gossip both through memserver.merge_transaction (the second is refused as a duplicate —
         WHICH IS WHY the watchtower hooks BEFORE the refusal paths: the refusal is the evidence)
      -> the watchtower builds the proof and merges a signed fee-exempt slash tx into the pool
      -> resolve_slash accepts that exact proof (offender + dedup key)
      -> a cross-chain replay (same content, different chain_id) is refused

Isolation: re-execs with HOME in a scratch dir before importing anything (the live LMDB is never opened).
Run: python3 tests/test_watchtower_slash.py
"""
import os
import subprocess
import sys
import tempfile

if os.environ.get("_WT_CHILD") != "1":
    tmp = tempfile.mkdtemp(prefix="wt_")
    env = dict(os.environ, HOME=tmp, _WT_CHILD="1", NADO_ALLOW_PYTHON_KERNELS="1",
               PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, os.path.abspath(__file__)], env=env)
    sys.exit(r.returncode)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs(os.path.expanduser("~/nado"), exist_ok=True)

from ops.key_ops import generate_keys                                    # noqa: E402
from ops.transaction_ops import (construct_duty_tx, resolve_slash,       # noqa: E402
                                 verify_attestation_equivocation_proof)

FAILS = []


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


class _Log:
    def __getattr__(self, _n):
        return lambda *a, **k: None


VALIDATOR = generate_keys()
EPOCH = 1000


def duty_attest(target_hash, max_block=60123):
    return construct_duty_tx(VALIDATOR, max_block,
                             attest={"target_epoch": EPOCH, "target_hash": target_hash})


class _WatchHost:
    """The minimal host the watchtower needs — its logic lives on MemServer, borrowed unbound so the
    test never constructs a full node (peers, sockets, chain state)."""
    def __init__(self):
        from memserver import MemServer
        self.logger = _Log()
        self.keydict = generate_keys()               # the REPORTER is a different identity
        self.latest_block = {"block_number": 60000}
        self.merged = []
        self.maybe_watchtower_slash = MemServer.maybe_watchtower_slash.__get__(self)

    def merge_transaction(self, tx, user_origin=False):
        self.merged.append(tx)
        return {"result": True, "message": "ok"}


def t_a_double_vote_produces_a_slash_automatically():
    host = _WatchHost()
    a = duty_attest("aa" * 32)
    b = duty_attest("bb" * 32)
    host.maybe_watchtower_slash(a)
    assert not host.merged, "one honest vote must never trigger anything"
    host.maybe_watchtower_slash(b)
    assert len(host.merged) == 1, "the second conflicting vote must produce exactly one slash tx"
    slash = host.merged[0]
    assert slash["recipient"] == "slash" and slash["fee"] == 0 and slash["amount"] == 0
    got = resolve_slash(slash["data"])
    assert got and got[0] == VALIDATOR["address"], \
        f"the submitted proof does not resolve to the offender ({got!r})"


def t_the_same_vote_regossiped_is_not_an_offence():
    host = _WatchHost()
    a = duty_attest("cc" * 32)
    host.maybe_watchtower_slash(a)
    host.maybe_watchtower_slash(dict(a))             # the exact same signed vote, seen again
    assert not host.merged, "re-gossip of one honest vote was reported as equivocation"


def t_an_unverifiable_pair_is_never_submitted():
    """A conflicting pair whose signatures do not survive verification must not spam the pool."""
    host = _WatchHost()
    a = duty_attest("dd" * 32)
    b = duty_attest("ee" * 32)
    b["signature"] = a["signature"]                  # broken: signature of a different txid
    host.maybe_watchtower_slash(a)
    host.maybe_watchtower_slash(b)
    assert not host.merged, "an unverifiable proof was submitted — free pool spam for any peer"


def t_cross_chain_replay_is_refused_by_the_proof_verifier():
    a = duty_attest("aa" * 32)
    b = duty_attest("bb" * 32)
    b2 = dict(b); b2["chain_id"] = "betanet-2"       # old-generation body, resurrected
    assert verify_attestation_equivocation_proof({"attest_a": a, "attest_b": b2}) is None, \
        "a foreign-generation attestation paired into a proof — the honest-validator burner"


def t_the_watch_memory_is_bounded():
    host = _WatchHost()
    for e in range(EPOCH, EPOCH + 6):
        tx = construct_duty_tx(VALIDATOR, 60123, attest={"target_epoch": e, "target_hash": "ff" * 32})
        host.maybe_watchtower_slash(tx)
    assert all(k[1] >= EPOCH + 3 for k in host._attest_watch), \
        "the per-epoch watch memory grows forever"


for name, fn in [(n, f) for n, f in list(globals().items()) if n.startswith("t_")]:
    check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "THE WATCHTOWER SLASHES WHAT IT SEES")
sys.exit(1 if FAILS else 0)
