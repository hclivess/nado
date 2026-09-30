"""The replay proof tool (tools/replay_chain.py) says IDENTICAL only when two replays agree, names the first
difference otherwise, and never replays inside the live checkout or writes into the tree it replays.

WHY (2026-09-30). The gen-27 gate cleanup was proven by replaying the live chain through the node's remote-block path
with the old and the new tree; the tool lived in a scratch directory and would have been lost with it, so the next
cleanup would have rebuilt it from nothing. Its verdict is the whole proof, so the comparison is pinned here on
synthetic results (a real replay needs the chain and an hour).

Pins: identical results -> "IDENTICAL through height N"; a side that replayed nothing -> "NOT A PROOF"; a differing root / hash / acceptance -> "DIFFERS AT HEIGHT h"
naming the field and h, and a non-zero exit; a differing genesis -> DIFFERS AT GENESIS; a side stopped on purpose
with --upto is not a difference; replay refuses the live checkout and a --work directory inside the replayed tree.

Run: python3 tests/test_replay_chain_proves.py
"""
import copy, json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tools", "replay_chain.py")
W = tempfile.mkdtemp(prefix="nado-test-replay-")
import atexit, shutil; atexit.register(shutil.rmtree, W, ignore_errors=True)
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def result(n, root_at=None, upto=None):
    rows = [{"h": h, "accepted": True, "hash": f"h{h}", "claimed": f"h{h}", "root": f"r{h}", "l2": [h], "err": None,
             "errors": [], "net": []} for h in range(1, n + 1)]
    if root_at:
        rows[root_at - 1]["root"] = "DIFFERENT"
    return {"tree": "/t", "commit": "c" * 40, "blocks_file": "/b.json", "child_rc": 0,
            "head": {"genesis_hash": "g", "genesis_root": "gr", "genesis_ok": True, "upto": upto if upto is not None else n},
            "blocks": rows}


def compare(a, b):
    pa, pb = os.path.join(W, "a.json"), os.path.join(W, "b.json")
    json.dump(a, open(pa, "w")); json.dump(b, open(pb, "w"))
    r = subprocess.run([sys.executable, TOOL, "compare", pa, pb], capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr


rc, out = compare(result(50), result(50))
check("two agreeing replays are IDENTICAL through the top height", rc == 0 and "IDENTICAL through height 50" in out, out)
rc, out = compare(result(50), result(50, root_at=17))
check("a different L1 root is named at its height, with the heights before it identical",
      rc == 1 and "DIFFERS AT HEIGHT 17" in out and "root" in out and "heights 1..16 identical" in out, out)
b = result(50); b["blocks"][29]["accepted"] = False; b["blocks"] = b["blocks"][:30]
rc, out = compare(result(50), b)
check("a block one side rejects is a difference", rc == 1 and "DIFFERS AT HEIGHT 30" in out, out)
b = result(50); b["head"] = dict(b["head"], genesis_hash="other")
rc, out = compare(result(50), b)
check("a different genesis is a difference before any block", rc == 1 and "DIFFERS AT GENESIS" in out, out)
b = result(20, upto=20)
rc, out = compare(result(50), b)
check("a side replayed only to --upto is not a difference", rc == 0 and "IDENTICAL through height 20" in out, out)

empty = result(0); empty["child_rc"] = 2; empty["head"] = None
rc, out = compare(empty, copy.deepcopy(empty))
check("two FAILED replays are never IDENTICAL (they compared 'IDENTICAL through height 0' once)",
      rc == 1 and "NOT A PROOF" in out and "IDENTICAL" not in out, out)
rc, out = compare(result(50), empty)
check("...nor is one failed side against a good one", rc == 1 and "NOT A PROOF" in out, out)

r = subprocess.run([sys.executable, TOOL, "replay", "/srv/nado-home/nado", os.path.join(W, "x.json")],
                   capture_output=True, text=True, timeout=60)
check("replay refuses the live checkout", r.returncode != 0 and "LIVE checkout" in (r.stdout + r.stderr), r.stdout + r.stderr)
tree = os.path.join(W, "tree"); os.makedirs(os.path.join(tree, "loops")); os.makedirs(os.path.join(tree, "genesis_data"))
open(os.path.join(tree, "genesis.py"), "w").close(); open(os.path.join(tree, "loops", "core_loop.py"), "w").close()
r = subprocess.run([sys.executable, TOOL, "replay", tree, os.path.join(W, "x.json"), "--work", os.path.join(tree, "w")],
                   capture_output=True, text=True, timeout=60)
check("replay refuses a --work directory inside the replayed tree", r.returncode != 0 and "inside the tree" in (r.stdout + r.stderr),
      r.stdout + r.stderr)
src = open(TOOL).read()
check("the replayed blocks go through the node's own remote-block path",
      'core.produce_block(blk, remote=True, remote_peer="replay-harness")' in src)
check("the child refuses every outbound connection", "_install_net_guard(net)" in src)
print("ALL PASS — the replay proof says IDENTICAL only when it is" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
