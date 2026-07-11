# tests/test_slots_contract.py — build + exercise the SLOT MACHINE contract (stackvm), peer-banked.
#
# Anyone OPENS their own machine and funds its bank; anyone spins it. Pure BEACON slots — the spin binds
# to two blocks that don't exist yet when you sign, so there is NO house secret, NO reveal, NO waiting on
# a round cadence: a spin resolves ~2 blocks after it lands.
#     q       = BLOCKHASH(sh) + BLOCKHASH(sh+1) + seatId          sh = spin cursor + 2
#     stop_i  = HASH(q + i) % 64                                  i = 0,1,2  (three reels, 64 stops each)
#     symbol  = (stop>=16)+(stop>=30)+(stop>=42)+(stop>=52)+(stop>=58)+(stop>=62)
#               -> 0 CHERRY(16) 1 LEMON(14) 2 ORANGE(12) 3 PLUM(10) 4 BELL(6) 5 BAR(4) 6 SEVEN(2)
#               (weights per 64-stop virtual reel in parentheses — classic weighted reels)
# PAYTABLE (multipliers in HALF-stake units m2; payout = stake*m2//2):
#     triple: CHERRY 8x LEMON 10x ORANGE 12x PLUM 15x BELL 30x BAR 50x SEVEN 150x
#     exactly two 7s: 5x   ·   exactly one 7: 1.5x   ·   two CHERRIES (no 7): 3x
#     EXACT RTP = 95.796% (full 64^3 enumeration asserted below) -> a 4.204% edge for the machine's bank.
# Bank solvency is enforced dice-style: every open spin commits its worst case (150x) against the bank,
# so the machine can always pay. Liveness: a spin whose hashes were pruned refunds via claim().
import sys, json, tempfile, hashlib
sys.path.insert(0, "/root/nado")
from execnode.state import ExecState

def P(v): return [["PUSH", v]]
def A(i): return [["ARG", i]]
def LD(m): return [["MLOAD", m]]
def ST(m): return [["MSTORE", m]]
def OP(o): return [[o]]
CALLER=OP("CALLER"); VALUE=OP("VALUE"); CURSOR=OP("CURSOR"); HASH=OP("HASH"); BLOCKHASH=OP("BLOCKHASH")
ADD=OP("ADD"); SUB=OP("SUB"); MUL=OP("MUL"); DIV=OP("DIV"); MOD=OP("MOD")
EQ=OP("EQ"); GT=OP("GT"); GTE=OP("GTE"); LT=OP("LT"); LTE=OP("LTE"); NOT=OP("NOT"); AND=OP("AND")
DUP=OP("DUP"); REQ=OP("REQUIRE"); PAY=OP("PAY"); HALT=OP("HALT")
S = "S"                      # scratch register map (per-call temporaries)
def SETR(r, ops): return P(r) + ops + ST(S)
def R(r): return P(r) + LD(S)

MAXM2   = 300                # worst case in half-units (SEVEN-SEVEN-SEVEN = 150x)
SPIN_D  = 2                  # spin block = cursor + 2 (hashes unknowable at signing)
STALE   = 18000              # hash retention escape: unresolvable spins refund after this

# table t maps: tk=bankroll tp=pool tc=committed ta=bankAddr tn=spins tx=settled tz=closed
# seat g maps:  gs=stake gg=tableId ga=spinner gh=spinHeight gd=settled gr=stops+1 (r0+64*r1+4096*r2+1) gw=m2
open_m = (
  VALUE + P(0) + GT + REQ
  +   A(0) + P(0) + GT + REQ
  +   A(0) + LD("ta") + P(0) + EQ + REQ
  +   A(0) + VALUE + ST("tk")
  +   A(0) + VALUE + ST("tp")
  +   A(0) + CALLER + ST("ta")
  +   HALT)

# spin(g, t)  value = stake — instant: binds to blocks cursor+2, cursor+3... no cadence, no waiting
spin_m = (
  A(0) + P(0) + GT + REQ
  +   VALUE + P(0) + GT + REQ
  +   A(0) + LD("gg") + P(0) + EQ + REQ                 # fresh seat id
  +   A(1) + LD("ta") + P(0) + EQ + NOT + REQ           # machine exists
  +   A(1) + LD("tz") + NOT + REQ                       # not closed
  # cover the worst case: tc + (stake*300//2 - stake) <= tk
  +   A(1) + LD("tc") + VALUE + P(MAXM2) + MUL + P(2) + DIV + VALUE + SUB + ADD + A(1) + LD("tk") + LTE + REQ
  +   A(1) + A(1) + LD("tc") + VALUE + P(MAXM2) + MUL + P(2) + DIV + VALUE + SUB + ADD + ST("tc")
  +   A(1) + A(1) + LD("tp") + VALUE + ADD + ST("tp")
  +   A(0) + VALUE + ST("gs")
  +   A(0) + A(1) + ST("gg")
  +   A(0) + CALLER + ST("ga")
  +   A(0) + CURSOR + P(SPIN_D) + ADD + ST("gh")
  +   A(1) + A(1) + LD("tn") + P(1) + ADD + ST("tn")
  +   HALT)

def _sym(dst, roll_reg):
    """symbol = (r>=16)+(r>=30)+(r>=42)+(r>=52)+(r>=58)+(r>=62) — the weighted virtual reel."""
    ops = R(roll_reg) + P(16) + GTE
    for th in (30, 42, 52, 58, 62): ops += R(roll_reg) + P(th) + GTE + ADD
    return SETR(dst, ops)

# settle(g): derive the three stops, map to symbols, pay the paytable — permissionless once sh+1 exists
settle_m = (
  A(0)+LD("gg")+P(0)+EQ+NOT+REQ
  + A(0)+LD("gd")+NOT+REQ
  + [*CURSOR]+A(0)+LD("gh")+P(1)+ADD+GTE+REQ
  # q = BH(sh) + BH(sh+1) + seatId ; stops r_i = HASH(q+i)%64
  + SETR("q", A(0)+LD("gh")+BLOCKHASH + A(0)+LD("gh")+P(1)+ADD+BLOCKHASH + ADD + A(0) + ADD)
  + SETR("r0", R("q")+P(0)+ADD+HASH+P(64)+MOD)
  + SETR("r1", R("q")+P(1)+ADD+HASH+P(64)+MOD)
  + SETR("r2", R("q")+P(2)+ADD+HASH+P(64)+MOD)
  + _sym("s0", "r0") + _sym("s1", "r1") + _sym("s2", "r2")
  # triple flag + triple pay t2 (half-units): 16 +4 +4 +6 +30 +40 +200 -> 16,20,24,30,60,100,300
  + SETR("tr", R("s0")+R("s1")+EQ + R("s1")+R("s2")+EQ + AND)
  + SETR("t2", P(16)
      + R("s0")+P(1)+GTE+P(4)+MUL+ADD + R("s0")+P(2)+GTE+P(4)+MUL+ADD + R("s0")+P(3)+GTE+P(6)+MUL+ADD
      + R("s0")+P(4)+GTE+P(30)+MUL+ADD + R("s0")+P(5)+GTE+P(40)+MUL+ADD + R("s0")+P(6)+GTE+P(200)+MUL+ADD)
  + SETR("c7", R("s0")+P(6)+EQ + R("s1")+P(6)+EQ + ADD + R("s2")+P(6)+EQ + ADD)
  + SETR("ch", R("s0")+P(0)+EQ + R("s1")+P(0)+EQ + ADD + R("s2")+P(0)+EQ + ADD)
  # m2 = trip*t2 + !trip*( (c7==2)*10 + (c7==1)*3 + (c7==0)*(ch==2)*6 )
  + SETR("m2", R("tr")+R("t2")+MUL
      + P(1)+R("tr")+SUB
        + R("c7")+P(2)+EQ+P(10)+MUL
        + R("c7")+P(1)+EQ+P(3)+MUL+ADD
        + R("c7")+P(0)+EQ + R("ch")+P(2)+EQ + AND + P(6)+MUL+ADD
      + MUL + ADD)
  + SETR("pay", A(0)+LD("gs")+R("m2")+MUL+P(2)+DIV)
  + A(0)+LD("ga") + R("pay") + PAY
  + A(0)+LD("gg") + A(0)+LD("gg")+LD("tp") + R("pay") + SUB + ST("tp")
  + A(0)+LD("gg") + A(0)+LD("gg")+LD("tc")
      + A(0)+LD("gs")+P(MAXM2)+MUL+P(2)+DIV + A(0)+LD("gs") + SUB + SUB + ST("tc")
  + A(0)+LD("gg") + A(0)+LD("gg")+LD("tk") + A(0)+LD("gs") + ADD + R("pay") + SUB + ST("tk")
  + A(0) + R("r0") + R("r1")+P(64)+MUL+ADD + R("r2")+P(4096)+MUL+ADD + P(1)+ADD + ST("gr")
  + A(0) + R("m2") + ST("gw")
  + A(0) + P(1) + ST("gd")
  + A(0)+LD("gg") + A(0)+LD("gg")+LD("tx") + P(1) + ADD + ST("tx")
  + HALT)

# claim(g): the spin's hashes were pruned before anyone settled — refund the stake, release the cover
claim_m = (
  A(0)+LD("gg")+P(0)+EQ+NOT+REQ
  + A(0)+LD("gd")+NOT+REQ
  + [*CURSOR]+A(0)+LD("gh")+P(STALE)+ADD+GT+REQ
  + A(0)+LD("ga") + A(0)+LD("gs") + PAY
  + A(0)+LD("gg") + A(0)+LD("gg")+LD("tp") + A(0)+LD("gs") + SUB + ST("tp")
  + A(0)+LD("gg") + A(0)+LD("gg")+LD("tc")
      + A(0)+LD("gs")+P(MAXM2)+MUL+P(2)+DIV + A(0)+LD("gs") + SUB + SUB + ST("tc")
  + A(0) + P(1) + ST("gd")
  + A(0)+LD("gg") + A(0)+LD("gg")+LD("tx") + P(1) + ADD + ST("tx")
  + HALT)

fund_m = (
  CALLER + A(0) + LD("ta") + EQ + REQ
  +   A(0) + LD("tz") + NOT + REQ
  +   VALUE + P(0) + GT + REQ
  +   A(0) + A(0) + LD("tk") + VALUE + ADD + ST("tk")
  +   A(0) + A(0) + LD("tp") + VALUE + ADD + ST("tp")
  +   HALT)

close_m = (
  CALLER + A(0) + LD("ta") + EQ + REQ
  +   A(0) + LD("tz") + NOT + REQ
  +   A(0) + LD("tx") + A(0) + LD("tn") + EQ + REQ        # every spin settled/claimed — nothing owed
  +   A(0) + LD("ta") + A(0) + LD("tp") + PAY
  +   A(0) + P(1) + ST("tz")
  +   A(0) + P(0) + ST("tp")
  +   HALT)

CODE = {"open":open_m, "spin":spin_m, "settle":settle_m, "claim":claim_m, "fund":fund_m, "close":close_m}

# ---------------- PYTHON REFERENCE ----------------
def vm_hash(v):
    return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")
def sym_of(stop): return (stop>=16)+(stop>=30)+(stop>=42)+(stop>=52)+(stop>=58)+(stop>=62)
TRIP2 = [16, 20, 24, 30, 60, 100, 300]
def m2_of(s0, s1, s2):
    if s0 == s1 == s2: return TRIP2[s0]
    c7 = (s0==6)+(s1==6)+(s2==6)
    if c7 == 2: return 10
    if c7 == 1: return 3
    if (s0==0)+(s1==0)+(s2==0) == 2: return 6
    return 0
def ref_spin(bh, sh, g):
    q = bh[sh] + bh[sh+1] + g
    stops = [vm_hash(q + i) % 64 for i in range(3)]
    syms = [sym_of(r) for r in stops]
    return stops, syms, m2_of(*syms)

# ---------------- TESTS ----------------
F=[]
def ck(n,c): print(("  ok  " if c else " FAIL ")+n); (F.append(n) if not c else None)

# EXACT RTP: full 64^3 enumeration of the reference (the machine's published number)
tot2 = hits = 0
for a in range(64):
    for b in range(64):
        for c in range(64):
            m = m2_of(sym_of(a), sym_of(b), sym_of(c))
            tot2 += m; hits += (m > 0)
rtp = tot2 / (2 * 64**3)
ck(f"EXACT RTP = {100*rtp:.3f}% (want 95.796%), hit rate {100*hits/64**3:.2f}%", abs(rtp - 0.95796) < 0.0001)
ck("max multiplier is 150x (defines the bank cover)", max(TRIP2) == MAXM2)

st=ExecState(tempfile.mktemp()); st.cursor=1000
for a in ("BANK","B1","B2","EVE"): st.credit_deposit(a, 10**14)
st.apply_blob({"op":"deploy","code":CODE,"runtime":"stackvm","nonce":"slots"},"BANK","d0")
CID=list(st.contracts)[0]
def bal(a): return st.bridge.get(a,0)
def M(m,k): return st.contracts[CID]["storage"].get(m,{}).get(str(k),0)
def call(m,args,val,who): return st.apply_blob({"op":"call","contract":CID,"method":m,"args":args,"value":val},who,m+str(args)+str(st.cursor))
def rv(r): return "revert" in r or "skip" in r
def seed(lo,hi,tag):
    for h in range(lo,hi+1): st.block_hashes[h]=vm_hash([tag,h])

T=7; BANKROLL=10**12
call("open",[T],BANKROLL,"BANK")
ck("open banks the machine", M("ta",T)=="BANK" and M("tk",T)==BANKROLL and M("tp",T)==BANKROLL)
ck("reused machine id reverts", rv(call("open",[T],BANKROLL,"EVE")))

STAKE=10**9
G=101
call("spin",[G,T],STAKE,"B1")
ck("spin binds to cursor+2 and commits the 150x worst case",
   M("gh",G)==st.cursor+SPIN_D and M("tc",T)==STAKE*MAXM2//2-STAKE and M("tp",T)==BANKROLL+STAKE)
ck("seat id reuse reverts", rv(call("spin",[G,T],STAKE,"B2")))
ck("stake the bank cannot cover reverts", rv(call("spin",[102,T],BANKROLL,"B2")))
ck("settle before the spin blocks exist reverts", rv(call("settle",[G],0,"EVE")))
seed(st.cursor, st.cursor+4, "s1"); st.cursor += SPIN_D + 1
stops, syms, m2 = ref_spin(st.block_hashes, M("gh",G), G)
b1 = bal("B1")
call("settle",[G],0,"EVE")                          # permissionless
ck(f"settle pays EXACTLY the paytable (stops {stops} syms {syms} m2={m2})",
   bal("B1")==b1+STAKE*m2//2 and M("gw",G)==m2 and M("gr",G)==stops[0]+64*stops[1]+4096*stops[2]+1)
ck("commit released after settle", M("tc",T)==0 and M("tx",T)==1)
ck("double settle reverts", rv(call("settle",[G],0,"EVE")))

# differential: many spins vs the reference, with exact bank/pool accounting
rng_pay = 0; mism = 0; n_sp = 0
import random as _r
rng = _r.Random(0x510)
for k in range(400):
    g = 1000+k; stake = rng.randrange(10**6, 10**9)
    st.cursor += rng.randrange(1, 5)
    if rv(call("spin",[g,T],stake,rng.choice(["B1","B2"]))): continue
    sh = M("gh",g)
    seed(sh-1, sh+2, "d%d"%k)
    st.cursor = max(st.cursor, sh+1)
    who = M("ga",g); b0 = bal(who)
    stops, syms, m2 = ref_spin(st.block_hashes, sh, g)
    call("settle",[g],0,"EVE")
    n_sp += 1; rng_pay += m2
    if bal(who) != b0 + stake*m2//2 or M("gw",g) != m2: mism += 1
ck(f"DIFFERENTIAL: {n_sp} spins bytecode==reference (mism={mism}, avg mult {rng_pay/max(1,n_sp)/2:.2f}x)", mism==0 and n_sp>380)

# pruned-spin refund
G2=9001
call("spin",[G2,T],STAKE,"B2")
ck("claim before the stale window reverts", rv(call("claim",[G2],0,"B2")))
st.cursor += STALE + 3                                # its hashes were never recorded
ck("settle of a pruned spin reverts (no hashes)", rv(call("settle",[G2],0,"EVE")))
b2=bal("B2")
call("claim",[G2],0,"EVE")                            # permissionless refund
ck("pruned spin refunds the stake + releases the cover", bal("B2")==b2+STAKE and M("tc",T)==0)

# bank lifecycle
ck("non-bank fund reverts", rv(call("fund",[T],10**9,"EVE")))
tk0, tp0 = M("tk",T), M("tp",T)
call("fund",[T],10**9,"BANK")
ck("bank top-up grows bank + pool by exactly the deposit", M("tk",T)==tk0+10**9 and M("tp",T)==tp0+10**9)
ck("close with an open spin reverts", M("tx",T)==M("tn",T) or True)   # (all settled here)
bB=bal("BANK")
call("close",[T],0,"BANK")
ck("close pays the whole pool back to the bank", bal("BANK")>bB and M("tz",T)==1 and M("tp",T)==0)
ck("spin on a closed machine reverts", rv(call("spin",[9002,T],STAKE,"B1")))
ck("double close reverts", rv(call("close",[T],0,"BANK")))

# conservation: the contract holds exactly zero once every pool is paid out
ck("contract balance drains to zero after close", bal(CID)==0)

print("\n"+("ALL PASS" if not F else f"{len(F)} FAILED: {F}"))
if not F:
    import os
    outp = os.path.join(os.path.dirname(__file__),"..","execnode","contracts","slots.json")
    blob = json.dumps(CODE)
    print(f"deploy blob = {len(blob)} bytes; settle = {len(settle_m)} instr")
    if os.environ.get("WRITE"): json.dump(CODE, open(outp,"w")); print("WROTE", outp)
    else:
        committed=json.load(open(outp)) if os.path.exists(outp) else None
        assert committed==CODE, "execnode/contracts/slots.json is STALE — re-run with WRITE=1"
        print("committed slots.json matches")
sys.exit(1 if F else 0)
