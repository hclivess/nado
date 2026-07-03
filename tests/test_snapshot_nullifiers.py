"""
Audit M-8: a bulk state snapshot must carry the consensus replay-guard nullifiers (withdrawal/payout/slash),
so a snapshot-synced node cannot re-accept an already-applied unshield/bridge/dividend/treasury payout or slash
(escrow double-spend / double-slash). Also: the guards are bound into the manifest hash (a donor can't strip
them), and NON-consensus local meta (e.g. finalized_height) is NOT carried.

Run: python3 tests/test_snapshot_nullifiers.py
"""
import os, sys, tempfile, traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = 0
def check(name, cond, detail=""):
    global fails
    if cond:
        print(f"PASS  {name}")
    else:
        fails += 1
        print(f"FAIL  {name}: {detail}")


def main():
    donor = tempfile.mkdtemp()
    joiner = tempfile.mkdtemp()

    # --- DONOR: seed accounts + every class of replay guard, then build a snapshot ---
    os.environ["HOME"] = donor
    from ops import kv_ops, snapshot_ops
    kv_ops.close_all()
    kv_ops.init_env()
    with kv_ops.write_txn():
        kv_ops.put_account("shield", {"balance": 1000})
        kv_ops.put_account("ndoalice", {"balance": 50})
        kv_ops.totals_set(0, 0)
    kv_ops.shield_nullifier_put("ndoalice", "7")
    kv_ops.bridge_nullifier_put("ndobob", "3")
    kv_ops.dividend_nullifier_put("ndocarol", "9")
    kv_ops.treasury_executed_put("pid-abc")
    kv_ops.slash_record("ndodave", 42)
    kv_ops.meta_set_int("finalized_height", 100)   # NON-consensus local meta — must NOT be carried

    manifest, chunks = snapshot_ops.build_snapshot(snapshot_height=0, block_hash="anchor", protocol=1, version="t")

    check("manifest is self-consistent", manifest["snapshot_hash"] == snapshot_ops.manifest_hash(manifest))
    guards = manifest.get("nullifiers", [])
    keys = {k for k, _ in guards}
    check("all 5 replay guards carried", len(guards) == 5, guards)
    check("shield guard present", "shieldnull:ndoalice:7" in keys)
    check("bridge/dividend/tspend/slash present",
          {"bridgenull:ndobob:3", "divnull:ndocarol:9", "tspend:pid-abc", "slash:ndodave:42"} <= keys, keys)
    check("local finalized_height NOT carried", "finalized_height" not in keys)

    # a donor cannot strip a guard: dropping one changes the agreed manifest hash
    tampered = dict(manifest)
    tampered["nullifiers"] = guards[:-1]
    check("stripping a guard breaks the manifest hash",
          snapshot_ops.manifest_hash(tampered) != manifest["snapshot_hash"])

    # --- JOINER: fresh empty home, import, and confirm the guards are reinstated ---
    kv_ops.close_all()
    os.environ["HOME"] = joiner
    kv_ops.init_env()
    check("joiner starts WITHOUT the guard", not kv_ops.shield_nullifier_exists("ndoalice", "7"))

    ok = snapshot_ops.import_snapshot(manifest, chunks)
    check("import_snapshot succeeded", ok)
    check("shield unshield guard restored", kv_ops.shield_nullifier_exists("ndoalice", "7"))
    check("bridge guard restored", kv_ops.bridge_nullifier_exists("ndobob", "3"))
    check("dividend guard restored", kv_ops.dividend_nullifier_exists("ndocarol", "9"))
    check("treasury payout guard restored", kv_ops.treasury_executed_exists("pid-abc"))
    check("slash guard restored", kv_ops.slash_exists("ndodave", 42))
    check("account state restored", kv_ops.get_account_or_default("shield").get("balance") == 1000
          if hasattr(kv_ops, "get_account_or_default") else True)


try:
    main()
except Exception as e:
    fails += 1
    print(f"FAIL  exception: {e}")
    traceback.print_exc()

print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
