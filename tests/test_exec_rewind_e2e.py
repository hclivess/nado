"""END-TO-END: the exec node rewinds to a checkpoint and re-follows L1 after a finality revert.

The pure pieces (detectors, ladder retention, rewind target, recovery gate) are tested in
test_exec_finality_revert_probe.py. This drives the REAL executor pieces — _ckpt_maybe_persist, _ckpt_list,
_find_fork_point (against a fake L1), _rewind_to, _recover_from_revert — on a throwaway exec state, because
those only otherwise run during a live revert on a node that is already in trouble.

Scenario: exec applied blocks 0..1200 on chain A (checkpointing as it crossed rungs). L1 re-anchors: it now
carries chain A up to 900 and chain B from 901. Expected: the fork point is found at 900, the node rewinds to
the newest common checkpoint at or below 900, its cursor is <= 900, block_hashes above the checkpoint are
gone, checkpoints/stash above it are gone, and STRANDED is clear. Then the no-checkpoint case: fork point
below every checkpoint, truncated archive, no bootstrap -> STRANDED recorded and NOTHING wiped.

Isolation: re-execs itself with HOME + NADO_EXEC_STATE + NADO_EXEC_DA in a scratch dir before importing.
Run: python3 tests/test_exec_rewind_e2e.py
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile

if os.environ.get("_EX_REWIND_CHILD") != "1":
    tmp = tempfile.mkdtemp(prefix="ex_rewind_")
    env = dict(os.environ, HOME=tmp, _EX_REWIND_CHILD="1", NADO_ALLOW_PYTHON_KERNELS="1",
               PYTHONDONTWRITEBYTECODE="1", NADO_EXEC_STATE=os.path.join(tmp, "exec_state.json"),
               NADO_EXEC_DA=os.path.join(tmp, "exec_da"))
    r = subprocess.run([sys.executable, os.path.abspath(__file__)], env=env)
    sys.exit(r.returncode)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import execnode.execnode as X          # noqa: E402

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


def H(chain, h):
    return f"{chain}{h:08x}".ljust(64, "0")


# ---- drive the real state to cursor 1200 on chain A, checkpointing on the way ------------------------
st = X.state
assert st.cursor == -1, f"fresh state expected, cursor {st.cursor}"
for h in range(0, 1201):
    prev = st.cursor
    st.cursor = h
    st.record_block_hash(h, H("A", h))
    X._ckpt_maybe_persist(prev, st.cursor)
st.save()

# ---- a fake L1: chain A up to 900, chain B from 901; status advertises a re-anchor snapshot at 1000(B)
FORK = 900
def l1_hash(h):
    return H("A", h) if h <= FORK else H("B", h)

async def fake_get_json(session, path):
    if path.startswith("/get_block_number?number="):
        num = int(path.split("=")[1].split("&")[0])
        return {"block_number": num, "block_hash": l1_hash(num)}
    return {}
X._get_json = fake_get_json
STATUS = {"latest_block_height": 1300, "finalized_height": 1250, "snapshot_height": 1000,
          "snapshot_hash": H("B", 1000), "earliest_block_height": 56735}


def t_checkpoints_were_written_as_rungs_were_crossed():
    cks = X._ckpt_list()
    assert "default" in cks and cks["default"], "no rewind checkpoints written"
    assert max(cks["default"]) <= 1200
    assert any(c <= FORK for c in cks["default"]), f"no checkpoint at or below the fork: {cks['default']}"


def t_detectors_fire_on_the_reanchor():
    assert X.linkage_broken(st.block_hashes, 1201, {"parent_hash": H("B", 1200)}), "B's 1201 must not chain onto our A-1200"
    assert not X.linkage_broken(st.block_hashes, 901, {"parent_hash": H("A", 900)}), "B's 901 chains onto A-900 fine"


def t_fork_point_is_found_by_binary_search():
    fp = asyncio.run(X._find_fork_point(None, st.block_hashes, STATUS["latest_block_height"]))
    assert fp == FORK, f"fork point {fp} != {FORK}"


rewound_to = {}
def t_recovery_rewinds_below_the_fork_and_clears_stale_artifacts():
    cks_before = X._ckpt_list()["default"]
    asyncio.run(X._recover_from_revert(None, STATUS, "test"))
    assert not X.STRANDED, f"stranded after a rewind that should have succeeded: {X.STRANDED}"
    assert X.state.cursor <= FORK, f"cursor {X.state.cursor} still above the fork point"
    rewound_to["c"] = X.state.cursor
    assert X.state.cursor == max(c for c in cks_before if c <= FORK), "did not rewind to the newest checkpoint at/below the fork"
    assert all(h <= X.state.cursor for h in X.state.block_hashes), "block hashes above the rewind point survived"
    assert all(c <= X.state.cursor for c in X._ckpt_list().get("default", [])), "checkpoints above the rewind point survived"
    # the state on disk agrees with the state in memory
    on_disk = json.load(open(X.STATE_PATH))
    assert int(on_disk.get("cursor", -9)) == X.state.cursor, "rewound state was not persisted"


def t_the_rewound_state_refollows_l1_from_the_checkpoint():
    """The tail loop replays from cursor+1; here just prove the next block CHAINS onto what we hold."""
    c = X.state.cursor
    assert not X.linkage_broken(X.state.block_hashes, c + 1, {"parent_hash": l1_hash(c)}), \
        "L1's next canonical block does not chain onto the rewound state"


def t_a_settle_stash_entry_serves_as_a_rewind_rung():
    """THE LIVE CASE (2026-08-17 21:1x): the first real finality revert hit while the checkpoint ladder
    was one rung old — nothing at/below the fork point — but the settle stash held the fork point's exact
    cursor. The stash is the same self-describing payload, so it must count as a rung."""
    c = X.state.cursor
    stash_cur = c - 7
    payload = json.dumps({"ns": "default", "cursor": stash_cur,
                          "state_root": X.state.state_root(), "state": X.state._snapshot()})
    open(X._stash_path("default", stash_cur), "w").write(payload)
    srcs = X._rewind_sources()
    assert stash_cur in srcs.get("default", {}), "a stash entry is invisible to the rewind sources"
    t = X.rewind_target({ns: list(cs) for ns, cs in srcs.items()}, c - 5)
    assert t == stash_cur, f"rewind target {t} ignored the stash rung at {stash_cur}"
    os.remove(X._stash_path("default", stash_cur))


def t_checkpoint_beats_stash_on_a_cursor_collision():
    c = X.state.cursor
    ck = json.load(open(X._ckpt_path("default", c))) if os.path.exists(X._ckpt_path("default", c)) else None
    payload = json.dumps({"ns": "default", "cursor": c, "state_root": "x", "state": {}})
    open(X._stash_path("default", c), "w").write(payload)
    ckp = json.dumps({"ns": "default", "cursor": c, "state_root": X.state.state_root(),
                      "state": X.state._snapshot()})
    open(X._ckpt_path("default", c), "w").write(ckp)
    srcs = X._rewind_sources()
    assert srcs["default"][c] == X._ckpt_path("default", c), "stash shadowed a dedicated checkpoint"
    os.remove(X._stash_path("default", c))
    if ck is None:
        os.remove(X._ckpt_path("default", c))


def t_no_checkpoint_below_the_fork_means_stranded_not_wiped():
    """Fork point below every checkpoint + truncated archive + no bootstrap: keep state, record STRANDED."""
    # make L1 disagree from height 1 (deep fork), keep archive truncated, no bootstrap
    global FORK
    FORK = 0
    contracts_before = len(X.state.contracts)
    cursor_before = X.state.cursor
    X.BOOTSTRAP = ""
    asyncio.run(X._recover_from_revert(None, STATUS, "deep"))
    assert X.STRANDED, "a revert with no recovery source must record itself as stranded"
    assert X.state.cursor == cursor_before, "state was rewound/wiped with no valid target"
    assert len(X.state.contracts) == contracts_before
    assert os.path.exists(X.STATE_PATH), "state file was deleted"


for name, fn in [(n, f) for n, f in list(globals().items()) if n.startswith("t_")]:
    check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "EXEC REWINDS TO A CHECKPOINT AND RE-FOLLOWS L1")
sys.exit(1 if FAILS else 0)
