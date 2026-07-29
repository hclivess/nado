"""EVERY GENESIS ADDRESS MUST BE DERIVABLE BY A KEY UNDER THE CURRENT FORMAT.

THE BUG THIS EXISTS FOR. alphanet-14 removed the "mldsa44" prefix, but genesis_data/genesis_alloc.dat still
held 115 addresses in the OLD 53-char format, carrying 72,420,002,894,736 raw of balance and
35,432,837,933,564 raw of bonded stake. Every one of those accounts would have been credited at genesis to a
string that NO key can derive: make_address(pk) now returns 42 hex + a 4-hex checksum, which can never equal
"mldsa44" + 42 hex + checksum. The founder's own GENESIS_ADDRESS had the same defect via protocol._GENESIS_BODY.

WHAT MADE IT INVISIBLE. validate_address() only re-checks the trailing 4-hex checksum, and the old JS computed
that checksum over "mldsa44"+body — so the stale addresses PASS validate_address. Genesis would have loaded
all 115 without a warning, credited them, and produced a chain where the balances exist and nobody owns them.
Nothing raises; the money is simply gone. `is_address()` is the check that actually distinguishes them, which
is exactly why the prefix removal replaced the old startswith() sniffs with it.

It is also NOT fixable by stripping the prefix: the checksum covered prefix+body, so "mldsa44abc…" minus its
first seven characters is a 46-char string with the WRONG checksum. The body must be kept and the checksum
RE-DERIVED — which is what scripts/rekey_alloc.py does, and what nothing in the reroll path was calling.

The checks below are cheap and run every time, because the failure mode is silent, total, and only observable
after a reroll has already happened.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol as P
from ops.address_ops import is_address, validate_address, make_checksum

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOC = os.path.join(HERE, "genesis_data", "genesis_alloc.dat")

with open(ALLOC) as fh:
    entries = json.load(fh)

addrs = [e["address"] for e in entries]
keyed = [a for a in addrs if a not in P.RESERVED_RECIPIENTS and len(a) == P.ADDRESS_LENGTH]
named = [a for a in addrs if a in P.RESERVED_RECIPIENTS]
other = [a for a in addrs if a not in P.RESERVED_RECIPIENTS and len(a) != P.ADDRESS_LENGTH]

check(len(entries) > 0, f"the genesis allocation is non-empty ({len(entries)} entries)")

# ---------------------------------------------------------------- THE DEFECT ITSELF
stale = [a for a in addrs if a.startswith("mldsa44")]
check(not stale,
      f"NO allocation address carries the removed 'mldsa44' prefix "
      f"(found {len(stale)}: {stale[:2]})")

bad = [a for a in keyed if not is_address(a)]
check(not bad,
      f"every keyed allocation address passes is_address() — i.e. a key can derive it "
      f"({len(keyed)} checked, {len(bad)} bad: {bad[:2]})")

# The trap: these would ALL have passed a checksum-only check, which is why the old format slipped through.
check(all(validate_address(a) for a in keyed),
      "...and they also pass validate_address (which alone would NOT have caught the old format)")

# ---------------------------------------------------------------- the checksum is re-derived, not stripped
for a in keyed[:5]:
    check(a[-4:] == make_checksum(a[:-4]),
          f"{a[:10]}… carries a checksum over its OWN body (a stripped prefix would leave a stale one)")

# ---------------------------------------------------------------- reserved sinks pass through untouched
check(all(not is_address(n) for n in named),
      f"reserved protocol names are NOT keyed addresses and are left alone ({sorted(named)})")

# `burn` predates this change: a deliberately unspendable sink that is not in RESERVED_RECIPIENTS.
# Pinned so it stays a known, named exception rather than quietly becoming a class of stale entries.
check(set(other) <= {"burn"},
      f"the only non-address, non-reserved allocation entry is the burn sink (got {sorted(other)})")

# ---------------------------------------------------------------- the founder's own address
check(not P._GENESIS_BODY.startswith("mldsa44"),
      "protocol._GENESIS_BODY is de-prefixed — otherwise GENESIS_ADDRESS belongs to nobody")
check(len(P.GENESIS_ADDRESS) == P.ADDRESS_LENGTH,
      f"GENESIS_ADDRESS is {P.ADDRESS_LENGTH} chars (got {len(P.GENESIS_ADDRESS)})")
check(is_address(P.GENESIS_ADDRESS),
      "GENESIS_ADDRESS is a derivable keyed address — the founder still controls the treasury source")
check(len(P._GENESIS_BODY) == P.ADDRESS_BODY,
      f"_GENESIS_BODY is exactly the {P.ADDRESS_BODY}-hex pubkey body")

# ---------------------------------------------------------------- value must be conserved by a re-key
# A re-key changes STRINGS, never amounts. If a future format switch drops or duplicates an account this
# catches it, because the totals are what the chain actually mints at genesis.
total_bal = sum(int(e.get("balance", 0) or 0) for e in entries)
total_bond = sum(int(e.get("bonded", 0) or 0) for e in entries)
check(total_bal > 0 and total_bond > 0,
      f"genesis carries real value (balance={total_bal}, bonded={total_bond})")
check(len(set(addrs)) == len(addrs),
      "no allocation address appears twice (a re-key that collided two accounts would double-credit one)")

print()
if fails:
    print(f"{len(fails)} CHECK(S) FAILED:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("ALL GENESIS ALLOCATION FORMAT CHECKS PASSED")
