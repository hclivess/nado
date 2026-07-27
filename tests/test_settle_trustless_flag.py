"""
TRUSTLESS-SETTLEMENT MASTER SWITCH (protocol.SETTLE_PROOF_TRUSTLESS) — proves the gated flip in isolation.

settlement_ops.settlement_justified gained a real branch: when the flag is ON, a settle-with-proof whose
STARK proof verified at block-validation (recorded via kv_ops.settlement_proof_put) justifies the exec root
with NO bonded quorum. When OFF (the alphanet-10 default) the marker is ignored and the chain is
byte-identical to the quorum-only path. This test pins BOTH behaviours deterministically, without STARK
proving (the real proof-verify end-to-end is tests/test_settle_with_proof.py t10 under NADO_HEAVY):

  * flag OFF: a recorded proof marker does NOT justify a root with no quorum  (no live regression)
  * flag ON : the same marker DOES justify, even against an EMPTY bonded registry (zero attesting shares)
  * revert : settlement_proof_del clears the marker (rollback symmetry) so justification disappears

Run: python3 tests/test_settle_trustless_flag.py
"""
import os, sys, tempfile, logging

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_trustless_")
os.environ.setdefault("NADO_TESTNET", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

logging.getLogger().addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

import protocol
from protocol import DEFAULT_NS
from ops import kv_ops
from ops import settlement_ops

fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1

NS, CURSOR, ROOT = DEFAULT_NS, 424242, "ab" * 32
EMPTY_REG = {}   # no bonded validators -> the quorum path can never justify (total shares == 0)

_saved = protocol.SETTLE_PROOF_TRUSTLESS
try:
    # baseline: nobody has attested (CURSOR, ROOT) and there is no proof marker
    protocol.SETTLE_PROOF_TRUSTLESS = False
    # The flag was ACTIVATED at the alphanet-11 trustless-settlement reroll (commit 95ecf25); it is ON in
    # source now. This test still forces it False/True locally below to prove BOTH gated behaviours.
    check("flag is ON in source (activated at the alphanet-11 reroll)", _saved is True)
    check("no marker, flag OFF, empty registry -> NOT justified",
          settlement_ops.settlement_justified(NS, CURSOR, ROOT, EMPTY_REG) is False)

    # record a proof marker (what apply/reflect_transaction does for a verified settle-with-proof)
    with kv_ops.write_txn():
        kv_ops.settlement_proof_put(NS, CURSOR, ROOT)
    check("marker is recorded", kv_ops.settlement_proven(NS, CURSOR, ROOT) is True)

    # flag OFF: the marker must be IGNORED (byte-identical to quorum-only, no live regression)
    protocol.SETTLE_PROOF_TRUSTLESS = False
    check("flag OFF: a recorded proof marker does NOT justify without quorum",
          settlement_ops.settlement_justified(NS, CURSOR, ROOT, EMPTY_REG) is False)

    # flag ON: the marker justifies, even with ZERO bonded/attesting shares -> proof is the sole authority
    protocol.SETTLE_PROOF_TRUSTLESS = True
    check("flag ON: the proof marker justifies with NO quorum (empty registry)",
          settlement_ops.settlement_justified(NS, CURSOR, ROOT, EMPTY_REG) is True)
    # and a DIFFERENT root at the same cursor is still unproven -> not justified (marker is root-specific)
    check("flag ON: a different root at the same cursor is NOT justified",
          settlement_ops.settlement_justified(NS, CURSOR, "cd" * 32, EMPTY_REG) is False)

    # revert symmetry: deleting the marker (rollback) removes justification even with the flag ON
    with kv_ops.write_txn():
        kv_ops.settlement_proof_del(NS, CURSOR, ROOT)
    check("rollback clears the marker", kv_ops.settlement_proven(NS, CURSOR, ROOT) is False)
    check("flag ON but marker reverted -> NOT justified (rollback symmetry)",
          settlement_ops.settlement_justified(NS, CURSOR, ROOT, EMPTY_REG) is False)
finally:
    protocol.SETTLE_PROOF_TRUSTLESS = _saved

print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
