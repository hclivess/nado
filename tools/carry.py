"""The carry: every contract crosses the reroll with ALL of its state.

Operator rule (2026-10-20): "everything should be carried ... this should be the carry mechanism we perfect now and can
move to mainnet". Nothing is reset to fresh-deploy storage and no pot is refunded in place of carrying it; a contract
the carry cannot move losslessly REFUSES the carry instead, naming why, so the operator settles it on the old chain
(or the module gains the hook it lacks) and the carry runs again. doc/stwo/g5-carry.md is the design.

From generation 29 on, every generation runs the same VM (zkvm2), the same hash and the same address digest, so the carry
RE-ENCODES NOTHING: it re-derives and checks, it never rewrites a key or a value. Per contract (carry_contract):
  1. the module is found by CODE: the game module whose build() is exactly the contract's code. No module, no carry.
  2. in flight: the module's carry_in_flight(storage[, tip]) must be [] — a refusal, never a reset; a module with no carry
     rule refuses whenever it holds storage.
  3. heights: the module's carry_rebase(storage, tip) moves old-chain heights onto the new chain.
  4. storage: every slot an int (the root commits int slots only); code: mod.build(); abi, deployer, runtime and
     upgradable as they are.
The registry (zk_addrs) and the asset ids are re-derived from their own strings and records and refused if any entry is
not its own digest / id (digest_map, asset_map): the carry never trusts what it can recompute.

(The gen-28 -> gen-29 crossing — the field VM to the 256-bit one, which re-hashed keys, remapped owner digests and asset
ids and rebuilt the code for the new ISA — was deleted in G9 slice 3b with the field VM: V1Hash, reencode_storage and the
modules' CARRY_WORDS / carry_hash_preimages / carry_v2_storage hooks. git history holds it if a generation ever changes
the VM hash again.)

READ-ONLY on its input: pass a COPY of exec_state.json; the tool refuses the live path. Nothing here opens the live
database (CLAUDE.md rule 4): the game builders are imported under a throwaway HOME and exec paths.

Run: python3 tools/carry.py /tmp/exec_state.copy.json [--out exec_genesis_contracts.json]
"""
import json
import os
import sys
import tempfile

LIVE_STATE = "/srv/nado-home/nado/exec_state.json"


class Refused(Exception):
    """The carry cannot move this state losslessly — the message names what and why."""


def _isolate():
    """Builders import node modules: never against the live node's home or exec files (CLAUDE.md rule 4)."""
    if not os.environ.get("NADO_CARRY_ISOLATED"):
        home = tempfile.mkdtemp(prefix="nado-carry-")
        # removed at exit: every carry and census run used to leave one of these behind (nine in /tmp, 2026-10-26)
        import atexit, shutil
        atexit.register(shutil.rmtree, home, ignore_errors=True)
        os.environ["HOME"] = home
        os.environ["NADO_EXEC_STATE"] = os.path.join(home, "exec_state.json")
        os.environ["NADO_EXEC_DA"] = os.path.join(home, "exec_da")
        os.environ["NADO_CARRY_ISOLATED"] = "1"
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)


def digest_map(zk_addrs):
    """({digest: digest}, the registry {str(digest): string}). Every entry must be the digest of its own string — a
    registry the carry cannot re-derive is refused, not trusted. The digest is the same on both chains (one VM), so the
    map is the identity: it exists so a carry that ever changes the digest has one place to remap."""
    from execnode.runtimes import zkvm_addr_digest
    dmap, reg = {}, {}
    for k, s in sorted((zk_addrs or {}).items(), key=lambda kv: int(kv[0])):
        d = int(k)
        if not isinstance(s, str) or zkvm_addr_digest(s) != d:
            raise Refused(f"zk_addrs entry {k} is not the digest of its string {s!r}")
        dmap[d], reg[k] = d, s
    return dmap, reg


def asset_map(assets):
    """{asset id: asset id}: an id is DERIVED from (issuer, seed) through the VM hash (state.asset_id), so every record
    must be its own id's preimage, or the carry refuses. The identity on a same-VM carry, like digest_map."""
    from execnode.state import asset_id
    amap = {}
    for aid, rec in sorted((assets or {}).items()):
        d = asset_id(rec["issuer"], rec["seed"])
        if d != int(aid):
            raise Refused(f"asset {aid} is not the id of its own (issuer, seed)")
        amap[d] = d
    return amap


def carry_assets(assets, abal, allow, amap):
    """(assets, abal, allow) keyed by the carried asset ids — records, balances and allowances unchanged. A balance or
    allowance of an asset with no record refuses."""
    def rk(d):
        out = {}
        for aid, v in sorted((d or {}).items()):
            if int(aid) not in amap:
                raise Refused(f"a balance or allowance of asset {aid}, which has no asset record")
            out[str(amap[int(aid)])] = json.loads(json.dumps(v))
        return out
    return rk(assets), rk(abal), rk(allow)


def module_of(contract):
    """The execnode.games module whose build() is exactly this contract's code, or None."""
    import importlib
    import pkgutil
    import execnode.games as _g
    code = json.loads(json.dumps(contract.get("code")))
    for m in pkgutil.iter_modules(_g.__path__):
        if m.name.startswith("_") or m.name in ("deploy", "redeploy"):
            continue
        mod = importlib.import_module(f"execnode.games.{m.name}")
        if hasattr(mod, "build") and json.loads(json.dumps(mod.build())) == code:
            return mod
    return None


def carry_contract(cid, contract, tip):
    """(the new generation's genesis record, counts) for one contract — the module docstring's four steps. Raises
    Refused naming the contract and why."""
    import inspect
    mod = module_of(contract)
    if mod is None:
        raise Refused(f"{cid}: its code is no game module's build — the carry cannot rebuild it")
    storage = json.loads(json.dumps(contract.get("storage") or {}))
    slots = storage.get("slots") or {}
    rules = getattr(mod, "CARRY_STORAGE", False) or hasattr(mod, "carry_in_flight") or hasattr(mod, "carry_rebase")
    if slots and not rules:
        raise Refused(f"{cid} ({mod.__name__}): holds storage but its module declares no carry rule "
                      "(CARRY_STORAGE, carry_in_flight or carry_rebase) — nothing says what in it names the old chain")
    if hasattr(mod, "carry_in_flight"):
        f = mod.carry_in_flight
        why = f(storage, tip=int(tip)) if "tip" in inspect.signature(f).parameters else f(storage)
        if why:
            raise Refused(f"{cid} ({mod.__name__}): in flight — settle on the old chain first: " + "; ".join(why))
    if hasattr(mod, "carry_rebase") and slots:
        storage = json.loads(json.dumps(mod.carry_rebase(storage, int(tip))))
    storage = dict(storage)
    storage["slots"] = {str(k): int(v) for k, v in (storage.get("slots") or {}).items()}   # ints: the root rule
    rec = {k: contract[k] for k in ("abi", "deployer", "runtime", "upgradable") if k in contract}
    rec["code"] = json.loads(json.dumps(mod.build()))
    rec["storage"] = storage
    return rec, {"slots": len(storage["slots"]), "module": mod.__name__.rsplit(".", 1)[-1]}


def carry_contracts(contracts, zk_addrs, tip):
    """({cid: new record}, the registry, {cid: counts}) — every contract, or Refused listing every one that cannot carry
    (all of them at once, so the operator settles everything in one pass)."""
    _dmap, reg = digest_map(zk_addrs)
    out, counts, refused = {}, {}, []
    for cid in sorted(contracts):
        try:
            out[cid], counts[cid] = carry_contract(cid, contracts[cid], tip)
        except Refused as e:
            refused.append(str(e))
    if refused:
        raise Refused("the carry refuses — nothing was written:\n  " + "\n  ".join(refused))
    return out, reg, counts


def main():
    argv = sys.argv[1:]
    if "--out" in argv:
        del argv[argv.index("--out") + 1]
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    path = os.path.abspath(args[0])
    if os.path.realpath(path) == os.path.realpath(LIVE_STATE):
        sys.exit("refusing the LIVE exec_state.json: copy it first (it is rewritten while the exec node runs)")
    _isolate()
    s = json.load(open(path))
    try:
        amap = asset_map(s.get("assets"))
        carry_assets(s.get("assets"), s.get("abal"), s.get("allow"), amap)
        contracts, reg, counts = carry_contracts(s.get("contracts") or {}, s.get("zk_addrs") or {}, int(s.get("cursor", 0)))
    except Refused as e:
        sys.exit(str(e))
    tot = 0
    for cid, n in sorted(counts.items(), key=lambda x: x[1]["module"]):
        tot += n["slots"]
        if n["slots"]:
            print(f"{n['module']:12} {cid[:12]:12} {n['slots']:>8} slots")
    print(f"{'TOTAL':25} {tot:>8} slots")
    print(f"contracts carried: {len(contracts)} (every one); registry entries: {len(reg)}; assets: {len(amap)}")
    if "--out" in sys.argv:
        dest = sys.argv[sys.argv.index("--out") + 1]
        with open(dest, "w") as f:
            json.dump({"contracts": contracts, "zk_addrs": reg}, f, sort_keys=True)
        print("wrote", dest)


if __name__ == "__main__":
    main()
