"""
CONSERVATION INVARIANTS — make "coins printed from thin air" a self-announcing bug class.

Roughly ten distinct mint/drain bugs have been found and fixed in this codebase (escrow drains, mod-P
wraparounds, tx double-inclusion inflation, an unbacked shielded mint, banked-game field wraps). Every one
had the SAME shape: a value that was PROVEN or VALIDATED but never AUTHORISED against a conservation rule.
Auditing finds the next instance; it does not find the one after that.

These checks close the class instead of the instance. Supply is a closed system with exactly one legal
source (block emission) and a fixed set of escrows, so any mint — known bug or unknown — must break one of
the equalities below. They are PURE functions of committed state: no mutation, no consensus effect, safe to
call from anywhere. A violation is reported, never raised into the consensus path (a false positive must
never halt the chain; see loops/core_loop where this runs as a periodic duty).

The four domains:
  L1 SUPPLY      sum(balance + bonded) over every account == TREASURY_GENESIS + produced - fees
  BRIDGE         BRIDGE_ESCROW  == exec-side credited balances + unclaimed exit records
  SHIELDED       SHIELD_ESCROW  == live note total + unclaimed exits + fees burned in-pool
  DIVIDEND       DIVIDEND_POOL  >= accrued + unclaimed exits + carry     (see check_dividend on why >=)

THE SHIELDED ONE IS THE POINT. A shielded pool's individual note values are private, but every CHANGE to
their total is public by construction: a deposit carries its L1 amount, and a transfer's public_value/fee
are public inputs to the proof. So the pool's AGGREGATE supply is auditable even though its contents are
not (the property Zcash's turnstile relies on). ExecState tracks it as pool_value/pool_fees. The 2026-07-20
unbacked mint — a transfer blob with public_value > 0 minting notes with no escrow behind them — would have
tripped check_shielded in the block it landed, with no review and no reasoning about join-splits.
"""
from protocol import (TREASURY_GENESIS, BRIDGE_ESCROW, SHIELD_ESCROW, DIVIDEND_POOL, HTLC_ESCROW)


class Violation(Exception):
    """Raised only by assert_all() — the TEST entry point. The node path uses check_all() and logs."""


def _bal(get_account, address):
    """Spendable balance of a reserved escrow account (0 when it has never been created)."""
    acc = get_account(address, create_on_error=False)
    return int((acc or {}).get("balance", 0) or 0)


def check_l1_supply(iter_accounts, totals):
    """Total coin in existence == everything emission ever created, minus everything fees destroyed.

    Emission is the ONLY source (TREASURY_GENESIS is 0 — no premine), and fees are the only sink, so this
    single equality closes every L1-side mint: a forged reward, a double-credited transfer, a reserved-tx
    replay, a rollback that credits without debiting. Bonded stake counts as supply — it is locked, not
    destroyed. Returns (ok, detail)."""
    actual = 0
    n = 0
    for _addr, doc in iter_accounts():
        actual += int(doc.get("balance", 0) or 0) + int(doc.get("bonded", 0) or 0)
        n += 1
    expected = TREASURY_GENESIS + int(totals.get("produced", 0)) - int(totals.get("fees", 0))
    return actual == expected, {"domain": "l1_supply", "accounts": n, "actual": actual,
                                "expected": expected, "delta": actual - expected}


def check_bridge(get_account, exec_state):
    """Every coin locked in BRIDGE_ESCROW is either credited to somebody exec-side or sitting in an
    unclaimed exit record. A gap in the POSITIVE direction (escrow > accounted) is stranded coin; a gap in
    the NEGATIVE direction is exec-side value with no L1 backing — i.e. a mint. Returns (ok, detail)."""
    escrow = _bal(get_account, BRIDGE_ESCROW)
    credited = sum(int(v) for v in (getattr(exec_state, "bridge", None) or {}).values())
    pending = sum(int(w.get("amount", 0)) for w in (getattr(exec_state, "withdrawals", None) or {}).values())
    accounted = credited + pending
    return escrow == accounted, {"domain": "bridge", "escrow": escrow, "credited": credited,
                                 "pending_exits": pending, "delta": accounted - escrow}


def check_shielded(get_account, exec_state):
    """SHIELD_ESCROW == live note value + unclaimed unshield exits + fees burned inside the pool.

    Coins enter ONLY via an L1 `shield` (escrow +amount, pool_value +amount) and leave ONLY via a recorded
    unshield exit that L1 later releases. A fee burned in a transfer leaves the notes but never leaves
    escrow, hence the third term. delta > 0 means notes exist that no escrowed coin backs — an unbacked
    mint. Returns (ok, detail)."""
    escrow = _bal(get_account, SHIELD_ESCROW)
    notes = int(getattr(exec_state, "pool_value", 0) or 0)
    fees = int(getattr(exec_state, "pool_fees", 0) or 0)
    pending = sum(int(w.get("amount", 0))
                  for w in (getattr(exec_state, "unshield_withdrawals", None) or {}).values())
    accounted = notes + pending + fees
    return escrow == accounted, {"domain": "shielded", "escrow": escrow, "note_value": notes,
                                 "pending_exits": pending, "fees_burned": fees,
                                 "delta": accounted - escrow}


def check_dividend(get_account, exec_state):
    """DIVIDEND_POOL >= accrued + unclaimed exits + carry.

    Deliberately an INEQUALITY, unlike the others. The pool fills on L1 from every block's open-lane cut,
    but the exec layer only distributes an epoch once its cursor passes it, so the pool legitimately runs
    AHEAD by any not-yet-distributed inflow. The direction that matters is the other one: exec-side
    entitlement exceeding the pool means dividend was credited that no L1 coin backs. Returns (ok, detail)."""
    pool = _bal(get_account, DIVIDEND_POOL)
    accrued = sum(int(v) for v in (getattr(exec_state, "dividend", None) or {}).values())
    pending = sum(int(w.get("amount", 0))
                  for w in (getattr(exec_state, "dividend_withdrawals", None) or {}).values())
    carry = int(getattr(exec_state, "div_carry", 0) or 0)
    claimable = accrued + pending + carry
    return pool >= claimable, {"domain": "dividend", "pool": pool, "accrued": accrued,
                               "pending_exits": pending, "carry": carry,
                               "undistributed": pool - claimable}


def check_all(iter_accounts, totals, get_account, exec_state=None):
    """Run every invariant that the available inputs allow. Returns (ok, [detail, ...]) — each detail
    carries `domain` and `ok`, so a caller can log the failures without knowing the check set. Never
    raises: a check that blows up is reported as a failure with its error, not propagated into a caller
    that may be on the block path."""
    results = []
    def _run(fn, *a):
        try:
            ok, detail = fn(*a)
        except Exception as e:                       # a broken check must not take the node with it
            ok, detail = False, {"domain": getattr(fn, "__name__", "?"), "error": repr(e)}
        detail["ok"] = bool(ok)
        results.append(detail)
    _run(check_l1_supply, iter_accounts, totals)
    if exec_state is not None:
        _run(check_bridge, get_account, exec_state)
        _run(check_shielded, get_account, exec_state)
        _run(check_dividend, get_account, exec_state)
    return all(r["ok"] for r in results), results


def assert_all(iter_accounts, totals, get_account, exec_state=None):
    """check_all, but raises Violation on the first failure — the TEST entry point. The node never uses
    this: on a live chain a false positive must degrade to a loud log, never a halt."""
    ok, results = check_all(iter_accounts, totals, get_account, exec_state)
    if not ok:
        bad = [r for r in results if not r["ok"]]
        raise Violation(f"conservation invariant violated: {bad}")
    return results
