#!/usr/bin/env python3
# _sovereign_e2e.py — LIVE: found two nations on-chain, run economy actions, confirm the global log + the
# JS engine replay agree. Uses the node key (A) + a fresh key (B).
import sys, json, time, urllib.request, subprocess
sys.path.insert(0, "/root/nado")
from ops.key_ops import load_keys
from signatures import generate_keydict
from ops.transaction_ops import construct_blob_tx, draft_transaction, create_transaction
from config import get_timestamp_seconds
from protocol import MIN_TX_FEE
L1 = "http://127.0.0.1:9173"; EX = "http://127.0.0.1:9273"; CID = "sovereign"
ok_all = True
def ck(n, c):
    global ok_all
    print(("  PASS " if c else "  FAIL ") + n, flush=True); ok_all = ok_all and c
def j(u): return json.load(urllib.request.urlopen(u, timeout=10))
def post(tx):
    r = urllib.request.Request(L1 + "/submit_transaction", data=json.dumps(tx).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=15))
def tip(): return j(L1 + "/get_latest_block")["block_number"]
def view(): return j(EX + f"/exec/contract?ns=default&cid={CID}&provisional=1").get("storage", {})
def mc():
    la = view().get("la", {}); return (max(map(int, la)) + 1) if la else 0
def wait(cond, what, tries=40):
    for _ in range(tries):
        try:
            if cond(): print("  [ok] " + what, flush=True); return True
        except Exception: pass
        time.sleep(5)
    print("  [TIMEOUT] " + what, flush=True); return False
def act(kd, enc, target, ply):
    return post(construct_blob_tx(kd, {"op": "call", "contract": CID, "method": "act", "args": [enc, target, ply]}, tip() + 25, MIN_TX_FEE))

# encAction helper (mirror the engine): op + 16*(a + 4096*(b + 4096*c))
def enc(op, a=0, b=0, c=0): return op + 16 * (a + 4096 * (b + 4096 * c))
OP = {"found":0,"build":1,"colonize":6}
BUILDABLE = ["village","city","market","farm","lab","factory","barracks","plant","arena","base","builder"]

A = load_keys()
B = generate_keydict()
print("sovereign E2E — A", A["address"][:14], "B", B["address"][:14], flush=True)
# fund B a little L1 dust for fees
draft = draft_transaction(A["address"], B["address"], 50 * MIN_TX_FEE, A["public_key"], get_timestamp_seconds(), "", tip() + 25)
post(create_transaction(draft, A["private_key"], MIN_TX_FEE))
wait(lambda: int(j(L1 + f"/get_account?address={B['address']}").get("balance", 0)) > 0, "B funded for fees")

m0 = mc()
ck("A found accepted", bool(act(A, enc(OP["found"]), 0, m0).get("result")))
wait(lambda: mc() >= m0 + 1, "A found landed")
m1 = mc()
ck("B found accepted", bool(act(B, enc(OP["found"]), 0, m1).get("result")))
wait(lambda: mc() >= m1 + 1, "B found landed")
m2 = mc()
# A builds 12 villages
ck("A build accepted", bool(act(A, enc(OP["build"], BUILDABLE.index("village"), 12), 0, m2).get("result")))
wait(lambda: mc() >= m2 + 1, "A build landed")
# stale ply is rejected AT EXEC (the mempool accepts the tx; the VM reverts it — so the log must NOT grow)
before = mc()
act(A, enc(OP["colonize"]), 0, 0)   # ply 0 is stale (log is far past 0)
time.sleep(20)
ck("stale-ply action reverted on-chain (log unchanged)", mc() == before)

# now replay the on-chain log through the JS engine and check A has villages + both nations exist
node = subprocess.run(["node", "--input-type=module", "-e", f"""
import {{ loadCrypto }} from './static/nadotx.js'; await loadCrypto('.');
const E = await import('./static/sovereign-engine.js');
const r = await (await fetch('{EX}/exec/contract?ns=default&cid={CID}&provisional=1')).json();
const sto = r.storage||{{}}; const la=sto.la||{{}},lc=sto.lc||{{}},le=sto.le||{{}},lt=sto.lt||{{}};
const mc = Object.keys(la).length? Math.max(...Object.keys(la).map(Number))+1:0;
const log=[]; for(let i=0;i<mc;i++){{ const rh=lc[String(i)]||0; log.push({{actor:la[String(i)],cursor:rh-2,rh,enc:le[String(i)]||0,target:lt[String(i)]||0}}); }}
const w = E.replayWorld(log, {tip()}, ()=>1n).world;
const A='{A["address"]}', B='{B["address"]}';
console.log(JSON.stringify({{nations:Object.keys(w).length, Avillages: w[A]?w[A].bld.village:-1, Aland: w[A]?w[A].land:-1, Bexists: !!w[B]}}));
"""], capture_output=True, text=True, cwd="/root/nado", timeout=60)
out = node.stdout.strip().splitlines()[-1] if node.stdout.strip() else node.stderr[-300:]
print("  replay:", out, flush=True)
try:
    d = json.loads(out)
    ck("engine replay sees both nations", d["nations"] >= 2 and d["Bexists"])
    ck("A's on-chain villages replay", d["Avillages"] == 12)
except Exception as e:
    ck("engine replay parses", False); print("   ", e, node.stderr[-200:])

print("\nSOVEREIGN E2E " + ("ALL PASS" if ok_all else "FAILED"), flush=True)
sys.exit(0 if ok_all else 1)
