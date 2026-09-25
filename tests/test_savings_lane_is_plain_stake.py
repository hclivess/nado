"""THE SAVINGS LANE IS PLAIN STAKE (protocol.py, doc/reroll.md §"What the cleanup deletes").

Gen 25 shaped both producer draws with eight gates — the per-device cap, the knee/tail curve, staking pools, the open-lane
exclusion of stakers, and the four gates that retired them. From generation 26 on every one of them resolved to "plain
stake, nobody excluded, pools refused", and the code paths were deleted. This pins that the deletion kept exactly that
behaviour — any drift here changes producer draws or tx verdicts on the live chain:
  1. the bonded producer draw runs over the raw bonded registry at EVERY slot (the same object, weight = stake);
  2. the open draw runs over the whole attested registry at every slot, stakers included;
  3. pool / delegate / undelegate are still refused by validate_transaction, with the pre-cleanup message, and keep
     their reserved name and per-block uniqueness key;
  4. a bonded-registry entry is {bonded, fidelity, bond_since} with the same address set as the bonded scan;
  5. the dividend gradient the exclusion once shared an epoch with stays at the flat 15 cap;
  6. none of the deleted gates, helpers or endpoints came back.
Run: python3 tests/test_savings_lane_is_plain_stake.py
"""
import os, sys, tempfile, logging
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-plainstake-")   # BEFORE any repo import (CLAUDE.md rule 4)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def main():
    from genesis import create_indexers
    create_indexers()
    import protocol as P
    from ops import kv_ops, mining_ops as M
    from ops.account_ops import create_account, get_bonded_registry
    from ops.transaction_ops import validate_transaction, create_txid, create_nonce, reserved_uniqueness_key
    from ops.key_ops import generate_keys
    from config import get_timestamp_seconds
    from signatures import sign, unhex
    lg = logging.getLogger("t"); lg.addHandler(logging.NullHandler())
    N = P.DENOMINATION

    # 1 + 2. both draw registries are their argument, at every slot — including the gen-25 gate heights
    a, b, c = "a" * 46, "b" * 46, "c" * 46
    bonded = {a: {"bonded": 50_000 * N, "fidelity": None, "bond_since": None},
              b: {"bonded": 50 * N, "fidelity": None, "bond_since": None}}
    open_reg = {a: {"fidelity": 5, "bonded": 50_000 * N}, c: {"fidelity": 9, "bonded": 0}}
    slots = (0, 1, 2, 4200, 6000, 6600, 11800, 16150, 16900, 19400, 29900, 10 ** 9)
    check("the bonded producer draw is the raw registry, same object, at every slot",
          all(M.bonded_producer_registry(bonded, open_reg, s) is bonded for s in slots)
          and all(M.bonded_producer_registry(bonded, {}, s) is bonded for s in slots))
    check("the open draw is the whole attested registry, same object, at every slot",
          all(M.open_lane_draw_registry(open_reg, s) is open_reg for s in slots))
    beacon = "cd" * 32
    open_wins, bonded_wins = set(), {}
    for slot in range(1, 1200):
        w = M.select_producer_two_lane(open_reg, bonded, beacon, slot)
        if M.lane_of(slot, beacon) == "open":
            open_wins.add(w)
        else:
            bonded_wins[w] = bonded_wins.get(w, 0) + 1
    check("a staked identity still wins open slots (one device, one slot)", a in open_wins and c in open_wins, open_wins)
    check("bonded slots are drawn by plain stake: 50,000 NADO beats 50 NADO by ~1000:1, uncapped",
          bonded_wins.get(a, 0) > 50 * bonded_wins.get(b, 0), bonded_wins)

    # 3. pool / delegate / undelegate: refused, first, with the message the gen-25 branch raised at POOL_HEIGHT = 0
    kd = generate_keys()
    create_account(kd["address"], balance=1000 * N)
    kv_ops.account_set(kd["address"], "bonded", 100 * N)
    datas = {"pool": {"fee_bps": 1000, "open": 1, "min": P.B_MIN, "max": 1000 * N, "label": "x"},
             "delegate": {"to": a}, "undelegate": {}}
    for r, data in datas.items():
        tx = {"sender": kd["address"], "recipient": r, "amount": 0, "timestamp": get_timestamp_seconds(), "data": data,
              "nonce": create_nonce(), "public_key": kd["public_key"], "max_block": 5, "chain_id": P.CHAIN_ID, "fee": 0}
        tx["txid"] = create_txid(tx)
        tx["signature"] = sign(private_key=kd["private_key"], message=unhex(tx["txid"]))
        try:
            validate_transaction(tx, lg, 5)
            verdict = "accepted"
        except AssertionError as e:
            verdict = str(e)
        check(f"a signed `{r}` tx is refused: 'staking pools are not enabled yet'", verdict == "staking pools are not enabled yet", verdict)
        check(f"`{r}` stays reserved with its one-per-sender-per-block key",
              r in P.RESERVED_RECIPIENTS and reserved_uniqueness_key(tx) == (r, kd["address"]))

    # 4. the bonded registry entry shape and address set
    kv_ops.account_set(b, "bonded", P.B_MIN)
    kv_ops.account_set(c, "bonded", P.B_MIN - 1)
    reg = get_bonded_registry()
    check("bonded registry = every account with >= one share, entries {bonded, fidelity, bond_since}",
          set(reg) == {kd["address"], b} and all(set(e) == {"bonded", "fidelity", "bond_since"} for e in reg.values())
          and reg[b]["bonded"] == P.B_MIN, reg)

    # 5. the gradient: min(fidelity, 15) at every epoch (gen 25 gated it at DIVIDEND_WEIGHT_CAP_V2_EPOCH, 0 from gen 26 and
    #    deleted after the betanet-8 reroll)
    check("dividend_weight caps at 15 from epoch 0", all(P.dividend_weight(30, e) == 15 and P.dividend_weight(7, e) == 7
                                                       for e in (0, 1, 110, 10 ** 6)) and not hasattr(P, "DIVIDEND_WEIGHT_CAP_V2_EPOCH"))
    kv_ops.close_all()

    # 6. nothing deleted came back
    gone = ("BOND_DEVICE_CAP_HEIGHT", "BOND_WEIGHT_CURVE_HEIGHT", "POOL_HEIGHT", "OPEN_LANE_EXCLUDE_BONDED_HEIGHT",
            "OPEN_LANE_EXCLUDE_BONDED_EPOCH", "BOND_ATTEST_OPTIONAL_HEIGHT", "POOL_RETIRE_HEIGHT", "BOND_CURVE_RETIRE_HEIGHT",
            "OPEN_LANE_EXCLUDE_RETIRE_HEIGHT", "BOND_DEVICE_CAP", "BOND_KNEE_OTHERS_BPS", "BOND_TAIL_BPS")
    check("the deleted gates and constants are gone from protocol", not any(hasattr(P, g) for g in gone), [g for g in gone if hasattr(P, g)])
    check("the knee/cap helpers are gone", not hasattr(M, "bond_weight") and not hasattr(M, "bond_knee"))
    check("pool_revert is gone from every sub-DB list; the snapshot/root set is unchanged by it",
          "pool_revert" not in kv_ops._PLAIN_DBS and "pool_revert" not in kv_ops.SNAPSHOT_DBS)
    nado_src = open(os.path.join(ROOT, "nado.py")).read()
    check("/pools is gone", '"/pools"' not in nado_src)
    bo = open(os.path.join(ROOT, "ops", "block_ops.py")).read()
    check("mining_status still answers the fields wallets read, at their gen-27 values",
          '"bond_attest_required": False' in bo and '"bond_plain": True' in bo and '"open_excluded_bonded"' in bo
          and "bonded_producer_registry(get_bonded_registry(), open_reg, epoch * EPOCH_LENGTH)" in bo)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback; traceback.print_exc(); _fails.append("exception")
    print("ALL PASS" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    raise SystemExit(1 if _fails else 0)
