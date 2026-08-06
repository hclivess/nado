"""The settle pre-state stash must survive a restart.

MEASURED 2026-08-06 on alphanet-15, one day's skips:

    epoch boundary        55
    records moved         36
    held (prove running)  33
    NO STASHED PRE-STATE  17
    span cap               5

The stash was purely in-memory, so every restart threw it away and the node could not prove ANYTHING until
it had settled again — a full settle cadence (~5 min) of blind spans after every deploy. All 17 were
self-inflicted by restarts, and it is the largest skip class removable WITHOUT a reroll: the other two are
the same records problem and need one.

TRUSTING A FILE HERE IS SAFE because the prover already treats the stash as untrusted input — it requires
the payload's cursor to equal L1's JUSTIFIED tip, and the finished proof must both extend the L1-justified
root and reproduce this node's real root, so a wrong stash yields NO proof rather than a bad one. On top of
that _stash_load refuses any payload that does not describe itself.

The checks below run against the module's own helpers with a throwaway STATE_PATH; they never touch the
live chain DB (importing execnode.execnode would open the live state, so the helpers are exec'd standalone
from source — see _load_helpers).

Run: python3 tests/test_settle_stash_persist.py
"""
import json
import os
import shutil
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SRC_PATH = os.path.join(ROOT, "execnode", "execnode.py")
SRC = open(SRC_PATH).read()

fails = 0


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


def _load_helpers(state_path):
    """Exec ONLY the stash helpers against a throwaway STATE_PATH.

    Importing execnode.execnode would open the LIVE exec state (and on a validator that is a write txn on
    the running node's data), so the block is sliced out of the source and run in a bare namespace. That
    also means these checks exercise the SHIPPED text, not a copy that can drift."""
    start = SRC.index("_STASH_SEP = ")
    end = SRC.index("# NAMESPACES this node maintains")
    ns = {"os": os, "json": json, "STATE_PATH": state_path, "NAMESPACES": ["default", "toy"],
          "_settled_snapshots": {}, "_settled_history": {}, "_SETTLED_HISTORY_KEEP": 3}
    exec(compile(SRC[start:end], SRC_PATH, "exec"), ns)
    return ns


def _payload(ns_name, cursor, root="ab" * 32):
    return json.dumps({"ns": ns_name, "cursor": cursor, "state_root": root, "state": {"x": cursor}},
                      sort_keys=True)


def t_round_trip():
    d = tempfile.mkdtemp(prefix="stash_")
    try:
        sp = os.path.join(d, "exec_state.json")
        w = _load_helpers(sp)
        w["_stash_persist"]("default", 100, _payload("default", 100))
        r = _load_helpers(sp)
        r["_stash_load"]()
        assert r["_settled_history"]["default"][100] == _payload("default", 100), "payload did not round-trip"
        assert r["_settled_snapshots"]["default"] == _payload("default", 100), "newest was not promoted"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_newest_is_promoted_and_history_is_bounded():
    d = tempfile.mkdtemp(prefix="stash_")
    try:
        sp = os.path.join(d, "exec_state.json")
        w = _load_helpers(sp)
        for c in (10, 20, 30, 40, 50):
            w["_stash_persist"]("default", c, _payload("default", c))
        r = _load_helpers(sp)
        r["_stash_load"]()
        got = sorted(r["_settled_history"]["default"])
        assert got == [30, 40, 50], f"expected the newest 3 kept, got {got}"
        assert json.loads(r["_settled_snapshots"]["default"])["cursor"] == 50, "newest must be promoted"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_a_payload_that_lies_about_itself_is_refused():
    """The whole safety argument is that a stash is untrusted input — pin the self-description check."""
    d = tempfile.mkdtemp(prefix="stash_")
    try:
        sp = os.path.join(d, "exec_state.json")
        w = _load_helpers(sp)
        w["_stash_persist"]("default", 100, _payload("default", 999))     # name says 100, body says 999
        w["_stash_persist"]("default", 101, _payload("toy", 101))         # name says default, body says toy
        r = _load_helpers(sp)
        r["_stash_load"]()
        assert not r["_settled_history"], f"a mismatched payload was accepted: {r['_settled_history']}"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_corrupt_and_foreign_files_are_skipped_not_fatal():
    d = tempfile.mkdtemp(prefix="stash_")
    try:
        sp = os.path.join(d, "exec_state.json")
        w = _load_helpers(sp)
        w["_stash_persist"]("default", 7, _payload("default", 7))
        open(sp + "~stash~default~8.json", "w").write("{not json")
        open(sp + "~stash~nosuchns~9.json", "w").write(_payload("nosuchns", 9))
        open(sp + "~stash~default~notanint.json", "w").write(_payload("default", 9))
        r = _load_helpers(sp)
        r["_stash_load"]()
        assert sorted(r["_settled_history"].get("default", {})) == [7], \
            f"only the good entry should load, got {r['_settled_history']}"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_clear_removes_memory_and_disk():
    d = tempfile.mkdtemp(prefix="stash_")
    try:
        sp = os.path.join(d, "exec_state.json")
        w = _load_helpers(sp)
        w["_stash_persist"]("default", 1, _payload("default", 1))
        w["_stash_load"]()
        assert w["_settled_history"], "precondition: something is stashed"
        w["_stash_clear"]()
        assert not w["_settled_history"] and not w["_settled_snapshots"], "memory not cleared"
        import glob
        assert not glob.glob(sp + "~stash~*"), "disk not cleared"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_the_generation_wipes_reach_the_stash():
    """Stash files MUST sit beside the state file so both reroll wipes sweep them — a stale-generation
    pre-state that survived a reroll would be replayed against a fresh chain."""
    d = tempfile.mkdtemp(prefix="stash_")
    try:
        sp = os.path.join(d, "exec_state.json")
        w = _load_helpers(sp)
        w["_stash_persist"]("default", 5, _payload("default", 5))
        import glob
        swept = glob.glob(sp + "*")                # exactly what both wipe sites glob
        assert any("~stash~" in p for p in swept), "the boot/reset glob would not reach a stash file"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_call_sites_are_wired():
    assert "_stash_persist(ns, cur, _settled_snapshots[ns])" in SRC, "persist must run on an accepted settle"
    assert "_stash_load()" in SRC.split("def _stash_load")[-1], "the loader must be CALLED at startup"
    assert "_stash_clear()" in SRC.split("def _stash_clear")[-1], "the reset path must clear the stash"
    # the loader must run AFTER the boot generation wipe, or it would restore stale-chain payloads
    assert SRC.index("CHAIN_GENERATION bumped") < SRC.rindex("_stash_load()"), \
        "_stash_load() must be called after the generation wipe"


for nm, fn in [("a stash round-trips through disk", t_round_trip),
               ("newest promoted, history bounded", t_newest_is_promoted_and_history_is_bounded),
               ("a payload that lies about itself is refused", t_a_payload_that_lies_about_itself_is_refused),
               ("corrupt/foreign files are skipped, not fatal", t_corrupt_and_foreign_files_are_skipped_not_fatal),
               ("clear removes memory and disk", t_clear_removes_memory_and_disk),
               ("the generation wipes reach the stash", t_the_generation_wipes_reach_the_stash),
               ("all three call sites are wired", t_call_sites_are_wired)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
