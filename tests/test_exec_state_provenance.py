"""
Exec-state provenance — the settlement-quorum completeness gate (execnode/state.py + execnode.py).

THE BUG CLASS THIS PINS (betanet-3 frozen-quorum incident, 2026-08-19): exec nodes that cold-started
on a pruned L1 silently SKIPPED body-less finalized blocks — blocks that carried the contract deploys
— then diverged from the from-genesis lineage on every state root they ever computed. window_canonical
gates only the RANDOMNESS window against a MOVING retention horizon, so it self-healed with time while
the state stayed wrong, and the divergent nodes kept attesting: /get_settled froze for 11k+ cursors
(8/8 multi-attester cursors disagreed, 0 quorums).

The fix is PERMANENT provenance on ExecState:
  replay_gap    — a body-less finalized block was skipped during replay; the state is a guess. Sticky.
  bootstrapped  — the state was adopted from a checkpoint verified against the L1-settled (cursor, root).
  attested      — cursor -> root memo of our own settle attestations (self-disqualification evidence).
and a state_complete() predicate maybe_settle gates on: never attest a root computed over a gap.

  1. state_complete truth table: genesis floors pass; cold-start floors fail; bootstrap redeems;
     replay_gap fail-stops EVERYTHING (even a bootstrap-redeemed state re-marked after a new gap)
  2. the flags + attested memo survive a save/restore roundtrip
  3. the flags DO NOT touch state_root (it is tree-derived) — flipping them can never fork the quorum
  4. a LEGACY payload (pre-provenance snapshot) restores to clean defaults
  5. source pins: the skip site records the gap; maybe_settle gates on state_complete and
     self-disqualifies on a contradicted attestation; the settle success site feeds the memo;
     both bootstrap paths stamp the provenance; the tail loop runs the auto-repair probe

Run: python3 tests/test_exec_state_provenance.py
"""
import os, sys, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState, _GENESIS_BEACON_FLOOR

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def _st():
    return ExecState(tempfile.mktemp(prefix="nado_execprov_", suffix=".json"))

_SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "execnode", "execnode.py")).read()


def t1_state_complete_truth_table():
    st = _st()
    # fresh (cursor -1): not complete — it has proven nothing yet
    assert st.cursor < 0 and not st.state_complete(), "fresh state must not be complete"
    # from-genesis lineage: cursor advanced, genesis floors
    st.cursor = 100
    st.beacon_floor = _GENESIS_BEACON_FLOOR
    st.blockhash_floor = 0
    assert st.state_complete(), "genesis-clean floors must pass"
    st.blockhash_floor = 1
    assert st.state_complete(), "blockhash_floor 1 (first recorded block) must pass"
    # cold-start floors: this node joined mid-flight — its replay may have missed deploys
    st.blockhash_floor = 400
    assert not st.state_complete(), "cold-start blockhash_floor must fail"
    st.blockhash_floor = 0
    st.beacon_floor = _GENESIS_BEACON_FLOOR + 500
    assert not st.state_complete(), "cold-start beacon_floor must fail"
    # a verified bootstrap redeems cold-start floors (the quorum vouched for the exact root)
    st.bootstrapped = True
    assert st.state_complete(), "quorum-verified bootstrap must redeem cold-start floors"
    # replay_gap fail-stops EVERYTHING — even a bootstrapped state that later skipped a body
    st.replay_gap = True
    assert not st.state_complete(), "replay_gap must override bootstrapped"
    st.bootstrapped = False
    st.beacon_floor = _GENESIS_BEACON_FLOOR
    assert not st.state_complete(), "replay_gap must override genesis floors"


def t2_flags_survive_roundtrip():
    st = _st()
    st.cursor = 42
    st.replay_gap = True
    st.bootstrapped = True
    st.attested = {40: "aa" * 32, 41: "bb" * 32}
    st.save()
    st2 = ExecState(st.path)
    assert st2.replay_gap is True and st2.bootstrapped is True
    assert st2.attested == {40: "aa" * 32, 41: "bb" * 32}, f"attested lost: {st2.attested}"
    assert all(isinstance(k, int) for k in st2.attested), "attested keys must restore as int"


def t3_flags_never_touch_state_root():
    # state_root is derived from the sparse KV/records trees; the provenance flags live only in the
    # persistence payload. If a flag ever leaked into the root, marking a gap would ITSELF fork the
    # quorum — the fix would reintroduce the bug it fixes.
    st = _st()
    st.bridge["ndoX"] = 7
    st._touch()
    r0 = st.state_root()
    st.replay_gap = True
    st.bootstrapped = True
    st.attested = {1: "cc" * 32}
    assert st.state_root() == r0, "provenance flags must NOT change state_root"


def t4_legacy_payload_defaults():
    st = _st()
    st.cursor = 7
    st.save()
    import json
    d = json.load(open(st.path))
    for k in ("replay_gap", "bootstrapped", "attested"):
        d.pop(k, None)                       # simulate a pre-provenance snapshot
    json.dump(d, open(st.path, "w"))
    st2 = ExecState(st.path)
    assert st2.replay_gap is False and st2.bootstrapped is False and st2.attested == {}


def t5_pin_skip_site_records_gap():
    # the body-less-skip branch must mark replay_gap BEFORE advancing the cursor past the hole
    i = _SRC.index('if "block_transactions" not in block:')
    seg = _SRC[i:i + 1600]
    a, b = seg.index("state.replay_gap = True"), seg.index("state.cursor = h")
    assert a < b, "skip site must set replay_gap before advancing the cursor"


def t6_pin_settle_gate_and_self_disqualify():
    i = _SRC.index("async def maybe_settle")
    seg = _SRC[i:_SRC.index("\nasync def ", i + 10)]
    assert "st.state_complete()" in seg, "maybe_settle must gate on state_complete"
    assert "SELF-DISQUALIFIED" in seg and "st.replay_gap = True" in seg, \
        "maybe_settle must self-disqualify when L1 justifies a root contradicting our attestation"
    assert seg.index("st.window_canonical()") < seg.index("st.state_complete()"), \
        "completeness gate sits behind the window gate (both must hold)"
    assert "st.attested[cur] = root" in seg, "settle success must feed the attested memo"


def t7_pin_bootstrap_paths_stamp_provenance():
    for fn in ("_maybe_bootstrap", "_repair_bootstrap"):
        i = _SRC.index(f"async def {fn}")
        seg = _SRC[i:_SRC.index("\nasync def ", i + 10)]
        assert "st.bootstrapped = True" in seg and "st.replay_gap = False" in seg \
               and "st.attested = {}" in seg, f"{fn} must stamp provenance on adopt"
        assert "cand.state_root()" in seg and "get_settled" in seg, \
            f"{fn} must verify the recomputed root against the L1-settled checkpoint"
    # the tail loop must actually run the repair probe, throttled
    tl = _SRC[_SRC.index("async def tail_loop"):]
    assert "_repair_bootstrap(session)" in tl and "_REPAIR_EVERY" in tl, \
        "tail_loop must invoke the throttled auto-repair probe"


check("state_complete truth table (floors / bootstrap / replay_gap)", t1_state_complete_truth_table)
check("provenance flags + attested memo survive save/restore", t2_flags_survive_roundtrip)
check("provenance flags never touch state_root", t3_flags_never_touch_state_root)
check("legacy payload restores to clean defaults", t4_legacy_payload_defaults)
check("pin: skip site records the replay gap", t5_pin_skip_site_records_gap)
check("pin: maybe_settle gates + self-disqualifies + feeds the memo", t6_pin_settle_gate_and_self_disqualify)
check("pin: bootstrap paths stamp provenance; tail runs auto-repair", t7_pin_bootstrap_paths_stamp_provenance)

print(f"\n{'ALL PASS' if fails == 0 else f'{fails} FAILURE(S)'}")
sys.exit(1 if fails else 0)
