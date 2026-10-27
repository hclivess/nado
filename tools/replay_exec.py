#!/usr/bin/env python3
"""EXEC REPLAY PROOF — prove a source-tree change alters no EXEC-LAYER result (the exec root at every height), the twin
of tools/replay_chain.py, which replays L1 and never computes an exec root. Needed for G9 (doc/stwo-migration.md 9.7):
the Goldilocks deletion edits execnode/ as much as ops/.

    python3 tools/replay_exec.py fetch   <blocks.json> --out accrual.json [--relay URL]
    python3 tools/replay_exec.py replay  <tree> <blocks.json> <accrual.json> --out result.json [--upto N] [--work DIR]
    python3 tools/replay_exec.py compare <resultA.json> <resultB.json>

fetch    GETs every dividend epoch's accrual inputs (/get_dividend_inflow, /get_open_weights) the blocks reach. Never
         POSTs, never imports node code. blocks.json is replay_chain.py's `fetch` output (bodies 0..N).
replay   Runs a CHILD (`_child`) with cwd=<tree>, PYTHONPATH=<tree>, a throwaway HOME with NADO_EXEC_STATE / NADO_EXEC_DA
         inside it, every inherited NADO_* variable removed, and every outbound connection refused. The child builds the
         exec layer exactly as execnode.py boots one (a fresh ExecState + exec_genesis.apply) and applies each block the
         way execnode._apply_block_inner does: the canonical dividend accrual owed before it, rules_at(h), block_apply.begin,
         the wide pool's depth for the block (trees that still have one), block_apply.dispatch, block_apply.close. A block carrying a DA-resolved op
         the exec node would have fetched (field_transfer / private_call not refused at its height) stops the replay:
         the replay holds no DA, and guessing would be a different chain. Records the exec root after every block.
compare  The first height where the roots differ, or IDENTICAL through the last common height.

Run it FROM A WORKTREE, never from the live checkout (root never executes code from the checkout — doc/jobs.md); `replay`
refuses a tree inside the live checkout. Everything it writes goes under --work, never into a tree.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

LIVE = "/srv/nado-home/nado"


def _get(url):
    """GET JSON, paced and patient: the node rate-limits (HTTP 429) a burst of reads, and a fetch is a one-off"""
    import urllib.error
    import urllib.request
    for attempt in range(8):
        time.sleep(0.2)
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError(f"{url}: still rate-limited after 8 tries")


def cmd_fetch(blocks_path, out, relay):
    blocks = json.load(open(blocks_path))
    blocks = blocks["blocks"] if isinstance(blocks, dict) and "blocks" in blocks else blocks
    top = max(int(b["block_number"]) for b in blocks)
    from_epoch_len = 60                      # protocol.EPOCH_LENGTH (not imported: fetch imports no node code)
    res = {}
    for e in range(0, top // from_epoch_len):
        inflow = _get(f"{relay}/get_dividend_inflow?epoch={e}")["inflow"]
        weights = _get(f"{relay}/get_open_weights?epoch={e}")["weights"]
        res[str(e)] = [int(inflow), weights]
    json.dump({"relay": relay, "epochs": res}, open(out, "w"))
    print(f"wrote {out}: {len(res)} epochs")


def cmd_replay(tree, blocks_path, accrual_path, out, upto, work):
    tree = os.path.realpath(tree)
    if tree == LIVE or tree.startswith(LIVE + os.sep):
        sys.exit("refusing to run code from the live checkout: replay a worktree")
    work = work or tempfile.mkdtemp(prefix="nado-replay-exec-")
    os.makedirs(work, exist_ok=True)
    home = tempfile.mkdtemp(prefix="home-", dir=work)
    env = {k: v for k, v in os.environ.items() if not k.startswith("NADO_")}
    env.update(HOME=home, PYTHONPATH=tree, NADO_EXEC_STATE=os.path.join(home, "exec_state.json"),
               NADO_EXEC_DA=os.path.join(home, "exec_da"))
    t = time.time()
    r = subprocess.run([sys.executable, os.path.abspath(__file__), "_child", os.path.abspath(blocks_path),
                        os.path.abspath(accrual_path), os.path.abspath(out), str(upto if upto is not None else -1)],
                       cwd=tree, env=env)
    print(f"replay {tree}: rc={r.returncode} in {time.time() - t:.0f}s -> {out}")
    sys.exit(r.returncode)


def _guard_network():
    import socket

    def refuse(self, addr, *a, **k):
        raise OSError(f"replay_exec: outbound connection to {addr!r} refused")
    socket.socket.connect = refuse


def cmd_child(blocks_path, accrual_path, out, upto):
    _guard_network()
    sys.path.insert(0, os.getcwd())
    from execnode import block_apply, exec_genesis
    from execnode.state import ExecState
    from execnode.stark import stark as _stk
    from protocol import EPOCH_LENGTH
    blocks = json.load(open(blocks_path))
    blocks = blocks["blocks"] if isinstance(blocks, dict) and "blocks" in blocks else blocks
    blocks = sorted(blocks, key=lambda b: int(b["block_number"]))
    acc = json.load(open(accrual_path))["epochs"]
    st = ExecState(os.environ["NADO_EXEC_STATE"])
    exec_genesis.apply(st)
    rows = {"genesis_root": st.state_root(), "roots": {}, "stopped": None}
    states = {"default": st}
    # conservative: ANY DA-carried op stops the replay (execnode.py may refuse some at their height, but importing it to
    # ask would boot an exec node; generation 29 has carried none)
    da_ops = {"field_transfer", "private_call"}
    for b in blocks:
        h = int(b["block_number"])
        if upto >= 0 and h > upto:
            break
        if "block_transactions" not in b:
            rows["stopped"] = f"block {h} has no body"
            break
        for tx in b.get("block_transactions", []):
            d = tx.get("data")
            if isinstance(d, dict) and d.get("op") in da_ops and d.get("proof_da") and tx.get("recipient") == "blob":
                rows["stopped"] = f"block {h} carries a DA-resolved {d.get('op')} (the replay holds no DA)"
                break
        if rows["stopped"]:
            break
        while st.last_div_epoch < h // EPOCH_LENGTH - 1:
            E = st.last_div_epoch + 1
            inflow, weights = acc[str(E)]
            st.accrue_dividend_epoch(int(inflow), weights, epoch=E)
            st.last_div_epoch = E
        with _stk.rules_at(h):
            block_apply.begin(states, h)
            if hasattr(st, "wide_enter"):      # a tree from before G9 slice 5 deepens its (empty) wide pool here
                st.wide_enter(h)
            block_apply.dispatch(states, st, b, {}, set(), verbose=False)
            block_apply.close(states, h, b.get("block_hash"))
        rows["roots"][str(h)] = st.state_root()
        if h % 500 == 0:
            print(f"  exec replay at {h}: {rows['roots'][str(h)][:16]}", flush=True)
    json.dump(rows, open(out, "w"))


def cmd_compare(a, b):
    A, B = json.load(open(a)), json.load(open(b))
    if A["genesis_root"] != B["genesis_root"]:
        print(f"DIFFER at genesis: {A['genesis_root'][:16]} vs {B['genesis_root'][:16]}")
        return 1
    common = sorted(set(map(int, A["roots"])) & set(map(int, B["roots"])))
    for h in common:
        if A["roots"][str(h)] != B["roots"][str(h)]:
            print(f"DIFFER at height {h}: {A['roots'][str(h)][:16]} vs {B['roots'][str(h)][:16]}")
            return 1
    print(f"IDENTICAL exec roots through height {common[-1] if common else -1} ({len(common)} heights); "
          f"stopped: {A.get('stopped')!r} / {B.get('stopped')!r}")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == "fetch":
        relay = a[a.index("--relay") + 1] if "--relay" in a else "http://127.0.0.1:9173"
        cmd_fetch(a[1], a[a.index("--out") + 1], relay)
    elif a[0] == "replay":
        upto = int(a[a.index("--upto") + 1]) if "--upto" in a else None
        work = a[a.index("--work") + 1] if "--work" in a else None
        cmd_replay(a[1], a[2], a[3], a[a.index("--out") + 1], upto, work)
    elif a[0] == "_child":
        cmd_child(a[1], a[2], a[3], int(a[4]))
    elif a[0] == "compare":
        sys.exit(cmd_compare(a[1], a[2]))
    else:
        sys.exit(__doc__)
