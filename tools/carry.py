"""The carry: every contract crosses the reroll with ALL of its state, re-encoded into the new generation's formats.

Operator rule (2026-10-20): "everything should be carried ... this should be the carry mechanism we perfect now and can
move to mainnet". Nothing is reset to fresh-deploy storage and no pot is refunded in place of carrying it; a contract
the carry cannot re-encode losslessly REFUSES the carry instead, naming why, so the operator settles it on the old chain
(or the module gains the hook it lacks) and the carry runs again. doc/stwo/g5-carry.md is the design; the census that
measured what live storage holds is tools/carry_census.py.

Gen 28 -> gen 29 (the Goldilocks -> BLAKE2s/M31 exec layer), per contract (carry_contract):
  1. the module is found by CODE: the game module whose build("v1") is exactly the contract's code. No module, no carry.
  2. in flight: the module's carry_in_flight(storage[, tip]) must be [] — a refusal, never a reset.
  3. heights: the module's carry_rebase(storage, tip) moves old-chain heights onto the new chain (unchanged hooks);
     then carry_v2_storage(storage), where a module's v2 code reads as state what v1 re-derived through the hash
     (pets: the gene's rolls -> the roll table, so a carried pet keeps every trait).
  4. storage, slot by slot (reencode_storage):
       key   a hash key (the module's carry_hash_preimages explains it) -> zkvm2.hash_words(preimage with every Owner
             word remapped); an owner-keyed field (CARRY_OWNER_KEY_FIELDS: (F*2^32 + digest) mod P) -> F*2^32 + new
             digest; a plain key (< 2^32, or F*2^32 + id with F < 2^20) unchanged; anything else REFUSES.
       value a registry digest -> the new digest; any other value >= 2^32 must be declared in the module's CARRY_WORDS
             (kept verbatim) or it REFUSES; small values unchanged.
  5. code: mod.build("v2"), and the module's ABI with it (its view schema describes the new code's state); deployer,
     runtime and upgradable carry as they are.
and the registry (zk_addrs) is re-keyed by the new digest of every string it holds (digest_map).

The new digest of a string is runtimes.zkvm_addr_digest(s, v2=True) — what the gen-29 call boundary computes for the same
caller or string argument, so a carried owner is recognised by their first call on the new chain.

READ-ONLY on its input: pass a COPY of exec_state.json; the tool refuses the live path. Nothing here opens the live
database (CLAUDE.md rule 4): the game builders are imported under a throwaway HOME and exec paths.

Run: python3 tools/carry.py /tmp/exec_state.copy.json [--out exec_genesis_contracts.json]
"""
import json
import os
import sys
import tempfile

P = 2**64 - 2**32 + 1          # the gen-28 VM word (Goldilocks)
WORD = 1 << 256                 # the gen-29 VM word
PLAIN_FIELD_MAX = 1 << 20       # tools/carry_census.py: composite keys carry field tags up to ~1,050 today
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


class V1Hash:
    """alghash.hashn — the gen-28 `hash` — with every short prefix's sponge state cached. The preimage hooks enumerate
    in nested order with the varying word last, so each candidate costs one permutation instead of one per word (the
    faucet's ~600k marker candidates: minutes -> seconds)."""

    def __init__(self):
        from execnode.stark import alghash, field
        self._a, self._f = alghash, field
        self._cache = {(): (0, alghash.IV)}

    def _state(self, prefix):
        st = self._cache.get(prefix)
        if st is None:
            s0, s1 = self._state(prefix[:-1])
            st = tuple(self._a.permute([self._f.add(s0, prefix[-1] % P), s1]))
            if len(prefix) <= 4:
                self._cache[prefix] = st
        return st

    def __call__(self, words):
        words = tuple(int(w) for w in words)
        s0, s1 = self._state(words[:-1])
        return self._a.permute([self._f.add(s0, words[-1] % P), s1])[0]


def digest_map(zk_addrs, src="v1", dst="v2"):
    """({old digest: new digest}, the re-keyed registry {str(new): string}). Every entry must be the `src` digest of
    its own string — a registry the carry cannot re-derive is refused, not trusted. src == dst: the identity."""
    from execnode.runtimes import zkvm_addr_digest
    dmap, reg = {}, {}
    for k, s in sorted((zk_addrs or {}).items(), key=lambda kv: int(kv[0])):
        old = int(k)
        if not isinstance(s, str) or zkvm_addr_digest(s, src == "v2") != old:
            raise Refused(f"zk_addrs entry {k} is not the {src} digest of its string {s!r}")
        if src == dst:
            dmap[old], reg[k] = old, s
            continue
        if old < 1 << 32:
            # a digest this small could not be told from a plain value or id in storage
            raise Refused(f"zk_addrs digest {k} is below 2^32 — ambiguous with plain storage values")
        new = zkvm_addr_digest(s, True)
        if str(new) in reg:
            raise Refused(f"two registry strings share the gen-29 digest {new}")
        dmap[old] = new
        reg[str(new)] = s
    return dmap, reg


def asset_map(assets, src="v1", dst="v2"):
    """{old asset id: new asset id}: an id is DERIVED from (issuer, seed) through the VM hash (state.asset_id), so the
    new generation's id of the same asset is recomputed from its own record. Every record must be its id's preimage."""
    from execnode.state import asset_id
    amap = {}
    for aid, rec in sorted((assets or {}).items()):
        old = asset_id(rec["issuer"], rec["seed"], src == "v2")
        if old != int(aid):
            raise Refused(f"asset {aid} is not the {src} id of its own (issuer, seed)")
        amap[old] = old if src == dst else asset_id(rec["issuer"], rec["seed"], dst == "v2")
    if len(set(amap.values())) != len(amap):
        raise Refused("two assets share a new id")
    return amap


def carry_assets(assets, abal, allow, amap):
    """(assets, abal, allow) re-keyed by the new asset ids — records, balances and allowances unchanged."""
    def rk(d):
        out = {}
        for aid, v in sorted((d or {}).items()):
            if int(aid) not in amap:
                raise Refused(f"a balance or allowance of asset {aid}, which has no asset record")
            out[str(amap[int(aid)])] = json.loads(json.dumps(v))
        return out
    return rk(assets), rk(abal), rk(allow)


def reencode_storage(mod, storage, dmap, v1hash=None, amap=None):
    """(gen-29 storage, counts) for one contract's (already rebased) gen-28 storage — the slot rules in the module
    docstring, step 4 (an asset id held as a value is remapped like a digest, through `amap`). Raises Refused on any
    slot it cannot explain."""
    from execnode import zkvm2
    from execnode.games._lib import Owner
    name = getattr(mod, "__name__", "?").rsplit(".", 1)[-1]
    v1hash = v1hash or V1Hash()
    slots = {int(k): int(v) for k, v in ((storage or {}).get("slots") or {}).items()}
    words = getattr(mod, "CARRY_WORDS", {})
    owner_fields = tuple(getattr(mod, "CARRY_OWNER_KEY_FIELDS", ()))
    big_keys = {k for k in slots if k >= 1 << 32}
    hashed = {}                                       # old key -> (new key, tag)
    if big_keys and hasattr(mod, "carry_hash_preimages"):
        for pre in mod.carry_hash_preimages(storage, sorted(dmap)):
            old = v1hash(pre)
            if old in big_keys and old not in hashed:
                try:
                    new_pre = [dmap[w] if isinstance(w, Owner) else int(w) for w in pre]
                except KeyError as e:
                    raise Refused(f"{name}: a hash preimage names digest {e} the registry does not hold")
                hashed[old] = (zkvm2.hash_words(new_pre), int(pre[0]))
    out, n = {}, {"slots": len(slots), "key_rehashed": 0, "key_owner": 0, "value_remapped": 0, "value_kept_word": 0}
    for k, v in sorted(slots.items()):
        if k in hashed:
            nk, where = hashed[k][0], ("tag", hashed[k][1])
            n["key_rehashed"] += 1
        else:
            nk = where = None
            for F in owner_fields:
                d = (k - (F << 32)) % P
                if d in dmap:
                    nk, where = ((F << 32) + dmap[d]) % WORD, ("field", F)
                    n["key_owner"] += 1
                    break
            if nk is None:
                if k < 1 << 32:
                    nk, where = k, ("slot", k)
                elif (k >> 32) < PLAIN_FIELD_MAX:
                    nk, where = k, ("field", k >> 32)
                else:
                    raise Refused(f"{name}: slot key {k} is no plain key, no owner-keyed field and no hash key its "
                                  "carry_hash_preimages explains — the carry cannot re-derive it")
        if v in dmap or v in (amap or {}):
            nv = dmap[v] if v in dmap else amap[v]
            n["value_remapped"] += 1
        elif v >= 1 << 32:
            if where not in words:
                raise Refused(f"{name}: slot {k} ({where[0]} {where[1]}) holds {v}, a value >= 2^32 that is no registry "
                              "digest and is not declared in CARRY_WORDS — an unregistered owner, or a hash-derived "
                              "value nobody has checked for re-derivation under the new hash")
            nv = v
            n["value_kept_word"] += 1
        else:
            nv = v
        if str(nk) in out:
            raise Refused(f"{name}: two gen-28 slots map to the gen-29 key {nk}")
        out[str(nk)] = int(nv)
    res = dict(storage or {})
    res["slots"] = out
    return res, n


def module_of(contract, isa="v1"):
    """The execnode.games module whose `isa` build is exactly this contract's code, or None (the census's match)."""
    import importlib
    import pkgutil
    import execnode.games as _g
    code = json.loads(json.dumps(contract.get("code")))
    for m in pkgutil.iter_modules(_g.__path__):
        if m.name.startswith("_") or m.name in ("deploy", "redeploy"):
            continue
        mod = importlib.import_module(f"execnode.games.{m.name}")
        if hasattr(mod, "build") and json.loads(json.dumps(mod.build(isa))) == code:
            return mod
    return None


def carry_contract(cid, contract, dmap, tip, v1hash=None, src="v1", dst="v2", amap=None):
    """(the new generation's genesis record, counts) for one contract — the module docstring's five steps. src == dst
    (every carry after gen 29: one VM, one hash, one digest) re-encodes nothing; v1 -> v2 is the gen-29 crossing."""
    import inspect
    if (src, dst) not in (("v1", "v2"), ("v1", "v1"), ("v2", "v2")):
        raise Refused(f"no carry is defined from ISA {src} to {dst}")
    mod = module_of(contract, src)
    if mod is None:
        raise Refused(f"{cid}: its code is no game module's {src} build — the carry cannot rebuild it")
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
    if src == dst:
        storage = dict(storage)
        storage["slots"] = {str(k): int(v) for k, v in (storage.get("slots") or {}).items()}   # ints: the root rule
        n = {"slots": len(storage["slots"]), "key_rehashed": 0, "key_owner": 0, "value_remapped": 0,
             "value_kept_word": 0}
    else:
        if hasattr(mod, "carry_v2_storage") and slots:
            # state the new code reads where the old code re-derived it from a hash (pets' roll table)
            storage = json.loads(json.dumps(mod.carry_v2_storage(storage)))
        storage, n = reencode_storage(mod, storage, dmap, v1hash, amap)
    rec = {k: contract[k] for k in ("abi", "deployer", "runtime", "upgradable") if k in contract}
    rec["code"] = json.loads(json.dumps(mod.build(dst)))
    if src != dst and hasattr(mod, "ABI"):
        # the ABI travels with the code it describes: a view schema for state the new code keeps (pets' roll table)
        rec["abi"] = json.loads(json.dumps(mod.ABI))
    rec["storage"] = storage
    n["module"] = mod.__name__.rsplit(".", 1)[-1]
    return rec, n


def carry_contracts(contracts, zk_addrs, tip, src=None, dst="v2", amap=None):
    """({cid: new record}, the re-keyed registry, {cid: counts}) — every contract, or Refused listing every one that
    cannot carry (all of them at once, so the operator settles everything in one pass). src defaults to the running
    generation's ISA; dst to v2 — every generation from 29 on runs the BLAKE2s VM from its genesis (BLAKE_EXEC_HEIGHT,
    gen 28's gate, inlined in G9: zkvmasm.default_isa is v2)."""
    if src is None:
        from execnode import zkvmasm
        src = zkvmasm.default_isa()
    dmap, reg = digest_map(zk_addrs, src, dst)
    v1hash = V1Hash()
    out, counts, refused = {}, {}, []
    for cid in sorted(contracts):
        try:
            out[cid], counts[cid] = carry_contract(cid, contracts[cid], dmap, tip, v1hash, src, dst, amap)
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
        contracts, reg, counts = carry_contracts(s.get("contracts") or {}, s.get("zk_addrs") or {}, int(s.get("cursor", 0)),
                                                 src="v1", amap=amap)
    except Refused as e:
        sys.exit(str(e))
    cols = ["slots", "key_rehashed", "key_owner", "value_remapped", "value_kept_word"]
    print(f"{'contract':12} {'cid':12} " + " ".join(f"{c:>15}" for c in cols))
    tot = dict.fromkeys(cols, 0)
    for cid, n in sorted(counts.items(), key=lambda x: x[1]["module"]):
        for c in cols:
            tot[c] += n[c]
        if n["slots"]:
            print(f"{n['module']:12} {cid[:12]:12} " + " ".join(f"{n[c]:>15}" for c in cols))
    print(f"{'TOTAL':25} " + " ".join(f"{tot[c]:>15}" for c in cols))
    print(f"contracts carried: {len(contracts)} (every one); registry re-keyed: {len(reg)} entries; "
          f"assets re-keyed: {len(amap)}")
    if "--out" in sys.argv:
        dest = sys.argv[sys.argv.index("--out") + 1]
        with open(dest, "w") as f:
            json.dump({"contracts": contracts, "zk_addrs": reg}, f, sort_keys=True)
        print("wrote", dest)


if __name__ == "__main__":
    main()
