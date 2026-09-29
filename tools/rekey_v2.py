"""Re-key a reroll carry to ADDRESS FORMAT 2 (gen 27 -> 28, betanet-9). Pure: no database, no network.

Used by exactly one carry: the one that crossed the format switch. Format 2 has been unconditional since the betanet-9
gate cleanup, so a carry from gen 28 onward re-keys nothing and tools/alphanet6_carryforward.py does not call this.

A format-1 address is the first 21 bytes of a public key; format 2 hashes the WHOLE key and carries a 4-byte checksum
(50 characters), so the old format is rejected by shape. The carry therefore moves every account to the address its
recorded key derives under format 2 — and every piece of carried state that names an address moves with it: device
bindings, aliases, account-auth histories, the present (leased) set and the relay seeds.

KEYS FROM OLDER GENERATIONS. Keys carry across rerolls, so an account that received but never sent on THIS chain has often
sent on an older one (measured at gen 27: 535 of 871 such accounts, 674 NADO). tools/recover_keys.py reads those keys
out of old-generation backups; rekey() accepts one only if it derives the account's format-1 address, and the owner's
wallet then derives the new address from the same private key with nothing to do. A key recorded on an older chain
carries exactly the trust of one recorded on this chain: it is the key that first sent from that address.

AN ACCOUNT WHOSE KEY NO CHAIN EVER SAW CANNOT BE RE-KEYED: a format-1 address commits to only 21 bytes that anyone can
match. It is carried AT ITS OLD 46-CHARACTER ADDRESS, which a format-2 chain rejects as a sender, and its owner's wallet
claims it with the key it already holds (`legacy_claim`, live from block 1 of gen 28 — the operator accepted that a
forger sharing the address's 21 bytes could claim first). Any bonded stake it held is released into its balance: a bonded identity nobody can sign for
would be drawn to produce and attest and could do neither.

Multisig addresses derive from their members' addresses, which all change here, and the descriptor is not on chain, so
a funded multisig account cannot be carried: the re-key refuses and the operator moves those funds first.
Supply is conserved exactly (bonded released into balance moves nothing out of the total)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops.address_ops import address_body_v2, make_checksum, legacy_address
from protocol import RESERVED_RECIPIENTS, MSIG_PREFIX, DOMAIN_ADDRESS_V2  # noqa: F401  (the domain is the address's)


def v2_address(public_key: str) -> str:
    """The format-2 address of a key: body = address_body_v2(key), then a 4-byte checksum."""
    body = address_body_v2(public_key)
    return body + make_checksum(body, checksum_size=4)


def rekey(alloc: list, extra: dict, seeds: list, known: dict = None):
    """(alloc, extra, seeds, report) for a format-2 chain. Raises on anything that cannot be carried safely.
    `known` = {format-1 address: public key} recovered from older generations, used only for rows with no recorded key
    and only where the key derives that address (a key that does not is ignored, never trusted)."""
    remap, keyless, released, recovered = {}, [], 0, 0
    known = known or {}
    out = []
    for row in alloc:
        r = dict(row)
        a = r["address"]
        if a in RESERVED_RECIPIENTS:
            out.append(r)
            continue
        if MSIG_PREFIX and a.startswith(MSIG_PREFIX):
            if int(r.get("balance", 0)) or int(r.get("bonded", 0)):
                raise SystemExit(f"multisig account {a} holds funds — move them before the reroll (its address "
                                 f"derives from member addresses, which all change)")
            continue
        pk = r.get("public_key")
        if not pk and known.get(a):
            try:
                ok = legacy_address(known[a]) == a
            except Exception:
                ok = False
            if ok:
                pk = r["public_key"] = known[a]
                recovered += 1
        if pk:
            n = v2_address(pk)
            if n in remap.values():
                raise SystemExit(f"two keys map to one format-2 address {n}")
            remap[a] = n
            r["address"] = n
        else:
            keyless.append(a)
            if int(r.get("bonded", 0)):
                released += int(r["bonded"])
                r["balance"] = int(r.get("balance", 0)) + int(r["bonded"])
                r["bonded"] = 0
        out.append(r)

    def m(a, what):
        if a in RESERVED_RECIPIENTS:
            return a
        if a not in remap:
            raise SystemExit(f"{what} names {a}, which has no recorded key and cannot be re-keyed")
        return remap[a]

    x = dict(extra)
    x["devbind"] = sorted([k, m(a, "a device binding"), mode] for k, a, mode in extra.get("devbind", []))
    x["aliases"] = sorted([n, m(o, f"alias {n}")] for n, o in extra.get("aliases", []))
    x["auth_history"] = sorted([m(a, "an auth history"), ver, keys] for a, ver, keys in extra.get("auth_history", []))
    x["present"] = sorted(m(a, "the present set") for a in extra.get("present", []))
    # A RELAY SEED NOBODY CAN RE-KEY IS DROPPED, not refused (2026-09-28 rehearsal: 07a8b0aa…, a genesis seed that never
    # produced a block and whose key no chain ever saw). A seed is only "registered + a genesis lease if present", and an
    # identity with no key cannot produce on any chain; its coins carry at its old address like every keyless account's,
    # where its key claims them (legacy_claim). A PRESENT identity with no key still refuses, through the present set above.
    dropped_seeds = sorted(a for a in seeds if a not in remap and a not in RESERVED_RECIPIENTS)
    s2 = [m(a, "a relay seed") for a in seeds if a not in dropped_seeds]
    before = sum(int(r.get("balance", 0)) + int(r.get("bonded", 0)) for r in alloc)
    after = sum(int(r.get("balance", 0)) + int(r.get("bonded", 0)) for r in out)
    if before != after:
        raise SystemExit(f"re-key changed supply: {before} -> {after}")
    report = {"rekeyed": len(remap), "recovered_from_older_generations": recovered,
              "keyless_kept_at_old_address": len(keyless), "bond_released_raw": released, "remap": remap,
              "dropped_seeds": dropped_seeds}
    return out, x, s2, report
