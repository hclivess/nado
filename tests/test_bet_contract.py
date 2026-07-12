# tests/test_bet_contract.py — build + exhaustively exercise the SPORTS BETTING contract (stackvm).
#
# A PARIMUTUEL (pooled) sports book with NO house: bettors stake NADO on an outcome of a real-world
# match; when the result is posted the WINNING side splits the ENTIRE pool pro-rata to their stake
# (exactly like a racetrack tote). The contract only escrows and redistributes — it never mints, never
# takes the other side of a bet, and can never pay out more than it holds.
#
# The one place trust enters is the RESULT: a blockchain can't see the real world, so an authorized
# ORACLE key must post the final outcome via resolve(). The oracle set is CONFIGURABLE (admin can add
# keys and raise the threshold to M-of-N), and a free public source registry (TheSportsDB, football-data,
# …) is stored on-chain for transparency. Bettors are protected two ways: the oracle may void() a
# postponed/cancelled match, and if NO result is posted by a per-market deadline ANYONE may void it —
# either way every stake is refunded 1:1. If the posted winner had zero backers the market auto-voids.
#
# Payouts are PULL-based: each participant calls claim(m) and the contract computes their own pro-rata
# share (or refund). That scales to unlimited bettors (PAY is capped at 16 recipients per call, so a
# push-to-all settle could never serve a big market).
#
# Outcomes are integers 0..nout-1 EVERYWHERE (bet/resolve args, pool keys) so the composite string keys
# always match. The frontend + resolver bot must honour that.
import sys, json, tempfile, os
sys.path.insert(0, "/root/nado")
from execnode.state import ExecState

# ---- opcode helpers -------------------------------------------------------------------------------
def P(v): return ["PUSH", v]
def A(i): return ["ARG", i]
def LD(m): return ["MLOAD", m]
def ST(m): return ["MSTORE", m]
CALLER=["CALLER"]; VALUE=["VALUE"]; CURSOR=["CURSOR"]
ADD=["ADD"]; SUB=["SUB"]; MUL=["MUL"]; DIV=["DIV"]
EQ=["EQ"]; GT=["GT"]; GTE=["GTE"]; LT=["LT"]; LTE=["LTE"]; AND=["AND"]; OR=["OR"]; NOT=["NOT"]
REQ=["REQUIRE"]; PAY=["PAY"]; HALT=["HALT"]; DUP=["DUP"]; SWAP=["SWAP"]; CONCAT=["CONCAT"]

SEP = "|"
def KEY(*parts):
    """Compose a namespaced map key on the stack: KEY([A(0)],[A(1)]) -> 'm|outcome'. Each part is a
    list of opcodes leaving exactly one value; parts are joined with a '|' separator (blake-safe, and
    the only key mechanism the VM has — keys are just strings built with CONCAT)."""
    prog = list(parts[0])
    for p in parts[1:]:
        prog = prog + [P(SEP), CONCAT] + list(p) + [CONCAT]
    return prog
def load(m, parts): return KEY(*parts) + [LD(m)]
def store(m, parts, valprog): return KEY(*parts) + list(valprog) + [ST(m)]
def acc(m, parts, valprog):    # m[key] += val   (read-modify-write; key rebuilt for load and store)
    return KEY(*parts) + KEY(*parts) + [LD(m)] + list(valprog) + [ADD, ST(m)]
def present(a):                # 1 if the value pushed by `a` is a non-empty string (a real address), else 0
    return list(a) + [P(0), EQ, NOT] + list(a) + [P(""), EQ, NOT] + [AND]

# ---- storage maps ---------------------------------------------------------------------------------
# cfg[admin|thr|oc|srcN]  orc[addr]=1  src[i]=name
# per market m: mk=1 exists · no=#outcomes · lk=lock height · dl=deadline height · ds=desc blob ·
#               so=source name · rs=winner+1 · dn=1 resolved · vd=1 void
# pools: pl[m|i]=pool · tot[m]=total · stk[m|i|caller] · us[m|caller]=total stake · cl[m|caller]=1 claimed
# votes (M-of-N): vt[m|caller]=voted outcome+1 · vc[m|i]=votes for i

# constructor(): deployer becomes admin + first oracle, threshold 1
constructor = (
    store("cfg", [[P("admin")]], [CALLER]) +
    store("cfg", [[P("thr")]],   [P(1)]) +
    store("cfg", [[P("oc")]],    [P(1)]) +
    store("orc", [[CALLER]],     [P(1)]) +
    [HALT])

ADMIN_GATE = [CALLER, P("admin"), LD("cfg"), EQ, REQ]

# set_oracle(addr, on): admin adds (on=1) / removes (on=0) an oracle key; oc tracks the count and can
# never drop below the threshold or below 1 (so resolution can't be stranded).
set_oracle = (
    ADMIN_GATE +
    [A(1), P(0), GTE, REQ, A(1), P(1), LTE, REQ] +                       # on in {0,1}
    store("cfg", [[P("oc")]],
          [P("oc"), LD("cfg")] + [A(1), A(0), LD("orc"), SUB] + [ADD]) + # oc += on - orc[addr]
    store("orc", [[A(0)]], [A(1)]) +                                     # orc[addr] = on
    [P("oc"), LD("cfg"), P(1), GTE, REQ] +                               # oc >= 1
    [P("oc"), LD("cfg"), P("thr"), LD("cfg"), GTE, REQ] +                # oc >= threshold
    [HALT])

# set_threshold(M): admin sets M-of-N (1 <= M <= oc)
set_threshold = (
    ADMIN_GATE +
    [A(0), P(1), GTE, REQ] +
    [A(0), P("oc"), LD("cfg"), LTE, REQ] +
    store("cfg", [[P("thr")]], [A(0)]) +
    [HALT])

# add_source(name): admin registers a free public source name (on-chain, for transparency)
add_source = (
    ADMIN_GATE +
    store("src", [[P("srcN"), LD("cfg")]], [A(0)]) +                     # src[srcN] = name
    store("cfg", [[P("srcN")]], [P("srcN"), LD("cfg"), P(1), ADD]) +     # srcN++
    [HALT])

# create_market(m, nout, lock, deadline, desc, source, ev, thr, r0, r1, r2): PERMISSIONLESS — anyone
# lists a market and names its own RESOLVER SET (up to 3 addresses r0..r2) + a threshold thr (M-of-N).
# Empty resolver slots are ignored; if NONE are given the creator becomes the sole resolver. thr defaults
# to 1 and must be <= the number of resolvers. desc is a '\n'-joined blob: line 0 = title, lines 1..nout =
# outcome labels. source = a free public source name (transparency); ev = its event id (so a bot can map
# the market to the real match). lock = L1 height betting closes (kickoff); deadline = height past which
# anyone may void if still unresolved. mrc = resolver count, mth = threshold, mres[m|addr]=1 membership,
# mcr = creator (attribution). Official (bot-created) markets just name the node key as the resolver.
create_market = (
    [A(0), LD("mk"), P(0), EQ, REQ] +          # market id is fresh
    [A(1), P(2), GTE, REQ] +                    # at least 2 outcomes
    [A(2), CURSOR, GT, REQ] +                   # betting closes in the future
    [A(3), A(2), GT, REQ] +                     # deadline is after the close
    # resolver membership for each provided address (a blank slot writes 0 -> deleted, harmless)
    store("mres", [[A(0)], [A(8)]], present([A(8)])) +
    store("mres", [[A(0)], [A(9)]], present([A(9)])) +
    store("mres", [[A(0)], [A(10)]], present([A(10)])) +
    store("mrc", [[A(0)]], present([A(8)]) + present([A(9)]) + [ADD] + present([A(10)]) + [ADD]) +
    # if no resolver was given, the creator becomes the resolver (OR preserves an already-set membership)
    store("mres", [[A(0)], [CALLER]],
          KEY([A(0)], [CALLER]) + [LD("mres")] + [A(0), LD("mrc"), NOT] + [OR]) +
    store("mrc", [[A(0)]], [A(0), LD("mrc")] + [A(0), LD("mrc"), NOT] + [ADD]) +   # +1 iff it was 0
    # threshold defaults to 1 and can't exceed the resolver count
    store("mth", [[A(0)]], [A(7)] + [A(7), NOT] + [ADD]) +
    [A(0), LD("mth"), A(0), LD("mrc"), LTE, REQ] +
    store("mk", [[A(0)]], [P(1)]) +
    store("no", [[A(0)]], [A(1)]) +
    store("lk", [[A(0)]], [A(2)]) +
    store("dl", [[A(0)]], [A(3)]) +
    store("ds", [[A(0)]], [A(4)]) +
    store("so", [[A(0)]], [A(5)]) +
    store("ev", [[A(0)]], [A(6)]) +
    store("mcr", [[A(0)]], [CALLER]) +
    [HALT])

# bet(m, outcome) with VALUE: stake on an outcome while the market is open and before it locks.
bet = (
    [VALUE, P(0), GT, REQ] +
    [A(0), LD("mk"), P(1), EQ, REQ] +           # market exists
    [A(0), LD("dn"), NOT, REQ] +                 # not resolved
    [A(0), LD("vd"), NOT, REQ] +                 # not void
    [CURSOR, A(0), LD("lk"), LT, REQ] +          # before lock
    [A(1), P(0), GTE, REQ] +                      # outcome >= 0
    [A(1), A(0), LD("no"), LT, REQ] +            # outcome < nout
    acc("pl",  [[A(0)], [A(1)]], [VALUE]) +
    acc("tot", [[A(0)]], [VALUE]) +
    acc("stk", [[A(0)], [A(1)], [CALLER]], [VALUE]) +
    acc("us",  [[A(0)], [CALLER]], [VALUE]) +
    [HALT])

# resolve(m, outcome): a RESOLVER of this market posts the result. Each resolver votes once; the first
# outcome to reach the market's threshold finalizes. If that outcome had zero backers the market
# auto-voids (refund everyone) instead of resolving to an unpayable pool.
POOLPOS = load("pl", [[A(0)], [A(1)]]) + [P(0), GT]                       # pool(outcome) > 0
# effective threshold: this market's own (mth) if it named resolvers, else 1 (legacy markets, admin-resolved)
THR_EFF = ([A(0), LD("mrc"), P(0), GT] + [A(0), LD("mth")] + [MUL]
           + [A(0), LD("mrc"), P(0), GT, NOT] + [ADD])
REACHED = load("vc", [[A(0)], [A(1)]]) + THR_EFF + [GTE]                  # votes(outcome) >= threshold
# who may resolve: a named resolver of THIS market, OR the admin for a legacy market (mrc == 0)
GATE_RES = (KEY([A(0)], [CALLER]) + [LD("mres")]
            + [A(0), LD("mrc"), NOT] + [CALLER, P("admin"), LD("cfg"), EQ, AND]
            + [OR])
resolve = (
    GATE_RES + [REQ] +                          # caller may resolve this market
    [A(0), LD("mk"), P(1), EQ, REQ] +           # market exists
    [A(0), LD("dn"), NOT, REQ] +                 # not already resolved
    [A(0), LD("vd"), NOT, REQ] +                 # not void
    [CURSOR, A(0), LD("lk"), GTE, REQ] +         # betting has closed
    [A(1), P(0), GTE, REQ] + [A(1), A(0), LD("no"), LT, REQ] +
    KEY([A(0)], [CALLER]) + [LD("vt"), P(0), EQ, REQ] +    # this resolver hasn't voted
    store("vt", [[A(0)], [CALLER]], [A(1), P(1), ADD]) +   # vt[m|caller] = outcome+1
    acc("vc", [[A(0)], [A(1)]], [P(1)]) +                  # vc[m|outcome]++
    store("dn", [[A(0)]], REACHED + POOLPOS + [AND]) +               # resolved iff reached & backed
    store("vd", [[A(0)]], REACHED + POOLPOS + [NOT] + [AND]) +       # void iff reached & unbacked
    store("rs", [[A(0)]], (REACHED + POOLPOS + [AND]) + [A(1), P(1), ADD, MUL]) +   # winner+1 (0 if not done)
    [HALT])

# void(m): a resolver of this market (or the admin) may void anytime before resolution; ANYONE may void
# once the deadline passes. Either way every stake is refunded 1:1 via claim().
void = (
    [A(0), LD("mk"), P(1), EQ, REQ] +
    [A(0), LD("dn"), NOT, REQ] +
    [A(0), LD("vd"), NOT, REQ] +
    (KEY([A(0)], [CALLER]) + [LD("mres")]                       # a resolver of this market
     + [CALLER, P("admin"), LD("cfg"), EQ] + [OR]               # or the admin
     + [CURSOR, A(0), LD("dl"), GTE] + [OR]) + [REQ] +          # or past the deadline
    store("vd", [[A(0)]], [P(1)]) +
    [HALT])

# claim(m): pull payout. If void -> refund the caller's total stake. If resolved -> the caller's stake
# on the winning outcome * total pool / winning pool. The divisor is made safe (+void) and the winning
# stake is 0 when void, so the untaken branch is always a clean 0 (never a divide-by-zero).
Wf = [A(0), LD("rs"), P(1), SUB]                                          # winning outcome index
numer      = KEY([A(0)], Wf, [CALLER]) + [LD("stk")] + [A(0), LD("tot")] + [MUL]
denom_safe = KEY([A(0)], Wf) + [LD("pl")] + [A(0), LD("vd")] + [ADD]      # pl[m|win] + void(0/1)
winshare   = numer + denom_safe + [DIV]
refund     = load("us", [[A(0)], [CALLER]])
term1 = [A(0), LD("vd")] + refund + [MUL]                                 # void ? refund : 0
term2 = [A(0), LD("vd"), NOT] + winshare + [MUL]                          # done ? winshare : 0
payout = term1 + term2 + [ADD]
claim = (
    [A(0), LD("dn"), A(0), LD("vd"), OR, REQ] +                 # resolved or void
    KEY([A(0)], [CALLER]) + [LD("cl"), NOT, REQ] +             # not already claimed
    payout + [DUP, P(0), GT, REQ] +                            # something to pay
    store("cl", [[A(0)], [CALLER]], [P(1)]) +                  # mark claimed
    [CALLER, SWAP, PAY] +                                      # pay caller the amount left on the stack
    [HALT])

CODE = {"constructor": constructor, "set_oracle": set_oracle, "set_threshold": set_threshold,
        "add_source": add_source, "create_market": create_market, "bet": bet, "resolve": resolve,
        "void": void, "claim": claim}

# ---- harness --------------------------------------------------------------------------------------
F = []
def ck(n, c): print(("  ok  " if c else " FAIL ") + n); (F.append(n) if not c else None)
st = ExecState(tempfile.mktemp()); T0 = 1000; st.cursor = T0
WHO = ["ADMIN", "O2", "O3", "X", "Y", "Z", "W"]
for a in WHO: st.credit_deposit(a, 1_000_000)
st.apply_blob({"op": "deploy", "code": CODE, "runtime": "stackvm", "nonce": "bet-v1"}, "ADMIN", "d0")
CID = list(st.contracts)[0]
def S(m, key): return st.contracts[CID]["storage"].get(m, {}).get(str(key), 0)
def bal(a): return st.bridge.get(a, 0)
def call(m, args, val, who): return st.apply_blob({"op": "call", "contract": CID, "method": m, "args": args, "value": val or 0}, who, m + str(args) + who + str(st.cursor))

# create args helper: pad the resolver set to 3 slots (thr=0 -> defaults to 1)
def CM(m, nout, lk, dl, desc, src, ev, thr=0, resolvers=()):
    r = list(resolvers) + ["", "", ""]
    return [m, nout, lk, dl, desc, src, ev, thr, r[0], r[1], r[2]]

# constructor wired the config
ck("deploy: admin set", S("cfg", "admin") == "ADMIN")

# add_source stays admin-gated (the free-source registry is protocol config)
ck("add_source: non-admin reverts", "revert" in call("add_source", ["thesportsdb"], None, "X"))
call("add_source", ["thesportsdb"], None, "ADMIN")
call("add_source", ["football-data"], None, "ADMIN")
ck("add_source: registered", S("src", 0) == "thesportsdb" and S("src", 1) == "football-data" and S("cfg", "srcN") == 2)

# --- market 1: created by ADMIN with NO resolver named -> ADMIN is the default resolver -------------
M1 = 5001
DESC = "Arsenal vs Chelsea\nArsenal\nDraw\nChelsea"
call("create_market", CM(M1, 3, T0+100, T0+400, DESC, "thesportsdb", "133602"), None, "ADMIN")
ck("create_market: stored", S("mk", M1) == 1 and S("no", M1) == 3 and S("lk", M1) == T0+100 and S("dl", M1) == T0+400 and S("ds", M1) == DESC and S("so", M1) == "thesportsdb" and S("ev", M1) == "133602")
ck("create_market: creator is default resolver", S("mres", f"{M1}|ADMIN") == 1 and S("mrc", M1) == 1 and S("mth", M1) == 1 and S("mcr", M1) == "ADMIN")
ck("create_market: PERMISSIONLESS — anyone can list", "revert" not in call("create_market", CM(5055, 2, T0+100, T0+400, "x\na\nb", "thesportsdb", "e"), None, "X") and S("mcr", 5055) == "X")
ck("create_market: duplicate id reverts", "revert" in call("create_market", CM(M1, 2, T0+100, T0+400, "x", "y", "z"), None, "ADMIN"))
ck("create_market: <2 outcomes reverts", "revert" in call("create_market", CM(5099, 1, T0+100, T0+400, "x", "y", "z"), None, "ADMIN"))
ck("create_market: lock in past reverts", "revert" in call("create_market", CM(5098, 2, T0-1, T0+400, "x", "y", "z"), None, "ADMIN"))
ck("create_market: deadline<=lock reverts", "revert" in call("create_market", CM(5097, 2, T0+100, T0+100, "x", "y", "z"), None, "ADMIN"))
ck("create_market: threshold > resolver count reverts", "revert" in call("create_market", CM(5096, 2, T0+100, T0+400, "x", "y", "z", thr=2, resolvers=("W",)), None, "ADMIN"))

# bets: X 300 on Arsenal(0), Y 700 on Chelsea(2), Z 500 on Arsenal(0). Total pool 1500, Arsenal 800.
bx, by, bz = bal("X"), bal("Y"), bal("Z")
call("bet", [M1, 0], 300, "X")
call("bet", [M1, 2], 700, "Y")
call("bet", [M1, 0], 500, "Z")
ck("bet: escrowed", bal("X") == bx-300 and bal("Y") == by-700 and bal("Z") == bz-500 and bal(CID) == 1500)
ck("bet: pools", S("pl", f"{M1}|0") == 800 and S("pl", f"{M1}|2") == 700 and S("tot", M1) == 1500)
ck("bet: per-user stake tracked", S("stk", f"{M1}|0|X") == 300 and S("stk", f"{M1}|0|Z") == 500 and S("us", f"{M1}|X") == 300)
ck("bet: zero value reverts", "revert" in call("bet", [M1, 0], 0, "X"))
ck("bet: bad outcome reverts", "revert" in call("bet", [M1, 3], 100, "X"))
ck("bet: nonexistent market reverts", "revert" in call("bet", [9999, 0], 100, "X"))

# can't resolve before the match locks; only a RESOLVER of this market may resolve
ck("resolve: before lock reverts", "revert" in call("resolve", [M1, 0], None, "ADMIN"))
st.cursor = T0 + 120   # kickoff passed, betting closed
ck("bet: after lock reverts", "revert" in call("bet", [M1, 0], 100, "X"))
ck("resolve: non-resolver reverts", "revert" in call("resolve", [M1, 0], None, "X"))

call("resolve", [M1, 0], None, "ADMIN")   # Arsenal (outcome 0) won
ck("resolve: recorded winner + done", S("rs", M1) == 1 and S("dn", M1) == 1 and S("vd", M1) == 0)
ck("resolve: double resolve reverts", "revert" in call("resolve", [M1, 2], None, "ADMIN"))

# claims: winners X and Z split the WHOLE 1500 pool pro-rata to their 800 Arsenal pool. loser Y gets 0.
bx, by, bz = bal("X"), bal("Y"), bal("Z")
call("claim", [M1], None, "X")
call("claim", [M1], None, "Z")
ck("claim: X pro-rata share", bal("X") == bx + 300*1500//800)
ck("claim: Z pro-rata share", bal("Z") == bz + 500*1500//800)
ck("claim: loser Y gets nothing (reverts)", "revert" in call("claim", [M1], None, "Y") and bal("Y") == by)
ck("claim: double-claim reverts", "revert" in call("claim", [M1], None, "X"))
ck("claim: payouts never exceed the pool (dust >= 0)", bal(CID) >= 0 and (300*1500//800)+(500*1500//800) <= 1500)

# --- market 1b: CUSTOM resolver — user X lists a market and names W as the sole resolver ------------
MC = 5010
call("create_market", CM(MC, 2, T0+150, T0+400, "Fight\nRed\nBlue", "thesportsdb", "evc", resolvers=("W",)), None, "X")
ck("custom: W is the named resolver, not the creator", S("mres", f"{MC}|W") == 1 and S("mres", f"{MC}|X") == 0 and S("mrc", MC) == 1)
call("bet", [MC, 0], 100, "Y"); call("bet", [MC, 1], 100, "Z")
st.cursor = T0 + 160
ck("custom: the creator can't resolve (not a resolver)", "revert" in call("resolve", [MC, 0], None, "X"))
ck("custom: the admin can't resolve someone else's market", "revert" in call("resolve", [MC, 0], None, "ADMIN"))
call("resolve", [MC, 0], None, "W")
ck("custom: the named resolver resolves it", S("dn", MC) == 1 and S("rs", MC) == 1)

# --- market 2: resolver voids a postponed match -> everyone refunded 1:1 ---------------------------
M2 = 5002
call("create_market", CM(M2, 2, T0+200, T0+500, "Game B\nHome\nAway", "thesportsdb", "ev2"), None, "ADMIN")
call("bet", [M2, 0], 400, "X")
call("bet", [M2, 1], 600, "Y")
bx, by = bal("X"), bal("Y")
ck("void: non-resolver before deadline reverts", "revert" in call("void", [M2], None, "X"))
call("void", [M2], None, "ADMIN")
ck("void: flag set", S("vd", M2) == 1)
ck("void: no more bets", "revert" in call("bet", [M2, 0], 100, "Z"))
call("claim", [M2], None, "X"); call("claim", [M2], None, "Y")
ck("void: full refunds", bal("X") == bx + 400 and bal("Y") == by + 600)

# --- market 3: resolver vanishes -> anyone voids after the deadline -> refunds ----------------------
M3 = 5003
call("create_market", CM(M3, 2, T0+300, T0+600, "Game C\nHome\nAway", "thesportsdb", "ev3"), None, "ADMIN")
call("bet", [M3, 0], 250, "Z")
ck("deadline void: before deadline by non-resolver reverts", (lambda: (setattr(st, "cursor", T0+590), "revert" in call("void", [M3], None, "Z"))[-1])())
st.cursor = T0 + 620   # past the deadline
bz = bal("Z")
ck("deadline void: ANYONE can void now", "revert" not in call("void", [M3], None, "Z"))
call("claim", [M3], None, "Z")
ck("deadline void: refunded", bal("Z") == bz + 250)

# --- market 4: posted winner had ZERO backers -> auto-void -> refunds -------------------------------
M4 = 5004
st.cursor = T0 + 700
call("create_market", CM(M4, 3, T0+750, T0+900, "Game D\nH\nX\nA", "thesportsdb", "ev4"), None, "ADMIN")
call("bet", [M4, 0], 100, "X")
call("bet", [M4, 1], 100, "Y")     # nobody backs outcome 2
st.cursor = T0 + 760
bx, by = bal("X"), bal("Y")
call("resolve", [M4, 2], None, "ADMIN")   # outcome 2 won, but pool is empty
ck("auto-void: unbacked winner -> void not done", S("vd", M4) == 1 and S("dn", M4) == 0)
call("claim", [M4], None, "X"); call("claim", [M4], None, "Y")
ck("auto-void: everyone refunded", bal("X") == bx + 100 and bal("Y") == by + 100)

# --- market 5: a 2-of-3 resolver panel named at creation --------------------------------------------
M5 = 5005
st.cursor = T0 + 800
call("create_market", CM(M5, 2, T0+850, T0+1000, "Game E\nHome\nAway", "football-data", "ev5", thr=2, resolvers=("ADMIN", "O2", "O3")), None, "ADMIN")
ck("2-of-3: panel + threshold stored", S("mrc", M5) == 3 and S("mth", M5) == 2 and S("mres", f"{M5}|O2") == 1)
call("bet", [M5, 0], 1000, "X")
call("bet", [M5, 1], 1000, "Y")
st.cursor = T0 + 860
ck("2-of-3: a non-panel address can't resolve", "revert" in call("resolve", [M5, 0], None, "W"))
call("resolve", [M5, 0], None, "ADMIN")
ck("2-of-3: one vote does NOT finalize", S("dn", M5) == 0 and S("vc", f"{M5}|0") == 1)
ck("2-of-3: a resolver can't vote twice", "revert" in call("resolve", [M5, 0], None, "ADMIN"))
call("resolve", [M5, 0], None, "O2")
ck("2-of-3: second matching vote finalizes", S("dn", M5) == 1 and S("rs", M5) == 1)
bx = bal("X")
call("claim", [M5], None, "X")
ck("2-of-3: winner X takes the pool", bal("X") == bx + 1000*2000//1000)

# disagreeing votes never reach threshold on any single outcome
M6 = 5006
call("create_market", CM(M6, 2, T0+900, T0+1100, "Game F\nHome\nAway", "football-data", "ev6", thr=2, resolvers=("ADMIN", "O2", "O3")), None, "ADMIN")
call("bet", [M6, 0], 500, "X"); call("bet", [M6, 1], 500, "Y")
st.cursor = T0 + 910
call("resolve", [M6, 0], None, "ADMIN")   # votes 0
call("resolve", [M6, 1], None, "O2")      # votes 1 -> split 1/1, neither hits 2
ck("2-of-3: split votes do not finalize", S("dn", M6) == 0 and S("vd", M6) == 0)
call("resolve", [M6, 0], None, "O3")      # 0 now has 2 votes -> finalize outcome 0
ck("2-of-3: tie broken by third vote", S("dn", M6) == 1 and S("rs", M6) == 1)

# --- LEGACY fallback: a market from the OLD contract (no per-market resolver set) is admin-resolved --
# (mirrors the markets created before this upgrade — mrc/mres absent; the admin resolves them.)
LEG = 6001
put = lambda mp, k, v: st.contracts[CID]["storage"].setdefault(mp, {}).__setitem__(str(k), v)
put("mk", LEG, 1); put("no", LEG, 2); put("lk", LEG, T0); put("dl", LEG, T0 + 9999)
put("pl", f"{LEG}|0", 100); put("tot", LEG, 100); put("stk", f"{LEG}|0|X", 100); put("us", f"{LEG}|X", 100)
ck("legacy: a non-admin can't resolve a resolver-less market", "revert" in call("resolve", [LEG, 0], None, "Y"))
call("resolve", [LEG, 0], None, "ADMIN")
ck("legacy: the admin resolves it (mrc==0 fallback)", S("dn", LEG) == 1 and S("rs", LEG) == 1)
bxl = bal("X")
call("claim", [LEG], None, "X")
ck("legacy: winner paid", bal("X") == bxl + 100*100//100)

print("\n" + ("ALL PASS" if not F else f"{len(F)} FAILED: {F}"))
if not F:
    outp = os.path.join(os.path.dirname(__file__), "..", "execnode", "contracts", "bet.json")
    if os.environ.get("WRITE"):
        json.dump(CODE, open(outp, "w")); print("WROTE", outp)
    else:
        committed = json.load(open(outp)) if os.path.exists(outp) else None
        assert committed == CODE, "execnode/contracts/bet.json is STALE — re-run with WRITE=1 to regenerate"
        print("committed bet.json matches the assembled contract")
sys.exit(1 if F else 0)
