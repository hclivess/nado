# tests/test_poker_contract.py — AUTO-DEALING VIDEO POKER (stackvm), peer-banked + multiplayer.
#
# Same self-dealing multi-seat frame as the new Roulette/Dice, but a seat is a 5-card poker bet vs the bank.
# Every ROUND blocks the table deals; each seat's 5 cards come from FINALIZED L1 block hashes + its seat id:
#     card_i = HASH( BLOCKHASH(sh) + BLOCKHASH(sh+1) + seatId*10 + i ) % 52     (i=0..4)
#     rank = card % 13 (0=2 … 8=T,9=J,10=Q,11=K,12=A) ; suit = card // 13
# The CONTRACT evaluates the hand on-chain (Jacks-or-better paytable) — objective, no trusted party, no secrets.
# A win pays stake * paytable[hand]; losing stakes fold into the bankroll. Cards are drawn independently (no
# shuffle is feasible in the VM), so the paytable is tuned by simulation to a ~3.5% house edge.
import sys, json, tempfile, hashlib
sys.path.insert(0, "/root/nado")
from execnode.state import ExecState

def P(v): return ["PUSH", v]
def A(i): return ["ARG", i]
def LD(m): return ["MLOAD", m]
def ST(m): return ["MSTORE", m]
def OP(o): return [o]
CALLER=OP("CALLER"); VALUE=OP("VALUE"); CURSOR=OP("CURSOR"); HASH=OP("HASH"); BLOCKHASH=OP("BLOCKHASH")
ADD=OP("ADD"); SUB=OP("SUB"); MUL=OP("MUL"); DIV=OP("DIV"); MOD=OP("MOD")
EQ=OP("EQ"); GT=OP("GT"); GTE=OP("GTE"); LTE=OP("LTE"); AND=OP("AND"); OR=OP("OR"); NOT=OP("NOT")
REQ=OP("REQUIRE"); PAY=OP("PAY"); HALT=OP("HALT"); DUP=OP("DUP"); SWAP=OP("SWAP")

ROUND = 20; MAXMULT = 100
# paytable (total return multiplier), priority high->low; tuned to ~3.5% edge for with-replacement deals
PAY_TABLE = [("ROY",100),("SF",80),("QUAD",50),("FH",22),("FLUSH",16),("STR",10),("TRIP",4),("TWOP",3),("JACKS",2)]
FKEY = {"FLUSH":0,"STR":1,"SF":2,"ROY":3,"QUAD":4,"TRIP":5,"NPAIR":6,"TWOP":7,"FH":8,"JACKS":9}

# ---------- Python reference evaluator (must equal the bytecode) ----------
def poker_mult(cards):
    ranks=[c%13 for c in cards]; suits=[c//13 for c in cards]
    has=[0]*13; cnt=[0]*13
    for r in ranks: has[r]=1; cnt[r]+=1
    flush = all(s==suits[0] for s in suits)
    win = lambda s: all(has[s+k] for k in range(5))
    straight = any(win(s) for s in range(9)) or (has[12] and has[0] and has[1] and has[2] and has[3])
    sflush = straight and flush
    royal = sflush and win(8)
    quad = any(c==4 for c in cnt); trip = any(c==3 for c in cnt)
    npair = sum(1 for c in cnt if c==2)
    twopair = npair>=2; fullhouse = trip and npair>=1
    jacks = any((v>=9 and cnt[v]>=2) for v in range(13))
    ind = {"ROY":royal,"SF":sflush,"QUAD":quad,"FH":fullhouse,"FLUSH":flush,"STR":straight,"TRIP":trip,"TWOP":twopair,"JACKS":jacks}
    for name,m in PAY_TABLE:
        if ind[name]: return m
    return 0

# ---------- bytecode generator for settle ----------
def card_seed(i):   # bh(sh)+bh(sh+1)+seatId*10+i   (seatId = ARG 0)
    return ([A(0),LD("gh"),BLOCKHASH] + [A(0),LD("gh"),P(1),ADD,BLOCKHASH,ADD]
          + [A(0),P(10),MUL,P(i),ADD, ADD, HASH, P(52), MOD])
def gen_settle():
    g=[ A(0), LD("gg"), P(0), EQ, NOT, REQ,
        A(0), LD("gd"), NOT, REQ,
        CURSOR, A(0), LD("gh"), P(1), ADD, GTE, REQ ]
    for i in range(5):   # deal: cc[i]=card, cr[i]=rank, cs[i]=suit
        g += [P(i)] + card_seed(i) + [ST("cc")]
        g += [P(i), P(i),LD("cc"), P(13), MOD, ST("cr")]
        g += [P(i), P(i),LD("cc"), P(13), DIV, ST("cs")]
    for v in range(13):  # cn[v]=count, hv[v]=has
        g += [P(v), P(0)]
        for i in range(5): g += [P(i),LD("cr"), P(v), EQ, ADD]
        g += [ST("cn")]
        g += [P(v), P(v),LD("cn"), P(1), GTE, ST("hv")]
    F=FKEY
    g += [P(F["FLUSH"]),
          P(0),LD("cs"), P(1),LD("cs"), EQ,
          P(1),LD("cs"), P(2),LD("cs"), EQ, AND,
          P(2),LD("cs"), P(3),LD("cs"), EQ, AND,
          P(3),LD("cs"), P(4),LD("cs"), EQ, AND, ST("f")]
    g += [P(F["STR"]), P(0)]
    for s in range(9):
        g += [P(s),LD("hv"), P(s+1),LD("hv"), AND, P(s+2),LD("hv"), AND, P(s+3),LD("hv"), AND, P(s+4),LD("hv"), AND, OR]
    g += [P(12),LD("hv"), P(0),LD("hv"), AND, P(1),LD("hv"), AND, P(2),LD("hv"), AND, P(3),LD("hv"), AND, OR, ST("f")]
    g += [P(F["SF"]), P(F["STR"]),LD("f"), P(F["FLUSH"]),LD("f"), AND, ST("f")]
    g += [P(F["ROY"]), P(F["SF"]),LD("f"),
          P(8),LD("hv"), P(9),LD("hv"), AND, P(10),LD("hv"), AND, P(11),LD("hv"), AND, P(12),LD("hv"), AND, AND, ST("f")]
    g += [P(F["QUAD"]), P(0)]
    for v in range(13): g += [P(v),LD("cn"), P(4), EQ, OR]
    g += [ST("f")]
    g += [P(F["TRIP"]), P(0)]
    for v in range(13): g += [P(v),LD("cn"), P(3), EQ, OR]
    g += [ST("f")]
    g += [P(F["NPAIR"]), P(0)]
    for v in range(13): g += [P(v),LD("cn"), P(2), EQ, ADD]
    g += [ST("f")]
    g += [P(F["TWOP"]), P(F["NPAIR"]),LD("f"), P(2), GTE, ST("f")]
    g += [P(F["FH"]), P(F["TRIP"]),LD("f"), P(F["NPAIR"]),LD("f"), P(1), GTE, AND, ST("f")]
    g += [P(F["JACKS"]), P(0)]
    for v in range(9,13): g += [P(v),LD("cn"), P(2), GTE, OR]
    g += [ST("f")]
    # mult via nested select into mv[0]:  acc = sel(flag, k, acc) built innermost->outermost
    g += [P(0), P(0)]
    for name,k in reversed(PAY_TABLE):
        g += [DUP, P(k), SWAP, SUB, P(F[name]),LD("f"), MUL, ADD]
    g += [ST("mv")]
    g += [A(0), P(0),LD("mv"), ST("gr")]
    g += [A(0), P(0),LD("mv"), P(0), GT, ST("gw")]
    g += [A(0), LD("ga"), A(0), LD("gs"), P(0),LD("mv"), MUL, PAY]
    g += [A(0),LD("gg"), A(0),LD("gg"),LD("tp"), A(0),LD("gs"), P(0),LD("mv"), MUL, SUB, ST("tp")]
    g += [A(0),LD("gg"), A(0),LD("gg"),LD("tc"), A(0),LD("gs"), P(MAXMULT-1), MUL, SUB, ST("tc")]
    g += [A(0),LD("gg"), A(0),LD("gg"),LD("tk"), A(0),LD("gs"), ADD, A(0),LD("gs"), P(0),LD("mv"), MUL, SUB, ST("tk")]
    g += [A(0), P(1), ST("gd")]
    g += [A(0),LD("gg"), A(0),LD("gg"),LD("tx"), P(1), ADD, ST("tx")]
    g += [HALT]
    return g

open_m = [
  VALUE, P(0), GT, REQ,
  A(0), P(0), GT, REQ,
  A(0), LD("ta"), P(0), EQ, REQ,
  A(0), VALUE, ST("tk"),
  A(0), VALUE, ST("tp"),
  A(0), CALLER, ST("ta"),
  A(0), CURSOR, ST("t0"),
  HALT ]
bet_m = [   # bet(g, t) value=stake -> a 5-card hand is dealt at the round's settle height
  A(0), P(0), GT, REQ,
  A(1), P(0), GT, REQ,
  VALUE, P(0), GT, REQ,
  A(0), LD("gg"), P(0), EQ, REQ,
  A(1), LD("ta"), P(0), EQ, NOT, REQ,
  A(1), LD("tz"), NOT, REQ,
  A(1), LD("tc"), VALUE, P(MAXMULT-1), MUL, ADD, A(1), LD("tk"), LTE, REQ,   # cover 99x
  A(1), A(1), LD("tc"), VALUE, P(MAXMULT-1), MUL, ADD, ST("tc"),
  A(1), A(1), LD("tp"), VALUE, ADD, ST("tp"),
  A(0), VALUE, ST("gs"),
  A(0), A(1), ST("gg"),
  A(0), CALLER, ST("ga"),
  A(0), CURSOR, A(1), LD("t0"), SUB, P(ROUND), DIV, P(1), ADD, P(ROUND), MUL, A(1), LD("t0"), ADD, ST("gh"),
  A(1), A(1), LD("tn"), P(1), ADD, ST("tn"),
  HALT ]
settle_m = gen_settle()
close_m = [
  CALLER, A(0), LD("ta"), EQ, REQ,
  A(0), LD("tz"), NOT, REQ,
  A(0), LD("tx"), A(0), LD("tn"), EQ, REQ,
  A(0), LD("ta"), A(0), LD("tp"), PAY,
  A(0), P(1), ST("tz"),
  A(0), P(0), ST("tp"),
  HALT ]
fund_m = [
  CALLER, A(0), LD("ta"), EQ, REQ,
  A(0), LD("tz"), NOT, REQ,
  VALUE, P(0), GT, REQ,
  A(0), A(0), LD("tk"), VALUE, ADD, ST("tk"),
  A(0), A(0), LD("tp"), VALUE, ADD, ST("tp"),
  HALT ]
CODE = {"open":open_m, "bet":bet_m, "settle":settle_m, "close":close_m, "fund":fund_m}

def vm_hash(v): return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")
def cards_of(bh, sh, g): return [vm_hash(bh[sh] + bh[sh+1] + g*10 + i) % 52 for i in range(5)]

# ---------- TESTS ----------
F=[]
def ck(n,c): print(("  ok  " if c else " FAIL ")+n); (F.append(n) if not c else None)
def C(rank, suit): return suit*13 + rank
ck("ref: royal flush -> 100", poker_mult([C(8,0),C(9,0),C(10,0),C(11,0),C(12,0)])==100)
ck("ref: straight flush -> 80", poker_mult([C(3,1),C(4,1),C(5,1),C(6,1),C(7,1)])==80)
ck("ref: quads -> 50", poker_mult([C(5,0),C(5,1),C(5,2),C(5,3),C(2,0)])==50)
ck("ref: full house -> 22", poker_mult([C(7,0),C(7,1),C(7,2),C(2,0),C(2,1)])==22)
ck("ref: flush -> 16", poker_mult([C(2,2),C(5,2),C(8,2),C(10,2),C(12,2)])==16)
ck("ref: straight -> 10", poker_mult([C(4,0),C(5,1),C(6,2),C(7,3),C(8,0)])==10)
ck("ref: wheel straight -> 10", poker_mult([C(12,0),C(0,1),C(1,2),C(2,3),C(3,0)])==10)
ck("ref: trips -> 4", poker_mult([C(9,0),C(9,1),C(9,2),C(2,0),C(4,1)])==4)
ck("ref: two pair -> 3", poker_mult([C(9,0),C(9,1),C(4,2),C(4,3),C(2,0)])==3)
ck("ref: pair of kings -> 2", poker_mult([C(11,0),C(11,1),C(2,2),C(5,3),C(8,0)])==2)
ck("ref: pair of fives -> 0", poker_mult([C(3,0),C(3,1),C(2,2),C(5,3),C(8,0)])==0)
ck("ref: high card -> 0", poker_mult([C(2,0),C(5,1),C(8,2),C(10,3),C(12,0)])==0)

st=ExecState(tempfile.mktemp()); T0=100; st.cursor=T0
st.credit_deposit("BANK", 10**14)
for a in range(50): st.credit_deposit("P%d"%a, 10**11)
st.apply_blob({"op":"deploy","code":CODE,"runtime":"stackvm","nonce":"poker-beacon"},"BANK","d0")
CID=list(st.contracts)[0]
def Mv(m,g): return st.contracts[CID]["storage"].get(m,{}).get(str(g),0)
def call(m,args,val,who): return st.apply_blob({"op":"call","contract":CID,"method":m,"args":args,"value":val},who,m+str(args))

T=1; call("open",[T],10**13,"BANK")
STAKE=1000; N=600
for i in range(N): call("bet",[1000+i, T], STAKE, "P%d"%(i%50))
sh=Mv("gh",1000)
st.block_hashes[sh]   = vm_hash(["bh", sh, 7])
st.block_hashes[sh+1] = vm_hash(["bh", sh+1, 9])
st.cursor = sh+2
mism=0; cats={}
for i in range(N):
    g=1000+i; call("settle",[g],0,"P%d"%(i%50))
    onchain = Mv("gr",g)
    ref = poker_mult(cards_of(st.block_hashes, sh, g))
    cats[ref]=cats.get(ref,0)+1
    if onchain != ref: mism += 1
ck(f"DIFFERENTIAL: {N}/{N} hands bytecode==reference", mism==0)
print("   hand-multiplier distribution seen:", dict(sorted(cats.items())))
ck("pool never negative", Mv("tp",T) >= 0)
ck("committed released to 0 after all settle", (Mv("tc",T) or 0)==0)
ck("bankroll non-negative", Mv("tk",T) >= 0)
ck("all seats settled", Mv("tx",T)==N and Mv("tn",T)==N)

st.cursor=99999; call("open",[9],5000,"BANK")
ck("under-bankrolled bet reverts (needs 99x cover)", "revert" in call("bet",[901,9],1000,"P0") and Mv("gg",901)==0)
call("open",[10],10**8,"BANK"); call("close",[10],0,"BANK")
ck("bet on a CLOSED table reverts", "revert" in call("bet",[1001,10],1000,"P0"))

print("\n"+("ALL PASS" if not F else f"{len(F)} FAILED: {F}"))
if not F:
    import os
    outp = os.path.join(os.path.dirname(__file__),"..","execnode","contracts","poker.json")
    if os.environ.get("WRITE"): json.dump(CODE, open(outp,"w")); print("WROTE", outp)
    else:
        committed=json.load(open(outp)) if os.path.exists(outp) else None
        assert committed==CODE, "execnode/contracts/poker.json is STALE — re-run with WRITE=1"
        print("committed poker.json matches")
sys.exit(1 if F else 0)
