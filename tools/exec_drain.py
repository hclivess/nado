"""Reroll step 5b: apply the UNFINALIZED L1 tail to the exec state, so the carry-forward sees it AT the L1 tip.

The exec node applies only finalized blocks, so it always trails the tip by about the finality depth (~45 blocks) and
can never catch up while L1 is stopped. Those blocks carry real exec ops (dividend claims, bridge and faucet deposits),
and the carry-forward refuses to run over the gap. With every service stopped this replays cursor+1..tip through the
exec node's own `_apply_block`, then saves; the carry-forward then runs with `--l1-tip <the cursor it prints>`.

Run ONLY with nado, nado-exec and nado-watchtower stopped (it reads the stopped node's block store and writes the
exec state file):
    cd /root/nado && python3 tools/exec_drain.py /root/nado/exec_state.json /root
Rehearse on copies first: point both arguments at a scratch HOME holding a copy of index/, blocks/ and the state.
Used for the betanet-8 reroll (2026-09-25): 46 blocks drained, 232997..233042.
"""
import os, sys, asyncio
STATE, HOME = sys.argv[1], sys.argv[2]
os.environ["NADO_EXEC_STATE"] = STATE                            # before ANY exec import: its paths are CWD-relative
os.environ["NADO_EXEC_DA"] = os.path.join(os.path.dirname(STATE), "exec_da")
os.environ["HOME"] = HOME
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
import execnode.execnode as EN
from ops import kv_ops
from ops.block_ops import get_block

kv_ops.init_env()


def block_at(h):
    # by hash, not get_block_number: that one swallows every error into False, and the first drain of the betanet-8
    # reroll "finished" with zero blocks applied because of it
    bh = kv_ops.hash_by_number(h)
    if not bh:
        return None
    b = get_block(bh)
    assert b, f"block {h} is indexed as {bh} but its body is unreadable"
    return b


st = ExecState(STATE)
start = h = int(st.cursor) + 1
loop = asyncio.new_event_loop()
while (b := block_at(h)) is not None:
    assert loop.run_until_complete(EN._apply_block(None, {"default": st}, st, b, verbose=True)), f"exec STALLED at {h}"
    h += 1
st.save()
print(f"DRAINED {start}..{h - 1}; cursor now {st.cursor}")
