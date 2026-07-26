# _games_live_smoke.py — does every DEPLOYED game actually respond on the live chain?
#
# tests/test_games_e2e.py proves the contracts are CORRECT in-process. This proves the deployed ones are
# REACHABLE, through the same path the browser uses: sign a blob tx, submit it to L1, wait for the exec
# layer to apply it, and confirm the game's own state actually changed. That is the difference between "a
# contract exists at a cid" and "clicking the button does something" — after a reroll the contracts existed
# at addresses nobody was calling, and every game silently did nothing.
#
# Each game gets its cheapest state-creating call (open a table, mint a pet, begin a march). We do not play
# a game out; if `open` lands and the id appears in the contract's own view, then the contract is live, its
# ABI matches what the frontend ships, and the exec layer is applying its calls.
#
# TWO THINGS THAT MAKE A NAIVE VERSION LIE, both learned the hard way:
#
#   * CALL VALUE COMES FROM THE EXEC-LAYER BRIDGE, NOT YOUR L1 BALANCE. state.py escrows `value` out of
#     bridge[sender]; with no deposit it returns "skip: insufficient bridge balance" and the call is a
#     silent no-op. On a freshly rerolled chain NOBODY has bridged in, so every value-carrying game appears
#     broken while the zero-value ones (autogame, hamster) appear fine. That is a funding problem, not a
#     game problem — so this script checks the bridge first and refuses to report failures without it.
#   * The exec node's per-contract endpoint is slow and intermittently returns empty under load. A single
#     fetch treated as truth marks live games dead, so every read is retried before believing a negative.
#
# Calls are submitted ONE AT A TIME and waited on: the producer includes roughly one tx per block, so firing
# twenty at once just races them all against their own expiry.
#
# Run: HOME=/root python3 _games_live_smoke.py [game ...]
#      HOME=/root python3 _games_live_smoke.py --fund 5000000000   # bridge-deposit first, then test
import json, sys, time, urllib.request

sys.path.insert(0, "/srv/nado-home/nado")
from ops.key_ops import load_keys
from ops.address_ops import make_address
from ops.transaction_ops import construct_blob_tx, construct_bridge_deposit_tx
from protocol import MIN_TX_FEE, TX_INCLUSION_DELAY
from execnode.games.redeploy import target_cids

L1 = "http://127.0.0.1:9173"
EX = "http://127.0.0.1:9273"
S = 1_000_000                      # small but non-zero: several games reject a zero-value open

K = load_keys(); K["address"] = make_address(K["public_key"])

# game -> (method, args, value), from each contract's shipped ABI. A drift between this table and the
# deployed ABI is itself a finding: it means the frontend is calling something the contract does not have.
CALLS = {
    "coinflip":   lambda i: ("open", [i], S),
    "dice":       lambda i: ("open", [i], S * 20),
    "roulette":   lambda i: ("open", [i], S * 20),
    "mines":      lambda i: ("open", [i], S * 20),
    "slots":      lambda i: ("open", [i], S * 20),
    "blackjack":  lambda i: ("open", [i], S * 20),
    "reversi":    lambda i: ("open", [i], S),
    "connect4":   lambda i: ("open", [i], S),
    "tictactoe":  lambda i: ("open", [i], S),
    "chess":      lambda i: ("open", [i], S),
    "scrapline":  lambda i: ("open", [i], S),
    "farkle":     lambda i: ("open", [i, i + 1], S),
    "battleship": lambda i: ("open", [i, 12345678], S),
    "holdem":     lambda i: ("open", [i, i + 1, 12345678, S], S),
    "stormhold":  lambda i: ("open", [i, 0, 12345678], S),
    "hexholm":    lambda i: ("open", [i, 4, 12345678], S),
    "hamster":    lambda i: ("open", [i], 0),        # opening a race is free; the value rides on the bets
    "pets":       lambda i: ("mint", [i], S),
    "autogame":   lambda i: ("begin", [i], 0),
    # bet needs a resolver panel + deadlines, reserve an asset/notice schedule, sovereign an encoded action:
    # multi-arg policy calls rather than a one-line open. Reported as SKIP rather than faked.
}
SKIP = ("bet", "reserve", "sovereign", "faucet")


def j(u, t=45):
    try:
        return json.load(urllib.request.urlopen(u, timeout=t))
    except Exception:
        return None


def tip():
    d = j(L1 + "/get_latest_block", 15)
    return d["block_number"] if d else None


def bridge_balance():
    d = j(f"{EX}/exec/bridge?address={K['address']}", 30)
    return None if d is None else int((d.get("balances") or {}).get(K["address"], 0))


def send(tx):
    req = urllib.request.Request(L1 + "/submit_transaction", data=json.dumps(tx).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        return bool(json.load(urllib.request.urlopen(req, timeout=25)).get("result"))
    except Exception:
        return False


def fund(amount):
    """Bridge NADO from L1 into the exec layer — the ledger contract call value is escrowed from."""
    t = tip()
    if t is None:
        sys.exit("L1 unreachable")
    print(f"bridging {amount} into the exec layer…", flush=True)
    send(construct_bridge_deposit_tx(K, int(amount), t + 40, MIN_TX_FEE))
    for _ in range(45):
        time.sleep(10)
        b = bridge_balance()
        if b:
            print(f"  bridge credited: {b}", flush=True)
            return True
    print("  NOT credited within the timeout")
    return False


def has_id(cid, gid):
    """Did the call take? True once our id is a key in ANY of the contract's view maps — exactly what the
    frontend reads to decide the table exists. Retried, because a single empty read is not a negative."""
    for _ in range(3):
        d = j(f"{EX}/exec/contract?ns=default&cid={cid}&provisional=1")
        if d is None:
            time.sleep(3); continue
        for m in (d.get("storage") or {}).values():
            if isinstance(m, dict) and str(gid) in m:
                return True
        return False
    return False


def play(game, cid, gid):
    meth, args, val = CALLS[game](gid)
    for attempt in range(3):
        t = tip()
        if t is None:
            time.sleep(10); continue
        p = {"op": "call", "contract": cid, "method": meth, "args": args}
        if val:
            p["value"] = int(val)
        send(construct_blob_tx(K, p, max_block=t + 40, fee=MIN_TX_FEE, min_block=t + TX_INCLUSION_DELAY))
        for _ in range(14):
            time.sleep(9)
            if has_id(cid, gid):
                return True, f"{meth}({', '.join(map(str, args))})"
        print(f"    {game}: attempt {attempt + 1} did not land, retrying", flush=True)
    return False, f"{meth}({', '.join(map(str, args))})"


def main():
    argv = sys.argv[1:]
    if "--fund" in argv:
        i = argv.index("--fund")
        fund(int(argv[i + 1])); argv = argv[:i] + argv[i + 2:]
    want = [a for a in argv if not a.startswith("-")]

    bal = bridge_balance()
    if bal is None:
        sys.exit("exec node unreachable — cannot tell working games from unreachable ones")
    print(f"exec bridge balance: {bal}")
    if bal < S * 25:
        print("\n  bridge balance is too low to open the banked tables. Contract call value is escrowed\n"
              "  from the EXEC BRIDGE, not your L1 account, so value-carrying games would report false\n"
              "  failures. Re-run with:  --fund 5000000000\n")
        if bal == 0:
            return 2

    targets = target_cids()
    games = [g for g in CALLS if not want or g in want]
    base = int(time.time()) % 900000 * 10 + 3
    res = {}
    print(f"\nexercising {len(games)} games, one call at a time\n", flush=True)
    for n, g in enumerate(games):
        ok, call = play(g, targets[g], base + n * 13)
        res[g] = ok
        print(f"  {'PASS' if ok else 'FAIL'}  {g:11s} {call}", flush=True)

    for g in SKIP:
        if not want:
            print(f"  SKIP  {g:11s} multi-arg policy call — not a one-line open")
    good = [g for g, v in res.items() if v]
    bad = [g for g, v in res.items() if not v]
    print("\n" + "=" * 58)
    print(f"{len(good)}/{len(res)} games responded on the live chain"
          + (f"\nFAILING: {', '.join(bad)}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
