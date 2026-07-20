"""
Conservation invariants (ops/invariants.py) — and the regression net that proves they catch the bug CLASS.

~10 separate "coins from thin air" bugs have been fixed here. The point of these invariants is not to pass
today; it is that any FUTURE member of that class trips them. So the load-bearing tests below REPLAY the
historical bugs as fixtures and require each one to be caught. A test that only asserts "healthy state is
healthy" would have passed on every single day those bugs were live.

Each replay is annotated with the real incident it reproduces.

Run: python3 tests/test_invariants.py
"""
import os, sys, tempfile, traceback, random
os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="nado_inv_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import invariants as INV
from protocol import TREASURY_GENESIS, BRIDGE_ESCROW, SHIELD_ESCROW, DIVIDEND_POOL

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


class FakeState:
    """Minimal duck-typed stand-in for ExecState — the invariants only read these attributes."""
    def __init__(self, **kw):
        self.bridge = kw.get("bridge", {})
        self.withdrawals = kw.get("withdrawals", {})
        self.pool_value = kw.get("pool_value", 0)
        self.pool_fees = kw.get("pool_fees", 0)
        self.unshield_withdrawals = kw.get("unshield_withdrawals", {})
        self.dividend = kw.get("dividend", {})
        self.dividend_withdrawals = kw.get("dividend_withdrawals", {})
        self.div_carry = kw.get("div_carry", 0)


def accounts_of(d):
    """iter_accounts() over a {address: balance} or {address: (balance, bonded)} dict."""
    def _it():
        for a, v in d.items():
            b, bo = v if isinstance(v, tuple) else (v, 0)
            yield a, {"balance": b, "bonded": bo}
    return _it


def getter(d):
    """get_account(address, create_on_error=) over a {address: balance} dict."""
    def _get(address, create_on_error=True):
        if address not in d:
            return None
        v = d[address]
        b, bo = v if isinstance(v, tuple) else (v, 0)
        return {"balance": b, "bonded": bo}
    return _get


# ------------------------------------------------------------------ healthy baselines

def t_healthy_l1():
    accts = {"a": 700, "b": (200, 100)}                      # 1000 total incl. bonded
    ok, d = INV.check_l1_supply(accounts_of(accts), {"produced": 1200, "fees": 200})
    assert ok, f"a conserving ledger must pass: {d}"


def t_healthy_all_domains():
    accts = {BRIDGE_ESCROW: 500, SHIELD_ESCROW: 300, DIVIDEND_POOL: 900, "m": 1000}
    st = FakeState(bridge={"x": 400}, withdrawals={"1": {"addr": "x", "amount": 100}},
                   pool_value=250, pool_fees=10, unshield_withdrawals={"1": {"addr": "y", "amount": 40}},
                   dividend={"m": 100}, dividend_withdrawals={"1": {"addr": "m", "amount": 50}}, div_carry=25)
    ok, res = INV.check_all(accounts_of(accts), {"produced": 2700, "fees": 0}, getter(accts), st)
    assert ok, f"a fully-consistent system must pass every domain: {[r for r in res if not r['ok']]}"


# ------------------------------------------------------------------ HISTORICAL BUG REPLAYS
# Each of these reproduces the observable state a real, fixed bug produced. If a future change reopens
# any of them, the corresponding invariant must fail.

def t_replay_unbacked_shielded_mint():
    """2026-07-20 — a `blob` transfer with public_value > 0 minted notes with NO L1 escrow behind them,
    then unshielded them back out against SHIELD_ESCROW (fixed: state.py fences pv > 0 on both blob paths).

    Observable state: notes exist that no escrowed coin backs."""
    accts = {SHIELD_ESCROW: 0}                                # nobody ever deposited
    st = FakeState(pool_value=5_000_000_000_000)              # 500 NADO conjured
    ok, d = INV.check_shielded(getter(accts), st)
    assert not ok, "an unbacked shielded mint MUST trip check_shielded"
    assert d["delta"] > 0, f"delta must show the excess note value, got {d}"


def t_replay_shielded_mint_is_caught_at_mint_not_at_exit():
    """The same bug, but caught in the block the notes were CREATED rather than when they were withdrawn.
    Catching it only at exit is worthless — by then L1's escrow floor is the last line of defence and the
    thief is draining other depositors."""
    accts = {SHIELD_ESCROW: 1_000}                            # one honest 1000-unit deposit
    honest = FakeState(pool_value=1_000)
    assert INV.check_shielded(getter(accts), honest)[0], "the honest deposit alone must be consistent"
    minted = FakeState(pool_value=1_000 + 999_000)            # mint, nothing withdrawn yet
    ok, d = INV.check_shielded(getter(accts), minted)
    assert not ok and d["pending_exits"] == 0, \
        "the mint must be visible with ZERO exits pending — i.e. at mint time, not at exit"


def t_replay_bridge_double_credit_inflation():
    """2026-07-10 — a bridge deposit was mined and credited 7x (tx double-inclusion with no cross-block
    dedup), inflating exec-side balances with no matching L1 escrow (fixed: at-most-once inclusion).

    Observable state: exec-side credit exceeds the escrow backing it."""
    accts = {BRIDGE_ESCROW: 200_000_000_000}                  # ONE 20-NADO deposit locked
    st = FakeState(bridge={"attacker": 200_000_000_000 * 7})  # credited seven times
    ok, d = INV.check_bridge(getter(accts), st)
    assert not ok and d["delta"] > 0, f"7x-credited bridge deposit MUST trip check_bridge: {d}"


def t_replay_escrow_drain_via_oversized_exit():
    """2026-07-03 C-3 — a mod-P wraparound let a 1-coin note prove a colossal unshield, draining the whole
    escrow (fixed: in-circuit range gadget + MAX_EXIT_VALUE). The exit RECORD is the observable: an exit is
    pending that the pool's own value cannot fund."""
    accts = {SHIELD_ESCROW: 1_000}
    st = FakeState(pool_value=1_000, unshield_withdrawals={"1": {"addr": "eve", "amount": 4_600_000_000_000}})
    ok, d = INV.check_shielded(getter(accts), st)
    assert not ok and d["delta"] > 0, f"an exit larger than the pool MUST trip check_shielded: {d}"


def t_replay_l1_forged_reward():
    """A block reward outside the legal range (audit C1) or any credit-without-debit shows up as supply in
    excess of total emission."""
    accts = {"miner": 5_000_000_000_000}
    ok, d = INV.check_l1_supply(accounts_of(accts), {"produced": 1_000_000_000, "fees": 0})
    assert not ok and d["delta"] > 0, f"supply above emission MUST trip check_l1_supply: {d}"


def t_replay_rollback_credit_without_debit():
    """A reorg that reverses a debit but not its credit (the class ops/account_ops.get_totals(revert=True)
    exists to prevent) leaves supply BELOW emission — the opposite sign, equally a bug."""
    accts = {"a": 10}
    ok, d = INV.check_l1_supply(accounts_of(accts), {"produced": 1000, "fees": 0})
    assert not ok and d["delta"] < 0, f"supply below emission MUST also trip: {d}"


def t_replay_dividend_overcredit():
    """Dividend credited exec-side beyond what the L1 pool ever collected. The pool legitimately runs AHEAD
    (undistributed inflow), so only this direction is a violation."""
    accts = {DIVIDEND_POOL: 100}
    ahead = FakeState(dividend={"m": 40})
    assert INV.check_dividend(getter(accts), ahead)[0], "an undistributed surplus is legal, not a violation"
    ok_a, da = INV.check_dividend(getter(accts), ahead)
    assert da["status"] == "undistributed", f"a surplus must be labelled, not left None: {da}"
    over = FakeState(dividend={"m": 500})
    ok, d = INV.check_dividend(getter(accts), over)
    assert not ok and d["status"] == INV.MINT, f"entitlement exceeding the pool MUST trip check_dividend: {d}"


def t_every_check_reports_a_status():
    """Every domain must speak the same vocabulary — a report where one check says status=None is one a
    reader has to special-case, and special cases are where things get skimmed past."""
    accts = {BRIDGE_ESCROW: 10, SHIELD_ESCROW: 10, DIVIDEND_POOL: 10, "m": 10}
    st = FakeState(bridge={"x": 10}, pool_value=10, dividend={"m": 10})
    _ok, res = INV.check_all(accounts_of(accts), {"produced": 40, "fees": 0}, getter(accts), st)
    for r in res:
        assert r.get("status"), f"check {r.get('domain')} reported no status: {r}"


# ------------------------------------------------------------------ fuzz: unknown paths

def t_fuzz_conserving_transfers_never_trip():
    """No false positives under random but CONSERVING activity. A check that cries wolf gets ignored, and
    an ignored invariant catches nothing. Seeded, so a failure is reproducible."""
    rng = random.Random(20260720)
    for _ in range(300):
        names = [f"a{i}" for i in range(rng.randint(2, 8))]
        accts = {n: rng.randint(0, 10_000) for n in names}
        supply = sum(accts.values())
        for _ in range(rng.randint(1, 20)):                    # random internal transfers conserve supply
            src, dst = rng.choice(names), rng.choice(names)
            amt = rng.randint(0, accts[src])
            accts[src] -= amt; accts[dst] += amt
        ok, d = INV.check_l1_supply(accounts_of(accts), {"produced": supply - TREASURY_GENESIS, "fees": 0})
        assert ok, f"conserving transfers must never trip the supply check: {d}"


def t_fuzz_any_injected_delta_is_caught():
    """The converse: inject a non-zero delta anywhere and it is ALWAYS caught, at any magnitude — including
    one raw unit, the size a rounding bug produces."""
    rng = random.Random(4242)
    for _ in range(300):
        accts = {f"a{i}": rng.randint(0, 10_000) for i in range(rng.randint(1, 6))}
        supply = sum(accts.values())
        delta = rng.choice([1, -1, rng.randint(2, 10**12), -rng.randint(2, 10**12)])
        victim = rng.choice(list(accts))
        if accts[victim] + delta < 0:
            continue
        accts[victim] += delta
        ok, d = INV.check_l1_supply(accounts_of(accts), {"produced": supply - TREASURY_GENESIS, "fees": 0})
        assert not ok and d["delta"] == delta, f"injected delta {delta} must be caught exactly: {d}"


def t_skipped_checks_are_reported_not_silently_passed():
    """Without an exec view only the L1 supply check can run. A bare ok=true would then read as
    "everything reconciles" when three of four domains never executed — the exact false comfort an
    invariant exists to remove. Skipped domains must appear explicitly with ok=None."""
    accts = {"a": 100}
    ok, res = INV.check_all(accounts_of(accts), {"produced": 100, "fees": 0}, getter(accts), None)
    skipped = [r for r in res if r.get("ok") is None]
    assert len(skipped) == len(INV.ESCROW_DOMAINS), f"every escrow domain must be reported skipped: {res}"
    assert all("skipped" in r for r in skipped), "a skipped check must say WHY"
    assert {r["domain"] for r in skipped} == set(INV.ESCROW_DOMAINS)
    assert ok, "skipped checks must not make the run fail either — they are unknown, not violated"


def t_stranded_is_reported_but_does_not_alarm():
    """Escrow holding MORE than is owed is coin nobody can claim — undesirable, but no supply was created.
    It must be REPORTED (status=stranded, exact delta) without setting ok=False. This is what stops the two
    long-standing gaps on the live chain from rendering the check permanently red, which is how a detector
    gets ignored right up until the run that matters."""
    accts = {SHIELD_ESCROW: 310_000_000_000}                  # 31 NADO escrowed, pool empty (the live case)
    st = FakeState(pool_value=0)
    ok, d = INV.check_shielded(getter(accts), st)
    assert ok, "stranded coin must NOT alarm — nothing was minted"
    assert d["status"] == INV.STRANDED and d["delta"] == -310_000_000_000, f"but it must be reported: {d}"


def t_mint_and_stranded_are_distinguished():
    """The two directions must never collapse into one verdict — that distinction is the whole point."""
    accts = {BRIDGE_ESCROW: 1_000}
    mint = FakeState(bridge={"eve": 9_000})
    strand = FakeState(bridge={"honest": 100})
    ok_m, dm = INV.check_bridge(getter(accts), mint)
    ok_s, ds = INV.check_bridge(getter(accts), strand)
    assert not ok_m and dm["status"] == INV.MINT and dm["delta"] > 0, f"over-credit is a MINT: {dm}"
    assert ok_s and ds["status"] == INV.STRANDED and ds["delta"] < 0, f"under-credit is STRANDED: {ds}"


def t_check_all_never_raises():
    """check_all is called from the node's periodic duty. A broken input must degrade to a reported
    failure, never an exception into the caller."""
    def _boom():
        raise RuntimeError("db exploded")
    ok, res = INV.check_all(_boom, {"produced": 0, "fees": 0}, getter({}), None)
    assert not ok and any("error" in r for r in res), "a blown check must be REPORTED, not raised"


for name, fn in [
    ("healthy L1 ledger passes", t_healthy_l1),
    ("healthy full system passes every domain", t_healthy_all_domains),
    ("REPLAY 2026-07-20 unbacked shielded mint", t_replay_unbacked_shielded_mint),
    ("REPLAY caught at mint time, not at exit", t_replay_shielded_mint_is_caught_at_mint_not_at_exit),
    ("REPLAY 2026-07-10 bridge 7x double-credit", t_replay_bridge_double_credit_inflation),
    ("REPLAY 2026-07-03 C-3 oversized escrow drain", t_replay_escrow_drain_via_oversized_exit),
    ("REPLAY forged block reward", t_replay_l1_forged_reward),
    ("REPLAY rollback credit-without-debit", t_replay_rollback_credit_without_debit),
    ("REPLAY dividend over-credit", t_replay_dividend_overcredit),
    ("fuzz: conserving activity never false-positives", t_fuzz_conserving_transfers_never_trip),
    ("fuzz: any injected delta is caught exactly", t_fuzz_any_injected_delta_is_caught),
    ("skipped checks are reported, not silently passed", t_skipped_checks_are_reported_not_silently_passed),
    ("every check reports a status", t_every_check_reports_a_status),
    ("stranded coin reported but does not alarm", t_stranded_is_reported_but_does_not_alarm),
    ("mint vs stranded are distinguished", t_mint_and_stranded_are_distinguished),
    ("check_all never raises into the caller", t_check_all_never_raises),
]:
    check(name, fn)

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
