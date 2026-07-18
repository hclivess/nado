"""
Re-key a genesis allocation for an ADDRESS-FORMAT change (doc/address-format.md).

An address is ADDRESS_PREFIX + the pubkey body + a checksum over prefix+body — so changing the
prefix (a rebrand) changes every address STRING while every KEY still owns the same account: the
new address is derivable from the old one (same body, new prefix, recomputed checksum). This tool
maps an alloc file old→new so a CHAIN_GENERATION reroll carries every balance to the same owners.

  python3 scripts/rekey_alloc.py <alloc.dat> <old_prefix> <new_prefix> > alloc_rekeyed.dat

The alloc format is one JSON object per line (or a single JSON dict) — whatever genesis.py reads;
addresses are re-keyed wherever they appear as dict keys or "address" fields. Reserved names
(treasury/faucet/…) pass through untouched. Every produced address is checksum-validated.

⚠ MULTISIG accounts CANNOT be re-keyed this way: their member address strings live INSIDE the
descriptor hash, so the new-format descriptor derives a different BODY — and P2SH-style opacity
means this tool cannot even identify which entries are multisig. Multisig balances must be moved
to keyed accounts before the snapshot (see doc/address-format.md, "Cutover caveat").
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops.address_ops import make_checksum, validate_address
from protocol import RESERVED_RECIPIENTS


def rekey(addr: str, old: str, new: str) -> str:
    if not isinstance(addr, str) or addr in RESERVED_RECIPIENTS or not addr.startswith(old):
        return addr
    body_hex = addr[len(old):-4]                      # strip old prefix + old 4-hex checksum
    fresh = new + body_hex
    out = fresh + make_checksum(fresh)
    assert validate_address(out), f"re-keyed address fails its own checksum: {out}"
    return out


def walk(obj, old, new):
    if isinstance(obj, dict):
        return {rekey(k, old, new): walk(v, old, new) for k, v in obj.items()}
    if isinstance(obj, list):
        return [walk(v, old, new) for v in obj]
    if isinstance(obj, str):
        return rekey(obj, old, new)
    return obj


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    path, old, new = sys.argv[1:4]
    raw = open(path, encoding="utf-8").read().strip()
    try:
        print(json.dumps(walk(json.loads(raw), old, new), separators=(",", ":"), sort_keys=True))
    except json.JSONDecodeError:                      # line-per-record format
        for line in raw.splitlines():
            line = line.strip()
            if line:
                print(json.dumps(walk(json.loads(line), old, new), separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
