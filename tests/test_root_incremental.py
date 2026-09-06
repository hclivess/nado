"""The incremental L1 state root (ops/snapshot_ops._root_from_inc, fed by kv_ops ROOT WRITE TRACKING) must
equal the full-walk root after EVERY commit: plain rows, DUPSORT rows, deletes, all-default account rows,
excluded meta keys, the retention-window floor moving, nested block-style txns, an untracked generation
bump, and a long seeded random sequence. Also pins that no code opens a write txn outside kv_ops' two
tracked sites."""
import os
import random
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_tmp = tempfile.mkdtemp()
os.environ["HOME"] = _tmp
os.environ["NADO_HOME"] = _tmp
os.environ["NADO_ROOT_INC"] = "verify"

from ops import kv_ops, snapshot_ops as so   # noqa: E402

checks = [0, 0]


def same(label):
    inc = so._root_from_inc()
    walk = so._root_from_walk()
    checks[0] += 1
    if inc != walk:
        checks[1] += 1
        print(f"FAIL  {label}: inc={inc[:16]} walk={walk[:16]}")
    return inc == walk


def main():
    kv_ops.init_env()
    assert same("empty state")
    kv_ops.put_account("a1", {"balance": 5, "produced": 1})
    kv_ops.put_account("a2", {"balance": 7})
    assert same("two accounts")
    kv_ops.account_set_field("a1", "public_key", "pk")
    assert same("schemaless field")
    kv_ops.put_account("a2", {"balance": 0})            # all-default doc == absent for the root
    assert same("default account row filtered")
    kv_ops.meta_set_int("finalized_height", 5)           # ROOT_EXCLUDED_META_KEYS
    kv_ops.meta_set_int("some_counter", 9)
    assert same("meta rows incl. an excluded key")
    kv_ops.meta_del("some_counter")
    assert same("meta delete")
    kv_ops.attestation_put(3, "v1", "h" * 64)
    kv_ops.attestation_put(3, "v2", "h" * 64)
    kv_ops.attestation_put(4, "v1", "g" * 64)
    assert same("dupsort inserts")
    kv_ops.attestation_del(3, "v1", "h" * 64)
    assert same("dupsort single-value delete")
    kv_ops.recert_put("a1", 2); kv_ops.recert_put("a1", 3)
    assert same("recert (two dup dbs)")
    kv_ops.settlement_put("ns", 7, "v1", "r" * 64)
    assert same("settlement put")
    kv_ops.settlement_del("ns", 7, "v1", "r" * 64)
    assert same("settlement del")
    with kv_ops.write_txn():                              # block-style nested txn, many writes, one commit
        for i in range(40):
            kv_ops.put_account(f"b{i}", {"balance": i + 1})
        with kv_ops.write_txn():
            kv_ops.meta_set_int("nested", 1)
            kv_ops.attestation_put(5, "v9", "z" * 64)
    assert same("nested block txn")
    # retention floor: epochw rows move the window; old windowed rows must drop out untouched
    for e in range(0, so.ROOT_RETENTION_EPOCHS + 3):
        kv_ops.meta_set_int(f"epochw:{e}", e * 10)
        assert same(f"epochw {e}")
    kv_ops.attestation_put(so.ROOT_RETENTION_EPOCHS + 2, "v1", "y" * 64)
    assert same("row inside the window")
    kv_ops.meta_set_int(f"epochw:{so.ROOT_RETENTION_EPOCHS + 10}", 1)
    assert same("floor jumps: windowed rows leave the commitment")
    # an untracked generation bump must force a rebuild, never a stale root
    kv_ops._bump_write_gen()
    kv_ops.put_account("c1", {"balance": 3})
    assert same("untracked bump then write")
    # seeded random sequence across every family
    rnd = random.Random(7)
    addrs = [f"r{i}" for i in range(30)]
    for step in range(250):
        op = rnd.randrange(8)
        if op == 0:
            kv_ops.put_account(rnd.choice(addrs), {"balance": rnd.randrange(3)})
        elif op == 1:
            kv_ops.account_set_field(rnd.choice(addrs), "x", rnd.randrange(5))
        elif op == 2:
            kv_ops.account_del_field(rnd.choice(addrs), "x")
        elif op == 3:
            kv_ops.meta_set_int(f"m{rnd.randrange(10)}", rnd.randrange(100))
        elif op == 4:
            kv_ops.meta_del(f"m{rnd.randrange(10)}")
        elif op == 5:
            kv_ops.attestation_put(rnd.randrange(60, 75), rnd.choice(addrs), "q" * 64)
        elif op == 6:
            kv_ops.attestation_del(rnd.randrange(60, 75), rnd.choice(addrs), "q" * 64)
        else:
            with kv_ops.write_txn():
                kv_ops.recert_put(rnd.choice(addrs), rnd.randrange(60, 75))
                kv_ops.meta_set_int(f"epochw:{rnd.randrange(60, 75)}", step)
        if step % 5 == 0:
            assert same(f"random step {step}")
    assert same("random end")
    # the two-site invariant: no other write txn creation anywhere
    import subprocess
    out = subprocess.run(["grep", "-rn", "begin(write=True)", "--include=*.py", "ops", "loops", "nado.py", "memserver.py"],
                         cwd=ROOT, capture_output=True, text=True).stdout
    sites = [l for l in out.splitlines() if "#" not in l.split(":", 2)[2].split("begin(")[0] and '"""' not in l]
    assert all(l.startswith("ops/kv_ops.py") for l in sites), sites
    assert sum("_TrackTxn(get_env().begin(write=True))" in l or "begin(write=True) as raw" in l for l in sites) == 3, sites
    print(f"ALL OK ({checks[0]} equivalence checks, {checks[1]} mismatches, {so._inc_stats['rebuilds']} rebuilds)")


if __name__ == "__main__":
    main()
