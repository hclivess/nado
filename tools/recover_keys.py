"""Recover {format-1 address: public key} from OLDER generations' account tables, for tools/rekey_v2.py.

Needed only by the carry that crossed into address format 2 (gen 27 -> 28); a carry from gen 28 onward re-keys nothing
(tools/alphanet6_carryforward.py). Kept runnable, not deleted.

Usage (at the reroll, before the carry):
    python3 tools/recover_keys.py OUT.json <old index/state dir> [<old index/state dir> ...]
e.g. the reroll backups' index/state (doc/reroll.md step "recover keys").

READ-ONLY and never the live database: every environment is opened readonly with lock=False, and a path that is the
running node's own index/state is refused. Only the `accounts` sub-DB is read, and only its public_key field — public
data that the chain published. A key is kept only if it derives the address it is stored under; when two generations
disagree about one address the address is left out (and printed), so rekey_v2 carries it at its old address rather
than guess."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def recover(paths):
    import lmdb
    from ops import codec
    from ops.address_ops import legacy_address
    from ops.data_ops import get_home
    live = os.path.realpath(os.path.join(get_home(), "index", "state"))
    found, conflict = {}, set()
    for path in paths:
        if os.path.realpath(path) == live:
            raise SystemExit(f"{path} is the running node's database — pass backup copies only")
        env = lmdb.open(path, readonly=True, lock=False, max_dbs=64)
        n = 0
        with env.begin(db=env.open_db(b"accounts", create=False)) as t:
            for k, v in t.cursor():
                a = k.decode(errors="ignore")
                try:
                    d = codec.unpack(v)
                except Exception:
                    continue
                pk = d.get("public_key") if isinstance(d, dict) else None
                if not pk:
                    continue
                try:
                    if legacy_address(pk) != a:
                        continue
                except Exception:
                    continue
                if a in found and found[a].lower() != pk.lower():
                    conflict.add(a)
                elif a not in found:
                    found[a] = pk
                    n += 1
        env.close()
        print(f"{path}: {n} keys")
    for a in sorted(conflict):
        print(f"  CONFLICT {a}: two generations recorded different keys — left out")
        found.pop(a, None)
    return found


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    keys = recover(sys.argv[2:])
    with open(sys.argv[1], "w") as f:
        json.dump(keys, f, sort_keys=True)
    print(f"WROTE {sys.argv[1]}: {len(keys)} keys")
