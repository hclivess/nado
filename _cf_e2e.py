#!/usr/bin/env python3
# _cf_e2e.py — LIVE end-to-end of the deployed Coin Flip contract. Two real keys stake real (tiny) NADO,
# the flip settles out of two L1 block hashes, and the winner is recomputed HERE from those hashes rather
# than read back off the chain. Also covers cancel (an unjoined game refunds its opener) and finality
# (a settled game cannot be re-settled).
#
# Run: HOME=/root python3 _cf_e2e.py
#
# This is a rewrite. The previous version had been dead since two separate migrations — it imported
# `Curve25519` (gone when signing went post-quantum) and `execnode.contract_lib.COIN_FLIP` (gone when the
# zkVM became the only runtime), and it played a commit/reveal protocol the contract no longer has. It
# failed in ONE SECOND and had done for months, so coinflip looked covered while having no live coverage at
# all. tests/test_e2e_scripts.py now catches that class of rot; this file is the repair.
import json
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/root/nado")
from config import get_timestamp_seconds
from ops.key_ops import load_keys
from ops.transaction_ops import (construct_blob_tx, construct_bridge_deposit_tx, create_transaction,
                                 draft_transaction)
from protocol import MIN_TX_FEE
from signatures import generate_keydict
from execnode.stark import alghash, field as F

L1 = "http://127.0.0.1:9173"
EX = "http://127.0.0.1:9273"
CID = "7dd1e147f769ced73123a1aefd5aac8c"       # execnode/games/coinflip.py — same cid static/coinflip.js uses
NADO = 10 ** 10
STAKE = NADO // 100                            # 0.01 NADO a side; this is a smoke test, not a wager

FAILS = []


def ck(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  [{extra}]" if extra else ""), flush=True)
    if not cond:
        FAILS.append(name)


def j(u):
    return json.load(urllib.request.urlopen(u, timeout=15))


def post(tx):
    r = urllib.request.Request(L1 + "/submit_transaction", data=json.dumps(tx).encode(),
                               headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(r, timeout=20))
    except urllib.error.HTTPError as e:
        return {"result": False, "message": e.read().decode()[:200]}


def tip():
    return j(L1 + "/get_latest_block")["block_number"]


def cursor():
    return int(j(EX + "/exec/root?ns=default&provisional=1").get("cursor", 0))


def sto():
    return j(EX + f"/exec/contract?ns=default&cid={CID}&provisional=1").get("storage", {})


def fld(name, g, default=0):
    """One decoded map cell, RAW. p1/p2 are address STRINGS (the ABI lists them under `addr`), so this must
    not int() — int()ing an address inside a wait() predicate raises, the retry loop swallows it, and the
    test then burns its whole timeout on a condition that was already true."""
    return (sto().get(name) or {}).get(str(g), default)


def num(name, g, default=0):
    try:
        return int(fld(name, g, default) or default)
    except (TypeError, ValueError):
        return default


def l1bal(a):
    try:
        return int(j(L1 + f"/get_account?address={a}").get("balance", 0))
    except Exception:
        return 0


def exbal(a):
    try:
        return int(j(EX + "/exec/bridge?ns=default&provisional=1").get("balances", {}).get(a, 0))
    except Exception:
        return 0


def wait(cond, what, timeout=900):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if cond():
                print("  [ok] " + what, flush=True)
                return
        except Exception:
            pass
        time.sleep(8)
    print("  [TIMEOUT] " + what, flush=True)
    sys.exit(1)


def call(kd, method, args, value=0, applied=None, tries=5):
    """Submit a contract call and — when given an `applied` predicate — keep submitting until the chain
    actually shows the effect.

    A successful /submit_transaction is NOT delivery. This run had one blob tx accepted into the pool and
    then simply never appear in a block; the script sat in the next wait() for twenty minutes looking like
    a broken contract. Resubmitting on a state predicate turns a lost tx into a five-second retry, and it
    is safe here because every method this test calls is idempotent-by-guard (a second open/join/settle/
    cancel of the same game reverts rather than double-acting)."""
    blob = {"op": "call", "contract": CID, "method": method, "args": args}
    if value:
        blob["value"] = int(value)
    for attempt in range(tries):
        for _ in range(8):
            r = post(construct_blob_tx(kd, blob, tip() + 25, MIN_TX_FEE))
            if r.get("result"):
                break
            print("   resubmit " + method + ": " + str(r.get("message"))[:90], flush=True)
            time.sleep(10)
        else:
            sys.exit("call gave up (never accepted): " + method)
        if applied is None:
            return
        for _ in range(14):                      # ~2 min: comfortably longer than inclusion + exec lag
            time.sleep(8)
            try:
                if applied():
                    return
            except Exception:
                pass
        print(f"   {method} was accepted but never landed (attempt {attempt + 1}) — resubmitting", flush=True)
    sys.exit("call gave up (never landed): " + method)


def transfer(kd, to, amount):
    draft = draft_transaction(kd["address"], to, int(amount), kd["public_key"],
                              get_timestamp_seconds(), "", tip() + 25)
    return post(create_transaction(draft, kd["private_key"], MIN_TX_FEE))


def blockhash(h):
    """The value BHASH(h) hands the VM: the L1 block hash as an integer, reduced into the field."""
    return int(j(L1 + f"/get_block_number?number={h}")["block_hash"], 16) % F.P


def expected_winner(g, sh):
    """The winner, derived here exactly as the SETTLE assembly derives it:

        w = 1 + lo32(alghash.hashn([ BHASH(sh) + BHASH(sh+1) + gameId ])) % 2

    Computing it independently is the entire point of this test. Asserting that `ws` is 1 or 2 would pass a
    contract that flipped a constant coin, and asserting that it equals whatever the chain stored would pass
    a contract that flipped nothing at all.
    """
    x = F.add(F.add(blockhash(sh), blockhash(sh + 1)), g % F.P)
    return 1 + ((alghash.hashn([x]) & 0xFFFFFFFF) % 2)


print("coinflip e2e on " + CID, flush=True)
wait(lambda: "settle" in (j(EX + f"/exec/contract?ns=default&cid={CID}").get("methods") or []),
     "contract live on the exec node", 300)

P1 = load_keys()
A1 = P1["address"]
print("  p1 (node key):  " + A1[:20] + "…", flush=True)
if exbal(A1) < 6 * STAKE:
    post(construct_bridge_deposit_tx(P1, 20 * STAKE, tip() + 25, MIN_TX_FEE))
    wait(lambda: exbal(A1) >= 6 * STAKE, "p1 bridged tokens into the exec layer")

P2 = generate_keydict()
A2 = P2["address"]
print("  p2 (fresh key): " + A2[:20] + "…", flush=True)
transfer(P1, A2, 40 * STAKE + 10 * MIN_TX_FEE)
wait(lambda: l1bal(A2) >= 20 * STAKE, "p2 funded on L1")
post(construct_bridge_deposit_tx(P2, 20 * STAKE, tip() + 25, MIN_TX_FEE))
wait(lambda: exbal(A2) >= 2 * STAKE, "p2 bridged tokens into the exec layer")

# ── 1. open ─────────────────────────────────────────────────────────────────────────────────────────
G = int(time.time()) % 900000000 + 1000                      # a gameId nobody else is using, < 2^32
print(f"\n1. p1 opens game {G} for {STAKE} raw", flush=True)
call(P1, "open", [G], STAKE, applied=lambda: num("nn", G) == 1)
wait(lambda: num("nn", G) == 1, "game is open and waiting")
ck("the stake is recorded", num("st", G) == STAKE, f"st={num('st', G)}")
ck("the pot holds exactly one stake", num("pt", G) == STAKE, f"pt={num('pt', G)}")
ck("p1 is the opener", str(fld("p1", G)) == A1, str(fld("p1", G))[:20])
ck("no settle height is armed yet", num("sh", G) == 0, f"sh={num('sh', G)}")

# ── 2. join ─────────────────────────────────────────────────────────────────────────────────────────
print("\n2. p2 joins", flush=True)
bal1, bal2 = exbal(A1), exbal(A2)
cur_at_join = cursor()
call(P2, "join", [G], STAKE, applied=lambda: num("nn", G) == 2)
wait(lambda: num("nn", G) == 2, "game is joined")
sh = num("sh", G)
ck("the pot holds both stakes", num("pt", G) == 2 * STAKE, f"pt={num('pt', G)}")
ck("p2 is the joiner", str(fld("p2", G)) == A2, str(fld("p2", G))[:20])
# the settle height must be UNMINED at join time, or the joiner could have picked a side knowing the answer
ck("the settle height was still in the future when the stakes went in", sh > cur_at_join,
   f"sh={sh} cursor@join={cur_at_join}")

# ── 3. settle — and check the flip against an independent derivation ────────────────────────────────
print(f"\n3. wait for heights {sh} and {sh + 1}, then settle", flush=True)
wait(lambda: cursor() >= sh + 1, f"the exec cursor reached {sh + 1}", 900)
want = expected_winner(G, sh)
call(P1, "settle", [G], applied=lambda: num("sd", G) == 1)
wait(lambda: num("sd", G) == 1, "settled")
got = num("ws", G)
ck("a winner was chosen", got in (1, 2), f"ws={got}")
ck("the winner matches an INDEPENDENT derivation from the two block hashes", got == want,
   f"chain={got} derived={want}")

winner, loser = (A1, A2) if got == 1 else (A2, A1)
wbal, lbal = (bal1, bal2) if got == 1 else (bal2, bal1)
print(f"   winner: p{got}  {winner[:20]}…", flush=True)
wait(lambda: exbal(winner) >= wbal + STAKE, "the pot reached the winner")
ck("the winner is up a full stake", exbal(winner) >= wbal + STAKE, f"{exbal(winner)} was {wbal}")
ck("the loser is down a full stake", exbal(loser) <= lbal - STAKE, f"{exbal(loser)} was {lbal}")
ck("nothing was minted — the pot is emptied", num("pt", G) == 0, f"pt={num('pt', G)}")

# ── 4. cancel refunds an unjoined game ──────────────────────────────────────────────────────────────
G2 = G + 1
print(f"\n4. p1 opens game {G2} and cancels it", flush=True)
before = exbal(A1)
call(P1, "open", [G2], STAKE, applied=lambda: num("nn", G2) == 1)
wait(lambda: num("nn", G2) == 1, "second game is open")
ck("opening escrowed the stake", exbal(A1) <= before - STAKE, f"{exbal(A1)} was {before}")
call(P1, "cancel", [G2], applied=lambda: num("sd", G2) == 1)
wait(lambda: num("sd", G2) == 1, "cancelled")
ck("cancel refunded the opener in full", exbal(A1) >= before, f"{exbal(A1)} was {before}")
ck("the cancelled pot is emptied", num("pt", G2) == 0, f"pt={num('pt', G2)}")

# ── 5. a settled game is final ──────────────────────────────────────────────────────────────────────
print("\n5. re-settling a settled game must be rejected", flush=True)
ws_before, w_before = num("ws", G), exbal(winner)
post(construct_blob_tx(P1, {"op": "call", "contract": CID, "method": "settle", "args": [G]},
                       tip() + 25, MIN_TX_FEE))
time.sleep(40)
ck("the winner did not change", num("ws", G) == ws_before, f"{num('ws', G)} vs {ws_before}")
ck("no second payout was made", exbal(winner) <= w_before, f"{exbal(winner)} vs {w_before}")

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: " + ", ".join(FAILS)), flush=True)
sys.exit(1 if FAILS else 0)
