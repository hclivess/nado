"""
Snapshot digest normalization + snapshot-hash pool alarm (ops/snapshot_ops.py + loops/consensus_loop.py).

THE DEFECT (found live 2026-08-19 by a payload diff at checkpoint 81000): state_root IDENTICAL across
the fleet, snapshot_hash split anyway — the ONLY divergence was 3 meta rows of 156277:
hard_finality (node-LOCAL pacing: backstop vs FFG boundary) and index_pruned_below_num/hash
(retention POLICY: archive prunes less than rolling). All three were introduced AFTER the payload
exclusion set was written and never added — the h10047 lesson applied to the DIGEST instead of the
root. A split digest splits agree_snapshot's bootstrap vote for no state reason. And NOTHING compared
snapshot hashes across the fleet (the alphanet-7 h76000 split shipped the same way) — now the
consensus loop CRITICAL-logs the moment our advertised checkpoint hash is out of majority.

  1. behavioral: two triple-lists differing ONLY in the three node-local rows digest IDENTICALLY;
     differing in any consensus row still digests apart
  2. pins: the exclusion set carries all five node-local keys; the consensus loop compares
     (snapshot_height, snapshot_hash) across the status pool and alarms out-of-majority

Run: python3 tests/test_snapshot_digest_pool.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ops.snapshot_ops as S

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def _base():
    return [("accounts", b"addr1", b"100"), ("meta", b"chain_head", b"h"),
            ("meta", b"hard_finality", b"80390"),
            ("meta", b"index_pruned_below_num", b"16954"),
            ("meta", b"index_pruned_below_hash", b"56954"),
            ("meta", b"finalized_height", b"80955"), ("meta", b"pruned_below", b"7")]


def t1_node_local_rows_do_not_split_the_digest():
    a = _base()
    b = [("accounts", b"addr1", b"100"), ("meta", b"chain_head", b"h"),
         ("meta", b"hard_finality", b"80400"),
         ("meta", b"index_pruned_below_num", b"30954"),
         ("meta", b"index_pruned_below_hash", b"70954"),
         ("meta", b"finalized_height", b"80999"), ("meta", b"pruned_below", b"9")]
    assert S.state_digest(a, 81000) == S.state_digest(b, 81000), \
        "node-local pacing/policy rows must not enter the transfer digest"
    c = list(a); c[0] = ("accounts", b"addr1", b"101")
    assert S.state_digest(a, 81000) != S.state_digest(c, 81000), \
        "a consensus row difference must still split the digest"


def t2_pin_exclusion_set():
    for k in (b"finalized_height", b"pruned_below", b"hard_finality",
              b"index_pruned_below_num", b"index_pruned_below_hash"):
        assert k in S.SNAPSHOT_PAYLOAD_EXCLUDED_META_KEYS, f"{k} must be payload-excluded"


def t3_pin_pool_alarm():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "loops", "consensus_loop.py")).read()
    assert "SNAPSHOT HASH OUT OF MAJORITY" in src and "snapshot_hash" in src
    i = src.index("SNAPSHOT-HASH POOL")
    seg = src[i:i + 3000]
    assert "latest_final_checkpoint_height" in seg and "load_checkpoint_manifest" in seg
    assert "len(_best) * 2 > _total" in seg, "majority = strictly more than half"
    assert "_snap_pool_logged" in seg, "alarm must be once-per-(height,hash)"


check("node-local rows do not split the digest; consensus rows still do", t1_node_local_rows_do_not_split_the_digest)
check("pin: all five node-local meta keys payload-excluded", t2_pin_exclusion_set)
check("pin: snapshot-hash pool alarm wired in the consensus loop", t3_pin_pool_alarm)
print(f"\n{'ALL PASS' if fails == 0 else f'{fails} FAILURE(S)'}")
sys.exit(1 if fails else 0)
