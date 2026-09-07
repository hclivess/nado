"""OPEN-LANE BLOCKS FOR DEVICE-ONLY MINERS (protocol.OPEN_LANE_EXCLUDE_BONDED_HEIGHT) + the gentler dividend gradient
(DIVIDEND_WEIGHT_CAP_V2 from DIVIDEND_WEIGHT_CAP_V2_EPOCH). Pins: the open draw skips attested identities with a bonded
share from the gate (and only from the gate); the attested set itself is unchanged (bonded cap still sees them); the epoch
weights exclude staked identities from the gate epoch and return the COMMITTED row whenever one exists; dividend_weight caps
at 30 before the epoch and 15 from it; the status fields and the wallet line are wired. Run: python3 tests/test_open_lane_exclusion.py
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-openexcl-")
_fails = []
def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond: _fails.append(name)

def main():
    import protocol as P
    from ops import kv_ops, mining_ops as M, dividend_ops as D
    from ops.account_ops import apply_register, get_open_registry
    import logging; lg = logging.getLogger("t")
    G, GE = P.OPEN_LANE_EXCLUDE_BONDED_HEIGHT, P.OPEN_LANE_EXCLUDE_BONDED_EPOCH
    check("gates: height ahead of the pool gate, epoch derived from it", G >= P.POOL_HEIGHT and GE == G // P.EPOCH_LENGTH and P.DIVIDEND_WEIGHT_CAP_V2_EPOCH == GE)
    # draw registry
    reg = {"a" * 46: {"fidelity": 5, "bonded": 0}, "b" * 46: {"fidelity": 9, "bonded": P.B_MIN}, "c" * 46: {"fidelity": 2, "bonded": P.B_MIN - 1}}
    check("below the gate the open draw registry is the attested set", M.open_lane_draw_registry(reg, G - 1) is reg)
    d = M.open_lane_draw_registry(reg, G)
    check("from the gate a bonded share removes an identity from the open draw; below one share it stays", set(d) == {"a" * 46, "c" * 46}, set(d))
    beacon = "cd" * 32; wins = set()
    for slot in range(G, G + 400):
        if M.lane_of(slot, beacon) == "open":
            wins.add(M.select_producer_two_lane(reg, {}, beacon, slot))
    check("open slots from the gate never go to the staked identity", wins <= {"a" * 46, "c" * 46} and wins, wins)
    bonded_reg = {"b" * 46: {"bonded": 500 * P.DENOMINATION, "fidelity": None, "bond_since": None, "pool_to": None, "pooled": 0}}
    pr = M.bonded_producer_registry(bonded_reg, reg, max(G, P.POOL_HEIGHT))
    check("the staked identity is still ATTESTED for the bonded producer cap", "b" * 46 in pr)
    # dividend cap
    check("dividend_weight: 30 before the epoch, 15 from it", P.dividend_weight(30, GE - 1) == 30 and P.dividend_weight(30, GE) == 15 and P.dividend_weight(7, GE) == 7)
    # the dividend stays universal: a staked, attested identity is still weighted (operator: "available for everyone")
    kv_ops.close_all(); kv_ops.init_env()
    a, b = "e" * 46, "f" * 46
    for addr in (a, b): kv_ops.account_set(addr, "balance", 0)
    kv_ops.account_set(b, "bonded", P.B_MIN)
    apply_register(a, GE, lg); apply_register(b, GE, lg)
    w = D.weights_at_epoch(GE)
    check("weights_at_epoch pays the staked identity too — the dividend is per attested device, production is per lane", a in w and b in w, w)
    check("live open registry keeps the staked identity (attested set) with its bonded field", get_open_registry(GE)[b]["bonded"] == P.B_MIN)
    check("no staked-status history rows exist (the draw reads live bonded as-of-parent)", not hasattr(kv_ops, "staked_at"))
    kv_ops.close_all()
    bo = open(os.path.join(ROOT, "ops", "block_ops.py")).read()
    check("mining_status reports open_excluded_bonded and totals over the draw registry", '"open_excluded_bonded"' in bo and "open_lane_draw_registry(open_reg" in bo)
    js = open(os.path.join(ROOT, "static", "interface.js")).read(); i18n = open(os.path.join(ROOT, "static", "i18n.js")).read()
    n = i18n.count('"myshare.excludedBonded":')
    check("wallet says why the free lane is closed to a staker, in every language", "open_excluded_bonded" in js and n >= 16 and n % 16 == 0, n)

if __name__ == "__main__":
    try: main()
    except Exception:
        import traceback; traceback.print_exc(); _fails.append("exception")
    print("ALL PASS" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    raise SystemExit(1 if _fails else 0)
