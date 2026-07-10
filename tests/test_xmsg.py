"""
Cross-rollup message DELIVERY (xmsg) end-to-end: rollup A emits an outbox message (committed in A's state
root); A settles on L1; a relayer submits xmsg{from_ns=A, message, proof} which L1 verifies against A's
SETTLED root (exactly like the bridge) + a (from_ns, seq) nullifier; the receiver rollup B's exec node then
delivers it to its inbox. Proves valid delivery, forgery / replay / unsettled rejection, and receiver-side
inbox commitment.

Run: python3 tests/test_xmsg.py
"""
import os, sys, tempfile, traceback, logging
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_xmsg_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logger = logging.getLogger("xmsg"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import B_MIN
from ops.account_ops import create_account, reflect_transaction
from ops.transaction_ops import validate_transaction, construct_settle_tx, construct_xmsg_tx
from ops.settlement_ops import latest_settled
from ops.key_ops import generate_keys
from execnode.state import ExecState

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()
def raises(fn):
    try: fn(); return False
    except Exception: return True

V = generate_keys(); create_account(V["address"], balance=B_MIN, bonded=4 * B_MIN)   # bonded validator (4/4 > 2/3)
U = generate_keys(); create_account(U["address"], balance=1_000_000)                 # relayer


def _emit_and_settle(ns_from, cursor, to_ns="rollupb", data={"hi": 1}):
    """Emit a message in A's exec state, settle A's root on L1 under `ns_from`@`cursor`; return (message, proof)."""
    st = ExecState(tempfile.mktemp(prefix="nado_a_", suffix=".json"))
    st.apply_blob({"op": "emit", "to_ns": to_ns, "data": data}, sender="ndoalice", txid="e1")
    root = st.state_root()
    op = st.outbox_proof(0)
    reflect_transaction(construct_settle_tx(V, exec_cursor=cursor, state_root=root, max_block=1, ns=ns_from), logger, 1)
    assert latest_settled(ns_from)[1] == root, "A root settled on L1"
    return op["message"], op["proof"]


def t1_valid_delivery_then_replay_rejected():
    """A settled message delivers once (proof verifies vs the settled root); a replay is blocked by the nullifier."""
    msg, proof = _emit_and_settle("nsa", 1)
    xt = construct_xmsg_tx(U, "nsa", "rollupb", msg, proof, max_block=1)
    validate_transaction(xt, logger, 1)
    reflect_transaction(xt, logger, 1)                        # burns (nsa, 0) nullifier
    assert raises(lambda: validate_transaction(xt, logger, 1)), "replay must be rejected by the nullifier"

def t2_forged_payload_rejected():
    """Tampering the message payload (keeping the real proof) fails the settled-root Merkle check."""
    msg, proof = _emit_and_settle("nsb", 2, data={"hi": 1})
    forged = dict(msg); forged["data"] = {"hi": 999}
    xt = construct_xmsg_tx(U, "nsb", "rollupb", forged, proof, max_block=1)
    assert raises(lambda: validate_transaction(xt, logger, 1)), "forged payload fails the proof"

def t3_unsettled_namespace_rejected():
    """A message whose namespace has no settled root cannot be delivered."""
    st = ExecState(tempfile.mktemp(suffix=".json"))
    st.apply_blob({"op": "emit", "to_ns": "rollupb", "data": {"x": 1}}, sender="ndoalice", txid="e1")
    op = st.outbox_proof(0)
    xt = construct_xmsg_tx(U, "neverset", "rollupb", op["message"], op["proof"], max_block=1)
    assert raises(lambda: validate_transaction(xt, logger, 1)), "no settled root -> reject"

def t4_to_ns_mismatch_rejected():
    """The delivery to_ns must match the message's own to_ns (can't re-route a message to another rollup)."""
    msg, proof = _emit_and_settle("nsc", 3, to_ns="rollupb")
    xt = construct_xmsg_tx(U, "nsc", "rollupOTHER", msg, proof, max_block=1)   # message says rollupb
    assert raises(lambda: validate_transaction(xt, logger, 1)), "to_ns mismatch -> reject"

def t5_receiver_inbox_commitment():
    """The receiver exec node folds an L1-verified message into its inbox, changing its committed state_root."""
    msg, _ = _emit_and_settle("nsd", 4, data={"hello": "world"})
    rb = ExecState(tempfile.mktemp(prefix="nado_b_", suffix=".json"))
    r0 = rb.state_root()
    rb.apply_xmsg("nsd", msg)
    assert len(rb.inbox) == 1 and rb.inbox[0]["data"] == {"hello": "world"} and rb.inbox[0]["from_ns"] == "nsd"
    assert rb.state_root() != r0, "delivery is committed in the receiver's state_root"


for name, fn in sorted(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
