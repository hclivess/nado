#!/usr/bin/env python3
"""NADO REPLAY PROOF — prove a source-tree change alters no consensus result (doc/reroll.md "What the cleanup deletes").

    python3 tools/replay_chain.py fetch   [--max N] [--out blocks.json] [--relay URL] [--work DIR]
    python3 tools/replay_chain.py replay  <tree> <blocks.json> [--out result.json] [--upto N] [--root-inc trust]
                                          [--deep-sync] [--keep-home] [--work DIR]
    python3 tools/replay_chain.py compare <resultA.json> <resultB.json>

HOW A CLEANUP IS PROVEN (the gen-27 gate cleanup, 2026-09-30: four slices, each IDENTICAL on 5810 live blocks):
  1. `fetch` the live chain once (GETs only).
  2. `git worktree add --detach <dir> main` and `git worktree add --detach <dir2> <candidate>`; in EACH tree replace
     native/ by a symlink to the live checkout's built native/, and run `cargo build --release` in the tree's OWN
     wasm/goldilocks (a symlinked goldilocks build is judged stale and rejects the first settle proof — an
     environment failure, not a consensus one; the replay prints a WARNING when a rejection names the environment).
  3. `replay` both trees (~1 block/s under load; `--root-inc trust` halves it with the same roots), then `compare`.
     "IDENTICAL through height N" is the proof; anything else names the first differing height and field.
Run it FROM A WORKTREE, never from the live checkout (root never executes code from the checkout — doc/jobs.md);
`replay` also refuses a tree inside the live checkout. Everything it writes goes under --work (default: a
"nado-replay" directory in the system temp dir), never into a tree.

fetch   GETs blocks 0..N from the relay's public /get_block (default N = the relay's finalized_height).
        Never POSTs, never imports node code. Do it ONCE; every tree replays the SAME file.

replay  Runs a CHILD process (this file, `_child`) with cwd=<tree>, PYTHONPATH=<tree>, a fresh throwaway
        HOME (NADO_EXEC_STATE / NADO_EXEC_DA inside it), every inherited NADO_* variable removed, and a socket
        guard that refuses every outbound connection. The child:
          1. builds genesis exactly as nado.py does on a fresh node (make_folders -> make_genesis with
             protocol GENESIS_ADDRESS / TREASURY_GENESIS / GENESIS_TIMESTAMP, seeded from the tree's
             genesis_data/*.dat) and checks block 0's hash == the downloaded block 0;
          2. constructs the node's REAL MemServer, REAL ConsensusClient and REAL CoreClient (threads never
             started, so there are no peers and no network), and feeds every downloaded block through
             CoreClient.produce_block(block, remote=True, remote_peer=...) — the remote-block path: rebuild,
             rebuilt-hash == claimed-hash, verify (timestamp, reward, producer draw, weight, L1 state root,
             L2 settled commitment, auth commitment, tx validation) and incorporate;
          3. records per height: accepted, rebuilt block_hash, claimed hash, the L1 state root after the
             block (snapshot_ops.l1_state_root), the L2 settled header commitment after the block, the
             error text on rejection, ERROR-level log lines, blocked network attempts, and wall time.
        Stops at the first rejected block (nothing after it can link).

compare Reports the first height where acceptance / rebuilt hash / L1 root / L2 commitment differ, or
        "IDENTICAL through height N".
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

DEFAULT_WORK = os.path.join(tempfile.gettempdir(), "nado-replay")   # results, homes, blocks: never inside a tree
DEFAULT_RELAY = "http://127.0.0.1:9173"
DEFAULT_PYTHON = "/srv/nado-home/nado/nado_venv/bin/python"     # the interpreter systemd runs the node with
LIVE = "/srv/nado-home/nado"


# ------------------------------------------------------------------------------------------------ fetch
def cmd_fetch(a):
    import http.client
    import urllib.parse
    u = urllib.parse.urlparse(a.relay)
    conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=30)

    def get(path):
        for attempt in range(5):
            try:
                conn.request("GET", path)                 # GET ONLY — the harness never writes to a node
                r = conn.getresponse()
                body = r.read()
                if r.status != 200:
                    raise RuntimeError(f"HTTP {r.status} for {path}: {body[:200]!r}")
                return json.loads(body)
            except (http.client.HTTPException, OSError) as e:
                conn.close()
                time.sleep(1 + attempt)
                last = e
        raise RuntimeError(f"GET {path} failed: {last}")

    status = get("/status")
    fin = int(status.get("finalized_height") or 0)
    n = fin if a.max is None else min(fin, int(a.max))
    if int(status.get("earliest_block_height") or 0) != 0:
        sys.exit(f"relay's history starts at {status.get('earliest_block_height')} — need an archive from genesis")
    t0 = time.time()
    blocks = []
    for h in range(0, n + 1):
        b = get(f"/get_block?number={h}")
        if not isinstance(b, dict) or int(b.get("block_number", -1)) != h:
            sys.exit(f"relay returned a bad body for height {h}: {str(b)[:200]}")
        if h and b.get("parent_hash") != blocks[-1]["block_hash"]:
            sys.exit(f"height {h} does not link to {h-1} (parent {b.get('parent_hash')}) — the relay reorged "
                     f"mid-fetch; fetch again (default N is the finalized height for exactly this reason)")
        blocks.append(b)
        if h % 500 == 0:
            print(f"  fetched {h}/{n}", flush=True)
    meta = {"relay": a.relay, "fetched_at": int(time.time()), "finalized_height": fin, "n": n,
            "chain_id": status.get("chain_id"), "genesis_hash": status.get("genesis_hash"),
            "relay_commit": status.get("running_commit"), "relay_tip": status.get("latest_block_height")}
    if blocks[0]["block_hash"] != status.get("genesis_hash"):
        sys.exit("block 0 != the relay's advertised genesis_hash")
    a.out = a.out or os.path.join(a.work, "blocks.json")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    tmp = a.out + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"meta": meta, "blocks": blocks}, f)
    os.replace(tmp, a.out)
    print(f"wrote {a.out}: blocks 0..{n} ({len(blocks)} bodies) in {time.time()-t0:.1f}s; meta={meta}")


# ------------------------------------------------------------------------------------------------ replay
def cmd_replay(a):
    tree = os.path.realpath(a.tree)
    blocks = os.path.realpath(a.blocks)
    if tree == os.path.realpath(LIVE) or tree.startswith(os.path.realpath(LIVE) + os.sep):
        sys.exit("refusing to replay inside the LIVE checkout — use a worktree")
    for need in ("genesis.py", "loops/core_loop.py", "genesis_data"):
        if not os.path.exists(os.path.join(tree, need)):
            sys.exit(f"{tree} is not a node tree (missing {need})")
    work = os.path.realpath(a.work)
    if work == tree or work.startswith(tree + os.sep):
        sys.exit("refusing a --work directory inside the tree being replayed (it must stay byte-for-byte as checked out)")
    out = os.path.realpath(a.out or os.path.join(work, f"result-{os.path.basename(tree)}.json"))
    homes = os.path.join(work, "homes")
    os.makedirs(homes, exist_ok=True)
    home = os.path.join(homes, f"{os.path.basename(tree)}-{int(time.time())}-{os.getpid()}")
    os.makedirs(home)
    env = {k: v for k, v in os.environ.items() if not k.startswith("NADO_")}   # no operator knob leaks in
    stripped = sorted(k for k in os.environ if k.startswith("NADO_"))
    env.update({
        "HOME": home,                                                  # ASSIGNED, never setdefault
        "NADO_EXEC_STATE": os.path.join(home, "exec_state.json"),     # the exec node's CWD-relative paths
        "NADO_EXEC_DA": os.path.join(home, "exec_da"),
        "PYTHONPATH": tree,
        "PYTHONDONTWRITEBYTECODE": "1",                               # leave the tree byte-for-byte as checked out
        "PYTHONHASHSEED": "0",
    })
    env.pop("NADO_TESTNET", None)
    if a.root_inc:
        # snapshot_ops._root_inc_mode: verify (default: incremental root cross-checked by a full walk every block,
        # the WALK's root used) | trust (incremental only, walk every NADO_ROOT_INC_VERIFY_EVERY roots; ~2x faster,
        # what the live relay runs) | off (walk only). Every mode still has verify_block enforce root == the
        # block's committed state_root, so a wrong root rejects the next block in any mode.
        env["NADO_ROOT_INC"] = a.root_inc
    commit = subprocess.run(["git", "-C", tree, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", tree, "status", "--porcelain", "--", ".", ":!native"],
                           capture_output=True, text=True).stdout.strip().splitlines()
    jsonl = out + ".jsonl"
    log = out + ".log"
    cmd = [a.python, os.path.abspath(__file__), "_child", tree, blocks, jsonl, "--work", work]
    if a.upto is not None:
        cmd += ["--upto", str(a.upto)]
    if a.deep_sync:
        cmd += ["--deep-sync"]
    print(f"replay: tree={tree} commit={commit[:12]} dirty_files={len(dirty)} home={home}\n        log={log}",
          flush=True)
    t0 = time.time()
    with open(log, "w") as lf:
        rc = subprocess.run(cmd, cwd=tree, env=env, stdout=lf, stderr=subprocess.STDOUT).returncode
    wall = time.time() - t0
    head, rows = None, []
    if os.path.exists(jsonl):
        with open(jsonl) as f:
            for line in f:
                r = json.loads(line)
                if r.get("kind") == "head":
                    head = r
                elif r.get("kind") == "block":
                    rows.append(r)
                elif r.get("kind") == "tail":
                    head = dict(head or {}, tail=r)
    res = {"tree": tree, "commit": commit, "dirty": dirty, "blocks_file": blocks, "python": a.python,
           "root_inc": a.root_inc or "verify(default)",
           "stripped_env": stripped, "deep_sync": bool(a.deep_sync), "child_rc": rc, "wall_s": round(wall, 1),
           "head": head, "blocks": rows}
    with open(out, "w") as f:
        json.dump(res, f, indent=0)
    acc = sum(1 for r in rows if r["accepted"])
    last = rows[-1] if rows else None
    live_roots = [r for r in rows if "root_eq_live" in r]
    bad_roots = [r["h"] for r in live_roots if not r["root_eq_live"]]
    print(f"replay done rc={rc} in {wall:.1f}s: genesis_ok={head and head.get('genesis_ok')} "
          f"accepted {acc}/{len(rows)} blocks; rebuilt hash == claimed at "
          f"{sum(1 for r in rows if r['hash'] == r['claimed'])}; L1 root == the live chain's committed root at "
          f"{len(live_roots) - len(bad_roots)}/{len(live_roots)} heights"
          + (f" (first mismatch {bad_roots[0]})" if bad_roots else "")
          + (f"; FIRST REJECT at {last['h']}: {last['err']}" if last and not last["accepted"] else "")
          + f"\n        result={out}", flush=True)
    if last and not last["accepted"] and any(s in str(last["err"]) for s in ("native crate", "cannot verify", "network disabled")):
        print("        WARNING: that rejection names the ENVIRONMENT (a native library / network), not a consensus rule "
              "— fix the tree's build (this file's docstring, step 2) before reading it as a difference", flush=True)
    if not a.keep_home:
        shutil.rmtree(home, ignore_errors=True)
    return 0 if (rc == 0 and head and head.get("genesis_ok") and rows and all(r["accepted"] for r in rows)) else 1


# ------------------------------------------------------------------------------------------------ compare
KEYS = ("accepted", "hash", "root", "l2", "err")


def cmd_compare(a):
    A, B = (json.load(open(p)) for p in (a.a, a.b))
    ha, hb = A.get("head") or {}, B.get("head") or {}
    # A FAILED REPLAY IS NOT A PROOF (found by the first real run of this file in the repo: two children that died on a
    # bad argument replayed 0 blocks each and compared "IDENTICAL through height 0"). Refuse unless both sides built the
    # live genesis and replayed at least one block.
    for name, side, head in (("A", A, ha), ("B", B, hb)):
        if not head or not head.get("genesis_ok") or not side.get("blocks"):
            print(f"NOT A PROOF: side {name} did not replay (child exit {side.get('child_rc')}, genesis_ok="
                  f"{head.get('genesis_ok') if head else None}, {len(side.get('blocks') or [])} blocks) — read its .log")
            return 1
    print(f"A: {A['commit'][:12]} {A['tree']}  ({len(A['blocks'])} blocks)")
    print(f"B: {B['commit'][:12]} {B['tree']}  ({len(B['blocks'])} blocks)")
    if A["blocks_file"] != B["blocks_file"]:
        print(f"WARNING: different blocks files ({A['blocks_file']} vs {B['blocks_file']})")
    for k in ("genesis_hash", "genesis_root", "genesis_ok"):
        if ha.get(k) != hb.get(k):
            print(f"DIFFERS AT GENESIS: {k}: A={ha.get(k)} B={hb.get(k)}")
            return 1
    ra = {r["h"]: r for r in A["blocks"]}
    rb = {r["h"]: r for r in B["blocks"]}
    top = max(list(ra) + list(rb) + [0])
    notes = []
    for h in range(1, top + 1):
        x, y = ra.get(h), rb.get(h)
        if x is None or y is None:
            # a side that STOPPED EARLY ON PURPOSE (--upto) with a clean exit is not a difference
            short, other = (B, "B") if y is None else (A, "A")
            if short["child_rc"] == 0 and (short.get("head") or {}).get("upto") == h - 1:
                print(f"IDENTICAL through height {h - 1} — {other} was replayed only to --upto {h - 1} "
                      f"(the other side continues to {top})")
                return 0
            print(f"DIFFERS AT HEIGHT {h}: present in {'B' if x is None else 'A'} only "
                  f"(A replayed {len(ra)} blocks, B {len(rb)})")
            return 1
        diff = [k for k in KEYS if x.get(k) != y.get(k)]
        if diff:
            print(f"DIFFERS AT HEIGHT {h}:")
            for k in diff:
                print(f"  {k}:\n    A={x.get(k)}\n    B={y.get(k)}")
            if h > 1:
                print(f"  (heights 1..{h-1} identical)")
            return 1
        if x.get("errors") != y.get("errors") or x.get("net") != y.get("net") \
                or x.get("inc_mismatch") != y.get("inc_mismatch"):
            notes.append(h)
    both_ok = all(r["accepted"] for r in A["blocks"]) and all(r["accepted"] for r in B["blocks"])
    print(f"IDENTICAL through height {top}" + ("" if both_ok else " (both sides reject at the same height)")
          + " — accepted, rebuilt hash, L1 state root, L2 settled commitment and error text agree at every height")
    if notes:
        print(f"  note: node-local diagnostics (ERROR log lines / blocked net attempts / inc-root mismatches) "
              f"differ at {len(notes)} height(s), first {notes[:10]} — not consensus outputs, but read them")
    return 0


# ------------------------------------------------------------------------------------------------ child
def _install_net_guard(record):
    """Refuse EVERY outbound connection and name lookup. A consensus path that silently reached the network
    would make a replay depend on the outside world; with this guard it fails loudly and is recorded."""
    import socket
    import traceback

    def _where():
        me = os.path.basename(__file__)
        fr = [f for f in traceback.extract_stack()[:-2] if os.path.basename(f.filename) != me]
        return " <- ".join(f"{os.path.basename(f.filename)}:{f.lineno}:{f.name}" for f in fr[-4:][::-1])

    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex

    def _blocked(what, target):
        record.append(f"{what} {target!r} at {_where()}")
        raise OSError(f"replay harness: network disabled ({what} {target!r})")

    def connect(self, address):
        if self.family == getattr(socket, "AF_UNIX", -1):
            return real_connect(self, address)
        _blocked("connect", address)

    def connect_ex(self, address):
        if self.family == getattr(socket, "AF_UNIX", -1):
            return real_connect_ex(self, address)
        _blocked("connect_ex", address)

    def getaddrinfo(host, *args, **kw):
        _blocked("getaddrinfo", host)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo
    socket.create_connection = lambda address, *a, **k: _blocked("create_connection", address)


def cmd_child(a):
    import logging
    tree, home = a.tree, os.environ["HOME"]
    assert os.path.realpath(home).startswith(os.path.realpath(os.path.join(a.work, "homes"))), home
    assert os.path.realpath(os.getcwd()) == os.path.realpath(tree)
    assert "NADO_TESTNET" not in os.environ
    sys.path.insert(0, tree)
    net = []
    _install_net_guard(net)
    out = open(a.jsonl, "w")

    def emit(obj):
        out.write(json.dumps(obj, separators=(",", ":")) + "\n")
        out.flush()

    with open(a.blocks) as f:
        data = json.load(f)
    chain = data["blocks"]
    upto = len(chain) - 1 if a.upto is None else min(int(a.upto), len(chain) - 1)

    # ---- genesis, exactly as nado.py builds it on a fresh node --------------------------------------------
    t0 = time.time()
    from ops.data_ops import get_home, stamp_chain_generation
    assert get_home() == os.path.join(home, "nado"), get_home()
    import protocol
    from genesis import make_folders, make_genesis
    from config import create_config, config_found
    from ops.key_ops import generate_keys, save_keys, keyfile_found
    from ops.log_ops import get_logger
    logger = get_logger(file="log.log", logger_name="logger")     # nado.py's logger name, inside the temp HOME
    captured = []

    class _Cap(logging.Handler):
        def emit(self, rec):
            if rec.levelno >= logging.ERROR:
                captured.append(rec.getMessage()[:300])
    logger.addHandler(_Cap())

    stamp_chain_generation()
    make_folders()
    # nado.py lets make_genesis create the config, which PROBES THE NETWORK for a public IP. The config's `ip`
    # is non-consensus (the node's advertised address; the genesis block itself uses the ip ARGUMENT, which
    # nothing hashes either), so the harness writes it first with a loopback ip and skips the probe.
    if not config_found():
        create_config(ip="127.0.0.1")
    make_genesis(address=protocol.GENESIS_ADDRESS, balance=protocol.TREASURY_GENESIS,
                 ip="38.242.201.206", port=9173, timestamp=protocol.GENESIS_TIMESTAMP, logger=logger)
    if not keyfile_found():
        save_keys(generate_keys())     # a THROWAWAY identity inside the temp HOME — never anyone's real key

    from memserver import MemServer
    from loops.consensus_loop import ConsensusClient
    from loops.core_loop import CoreClient
    from ops.snapshot_ops import l1_state_root
    from ops import snapshot_ops
    from ops.settlement_ops import settled_header_commitment

    memserver = MemServer(logger=logger)
    consensus = ConsensusClient(memserver=memserver, logger=logger)    # never .start()ed: empty peer pools
    core = CoreClient(memserver=memserver, consensus=consensus, logger=logger)
    if a.deep_sync:
        # what a node syncing from a peer knows: the batch tail's height (core_loop._fetch_sync_batch sets it),
        # which lets verification skip settle-proof STARK checks on blocks buried > FINALITY_DEPTH.
        core._known_tip_height = int(chain[upto]["block_number"])

    g = memserver.latest_block
    groot = l1_state_root()
    head = {"kind": "head", "genesis_hash": g["block_hash"], "expected_genesis": chain[0]["block_hash"],
            "genesis_ok": g["block_hash"] == chain[0]["block_hash"], "genesis_root": groot,
            "chain_generation": protocol.CHAIN_GENERATION, "chain_id": protocol.CHAIN_ID,
            "genesis_s": round(time.time() - t0, 2), "net": list(net), "errors": list(captured),
            "upto": upto, "meta": data.get("meta")}
    emit(head)
    print(f"[harness] genesis {g['block_hash']} ok={head['genesis_ok']} root={groot[:16]} "
          f"({head['genesis_s']}s)", flush=True)
    if not head["genesis_ok"]:
        return 2

    # observe (never alter) what the remote path rebuilt — the value it compares against the claimed hash
    seen = {}
    real_rebuild = core.rebuild_block

    def rebuild_spy(block):
        r = real_rebuild(block)
        seen["rebuilt"] = r.get("block_hash") if isinstance(r, dict) else None
        return r
    core.rebuild_block = rebuild_spy

    rejected = False
    t_start = time.time()
    for h in range(1, upto + 1):
        src = chain[h]
        blk = json.loads(json.dumps(src))                           # a private copy: the node mutates what it is fed
        seen.clear()
        del captured[:]
        n_net = len(net)
        inc0 = snapshot_ops._inc_stats.get("mismatch", 0) if hasattr(snapshot_ops, "_inc_stats") else None
        memserver.last_block_reject = None
        t = time.time()
        err = None
        try:
            ok = bool(core.produce_block(blk, remote=True, remote_peer="replay-harness"))
        except BaseException as e:                                  # produce_block swallows; this is a belt
            ok, err = False, f"RAISED {type(e).__name__}: {e}"
        ms = round((time.time() - t) * 1000)
        if not ok and err is None:
            rej = getattr(memserver, "last_block_reject", None) or {}
            err = rej.get("error") or "produce_block returned False (no reject recorded)"
        tip = memserver.latest_block
        if ok and tip.get("block_number") != h:
            ok, err = False, f"accepted but tip is {tip.get('block_number')}"
        row = {"kind": "block", "h": h, "accepted": ok, "claimed": src["block_hash"],
               "hash": tip["block_hash"] if ok else seen.get("rebuilt"),
               "root": l1_state_root(), "l2": list(settled_header_commitment()),
               "err": err, "errors": list(captured), "net": net[n_net:], "ms": ms}
        if inc0 is not None:
            row["inc_mismatch"] = snapshot_ops._inc_stats.get("mismatch", 0) - inc0
        # diagnostics (NOT compared): the slot's lane and the tx count, to locate a deliberate change
        try:
            from ops.reward_ops import block_lane
            row["lane"] = block_lane(src)
        except Exception as e:
            row["lane"] = f"? {type(e).__name__}"
        row["ntx"] = len(src.get("block_transactions") or [])
        # the LIVE chain's own witness of this root: block h+1 commits state_root = the root after block h
        if h + 1 < len(chain):
            row["root_eq_live"] = row["root"] == chain[h + 1].get("state_root")
        if ok and row["hash"] != src["block_hash"]:
            row["accepted"], row["err"] = False, f"stored hash {row['hash']} != claimed {src['block_hash']}"
            ok = False
        emit(row)
        if h % 250 == 0 or not ok:
            el = time.time() - t_start
            print(f"[harness] h={h} ok={ok} {el:.0f}s ({h/el:.1f} blk/s) root={row['root'][:16]}"
                  + ("" if ok else f" ERR={err}"), flush=True)
        if not ok:
            rejected = True
            break
    emit({"kind": "tail", "replay_s": round(time.time() - t_start, 1), "rejected": rejected,
          "inc_stats": dict(getattr(snapshot_ops, "_inc_stats", {}) or {})})
    out.close()
    return 1 if rejected else 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    f = sp.add_parser("fetch")
    f.add_argument("--max", type=int, default=None, help="cap N (default: the relay's finalized_height)")
    f.add_argument("--work", default=DEFAULT_WORK)
    f.add_argument("--out", default=None, help="default: <work>/blocks.json")
    f.add_argument("--relay", default=DEFAULT_RELAY)
    r = sp.add_parser("replay")
    r.add_argument("tree")
    r.add_argument("blocks")
    r.add_argument("--out")
    r.add_argument("--upto", type=int)
    r.add_argument("--deep-sync", action="store_true")
    r.add_argument("--keep-home", action="store_true")
    r.add_argument("--root-inc", choices=("verify", "trust", "off"), default=None)
    r.add_argument("--python", default=DEFAULT_PYTHON if os.path.exists(DEFAULT_PYTHON) else sys.executable)
    r.add_argument("--work", default=DEFAULT_WORK)
    c = sp.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    ch = sp.add_parser("_child")
    ch.add_argument("tree")
    ch.add_argument("blocks")
    ch.add_argument("jsonl")
    ch.add_argument("--upto", type=int)
    ch.add_argument("--deep-sync", action="store_true")
    ch.add_argument("--work", required=True)
    a = p.parse_args()
    return {"fetch": cmd_fetch, "replay": cmd_replay, "compare": cmd_compare, "_child": cmd_child}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main() or 0)
