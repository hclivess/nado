"""A payment to a multisig account lands in its [min_block, max_block] window (protocol.MSIG_PAY_FLEXIBLE_HEIGHT).

is_address() deliberately refuses the MSIG_PREFIX, so ops/block_ops._lands_flexibly classified a transfer TO a shared
account as exact-landing: includable only in the block numbered exactly its max_block, which no wallet targets. The
scheme-wallet walk of 2026-11-04 funded a 2-of-2 from the wallet's Send tab and watched the transfer sit validated in
every mempool, never mined. Pinned under both rule sets, on the producer side (match_transactions_target) and the
verifier side (check_target_match) — they must agree, or a producer builds a block its peers refuse:
  - from the gate, the payment is selected and accepted anywhere in its window, and still refused outside it;
  - below the gate, the old exact-landing rule stands, so history replays;
  - a plain-address transfer lands flexibly at every height, as before.

Run: python3 tests/test_a_payment_to_a_multisig_account_lands_in_its_window.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-msigpay-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import logging
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
from genesis import create_indexers
create_indexers()
import protocol as P
from ops import block_ops as B
from ops.multisig_ops import multisig_address
from signatures import generate_keydict

logger = logging.getLogger("msigpay"); logger.addHandler(logging.NullHandler())
fails = 0
POST = P.MSIG_PAY_FLEXIBLE_HEIGHT
PRE = POST - 1


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def tx(recipient, lo, hi, n):
    return {"sender": generate_keydict()["address"], "recipient": recipient, "amount": 1, "fee": P.MIN_TX_FEE,
            "min_block": lo, "max_block": hi, "txid": f"{n:064x}"}


def selected(t, h):
    return [x["txid"] for x in (B.match_transactions_target([t], h, logger) or [])] == [t["txid"]]


def accepted(t, h):
    return bool(B.check_target_match([t], h, logger))


MSIG = multisig_address(2, sorted([generate_keydict()["address"], generate_keydict()["address"]]))
PLAIN = generate_keydict()["address"]

post = tx(MSIG, POST - 5, POST + 50, 1)
check("POST: a payment to a multisig is selected inside its window", selected(post, POST + 10))
check("POST: ...and the verifier accepts it there", accepted(post, POST + 10))
check("POST: it is still refused before its min_block", not selected(post, POST - 6) and not accepted(post, POST - 6))
check("POST: and after its max_block", not selected(post, POST + 51) and not accepted(post, POST + 51))

pre = tx(MSIG, PRE - 20, PRE + 30, 2)
check("PRE: below the gate it is NOT selected inside its window (exact landing, as before)", not selected(pre, PRE - 5))
check("PRE: ...and the verifier refuses it there", not accepted(pre, PRE - 5))
exact = tx(MSIG, 0, PRE, 3)
check("PRE: only the exact max_block block takes it, as history did", selected(exact, PRE) and accepted(exact, PRE))

plain = tx(PLAIN, PRE - 20, POST + 30, 4)
check("a plain-address transfer lands flexibly below the gate", selected(plain, PRE - 5) and accepted(plain, PRE - 5))
check("...and above it", selected(plain, POST + 5) and accepted(plain, POST + 5))
check("a reserved recipient that lands exactly is unchanged (bond)",
      not selected(tx("bond", 0, POST + 30, 5), POST + 5) and selected(tx("bond", 0, POST + 5, 6), POST + 5))

print("ALL PASS — a payment to a multisig account lands in its window" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
