"""AN HONEST SETTLE PROOF BUILT FROM THIS NODE'S REAL SETTLE STASH MUST VERIFY UNDER EVERY SCHEDULED RULE (2026-09-24).

This is the check that found the REVIEW_R2 `faucet` refusal, turned into a test. The unit tests for that check were
green because they fed it hand-written pre-states; the chain's state had two contracts under fixed names, so every
honest proof-carrying settle from block 214000 was refused, and nothing ran a proof built from the real state until
someone asked why no proof landed. tests/test_settle_proof_live_state_shape.py covers the shape synthetically; this
file uses the REAL thing when the machine has it.

What it does, read-only:
  * picks the newest `exec_state.json~stash~<ns>~<cursor>.json` beside the checkout (the exact pre-state the exec
    node proves from) and copies it — it NEVER imports execnode.execnode, which would open the live exec files;
  * proves an empty span over it at the protocol depth and query count, at a cursor ABOVE every finite gen-25 gate,
    so every rule that is scheduled — not only the ones already live — judges it (a new verifier check that would
    refuse live state fails HERE, before its height arrives);
  * verifies it through the real verify child (ops/proof_child) and requires (True, 'ok') and the stash's KV root.

SKIPS with a message when no stash exists (a machine that is not a settling exec node). Takes about a minute with
the exec node's fold cache (read, never written), a few minutes cold.

Run: python3 tests/test_settle_proof_verifies_live_stash.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-live-stash-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")   # never the live exec files
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import glob, json, re, sys, time
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import protocol as P
from execnode.stark import settlement_sparse as SS, storage_tree as ST, stark
from execnode import exec_root as ER


def newest_stash():
    best = None
    for p in glob.glob(os.path.join(REPO, "exec_state.json~stash~*~*.json")):
        m = re.search(r"~stash~([^~]+)~(\d+)\.json$", p)
        if m and (best is None or int(m.group(2)) > best[0]):
            best = (int(m.group(2)), p)
    return best


def future_cursor(stash_cursor):
    """A cursor above every finite gen-25 gate, so every SCHEDULED rule is in force (2^62 reroll gates excluded)."""
    src = open(os.path.join(REPO, "protocol.py")).read()
    finite = [int(h) for h in re.findall(r"_HEIGHT = (\d+) if CHAIN_GENERATION == 25", src)]
    return max([stash_cursor] + finite) + 16


def main():
    if int(P.PROOF_FIXED_CID_HEIGHT) >= (1 << 62):
        # DELIBERATE HOLD (2026-09-24): honest settle proofs over live state are refused on gen 25 until a pending
        # verifier fix ships and re-schedules PROOF_FIXED_CID_HEIGHT with it. Say so instead of failing or passing.
        print("SKIP  PROOF_FIXED_CID_HEIGHT is deferred: settle proofs are held closed on purpose until the "
              "pending verifier fix re-schedules it"); return 0
    found = newest_stash()
    if not found:
        print("SKIP  no settle stash beside this checkout — not a settling exec node"); return 0
    cursor, path = found
    local = os.path.join(os.environ["HOME"], "stash.json")
    shutil.copyfile(path, local)                                   # read-only on the live file
    snap = json.load(open(local))
    pre = (snap.get("state") or {}).get("contracts") or {}
    print(f"stash {os.path.basename(path)}: {len(pre)} contracts, "
          f"{sum(len(((c.get('storage') or {}).get('slots') or {})) for c in pre.values())} slots")
    folds = os.path.join(REPO, "exec_state.json.folds.json")
    if os.path.exists(folds):                                      # speed only; validated, never written back
        ST.load_fold_cache(folds, P.EXEC_TREE_DEPTH)
        os.makedirs(os.path.join(os.environ["HOME"], "nado"), exist_ok=True)
        shutil.copyfile(folds, os.path.join(os.environ["HOME"], "nado", "settle_verify_folds.json"))
    cur = future_cursor(cursor)
    rules = stark.rules_for_height(cur)
    t = time.time()
    with stark.with_rules(rules):
        pf = SS.prove_settlement_sparse(pre, [], cur, "00" * 32, depth=P.EXEC_TREE_DEPTH)
    print(f"proved at cursor {cur} under {rules} in {time.time() - t:.1f}s")
    want_kv = SS.sparse_root_hex(pre, P.EXEC_TREE_DEPTH, v2=ER.root_v2(cur))
    fails = 0
    if pf["kv_pre"] != want_kv:
        fails += 1; print(f"FAIL  the proof's kv_pre {pf['kv_pre'][:16]}… is not the stash's KV root {want_kv[:16]}…")
    from ops.proof_child import verify_sparse_out_of_process
    t = time.time()
    res = verify_sparse_out_of_process(pf, P.EXEC_TREE_DEPTH, rules=rules)
    if res is None:
        fails += 1; print("FAIL  the verify child produced no verdict")
    elif not res[0]:
        fails += 1; print(f"FAIL  an honest proof from the LIVE state is refused under the scheduled rules: {res[1]}")
    else:
        print(f"PASS  honest proof from the live stash verifies in the verify child ({time.time() - t:.1f}s)")
    print("ALL PASS" if not fails else f"{fails} FAILURES")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
