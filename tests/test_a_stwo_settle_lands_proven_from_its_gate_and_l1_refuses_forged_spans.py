"""A STWO SETTLE LANDS PROVEN FROM ITS GATE, AND L1 REFUSES FORGED SPANS (G8; protocol.STWO_SETTLE_HEIGHT,
ops/transaction_ops._stwo_settle_check, ops/account_ops' settle branch, ops/settle_chain.py).

An L1 database and a from-genesis exec node are built from the same blocks: a dice table opened, then a span (60, 300] in
which a bet binds an epoch beacon and a later settle reads it (a BEACON chain read, one Stwo VM proof), RANDAO reveals,
dividend accrual across four epoch boundaries with a non-zero carry; then a span (300, 360] with no contract call. The
settled tip is justified by the bonded quorum at 60. Then, through validate_transaction and reflect_transaction:
  BOTH RULE SETS
  1. below the gate (the shipped value, dormant on generation 29) a settle carrying `stwo` is REFUSED with the gate's
     message, the honest bundle notwithstanding, and nothing moves: no proven marker, the settled tip stays; even a
     settle that reached apply carrying `stwo` below the gate records no marker;
  2. from the gate the honest bundle validates, the apply records the proven marker and settlement_justified accepts the
     root on a 1-of-5-shares settler's word (no quorum), latest_settled moves to it; the revert removes exactly that
     marker and the tip returns. The no-call span then extends the PROVEN tip the same way (no VM proof, no prover);
  FORGERIES, each refused for its own reason at L1: a state_root other than the proven one; a bundle for another span; a
     bundle whose pre-state is not the justified tip; a tampered chain read (one reveal of the epoch the bet reads added to
     L1's state); a tampered boundary carry; a span longer than SETTLE_PROOF_MAX_SPAN, a span reaching the block that
     carries it, a non-default namespace;
  NOT A JUDGEMENT: a bundle not yet in DA, or a span block this node does not hold, DEFERS (ProofUnavailable, never a
     rejection, never memoised: the same tx validates once the data arrives); a block deep below the tip is judged on
     structure only (no fetch); a pooled settle is verified ONCE (the second validation fetches nothing), and the memo
     answers only for the bytes it saw (a corrupted bundle under another commitment is refused after the honest one
     verified);
  3. L1's own Chain (ops/settle_chain.l1_chain, from kv_ops) equals settle_b2.reference_chain on both real spans.
Needs the nightly toolchain for the call span's VM proof and stable Rust for the node's verifier; without them the call
span is SKIPPED (named) and the no-call span, which needs neither, still runs every rule above it can.
Run: python3 tests/test_a_stwo_settle_lands_proven_from_its_gate_and_l1_refuses_forged_spans.py
"""
import os
_REAL_HOME = os.path.expanduser("~")      # BEFORE isolate: the toolchains live under the real HOME
import _harness
HOME = _harness.isolate("nado-test-stwo-settle-l1-")
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(os.path.join(HOME, "nado", d), exist_ok=True)
import json
import logging

from genesis import create_indexers
create_indexers()

from execnode import block_apply, settle_b2 as S2, zkvm2
from execnode.games import dice
from execnode.records_effects import dividend_accrual_effects
from execnode.state import ExecState
from hashing import blake2b_hash
from ops import kv_ops, settle_chain as SC, transaction_ops as TXO
from ops.account_ops import create_account, reflect_transaction, get_bonded_registry
from ops.block_ops import save_block
from ops.key_ops import generate_keys
from ops.settlement_ops import latest_settled, settlement_justified
from ops.transaction_ops import ProofUnavailable, construct_settle_tx, validate_transaction
from protocol import B_MIN, DEFAULT_NS, EPOCH_LENGTH as L, SETTLE_PROOF_MAX_SPAN, STWO_SETTLE_HEIGHT
from tests._stwo_settle_build import NIGHTLY, build, build_verifier

T = _harness.Report()
logger = logging.getLogger("stwo-settle")
logger.addHandler(logging.NullHandler())
A = "ndo" + "A" * 45
B = "ndo" + "B" * 45
C = "ndo" + "C" * 45
V1 = generate_keys()
V2 = generate_keys()
create_account(V1["address"], balance=B_MIN, bonded=4 * B_MIN)       # 4 of 5 shares
create_account(V2["address"], balance=B_MIN, bonded=1 * B_MIN)       # 1 of 5: never a quorum alone

# ---- the chain ------------------------------------------------------------------------------------------------------
# the registry committed from block 1 (EXEC_ADDR_ROOT_HEIGHT's reroll value; 8500 on the live chain), so the dice payout to
# a player registered before the span is provable — the span test pins it the same way
_harness.pinned(EXEC_ADDR_ROOT_HEIGHT=1).__enter__()
DC = dice.build()
st0 = ExecState(os.path.join(HOME, "probe.json"))
D_CID = st0.contract_id(A, DC, "d")
_n = [0]


def blob(who, payload):
    _n[0] += 1
    return {"recipient": "blob", "sender": who, "txid": "t%d" % _n[0], "data": payload}


def call(who, m, args, value=0):
    return blob(who, {"op": "call", "contract": D_CID, "method": m, "args": args, **({"value": value} if value else {})})


def txs_at(h):
    out = []
    if h == 1:
        out += [blob(A, {"op": "deploy", "runtime": "zkvm", "code": DC, "nonce": "d"})]
        out += [{"recipient": "bridge", "sender": x, "amount": 10**7} for x in (A, B, C)]
    if h == 2:
        out.append(call(A, "open", [1], 10**6))
    if h == 61:
        out.append(call(B, "bet", [3, 1, 50], 100))
    if h == 300:
        out.append(call(C, "settle", [3]))
    if h >= 1 and h % L == 1:
        out.append({"recipient": "duty", "sender": A, "data": {"reveal": {"target_epoch": h // L + 1, "secret": "s%d" % h}}})
    return out


N = 360
BLOCKS = [{"block_number": h, "block_hash": "%064x" % (0xc0de0000 + 104729 * h), "block_transactions": txs_at(h)}
          for h in range(N + 1)]


def accrual(E):
    return ({0: 4000, 1: 1001, 2: 333}.get(E, 7 * E + 1), {A: 3, B: 1, C: 1})


# ---- L1's state, as L1 writes it ---------------------------------------------------------------------------------------
for b in BLOCKS:
    save_block(b, logger)
    kv_ops.block_index_put(b["block_number"], b["block_hash"])
    for tx in b["block_transactions"]:
        if tx["recipient"] == "duty":
            kv_ops.reveal_put(tx["data"]["reveal"]["target_epoch"], tx["data"]["reveal"]["secret"])
carry = 0
for E in range(N // L):
    inflow, w = accrual(E)
    kv_ops.dividend_inflow_add(E, inflow)
    kv_ops.epoch_weights_commit(E, w)
    _eff, carry = dividend_accrual_effects(inflow, w, carry, E)       # loops/core_loop._accrual_effects' chain
    kv_ops.exec_summary_put((E + 1) * L, True, {}, records=[], derivable=True, div_carry=carry)

# ---- the exec node, from genesis -----------------------------------------------------------------------------------------
st = ExecState(os.path.join(HOME, "st.json"))
states = {"default": st}
snap, root_at = {}, {}
for b in BLOCKS:
    h = b["block_number"]
    while st.last_div_epoch < h // L - 1:
        E = st.last_div_epoch + 1
        st.accrue_dividend_epoch(*accrual(E), epoch=E)
        st.last_div_epoch = E
    block_apply.begin(states, h)
    block_apply.dispatch(states, st, b, {}, set(), verbose=False)
    block_apply.close(states, h, b["block_hash"])
    root_at[h] = st.state_root()
    if h in (60, 120, 300):
        snap[h] = st.clone()
SPAN1, SPAN2 = BLOCKS[61:301], BLOCKS[301:361]

# ---- DA stand-in: the commitment is the blob's hash (the real one binds the bytes the same way), and fetches are counted
DA, FETCHES = {}, []


def put(bundle):
    raw = json.dumps(bundle, separators=(",", ":"), sort_keys=True).encode()
    c = blake2b_hash(raw.hex())[:64]
    DA[c] = raw
    return c


def fetch(c, timeout=8):
    FETCHES.append(c)
    return DA.get(c)


TXO._fetch_da_proof = fetch


def settle(v, cursor, root, c, ns=DEFAULT_NS):
    return construct_settle_tx(v, cursor, root, max_block=1, ns=ns, stwo=c)


def reason(fn):
    try:
        fn()
        return ""
    except ProofUnavailable as e:
        return "DEFER " + str(e)
    except Exception as e:
        return str(e) or type(e).__name__


kv_ops.settlement_put(DEFAULT_NS, 60, V1["address"], root_at[60])     # the quorum justifies 60 (4 of 5 shares)
kv_ops.settlement_put(DEFAULT_NS, 60, V2["address"], root_at[60])
T.check("0. the quorum's justified tip is (60, root@60)", latest_settled() == (60, root_at[60]), latest_settled())

# ---- 3 (first): L1's own Chain equals the exec node's on both real spans
d1 = SC.compare_with_reference(S2.reference_chain(snap[60], SPAN1, accrual), SC.l1_chain(60), SPAN1)
d2 = SC.compare_with_reference(S2.reference_chain(snap[300], SPAN2, accrual), SC.l1_chain(300), SPAN2)
T.check("3. L1's Chain (kv_ops via ops/settle_chain) equals reference_chain on both real spans", not d1 and not d2, d1[:3] + d2[:3])

# ---- the toolchains -------------------------------------------------------------------------------------------------------
BIN, blog = build(_REAL_HOME, "vm_settle")
SO, slog = build_verifier(_REAL_HOME)
CALLS = BIN is not None and SO is not None
if BIN is None and blog:
    T.check("the vm_settle prover builds", False, blog)
if SO is None and slog and "error" in slog:
    T.check("the node's stwo_settle verifier builds on stable", False, slog)
if SO is not None:
    os.environ["NADO_STWO_SETTLE_LIB"] = SO
if not CALLS:
    print(f"SKIP  the call span (60, 300]: no {NIGHTLY} prover or no stable verifier here — the no-call span still runs")


def honest(pre, span):
    return S2.prove_span(pre, span, S2.reference_chain(pre, span, accrual), BIN)


if CALLS:
    B1 = honest(snap[60], SPAN1)
    T.check("the call span proves: one VM proof over the bet and the settle", B1["vm_proof"] and len(B1["runs"]) >= 2,
            len(B1["runs"]))
    c1 = put(B1)
    tx = settle(V2, 300, root_at[300], c1)

    # ---- 1. below the gate
    r = reason(lambda: validate_transaction(tx, logger, 310))
    T.check("1a. below STWO_SETTLE_HEIGHT (the shipped, dormant value) the honest Stwo settle is refused by the gate",
            STWO_SETTLE_HEIGHT == 1 << 62 and "below STWO_SETTLE_HEIGHT" in r and not FETCHES, (r, FETCHES))
    reflect_transaction(tx, logger, 310)                            # even if one reached apply below the gate...
    T.check("1b. ...nothing moves: no proven marker, the settled tip stays at 60",
            not kv_ops.settlement_proven(DEFAULT_NS, 300, root_at[300]) and latest_settled() == (60, root_at[60]))
    reflect_transaction(tx, logger, 310, revert=True)

    with _harness.pinned(STWO_SETTLE_HEIGHT=100):
        # ---- forgeries
        bad_root = "%064x" % 7
        r = reason(lambda: validate_transaction(settle(V2, 300, bad_root, c1), logger, 310))
        T.check("F1. refused: a state_root other than the one the bundle proves", "not the settle's state_root" in r, r)
        c_other = put(honest(snap[60], BLOCKS[61:241]))             # a real proof of (60, 240], offered for (60, 300]
        r = reason(lambda: validate_transaction(settle(V2, 300, root_at[300], c_other), logger, 310))
        T.check("F2. refused: a bundle for another span", r and "DEFER" not in r, r)
        c_pre = put(honest(snap[120], BLOCKS[121:301]))             # pre-state 120: not the justified tip
        r = reason(lambda: validate_transaction(settle(V2, 300, root_at[300], c_pre), logger, 310))
        T.check("F3. refused: a bundle whose pre-state is not the justified tip", "wrong cursor" in r, r)
        epochs = sorted({e[1] for run in B1["runs"] for e in run["io"] if e[0] == zkvm2.IO_BEACON})
        T.check("the span reads a beacon (the bet's epoch)", bool(epochs), B1["runs"])
        kv_ops.reveal_put(epochs[0], "a-reveal-L1-never-saw")
        r = reason(lambda: validate_transaction(settle(V2, 300, root_at[300], c1), logger, 311))
        T.check("F4. refused: a chain read that is not L1's (one reveal of the bet's epoch added to L1's state)",
                "chain read" in r or "VM proof" in r, r)
        kv_ops.reveal_del(epochs[0], "a-reveal-L1-never-saw")
        TXO._STWO_VERIFY_MEMO.clear()
        doc = kv_ops.exec_summary_get(60)
        kv_ops.exec_summary_restore(60, dict(doc, dc=doc["dc"] + 1))
        r = reason(lambda: validate_transaction(settle(V2, 300, root_at[300], c1), logger, 312))
        T.check("F5. refused: a tampered boundary carry (the replay lands elsewhere)", "post root" in r, r)
        kv_ops.exec_summary_restore(60, doc)
        TXO._STWO_VERIFY_MEMO.clear()

        # ---- not a judgement
        n0 = len(FETCHES)
        TXO._STWO_VERIFY_MEMO.clear()
        saved = DA.pop(c1)
        r = reason(lambda: validate_transaction(tx, logger, 313))
        T.check("D1. a bundle not yet in DA DEFERS (ProofUnavailable), it is not refused", r.startswith("DEFER"), r)
        DA[c1] = saved
        r = reason(lambda: validate_transaction(tx, logger, 313))
        T.check("D2. ...and is not memoised: the same tx validates once the blob arrives", r == "", r)
        n1 = len(FETCHES)
        r2 = reason(lambda: validate_transaction(tx, logger, 313))
        T.check("D3. a pooled settle is verified ONCE: the second validation fetches nothing", r2 == "" and len(FETCHES) == n1,
                (r2, n1, len(FETCHES)))
        corrupt = json.loads(DA[c1])
        corrupt["post_root"] = root_at[300]
        corrupt["runs"][0]["n_steps"] += 1
        c_bad = put(corrupt)
        r = reason(lambda: validate_transaction(settle(V2, 300, root_at[300], c_bad), logger, 313))
        T.check("D4. the memo answers only for the bytes it saw: a corrupted bundle (same claims) is refused after the "
                "honest one verified", "VM proof" in r, r)
        TXO._STWO_VERIFY_MEMO.clear()
        n2 = len(FETCHES)
        r = reason(lambda: TXO._validate_settle(settle(V2, 300, root_at[300], c_bad), 313, True))
        T.check("D5. a block deep below the tip is judged on structure only: no fetch, no verify", r == "" and len(FETCHES) == n2,
                r)

        # ---- 2. from the gate: lands proven, reverts exactly
        validate_transaction(tx, logger, 313)
        reflect_transaction(tx, logger, 313)
        reg = get_bonded_registry()
        T.check("2a. from the gate the honest settle validates and its apply records the proven marker",
                kv_ops.settlement_proven(DEFAULT_NS, 300, root_at[300]))
        T.check("2b. settlement_justified accepts the root on a 1-of-5 settler's word, and latest_settled moves to it",
                settlement_justified(DEFAULT_NS, 300, root_at[300], reg) and latest_settled() == (300, root_at[300]),
                latest_settled())
        reflect_transaction(tx, logger, 313, revert=True)
        T.check("2c. the revert removes exactly that marker, and the tip returns to the quorum's 60",
                not kv_ops.settlement_proven(DEFAULT_NS, 300, root_at[300]) and latest_settled() == (60, root_at[60]))
        reflect_transaction(tx, logger, 313)                        # land it again: the no-call span extends it
        T.check("2d. ...and re-applying lands it again", latest_settled() == (300, root_at[300]))
else:
    kv_ops.settlement_put(DEFAULT_NS, 300, V1["address"], root_at[300])     # the quorum takes the tip to 300 instead
    T.check("0b. (no prover) the quorum justifies 300", latest_settled() == (300, root_at[300]), latest_settled())

# ---- the no-call span (300, 360]: needs neither the prover nor the native verifier
B2 = S2.prove_span(snap[300], SPAN2, S2.reference_chain(snap[300], SPAN2, accrual), None)
T.check("the no-call span proves without a VM proof", B2["vm_proof"] is None and not B2["runs"])
c2 = put(B2)
tx2 = settle(V2, 360, root_at[360], c2)
r = reason(lambda: validate_transaction(tx2, logger, 370))
T.check("1c. below the gate the no-call Stwo settle is refused too", "below STWO_SETTLE_HEIGHT" in r, r)
with _harness.pinned(STWO_SETTLE_HEIGHT=100):
    r = reason(lambda: validate_transaction(settle(V2, 360, root_at[360], c2), logger, 360))
    T.check("F6. refused: a span reaching the block that carries it", "wholly below" in r, r)
    r = reason(lambda: validate_transaction(settle(V2, 360, root_at[360], c2, ns="rollupa"), logger, 370))
    T.check("F7. refused: a namespace other than the default one", "default namespace" in r or "fee" in r, r)
    r = reason(lambda: validate_transaction(settle(V2, 300 + SETTLE_PROOF_MAX_SPAN + 1, "%064x" % 9, c2), logger,
                                            300 + SETTLE_PROOF_MAX_SPAN + 50))
    T.check("F8. refused: a span longer than SETTLE_PROOF_MAX_SPAN", "SETTLE_PROOF_MAX_SPAN" in r, r)
    h_body = kv_ops.hash_by_number(330)
    kv_ops.block_index_del(330, h_body)
    TXO._STWO_VERIFY_MEMO.clear()
    r = reason(lambda: validate_transaction(tx2, logger, 370))
    T.check("D6. a span block this node does not hold DEFERS (ProofUnavailable)", r.startswith("DEFER"), r)
    kv_ops.block_index_put(330, h_body)
    r = reason(lambda: validate_transaction(tx2, logger, 370))
    T.check("2e. the no-call span validates from the gate, extending the justified tip", r == "", r)
    reflect_transaction(tx2, logger, 370)
    T.check("2f. ...lands proven, and latest_settled moves to 360",
            kv_ops.settlement_proven(DEFAULT_NS, 360, root_at[360]) and latest_settled() == (360, root_at[360]))
    reflect_transaction(tx2, logger, 370, revert=True)
    T.check("2g. ...and its revert is the exact inverse", not kv_ops.settlement_proven(DEFAULT_NS, 360, root_at[360])
            and latest_settled()[0] == 300)
T.done()
