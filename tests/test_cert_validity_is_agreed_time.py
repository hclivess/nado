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
  * from the gate: every node — the two honest ones and the re-stamped one — reaches the same verdict, judged at
    agreed_time(anchor): the median of the committee's own duty-tx clocks in committed blocks;
  * a certificate issued AFTER agreed time (agreed time lags ~30 min) is accepted through CERT_NOT_BEFORE_GRACE on every
    node, and an EXPIRED one is refused on every node — the grace never reaches expiry;
  * agreed_time: one sample per sender (its latest), the median (a minority of liars cannot move it out of the honest
    range), junk timestamps ignored, too few senders -> chain_clock, a missing block DEFERS (WindowUnavailable), and the
    cache follows a reorg of the window;
  * the tpm_enrol clock (validation) and its apply (account_ops) read the same value from the gate;
  * the gate is live on gen 27 (29000) and 1 at the next reroll.
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


WIN_HASH = ["22" * 32]                   # the window's last block hash (agreed_time's cache key); a reorg changes it


def duty(sender, ts):
    return {"recipient": "duty", "sender": sender, "timestamp": ts}


def chain_view(anchor_ts, window_txs):
    """One node's view: the anchor block with THIS node's own stamp (same hash everywhere), and the window blocks with
    the committed duty transactions every node reads identically."""
    def lookup(n):
        if n == ANCHOR_N[0]:
            return {"block_number": n, "block_hash": ANCHOR_HASH, "block_timestamp": anchor_ts}
        lo, hi = T.agreed_time_window(ANCHOR_N[0])
        if lo <= n < hi:
            return {"block_number": n, "block_transactions": window_txs.get(n, [])}
        return None
    return lookup


ANCHOR_N = [0]


def use(lookup):
    import ops.block_ops as B
    T.get_block_number = lookup
    B.get_block_hash_by_number = lambda n: WIN_HASH[0]
    T._agreed_time_cache.clear()


def main():
    src = open(os.path.join(ROOT, "protocol.py")).read()
    check("the gate is LIVE on gen 27 at a height ahead of the fleet's adoption",
          P.CHAIN_GENERATION == 27 and "CERT_CLOCK_HEIGHT = 29000 if CHAIN_GENERATION == 27 else 1" in src, LIVE_GATE)

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

    # ---- AFTER: the gate in force --------------------------------------------------------------------------------
    P.CERT_CLOCK_HEIGHT = 1
    try:
        h = 30000
        ANCHOR_N[0] = h - OFF
        lo, hi = T.agreed_time_window(ANCHOR_N[0])
        tx, t_lo, t_hi = statement(h)

        def window(med, liars=()):
            """11 honest senders around `med` (one duty each, some twice), plus liars with absurd clocks."""
            txs = {}
            for i in range(11):
                txs.setdefault(lo + i, []).append(duty(f"v{i:02d}", med - 300 + i * 60))
                if i % 3 == 0:                                 # an earlier duty of the same sender: only its latest counts
                    txs.setdefault(lo + 60 + i, []).append(duty(f"v{i:02d}", med - 5000))
            for j, ts in enumerate(liars):
                txs.setdefault(lo + 100 + j, []).append(duty(f"liar{j}", ts))
            return txs

        def all_nodes(txs):
            out = {}
            for name, ts in (("honest_early", t_lo - 6), ("honest_late", t_hi + 6), ("restamped_0", 0)):
                use(chain_view(ts, txs))
                out[name] = verdict(tx, T.get_block_number)
            return out

        after = all_nodes(window(t_hi + 60))
        for k, v in after.items():
            print(f"      from the gate   {k:14} {v}")
        check("from the gate every node reaches ONE verdict (honest skew, a block a peer re-stamped to 0)",
              len(set(after.values())) == 1 and after["honest_early"] == "accepted:apple", after)

        lagging = all_nodes(window(t_lo - 3600))
        check("a certificate issued an hour AFTER agreed time is accepted on every node (the notBefore grace)",
              len(set(lagging.values())) == 1 and lagging["honest_late"] == "accepted:apple", lagging)
        future = all_nodes(window(t_hi + 40 * 365 * 86400))
        check("an EXPIRED certificate is refused on every node — the grace never reaches expiry",
              len(set(future.values())) == 1 and "outside validity" in future["honest_late"], future)

        # agreed_time itself
        med = 1_790_000_000
        use(chain_view(0, window(med)))
        honest = sorted(med - 300 + i * 60 for i in range(11))
        check("agreed time is the median of distinct senders' LATEST duty clocks",
              T.agreed_time(ANCHOR_N[0]) == honest[5], (T.agreed_time(ANCHOR_N[0]), honest[5]))
        use(chain_view(0, window(med, liars=[med + 10 ** 7] * 5)))
        t5 = T.agreed_time(ANCHOR_N[0])
        check("five liars far in the future (a minority of 16) cannot move it outside the honest range",
              honest[0] <= t5 <= honest[-1], t5)
        use(chain_view(0, window(med, liars=[True, 1.5, "x", 5, 2 ** 50])))
        check("junk timestamps (bool, float, string, pre-2020, far future) are ignored",
              T.agreed_time(ANCHOR_N[0]) == honest[5])
        use(chain_view(0, {lo: [duty("a", med), duty("b", med)]}))
        check("fewer than CERT_CLOCK_MIN_SAMPLES senders falls back to chain_clock (agreed as well)",
              T.agreed_time(ANCHOR_N[0]) == P.chain_clock(hi))
        use(lambda n: None)
        try:
            T.agreed_time(ANCHOR_N[0])
            check("a missing window block DEFERS (WindowUnavailable), never guesses", False)
        except T.WindowUnavailable:
            check("a missing window block DEFERS (WindowUnavailable), never guesses", True)
        use(chain_view(0, window(med)))
        first = T.agreed_time(ANCHOR_N[0])
        T.get_block_number = chain_view(0, window(med + 999))
        WIN_HASH[0] = "33" * 32                                   # a reorg rewrote the window: its last hash changed
        check("the cache follows a reorg of the window (keyed on its last block hash)",
              T.agreed_time(ANCHOR_N[0]) != first)

        # the tpm_enrol clock: validation (_anchor_time) and apply (account_ops) agree
        use(chain_view(0, window(med)))
        got_v, got_a = T._anchor_time({}, h), A._tpm_anchor_time(h)
        check("tpm_enrol validation and apply read the same agreed clock", got_v == got_a == honest[5], (got_v, got_a))
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
