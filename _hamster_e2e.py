# _hamster_e2e.py — LIVE end-to-end of the deployed Hamster contract: opens a race (so the game has content),
# then exercises the free Daily Derby plumbing on-chain: anchor the day (two-phase), compute a VALID score with
# the real JS engine, post it, and confirm the faucet replay-oracle ranks it. Run: HOME=/root python _hamster_e2e.py
import json, urllib.request, time, sys, subprocess
sys.path.insert(0, "/root/nado")
from ops.key_ops import load_keys
from ops.address_ops import make_address
from ops.transaction_ops import construct_blob_tx
from protocol import MIN_TX_FEE, TX_INCLUSION_DELAY

L1 = "http://127.0.0.1:9173"; EX = "http://127.0.0.1:9273"
CID = "1e40bed8f325ecd3e6d8a59db0406b19"
def j(u): return json.load(urllib.request.urlopen(u, timeout=10))
def post(tx):
    r = urllib.request.Request(L1 + "/submit_transaction", data=json.dumps(tx).encode(), headers={"Content-Type": "application/json"})
    try: return json.load(urllib.request.urlopen(r, timeout=15))
    except urllib.error.HTTPError as e: return {"result": False, "message": e.read().decode()[:200]}
def tip(): return j(L1 + "/get_latest_block")["block_number"]
def sto(): return j(EX + f"/exec/contract?ns=default&cid={CID}&provisional=1").get("storage", {})
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

print("hamster e2e as", ME, flush=True)
wait(lambda: j(EX + f"/exec/contract?ns=default&cid={CID}").get("cid") == CID, "contract live", 120)

# --- open a race (permissionless, value-free) so the live game shows content ---
R = int(time.time()) % 900000000 + 1
call("open", [R])
wait(lambda: sto().get("ra", {}).get(str(R)) == 1, f"race {R} opened")
gh = int(sto()["gh"][str(R)]); lk = int(sto()["lk"][str(R)]); fh = int(sto()["fh"][str(R)])
ck("open pins gh<lk<fh", gh < lk < fh)

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
import {{ dailyRaces, scorePicks, RACES, PICK_BITS }} from "./static/hamster-daily.js";
import {{ provableSeed, packMoves }} from "./static/provable.js";
const seed = provableSeed("hamster", {day}, "{anchor}", "{ME}");
const races = dailyRaces(seed);
const picks = races.map(r => r.winner);                          // a perfect day
console.log(JSON.stringify({{ word: packMoves(picks, PICK_BITS)[0], score: scorePicks(races, picks) }}));
'''], capture_output=True, text=True, cwd="/root/nado", timeout=60)
res = json.loads(node.stdout.strip().splitlines()[-1]); WORD, SCORE = int(res["word"]), int(res["score"])
print(f"  engine: perfect-day word={WORD} score={SCORE}", flush=True)
call("post", [day, SCORE, 8, WORD])
wait(lambda: any(sto().get("eaddr", {}).get(e) == ME and int(sto().get("escore", {}).get(e, 0)) == SCORE
                 for e in sto().get("eday", {}) if int(sto().get("eday", {}).get(e, -1)) == day), "score posted on-chain")

# the faucet oracle: replay-verify TODAY's board — my score must rank
vr = subprocess.run(["node", "tests/hamster_daily_verify.mjs", CID, str(day)], capture_output=True, text=True, cwd="/root/nado", timeout=120)
rows = json.loads(vr.stdout.strip().splitlines()[-1]) if vr.returncode == 0 else []
print("  verifier rows:", rows, flush=True)
ck("my verified score on the board", any(a == ME and s == SCORE for a, s in rows))

print(("\nALL PASS" if not FAILS else "\nFAILURES: " + ", ".join(FAILS)), flush=True)
sys.exit(1 if FAILS else 0)
