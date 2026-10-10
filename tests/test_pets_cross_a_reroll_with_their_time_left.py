"""Pets cross a reroll with their time left, and every pending roll resolves on the new chain (pets.carry_rebase).

Pets stores OLD-CHAIN HEIGHTS at rest — fed-until, exhausted-until, a building's since-block — and pins pending rolls to
old block hashes and beacons (hatch, training, building finds, item rerolls). Carried raw, a fed pet would live for
free until the new chain reached its old height (~150,000 blocks here) and an unhatched egg could not hatch for days.

Pins, on the REAL pets contract (throwaway HOME), old chain at height ~150,000 and a new chain starting at 0:
  1. a fed pet keeps exactly the life it had left (raw storage would hand it ~150,000 free blocks);
  2. an unhatched egg hatches on the new chain from new-chain block hashes (raw: it could not hatch for days);
  3. a pending training session resolves on the new chain;
  4. a building collects on the new chain and its pending find is pinned to a new-chain beacon epoch >= 2;
  5. hashed slots (a player's resource balance) are untouched, and the carry keeps the contract (policy "keep");
  6. an open battle keeps its reveal window, and both reveals and the duel complete on the new chain.

Run: python3 tests/test_pets_cross_a_reroll_with_their_time_left.py
"""
import os, sys, json, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-pets-carry-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
H = os.environ["HOME"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from execnode.state import ExecState
from execnode.games import pets as P
from execnode.runtimes import zkvm_addr_digest
from execnode.stark import alghash
import tools.alphanet6_carryforward as C

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


A = "ndoA" + "a" * 44
OLD_TIP0 = 150_000


def chain(st, salt, upto):
    st.block_hashes = {h: (h * 1_000_003 + salt) for h in range(0, upto)}
    st.beacons = {e: (e * 7_919_993 + salt) for e in range(0, upto // 60 + 10)}


_n = [0]


def call(st, cid, who, method, args, value=None):
    _n[0] += 1
    p = {"op": "call", "contract": cid, "method": method, "args": args}
    if value:
        p["value"] = value
    return st.apply_blob(p, who, f"{method}-{_n[0]}")


old = ExecState(os.path.join(H, "old.json"))
old.cursor, old.block_ts = OLD_TIP0, int(time.time())
chain(old, 7, OLD_TIP0 + 50_000)
code = P.build()
old.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": P.ABI, "nonce": "n"}, A, "d")
cid = old.contract_id(A, code, "n")
rd = lambda st, f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
old.credit_deposit(A, 3000 * P.MINT_FEE)

# a hatched pet of trade 0 (a farmer), so it can raise and work a farm
pid = 1000
while True:
    call(old, cid, A, "mint", [pid], P.MINT_FEE)
    old.cursor += 3
    call(old, cid, A, "hatch", [pid])
    if rd(old, P.SI, pid) % P.NJOBS == 0:
        break
    pid += 1
FARMER = pid
call(old, cid, A, "build", [1, 0, FARMER], P.BUILD_FEE)
old.cursor += 500
call(old, cid, A, "collect", [1])                                # pins the farm's next find (bdp)
call(old, cid, A, "train", [FARMER, 3], P.TRAIN_FEE)             # a pending training session (th)
EGG = 9000
call(old, cid, A, "mint", [EGG], P.MINT_FEE)                     # minted, not hatched (bh)
# an OPEN commit-reveal battle between A's farmer and B's pet: accepted, nobody revealed yet (wrd pending)
B = "ndoB" + "b" * 44
old.credit_deposit(B, 20 * P.MINT_FEE)
BPET = 7000
call(old, cid, B, "mint", [BPET], P.MINT_FEE)
old.cursor += 3
call(old, cid, B, "hatch", [BPET])
from execnode.stark import field as _F
S1, S2, STAKE = 123456789, 987654321, 10 ** 9
Hc = lambda x: alghash.hashn([x % _F.P])
old.cursor = max(old.cursor, rd(old, P.EX, FARMER), rd(old, P.EX, BPET)) + 1
r_ch = call(old, cid, A, "challenge", [70, FARMER, BPET, Hc(S1)], STAKE)
r_ac = call(old, cid, B, "accept", [70, Hc(S2)], STAKE)
res_slot = str(alghash.hashn([P.TG_RES, zkvm_addr_digest(A), 0]))
old.contracts[cid]["storage"]["slots"][res_slot] = "777"         # a hashed slot: a resource balance
TIP = old.cursor
wrd_left = rd(old, P.WRD, 70) - old.cursor
check("setup: an open battle, accepted, awaiting both reveals", "ok" in r_ch and "ok" in r_ac and wrd_left > 0, (r_ch, r_ac))
check("setup: a farmer, a farm with a pinned find, a training session and an egg exist",
      rd(old, P.BO, 1) and rd(old, P.BDP, 1) and rd(old, P.TH, FARMER) and rd(old, P.OW, EGG) and not rd(old, P.GN, EGG))
life_left = rd(old, P.FU, FARMER) - TIP

check("5. pets carries (a rebase, nothing blocks it)", C.carry_policy(cid, old.contracts[cid]) == "keep")
pot = int(old.bridge.get(cid, 0))
gen, kept = C.exec_genesis_doc({cid: old.contracts[cid]}, {cid: pot}, tip=TIP)
check("...its pot (burned fees, battle stakes) stays with it", kept == {cid: pot} and pot > 0, (kept, pot))
new = ExecState(os.path.join(H, "new.json"))
new.contracts[cid] = json.loads(json.dumps(gen[cid]))
new.bridge[cid] = kept[cid]
new.cursor, new.block_ts = 0, int(time.time())
chain(new, 99, 5000)                                             # the new chain's own hashes and beacons
raw = json.loads(json.dumps(old.contracts[cid]["storage"]))

check("1. a fed pet keeps exactly the life it had left", rd(new, P.FU, FARMER) - new.cursor == life_left,
      (rd(new, P.FU, FARMER), life_left))
check("...where raw storage would hand it the whole old height for free",
      int(raw["slots"][str((P.FU << 32) + FARMER)]) - new.cursor > life_left + 100_000)

new.cursor = P.CARRY_PIN_FLOOR + 2
new.credit_deposit(A, 10 * P.MINT_FEE)
call(new, cid, A, "hatch", [EGG])
want_gene = P.ref_gene(new.block_hashes[rd(new, P.BH, EGG)], new.block_hashes[rd(new, P.BH, EGG) + 1], EGG)
check("2. the egg hatches on the new chain, from the new chain's block hashes",
      rd(new, P.GN, EGG) == want_gene and rd(new, P.BH, EGG) >= P.CARRY_PIN_FLOOR, (rd(new, P.GN, EGG), want_gene))
check("...where raw storage would make it wait for an old-chain height",
      int(raw["slots"][str((P.BH << 32) + EGG)]) > 100_000)

tf0 = rd(new, P.TH, FARMER)
call(new, cid, A, "train_resolve", [FARMER])
check("3. the pending training session resolves on the new chain", tf0 >= P.CARRY_PIN_FLOOR and rd(new, P.TH, FARMER) == 0,
      (tf0, rd(new, P.TH, FARMER)))

check("4. the farm's pending find is pinned to a new-chain beacon epoch >= 2",
      rd(new, P.BDP, 1) >= P.CARRY_PIN_FLOOR and rd(new, P.BDP, 1) < 100, rd(new, P.BDP, 1))
new.cursor = 300
r = call(new, cid, A, "collect", [1])
check("...and the farm collects on the new chain", rd(new, P.BSI, 1) == 300, (r, rd(new, P.BSI, 1)))
check("5. a hashed slot (a resource balance) is untouched by the rebase",
      gen[cid]["storage"]["slots"].get(res_slot) == "777")

new.cursor = P.CARRY_PIN_FLOOR + 2
check("6. an open battle keeps the reveal window it had left (new block 0 stands where the old tip stood)",
      rd(new, P.WRD, 70) == wrd_left, (rd(new, P.WRD, 70), wrd_left))
ra, rb = call(new, cid, A, "reveal_battle", [70, S1]), call(new, cid, B, "reveal_battle", [70, S2])
rr = call(new, cid, A, "resolve_battle", [70])
check("...and both sides reveal and the duel resolves on the new chain, paying out both stakes",
      all("ok" in x for x in (ra, rb, rr)) and f"paid={2 * STAKE}" in rr, (ra, rb, rr))
print("ALL PASS — pets cross a reroll with their time left" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
