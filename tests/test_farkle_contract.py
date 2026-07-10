# tests/test_farkle_contract.py — OPEN MULTI-SEAT FARKLE (stackvm), fast + objective, winner-takes-pot.
#
# Players ante equal stakes into a pot and each pick a greed THRESHOLD (their push-your-luck strategy: how many
# points to chase before banking). At the table's settle block, each seat's turn is AUTO-PLAYED on-chain from a
# FINALIZED L1 block hash by the verified score_ops engine (see tests/farkle_onchain.py — 20000/20000
# differential-verified): seed_g = HASH(BLOCKHASH(sh)+BLOCKHASH(sh+1)+seatId); banked = farkle(seed_g, threshold).
# Nobody can predict the seed while betting is open, so every turn is objective + unriggable. Highest banked
# score wins the whole pot (strict >, first to reach it keeps ties); if every player farkles (0), the host
# reclaims. ONE beacon draw resolves a whole turn — no per-roll waits.
import sys, os, json, tempfile, hashlib, random
sys.path.insert(0, "/root/nado"); sys.path.insert(0, "/root/nado/tests")
from execnode.state import ExecState
from farkle_onchain import (score_ops, farkle_ref, vm_hash, P, A, LD, STm, LDR, STR,
                            ADD, SUB, MUL, MOD, EQ, LT, GT, GTE, AND, OR, NOT, HASH)

# extra single-op helpers (farkle_onchain's assembler returns LISTS, so these compose with +)
CURSOR=[["CURSOR"]]; VALUE=[["VALUE"]]; BLOCKHASH=[["BLOCKHASH"]]; CALLER=[["CALLER"]]
PAY=[["PAY"]]; REQ=[["REQUIRE"]]; HALT=[["HALT"]]
WINDOW = 20   # blocks the join window stays open before the settle height

# table t: ta=host tp=pot ts=ante tsh=settleHeight tn=seatCount tx=resolvedCount tw=bestScore tb=leaderSeatId tz=closed
# seat g:  gg=tableId ga=addr gm=threshold gh=settleHeight gd=resolved gsc=bankedScore
open_m = (VALUE+P(0)+GT+REQ
  + A(0)+P(0)+GT+REQ
  + A(0)+LD("ta")+P(0)+EQ+REQ                    # table id fresh
  + A(2)+P(0)+GT+REQ                              # threshold > 0
  + A(1)+P(0)+GT+REQ                              # seat id > 0
  + A(0)+CALLER+STm("ta")
  + A(0)+VALUE+STm("ts")                          # ante
  + A(0)+VALUE+STm("tp")                          # pot starts = ante
  + A(0)+CURSOR+P(WINDOW)+ADD+STm("tsh")          # settle height
  + A(0)+P(1)+STm("tn")
  + A(1)+A(0)+STm("gg")                           # opener's seat
  + A(1)+CALLER+STm("ga")
  + A(1)+A(2)+STm("gm")
  + A(1)+A(0)+LD("tsh")+STm("gh")
  + HALT)

join_m = (VALUE+P(0)+GT+REQ
  + A(1)+P(0)+GT+REQ                              # seat id > 0
  + A(1)+LD("gg")+P(0)+EQ+REQ                     # seat fresh
  + A(0)+LD("ta")+P(0)+EQ+NOT+REQ                 # table exists
  + A(0)+LD("tz")+NOT+REQ                         # not closed
  + VALUE+A(0)+LD("ts")+EQ+REQ                    # ante matches
  + CURSOR+A(0)+LD("tsh")+LT+REQ                  # join window still open
  + A(2)+P(0)+GT+REQ                              # threshold > 0
  + A(0)+A(0)+LD("tp")+VALUE+ADD+STm("tp")        # pot += ante
  + A(0)+A(0)+LD("tn")+P(1)+ADD+STm("tn")         # seatCount++
  + A(1)+A(0)+STm("gg")
  + A(1)+CALLER+STm("ga")
  + A(1)+A(2)+STm("gm")
  + A(1)+A(0)+LD("tsh")+STm("gh")
  + HALT)

# resolve(g): PERMISSIONLESS once sh+1 is finalized — auto-play the seat's whole turn on-chain, then update leader
resolve_m = (A(0)+LD("gg")+P(0)+EQ+NOT+REQ        # seat exists
  + A(0)+LD("gd")+NOT+REQ                          # not resolved
  + CURSOR+A(0)+LD("gh")+P(1)+ADD+GTE+REQ          # sh+1 finalized
  # seed = HASH(BLOCKHASH(sh)+BLOCKHASH(sh+1)+seatId) -> scratch S["seed"]
  + STR("seed", A(0)+LD("gh")+BLOCKHASH + A(0)+LD("gh")+P(1)+ADD+BLOCKHASH + ADD + A(0) + ADD + HASH)
  # auto-play the turn -> gsc[seatId]  (seed_expr reads S["seed"] once per die; thr = gm[seatId])
  + score_ops(LDR("seed"), A(0)+LD("gm"), "gsc", A(0))
  + A(0)+P(1)+STm("gd")                            # resolved
  + A(0)+LD("gg")+A(0)+LD("gg")+LD("tx")+P(1)+ADD+STm("tx")   # tx[table]++
  # bet = gsc[g] > tw[table]
  + STR("bet", A(0)+LD("gsc") + A(0)+LD("gg")+LD("tw") + GT)
  # tw[table] = tw + bet*(gsc - tw)
  + A(0)+LD("gg") + (A(0)+LD("gg")+LD("tw")) + LDR("bet") + (A(0)+LD("gsc")) + (A(0)+LD("gg")+LD("tw")) + SUB + MUL + ADD + STm("tw")
  # tb[table] = tb + bet*(seatId - tb)
  + A(0)+LD("gg") + (A(0)+LD("gg")+LD("tb")) + LDR("bet") + A(0) + (A(0)+LD("gg")+LD("tb")) + SUB + MUL + ADD + STm("tb")
  + HALT)

# settle(t): pay the whole pot to the leader (highest banked). Requires all resolved + a leader exists.
settle_m = (A(0)+LD("ta")+P(0)+EQ+NOT+REQ
  + A(0)+LD("tz")+NOT+REQ
  + A(0)+LD("tx")+A(0)+LD("tn")+EQ+REQ            # every seat resolved
  + A(0)+LD("tb")+P(0)+EQ+NOT+REQ                 # a leader exists (someone scored > 0)
  + A(0)+LD("tb")+LD("ga") + A(0)+LD("tp") + PAY  # pay pot to ga[leaderSeatId]
  + A(0)+P(1)+STm("tz")
  + A(0)+P(0)+STm("tp")
  + HALT)

# reclaim(t): the all-farkle edge — nobody scored, host reclaims the pot
reclaim_m = (CALLER+A(0)+LD("ta")+EQ+REQ
  + A(0)+LD("tz")+NOT+REQ
  + A(0)+LD("tx")+A(0)+LD("tn")+EQ+REQ
  + A(0)+LD("tb")+P(0)+EQ+REQ                     # no leader (all busted)
  + A(0)+LD("ta") + A(0)+LD("tp") + PAY
  + A(0)+P(1)+STm("tz")
  + A(0)+P(0)+STm("tp")
  + HALT)

CODE = {"open":open_m, "join":join_m, "resolve":resolve_m, "settle":settle_m, "reclaim":reclaim_m}

def bh_seed(bh, sh, g): return vm_hash(bh[sh] + bh[sh+1] + g)   # == the contract's S["seed"]

# ---------------- TESTS ----------------
F=[]
def ck(n,c): print(("  ok  " if c else " FAIL ")+n); (F.append(n) if not c else None)
from execnode.vm import GAS_LIMIT
ck(f"resolve fits gas ({len(resolve_m)} < {GAS_LIMIT})", len(resolve_m) < GAS_LIMIT)

st=ExecState(tempfile.mktemp()); T0=1000; st.cursor=T0
for a in ["HOST"]+["P%d"%i for i in range(40)]: st.credit_deposit(a, 10**9)
st.apply_blob({"op":"deploy","code":CODE,"runtime":"stackvm","nonce":"farkle-open"},"HOST","d0")
CID=list(st.contracts)[0]
def bal(a): return st.bridge.get(a,0)
def M(m,k): return st.contracts[CID]["storage"].get(m,{}).get(str(k))
def call(m,args,val,who): return st.apply_blob({"op":"call","contract":CID,"method":m,"args":args,"value":val},who,m+str(args))

ANTE=1000; THRS=[300,500,750,1000,1500,2000,3000]
T=7; players=[]
# host opens (seat 100), others join (seats 101..)
call("open",[T, 100, 750], ANTE, "HOST"); players.append((100, 750, "HOST"))
sh=M("tsh",T)
ck("open: table + opener seat + settle height", M("ta",T)=="HOST" and M("gg",100)==T and M("gh",100)==sh and M("tp",T)==ANTE)
rng=random.Random(0xFA5)
for i in range(1, 30):
    g=100+i; thr=rng.choice(THRS); who="P%d"%(i%40)
    call("join",[T, g, thr], ANTE, who); players.append((g, thr, who))
ck("join: pot accumulated across all seats", M("tp",T)==ANTE*len(players))
ck("join: seat count", M("tn",T)==len(players))
ck("join after window closes reverts", (lambda: (st.__setattr__('cursor', sh+1), "revert" in call("join",[T,999,500],ANTE,"P1"))[-1])())
ck("wrong-ante join reverts", "revert" in call("join",[T, 998, 500], ANTE+1, "P2"))

# provide the settle block hashes, advance past sh+1, resolve every seat
st.block_hashes[sh]   = vm_hash(["bh", sh, 3])
st.block_hashes[sh+1] = vm_hash(["bh", sh+1, 8])
ck("resolve before finality reverts", (lambda: (st.__setattr__('cursor', sh), "revert" in call("resolve",[100],0,"P1"))[-1])())
st.cursor = sh+2
mism=0; best=(0,None); scores={}
for g, thr, who in players:
    call("resolve",[g],0,"anyone")
    onchain = M("gsc", g) or 0
    ref = farkle_ref(bh_seed(st.block_hashes, sh, g), thr)
    scores[g]=ref
    if onchain != ref: mism+=1
    if ref > best[0]: best=(ref, g)
ck(f"DIFFERENTIAL: {len(players)}/{len(players)} auto-played turns bytecode==reference", mism==0)
ck("leader = highest banked score (bytecode tracked it)", M("tb",T)==best[1] and (M("tw",T) or 0)==best[0])
print("   scores:", dict(sorted(scores.items(), key=lambda kv:-kv[1])[:6]), "…  best seat", best[1], "=", best[0])
ck("all seats resolved", M("tx",T)==len(players))
ck("double-resolve reverts", "revert" in call("resolve",[100],0,"anyone"))

# settle pays the whole pot to the leader
if best[1] is not None:
    winner = dict((g,who) for g,_,who in players)[best[1]]
    bw=bal(winner); pot=M("tp",T)
    call("settle",[T],0,"anyone")
    ck("settle pays the whole pot to the leader", bal(winner)==bw+pot and M("tz",T)==1)
    ck("re-settle reverts (closed)", "revert" in call("settle",[T],0,"anyone"))

# reclaim path: a table where everybody farkles (threshold huge is irrelevant; force via a bust-only seed check)
# construct a 1-seat table whose single seed busts -> no leader -> host reclaims
st.cursor=5000
call("open",[8, 200, 3000], ANTE, "HOST")
sh8=M("tsh",8)
# find block hashes that make seat 200 bust (farkle_ref==0)
h=9999
while True:
    b0=vm_hash(["z",h]); b1=vm_hash(["z",h+1])
    if farkle_ref(vm_hash(b0+b1+200), 3000)==0: break
    h+=1
st.block_hashes[sh8]=b0; st.block_hashes[sh8+1]=b1; st.cursor=sh8+2
call("resolve",[200],0,"HOST")
ck("all-farkle table has no leader", (M("tw",8) or 0)==0 and (M("tb",8) or 0)==0)
ck("settle reverts when nobody scored", "revert" in call("settle",[8],0,"HOST"))
bh0=bal("HOST"); pot8=M("tp",8); call("reclaim",[8],0,"HOST")
ck("host reclaims the pot when all busted", bal("HOST")==bh0+pot8 and M("tz",8)==1)

print("\n"+("ALL PASS" if not F else f"{len(F)} FAILED: {F}"))
if not F:
    outp = os.path.join(os.path.dirname(__file__),"..","execnode","contracts","farkle.json")
    if os.environ.get("WRITE"): json.dump(CODE, open(outp,"w")); print("WROTE", outp)
    else:
        committed=json.load(open(outp)) if os.path.exists(outp) else None
        assert committed==CODE, "execnode/contracts/farkle.json is STALE — re-run with WRITE=1"
        print("committed farkle.json matches")
sys.exit(1 if F else 0)
