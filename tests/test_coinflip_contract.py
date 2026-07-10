# tests/test_coinflip_contract.py — build + exhaustively exercise the BEACON Coin Flip CONTRACT (stackvm).
#
# No secrets, no reveal: two players just stake. When the second player joins, the game is bound to a settle
# height sh = CURSOR + SETTLE_DELAY; once that block is finalized the coin is decided by the chain:
#     result = HASH( BLOCKHASH(sh) + BLOCKHASH(sh+1) + gameId ) % 2      (0 -> p1/heads, 1 -> p2/tails)
# Those block hashes don't exist yet when either player commits their stake, so neither can predict or steer the
# flip (two blocks mixed vs a single-producer grind). settle is PERMISSIONLESS and pays the pot to the winner.
# Before an opponent joins, the opener can cancel and reclaim. Players sign ONCE (their stake) — nothing else.
import sys, json, tempfile, hashlib
sys.path.insert(0, "/root/nado")
from execnode.state import ExecState

def P(v): return ["PUSH", v]
def A(i): return ["ARG", i]
def LD(m): return ["MLOAD", m]
def ST(m): return ["MSTORE", m]
def OP(o): return [o]
CALLER=OP("CALLER"); VALUE=OP("VALUE"); CURSOR=OP("CURSOR"); HASH=OP("HASH"); BLOCKHASH=OP("BLOCKHASH")
ADD=OP("ADD"); SUB=OP("SUB"); MUL=OP("MUL"); MOD=OP("MOD"); EQ=OP("EQ"); GT=OP("GT"); GTE=OP("GTE"); NOT=OP("NOT")
REQ=OP("REQUIRE"); PAY=OP("PAY"); HALT=OP("HALT")

SETTLE_DELAY = 2   # blocks after the game fills before the flip block; result reads sh and sh+1

# maps: st=stake pt=pot sd=settled nn=count sh=settleHeight p1/p2=addr ws=winnerSlot(1|2)
open_m = [
  VALUE, P(0), GT, REQ,                         # value>0
  A(0), P(0), GT, REQ,                           # gid>0
  A(0), LD("nn"), P(0), EQ, REQ,                # fresh
  A(0), VALUE, ST("st"),
  A(0), VALUE, ST("pt"),
  A(0), CALLER, ST("p1"),
  A(0), P(1), ST("nn"),
  HALT ]

# join(gid)  value=stake  -> slot 2; binds the settle height
join_m = [
  A(0), LD("nn"), P(1), EQ, REQ,                # exactly one player so far
  A(0), LD("sd"), NOT, REQ,                      # not settled/cancelled
  VALUE, A(0), LD("st"), EQ, REQ,               # stake matches
  CALLER, A(0), LD("p1"), EQ, NOT, REQ,         # opponent isn't the opener
  A(0), CALLER, ST("p2"),
  A(0), A(0), LD("pt"), VALUE, ADD, ST("pt"),
  A(0), P(2), ST("nn"),
  A(0), CURSOR, P(SETTLE_DELAY), ADD, ST("sh"),  # sh = cursor + SETTLE_DELAY
  HALT ]

# settle(gid): PERMISSIONLESS once sh+1 is finalized — the chain decides + pays the winner the whole pot
settle_m = [
  A(0), LD("nn"), P(2), EQ, REQ,                # full
  A(0), LD("sd"), NOT, REQ,                      # not settled
  CURSOR, A(0), LD("sh"), P(1), ADD, GTE, REQ,  # sh+1 finalized
  # ws = HASH(bh(sh)+bh(sh+1)+gid) % 2 + 1   (1 -> p1, 2 -> p2)
  A(0),
  A(0), LD("sh"), BLOCKHASH,
  A(0), LD("sh"), P(1), ADD, BLOCKHASH, ADD,
  A(0), ADD, HASH, P(2), MOD, P(1), ADD, ST("ws"),
  # PAY winner the pot:  p1 gets pt*(ws==1), p2 gets pt*(ws==2)  (a 0 payout is a no-op)
  A(0), LD("p1"), A(0), LD("pt"), A(0), LD("ws"), P(1), SUB, NOT, MUL, PAY,
  A(0), LD("p2"), A(0), LD("pt"), A(0), LD("ws"), P(1), SUB, MUL, PAY,
  A(0), P(1), ST("sd"),
  A(0), P(0), ST("pt"),
  HALT ]

# cancel(gid): the opener reclaims the pot while no opponent has joined
cancel_m = [
  CALLER, A(0), LD("p1"), EQ, REQ,
  A(0), LD("nn"), P(1), EQ, REQ,
  A(0), LD("sd"), NOT, REQ,
  A(0), LD("p1"), A(0), LD("pt"), PAY,
  A(0), P(1), ST("sd"),
  A(0), P(0), ST("pt"),
  HALT ]
CODE = {"open":open_m, "join":join_m, "settle":settle_m, "cancel":cancel_m}

def vm_hash(v): return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")
def flip(bh, sh, g): return vm_hash(bh[sh] + bh[sh+1] + g) % 2   # 0->p1, 1->p2

F=[]
def ck(n,c): print(("  ok  " if c else " FAIL ")+n); (F.append(n) if not c else None)
st=ExecState(tempfile.mktemp()); T0=100; st.cursor=T0
for a in ("A","B","C"): st.credit_deposit(a, 100000)
st.apply_blob({"op":"deploy","code":CODE,"runtime":"stackvm","nonce":"coinflip-beacon"},"A","d0")
CID=list(st.contracts)[0]
def set_hashes(upto):
    for h in range(T0, upto+2): st.block_hashes[h]=vm_hash(["blk",h])
def bal(a): return st.bridge.get(a,0)
def M(m,g): return st.contracts[CID]["storage"].get(m,{}).get(str(g),0)
def call(m,args,val,who): return st.apply_blob({"op":"call","contract":CID,"method":m,"args":args,"value":val},who,m+str(args))

# open + join
G=7001
call("open",[G],50,"A")
ck("open escrows stake", bal("A")==100000-50 and M("st",G)==50 and M("nn",G)==1 and M("pt",G)==50)
ck("open by fresh id only (re-open reverts)", "revert" in call("open",[G],50,"A"))
ck("opener cannot join own game", "revert" in call("join",[G],50,"A"))
ck("stake-mismatch join reverts + refunds", "revert" in call("join",[G],40,"B") and bal("B")==100000)
call("join",[G],50,"B")
sh=M("sh",G)
ck("join escrows, pot=100, nn=2", M("pt",G)==100 and M("nn",G)==2 and M("p2",G)=="B")
ck("settle height bound = cursor+delay", sh==T0+SETTLE_DELAY)
ck("third player cannot join a full game", "revert" in call("join",[G],50,"C"))

# settle too early reverts
ck("settle before settle-height reverts", "revert" in call("settle",[G],0,"C"))

# finalize sh+1, settle (permissionless)
st.cursor=sh+2; set_hashes(st.cursor)
res=flip(st.block_hashes, sh, G); winner="A" if res==0 else "B"; loser="B" if res==0 else "A"
bw=bal(winner)
call("settle",[G],0,"C")   # settled by a THIRD party — still pays the real winner
ck(f"coin={res} -> winner {winner} paid the pot", bal(winner)==bw+100)
ck("winner slot recorded", M("ws",G)==(1 if res==0 else 2))
ck("settled flag + pot 0", M("sd",G)==1 and (M("pt",G) or 0)==0)
ck("double-settle reverts", "revert" in call("settle",[G],0,"C"))

# cancel path: opener reclaims before anyone joins
G2=7002
call("open",[G2],70,"A"); ba=bal("A")
ck("cancel refunds opener", "revert" not in call("cancel",[G2],0,"A") and bal("A")==ba+70)
ck("cannot join a cancelled game", "revert" in call("join",[G2],70,"B"))
ck("non-opener cannot cancel", (lambda: (call("open",[7003],30,"A"), "revert" in call("cancel",[7003],0,"B"))[-1])())

# SECURITY: cannot settle a game that never filled
call("open",[7004],25,"A"); st.cursor+=10; set_hashes(st.cursor)
ck("SEC: settle on a 1-player game reverts", "revert" in call("settle",[7004],0,"A"))

print("\n"+("ALL PASS" if not F else f"{len(F)} FAILED: {F}"))
if not F:
    import os
    outp = os.path.join(os.path.dirname(__file__),"..","execnode","contracts","coinflip.json")
    if os.environ.get("WRITE"): json.dump(CODE, open(outp,"w")); print("WROTE", outp)
    else:
        committed=json.load(open(outp)) if os.path.exists(outp) else None
        assert committed==CODE, "execnode/contracts/coinflip.json is STALE — re-run with WRITE=1 to regenerate"
        print("committed coinflip.json matches the assembled contract")
sys.exit(1 if F else 0)
