"""A lone or minority bonded settler cannot make its own exec root the settled one (audit 2026-09-25 HIGH).

THE FINDING, reproduced here with real kv tables and real transactions: the settle quorum's denominator
(settlement_ops.active_settler_shares) is the stake that attested RECENTLY. It is empty on a fresh chain (every settler
starts from zero at a reroll; on betanet-8 the honest settlers' first attestations landed in block 12) and it empties
again once every other settler has been silent for SETTLE_ANCHOR_LONG_CURSORS (100,800 cursors). In both states the
first bonded account to settle is the whole denominator: one B_MIN bond justifies a made-up root, and dividend_withdraw
/ unshield / bridge_withdraw proven against that root pay DIVIDEND_POOL, SHIELD_ESCROW and BRIDGE_ESCROW to it.

THE FIX (the stake floor, settlement_ops.settlement_justified): a quorum-justified root also needs its attesting shares
to exceed SETTLE_FLOOR_NUM/SETTLE_FLOOR_DEN (1/16) of ALL bonded shares, which silence cannot shrink. Gen 27 gated it at
SETTLE_STAKE_FLOOR_HEIGHT (2^62, never live there); it held from block 1 on gen 28 and the gate was deleted after the
betanet-9 reroll, so the drain below the gate is history and only the rule is exercised here.
The registry below mirrors live betanet-8 on 2026-09-28: 952 bonded shares, four settlers holding 48 + 47 + 25 + 5.

The lone and minority settlers are refused, the honest settlers still settle, and every exit proven against the
minority root is refused.

Run: python3 tests/test_lone_settler_cannot_settle.py
"""
import os, sys, tempfile, logging, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-lone-settler-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

logger = logging.getLogger("lone-settler"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

import protocol as P
from protocol import B_MIN, DIVIDEND_POOL, SHIELD_ESCROW, BRIDGE_ESCROW, MIN_TX_FEE, CHAIN_ID, DEFAULT_NS
from ops import kv_ops
from ops import settlement_ops as SO
from ops.account_ops import create_account, get_account, reflect_transaction
from ops.mining_ops import total_bonded_shares
from ops.account_ops import get_bonded_registry
from ops.transaction_ops import (validate_transaction, construct_settle_tx, construct_dividend_withdraw_tx,
                                  construct_bridge_withdraw_tx, construct_bridge_deposit_tx, create_txid)
from ops.key_ops import generate_keys
from signatures import sign, unhex
from execnode.state import ExecState
from execnode import exec_root as ER

fails = []
def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"  [{detail}]"))
    if not cond:
        fails.append(name)

def refused(fn):
    """The AssertionError text if fn is refused, else None."""
    try:
        fn()
        return None
    except AssertionError as e:
        return str(e) or "refused"

def bal(a):
    acc = get_account(a, create_on_error=False)
    return acc["balance"] if acc else 0

def _bonded(shares, balance=B_MIN):
    kd = generate_keys()
    create_account(kd["address"], balance=balance, bonded=shares * B_MIN)
    kv_ops.account_set_field(kd["address"], "public_key", kd["public_key"])
    return kd

# --- the live betanet-8 shape (2026-09-28, /mining_status + the settle txs of blocks 27377..27777) ---------------------
SETTLERS = [_bonded(s) for s in (48, 47, 25, 5)]                   # the four accounts that actually settle: 125 shares
WHALE = _bonded(71)                                                # the largest bonded account; it does not settle
IDLE = [_bonded(s) for s in (46, 37, 35, 30, 27, 25, 22, 22, 21, 21, 21, 20, 20, 20, 19, 19, 19, 18, 18, 18, 17, 17,
                             16, 16, 15, 14, 13, 11, 10, 10, 10, 9, 8, 7, 7, 6, 6, 6, 6, 5, 5, 4, 4, 3, 3, 3, 3, 2, 2,
                             2, 2, 1, 1, 1, 1, 1)]                # the rest of the bonded registry: 725 idle shares
ATTACKER = _bonded(1, balance=B_MIN)                               # ONE B_MIN bond: 10 NADO
MINORITY = _bonded(30)                                             # a bigger attacker: 3 % of all bonded stake
create_account(DIVIDEND_POOL, balance=1_875_278_970_392)           # live balances at tip 27777
create_account(SHIELD_ESCROW, balance=1_123_000)
USER = generate_keys(); create_account(USER["address"], balance=5 * B_MIN)
kv_ops.account_set_field(USER["address"], "public_key", USER["public_key"])

REG = get_bonded_registry()
TOTAL = total_bonded_shares(REG)
check("the registry mirrors live betanet-8 (952 bonded shares, settlers 125)", TOTAL == 952 and
      sum(REG[k["address"]]["bonded"] // B_MIN for k in SETTLERS) == 125, TOTAL)

HONEST = "aa" * 32


def fabricated_state(who):
    """The attacker's made-up exec state: exit records paying it every escrow. No rule of the exec layer produced it —
    the point of a settled root is that nobody has to trust whoever computed it."""
    st = ExecState(tempfile.mktemp(prefix="nado_exec_fake_", suffix=".json", dir=os.environ["HOME"]))
    addr = who["address"]
    st.dividend_withdrawals["d1"] = {"addr": addr, "amount": bal(DIVIDEND_POOL)}
    st.unshield_withdrawals["u1"] = {"addr": addr, "amount": bal(SHIELD_ESCROW)}
    st.withdrawals["b1"] = {"addr": addr, "amount": kv_ops.bridge_escrow_ns(DEFAULT_NS)}
    st._touch()
    return st


def exits(st, who, h):
    """The three escrow exits the attacker proves against its root, as real signed transactions."""
    d = st.dividend_withdrawal_proof("d1")
    u = st.unshield_withdrawal_proof("u1")
    b = st.withdrawal_proof("b1")
    div = construct_dividend_withdraw_tx(who, d["amount"], "d1", d["proof"], max_block=h)
    uns = {"sender": who["address"], "recipient": "unshield", "amount": 0, "fee": 0, "timestamp": 1, "nonce": "nu",
           "data": {"addr": who["address"], "amount": u["amount"], "nonce": "u1", "proof": u["proof"]},
           "public_key": who["public_key"], "max_block": h, "chain_id": CHAIN_ID}
    uns["txid"] = create_txid(uns); uns["signature"] = sign(who["private_key"], unhex(uns["txid"]))
    brw = construct_bridge_withdraw_tx(who, who["address"], b["amount"], "b1", b["proof"], max_block=h)
    return {"dividend_withdraw": div, "unshield": uns, "bridge_withdraw": brw}


def fresh():
    SO._latest_settled_cache[0] = None          # the caches key on the write generation; start every read cold
    SO._recent_settled_cache[0] = None


def settle(kd, cursor, root, h):
    tx = construct_settle_tx(kd, exec_cursor=cursor, state_root=root, max_block=h)
    validate_transaction(tx, logger, h)
    with kv_ops.write_txn():
        reflect_transaction(tx, logger, h)
    fresh()
    return tx


def unsettle(tx, h):
    with kv_ops.write_txn():
        reflect_transaction(tx, logger, h, revert=True)
    fresh()


def t0_the_floor_is_unconditional():
    check("the floor has no gate left", not hasattr(P, "SETTLE_STAKE_FLOOR_HEIGHT"))
    check("the floor is 1/16 of all bonded shares", (P.SETTLE_FLOOR_NUM, P.SETTLE_FLOOR_DEN) == (1, 16))


def t1_fresh_chain_one_bond_cannot_drain():
    """THE FINDING on a fresh chain: nobody has settled yet, so one B_MIN bond is the whole quorum."""
    dep = construct_bridge_deposit_tx(USER, 3 * B_MIN, max_block=3, fee=MIN_TX_FEE)   # an honest bridge deposit
    validate_transaction(dep, logger, 3)
    with kv_ops.write_txn():
        reflect_transaction(dep, logger, 3)
    st = fabricated_state(ATTACKER)
    fake = st.state_root()
    h = 6
    tx = settle(ATTACKER, 5, fake, h)
    txs = exits(st, ATTACKER, h + 1)
    check("the lone 10-NADO settler's root is NOT settled (fresh chain)", SO.latest_settled() == (-1, None),
          SO.latest_settled())
    for kind, etx in txs.items():
        why = refused(lambda: validate_transaction(etx, logger, h + 1))
        check(f"{kind} against the lone settler's root is refused", why is not None and "settled" in why, why)
    check("the dividend pool is untouched", bal(DIVIDEND_POOL) == 1_875_278_970_392)
    unsettle(tx, h)

    # an honest first settlement (what betanet-8's four settlers did at block 12) still settles
    for kd in SETTLERS:
        kv_ops.settlement_put(DEFAULT_NS, 0, kd["address"], P.EXEC_GENESIS_ROOT)
    fresh()
    check("the four honest settlers' first root settles at cursor 0 (125 of 952 > 1/16)",
          SO.latest_settled() == (0, P.EXEC_GENESIS_ROOT), SO.latest_settled())
    for kd in SETTLERS:
        kv_ops.settlement_del(DEFAULT_NS, 0, kd["address"], P.EXEC_GENESIS_ROOT)
    fresh()
    # ...and a lone cursor-0 attestation, the one cursor a bare `cursor >= 1` would have missed, is covered too
    kv_ops.settlement_put(DEFAULT_NS, 0, ATTACKER["address"], fake)
    fresh()
    check("a lone cursor-0 attestation does not settle", SO.latest_settled() == (-1, None))
    kv_ops.settlement_del(DEFAULT_NS, 0, ATTACKER["address"], fake)
    fresh()


def t2_after_100800_silent_cursors_one_bond_cannot_drain():
    """THE FINDING after a long silence: the honest settlers' last attestations fall out of SETTLE_ANCHOR_LONG_CURSORS,
    the stake basis empties, and the next settler is its own quorum again."""
    c0 = 1000
    for kd in SETTLERS:
        kv_ops.settlement_put(DEFAULT_NS, c0, kd["address"], HONEST)
    fresh()
    check("the honest settlers settle (baseline)", SO.latest_settled() == (c0, HONEST))
    st = fabricated_state(ATTACKER)
    fake = st.state_root()
    h = c0 + P.SETTLE_ANCHOR_LONG_CURSORS + 1                     # honest silent for 100,800 cursors
    tx = settle(ATTACKER, h, fake, h)
    txs = exits(st, ATTACKER, h + 1)
    check("the lone settler cannot settle after the silence",
          SO.latest_settled() == (c0, HONEST), SO.latest_settled())
    for kind, etx in txs.items():
        why = refused(lambda: validate_transaction(etx, logger, h + 1))
        check(f"{kind} against the lone root is refused", why is not None and "window" in why, why)

    # a MINORITY settler (30 shares = 3 % of bonded, and the whole active set) is refused the same way
    tx2 = settle(MINORITY, h, fake, h)
    check("the 3 % minority settler cannot", SO.latest_settled() == (c0, HONEST), SO.latest_settled())
    for kind, etx in txs.items():
        why = refused(lambda: validate_transaction(etx, logger, h + 1))
        check(f"{kind} against the minority root is refused", why is not None, why)

    # the honest settlers come back: they settle at once, and the attackers' root stays unsettled
    for kd in SETTLERS:
        kv_ops.settlement_put(DEFAULT_NS, h + 60, kd["address"], HONEST)
    fresh()
    check("the honest settlers still settle next to the attackers", SO.latest_settled() == (h + 60, HONEST))
    check("...and the attackers' root is not in the exit window",
          all(r != fake for _c, r in SO.recent_settled_roots(k=3)), SO.recent_settled_roots(k=3))
    for kd in SETTLERS:
        kv_ops.settlement_del(DEFAULT_NS, h + 60, kd["address"], HONEST)
    unsettle(tx2, h)
    unsettle(tx, h)
    for kd in SETTLERS:
        kv_ops.settlement_del(DEFAULT_NS, c0, kd["address"], HONEST)
    fresh()


def t3_liveness_the_honest_settlers_keep_settling():
    """The price of the floor, pinned so nobody is surprised by it: the leak still carries the settlers through one
    dark member, and two small settlers alone (30 of 952 shares) wait for a large one to return."""
    c = 50_000
    for kd in SETTLERS:
        kv_ops.settlement_put(DEFAULT_NS, c, kd["address"], HONEST)
    fresh()
    check("all four settlers (125 shares) settle", SO.settlement_justified(DEFAULT_NS, c, HONEST, REG))
    later = c + P.SETTLE_ACTIVITY_CURSORS + 60                    # the largest settler has gone dark past the window
    for kd in SETTLERS[1:]:
        kv_ops.settlement_put(DEFAULT_NS, later, kd["address"], HONEST)
    check("with the largest settler dark, the other three (77 shares) still settle through the leak",
          SO.settlement_justified(DEFAULT_NS, later, HONEST, REG))
    # both large settlers dark: the stake anchor holds for SETTLE_ANCHOR_LONG_CURSORS (30 shares cannot move it), then
    # the rule before the floor let the two small ones settle alone — and so could any 10-NADO bond at that point (t2)
    both = later + P.SETTLE_ANCHOR_LONG_CURSORS + 60
    for kd in SETTLERS[2:]:
        kv_ops.settlement_put(DEFAULT_NS, both, kd["address"], HONEST)
    fresh()
    check("the two small settlers (30 shares) alone do not settle — 30 < 952/16; settlement waits for stake to return "
          "(the documented cost)", not SO.settlement_justified(DEFAULT_NS, both, HONEST, REG))
    for cc, group in ((c, SETTLERS), (later, SETTLERS[1:]), (both, SETTLERS[2:])):
        for kd in group:
            kv_ops.settlement_del(DEFAULT_NS, cc, kd["address"], HONEST)
    fresh()


def t4_validity_proven_roots_need_no_floor():
    """A root carried by a verified settle proof stays justified with no quorum at all — the floor is on the quorum."""
    kv_ops.settlement_proof_put(DEFAULT_NS, 70_000, HONEST)
    fresh()
    check("a proven root justifies with no attestations",
          P.SETTLE_PROOF_TRUSTLESS is False or SO.settlement_justified(DEFAULT_NS, 70_000, HONEST, REG))
    kv_ops.settlement_proof_del(DEFAULT_NS, 70_000, HONEST)


for name, fn in list(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        try:
            fn()
        except Exception as e:
            traceback.print_exc()
            check(f"{name} ran to the end", False, f"{type(e).__name__}: {e}")

print("ALL PASS" if not fails else f"{len(fails)} FAILURES")
sys.exit(1 if fails else 0)
