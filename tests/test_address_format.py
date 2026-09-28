"""THE ADDRESS FORMAT, AND THE DISCRIMINATOR THAT REPLACED THE PREFIX.

alphanet-14 removed the "mldsa44" prefix with no backwards compatibility. An address is now 42 hex chars of
the pubkey plus a 4-hex blake2b checksum — 46 characters. From gen 28 (address format 2) the 42-hex body is a hash of
the whole key and the checksum is 8 hex — 50 characters (tests/test_address_format_v2.py); the checks below are
written against the live format's constants, so they hold on either.

The removal itself is easy. The dangerous part is what the prefix was quietly load-bearing for: a dozen sites
asked `x.startswith(ADDRESS_PREFIX)` to mean "is this recipient an address rather than a reserved protocol
name or an alias". With an empty prefix `startswith("")` is True for EVERY string, and NONE of those sites
would have raised — they would simply have started answering yes to everything:

  * block_ops._lands_flexibly would classify bond / register / attest / settle as flexibly-landing and
    silently drop the exact-landing timing invariant those transactions depend on. A consensus change with
    no error and no traceback.
  * alias_ops.valid_alias_name would reject the entire alias namespace.
  * the HTLC / faucet / wallet recipient checks would go vacuous.

So the checks below are not really about the format. They pin the DISCRIMINATOR — that `is_address()` says
no to the things the old sniff would now say yes to. That is the property whose failure is invisible.
"""
import os as _os, tempfile as _tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): never the live node's HOME or exec files
_os.environ["HOME"] = _tempfile.mkdtemp(prefix="nado-test-")
_os.environ["NADO_EXEC_STATE"] = _os.path.join(_os.environ["HOME"], "exec_state.json")
_os.environ["NADO_EXEC_DA"] = _os.path.join(_os.environ["HOME"], "exec_da")
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol as P
from ops.address_ops import make_address, validate_address, is_address, make_checksum

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


PK = "96381e3725f85cfe0ab8de17623957b4565ca9b04d37b903075f2723600c21e3"
ADDR = make_address(PK)

# ---------------------------------------------------------------- the format itself
check(P.ADDRESS_PREFIX == "", "ADDRESS_PREFIX is empty — the prefix is gone, not merely unused")
CK = P.ADDRESS_CHECKSUM * 2                                     # 4 hex on format 1, 8 on format 2
check(len(ADDR) == P.ADDRESS_LENGTH == (46 if P.ADDRESS_FORMAT == 1 else 50),
      f"an address is {P.ADDRESS_LENGTH} chars (got {len(ADDR)})")
check(not ADDR.startswith("mldsa44"), "no residual prefix on a freshly derived address")
check(all(c in "0123456789abcdef" for c in ADDR), "an address is lowercase hex end to end")
if P.ADDRESS_FORMAT == 1:
    check(ADDR.startswith(PK[:P.ADDRESS_BODY]), "the body is the leading pubkey hex, unchanged")
else:
    from ops.address_ops import legacy_address
    check(not ADDR.startswith(PK[:P.ADDRESS_BODY]) and len(ADDR) - CK == P.ADDRESS_BODY,
          "format 2: the body is a hash of the key, not its leading hex (the forgery the format closes)")
    check(not validate_address(legacy_address(PK)), "format 2: the key's format-1 address is no address")
check(ADDR[-CK:] == make_checksum(ADDR[:-CK]), f"the trailing {CK} hex are the blake2b checksum over the rest")

# ---------------------------------------------------------------- verification strength is UNCHANGED
# The prefix never took part in validation — validate_address has always checked only the checksum. So the
# answer to "does this string belong to NADO" is exactly as strong as it was before the removal.
check(validate_address(ADDR), "a derived address validates")
for i in (0, 7, 20, len(ADDR) - 5):
    typo = ADDR[:i] + ("0" if ADDR[i] != "0" else "1") + ADDR[i + 1:]
    check(not validate_address(typo), f"a one-character typo at index {i} is rejected")
check(not validate_address(ADDR[:-1]), "truncation is rejected")
check(not validate_address(ADDR + "0"), "extension is rejected")

# ---------------------------------------------------------------- THE DISCRIMINATOR (the actual hazard)
check(is_address(ADDR), "is_address accepts a real address")
for name in sorted(P.RESERVED_RECIPIENTS):
    if not is_address(name):
        continue
    check(False, f"is_address must reject the reserved name {name!r}")
check(all(not is_address(n) for n in P.RESERVED_RECIPIENTS),
      f"is_address rejects ALL {len(P.RESERVED_RECIPIENTS)} reserved protocol names "
      f"(startswith('') would have accepted every one)")
check(not is_address("alice"), "is_address rejects an alias name")
check(not is_address(""), "is_address rejects the empty string")
check(not is_address(None), "is_address rejects None rather than raising")
check(not is_address(12345), "is_address rejects a non-string rather than raising")
check(not is_address(ADDR.upper()), "is_address rejects uppercase — addresses are canonical lowercase")
check(not is_address("z" * P.ADDRESS_LENGTH), "is_address rejects a right-length non-hex string")
check(not is_address("0" * P.ADDRESS_LENGTH), "is_address rejects right-length hex with a wrong checksum")

# a multisig account is NOT a keyed address; callers meaning "any account" must say so explicitly
if P.MSIG_PREFIX:
    msig = P.MSIG_PREFIX + ADDR[len(P.MSIG_PREFIX):]
    check(not is_address(msig), "is_address rejects a multisig account (MSIG_PREFIX is a separate namespace)")

# ---------------------------------------------------------------- the consensus routing it now drives
from ops.block_ops import _lands_flexibly

check(_lands_flexibly({"recipient": ADDR}), "a plain transfer to an address lands FLEXIBLY")
check(_lands_flexibly({"recipient": "blob"}), "a blob lands flexibly (explicitly listed)")
for r in ("bond", "unbond", "register", "attest", "settle"):
    if r in P.RESERVED_RECIPIENTS:
        check(not _lands_flexibly({"recipient": r}),
              f"{r!r} keeps EXACT landing — the invariant an empty-prefix sniff would have destroyed")
check(not _lands_flexibly({"recipient": "alice"}), "an alias recipient keeps exact landing")

# ---------------------------------------------------------------- the alias namespace survives
from ops.alias_ops import valid_alias_name

check(valid_alias_name("alice"), "a normal alias name is still valid (a bare sniff would reject every name)")
check(not valid_alias_name(ADDR), "an address is never a valid alias name")

print()
if fails:
    print(f"{len(fails)} CHECK(S) FAILED:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("ALL ADDRESS-FORMAT AND DISCRIMINATOR CHECKS PASSED")
