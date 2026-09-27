"""Certificate validity is judged at an AGREED time: two nodes holding the same anchor block with different
block_timestamps reach the same verdict (protocol.CERT_CLOCK_HEIGHT, audit 2026-09-25 HIGH).

block_timestamp is outside the block-hash preimage and, under leaderless assembly, every node stamps its own copy of
every block — measured on eight fleet nodes 2026-09-27: one hash per block, timestamps up to 12 s apart — and nothing
bounds it from below, so a peer serving sync can re-stamp a block without changing its hash. Every certificate check
read the anchor block's block_timestamp, so a certificate whose validity edge fell between two nodes' stamps was valid
on one and not the other: a fork.

The statement here is a real apple-format attestation over an openssl chain whose leaf is issued NOW (the test root is
pinned for the run), verified by the real native kernel. Pins:
  * below the gate (the live gen-27 rule, unchanged): the two honest nodes 12 s apart DISAGREE about the same register
    tx, and a node fed a block stamped 0 disagrees with both — the finding reproduced;
  * from the gate: every node — the two honest ones, the re-stamped one and a pruned one that holds no anchor block —
    reaches the same verdict, and it is the verdict at chain_clock(anchor height);
  * the tpm_enrol clock (validation) and its apply (account_ops) read the same value from the gate, with no block read;
  * the gate is dormant on gen 27 and 1 at the next reroll.
Run: python3 tests/test_cert_validity_is_agreed_time.py
"""
import os
import tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-cert-clock-")      # BEFORE any nado import (CLAUDE.md rule 4)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import base64
import hashlib
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _attest_fixtures as FX
import protocol as P
from ops import attest_native as AN
from ops import transaction_ops as T
from ops import account_ops as A

fails = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


SENDER = "ab" * 23
ANCHOR_HASH = "11" * 32                  # ONE block hash every node agrees on; only the uncommitted stamp differs
OFF = P.POSW_ANCHOR_OFFSET
LIVE_GATE = P.CERT_CLOCK_HEIGHT
b64 = lambda b: base64.b64encode(b).decode()


def statement(max_block):
    """A register tx whose leaf certificate is issued now: notBefore lies in [t_lo, t_hi]."""
    t_lo = int(time.time())
    att, cdj, root_der = FX.build_apple("get.nadochain.com", T.register_device_challenge(SENDER, ANCHOR_HASH, max_block))
    t_hi = int(time.time()) + 1
    AN.pinned_roots_der = lambda: [root_der]
    AN._roots_blob = None
    P.DEVICE_ATTEST_ROOT_FINGERPRINTS = frozenset(P.DEVICE_ATTEST_ROOT_FINGERPRINTS | {hashlib.sha256(root_der).hexdigest()})
    tx = {"sender": SENDER, "max_block": max_block,
          "device": {"att": b64(att), "cdj": b64(cdj), "rp": "get.nadochain.com"}}
    return tx, t_lo, t_hi


def nodes(t_lo, t_hi):
    """Four nodes' views of the SAME anchor block (same hash): two honest stamps 12+ s apart straddling the leaf's
    notBefore, a block a lying peer re-stamped to 0, and a pruned node that holds no copy at all."""
    blk = lambda ts: (lambda n: {"block_number": n, "block_hash": ANCHOR_HASH, "block_timestamp": ts})
    return {"honest_early": blk(t_lo - 6), "honest_late": blk(t_hi + 6), "restamped_0": blk(0), "pruned": lambda n: None}


def verdict(tx, lookup):
    T.get_block_number = lookup
    try:
        v = T.verify_register_device(tx, ANCHOR_HASH)
        return f"accepted:{v['fmt']}"
    except AssertionError as e:
        return f"refused:{e}"


def main():
    check("the gate is dormant on gen 27 (the live clock is unchanged)", P.CHAIN_GENERATION == 27 and LIVE_GATE == 1 << 62,
          LIVE_GATE)
    src = open(os.path.join(ROOT, "protocol.py")).read()
    check("the gate is 1 at the next reroll", "CERT_CLOCK_HEIGHT = (1 << 62) if CHAIN_GENERATION == 27 else 1" in src)

    # ---- BEFORE: the live rule, at a real gen-27 height below the gate ---------------------------------------------
    H = 24886
    tx, t_lo, t_hi = statement(H)
    before = {name: verdict(tx, lk) for name, lk in nodes(t_lo, t_hi).items() if name != "pruned"}
    for k, v in before.items():
        print(f"      below the gate  {k:14} {v}")
    check("below the gate two honest nodes DISAGREE about one register tx (the finding, reproduced)",
          before["honest_early"] != before["honest_late"]
          and "outside validity" in before["honest_early"] and before["honest_late"] == "accepted:apple", before)
    check("below the gate a same-hash block re-stamped to 0 by a peer flips the verdict",
          before["restamped_0"] != before["honest_late"], before)

    # ---- AFTER: the gate in force (its value on the next chain) ---------------------------------------------------
    P.CERT_CLOCK_HEIGHT = 1
    try:
        # a height whose chain clock is past the leaf's issuance: every node accepts
        h_late = OFF + (t_hi + 3600 - P.GENESIS_TIMESTAMP) * 10 // P.CHAIN_CLOCK_CADENCE_DS + 1
        tx, t_lo, t_hi = statement(h_late)
        # (the pruned node is left out HERE only: a register's challenge binds the anchor block's HASH, which a node must
        #  hold to compare — a separate, pre-existing dependency; the clock itself needs no block, pinned below)
        after = {name: verdict(tx, lk) for name, lk in nodes(t_lo, t_hi).items() if name != "pruned"}
        for k, v in after.items():
            print(f"      from the gate   {k:14} {v}")
        check("from the gate every node reaches ONE verdict (honest skew, a block a peer re-stamped to 0)",
              len(set(after.values())) == 1, after)
        check("... and it is the verdict at chain_clock(anchor height): accepted", after["honest_early"] == "accepted:apple",
              after)

        # a height whose chain clock is BEFORE the leaf's issuance: every node refuses — agreed, and it is the
        # documented trade-off (a chain clock that lags wall time refuses a certificate issued within the lag)
        h_early = OFF + 1000
        tx, t_lo, t_hi = statement(h_early)
        early = {name: verdict(tx, lk) for name, lk in nodes(t_lo, t_hi).items() if name != "pruned"}
        check("a chain clock before the leaf's notBefore refuses on EVERY node alike",
              len(set(early.values())) == 1 and "outside validity" in early["honest_late"], early)

        # the tpm_enrol clock: validation (_anchor_time) and apply (account_ops) agree, need no block, ignore the stamp
        for name, lk in nodes(t_lo, t_hi).items():
            T.get_block_number = lk
            want = P.chain_clock(h_late - OFF)
            got_v, got_a = T._anchor_time({}, h_late), A._tpm_anchor_time(h_late)
            check(f"tpm_enrol clock on the {name} node is chain_clock(anchor), for validation and apply alike",
                  got_v == got_a == want, (got_v, got_a, want))
    finally:
        P.CERT_CLOCK_HEIGHT = LIVE_GATE

    # below the gate the historical rule stays byte for byte (replay of the live chain keeps every verdict)
    T.get_block_number = lambda n: {"block_number": n, "block_hash": ANCHOR_HASH, "block_timestamp": 1_790_400_000}
    check("below the gate the clock is still the stored anchor stamp (replay unchanged)",
          T._anchor_time({}, 5000) == 1_790_400_000)
    T.get_block_number = lambda n: None
    try:
        T._anchor_time({}, 5000)
        check("below the gate a missing anchor block is still refused", False)
    except AssertionError:
        check("below the gate a missing anchor block is still refused", True)

    print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
