"""
Frozen-quorum auto-recovery — anchor-verified adoption (execnode/execnode.py).

THE DEADLOCK (betanet-3, 2026-08-19): three attesters (29/28/20 shares), each on its own lineage,
no same-root subset above 2/3 of active shares. Waiting cannot end it; the last justified checkpoint
proved irreproducible (three replay attempts missed, incl. one from journal-recorded accrual
boundaries — /get_open_weights recomputes old epochs from TODAY's pool state). The breaker: adopt
the ANCHOR's lineage, verified against the anchor's ML-DSA-signed settle attestation replayed from a
FINALIZED L1 block (inclusion = L1 already verified the signature). The anchor is the operator whose
pushed code the fleet auto-runs — no trust the fleet doesn't already extend.

  1. behavioral: anchored-pair extraction — only (cursor, root) pairs the anchor signed count
  2. pins: adoption requires the frozen-quorum threshold; snapshot cursor <= finalized (the
     reroll-stranded detector would otherwise WIPE the adopter); one adoption per episode;
     the anchor node itself never adopts; fetches are by-cursor
  3. pins: adoption stamps provenance + resets derived globals + is loud
  4. state: anchor_adopted_at survives a save/restore roundtrip

Run: python3 tests/test_exec_anchor_recovery.py
"""
import os, sys, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

_SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "execnode", "execnode.py")).read()
_FN = _SRC[_SRC.index("async def _anchor_adopt"):_SRC.index("async def tail_loop")]


def t1_anchored_pair_extraction():
    # mirror of the comprehension in _anchor_adopt: only pairs carrying the anchor's FULL sender count
    ANCHOR = "ebd27698662f14ee2389e509781d5ff57487f4289a4d67"
    observed = {80765: {"aa" * 32: {ANCHOR}},
                80800: {"bb" * 32: {"f58d6c7781a089afd83c935f4c7659aef7ebeb6a3b54d2"}},
                80810: {"cc" * 32: {ANCHOR, "other"}, "dd" * 32: {"other2"}}}
    anchored = {(c, r) for c, roots in observed.items()
                for r, senders in roots.items() if ANCHOR in senders}
    assert anchored == {(80765, "aa" * 32), (80810, "cc" * 32)}


def t2_pin_guards():
    assert 'SETTLE_ANCHOR = "ebd27698662f14ee2389e509781d5ff57487f4289a4d67"' in _SRC
    assert "st.cursor - settled_cur < ANCHOR_STALL_CURSORS" in _FN, "must require a FROZEN quorum"
    assert "snap_cur > finalized" in _FN and "stranded" in _FN, \
        "must never adopt above local finality (reset-to-genesis hazard)"
    assert "st.cursor - st.anchor_adopted_at < ANCHOR_STALL_CURSORS" in _FN, \
        "one adoption per freeze episode"
    assert "_anchor_self()" in _FN and "return" in _FN.split("_anchor_self()")[1][:40], \
        "the anchor node itself must never adopt"
    assert "&cursor={want}" in _FN, "fetch must be by observed anchored cursor"
    assert "SETTLE_ANCHOR in senders" in _FN, "verification binds to the anchor's on-chain attestation"
    assert "(snap_cur, root) not in anchored" in _FN, "payload root must match the attested pair"
    assert "DIV_ACCRUAL_CANONICAL_FROM" not in _FN, \
        "gen 22: every checkpoint is canonical-era (per-block accrual from cursor 0); the era filter is gone"


def t3_pin_adoption_effects():
    assert "st.bootstrapped = True" in _FN and "st.replay_gap = False" in _FN \
           and "st.anchor_adopted_at = st.cursor" in _FN and "st.attested = {}" in _FN
    assert "prov_states = None" in _FN and "_prov_key = None" in _FN, "derived caches must reset"
    assert "ANCHOR ADOPTION" in _FN, "adoption must be loud"
    tl = _SRC[_SRC.index("async def tail_loop"):]
    assert "_anchor_adopt(session, finalized)" in tl and "ANCHOR_ADOPT_EVERY" in tl, \
        "tail loop must run the throttled recovery probe"


def t4_anchor_adopted_at_roundtrip():
    st = ExecState(tempfile.mktemp(prefix="nado_anchor_", suffix=".json"))
    st.cursor = 5
    st.anchor_adopted_at = 81000
    st.save()
    st2 = ExecState(st.path)
    assert st2.anchor_adopted_at == 81000
    # legacy payloads default to -1
    import json
    d = json.load(open(st.path)); d.pop("anchor_adopted_at")
    json.dump(d, open(st.path, "w"))
    assert ExecState(st.path).anchor_adopted_at == -1


check("anchored-pair extraction binds to the anchor's full sender", t1_anchored_pair_extraction)
check("pin: freeze threshold / finality guard / one-per-episode / anchor never adopts / by-cursor", t2_pin_guards)
check("pin: adoption stamps provenance, resets caches, is loud, probe wired", t3_pin_adoption_effects)
check("anchor_adopted_at roundtrip + legacy default", t4_anchor_adopted_at_roundtrip)
print(f"\n{'ALL PASS' if fails == 0 else f'{fails} FAILURE(S)'}")
sys.exit(1 if fails else 0)
