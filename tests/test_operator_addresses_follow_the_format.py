"""Every address the code hard-codes for the operator is an address on the LIVE format — a format switch that leaves one
behind names an account no key can derive, and nothing raises.

WHY (the gen-28 rehearsal, 2026-09-28). Address format 2 hashes the whole key, so every hard-coded address changes with
the reroll. The first cut remapped SETTLE_ANCHOR, FIXED_CIDS and the wallet's auto-vote default, and missed two:
  * protocol.GENESIS_ADDRESS was built from a 42-hex BODY — a format-1 literal genesis would credit to nobody;
  * the faucet contract identified its operator as make_address(<body>), which under format 2 hashes the body into an
    address nobody holds: every prize payout would have reverted on the operator check (the betanet-7 debrand broke it
    exactly this way once before).

Pins: each is a valid address on the live format; the operator's four uses name ONE address; the founder's two name one;
the faucet reads its operator from the fixed-cid table; and a 42/46-hex address literal outside the known set fails here.

Run: python3 tests/test_operator_addresses_follow_the_format.py
"""
import os, re, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-opaddr-")
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import protocol as P
from ops.address_ops import is_address
from execnode.code_codec import FIXED_CIDS
from execnode.games import faucet

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


# SETTLE_ANCHOR is read as SOURCE: importing execnode.execnode loads exec state (CLAUDE.md rule 4)
exn = open(os.path.join(ROOT, "execnode", "execnode.py")).read()
anchor = re.search(r'^SETTLE_ANCHOR = "([0-9a-f]+)"', exn, re.M).group(1)
js = open(os.path.join(ROOT, "static", "interface.js")).read()
vote = re.search(r"const AUTO_VOTE_DEFAULT_ALLOW = \[([^\]]*)\];", js).group(1)
vote = [v.strip().strip('"') for v in vote.split(",")]

for name, a in (("protocol.GENESIS_ADDRESS", P.GENESIS_ADDRESS), ("execnode SETTLE_ANCHOR", anchor),
                ("code_codec FIXED_CIDS faucet", FIXED_CIDS["faucet"]), ("code_codec FIXED_CIDS sovereign", FIXED_CIDS["sovereign"]),
                ("the faucet contract's OPERATOR", faucet.OPERATOR), ("the wallet's auto-vote default", vote[0])):
    check(f"{name} is an address on the live format ({P.ADDRESS_LENGTH} chars)", is_address(a) and len(a) == P.ADDRESS_LENGTH, a)
check("the operator's settle anchor, fixed cids and faucet operator are ONE address",
      len({anchor, FIXED_CIDS["faucet"], FIXED_CIDS["sovereign"], faucet.OPERATOR}) == 1)
check("the founder's genesis address and the auto-vote default are ONE address", P.GENESIS_ADDRESS == vote[0])
check("the faucet reads its operator from the fixed-cid table (never make_address of a body)",
      'OPERATOR = _FIXED_CIDS["faucet"]' in open(faucet.__file__).read())

# no other operator address literal hides in the shipped code (the sweep that found the two above)
KNOWN = {P._GENESIS_BODY, faucet.OPERATOR_PUBKEY, "6a7a7a6d26040d8d53ce66343a47347c9b79e814c6",   # body / vector bodies
         "18c3afa286439e7ebcb284710dbd4ae42bdaf21b80"}
KNOWN |= {"27f2870bb2969a4d2b9d4eea303bedea996b9ccc93479f"}      # the wallet's EARLIER default, kept to follow it forward
lits = []
for d in ("ops", "loops", "execnode", "static"):
    for dp, _dn, fns in os.walk(os.path.join(ROOT, d)):
        if "vendor" in dp or "target" in dp or "i18n_games" in dp:
            continue
        for fn in fns:
            if fn.endswith((".py", ".js", ".html")):
                for m in re.finditer(r"[\"']([0-9a-f]{42}(?:[0-9a-f]{4})?)[\"']", open(os.path.join(dp, fn), errors="ignore").read()):
                    if m.group(1) not in KNOWN:
                        lits.append((fn, m.group(1)))
for fn in ("protocol.py", "nado.py", "genesis.py"):
    for m in re.finditer(r"[\"']([0-9a-f]{42}(?:[0-9a-f]{4})?)[\"']", open(os.path.join(ROOT, fn)).read()):
        if m.group(1) not in KNOWN:
            lits.append((fn, m.group(1)))
check("no unlisted 42/46-hex address literal in the shipped code", not lits, lits[:5])

print("ALL PASS — every hard-coded operator address is on the live format" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
