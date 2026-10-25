"""G5 carry census: what carried contract storage holds in a generation-28 encoding the gen-29 carry must re-encode.

READ-ONLY, and on a COPY: pass a copy of exec_state.json (`cp /srv/nado-home/nado/exec_state.json /tmp/x.json`), never
the live file — the exec node rewrites it while it runs, and a half-written read is a wrong census. Nothing here opens
the live database: the only node import is the game builders (to name each contract by its code, as the carry matches
it), under a throwaway HOME and exec paths (CLAUDE.md rule 4).

Per contract it classifies every slot (doc/stwo-migration.md 9.2, doc/stwo/g5-carry.md):
  value  digest    the value is a zk_addrs key: an owner or string digest (gen 28: blake2b mod P) — remapped through the
                   registry to the gen-29 digest (256-bit BLAKE2s, runtimes.zkvm_addr_digest(v2=True))
         big       >= 2^32 and not a digest: an amount (1 NADO = 10^10 raw), a packed word, or a hash-valued slot —
                   listed one by one with --detail, because which of the three it is decides what the carry does
  key    plain     < 2^32, or F*2^32 + id with a field tag F < 2^20: carried unchanged
         F|digest  (F*2^32 + digest) mod P: re-keyed to F*2^32 + new digest
         hash      a VM-hash output (an alghash key, ~2^63): re-derived from its preimage through the contract's own
                   index (a carry hook), never decoded from its bits
Also the registry (addresses vs other strings), assets, and whether the legacy pools are empty.

Run: python3 tools/carry_census.py /tmp/exec_state.copy.json [--detail]
"""
import collections
import json
import os
import re
import sys
import tempfile

P = 2**64 - 2**32 + 1          # the gen-28 VM word (Goldilocks)
PLAIN_FIELD_MAX = 1 << 20       # composite keys carry field tags up to ~1,050 today; an alghash output's high half ~2^31


def classify(storage_slots, digests):
    """-> {slot key int: (key class, value class)} for one contract's slots (pure, testable)."""
    out = {}
    for k, v in storage_slots.items():
        k, v = int(k), int(v)
        vc = "digest" if v in digests else ("big" if v >= 2**32 else "small")
        if k in digests:
            kc = "digest"
        elif k >= 2**32 and (k >> 32) >= PLAIN_FIELD_MAX and any(((k - (F << 32)) % P) in digests for F in range(256)):
            kc = "F|digest"
        elif k < 2**32 or (k >> 32) < PLAIN_FIELD_MAX:
            kc = "plain"
        else:
            kc = "hash"
        out[k] = (kc, vc)
    return out


def contract_names(contracts, root):
    """cid -> game module name, by code equality with the module's gen-28 build (the carry's own match)."""
    os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-carry-census-")
    os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
    os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
    sys.path.insert(0, root)
    import importlib
    import pkgutil
    from execnode import games
    by_code = {}
    for m in pkgutil.iter_modules(games.__path__):
        if m.name.startswith("_"):
            continue
        mod = importlib.import_module("execnode.games." + m.name)
        if not hasattr(mod, "build"):
            continue
        try:
            code = mod.build("v1")
        except TypeError:
            code = mod.build()
        by_code[json.dumps(code, sort_keys=True)] = m.name
    return {cid: by_code.get(json.dumps(c.get("code"), sort_keys=True), "?unmatched") for cid, c in contracts.items()}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    path = os.path.abspath(args[0])
    if os.path.realpath(path) == os.path.realpath("/srv/nado-home/nado/exec_state.json"):
        sys.exit("refusing the LIVE exec_state.json: copy it first (it is rewritten while the exec node runs)")
    s = json.load(open(path))
    reg = s.get("zk_addrs", {})
    digests = {int(k) for k in reg}
    names = contract_names(s["contracts"], os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cols = ["slots", "v=digest", "v=big", "k=plain", "k=digest", "k=F|digest", "k=hash"]
    print(f"{'contract':12} {'cid':12} " + " ".join(f"{c:>10}" for c in cols))
    tot = collections.Counter()
    detail = []
    for cid, c in sorted(s["contracts"].items(), key=lambda x: names[x[0]]):
        slots = (c.get("storage") or {}).get("slots", {})
        cl = classify(slots, digests)
        n = collections.Counter(slots=len(cl))
        for k, (kc, vc) in cl.items():
            n["k=" + kc] += 1
            if vc != "small":
                n["v=" + vc] += 1
            if vc == "big" or kc in ("hash", "F|digest", "digest"):
                detail.append((names[cid], k, int(slots[str(k)]), kc, vc))
        tot.update(n)
        if n["slots"]:
            print(f"{names[cid]:12} {cid[:12]:12} " + " ".join(f"{n[c]:>10}" for c in cols))
    print(f"{'TOTAL':25} " + " ".join(f"{tot[c]:>10}" for c in cols))
    addrs = sum(1 for v in reg.values() if isinstance(v, str) and re.fullmatch(r"[0-9a-f]{50}", v))
    print(f"zk_addrs: {len(reg)} entries — {addrs} addresses, {len(reg) - addrs} other strings (string args)")
    print(f"assets: {len(s.get('assets', {}))}, abal: {len(s.get('abal', {}))}, allow: {len(s.get('allow', {}))}")
    for pool in ("field_pool", "shielded"):
        p = s.get(pool) or {}
        print(f"{pool}: {len(p.get('commitments') or [])} commitments, {len(p.get('nullifiers') or [])} nullifiers")
    print("empty contracts:", ", ".join(sorted(names[c] for c, x in s["contracts"].items()
                                               if not (x.get("storage") or {}).get("slots"))))
    if "--detail" in sys.argv:
        for name, k, v, kc, vc in sorted(detail):
            f = k >> 32 if (k >> 32) < PLAIN_FIELD_MAX else "-"
            print(f"  {name:10} key={k} (F={f}, {kc}) value={v} ({vc}{', %.4f NADO if an amount' % (v / 1e10) if vc == 'big' else ''})")


if __name__ == "__main__":
    main()
