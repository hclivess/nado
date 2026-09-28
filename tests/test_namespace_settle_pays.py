"""An exec node's settle for a non-default namespace pays the fee validation demands (ops/transaction_ops.construct_settle_tx).

WHY (found 2026-09-28 by the gen-28 rehearsal). From SPAM_HARDEN_HEIGHT a settle outside the default namespace must pay
MIN_TX_FEE, but construct_settle_tx — the only builder, used by every exec settle loop (execnode.py: quorum settle,
proof settle, bare retry) — always signed fee 0. The txid covers the fee, so no caller could fix it afterwards: every
settle an exec node posted for a NADO_EXEC_NAMESPACES namespace was refused.

Pins, on real tables (throwaway HOME) with a bonded validator:
  1. a default-namespace settle is still fee 0 (byte-identical) and validates;
  2. a namespace settle from the builder carries MIN_TX_FEE and VALIDATES above the gate;
  3. below the gate (probed at gen 27's 24000) the builder still signs fee 0, as the rule then was.

Run: python3 tests/test_namespace_settle_pays.py
"""
import os, sys, tempfile, logging
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-nssettle-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
from genesis import create_indexers
create_indexers()
import protocol as P
from ops.account_ops import create_account
from ops.transaction_ops import construct_settle_tx, validate_transaction
from ops.key_ops import generate_keys
from ops import kv_ops

logger = logging.getLogger("nssettle"); logger.addHandler(logging.NullHandler())
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def verdict(tx, h):
    try:
        validate_transaction(tx, logger, h)
        return None
    except Exception as e:
        return str(e) or type(e).__name__


kd = generate_keys()
create_account(kd["address"], balance=P.B_MIN, bonded=4 * P.B_MIN)
LIVE = P.SPAM_HARDEN_HEIGHT
H = max(LIVE, 1) + 700                                    # above the gate on either generation

tx = construct_settle_tx(kd, exec_cursor=H, state_root="a" * 64, max_block=H + 5)
check("a default-namespace settle is still fee 0", tx["fee"] == 0 and "ns" not in tx["data"], tx["fee"])
check("...and validates", verdict(tx, H) is None, verdict(tx, H))
tx = construct_settle_tx(kd, exec_cursor=H, state_root="a" * 64, max_block=H + 5, ns="rollupa")
check("a namespace settle from the builder carries MIN_TX_FEE", tx["fee"] == P.MIN_TX_FEE, tx["fee"])
check("...and VALIDATES above the gate (it was refused: 'pays the minimum fee')", verdict(tx, H) is None, verdict(tx, H))

from ops.transaction_ops import construct_xmsg_tx
xt = construct_xmsg_tx(kd, "rollupa", "rollupb", {"seq": 0}, [], max_block=H + 5)
check("the xmsg builder also carries MIN_TX_FEE from the gate (it signed 0: every delivery refused)", xt["fee"] == P.MIN_TX_FEE,
      xt["fee"])

P.SPAM_HARDEN_HEIGHT = 24000                              # gen 27's gate: below it the rule did not exist
try:
    tx = construct_settle_tx(kd, exec_cursor=100, state_root="a" * 64, max_block=105, ns="rollupa")
    check("below the gate the builder signs fee 0, as the rule then was", tx["fee"] == 0, tx["fee"])
    xt = construct_xmsg_tx(kd, "rollupa", "rollupb", {"seq": 0}, [], max_block=105)
    check("...and so does the xmsg builder (below the gate an xmsg must be exactly fee 0)", xt["fee"] == 0, xt["fee"])
finally:
    P.SPAM_HARDEN_HEIGHT = LIVE

kv_ops.close_all()
print("ALL PASS — a namespace settle pays what validation demands" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
