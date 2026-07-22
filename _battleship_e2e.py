# _battleship_e2e.py — LIVE end-to-end of the deployed Battleship contract's free daily board: anchor the day
# (two-phase), compute a VALID score with the real JS engine, post it, and confirm the faucet replay-oracle
# ranks it. Run: HOME=/root python _battleship_e2e.py
import json, urllib.request, time, sys, subprocess
sys.path.insert(0, "/root/nado")
from ops.key_ops import load_keys
from ops.address_ops import make_address
from ops.transaction_ops import construct_blob_tx
from protocol import MIN_TX_FEE, TX_INCLUSION_DELAY

L1 = "http://127.0.0.1:9173"; EX = "http://127.0.0.1:9273"
CID = "a6c3c02696e9cce9a380ceaa86d0127b"
def j(u): return json.load(urllib.request.urlopen(u, timeout=10))
def post(tx):
    r = urllib.request.Request(L1 + "/submit_transaction", data=json.dumps(tx).encode(), headers={"Content-Type": "application/json"})
    try: return json.load(urllib.request.urlopen(r, timeout=15))
    except urllib.error.HTTPError as e: return {"result": False, "message": e.read().decode()[:200]}
def tip(): return j(L1 + "/get_latest_block")["block_number"]
def sto(): return j(EX + f"/exec/contract?ns=default&cid=a6c3c02696e9cce9a380ceaa86d0127b&provisional=1").get("storage", {})
def cursor(): return int(j(EX + "/exec/root?ns=default&provisional=1").get("cursor", 0))
K = load_keys(); K["address"] = make_address(K["public_key"]); ME = K["address"]
def call(method, args, value=0):
    p = {"op": "call", "contract": CID, "method": method, "args": args}
    if value: p["value"] = int(value)
    for _ in range(8):
        r = post(construct_blob_tx(K, p, tip() + 12, MIN_TX_FEE, min_block=tip() + TX_INCLUSION_DELAY))
        if r.get("result"): return r
        print("  retry call", method, r.get("message"), flush=True); time.sleep(12)
    print("  [GIVEUP]", method, flush=True); sys.exit(1)
def wait(cond, label, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if cond(): print("  [ok]", label, flush=True); return True
        except Exception as e: pass
        time.sleep(10)
    print("  [TIMEOUT]", label, flush=True); sys.exit(1)
FAILS = []
def ck(n, c): print(("  PASS " if c else "  FAIL ") + n, flush=True); (None if c else FAILS.append(n))

print("battleship e2e as", ME, flush=True)
wait(lambda: j(EX + f"/exec/contract?ns=default&cid={CID}").get("cid") == CID, "contract live", 120)

# --- Daily Derby: anchor the day (two-phase), post a valid score, confirm the oracle ranks it ---
day = int(time.time()) // 86400
call("anchor", [day])                                            # phase 1: pin a future height
wait(lambda: int(sto().get("ah", {}).get(str(day), 0)) > 0, "anchor pinned")
call("anchor", [day])                                            # phase 2 (retried until the pin resolves)
wait(lambda: sto().get("av", {}).get(str(day)), "anchor resolved (av[day] set)", 400)
anchor = str(sto()["av"][str(day)])
ck("anchor value present", bool(anchor) and anchor != "0")

# compute a valid (word, score) with the SAME engine the client + faucet use
node = subprocess.run(["node", "--input-type=module", "-e", f'''
import {{ dailyFleet, scoreShots, SHOT_BITS, WORDS }} from "./static/battleship-daily.js";
import {{ provableSeed, packMoves, anchorOf }} from "./static/provable.js";
const sto = (await (await fetch("http://127.0.0.1:9273/exec/contract?ns=default&cid=a6c3c02696e9cce9a380ceaa86d0127b&provisional=1")).json()).storage || {{}};
const anchor = anchorOf(sto, (s,n)=>s[n]||{{}}, {day});   // read av[day] exactly as the client/verifier do (JS)
const seed = provableSeed("battleship", {day}, anchor, "{ME}");
const fleet = dailyFleet(seed);
const shots = [...fleet.occ];                                    // a perfect salvo: fire every ship cell
const words = packMoves(shots, SHOT_BITS); while (words.length < WORDS) words.push(0);
console.log(JSON.stringify({{ words, n: shots.length, score: scoreShots(fleet, shots) }}));
'''], capture_output=True, text=True, cwd="/root/nado", timeout=60)
res = json.loads(node.stdout.strip().splitlines()[-1]); WORDS_, NSHOTS, SCORE = res["words"], int(res["n"]), int(res["score"])
print(f"  engine: perfect salvo n={NSHOTS} score={SCORE}", flush=True)
call("post", [day, SCORE, NSHOTS] + [int(w) for w in WORDS_])
wait(lambda: any(sto().get("eaddr", {}).get(e) == ME and int(sto().get("escore", {}).get(e, 0)) == SCORE
                 for e in sto().get("eday", {}) if int(sto().get("eday", {}).get(e, -1)) == day), "score posted on-chain")

# the faucet oracle: replay-verify TODAY's board — my score must rank
vr = subprocess.run(["node", "tests/battleship_daily_verify.mjs", CID, str(day)], capture_output=True, text=True, cwd="/root/nado", timeout=120)
rows = json.loads(vr.stdout.strip().splitlines()[-1]) if vr.returncode == 0 else []
print("  verifier rows:", rows, flush=True)
ck("my verified score on the board", any(a == ME and s == SCORE for a, s in rows))

print(("\nALL PASS" if not FAILS else "\nFAILURES: " + ", ".join(FAILS)), flush=True)
sys.exit(1 if FAILS else 0)
