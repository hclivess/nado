#!/usr/bin/env python3
# _faucet_e2e.py — LIVE faucet flow: a fresh (broke) key grinds the claim PoW, claims dice free play
# from the faucet contract, and the grant lands as spendable exec balance. (The donation + enrollment
# already happened; this is the player half of doc/faucet.md.)
import sys, json, time, urllib.request
sys.path.insert(0, "/root/nado")
from ops.key_ops import load_keys
from signatures import generate_keydict
from ops.transaction_ops import construct_blob_tx, draft_transaction, create_transaction
from config import get_timestamp_seconds
from protocol import MIN_TX_FEE
from execnode.stark import alghash
from execnode import runtimes

L1 = "http://127.0.0.1:9173"; EX = "http://127.0.0.1:9273"
ok_all = True
def ck(n, c):
    global ok_all
    print(("  PASS " if c else "  FAIL ") + n, flush=True)
    if not c: ok_all = False
def j(u): return json.load(urllib.request.urlopen(u, timeout=10))
def post(tx):
    r = urllib.request.Request(L1 + "/submit_transaction", data=json.dumps(tx).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=15))
def tip(): return j(L1 + "/get_latest_block")["block_number"]
def exbal(a): return int(j(EX + "/exec/bridge?ns=default&provisional=1").get("balances", {}).get(a, 0))
def wait(cond, what, tries=40):
    for _ in range(tries):
        try:
            if cond(): print("  [ok] " + what, flush=True); return True
        except Exception: pass
        time.sleep(5)
    print("  [TIMEOUT] " + what, flush=True); return False

OP = load_keys()
P2 = generate_keydict(); A2 = P2["address"]
print("faucet E2E — fresh player:", A2[:16] + "…", flush=True)
# fee dust so the newcomer can sign the claim tx (players get this from a mining lease normally)
draft = draft_transaction(OP["address"], A2, 50 * MIN_TX_FEE, OP["public_key"], get_timestamp_seconds(), "", tip() + 25)
post(create_transaction(draft, OP["private_key"], MIN_TX_FEE))
wait(lambda: int(j(L1 + f"/get_account?address={A2}").get("balance", 0)) > 0, "fee dust arrived")

sto = j(EX + "/exec/contract?ns=default&cid=faucet&provisional=1").get("storage", {})
IDX = 0                                    # dice
grant = int((sto.get("ggrant") or {}).get(str(IDX), 0))
powt = int((sto.get("gpow") or {}).get(str(IDX), 0))
ck("dice enrolled with a grant", grant > 0 and powt > 0)
d = runtimes.zkvm_addr_digest(A2)
nonce, t0 = 0, time.time()
while alghash.hashn([d, IDX, nonce]) >= powt: nonce += 1
print(f"  ground nonce {nonce} in {time.time()-t0:.1f}s", flush=True)
b0, f0 = exbal(A2), exbal("faucet")
r = post(construct_blob_tx(P2, {"op": "call", "contract": "faucet", "method": "claim", "args": [IDX, nonce]}, tip() + 25, MIN_TX_FEE))
ck("claim accepted by the mempool", bool(r.get("result")))
ok = wait(lambda: exbal(A2) == b0 + grant, "grant landed as exec balance")
ck("player credited exactly the grant", ok)
ck("faucet debited exactly the grant", exbal("faucet") == f0 - grant)
# the money is REAL play money: stake it — deposit path not needed (it's already exec-side); prove
# usability by a value call: open a tiny scrapline duel with it (same escrow machinery as dice bets)
r = post(construct_blob_tx(P2, {"op": "call", "contract": "72a195822ef32caa9680eee51eb95dc9", "method": "open",
                                "args": [990000001], "value": grant // 2}, tip() + 25, MIN_TX_FEE))
ck("stake tx accepted", bool(r.get("result")))
ok = wait(lambda: exbal(A2) == b0 + grant - grant // 2, "granted funds staked in a game")
ck("free play propagated into a game", ok)
print("\nFAUCET E2E " + ("ALL PASS" if ok_all else "FAILED"), flush=True)
sys.exit(0 if ok_all else 1)
